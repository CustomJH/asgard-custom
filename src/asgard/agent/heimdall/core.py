"""Heimdall 오케스트레이터 코어 — 세션·모델 관리 + 요청 라우팅 (DIRECT / Trinity).

Odin 요청 → [분류] → DIRECT (write 없음, 무세금)
                  → Trinity: TrinityRun 상태기계 (trinity 모듈) — 퀘스트 로그 open →
                    매 턴 전이 함수(quest-log next, 결정론) → 역할 세션(child context) →
                    퀘스트 로그 기록(하니스가 결정론 수행) → Verifier verdict 툴 →
                    게이트(verifier-gate, 루프 종료 지점) → close

협력자 구성: DeliveryDispatch(딜리버리 위임·편대), WaveRunner(배정 단위 wave 실행),
TrinityRun(퀘스트 순환). Heimdall 은 provider/세션/모델/메모리 표면과 라우팅만 진다 —
기존 테스트·호출자가 쓰는 `_dispatch_handler` 류 메서드는 협력자 위임 파사드로 유지한다.
"""

from __future__ import annotations

import json
import random
import threading
import time
import uuid
from typing import Callable, Protocol

from ...providers import ResolvedProvider, resolve_trinity
from ..session import AgentSession, SessionResult, TurnCancelled, make_client, ql
from .classify import _DESTRUCTIVE_PAT, _PARALLEL_WORK_PAT, _pred_fields, classify_api_error, classify_heuristic
from .dispatch import DeliveryDispatch, _freyja_gate_rejection, _safe_candidates
from .journal import _log_classify
from .planning import _resume_snapshot
from .roles import (
    _DELIVERY_TIERS,
    _EXPLORE_NUDGE_MIN,
    _TIER_MODELS,
    _TIER_UP,
    _identity,
    _mimir_note,
    _model_tier,
    _skill_support,
)
from .trinity import TrinityRun
from .waves import WaveRunner


class SessionLike(Protocol):
    """_run_turn 이 요구하는 표면 — run() 하나. 테스트 대역(FakeSession)이 AgentSession 상속 없이 만족."""

    def run(self, user_content: str) -> SessionResult: ...


