"""Trinity 순환 — 한 퀘스트가 역할을 옮겨 다니는 자리.

역할 턴의 본문은 믹스인 셋이 나눠 진다. 여기 남은 것은 순환 그 자체다: 퀘스트를 열고,
전이 함수가 준 역할을 받아, 턴을 돌리고, 끝났는지 묻는다.

믹스인인 이유는 이 메서드들이 전부 같은 실행 상태(`self.quest`·`self.turn`·`self.hd`)를
읽고 쓰기 때문이다. 협력 객체로 뽑으려면 그 상태를 먼저 갈라야 하고, 그것은 이 분해가
답할 질문이 아니다 — 여기서 바뀐 것은 한 파일이 몇 줄인가뿐이다."""

from __future__ import annotations

import json
import time
import uuid

from .... import activity, i18n, ui
from ...session import ql
from ..bifrost import NULL_LEDGER, CoordinatorLoop, open_ledger
from ..journal import record_writes
from ..roles import _ROLE_KEY, _transition_line
from ._shared import (  # noqa: F401 — 아래 넷은 여기서 안 쓰고 다시 내보내기만 한다
    _CRAFT_MAX_BLOCKS,
    MAX_TRINITY_TURNS,
    _classified_findings,
    _craft_blocking,
    _runner_identity,
)
from .notes import _NotesMixin
from .turns import _TurnsMixin
from .verdict import _VerdictMixin


