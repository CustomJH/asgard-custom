"""Trinity 를 배차 장부에 비추는 어댑터 — 역할 턴과 배정 단위를 Run·Task·Dispatch 로.

여태 Trinity 의 통제는 **전이 함수 하나**였다. `quest-log next` 가 다음 역할을 정하고, 그
역할이 돌고, 결과가 퀘스트 로그에 붙는다. 결정론이라는 점에서 좋았지만 배차를 모른다:
어느 턴이 몇 번째 시도인지, 어느 모델이 그 턴을 돌았는지, 병렬 단위 중 무엇이 아직 답을
기다리는지를 물을 자리가 없었다. 그 물음은 wave 병렬이 켜지는 순간 실무가 된다.

이 어댑터가 두 가지를 장부에 적는다:

  역할 턴    THINKER·WORKER·VERIFIER 각각이 Task 하나 + Dispatch 하나. 마지막으로 **성공한**
             턴을 의존으로 달아 순환의 순서가 DAG 로 남는다. 실패한 턴을 의존으로 달면 다음
             턴이 `blocked` 이 되어 순환의 수리 전이 자체가 막힌다.
  배정 단위  wave 의 각 단위가 Worker 턴 Task 의 자식 Task. 의존은 계획이 이미 선언한
             `access` 를 그대로 쓴다 — 여태 문맥 주입에만 쓰이고 의존으로는 안 쓰이던 값이다.

**정본은 DB 다.** 프로세스를 재시작해 같은 퀘스트를 이어 받으면 `_resume` 이 이 Run 의 Task 를
읽어 장부 상태를 되살리고, 정산 없이 남은 시도를 회수한다. 중복 방지가 메모리에만 있으면
재개한 퀘스트는 배정 단위 Task 를 두 벌 갖고 시도 횟수가 갈린다.

**전부 fail-open 이다.** 장부가 못 서면 `enabled` 가 내려가고 Trinity 는 종전과 같이 돈다.
정본은 퀘스트 로그(`.asgard/quest/*.jsonl`)이고 이것은 그 위의 파생 기록이라, 장부를 얻으려다
작업을 잃는 교환은 성립하지 않는다. 다만 fail-open 은 fail-silent 가 아니다 — 삼킨 실패는
`_note` 가 `notes` 와 stderr 에 한 줄씩 남긴다.
"""

from __future__ import annotations

import sys
import threading
from typing import TYPE_CHECKING

from ...orchestration import (
    META_MAX_ATTEMPTS,
    ask,
    choose_shape,
    dispatch_mark,
    dispatch_settle,
    escalate,
    gate_create,
    open_dispatch,
    pending_questions,
    reclaim,
    reply,
    run_bind,
    run_close,
    run_shape,
    set_meta,
    task_create,
    task_list,
    task_update,
    topo_waves,
    worker_done,
)
from ...orchestration import check as mail_check

if TYPE_CHECKING:
    from .core import Heimdall

# 코디네이터가 우편함을 비울 때 한 번에 처리하는 상한은 orchestration.DELIVERY_CAP 이 정한다.
# 여기서는 대기 시간만 정하는데, 0 이면 "지금 있는 것만" 이라는 뜻이다 — 역할 턴 사이의
# 배수는 기다릴 이유가 없다(워커가 이미 끝나 있다).
_DRAIN_TIMEOUT_MS = 0

# 역할 턴 Task 의 `unit_id` 로 쓰이는 이름들. 재개할 때 장부를 DB 에서 복원하려면 역할 턴과
# 배정 단위를 가려야 하는데, 그 둘이 같은 칸을 쓴다. 배정 단위 id 는 계획이 붙인 값이라
# 이 목록 밖이다.
_TURN_UNIT_IDS = frozenset({"BASELINE_VERIFY", "THINKER", "THINKER_REPLAN", "WORKER", "WORKER_RETRY", "VERIFIER"})

# 한 퀘스트 동안 코디네이터가 모델을 불러 답할 수 있는 횟수. 상한이 `CoordinatorLoop` 에
# 있으면 역할 턴마다 새로 세워지면서 리셋되어 실질 상한이 턴 수만큼 곱해진다.
_MAX_MODEL_ANSWERS = 6

