"""압축 엔진 — 세션 1개의 압축 상태와 사다리 실행. 실패 분류도 여기 산다.

가드(안티스래시·쿨다운·무효 압축 정지)가 이 모듈의 본론이다. 아래 계층은 전부 순수
계산이고, 언제 그것을 부를지와 실패했을 때 무엇을 지킬지는 여기서만 정한다."""

from __future__ import annotations

import time

from .align import _align_head_end, _align_tail_start, _is_real_user_turn
from .handoff import _handoff_pair, extract_handoff
from .pairs import sanitize_tool_pairs
from .policy import CompressPolicy
from .prune import _prunable_end, hygiene_and_prune
from .server import has_compaction_block, server_side_kwargs
from .text import _message_text, _redact, build_prompt, serialize_turns
from .tokens import _role, estimate_tokens

_COOLDOWN_SECONDS = 600  # 요약 실패 후 재시도 금지 구간
_INEFFECTIVE_LIMIT = 2  # 연속 무효 압축 횟수 — 초과 시 세션 내 자동 요약 정지
_MIN_SAVINGS_PCT = 10.0  # 이만큼도 못 줄이면 무효 압축


def classify_failure(exc: BaseException) -> str:
    """auth / network / other — 앞의 둘은 재시도가 답이지 중간 구간을 태울 이유가 아니다."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in {401, 403}:
        return "auth"
    name = type(exc).__name__.lower()
    text = f"{exc}".lower()
    if any(k in name for k in ("connect", "timeout", "network", "apiconnection")):
        return "network"
    if any(k in text for k in ("connection", "timed out", "timeout", "temporarily unavailable")):
        return "network"
    if any(k in text for k in ("unauthorized", "forbidden", "invalid api key", "authentication")):
        return "auth"
    return "other"


class Huginn:
    """세션 1개의 압축 상태. 가드(안티스래시·쿨다운)는 여기 산다.

    call은 (prompt, max_tokens) -> str 인 요약 호출자다. 세션이 트랜스포트를 알고 주입한다 —
    이 클래스는 와이어를 모른다 (테스트가 가짜 호출자를 꽂을 수 있는 이유)."""

    def __init__(self, root: str, window: int, pol: CompressPolicy, call=None, now=time.monotonic, session_id=""):
        self.root, self.window, self.policy, self.call, self._now = root, max(1, window), pol, call, now
        self.session_id = session_id
        self.compressions = 0
        self.prunes = 0
        self.archived = 0  # T4 — 보관소로 내려보낸 방출 행 수
        self.server_compactions = 0  # T3 — provider가 수행한 압축 횟수
        self._ineffective = 0
        self._cooldown_until = 0.0
        self._summary_disabled = False
        self._awaiting_usage = False
        self._announced: set[str] = set()  # 차단 사유는 한 번만 알린다 — 매 턴 같은 경고는 소음이다
        self._redo = None  # ACON — 압축 직후 재작업 감시창
        self.last_event: dict = {}

    # -- 발동 판정 --------------------------------------------------------
    @property
    def prune_tokens(self) -> int:
        return int(self.window * self.policy.prune_at)

    @property
    def summary_tokens(self) -> int:
        return int(self.window * self.policy.summary_at)

    def effective_tail_tokens(self) -> int:
        """보호 tail이 창의 1/4을 넘으면 압축할 중간 구간이 남지 않아 매 턴 무효 압축이 돈다."""
        return max(1_000, min(self.policy.tail_tokens, self.window // 4))

    def summary_blocked(self) -> str:
        if self.policy.mode != "full":
            return "mode"
        if self.call is None:
            return "no_caller"
        if self._summary_disabled:
            return "ineffective"
        if self._now() < self._cooldown_until:
            return "cooldown"
        if self._awaiting_usage:
            return "awaiting_usage"
        return ""

    def note_usage(self, context_tokens: int) -> None:
        """실측 사용량 도착 — 압축 직후 추정치로 재발동하는 스래싱을 여기서 끊는다."""
        if context_tokens > 0:
            self._awaiting_usage = False

    # -- 본체 ------------------------------------------------------------
    def compress(self, messages: list, context_tokens: int) -> tuple[list, dict]:
        """(새 메시지 목록, 사건 dict). 사건이 비어 있으면 아무 일도 없었다는 뜻."""
        if self.policy.mode == "off" or not messages or context_tokens < self.prune_tokens:
            return messages, {}
        tail = self.effective_tail_tokens()

        out, event = hygiene_and_prune(messages, tail_tokens=tail, min_recovery_tokens=self.policy.min_recovery_tokens)
        recovered = bool(event.get("recovered"))
        if recovered:
            self.prunes += 1
            event = {**event, "tier": "prune"}
        else:
            out = messages  # 회수 0 이면 원본 객체 그대로 — 호출자가 동일성으로 무개입을 확인할 수 있다

        # 사다리의 요점 — 위 단이 임계를 제거했으면 아래 단은 안 간다. 실측 보고값과 프룬 후
        # 추정치 둘 다 봐야 한다: 보고값은 프룬을 반영하지 못한 직전 호출의 값이다.
        if context_tokens < self.summary_tokens or estimate_tokens(out) < self.summary_tokens:
            return self._finish(out, event if recovered else {})

        blocked = self.summary_blocked()
        if blocked:
            if blocked not in self._announced:
                self._announced.add(blocked)
                event = {**event, "blocked": blocked}
            return self._finish(out, event if recovered or event.get("blocked") else {})

        summarized, sevent = self._summarize(out, tail)
        return self._finish(summarized, {**event, **sevent})

    def _finish(self, messages: list, event: dict) -> tuple[list, dict]:
        self.last_event = event
        self._journal(event)
        return messages, event

    def _summarize(self, messages: list, tail_tokens: int) -> tuple[list, dict]:
        call = self.call
        if call is None:  # summary_blocked()가 이미 걸렀지만 계약은 여기서도 닫는다
            return messages, {"tier": "summary", "failure": "no_caller"}
        before = estimate_tokens(messages)
        previous, working = extract_handoff(messages)

        head_end = _align_head_end(working, self.policy.protect_first_n)
        raw_tail = _prunable_end(working, tail_tokens, min_keep=2)
        tail_start = _align_tail_start(working, raw_tail, head_end)
        if tail_start < 0 or tail_start <= head_end:
            self._record_ineffective("no_summary_window")
            return messages, {"tier": "summary", "failure": "no_summary_window"}

        middle = working[head_end:tail_start]
        if not middle:
            self._record_ineffective("empty_window")
            return messages, {"tier": "summary", "failure": "empty_window"}

        turns = serialize_turns(middle)
        if not turns.strip() and not previous:
            self._record_ineffective("nothing_to_summarize")
            return messages, {"tier": "summary", "failure": "nothing_to_summarize"}

        t0 = self._now()
        try:
            body = (
                call(build_prompt(turns, previous, self._lesson_block()), self.policy.summary_max_tokens) or ""
            ).strip()
        except Exception as exc:  # noqa: BLE001 — 분류해서 전부 fail-open 처리한다
            kind = classify_failure(exc)
            # auth·network 실패로 중간 구간을 태우는 건 압축이 아니라 파손이다. 원본을 지키고 물러난다.
            self._cooldown_until = self._now() + _COOLDOWN_SECONDS
            return messages, {
                "tier": "summary",
                "failure": kind,
                "error": str(exc)[:200],
                "aborted": True,
            }
        duration_ms = int((self._now() - t0) * 1000)
        if not body:
            self._cooldown_until = self._now() + _COOLDOWN_SECONDS
            return messages, {"tier": "summary", "failure": "empty_summary", "aborted": True}

        rebuilt = sanitize_tool_pairs(working[:head_end] + _handoff_pair(_redact(body)) + working[tail_start:])
        after = estimate_tokens(rebuilt)
        savings = 100.0 * (before - after) / before if before else 0.0
        if savings < _MIN_SAVINGS_PCT:
            # 요약이 원문만큼 크다 — 캐시만 날리고 얻은 게 없다. 원본을 지키고 카운트한다.
            self._record_ineffective("low_savings")
            return messages, {
                "tier": "summary",
                "failure": "low_savings",
                "savings_pct": round(savings, 1),
                "aborted": True,
            }

        self.compressions += 1
        self._ineffective = 0
        self._awaiting_usage = True
        event = {
            "tier": "summary",
            "before_tokens": before,
            "after_tokens": after,
            "savings_pct": round(savings, 1),
            "summarized": len(middle),
            "head": head_end,
            "tail": len(working) - tail_start,
            "iterative": bool(previous),
            "duration_ms": duration_ms,
        }
        # T4 — 잘라낸 구간은 태우지 않고 보관소로 내려보낸다 (context_recall로 되짚기).
        archived = self._archive(middle)
        if archived:
            event["archived"] = archived
        # ACON — 산출물 구조 비평 + 재작업 감시창 개시. 둘 다 결정론, 추가 LLM 호출 없음.
        self._learn(body, middle)
        return rebuilt, event

    # -- T4 보관소 --------------------------------------------------------
    def _archive(self, middle: list) -> int:
        if not self.policy.vault:
            return 0
        try:
            from ..evicted import archive

            rows = [(_role(m) or "unknown", _redact(_message_text(m))) for m in middle]
            written = archive(self.root, [r for r in rows if r[1]], session_id=self.session_id)
            self.archived += written
            return written
        except Exception:
            return 0  # fail-open — 보관 실패가 압축을 되돌릴 이유는 아니다

    # -- ACON 교훈 --------------------------------------------------------
    def _lesson_block(self) -> str:
        if not self.policy.lessons:
            return ""
        try:
            from ..compact_lessons import guideline_block

            return guideline_block(self.root)
        except Exception:
            return ""

    def _learn(self, body: str, middle: list) -> None:
        if not self.policy.lessons:
            return
        try:
            from ..compact_lessons import RedoWatch, call_keys, critique, record

            faults = critique(
                body,
                has_user_turn=any(_is_real_user_turn(m) for m in middle),
                budget_tokens=self.policy.summary_max_tokens,
            )
            if faults:
                record(self.root, faults)
            self._redo = RedoWatch(call_keys(middle))
        except Exception:
            self._redo = None

    def observe_turn(self, messages: list) -> bool:
        """압축 직후 턴 관찰 — 방출된 호출을 그대로 다시 했으면 교훈으로 적립한다.

        '이미 한 일을 또 했다'가 압축 손실의 가장 정직한 관측 신호다. 감시창은 몇 턴 뒤
        스스로 닫힌다 — 압축과 무관한 정상 재읽기까지 세면 지침이 오염된다."""
        watch = self._redo
        if watch is None or not getattr(watch, "active", False):
            return False
        try:
            if not watch.observe(messages):
                return False
            from ..compact_lessons import record

            record(self.root, ["redone_work"])
            self._journal({"tier": "lesson", "lesson": "redone_work"})
            return True
        except Exception:
            return False

    # -- T3 서버측 --------------------------------------------------------
    def server_kwargs(self) -> dict:
        """anthropic 요청에 얹을 서버측 압축 필드 — 미사용/미지원이면 빈 dict."""
        if self.policy.mode == "off":
            return {}
        try:
            return server_side_kwargs(self.policy, self.window)
        except Exception:
            return {}

    def note_server_compaction(self, content: object) -> bool:
        """응답에 compaction 블록이 있었으면 계측한다 — provider가 우리 대신 압축한 것."""
        try:
            if not has_compaction_block(content):
                return False
        except Exception:
            return False
        self.server_compactions += 1
        self._awaiting_usage = True  # 서버측 압축 직후도 추정치 재발동을 막는다
        self._journal({"tier": "server", "server_compactions": self.server_compactions})
        return True

    def _record_ineffective(self, reason: str) -> None:
        self._ineffective += 1
        if self._ineffective >= _INEFFECTIVE_LIMIT:
            # 줄지 않는 압축을 매 턴 재시도하면 세션이 멈춘 것처럼 보인다 — 자동 요약을 끈다.
            self._summary_disabled = True

    def _journal(self, event: dict) -> None:
        if not event:
            return
        try:
            from ...io_journal import note

            note(self.root, "compact", {k: v for k, v in event.items() if v not in ("", None)})
        except Exception:
            pass  # fail-open — 계측이 실행을 인질로 잡지 않는다