class TrinityRun(_TurnsMixin, _VerdictMixin, _NotesMixin):
    """한 퀘스트의 Trinity 순환 실행 상태 + 역할 턴 메서드."""

    # 지금 도는 역할 턴의 코디네이터. 턴 밖에서는 None 이다 — `_role_turn` 이 세우고 걷는다.
    _loop: CoordinatorLoop | None = None

    def __init__(
        self,
        hd,
        request: str,
        cls: dict,
        *,
        dual: bool = False,
        pre_work=None,
        standard: bool = False,
        pre_base_ref: str | None = None,
        resume_qid: str | None = None,
        resume_units: list[dict] | None = None,
    ):
        self._hd = hd
        self.request = request
        # Heuristic classification intentionally avoids a second LLM call, so it may not
        # produce criteria. Bind the actual request into a non-empty criterion used by every
        # subsequent role and by the durable quest gate; do not show Verifier an empty list.
        if not cls.get("criteria"):
            cls = {**cls, "criteria": [f"Request text and resulting change match: {request[:500]}"]}
        self.cls = cls
        self.dual = dual
        self.pre_work = pre_work
        self.standard = standard
        self.pre_base_ref = pre_base_ref
        self.resume_qid = resume_qid
        self.resume_units = resume_units
        self.qid = resume_qid or f"native-{int(time.time())}-{uuid.uuid4().hex[:6]}"  # 초 단위 충돌 방지
        self.sid = self.qid
        tc = str(cls.get("task_class") or "")
        self.tc = tc if tc in ("trivial", "standard") else "deep"  # 미상/파싱 실패는 deep (안전 기본값)

        # ── 순환 가변 상태 ──
        # 단일 Worker가 기본 계획자다. 별도 Thinker가 필요한 병렬/재계획 경로는 이 값을 덮어쓴다.
        self.plan_ctx = "Success criteria: " + "; ".join(map(str, cls["criteria"]))
        self.explored: list[str] = []  # Thinker 관찰 명령 — Worker 재탐색 세금 절감 (힌트 전용)
        self.structural = False  # 직전 FAIL이 구조적 — 다음 next에 --structural 전달
        self.last_fail: dict | None = None  # 직전 FAIL 상세 — WORKER_RETRY에 주입
        self.fail_history: list[str] = []  # 턴별 실패 이력 — THINKER_REPLAN에 주입
        self.gate_sigs: dict[str, int] = {}  # 게이트 차단 사유별 카운트
        self.gate_blocks = 0
        self.craft_blocks = 0  # 형상 래칫 차단 횟수 — 상한은 hooks/craft_gate.py와 같다
        self.saw_red = False  # 이 퀘스트에서 하네스 베이스라인 red 관측 — prior 집계 축
        self.replans = 0  # 재계획 횟수 — 2회+ 는 clean-slate: thinker_alt placement 또는 티어 승급
        self.wave_plan_pending = False  # 새 Thinker 계획의 units는 WORKER_RETRY 전이여도 한 번 실행
        self.dual_plan_pending = False  # 초기 dual 계획은 단일 Worker가 직접 합성·실행
        self.had_wave_plan = False  # wave FAIL을 범위 없는 단일 Worker로 강등하지 않는 latch
        self.pending: tuple[str, str] | None = None  # 게이트 수리 강제 턴 — next 우회

        # ── 턴 스코프 상태 (매 턴 run()이 재설정) ──
        self.t = 0
        self.role = ""
        self.why = ""
        self.level = "micro"
        self.budget_note = ""
        self.model: str | None = None
        self.rrp = hd.rp
        self.used_model = ""

        # 배차 장부 — 역할 턴과 배정 단위를 Run·Task·Dispatch 로 비춘다 (fail-open). 역할 턴의
        # 순서는 여전히 전이 함수(quest-log next)가 정하고, 배정 단위의 갈래는 형상이 정한다
        # (`_routed_shape`). `open_ledger` 는 direct 형상이면 장부를 안 연다 — 형상이 먼저다.
        self.bifrost = open_ledger(hd, self.qid, request, self.cls)
        hd.bifrost = self.bifrost  # WaveRunner 가 같은 장부를 본다
        self.coordinator_answers: list[tuple[str, str]] = []  # (질문, 답) — 최종 보고에 표시된다
        self.unit_reports: list[dict] = []  # 감독 고리가 거둔 단위 완료 보고 — 최종 보고에 표시된다
        # 형상은 계획 전에 한 번 고르고, Thinker 가 배정 단위를 내면 다시 고른다. 첫 판정은
        # 분류 신호만 보므로 대개 single 이나 squad 이고, units 가 나오면 graph 로 바뀐다.
        self.bifrost.choose_shape(self.cls)

    # ── 준비 ────────────────────────────────────────────────────────────
    def _open_quest(self) -> str | None:
        args = ["open", self.qid, "--task-class", self.tc, "--request-stdin"] + [
            x for c in self.cls["criteria"] for x in ("--criteria", c)
        ]
        if self.pre_base_ref:
            args += ["--base-ref", self.pre_base_ref]
        opened = ql(
            self._hd.root,
            *args,
            session=self.sid,
            stdin=json.dumps({"request": self.request}, ensure_ascii=False),
        )
        if opened.returncode != 0:
            detail = (opened.stderr or opened.stdout or "quest open rejected").strip()[:300]
            return f"⚠ Trinity를 시작하지 못했어요 — {detail}"
        return None

    def _record_pre_work(self) -> None:
        # DIRECT 오분류 소급 편입 — 이미 실행된 write를 work로 기록
        pre_work = self.pre_work
        if pre_work is None:  # run() 가드와 동일 — 타입 내로잉
            return
        record_writes(self._hd.root, self.sid, list(pre_work.writes))
        ql(
            self._hd.root,
            "append",
            session=self.sid,
            stdin=json.dumps(
                {
                    "role": "worker",
                    "event": "work",
                    "changed_files": list(pre_work.writes)[:50],
                    "commands": pre_work.commands[-20:],
                }
            ),
        )

    # ── 순환 본체 ────────────────────────────────────────────────────────
    def run(self) -> str:
        """순환을 돌고 최종 보고를 돌려준다. 종결하는 모든 갈래에서 Run 을 닫는다.

        보고를 들고 나가는 것은 **종결**이다 — 예산 소진도, DIRECT_DONE 도, 미지의 전이 상태도
        그 자리에서 퀘스트가 끝난다. 그때 Run 을 안 닫으면 `run_bind` 가 열린 Run 만 재사용하므로
        그 Run 이 `siege runs` 에 영원히 남고, 열린 질문을 훑는 명령이 매번 그것을 지난다.

        예외로 나가는 갈래(진짜 중단)만 Run 을 열어 둔다. 중단된 퀘스트는 이어서 검증할 자리가
        남아 있어야 하고, 열린 Run 이 곧 그 표시다.
        """
        try:
            out = self._cycle()
        finally:
            # 장부는 이 퀘스트의 것이다. Heimdall 은 REPL 에서 장수하므로 되돌리지 않으면
            # 다음 요청이 끝난 퀘스트의 장부를 가리킨 채 돈다.
            if self._hd.bifrost is self.bifrost:
                self._hd.bifrost = NULL_LEDGER
        self.bifrost.close()
        return out

    def _preflight(self) -> str | None:
        """순환에 들어가기 전에 해 둘 것 — 배치 검사, 퀘스트 열기, 사전 작업 편입.

        Returns:
            문자열이면 순환을 시작하지 않고 그것을 최종 보고로 낸다.
        """
        hd = self._hd
        dual_active = self.dual and not self.resume_qid and self.pre_work is None
        if dual_active:
            a, b = hd.dual_thinker_labels()
            if a == b:
                return (
                    f"⚠ Dual mode는 서로 다른 Thinker 모델이 있어야 해요 ({a}). "
                    "`/trinity set`에서 thinker_alt를 다른 모델로 배치해 주세요."
                )
            if self.cls.get("parallel_requested"):
                return "⚠ Dual mode와 Worker 병렬 wave는 아직 같이 못 써요."
        if not self.resume_qid:
            rejected = self._open_quest()
            if rejected:
                return rejected
        if self.pre_work is not None:
            self._record_pre_work()
        elif dual_active:
            self._dual_thinker_turn()
        return None

    def _assign_turn(self) -> None:
        """이번 턴의 (역할, 모델)을 정한다 — Trinity per-turn assignment의 하니스 판."""
        hd = self._hd
        if self.role == "THINKER_REPLAN":
            self.replans += 1
        role_key = _ROLE_KEY.get(self.role, "")
        alt = (
            self.role == "THINKER_REPLAN" and self.replans >= 2 and hd.role_rp.get("thinker_alt", hd.rp) is not hd.rp
        )  # clean-slate: 같은 모델의 재계획이 반복 실패 — 다른 시선 투입 (Fugu §4.4)
        sess_role = "thinker_alt" if alt else role_key
        bump = (self.role == "VERIFIER" and self.level == "full") or (
            role_key == "thinker" and self.replans >= 2 and not alt
        )
        self.sess_role = sess_role
        self.model = hd._model_for(sess_role, bump=bump) if role_key else None
        self.rrp = hd.role_rp.get(sess_role, hd.rp)
        self.used_model = f"{self.rrp.profile.name}:{self.model or self.rrp.model}"  # 퀘스트 로그 기록용
        if self.rrp is not hd.rp:  # 역할별 배치가 있으면 어떤 모델이 뛰는지 표시
            self.why += f" · {self.rrp.profile.name}:{self.rrp.model}"
        elif self.model and self.model != hd.rp.model:
            self.why += f" · {self.model}"

    def _exhausted_report(self, budget: int) -> str:
        """예산 소진 Odin 보고 — 무엇을 못 돌렸는지와 그 이유를 함께 적는다.

        침묵 break는 "판정 실패"로 오독된다 (26-07-22 실측: grace PASS 후 타 세션 소유
        베이스라인 red로 수리 전이가 막혀 "grace 판정까지 완료 실패" 보고 — 실제 판정은 PASS
        완료). 미실행 전이와 사유를 들고 나가야 보고가 정직해진다.
        """
        self._hd._record_outcome(self.tc, "budget-exhausted", self.saw_red)
        pending_next = getattr(self, "exhausted_next", None)
        if pending_next:
            role, why = pending_next
            detail = f"미실행 전이 {role} — {why}"
            for fail_line in self._baseline_red_fails()[:2]:
                detail += f"\n  붉은 체크: {fail_line[:160]}"
        else:
            detail = "grace 판정까지 완료 실패"
        return f"⚠ 턴 예산({budget})을 다 썼어요 — 여기까지 보고드려요 ({detail}). 퀘스트 로그: .asgard/quest/{self.qid}.jsonl"

    def _cycle(self) -> str:
        hd = self._hd
        rejected = self._preflight()
        if rejected:
            return rejected
        # 턴 예산 = budget_priors[task_class] — T→W→V 최소 순환 아래로는 안 내려간다
        priors = hd.policy.get("budget_priors") or {}
        budget = int((priors.get(self.cls.get("task_class") or "deep") or {}).get("turns", MAX_TRINITY_TURNS))
        budget = max(3, min(budget, MAX_TRINITY_TURNS))
        flag_args = [
            f
            for f, on in (
                ("--ambiguous", self.cls["ambiguous"]),
                ("--external-research", self.cls["external_research"]),
                ("--shared", self.cls["shared"]),
                ("--parallel-requested", self.cls.get("parallel_requested", False)),
                ("--write-expected", True),
            )
            if on
        ]  # 게이트-우선은 전이 함수 기본값 — 별도 플래그 없음, 물리 가드가 판정
        flag_args += ["--task-class", self.tc]  # prior 승격 문턱 축

        if self.resume_units:
            # i18n.t를 모듈 경유로 부른다 — 이 메서드의 `t`는 턴 번호다 (from-import는 그 위를 덮는다)
            hd.on_text(f"  {ui.dim('│ ↻ ' + i18n.t('todo_resume', qid=self.qid, n=len(self.resume_units)))}\n")
            hd._run_worker_waves(self.sid, self.request, self.resume_units, "\n(resumed after process restart)")
            self.had_wave_plan = True

        for t in range(1, budget + 3):  # +2 = grace 판정 턴 + 종료(DONE/게이트) 여지
            self.t = t
            if self.pending:
                self.role, self.why = self.pending
                self.pending = None
                # 수리 재검증은 상위 레벨로 — micro 부족이 차단 사유일 수 있다. 단 verify_level=low
                # 에서는 micro가 차단 사유가 될 수 없으므로 승격도 없다 (설정이 정한 상한).
                from ....hooks.quest_log import full_verify_required

                self.level = "full" if full_verify_required(hd.policy, True) else "micro"
            else:
                nx_args = flag_args + (["--structural"] if self.structural else [])
                nxt = json.loads(ql(hd.root, "next", *nx_args, session=self.sid).stdout or "{}")
                self.role, self.why = nxt.get("next_role", ""), nxt.get("why", "")
                self.level = nxt.get("verify_level", "micro")
                if self.role == "WORKER_RETRY" and ("baseline" in self.why.lower() or "베이스라인" in self.why):
                    self.last_fail = {"sig": "baseline-red", "why": self.why[:500]}
            if t > budget and self.role not in ("VERIFIER", "BASELINE_VERIFY", "DONE", "ESCALATE_ODIN", "DIRECT_DONE"):
                # 예산 소진 — grace는 판정·종료 전용, 새 작업 턴 금지.
                self.exhausted_next = (self.role, self.why)
                break
            # 잔량 자기규제 (budget-guard) — 80% 도달 시 범위 축소 지시
            self.budget_note = f"\n(turn {t}/{budget}" + (
                " — 80% of budget reached: narrow scope, prioritize core criteria, record assumptions as `가정:` )"
                if t >= max(2, int(budget * 0.8))
                else ")"
            )
            self._assign_turn()
            # 역할 전이 = 이 퀘스트의 **실제** 단계다. 창의 진행 표시가 여태 거짓말이던 자리를
            # 여기서 갚는다: 다섯 칸짜리 고정 레일을 상태 하나로 칠하는 대신, 실제로 일어난
            # 전이를 그때그때 흘린다 (가짜 서수는 병렬로 도는 일을 왜곡한다).
            activity.emit("role", role=self.role, why=self.why[:200], turn=t, budget=budget)
            hd.on_text(_transition_line(self.role, self.why))

            out = self._role_turn()
            if out is not None:
                return out

        return self._exhausted_report(budget)

    def _quest_paths(self) -> list[str]:
        """이 퀘스트에 귀속된 변경 경로 — 워킹트리엔 타 세션 작업이 섞일 수 있어 로그가 정본이다."""
        try:
            state = json.loads(ql(self._hd.root, "state", session=self.sid).stdout or "{}")
        except Exception:
            return []
        return [str(path) for path in (state.get("changed_files") or []) if str(path)]

    def _fail_and_repair(self, sig: str, why: str, cmd: str, role: str, retry: str) -> bool:
        """하네스 판정 FAIL을 로그에 남기고 수리 턴을 예약한다 — 완료 불변식들의 공통 자리."""
        commands = [{"cmd": cmd, "exit_code": 1}]
        self.saw_red = True
        self.last_fail = {"sig": sig, "why": why, "criteria": self.cls["criteria"], "commands": commands}
        self.fail_history.append(f"{sig}: {why[:200]}")
        ql(
            self._hd.root,
            "append",
            "--verdict",
            "FAIL",
            "--level",
            "full",
            session=self.sid,
            stdin=json.dumps(
                {
                    "role": role,
                    "event": "verify",
                    "criteria": self.cls["criteria"],
                    "commands": commands,
                    "failure_sig": sig,
                }
            ),
        )
        self.pending = ("WORKER_RETRY", retry)
        return True

    # ── 역할 턴 ──────────────────────────────────────────────────────────

    def _role_turn(self) -> str | None:
        """이번 턴의 역할을 수행하고, 그 시도를 배차 장부에 남긴다.

        장부는 기록이지 통제가 아니다 — 어떤 역할을 돌릴지는 이미 전이 함수가 정했고 여기서는
        시작과 끝을 적을 뿐이다. 종료 상태(DONE·ESCALATE_ODIN·DIRECT_DONE)는 워커 턴이 아니라
        순환의 끝이라 Dispatch 를 열지 않는다.

        Returns:
            None 이면 다음 턴을 계속하고, 문자열이면 그것이 최종 보고다.
        """
        hd = self._hd
        if self.role == "DONE":
            return self._done_turn()
        if self.role == "ESCALATE_ODIN":
            hd._escalate(self.sid)
            hd._record_outcome(self.tc, "escalate", self.saw_red)
            self.bifrost.escalate(self.why)
            return f"⚠ 오딘이 정해 주셔야 해요 — {self.why}"
        if self.role == "DIRECT_DONE":
            return hd._direct(self.request)

        runner = {
            "BASELINE_VERIFY": self._baseline_turn,
            "THINKER": self._thinker_turn,
            "THINKER_REPLAN": self._thinker_turn,
            "WORKER": self._worker_turn,
            "WORKER_RETRY": self._worker_turn,
            "VERIFIER": self._verifier_turn,
        }.get(self.role)
        if runner is None:
            return f"⚠ 모르는 전이 상태 '{self.role}'를 만났어요 — 여기까지 보고드려요 (퀘스트 로그: .asgard/quest/{self.qid}.jsonl)"

        dispatch = self.bifrost.open_turn(
            self.role,
            self.why,
            model=self.used_model,
            agent=hd._agent_for(getattr(self, "sess_role", "")) or "",
        )
        # 코디네이터 고리는 이 턴이 도는 내내 별도 스레드에서 우편함을 본다. 워커가 묻는 쪽과
        # 답하는 쪽이 다른 스레드여야 교착이 아니다 — 단일 Worker 턴에서도 같은 이유로 필요하다.
        # `self._loop` 에 걸어 두는 것은 wave 갈래가 이 고리로 감독하기 위해서다: 턴마다 고리를
        # 새로 세우면 데몬 스레드가 둘이 되어 같은 질문에 두 번 답한다.
        try:
            with CoordinatorLoop(hd, self.bifrost, self.request) as loop:
                self._loop = loop
                out = runner()
        except BaseException as exc:
            # 취소도 실패로 적는다 — 이 시도가 결과 없이 끝났다는 사실은 같다. Verifier 의
            # FAIL 판정은 여기 오지 않는다: 판정을 냈으면 그 턴은 자기 몫을 한 것이다.
            self.bifrost.settle_turn(dispatch, "failed", summary=f"{exc.__class__.__name__}: {exc}")
            raise
        finally:
            self._loop = None  # 고리는 이 턴의 것이다 — 이미 닫힌 고리를 다음 턴이 붙들지 않게
        if loop.answered:
            self.coordinator_answers.extend(loop.answered)
        self.bifrost.settle_turn(dispatch, "succeeded", summary=str(out or "")[:2000])
        return out