# 장부 실패 기록의 상한. 실패가 폭주해도 메모리를 무한정 먹지 않게 한다.
_NOTE_CAP = 50


class BifrostLedger:
    """한 퀘스트의 배차 장부. 실패해도 Trinity 를 막지 않는다."""

    def __init__(self, hd: Heimdall, qid: str, request: str) -> None:
        self._hd = hd
        self.root = hd.root
        self.qid = qid
        self.request = request
        self.enabled = False
        self.run_id = ""
        self.notes: list[str] = []  # 삼킨 장부 실패의 기록 — fail-open 이지 fail-silent 가 아니다
        self._specialists: list[str] | None = None  # 지연 계산 + 기억 (아래 matched_specialists)
        self._turn_task = ""  # 지금 도는 역할 턴 Task
        self._turn_dispatch = ""
        self._ok_turn_task = ""  # 마지막으로 **성공한** 역할 턴 — 다음 턴의 의존
        self._unit_task: dict[str, str] = {}  # 단위 id(문자열) → Task id
        self._unit_dispatch: dict[str, str] = {}
        self._worker_task = ""  # 배정 단위들이 매달릴 부모
        self.shape = ""  # `choose_shape` 가 정한 실행 모양 — 최종 보고에 표시된다
        self._answer_lock = threading.Lock()  # 코디네이터 답변 예산 — 데몬 스레드와 메인이 함께 센다
        self._model_answers = 0
        try:
            run = run_bind(self.root, qid, request[:500], coordinator=hd.__class__.__name__)
            self.run_id = run["id"]
            self.enabled = True
        except Exception as exc:
            # 장부 없이도 순환은 돈다. 여기서 예외를 올리면 DB 하나 때문에 퀘스트가 안 열린다.
            self.enabled = False
            self._note("run_bind", exc)
            return
        self._publish_policy()
        self._resume()

    # ── 기록 ───────────────────────────────────────────────────────────────────

    def _note(self, where: str, exc: BaseException) -> None:
        """장부 쓰기 실패를 한 줄로 남긴다.

        fail-open 은 옳지만 fail-silent 는 아니다. 이 계층은 코디네이터가 읽는 장부라, 쓰기가
        조용히 실패하면 `siege show` 가 참이 아닌 상태를 보여 주고 코디네이터는 그 화면을
        근거로 다음 배차를 정한다. 사용자 표면(`on_text`)이 아니라 stderr 로 보내는 이유는
        장부의 실패가 퀘스트의 진행과 무관한 정보이기 때문이다.
        """
        line = f"⚠ bifrost {where} — {exc.__class__.__name__}: {exc}"[:300]
        if len(self.notes) < _NOTE_CAP:
            self.notes.append(line)
        print(line, file=sys.stderr)

    # ── 재개 ───────────────────────────────────────────────────────────────────

    def _publish_policy(self) -> None:
        """이 프로젝트의 재시도 상한을 장부에 적는다 — 배차와 정산이 같은 수를 보게.

        `MAX_ATTEMPTS` 하드코딩과 `ticket_runtime.max_attempts` 설정값이 서로 다른 소스라,
        정책을 5 로 올리면 티켓은 다섯 번 도는데 배차 장부는 셋째에 회로를 끊는다.
        """
        try:
            policy = self._hd.policy.get("ticket_runtime") or {}
            configured = policy.get("max_attempts")
            if configured is None:
                return
            set_meta(self.root, META_MAX_ATTEMPTS, str(max(1, min(int(configured), 20))))
        except Exception as exc:
            self._note("policy", exc)

    def _resume(self) -> None:
        """이미 이 Run 에 있는 Task 를 읽어 장부 상태를 되살린다.

        장부의 정본은 DB 이지 프로세스 메모리가 아니다. 재개(프로세스 재시작 후 같은 퀘스트를
        이어 받는 것)에서 이 복원이 없으면 `register_units` 의 중복 방지가 통째로 비어 있는
        딕셔너리를 보고, 배정 단위 Task 가 두 벌 생겨 시도 횟수가 갈린다.

        복원과 함께 정산 없이 남은 시도를 회수한다. 죽은 프로세스가 남긴 `ready` Dispatch 가
        있으면 그 Task 는 다시 배차되지 않아 재개 자체가 성립하지 않는다.
        """
        try:
            reclaim(self.root, self.run_id)
            rows = task_list(self.root, self.run_id)
        except Exception as exc:
            self._note("resume", exc)
            return
        for task in rows:
            uid = str(task.get("unit_id") or "")
            if not uid:
                continue
            if uid in _TURN_UNIT_IDS:
                self._turn_task = task["id"]
                if task["status"] == "completed":
                    self._ok_turn_task = task["id"]
                if uid.startswith("WORKER"):
                    self._worker_task = task["id"]
            else:
                self._unit_task[uid] = task["id"]

    def matched_specialists(self) -> list[str]:
        """이 과업에 결정론 매칭된 딜리버리 전문가 이름들 (thor·freyja·eitri 중).

        `roles._delivery_matches` 를 그대로 읽는다. 같은 값이 이미 Thinker 계획 문맥
        (`delivery_canon_note`)과 Worker 착수 힌트(`worker_canon_hint`)를 만들고 있으므로,
        여기서 새로 재는 것이 아니라 이미 있는 판정을 형상 선택에도 읽히는 것이다 — 모델
        호출 없음.

        장부는 한 번만 재고 기억한다. `choose_shape` 는 계획 전후로 두 번 불리는데 과업
        텍스트는 그 사이에 변하지 않으므로 두 번째 계산은 같은 답을 낸다.

        실패는 빈 목록이다 — 매처가 죽으면 squad 만 못 고를 뿐 형상 선택 자체는 돈다.
        """
        if self._specialists is None:
            try:
                from .roles import _delivery_matches

                self._specialists = list(_delivery_matches(self.root, self.request))
            except Exception:
                self._specialists = []
        return self._specialists

    def choose_shape(self, cls: dict, *, unit_count: int = 0, specialists: list[str] | None = None) -> dict:
        """이 퀘스트의 오케스트레이션 형상을 고르고 Run 에 적는다.

        판정은 `orchestration.strategy.choose` 가 하고 여기서는 신호를 모아 넘기기만 한다 —
        새 모델 호출은 없다. 계획이 나오면 다시 부를 수 있다(단일로 시작해 배정 단위가 둘
        나오면 graph 가 된다).

        `specialists` 를 안 넘기면 과업에 매칭된 전문가를 장부가 직접 잰다. 호출부가 이 값을
        모르기 때문이다 — 전문가 선택은 Worker 가 `dispatch` 툴로 하는 런타임 결정이라
        형상을 고르는 시점에는 아직 일어나지 않았고, 그때까지 기다리면 형상을 못 적는다.
        빈 목록을 명시적으로 넘기면 매칭을 끄는 뜻이다.
        """
        decision = choose_shape(
            write_expected=bool(cls.get("write_expected", True)),
            task_class=str(cls.get("task_class") or "deep"),
            parallel_requested=bool(cls.get("parallel_requested")),
            unit_count=unit_count,
            specialists=list(specialists) if specialists is not None else self.matched_specialists(),
        )
        self.shape = decision["shape"]
        if self.enabled:
            try:
                run_shape(self.root, self.run_id, decision["shape"], decision["why"])
            except Exception as exc:
                self._note("run_shape", exc)
        return decision

    # ── 역할 턴 ────────────────────────────────────────────────────────────────

    def open_turn(self, role: str, why: str, *, model: str = "", agent: str = "") -> str:
        """역할 턴 하나를 Task + Dispatch 로 연다. 돌려주는 값은 Dispatch id 다.

        의존은 직전 턴이 아니라 **마지막으로 성공한 턴**이다. 순환의 수리 전이(WORKER 실패 →
        VERIFIER → WORKER_RETRY)에서는 앞 턴이 실패해도 다음 턴이 돌아야 하는데, 실패한 턴을
        의존으로 달면 다음 Task 가 `blocked` 이 되고 `open_dispatch` 가 그것을 거부한다.
        "순서를 DAG 로 남긴다" 는 목적은 성공한 턴만 이어도 그대로 지켜진다 — 실패한 시도는
        Dispatch 이력에 남는다.

        Returns:
            Dispatch id. 장부가 꺼져 있거나 실패하면 빈 문자열 — 호출자는 그 값을 그대로
            넘기기만 하면 되고, 빈 값이면 뒤따르는 정산이 조용히 넘어간다.
        """
        if not self.enabled:
            return ""
        try:
            task = task_create(
                self.root,
                self.run_id,
                f"{role} — {why}"[:500],
                deps=[self._ok_turn_task] if self._ok_turn_task else [],
                unit_id=role,
            )
        except Exception as exc:
            self._note(f"open_turn({role}) task", exc)
            return ""
        try:
            dispatch = open_dispatch(
                self.root,
                task["id"],
                worker=f"{self.qid}:{role}",
                role=role,
                agent=agent,
                model=model,
            )
        except Exception as exc:
            self._note(f"open_turn({role}) dispatch", exc)
            self._fold(task["id"])  # 배차 없는 Task 를 남기면 Run 이 영영 미완으로 보인다
            return ""
        self._turn_task = task["id"]
        self._turn_dispatch = dispatch["id"]
        if role.startswith("WORKER"):
            self._worker_task = task["id"]
        return dispatch["id"]

    def _fold(self, task_id: str) -> None:
        """배차되지 못한 Task 를 실패로 접는다 — 고아 Task 가 Run 을 미완으로 남기지 않게."""
        try:
            task_update(self.root, task_id, status="failed")
        except Exception as exc:
            self._note("fold", exc)

    def settle_turn(self, dispatch_id: str, outcome: str, *, summary: str = "", files: list[str] | None = None) -> None:
        """역할 턴을 끝낸다. 실패면 회로 차단 규칙이 재시도 여지를 정한다."""
        if not (self.enabled and dispatch_id):
            return
        try:
            dispatch_settle(self.root, dispatch_id, outcome, summary=summary[:2000], files_modified=files)
        except Exception as exc:
            self._note("settle_turn", exc)
            return
        if outcome == "succeeded" and dispatch_id == self._turn_dispatch:
            self._ok_turn_task = self._turn_task

    # ── 배정 단위 ──────────────────────────────────────────────────────────────

    def register_units(self, units: list[dict]) -> None:
        """계획의 배정 단위를 Task 로 만든다. 의존은 계획이 선언한 `access` 그대로다.

        **선행 단위를 먼저 만든다.** `task_create` 는 이미 존재하는 Task 만 의존으로 받으므로,
        계획이 단위 2 를 1 보다 앞에 적어 두면(`access:[1]`) 목록 순서대로 만들 때 그 의존이
        조용히 사라진다 — 그러면 둘 다 ready 가 되어 순서가 있는 일이 병렬로 돈다. `topo_waves`
        로 위상 정렬한 뒤 만든다.

        같은 wave 를 재시도할 때 다시 불려도 이미 만든 단위는 건너뛴다 — 재시도마다 Task 를
        새로 만들면 시도 횟수가 Task 단위로 흩어져 회로 차단이 영영 안 걸린다.

        단위 하나의 실패는 그 단위만 장부에서 빠뜨린다. 예전에는 여기서 장부 전체를 껐는데,
        등록 실패 하나로 이후 역할 턴 기록까지 같이 잃는 것은 fail-open 의 범위가 너무 넓다.
        """
        if not self.enabled:
            return
        try:
            by_id = {str(unit.get("id")): unit for unit in units}
            deps_by_id = {uid: [str(d) for d in (unit.get("access") or [])] for uid, unit in by_id.items()}
            ordered = [uid for wave in topo_waves(list(by_id), deps_by_id) for uid in wave]
        except Exception as exc:
            # 순환 의존처럼 계획 전체가 못 쓰는 경우다. 단위별로 나눌 수 없어 통째로 건너뛴다.
            self._note("register_units plan", exc)
            return
        for uid in ordered:
            if uid in self._unit_task:
                continue
            deps = [self._unit_task[dep] for dep in deps_by_id[uid] if dep in self._unit_task]
            try:
                task = task_create(
                    self.root,
                    self.run_id,
                    str(by_id[uid].get("subtask") or "")[:500],
                    deps=deps,
                    unit_id=uid,
                    parent=self._worker_task,
                )
            except Exception as exc:
                self._note(f"register_units({uid})", exc)
                continue
            self._unit_task[uid] = task["id"]

    def open_unit(self, unit: dict, *, model: str = "", agent: str = "") -> str:
        """배정 단위 한 번의 시도를 연다."""
        if not self.enabled:
            return ""
        uid = str(unit.get("id"))
        task_id = self._unit_task.get(uid)
        if not task_id:
            return ""
        try:
            dispatch = open_dispatch(
                self.root,
                task_id,
                worker=f"{self.qid}:unit{uid}",
                role="worker",
                agent=agent,
                model=model,
            )
        except Exception as exc:
            self._note(f"open_unit({uid})", exc)
            return ""
        self._unit_dispatch[uid] = dispatch["id"]
        return dispatch["id"]

    def settle_unit(self, unit: dict, outcome: str, *, summary: str = "", files: list[str] | None = None) -> None:
        """배정 단위 시도를 끝낸다 — 워커의 완료 보고 형식으로.

        역할 턴(`settle_turn`)과 달리 `worker_done` 메일까지 보낸다. 역할 턴은 코디네이터가
        자기 손으로 돈 것이라 보고할 상대가 없지만, 배정 단위는 격리된 워커가 돈 것이라
        코디네이터가 우편함에서 결과를 읽는다. `open_unit` 을 안 거친 단위는 조용히 넘어간다.
        """
        if not self.enabled:
            return
        uid = str(unit.get("id"))
        dispatch_id = self._unit_dispatch.pop(uid, "")
        if not dispatch_id:
            return
        try:
            worker_done(
                self.root,
                self.run_id,
                self._unit_task.get(uid, ""),
                dispatch_id,
                outcome,
                subject=f"unit {uid} {outcome}",
                body=summary[:2000],
                files_modified=files,
                sender=f"{self.qid}:unit{uid}",
            )
        except Exception as exc:
            self._note(f"settle_unit({uid})", exc)

    def stop_unit(self, unit: dict) -> None:
        """배정 단위 시도를 중지로 표시한다 — 취소 경로 전용.

        취소는 실패가 아니다. 워커가 결과를 못 냈다는 점은 같지만 실패로 접으면 재시도 예산을
        소모시키고, 정산을 아예 안 하면 그 Dispatch 가 `ready` 로 남아 그 Task 는 다시 배차되지
        않는다. `stopped` 는 그 사이 자리다 — 시도는 끝났고 Task 는 접히지 않는다.
        """
        if not self.enabled:
            return
        uid = str(unit.get("id"))
        dispatch_id = self._unit_dispatch.pop(uid, "")
        if not dispatch_id:
            return
        try:
            dispatch_mark(self.root, dispatch_id, "stopped")
        except Exception as exc:
            self._note(f"stop_unit({uid})", exc)

    # ── 코디네이터 답변 예산 ───────────────────────────────────────────────────

    def spend_model_answer(self) -> bool:
        """코디네이터 모델 답변 한 번을 예산에서 뺀다. 예산이 남아 있었으면 True.

        예산이 퀘스트 수명인 이유는 `CoordinatorLoop` 가 역할 턴마다 새로 세워지기 때문이다.
        상한을 고리에 두면 턴마다 리셋되어 실질 상한이 턴 수만큼 곱해진다.
        """
        with self._answer_lock:
            if self._model_answers >= _MAX_MODEL_ANSWERS:
                return False
            self._model_answers += 1
            return True

    def ask_handler(self, unit: dict | None = None, *, timeout_ms: int = 120_000):
        """워커 세션에 붙일 `ask_coordinator` 핸들러를 만든다.

        핸들러는 질문을 우편함에 넣고 답을 기다린다. 기다리는 쪽이 워커 스레드이고 답하는 쪽은
        `CoordinatorLoop` 의 데몬 스레드라 교착이 아니다 — 고리가 안 돌고 있으면 시간이 다 되어
        "가정을 명시하고 진행하라" 가 돌아간다. 침묵으로 끝나는 갈래는 없다.

        Args:
            unit: 배정 단위. 주면 질문이 그 단위의 Task·Dispatch 에 귀속된다. 단일 Worker 턴이면
                None 이고 그때는 역할 턴에 귀속된다.
        """

        def handler(inp: dict) -> str:
            question = str(inp.get("question") or "").strip()
            if not question:
                return "질문이 비어 있다 — 무엇을 정해 달라는 것인지 한 문장으로 적어라."
            if not self.enabled:
                return self._unanswered()
            tried = str(inp.get("tried") or "").strip()
            uid = str(unit.get("id")) if unit else ""
            body = f"{question}\n\n(이미 시도한 것: {tried})" if tried else question
            try:
                message = ask(
                    self.root,
                    self.run_id,
                    body,
                    options=[str(o) for o in (inp.get("options") or [])][:6],
                    sender=f"{self.qid}:unit{uid}" if uid else f"{self.qid}:worker",
                    task_id=self._unit_task.get(uid) or self._turn_task,
                    dispatch_id=self._unit_dispatch.get(uid) or self._turn_dispatch,
                    timeout_ms=timeout_ms,
                )
            except Exception as exc:
                self._note("ask", exc)
                return self._unanswered()
            return str(message.get("answer") or "") or self._unanswered()

        return handler

    @staticmethod
    def _unanswered() -> str:
        return (
            "코디네이터의 답을 받지 못했다. 가장 보수적인 선택을 하고, 그 선택을 `가정:` 으로 "
            "명시한 뒤 배정된 범위 안에서 진행하라."
        )

    # ── 코디네이터 ─────────────────────────────────────────────────────────────

    def drain(self, answer) -> list[dict]:
        """우편함을 비운다 — 질문에는 답하고, 나머지는 호출자에게 돌려준다.

        Args:
            answer: 질문 하나를 받아 답 문자열을 만드는 호출 가능 객체. 빈 문자열을 돌려주면
                그 질문은 답하지 않고 남는다(워커가 계속 기다린다는 뜻이므로, 답을 지어내는
                것보다 낫다).

        Returns:
            질문이 아닌 메일 목록 — worker_done·escalation·status 등. 코디네이터가 읽고
            보고에 쓴다.
        """
        if not self.enabled:
            return []
        try:
            batch = mail_check(self.root, self.run_id, timeout_ms=_DRAIN_TIMEOUT_MS)
            rest = []
            for message in batch["messages"]:
                if message["type"] == "question" and message.get("answered_at") is None:
                    text = answer(message) if answer else ""
                    if text:
                        reply(self.root, message["id"], text)
                else:
                    rest.append(message)
            if batch["delivery_id"]:
                mail_check(self.root, self.run_id, ack=batch["delivery_id"])
            return rest
        except Exception as exc:
            self._note("drain", exc)
            return []

    def blocked_on(self) -> list[dict]:
        """아직 답이 안 달린 질문 — 순환이 왜 멈춰 있는지를 보고에 실을 자리."""
        if not self.enabled:
            return []
        try:
            return pending_questions(self.root, self.run_id)
        except Exception as exc:
            self._note("blocked_on", exc)
            return []

    def gate(self, question: str, options: list[str] | None = None) -> str:
        """코디네이터가 다음 갈래를 고를 자리를 만든다. 돌려주는 값은 게이트 id 다."""
        if not self.enabled:
            return ""
        try:
            return gate_create(self.root, self.run_id, question, task_id=self._turn_task, options=options)["id"]
        except Exception as exc:
            self._note("gate", exc)
            return ""

    def escalate(self, reason: str) -> None:
        """Odin 결정이 필요하다고 장부에 남긴다."""
        if not self.enabled:
            return
        try:
            escalate(self.root, self.run_id, reason, task_id=self._turn_task, dispatch_id=self._turn_dispatch)
        except Exception as exc:
            self._note("escalate", exc)

    def close(self) -> None:
        """Run 을 닫고 이 장부를 끈다. 퀘스트가 끝나면 장부도 끝난다.

        `enabled` 를 함께 내리는 것이 요점이다. Heimdall 은 REPL 에서 장수하므로, 닫힌 Run 을
        가리킨 채 켜져 있는 장부가 남으면 다음 경로가 끝난 Run 에 일감을 쌓는다.
        """
        if not self.enabled:
            return
        self.enabled = False
        try:
            run_close(self.root, self.run_id)
        except Exception as exc:
            self._note("close", exc)


