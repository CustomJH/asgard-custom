"""Heimdall — 한 요청이 지나는 조정자.

세션·기억·라우팅·마무리의 본문은 믹스인 넷이 나눠 진다. 여기 남은 것은 요청 하나의
생애다: 받고(`handle`), 레인을 골라(`_direct`·`_trinity`) 돌리고, 턴을 적는다.

믹스인인 이유는 이 메서드들이 전부 같은 조정자 상태(`self.sessions`·`self.total_tokens`·
`self.rp`)를 읽고 쓰기 때문이다. 협력 객체로 뽑으려면 그 상태를 먼저 갈라야 하고, 그것은
이 분해가 답할 질문이 아니다 — 여기서 바뀐 것은 한 파일이 몇 줄인가뿐이다."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable

from ....providers import ResolvedProvider, resolve_trinity
from ....sessions import session_key as _session_key
from ...session import TurnCancelled, ql
from ..bifrost import NULL_LEDGER
from ..classify import memory_write_intent
from ..delivery import DeliveryDispatch
from ..journal import _log_classify
from ..planning import _resume_snapshot
from ..roles import _DELIVERY_TIERS, _memory_save_support, _mimir_note, _skill_support
from ..roles import delivery_identity as _delivery_identity
from ..roles import direct_identity as _direct_identity
from ..trinity import TrinityRun
from ..waves import WaveRunner
from ._shared import (  # noqa: F401 — SessionLike·_concurrent_label 은 여기서 안 쓰고 다시 내보낸다
    SessionLike,
    _concurrent_label,
    _invoked_command,
    _new_recap,
)
from .closing import _ClosingMixin
from .recall import _RecallMixin
from .routing import _RoutingMixin
from .sessions import _SessionsMixin


class Heimdall(_SessionsMixin, _RecallMixin, _RoutingMixin, _ClosingMixin):
    def __init__(
        self,
        rp: ResolvedProvider,
        root: str,
        on_text: Callable[[str], None],
        on_status: Callable[[str | None], None] | None = None,
        agent: str = "",
    ):
        self.rp, self.root, self.on_text = rp, root, on_text
        self.on_status = on_status or (lambda s: None)
        # 이 세션이 명시로 고른 에이전트. 비어 있으면 프로젝트 배치와 끈끈한 활성이 정한다
        # (sessions.resolve_agent 의 사다리). 게이트웨이의 `?agent=` 가 이 인자로 들어온다.
        self._explicit_agent = str(agent or "")
        self._state_lock = threading.Lock()  # wave 병렬 스레드의 _clients/total_tokens 변이 보호
        self._session_seq = 0
        self._sessions: dict[str, dict] = {}
        # 턴 단위 협조 취소 — 모든 자식 AgentSession이 이 이벤트를 공유 (handle() 진입 시 clear)
        self.cancel_event = threading.Event()
        self._clients: dict[tuple, object] = {}  # (provider, base_url, key_source) → SDK 클라이언트
        self.client = self._client_for(rp)
        # 역할별 provider 배치 ([trinity.<role>]) — 미충족은 기본 provider로 fail-open + 경고 1회
        from ....providers import TRINITY_EXTRA_ROLES, TRINITY_ROLES

        self.role_rp: dict[str, ResolvedProvider] = {}
        roles = TRINITY_ROLES + TRINITY_EXTRA_ROLES + tuple(_DELIVERY_TIERS)
        for role, rrp in resolve_trinity(root, rp, roles).items():
            if rrp is not rp and rrp.missing:
                on_text(f"⚠ [trinity.{role}] 조건이 안 맞아서({'; '.join(rrp.missing)}) 기본 provider로 갈게요\n")
                rrp = rp
            self.role_rp[role] = rrp
        # trinity-policy.json — roles tier/effort·budget_priors·delivery 티어 소비
        from ....hooks.quest_log import active_quest, load_policy

        self.policy = load_policy(root)
        self._load_prompt_layers(root)
        self._load_memory_layers(rp, root)
        # delivery_identity = 메모리 무주입 — 딜리버리 자식(freyja/thor/eitri/loki)은 코디네이터가 아니다.
        # 특히 loki는 Verifier의 반례 탐색자라 메모리 유입 = 게이트 무결성 훼손.
        # 정체성은 두 벌이다 — 자르는 자리가 소비자마다 다르기 때문이다. 공통으로 빠지는 것은
        # 하네스가 코드로 도는 절차(trinity)와 아래 tail이 전문으로 다시 싣는 계약(lagom·bragi),
        # 그리고 이 프로젝트가 안 켠 기능의 설명(map·manual·agents)이다. 조립은 roles.py가 갖는다.
        tail = self.lagom + self.bragi + self.charter_identity + self.manual_identity
        self.delivery_identity = _delivery_identity(root) + tail
        self.direct_identity = _direct_identity(root) + tail
        self.identity = self.delivery_identity + self.memory_note
        self.map_note = ""  # 요청마다 최신화되는 bounded volatile context; cached identity와 분리.
        self._map_warnings: set[str] = set()
        self.total_tokens = 0  # 세션 누적 지출 (status line 사용량)
        self.turn_recap = _new_recap()  # 턴 단위 활동 집계 (handle() 진입 시 리셋) — REPL recap 패널 소스
        self.last_context_tokens = 0  # 마지막 역할 턴의 컨텍스트 크기 — status line 창 % 용
        # 프롬프트 캐시 계측 (누적) — 적중률 = read / (read+write+uncached), status line ⚡ 표시
        self.cache_read_tokens = 0
        self.cache_prompt_tokens = 0
        # DIRECT는 REPL 이중 출력을 피하려고 handle()에서 빈 문자열 sentinel을 반환한다.
        # headless JSON 호출자는 실제 최종 응답을 이 필드에서 회수한다.
        self.last_response_text = ""
        self.history: list[tuple[str, str]] = []  # REPL 턴 간 (요청, 응답 요약) — DIRECT 후속 질문 맥락
        # 세션 좌표에 에이전트를 넣는다 — 이 id 로 적히는 턴·에피소드·튜터 기록이 에이전트마다
        # 갈린다. 주변 상태(ASGARD_PROFILE)가 나중에 바뀌어도 이 세션의 기록은 안 옮겨간다.
        self._memory_session_id = _session_key(self._session_agent, scope="native", suffix=uuid.uuid4().hex)
        self._memory_turn_seq = 0
        self._last_quest_id: str | None = None  # 이 턴이 연 퀘스트 — turn_store 귀속 신호
        self._last_completion: dict | None = None
        self.dual_mode = False  # 세션 한정 — /trinity dual on 또는 headless --dual
        self._explore_cmds = 0  # 직전 DIRECT 턴의 탐색 커맨드 수 — 증류 넛지 문턱 판정용
        self._sleep: Callable[[float], None] = time.sleep  # 재시도 백오프 — 테스트 주입점
        # 협력자 — 딜리버리 위임·편대(dispatch), 배정 단위 wave 실행(waves)
        self._dispatchers = DeliveryDispatch(self)
        self._waves = WaveRunner(self)
        # 배차 장부는 퀘스트가 열릴 때 TrinityRun 이 세운다. 그 전(그리고 퀘스트 없이 도는
        # 경로)에는 아무 일도 안 하는 대역이 서 있어 호출부에 분기가 생기지 않는다.
        self.bifrost = NULL_LEDGER
        dangling = active_quest(root)
        if dangling:  # 이전 세션 중단으로 남은 ACTIVE 퀘스트 — 조용히 덮지 않는다
            on_text(
                f"⚠ 안 끝난 퀘스트가 있어요({dangling}) — 이전 세션이 중간에 멈춘 자국이에요. 이어서 검증하거나 quest-log close 해 주세요.\n"
            )

    def _load_prompt_layers(self, root: str) -> None:
        """프롬프트에 얹히는 문서 계층을 세션 생성 시 1회 렌더한다.

        전부 여기서 한 번만 읽는 이유는 KV 캐시와 재현성이다 — 세션 도중 파일이 바뀌어도
        프롬프트는 안 변한다. 설정 전환(REPL `/lagom`)은 _Reconfigure가 Heimdall을 다시 세워
        이 자리로 돌아온다.
        """
        # Lagom — off면 빈 문자열이라 프롬프트가 종전과 바이트 동일하다.
        from ....lagom import note as _lagom_note

        self.lagom = _lagom_note(root)
        # Bragi (사람 문체) — lagom과 독립 축이라 별도 해석. `/lagom off`는 압축을 끄는 것이지
        # 사람처럼 쓰기를 끄는 게 아니다. 기본 on, 끄기는 설정 bragi.mode 또는 ASGARD_BRAGI=off.
        from ....bragi import note as _bragi_note

        self.bragi = _bragi_note(root)
        # 주석 계약 — 코드를 쓰는 역할만 받는다. Verifier는 남의 주석을 판정할 뿐이고 DIRECT는
        # 코드를 안 쓰므로, identity가 아니라 worker 프롬프트에만 붙인다 (trinity.py·waves.py).
        from ....templates.comments import COMMENT_CANON

        self.comments = "\n\n" + COMMENT_CANON
        # Charter (프로젝트 북극성) — through-line은 identity로(설계①, 모든 역할·DIRECT 관통),
        # coherence는 Thinker/Verifier 프롬프트에 역할별로(협업②/판단③). 미설정이면 전부 빈 문자열.
        from ....charter import note as _charter_note

        self._charter_note = _charter_note
        self.charter_identity = _charter_note(root, "identity")
        # 커스텀 매뉴얼 — 오딘이 루트 `MANUAL.md`(+`.asgard/`)에 쓴 프로젝트 규칙. identity 절은
        # 메인·딜리버리가, 역할 절(thinker/worker/verifier)은 각 프롬프트가 가져간다. charter와
        # 달리 Worker도 받는다 — "이 프로젝트에선 코드를 이렇게 써라"가 본문이라 코드를 쓰는
        # 역할에 안 닿으면 계층 자체가 무의미하다 (hooks/manual_activate.section_for와 같은 판정).
        from ....manual import note as _manual_note

        self._manual_note = _manual_note
        self.manual_identity = _manual_note(root, "identity")
        self.manual_worker = _manual_note(root, "worker")

    # ── 딜리버리 디스패치 파사드 (구현 = delivery.DeliveryDispatch) ──
    def _thor_squad_handler(self, sid: str, worker_result_writes: list[str], cwd: str | None = None):
        return self._dispatchers.thor_squad_handler(sid, worker_result_writes, cwd)

    def _dispatch_handler(self, sid: str, worker_result_writes: list[str], cwd: str | None = None):
        return self._dispatchers.dispatch_handler(sid, worker_result_writes, cwd)

    def _run_worker_waves(self, sid: str, request: str, units: list[dict], budget_note: str) -> None:
        return self._waves.run(sid, request, units, budget_note)

    def resume(self, qid: str | None = None) -> str:
        """Recover and continue one durable native Quest without replaying done tickets."""
        from ....hooks.quest_log import active_quest

        qid = qid or active_quest(self.root)
        if not qid:
            return "⚠ 이어서 할 ACTIVE Quest가 없어요."
        recovered = ql(self.root, "ticket-recover", session=qid)
        if recovered.returncode != 0:
            detail = (recovered.stderr or recovered.stdout or "ticket recovery failed").strip()[:300]
            return f"⚠ Quest {qid}를 되살리지 못했어요 — {detail}"
        snapshot = _resume_snapshot(self.root, qid)
        if snapshot["blocked"]:
            return f"⚠ Quest {qid}는 재시도 예산을 다 썼어요 — ticket: {snapshot['blocked']}"
        if snapshot["active"]:
            return f"⚠ Quest {qid}에 아직 살아 있는 active ticket이 있어서 겹쳐 돌리지 않을게요: {snapshot['active']}"
        request = snapshot["request"] or ("Resumed Quest %s — %s" % (qid, "; ".join(snapshot["criteria"])))
        self._prepare_map(request)
        cls = {
            "task_class": "deep",
            "criteria": snapshot["criteria"] or [f"Meet the existing success criteria of Quest {qid}"],
            "parallel_requested": len(snapshot["units"]) + len(snapshot["completed"]) > 1,
            "ambiguous": False,
            "external_research": False,
            "shared": False,
        }
        return self._trinity(request, cls, resume_qid=qid, resume_units=snapshot["units"])

    def restore_history(self) -> int:
        """직전 대화 복원 — turn_store의 최근 턴을 history로 되살린다 (대화 맥락만, 권위 없음).
        반환 = 복원 턴 수. 퀘스트·게이트·메모리 상태는 건드리지 않는다."""
        try:
            from ...episodes import compact_text
            from ...turn_store import load_turns

            turns = load_turns(self.root, limit=6)
        except Exception:
            return 0
        if turns:
            # 맹목 접두 절단 대신 의미 보존 발췌 — 응답 꼬리의 결론·증거(경로·수치·판정)를 살린다
            self.history = [(q, compact_text(a, 500)) for q, a in turns]
        return len(turns)

    def _persist_turn(self, request: str, response: str) -> None:
        """완결 턴을 turn_store에 append — 취소·오류 턴은 호출부가 걸러 여기 오지 않는다.
        퀘스트·세션 귀속을 함께 남긴다 — 에피소드 계층의 검색 좌표."""
        try:
            from ...turn_store import append_turn

            append_turn(
                self.root,
                request,
                response,
                quest_id=self._last_quest_id,
                session_id=self._memory_session_id,
            )
        except Exception:
            pass

    def cancel(self) -> None:
        """협조적 취소 — 이 턴의 모든 AgentSession(디스패치 자식 포함)이 공유 이벤트로 멈춘다."""
        self.cancel_event.set()

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
        run = TrinityRun(
            self,
            request,
            cls,
            dual=self.dual_mode,
            pre_work=pre_work,
            standard=standard,
            pre_base_ref=pre_base_ref,
            resume_qid=resume_qid,
            resume_units=resume_units,
        )
        self._last_quest_id = run.qid  # 퀘스트 귀속 — 종료 후 persist 시점엔 ACTIVE가 이미 해제된다
        return run.run()

    def _direct(self, request: str, memory_intent: bool = False) -> str:
        """DIRECT 응답 — 본문은 on_text로 이미 스트리밍됨. 빈 문자열 반환해 이중 출력 방지.
        예외: refusal 안내는 스트림에 안 들어간 합성 텍스트 — 그것만 반환.

        가드: classify 오판으로 DIRECT 세션이 파일을 쓰면 — editor writes 또는
        워킹트리 fingerprint 변화 — 소급 퀘스트를 열어 Verifier 판정 + 게이트를 강제한다.
        mode B의 orphan-write 봉인의 네이티브 등가물 (native 엔 Stop 훅이 없다).

        memory_intent: 사용자의 명시적 기억 지시 턴 — memory_save 도구를 열고, 턴 종료 시
        실행 증거(도구 호출 성공)를 판정한다. 미저장이면 원문 결정론 폴백으로 봉합 —
        모델이 저장 없이 "기억했다"고 답하고 끝나는 경로가 없다 (26-07-21 실측 2회)."""
        from ....hooks.quest_log import snapshot_ref

        before = self._worktree_dirty()
        before_ref = snapshot_ref(self.root)
        # REPL 턴 간 대화 맥락 — 직전 문답 요약을 앞에 붙인다 (후속 질문 "그건 왜?"가 성립하게).
        # Trinity 경로엔 안 붙인다 — write 과업은 요청+계획이 맥락의 전부여야 한다 (Canon 7 범위 존중).
        ctx = "".join(f"[Previous exchange]\nOdin: {q}\nResponse: {a}\n\n" for q, a in self.history[-3:])
        # 요청 기반 zero-LLM 회수 (감사 권고) — 카탈로그(identity)와 별개로 관련 페이지를 결정론 주입.
        # 에피소드 레인(과거 세션 원문의 관련 구간)도 같은 호출로 받는다: 블록을 따로 이어 붙이면
        # 이 경로만 천장이 에피소드 예산만큼 높아지고, 그 구간이 개인·프로젝트·문서 레인과 중복
        # 판정을 한 번도 안 거친다 — 조립기가 하는 일이 여기서만 무효가 된다.
        recall = ""
        if self._memory_provider_allowed:
            from ....memory_context import recall_note as _recall

            recall = _recall(request, start=self.root, include_episodes=True)
        self._record_recall(recall)  # 답변 소스 배지 — 이 턴에 실제 주입될 회상량 (빈 회상은 무기록)
        live_identity = self.direct_identity + (self._memory_snap if self._memory_provider_allowed else "")
        mimir = _mimir_note(request)
        skill_note, skill_tools, skill_handlers = (
            _skill_support("mimir", self.root, include_learned=False) if mimir else ("", [], {})
        )
        # 기억 지시 턴 — 저장은 provider 주입 게이트와 무관하다: 사실은 사용자 발화에서 왔으므로
        # 메모리가 원격 모델로 새는 표면이 아니다 (inject_allowed는 읽기 주입만 다룬다).
        mem_saved: list[tuple[str, str]] = []
        mem_note, mem_tools, mem_handlers = _memory_save_support(mem_saved) if memory_intent else ("", [], {})
        r = self._session(
            live_identity + self.map_note + mimir + skill_note + mem_note,
            extra_tools=skill_tools + mem_tools,
            handlers={**skill_handlers, **mem_handlers},
            role="direct",
            readonly=True,
        ).run((ctx + request if ctx else request) + recall)
        if r.stop_reason == "cancelled":
            raise TurnCancelled()
        self.last_context_tokens = r.context_tokens or self.last_context_tokens
        self._track_cache(r)
        # 소급 승격 판정 — 전 트리 지문 비교(≠)는 병렬 세션·빌드 아티팩트의 무관 드리프트로도
        # 순수 질문을 Trinity+Verifier로 승격시켰다 (26-07-23 감사). 이 세션의 write로 귀속
        # 가능한 변화만 승격한다: 도구 관측 write(r.writes), 또는 드리프트 경로가 이 세션의
        # 실행 명령 텍스트에 등장 (bash 우회 write 백스톱 — read-only 가드가 1차 방어).
        after = self._worktree_dirty()
        drift = self._porcelain_paths(after) ^ self._porcelain_paths(before) if after != before else set()
        cmd_text = " ".join(str(c.get("cmd", "")) for c in r.commands if isinstance(c, dict))
        touched = sorted(p for p in drift if p and p in cmd_text)
        if drift and not r.writes and not touched:
            _log_classify(self.root, {"event": "misroute", "route": "direct", "external_drift": sorted(drift)[:10]})
        if r.writes or touched:
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
        corrected = final != r.text  # 라곰 재작성·봉합 — 스트리밍된 초안과 정본이 갈린 경우만
        mem_notice = self._memory_write_outcome(request, mem_saved) if memory_intent else ""
        record = final
        if mem_notice:
            record = (final.rstrip() + "\n\n" + mem_notice) if final.strip() else mem_notice
        self._explore_cmds = len(r.commands)  # 탐색량 — _finalize_memory 증류 넛지 문턱 (순수 DIRECT 한정)
        self.last_response_text = record
        self.history = (self.history + [(request, record[:500])])[-6:]
        self._persist_turn(request, record)
        if r.stop_reason == "refusal":
            return record  # refusal 안내는 스트림에 안 들어간 합성 텍스트 — 반환으로 표시
        if corrected:
            from ....i18n import t

            # 본문은 이미 라이브 스트리밍됨 (검사 전 버퍼링은 REPL을 먹통으로 보이게 했다 —
            # 26-07-23). 위반 시에만 정본을 교정 표식과 함께 뒤에 붙인다. 정본은 위에서 확정됨.
            self.on_text("\n\n" + t("lagom_corrected") + "\n" + final + "\n")
        if mem_notice:
            self.on_text("\n\n" + mem_notice)  # 본문은 이미 스트리밍됨 — 증거 노티스만 추가 출력
        return ""

    def handle(self, request: str) -> str:
        self._last_completion = None
        self._last_quest_id = None  # 턴 단위 리셋 — DIRECT 턴이 직전 퀘스트 귀속을 승계하지 않게
        self._explore_cmds = 0  # 턴 단위 리셋 — Trinity/거절 턴이 직전 DIRECT 탐색량을 승계하지 않게
        with self._state_lock:
            self.turn_recap = _new_recap()  # 턴 recap 리셋 — REPL이 턴 종료 후 회수
        # 스킬 호출이면 `request` 는 그 스킬 본문으로 부푼 프롬프트다. 요청이 무엇이냐를 읽는
        # 층(지도 준비·튜터·분류)은 부푼 본문이 아니라 `/skill args` 원문을 봐야 한다 — 본문은
        # 절차가 무엇을 할 수 있는지를 적은 계약이지 사용자가 부탁한 일이 아니다.
        invoked = _invoked_command(request)
        subject = invoked or request
        self._prepare_map(subject)
        self._tutor_brief(subject)
        self._tutor_tip()
        # cancel_event는 여기서 clear 하지 않는다 — 제출측(REPL)이 턴 시작 전에 clear 한다.
        # handle() 진입 시 clear 하면 '제출 직후~handle 진입 전' ctrl+c가 유실된다 (경합).
        cls = self._route(subject, invoked)
        if self.cancel_event.is_set():  # 분류 중 취소 — 라우팅 진입 전에 멈춘다
            return self._cancel_notice()
        if cls["destructive"]:
            _log_classify(self.root, {"event": "route", "route": "refused-destructive"})
            return self._finalize_memory(
                request, "⚠ 되돌릴 수 없는 작업이라 오딘의 확인이 필요해요 (Canon 3). 대상을 적어서 다시 말씀해 주세요."
            )
        if not cls["write_expected"]:
            _log_classify(self.root, {"event": "route", "route": "direct"})
            try:
                # 기억 지시는 분류 소스와 무관한 결정론 재판정 — LLM 분류가 trivial로 뭉개도 계약이 열린다.
                return self._finalize_memory(
                    request, self._direct(request, memory_intent=memory_write_intent(subject))
                )  # DIRECT — 무세금
            except TurnCancelled:
                return self._cancel_notice()  # 취소 턴은 메모리 보존도 하지 않는다
        # 봉인 레인 — write 이지만 소스는 안 건드린다 (git 이력만). Trinity 는 계획할 변경도,
        # 돌릴 베이스라인도, 대조할 diff-hash 도 못 만드는 과업에 그 절차를 전부 실행한다.
        if cls.get("task_class") == "vcs":
            _log_classify(self.root, {"event": "route", "route": "seal"})
            try:
                return self._finalize_memory(request, self._seal(request, subject))
            except TurnCancelled:
                return self._cancel_notice()
        # 모든 비파괴 write는 Worker가 먼저 자율 계획·실행한다. standard는 기계 baseline 적격과
        # 개인 메모리 최소 회수만 표시하고, deep/ambiguous/shared도 선행 Thinker 없이 시작한다.
        # 별도 Thinker는 명시적 병렬 분해 또는 관측된 실패의 재계획에만 사용한다.
        standard = cls.get("task_class") in ("trivial", "standard") and not (cls["ambiguous"] or cls["shared"])
        _log_classify(self.root, {"event": "route", "route": "standard" if standard else "trinity"})
        try:
            out = self._trinity(request, cls, standard=standard)
            self.history = (self.history + [(request, out[:500])])[-6:]  # 후속 질문 맥락 (DIRECT가 소비)
            self.last_response_text = out
            self._persist_turn(request, out)
            return self._finalize_memory(request, out)
        except TurnCancelled:
            self.last_response_text = ""
            return self._cancel_notice()
        except Exception as e:  # dangling 방지 — 퀘스트는 ACTIVE로 남고 정직하게 보고
            out = (
                f"⚠ 세션에 문제가 생겨 Trinity를 멈췄어요 ({e.__class__.__name__}: {str(e)[:200]}) — "
                "퀘스트가 ACTIVE로 남아 있음. 재요청 시 이어서 검증하거나 quest-log close 하세요."
            )
            self.last_response_text = out
            return self._finalize_memory(request, out)