class Heimdall:
    def __init__(
        self,
        rp: ResolvedProvider,
        root: str,
        on_text: Callable[[str], None],
        on_status: Callable[[str | None], None] | None = None,
    ):
        self.rp, self.root, self.on_text = rp, root, on_text
        self.on_status = on_status or (lambda s: None)
        self._state_lock = threading.Lock()  # wave 병렬 스레드의 _clients/total_tokens 변이 보호
        self._session_seq = 0
        self._sessions: dict[str, dict] = {}
        # 턴 단위 협조 취소 — 모든 자식 AgentSession 이 이 이벤트를 공유 (handle() 진입 시 clear)
        self.cancel_event = threading.Event()
        self._clients: dict[tuple, object] = {}  # (provider, base_url, key_source) → SDK 클라이언트
        self.client = self._client_for(rp)
        # 역할별 provider 배치 ([trinity.<role>]) — 미충족은 기본 provider 로 fail-open + 경고 1회
        from ...providers import TRINITY_EXTRA_ROLES, TRINITY_ROLES

        self.role_rp: dict[str, ResolvedProvider] = {}
        roles = TRINITY_ROLES + TRINITY_EXTRA_ROLES + tuple(_DELIVERY_TIERS)
        for role, rrp in resolve_trinity(root, rp, roles).items():
            if rrp is not rp and rrp.missing:
                on_text(f"⚠ [trinity.{role}] 미충족({'; '.join(rrp.missing)}) — 기본 provider 사용\n")
                rrp = rp
            self.role_rp[role] = rrp
        # trinity-policy.json — roles tier/effort·budget_priors·delivery 티어 소비
        from ...hooks.quest_log import active_quest, load_policy

        self.policy = load_policy(root)
        # Lagom — 세션 생성 시점 모드로 렌더 (off = 빈 문자열, 프롬프트 무변화).
        # REPL /lagom 전환은 _Reconfigure 로 Heimdall 을 재생성해 여기로 다시 온다.
        from ...lagom import note as _lagom_note

        self.lagom = _lagom_note(root)
        # Charter (프로젝트 북극성) — through-line 은 identity 로(설계①, 모든 역할·DIRECT 관통),
        # coherence 는 Thinker/Verifier 프롬프트에 역할별로(협업②/판단③). 미설정이면 전부 빈 문자열.
        from ...charter import note as _charter_note

        self._charter_note = _charter_note
        self.charter_identity = _charter_note(root, "identity")
        # 개인 메모리 동결 스냅샷 (memory v3 P1) — 세션 생성 시 1회 렌더
        # (세션 중 메모리가 바뀌어도 프롬프트 불변 = KV 캐시·재현성 보존).
        # 주입 매트릭스: DIRECT(identity)·호출된 Thinker = 스냅샷+회수. standard Worker는
        # 요청 관련 개인 회수만 받고, deep Worker는 개인 메모리를 받지 않는다.
        # Verifier/딜리버리(loki 포함)는 영구 무주입.
        # provider 게이트: inject_allowed — 킬스위치 + [memory].providers allowlist.
        from ...memory import inject_allowed as _mem_allowed
        from ...memory import snapshot_note as _memory_note

        self._memory_snap = _memory_note()  # 동결 원본 — 역할별 게이트는 아래에서
        self._mem_allowed = _mem_allowed
        self._memory_provider_allowed = _mem_allowed(rp.profile.name, rp.source)
        self.memory_note = self._memory_snap if self._memory_provider_allowed else ""
        # delivery_identity = 메모리 무주입 — 딜리버리 자식(freyja/thor/eitri/loki)은 코디네이터가 아니다.
        # 특히 loki 는 Verifier 의 반례 탐색자라 메모리 유입 = 게이트 무결성 훼손.
        self.delivery_identity = _identity(root) + self.lagom + self.charter_identity
        self.identity = self.delivery_identity + self.memory_note
        self.total_tokens = 0  # 세션 누적 지출 (status line 사용량)
        self.last_context_tokens = 0  # 마지막 역할 턴의 컨텍스트 크기 — status line 창 % 용
        # 프롬프트 캐시 계측 (누적) — 적중률 = read / (read+write+uncached), status line ⚡ 표시
        self.cache_read_tokens = 0
        self.cache_prompt_tokens = 0
        # DIRECT는 REPL 이중 출력을 피하려고 handle()에서 빈 문자열 sentinel을 반환한다.
        # headless JSON 호출자는 실제 최종 응답을 이 필드에서 회수한다.
        self.last_response_text = ""
        self.history: list[tuple[str, str]] = []  # REPL 턴 간 (요청, 응답 요약) — DIRECT 후속 질문 맥락
        self._memory_session_id = f"native-{uuid.uuid4().hex}"
        self._memory_turn_seq = 0
        self._last_completion: dict | None = None
        self._explore_cmds = 0  # 직전 DIRECT 턴의 탐색 커맨드 수 — 증류 넛지 문턱 판정용
        self._sleep: Callable[[float], None] = time.sleep  # 재시도 백오프 — 테스트 주입점
        # 협력자 — 딜리버리 위임·편대(dispatch), 배정 단위 wave 실행(waves)
        self._dispatchers = DeliveryDispatch(self)
        self._waves = WaveRunner(self)
        dangling = active_quest(root)
        if dangling:  # 이전 세션 중단으로 남은 ACTIVE 퀘스트 — 조용히 덮지 않는다
            on_text(f"⚠ 미완 퀘스트 발견({dangling}) — 이전 세션 중단 흔적. 이어서 검증하거나 quest-log close 필요.\n")

    def _client_for(self, rp: ResolvedProvider):
        key = (rp.profile.name, rp.base_url, rp.key_source)
        with self._state_lock:
            if key not in self._clients:
                self._clients[key] = make_client(rp)
            return self._clients[key]

    def _add_tokens(self, n: int) -> None:
        with self._state_lock:
            self.total_tokens += n

    def _session_observer(self, role: str) -> tuple[Callable[[str | None], None], Callable[[str, str], None]]:
        with self._state_lock:
            self._session_seq += 1
            sid = f"{role}-{self._session_seq}"
            self._sessions[sid] = {
                "id": sid,
                "role": role,
                "state": "ready",
                "status": "",
                "started": 0.0,
                "ended": 0.0,
            }

        def emit() -> None:
            rows = self.session_snapshot(active_only=True)
            if not rows:
                self.on_status(None)
                return
            row = rows[-1]
            label = row["role"] + (f" · {row['status']}" if row["status"] else "")
            if len(rows) > 1:
                label += f" · +{len(rows) - 1}"
            self.on_status(label)

        def status(label: str | None) -> None:
            with self._state_lock:
                row = self._sessions[sid]
                if row["state"] == "running":
                    row["status"] = label or ""
            emit()

        def lifecycle(event: str, detail: str) -> None:
            now = time.monotonic()
            with self._state_lock:
                row = self._sessions[sid]
                if event == "running":
                    row.update(state="running", status="", started=now)
                else:
                    state = detail if detail in {"cancelled", "failed"} else "done"
                    row.update(state=state, status="", result=detail, ended=now)
                if len(self._sessions) > 32:
                    for old_id, old in list(self._sessions.items()):
                        if old["state"] != "running" and old_id != sid:
                            del self._sessions[old_id]
                            break
            emit()

        return status, lifecycle

    def session_snapshot(self, active_only: bool = False) -> list[dict]:
        """Thread-safe child-session view for the terminal; no model state or prompts leak."""
        now = time.monotonic()
        with self._state_lock:
            rows = [dict(row) for row in self._sessions.values() if not active_only or row["state"] == "running"]
        for row in rows:
            if row["started"]:
                row["elapsed_s"] = round((row["ended"] or now) - row["started"], 1)
            else:
                row["elapsed_s"] = 0.0
        return rows

    def _session(
        self,
        system: str,
        extra_tools=None,
        handlers=None,
        quiet=False,
        role: str | None = None,
        model: str | None = None,
        readonly: bool = False,
        rp_override: ResolvedProvider | None = None,
        cwd: str | None = None,
    ) -> AgentSession:
        session_status, lifecycle = self._session_observer(role or ("readonly" if readonly else "legacy"))
        rp = rp_override or self.role_rp.get(role or "", self.rp)
        if model and model != rp.model:  # 상황별 모델 스왑 — provider 는 유지, 모델만
            from dataclasses import replace

            rp = replace(rp, model=model)
        return AgentSession(
            self._client_for(rp),
            rp,
            self.root,
            system,
            extra_tools=extra_tools,
            tool_handlers=handlers,
            on_text=(lambda s: None) if quiet else self.on_text,
            on_tokens=self._add_tokens,
            on_status=session_status,
            readonly=readonly,
            role=role,
            cwd=cwd,
            cancel_event=self.cancel_event,
            on_lifecycle=lifecycle,
        )

    def _model_for(self, role_key: str, bump: bool = False) -> str | None:
        """정책 tier → 상황별 모델. None = 스왑 없음 (해당 세션 rp.model 그대로).

        존중 규칙: ① 역할에 명시 placement 가 있으면 그 모델 ② 기본 provider 가 anthropic 이
        아니면 티어 매핑 불가 ③ 알려지지 않은 커스텀 모델은 그 선택 유지.
        티어 하한 = 코디네이터: 정책 티어가 세션 모델 티어보다 낮으면 세션 티어로 올린다 —
        더 싼 손이 필요하면 ① placement 로 명시한다.
        bump = 상황 승급 (full-verify·재계획 2회+) — 티어 사다리 한 칸 위 (high→max=fable)."""
        rp = self.role_rp.get(role_key, self.rp)
        if rp is not self.rp:
            return None  # 명시 placement 존중
        # claude_cli 도 티어 매핑 가능 — CLI 가 full 모델 ID 를 그대로 해석한다
        if rp.profile.api_mode not in ("anthropic", "claude_cli"):
            return None
        tier = str((self.policy.get("roles", {}).get(role_key) or {}).get("tier", "standard"))
        # 코디네이터 티어 하한 — 위임된 실행·판정 손이 세션 모델보다 약하면 그 손이 품질 하한이
        # 된다 (숨은 caller 추적처럼 코디네이터는 하는 일을 못 한다). 정책이 명시한 티어라도
        # 코디네이터 아래로는 내리지 않는다; 역매핑 불가 모델(커스텀 ID)은 하한 미적용.
        order = list(_TIER_MODELS)
        coord = _model_tier(rp.model)
        if coord is None:
            return None
        if coord and tier in order and order.index(coord) > order.index(tier):
            tier = coord
        if bump:
            tier = _TIER_UP.get(tier, tier)
        return _TIER_MODELS.get(tier)

    def _delivery_model(self, agent: str) -> str | None:
        """딜리버리 전문가 모델 — 정책 "delivery" 티어 (기본: freyja/thor/eitri=sonnet, loki=haiku)."""
        rp = self.role_rp.get(agent, self.rp)
        if rp is not self.rp:  # 명시 placement 존중
            return None
        if rp.profile.api_mode not in ("anthropic", "claude_cli"):
            return None
        tier = str((self.policy.get("delivery") or {}).get(agent, _DELIVERY_TIERS.get(agent, "standard")))
        coord = _model_tier(rp.model)
        if coord is None:
            return None
        # Loki는 의도된 저비용 반례 정찰. 실제 산출을 만드는 나머지 손만 코디네이터 하한 적용.
        order = list(_TIER_MODELS)
        if agent != "loki" and tier in order and order.index(coord) > order.index(tier):
            tier = coord
        return _TIER_MODELS.get(tier)

    def _classify(self, request: str) -> dict:
        # 1차 결정론 휴리스틱 (LLM 토큰 0) — 명백 케이스만. 모호하면 LLM 폴백.
        d = classify_heuristic(request)
        if d is not None:
            _log_classify(self.root, {"event": "classify", "source": "heuristic", **_pred_fields(d)})
            return d
        # structured-output 강제 대신 "JSON 만 출력" + 관대한 파싱 — 두 트랜스포트(및 nemotron 류
        # JSON-mode 불확실 모델) 공통. 파싱 실패는 안전 기본값(write 로 간주 → 게이트가 잡는다).
        sysmsg = (
            "과업 분류기. 요청을 읽고 아래 JSON 만 출력한다 (설명 금지, JSON 앞뒤 텍스트 금지). "
            "write_expected = 파일을 생성·수정해야 하는 과업이면 true. "
            "**질문·계산·설명·조회처럼 답만 하면 되는 것은 false** (예: '1+1?', '이 함수 설명해'). "
            "criteria 는 write 과업일 때만, 명령으로 확인 가능한 형태로. "
            "task_class = trivial(파일 1개 소형)|standard|deep(멀티파일·리팩터·리스크). "
            '{"write_expected":bool,"ambiguous":bool,"destructive":bool,'
            '"external_research":bool,"shared":bool,"criteria":[str],"task_class":str}'
        )
        try:
            raw = self._complete_text(sysmsg, request, max_tokens=2000)
            s = raw[raw.index("{") : raw.rindex("}") + 1]
            d = json.loads(s)
            for k in ("write_expected", "ambiguous", "destructive", "external_research", "shared"):
                d[k] = bool(d.get(k))
            d["criteria"] = [str(c) for c in (d.get("criteria") or [])]
            d["parallel_requested"] = bool(d["write_expected"] and _PARALLEL_WORK_PAT.search(request.lower()))
            if d.get("task_class") not in ("trivial", "standard", "deep"):
                d["task_class"] = "standard"
            _log_classify(self.root, {"event": "classify", "source": "llm", **_pred_fields(d)})
            return d
        except Exception:
            d = {
                "write_expected": True,
                "ambiguous": True,
                "destructive": bool(_DESTRUCTIVE_PAT.search(request.lower())),
                "external_research": False,
                "shared": False,
                "parallel_requested": bool(_PARALLEL_WORK_PAT.search(request.lower())),
                "criteria": [],
                "task_class": "deep",  # 파싱 실패 = 미상 — 최대 예산으로 안전하게
            }
            _log_classify(self.root, {"event": "classify", "source": "fallback", **_pred_fields(d)})
            return d

    def _complete_text(self, system: str, user: str, max_tokens: int = 2000) -> str:
        """비스트리밍 단발 completion — 트랜스포트 무관 (classify 등 내부 판단용).
        [trinity.classify] placement 가 있으면 그 provider/모델 사용 (저비용 분류)."""
        rp = self.role_rp.get("classify", self.rp)
        client = self._client_for(rp)
        if rp.profile.api_mode == "claude_cli":
            from ..claude_native import complete_text

            return complete_text(system, user, model=rp.model, root=self.root)
        if rp.profile.api_mode == "anthropic":
            resp = client.messages.create(
                model=rp.model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}]
            )
            return "".join(b.text for b in resp.content if b.type == "text")
        if rp.profile.api_mode in {"openai_responses", "codex_responses"}:
            kwargs: dict[str, object] = dict(
                model=rp.model,
                instructions=system,
                input=user,
                timeout=120.0,
            )
            if rp.profile.api_mode == "codex_responses":
                kwargs["store"] = False
            else:
                kwargs["max_output_tokens"] = max(4096, max_tokens)
            if rp.model.startswith(("gpt-5", "o1", "o3", "o4")):
                kwargs["reasoning"] = {"effort": "low"}
            resp = client.responses.create(**kwargs)
            return resp.output_text or ""
        resp = client.chat.completions.create(
            model=rp.model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""

    def _run_turn(
        self,
        make: Callable[[], SessionLike],
        prompt: str,
        fallback: Callable[[], SessionLike] | None = None,
        fallback_prompt: str | None = None,
    ):
        """역할 턴 실행 + 오류 회복 — retryable 은 jittered backoff ≤2회 재시도,
        소진 시 placement 폴백 1회 (기본 provider), fatal 은 즉시 표면화."""
        delay = 2.0
        for attempt in range(3):
            try:
                r = make().run(prompt)
                if getattr(r, "stop_reason", "") == "cancelled":
                    raise TurnCancelled()
                self.last_context_tokens = getattr(r, "context_tokens", 0) or self.last_context_tokens
                self._track_cache(r)
                return r
            except TurnCancelled:
                raise  # 취소는 재시도·폴백 대상이 아니다
            except Exception as e:
                if classify_api_error(e) != "retryable" or attempt == 2:
                    if fallback is not None:
                        self.on_text(f"⚠ provider 오류({e.__class__.__name__}) — 기본 provider 폴백 1회\n")
                        r = fallback().run(prompt if fallback_prompt is None else fallback_prompt)
                        if getattr(r, "stop_reason", "") == "cancelled":
                            raise TurnCancelled()
                        self._track_cache(r)
                        return r
                    raise
                self.on_text(f"⚠ provider 일시 오류({e.__class__.__name__}) — {delay:.0f}s 후 재시도\n")
                self._sleep(delay + random.uniform(0, delay / 2))
                delay = min(delay * 2, 30.0)
        raise RuntimeError("unreachable")

    def _learned_note(self, task: str, agent: str, quiet: bool = False) -> str:
        """learned 스킬 주입 노트 (skill_bank, CUS-252) — 승인된 경험 지식의 advisory 층.

        Verifier/loki 호출측은 이 함수를 부르지 않는다 (게이트 무결성 — 학습물은 판정 표면 금지).
        실패는 조용히 빈 문자열 (fail-open — 스킬 뱅크 문제로 본 작업이 죽으면 안 된다)."""
        try:
            from ... import ui  # 로컬 임포트 — WIP 커밋 순서와 무관하게 자립 (모듈 임포트와 공존 무해)
            from ...skill_bank import record_use, resolve_learned

            hits = resolve_learned(self.root, task, agent)
            if not hits:
                return ""
            record_use(self.root, [n for n, _ in hits])
            if not quiet:
                self.on_text(f"  {ui.dim('│ ✦ 학습 스킬 — ' + ', '.join(n for n, _ in hits))}\n")
            return "\n\n# 학습 스킬 (승인된 과거 경험 — advisory, 게이트 증거 아님)\n\n" + "\n\n".join(
                b for _, b in hits
            )
        except Exception:
            return ""

    def _track_cache(self, r) -> None:
        """프롬프트 캐시 계측 집계 — 세션 결과의 read/write/uncached 를 누적 (스레드 안전, wave 병렬)."""
        cr = getattr(r, "cache_read_tokens", 0) or 0
        total = cr + (getattr(r, "cache_write_tokens", 0) or 0) + (getattr(r, "uncached_input_tokens", 0) or 0)
        if total:
            with self._state_lock:
                self.cache_read_tokens += cr
                self.cache_prompt_tokens += total

    # ── 딜리버리 디스패치 파사드 (구현 = dispatch.DeliveryDispatch) ──
    _safe_candidates = staticmethod(_safe_candidates)
    _freyja_gate_rejection = staticmethod(_freyja_gate_rejection)

    def _freyja_squad_handler(self, sid: str, worker_result_writes: list[str], cwd: str | None = None):
        return self._dispatchers.freyja_squad_handler(sid, worker_result_writes, cwd)

    def _freyja_verdict_handler(self, sid: str, worker_result_writes: list[str], cwd: str, verdict_state: dict):
        return self._dispatchers.visual_verdict_handler(sid, worker_result_writes, cwd, verdict_state)

    def _thor_squad_handler(self, sid: str, worker_result_writes: list[str], cwd: str | None = None):
        return self._dispatchers.thor_squad_handler(sid, worker_result_writes, cwd)

    def _dispatch_handler(self, sid: str, worker_result_writes: list[str], cwd: str | None = None):
        return self._dispatchers.dispatch_handler(sid, worker_result_writes, cwd)

    def _reject_freyja_final(self, sid: str, reason: str) -> str:
        return self._dispatchers.reject_freyja_final(sid, reason)

    def _run_worker_waves(self, sid: str, request: str, units: list[dict], budget_note: str) -> None:
        return self._waves.run(sid, request, units, budget_note)

    def _record_outcome(self, task_class: str, result: str, saw_red: bool) -> None:
        """퀘스트 종결 → route-priors 카운트 + classify.jsonl 감사 (Bayesian-lite 데이터 축)."""
        from ...hooks.quest_log import update_priors

        _log_classify(
            self.root, {"event": "outcome", "task_class": task_class, "result": result, "baseline_red": saw_red}
        )
        update_priors(self.root, task_class, saw_red)

    def _escalate(self, sid: str) -> None:
        """ESCALATE 퀘스트 로그 기록 — verify 이벤트는 verdict 필수 (없으면 quest_log 가 거부, 조용히 유실)."""
        ql(
            self.root,
            "append",
            "--verdict",
            "ESCALATE",
            session=sid,
            stdin=json.dumps({"role": "verifier", "event": "verify"}),
        )

    def resume(self, qid: str | None = None) -> str:
        """Recover and continue one durable native Quest without replaying done tickets."""
        from ...hooks.quest_log import active_quest

        qid = qid or active_quest(self.root)
        if not qid:
            return "⚠ 재개할 ACTIVE Quest가 없습니다."
        recovered = ql(self.root, "ticket-recover", session=qid)
        if recovered.returncode != 0:
            detail = (recovered.stderr or recovered.stdout or "ticket recovery failed").strip()[:300]
            return f"⚠ Quest {qid} 복구 실패 — {detail}"
        snapshot = _resume_snapshot(self.root, qid)
        if snapshot["blocked"]:
            return f"⚠ Quest {qid} retry budget 소진 ticket: {snapshot['blocked']}"
        if snapshot["active"]:
            return f"⚠ Quest {qid}에 유효 lease의 active ticket이 있어 중복 실행하지 않습니다: {snapshot['active']}"
        request = snapshot["request"] or ("재개 Quest %s — %s" % (qid, "; ".join(snapshot["criteria"])))
        cls = {
            "task_class": "deep",
            "criteria": snapshot["criteria"] or [f"Quest {qid}의 기존 성공 기준 충족"],
            "parallel_requested": len(snapshot["units"]) + len(snapshot["completed"]) > 1,
            "ambiguous": False,
            "external_research": False,
            "shared": False,
        }
        return self._trinity(request, cls, resume_qid=qid, resume_units=snapshot["units"])

    # ── Trinity 순환 (구현 = trinity.TrinityRun) ──
    def _trinity(
        self,
        request: str,
        cls: dict,
        pre_work=None,
        standard: bool = False,
        pre_base_ref: str | None = None,
        resume_qid: str | None = None,
        resume_units: list[dict] | None = None,
    ) -> str:
        return TrinityRun(
            self,
            request,
            cls,
            pre_work=pre_work,
            standard=standard,
            pre_base_ref=pre_base_ref,
            resume_qid=resume_qid,
            resume_units=resume_units,
        ).run()

    def _final_report(self, qid: str, sid: str, gate_blocks: int) -> str:
        """퀘스트 로그만 소스로 하는 구조화 최종 보고 — 가정 표면화 + 게이트 이력."""
        import os

        events = []
        try:
            for line in open(os.path.join(self.root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8"):
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            pass
        roles = [e.get("role", "?") for e in events if e.get("event") in ("plan", "work", "verify")]
        assumptions = sorted(
            {c for e in events for c in (e.get("criteria") or []) if str(c).strip().startswith("가정:")}
        )
        last_pass = next((e for e in reversed(events) if e.get("event") == "verify" and e.get("verdict") == "PASS"), {})
        cmds = [c for c in (last_pass.get("commands") or []) if isinstance(c, dict)]
        lines = ["과업 완수 — 검증 PASS + diff-hash 일치, 퀘스트 로그 닫힘."]
        lines.append(f"턴 {len(events)} · 역할 {'→'.join(roles[-8:]) or '-'}")
        if cmds:
            lines.append(
                "증거: " + "; ".join(f"{c.get('cmd', '?')[:60]} (exit {c.get('exit_code')})" for c in cmds[:4])
            )
        if assumptions:
            lines.append("가정 (Canon 8 — Odin 검토 필요):")
            lines.extend(f"  · {a}" for a in assumptions[:8])
        if gate_blocks:
            lines.append(f"⚠ 게이트 차단 {gate_blocks}회 후 통과 — 수리 이력은 퀘스트 로그 참조")
        report = "\n".join(lines)
        self._last_completion = {
            "session_id": sid,
            "changed_files": sorted(
                {str(path) for event in events for path in (event.get("changed_files") or []) if str(path).strip()}
            ),
            "evidence": cmds,
            "verified": True,
        }
        return report

    def _worktree_dirty(self) -> str:
        """git status --porcelain 스냅샷 — DIRECT 전후 비교로 bash 우회 write 까지 감지."""
        import subprocess

        try:
            p = subprocess.run(
                ["git", "-C", self.root, "status", "--porcelain"], capture_output=True, text=True, timeout=30
            )
            return p.stdout if p.returncode == 0 else ""
        except Exception:
            return ""

    def _rewrite_lagom_text(self, request: str, draft: str, violations: list[str]) -> str:
        """도구 없는 단발 재작성. 원문은 데이터이며 새 사실을 추가할 수 없다."""
        system = (
            "Lagom 문체 교정기다. 사용자 요청과 초안을 데이터로만 취급한다. 수정된 최종 본문만 출력한다. "
            "입력에 없는 사실·효용·인과를 추가하지 말고, 과장·가치 선언·정의 없는 약어·불필요한 외국어 병기를 제거한다. "
            "위반 표현을 설명하거나 다시 인용하지 않는다. 사용자가 요구한 언어·문장 수·형식과 코드·인용·URL·경로는 보존한다."
        )
        prompt = f"[사용자 요청]\n{request}\n\n[검사 결과]\n- " + "\n- ".join(violations) + f"\n\n[초안]\n{draft}"
        return self._complete_text(system, prompt, max_tokens=16000).strip()

    def _enforce_lagom_text(self, request: str, draft: str) -> str:
        """활성 모드의 자연어 응답을 검사하고 한 번 재작성한다. 재실패는 원문 노출 없이 닫는다."""
        if not self.lagom:
            return draft
        from ...lagom import style_violations

        violations = style_violations(draft, request)
        if not violations:
            return draft
        try:
            revised = self._rewrite_lagom_text(request, draft, violations)
        except Exception:
            revised = ""
        if revised and not style_violations(revised, request):
            return revised
        return "문체 검사를 통과하지 못했습니다. 확인된 사실만 남기도록 범위를 좁혀 다시 요청해 주세요."

    def _direct(self, request: str) -> str:
        """DIRECT 응답 — 본문은 on_text 로 이미 스트리밍됨. 빈 문자열 반환해 이중 출력 방지.
        예외: refusal 안내는 스트림에 안 실린 합성 텍스트 — 그것만 반환.

        가드: classify 오판으로 DIRECT 세션이 파일을 쓰면 — editor writes 또는
        워킹트리 fingerprint 변화 — 소급 퀘스트를 열어 Verifier 판정 + 게이트를 강제한다.
        mode B 의 orphan-write 봉인의 네이티브 등가물 (native 엔 Stop 훅이 없다)."""
        from ...hooks.quest_log import snapshot_ref

        before = self._worktree_dirty()
        before_ref = snapshot_ref(self.root)
        # REPL 턴 간 대화 맥락 — 직전 문답 요약을 앞에 붙인다 (후속 질문 "그건 왜?" 가 성립하게).
        # Trinity 경로엔 안 붙인다 — write 과업은 요청+계획이 맥락의 전부여야 한다 (Canon 7 범위 존중).
        ctx = "".join(f"[이전 문답]\nOdin: {q}\n응답: {a}\n\n" for q, a in self.history[-3:])
        # 요청 기반 zero-LLM 회수 (감사 권고) — 카탈로그(identity)와 별개로 관련 페이지를 결정론 주입.
        recall = ""
        if self._memory_provider_allowed:
            from ...memory_context import recall_note as _recall

            recall = _recall(request, start=self.root)
        active_lagom = bool(self.lagom)
        # 활성 모드는 검사 전 초안이 터미널에 스트리밍되면 회수할 수 없다. 검사 완료까지 버퍼링한다.
        live_identity = self.delivery_identity + (self._memory_snap if self._memory_provider_allowed else "")
        mimir = _mimir_note(request)
        skill_note, skill_tools, skill_handlers = (
            _skill_support("mimir", self.root, include_learned=False) if mimir else ("", [], {})
        )
        r = self._session(
            live_identity + mimir + skill_note,
            extra_tools=skill_tools,
            handlers=skill_handlers,
            role="direct",
            readonly=True,
            quiet=active_lagom,
        ).run((ctx + request if ctx else request) + recall)
        if r.stop_reason == "cancelled":
            raise TurnCancelled()
        self.last_context_tokens = r.context_tokens or self.last_context_tokens
        self._track_cache(r)
        if r.writes or self._worktree_dirty() != before:
            _log_classify(self.root, {"event": "misroute", "route": "direct", "actual_write": True})
            self.on_text("\n⚠ DIRECT 분류였지만 write 감지 — 소급 검증 경로 진입 (Canon 10)\n")
            cls = {
                "write_expected": True,
                "ambiguous": False,
                "destructive": False,
                "external_research": False,
                "shared": False,
                "criteria": [],
                "task_class": "standard",
            }
            return self._trinity(request, cls, pre_work=r, pre_base_ref=before_ref)
        final = self._enforce_lagom_text(request, r.text)
        self._explore_cmds = len(r.commands)  # 탐색량 — _finalize_memory 증류 넛지 문턱 (순수 DIRECT 한정)
        self.last_response_text = final
        self.history = (self.history + [(request, final[:500])])[-6:]
        self._persist_turn(request, final)
        if active_lagom:
            self.on_text(final)
            return ""  # 검사된 본문을 방금 출력 — REPL 이중 출력 방지
        return final if r.stop_reason == "refusal" else ""

    # ── 진입점 ───────────────────────────────────────────────────────────
    def _finalize_memory(self, request: str, visible_response: str) -> str:
        """완성 turn 자동 retain + 검증된 write 과업의 승인 proposal + 탐색 발견 증류 넛지.
        모든 장애는 agent 실행에 fail-open."""
        out = visible_response
        response = visible_response or self.last_response_text
        try:
            from ...memory_bridge import find_config, is_backend_trusted
            from ...project_memory import propose_completion, retain_turn

            found = find_config(self.root)
            if found:
                root, cfg = found
                self._memory_turn_seq += 1
                if cfg.get("auto_retain_turns", False) and is_backend_trusted(cfg):
                    retain_turn(
                        root,
                        cfg,
                        session_id=self._memory_session_id,
                        turn_id=f"turn-{self._memory_turn_seq}",
                        user_text=request,
                        assistant_text=response,
                        mode="native",
                    )
                completion = self._last_completion
                if completion and cfg.get("auto_propose_completion", True):
                    proposal = propose_completion(root, cfg, request=request, response=response, **completion)
                    if proposal.status == "proposed":
                        out += "\n\n🧠 프로젝트 메모리 승인 제안\n" + proposal.preview
        except Exception:
            pass
        # 탐색 발견 증류 (개인 Tier0) — 프로젝트 backend 유무와 무관. 탐색이 컸던 순수 DIRECT
        # 턴의 위치 지식을 기존 ingest 승인 게이트로 안내한다 (숏컷 벤치 26-07-16 근거).
        try:
            if self._explore_cmds >= _EXPLORE_NUDGE_MIN and self._memory_provider_allowed:
                from ...memory import distill_nudge

                nudge = distill_nudge(request, response, self.root)
                if nudge:
                    out += "\n\n" + nudge
        except Exception:
            pass
        return out

    def cancel(self) -> None:
        """협조적 취소 — 이 턴의 모든 AgentSession(디스패치 자식 포함)이 공유 이벤트로 멈춘다."""
        self.cancel_event.set()

    def _persist_turn(self, request: str, response: str) -> None:
        """완결 턴을 turn_store 에 append — 취소·오류 턴은 호출부가 걸러 여기 오지 않는다."""
        try:
            from ..turn_store import append_turn

            append_turn(self.root, request, response)
        except Exception:
            pass

    def restore_history(self) -> int:
        """직전 대화 복원 — turn_store 의 최근 턴을 history 로 되살린다 (대화 맥락만, 권위 없음).
        반환 = 복원 턴 수. 퀘스트·게이트·메모리 상태는 건드리지 않는다."""
        try:
            from ..turn_store import load_turns

            turns = load_turns(self.root, limit=6)
        except Exception:
            return 0
        if turns:
            self.history = [(q, a[:500]) for q, a in turns]
        return len(turns)

    def _cancel_notice(self) -> str:
        """취소의 정직한 종결 문구 — 퀘스트는 조용히 닫지 않는다 (ACTIVE 잔존을 명시)."""
        from ...hooks.quest_log import active_quest
        from ...i18n import t

        qid = active_quest(self.root)
        return t("cancel_notice") + (t("cancel_notice_quest", qid=qid) if qid else "")

    def handle(self, request: str) -> str:
        from ...i18n import t

        self._last_completion = None
        self._explore_cmds = 0  # 턴 단위 리셋 — Trinity/거절 턴이 직전 DIRECT 탐색량을 승계하지 않게
        # cancel_event 는 여기서 clear 하지 않는다 — 제출측(REPL)이 턴 시작 전에 clear 한다.
        # handle() 진입 시 clear 하면 '제출 직후~handle 진입 전' ctrl+c 가 유실된다 (경합).
        self.on_status(t("thinking"))  # 분류도 모델 호출 — 침묵 구간 커버
        try:
            cls = self._classify(request)
        finally:
            self.on_status(None)
        if self.cancel_event.is_set():  # 분류 중 취소 — 라우팅 진입 전에 멈춘다
            return self._cancel_notice()
        if cls["destructive"]:
            _log_classify(self.root, {"event": "route", "route": "refused-destructive"})
            return self._finalize_memory(
                request, "⚠ 파괴 작업 감지 — Odin 명시 동의 필요 (Canon 3). 대상과 함께 재요청하세요."
            )
        if not cls["write_expected"]:
            _log_classify(self.root, {"event": "route", "route": "direct"})
            try:
                return self._finalize_memory(request, self._direct(request))  # DIRECT — 무세금
            except TurnCancelled:
                return self._cancel_notice()  # 취소 턴은 메모리 보존도 하지 않는다
        # 모든 비파괴 write 는 Worker가 먼저 자율 계획·실행한다. standard 는 기계 baseline 적격과
        # 개인 메모리 최소 회수만 표시하고, deep/ambiguous/shared도 선행 Thinker 없이 시작한다.
        # 별도 Thinker는 명시적 병렬 분해 또는 관측된 실패의 재계획에만 사용한다.
        standard = cls.get("task_class") in ("trivial", "standard") and not (cls["ambiguous"] or cls["shared"])
        _log_classify(self.root, {"event": "route", "route": "standard" if standard else "trinity"})
        try:
            out = self._trinity(request, cls, standard=standard)
            self.history = (self.history + [(request, out[:500])])[-6:]  # 후속 질문 맥락 (DIRECT 가 소비)
            self.last_response_text = out
            self._persist_turn(request, out)
            return self._finalize_memory(request, out)
        except TurnCancelled:
            self.last_response_text = ""
            return self._cancel_notice()
        except Exception as e:  # dangling 방지 — 퀘스트는 ACTIVE 로 남고 정직하게 보고
            out = (
                f"⚠ 세션 오류로 Trinity 중단 ({e.__class__.__name__}: {str(e)[:200]}) — "
                "퀘스트가 ACTIVE 로 남아 있음. 재요청 시 이어서 검증하거나 quest-log close 하세요."
            )
            self.last_response_text = out
            return self._finalize_memory(request, out)