class CoordinatorLoop:
    """wave 가 도는 동안 워커의 질문에 답하는 코디네이터 — 데몬 스레드 하나.

    병렬 wave 에서는 코디네이터 스레드가 `_execute_pending` 안에서 future 를 기다리므로 우편함을
    볼 수 없다. 그동안 질문한 워커는 답을 못 받고 멈춰 있게 되는데, 그 상태가 곧 교착이다.
    이 고리가 그 사이를 맡는다: 질문이 오면 답하고, 답할 수 없으면 **가정을 명시하고 진행하라**고
    말한다. 침묵하지 않는 것이 계약이다 — 답 없는 질문은 워커를 타임아웃까지 세워 둔다.

    답의 출처는 둘이다. 먼저 결정론으로 답할 수 있는 것(자기 단위 밖 파일을 만져도 되는가 →
    안 된다)을 걸러 내고, 나머지만 코디네이터 모델에 묻는다. 모델 호출 상한은 장부가 든다 —
    이 고리는 역할 턴마다 새로 세워지므로 여기 두면 턴마다 리셋된다.
    """

    _POLL_SECONDS = 0.5

    def __init__(self, hd: Heimdall, ledger: BifrostLedger, request: str) -> None:
        self._hd = hd
        self._ledger = ledger
        self._request = request
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 우편함을 한 번에 한 스레드만 훑게 한다. `__exit__` 은 join 결과와 무관하게 한 번 더
        # 훑는데, 데몬 스레드가 모델 호출 안에서 5초를 넘기면 둘이 같은 질문 목록을 함께 본다.
        self._drain_lock = threading.Lock()
        self._done: set[str] = set()  # 이미 답한 질문 id — 같은 질문에 모델을 두 번 안 부른다
        self.answered: list[tuple[str, str]] = []  # (질문, 답) — 최종 보고에 표시된다

    def __enter__(self) -> CoordinatorLoop:
        if self._ledger.enabled:
            self._thread = threading.Thread(target=self._loop, name="bifrost-coordinator", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        # 스레드가 멈춘 뒤 남은 질문을 한 번 더 훑는다 — 마지막 순간에 들어온 것이 안 묻힌다.
        self._drain_once()

    def _loop(self) -> None:
        while not self._stop.wait(self._POLL_SECONDS):
            self._drain_once()

    def _drain_once(self) -> None:
        with self._drain_lock:
            for question in self._ledger.blocked_on():
                qid = str(question.get("id") or "")
                if qid in self._done:
                    continue
                self._done.add(qid)
                self._answer_one(question)

    def _answer_one(self, question: dict) -> None:
        """질문 하나에 답한다. 실패는 이 질문에서 끝난다 — 여기서 예외를 올리면 wave 가 죽는다.

        루프가 아니라 이 안에서 잡는 것이 요점이다. 예전에는 `reply` 예외 하나가 for 루프 전체를
        끊어 그 라운드의 남은 질문들이 답을 못 받았다.
        """
        try:
            answer = self._answer(question)
            reply(self._ledger.root, question["id"], answer)
        except Exception as exc:
            self._ledger._note("coordinator reply", exc)
            return
        self.answered.append((question.get("body") or "", answer))

    def _answer(self, question: dict) -> str:
        text = str(question.get("body") or "")
        options = list((question.get("payload") or {}).get("options") or [])
        settled = self._deterministic(text)
        if settled:
            return settled
        if not self._ledger.spend_model_answer():
            return "코디네이터 답변 예산 소진. 가장 보수적인 선택을 하고, 그 선택을 `가정:` 으로 명시한 뒤 진행하라."
        try:
            return self._ask_model(text, options).strip() or self._fallback()
        except Exception:
            return self._fallback()

    def _deterministic(self, text: str) -> str:
        """묻지 않고도 아는 것 — 규율이 이미 정해 둔 답은 모델을 안 부른다."""
        lowered = text.lower()
        if any(word in lowered for word in ("다른 단위", "other unit", "남의 파일", "outside my scope")):
            return (
                "아니다. 배정된 단위의 파일만 수정하라 (Canon 7). 다른 단위의 파일이 필요하면 "
                "그 사실을 결과에 적고 네 범위 안에서 할 수 있는 데까지만 하라."
            )
        return ""

    def _ask_model(self, text: str, options: list[str]) -> str:
        system = (
            "You are the coordinator of a Trinity quest. A worker is blocked and asked one question. "
            "Answer it directly in the worker's language, in at most three sentences. Decide — do not "
            "restate the question or hand it back. If the answer is genuinely not knowable from the "
            "request, tell the worker which assumption to take and to record it as `가정:`."
        )
        user = f"Quest request: {self._request[:1500]}\n\nWorker question: {text[:1500]}"
        if options:
            user += "\n\nCandidate answers the worker sees: " + "; ".join(str(o) for o in options[:6])
        return self._hd._complete_text(system, user, max_tokens=400)

    def _fallback(self) -> str:
        return (
            "코디네이터가 답을 정하지 못했다. 가장 보수적인 선택을 하고, 그 선택을 `가정:` 으로 "
            "명시한 뒤 배정된 범위 안에서 진행하라."
        )


class _NullLedgerShapeMixin:
    """비활성 장부도 형상은 고른다 — 판정이 순수 함수라 장부 없이도 답이 같다."""

    shape = ""

    def choose_shape(self, cls: dict, *, unit_count: int = 0, specialists: list[str] | None = None) -> dict:
        decision = choose_shape(
            write_expected=bool(cls.get("write_expected", True)),
            task_class=str(cls.get("task_class") or "deep"),
            parallel_requested=bool(cls.get("parallel_requested")),
            unit_count=unit_count,
            specialists=list(specialists or []),
        )
        self.shape = decision["shape"]
        return decision


class _NullLedger(_NullLedgerShapeMixin):
    """장부가 아직 안 선 경로가 쓰는 비활성 장부.

    Heimdall 은 퀘스트 밖에서도 wave 를 돌릴 수 있고(재개 경로), 테스트 대역은 TrinityRun 을
    거치지 않는다. 그 경로마다 `if ledger:` 를 두는 대신 아무 일도 안 하는 대역을 기본값으로
    세운다 — 분기가 없으면 어느 갈래를 빠뜨릴 일도 없다.
    """

    enabled = False
    run_id = ""
    root = ""
    notes: list[str] = []

    def _note(self, where: str, exc: BaseException) -> None:
        return None

    def spend_model_answer(self) -> bool:
        return False

    def open_turn(self, *args, **kwargs) -> str:
        return ""

    def settle_turn(self, *args, **kwargs) -> None:
        return None

    def register_units(self, *args, **kwargs) -> None:
        return None

    def open_unit(self, *args, **kwargs) -> str:
        return ""

    def settle_unit(self, *args, **kwargs) -> None:
        return None

    def stop_unit(self, *args, **kwargs) -> None:
        return None

    def drain(self, *args, **kwargs) -> list[dict]:
        return []

    def blocked_on(self) -> list[dict]:
        return []

    def gate(self, *args, **kwargs) -> str:
        return ""

    def escalate(self, *args, **kwargs) -> None:
        return None

    def close(self) -> None:
        return None

    def ask_handler(self, *args, **kwargs):
        def handler(inp: dict) -> str:
            return BifrostLedger._unanswered()

        return handler


NULL_LEDGER = _NullLedger()
