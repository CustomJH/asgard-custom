"""코디네이터 — 준비된 일감을 배차하는 감독 고리 + 워커 질문에 답하는 데몬 스레드 하나."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from ....orchestration import reply

if TYPE_CHECKING:
    from ..core import Heimdall
    from .ledger import BifrostLedger

# 감독 고리 한 번이 볼 수 있는 준비 묶음의 수. Orca 계약은 의존을 3~4 단계보다 깊게 두지
# 말라고 하므로 그 두 배면 정상 그래프를 다 덮는다 — 상한은 폭주 방지용이다.
_SUPERVISE_ROUNDS = 8


class CoordinatorLoop:
    """코디네이터 — 준비된 일감을 배차하는 감독 고리 + 워커 질문에 답하는 데몬 스레드 하나.

    병렬 wave 에서는 코디네이터 스레드가 `_execute_pending` 안에서 future 를 기다리므로 우편함을
    볼 수 없다. 그동안 질문한 워커는 답을 못 받고 멈춰 있게 되는데, 그 상태가 곧 교착이다.
    데몬 스레드가 그 사이를 맡는다: 질문이 오면 답하고, 답할 수 없으면 **가정을 명시하고
    진행하라**고 말한다. 침묵하지 않는 것이 계약이다 — 답 없는 질문은 워커를 타임아웃까지
    세워 둔다.

    답의 출처는 둘이다. 먼저 결정론으로 답할 수 있는 것(자기 단위 밖 파일을 만져도 되는가 →
    안 된다)을 걸러 내고, 나머지만 코디네이터 모델에 묻는다. 모델 호출 상한은 장부가 든다 —
    이 고리는 역할 턴마다 새로 세워지므로 여기 두면 턴마다 리셋된다.

    **묻는 스레드와 답하는 스레드는 달라야 한다.** `ask_coordinator` 핸들러는 워커 스레드에서
    돌며 답을 기다리는데, 같은 스레드가 답할 차례를 갖고 있으면 그 기다림은 영영 안 끝난다.
    그래서 답은 데몬 스레드만 하고, `supervise` 는 부른 쪽 스레드에서 돌면서 질문에 손대지
    않는다 (`drain(None)`).
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

    # ── 감독 고리 ──────────────────────────────────────────────────────────────

    def supervise(self, dispatch, *, rounds: int = _SUPERVISE_ROUNDS, wait_ms: int = 0) -> dict:
        """준비된 일감을 읽어 배차하고 정산을 기다린다 — Orca 의 감독 고리.

        한 바퀴는 넷이다: `task_list(ready=True)` 로 준비 묶음을 읽고, 실행자에게 넘기고,
        정산 메일을 거두고, 다시 읽는다. 선행 의존이 안 끝난 일감은 `ready` 가 아니므로 실행자
        손에 아예 안 들어간다 — 준비도를 계획에서 다시 추론하지 않고 장부에서 읽는 이유가 그것이다.

        **fail-open 이 이 고리의 첫 규칙이다.** 준비도를 못 읽었으면(장부가 꺼졌거나 조회가
        실패했으면) 감독 없이 한 번 배차하고 끝낸다. 장부는 파생 기록이라, 그것을 못 읽었다고
        일을 안 돌리면 부기 고장 하나가 퀘스트를 잃게 만든다.

        실패한 일감을 이 고리 안에서 자동 재배차하지 않는다. 같은 묶음이 다시 준비되면 그대로
        끝낸다 — 재시도는 순환의 WORKER_RETRY 전이가 정하는 것이고, 시도 예산은 회로 차단이
        든다 (`orchestration.dispatch.open_dispatch`).

        Args:
            dispatch: 준비된 Task 행 목록을 받아 실행하는 호출 가능 객체. 예외는 그대로
                올린다 — 실행자의 실패는 이 턴의 실패이고, 역할 턴 정산이 그것을 적는다.
            rounds: 볼 준비 묶음의 최대 수.
            wait_ms: 정산 메일을 기다릴 시간. 실행자가 동기로 끝나면 0 이면 된다.

        Returns:
            `{"rounds": int, "dispatched": [task_id], "reports": [...], "escalations": [...],
            "supervised": bool}`. `rounds` 는 감독한 묶음의 수다. `supervised` 가 False 면
            준비도를 읽을 자리가 없어 감독 없이 한 번만 돌렸다는 뜻이다.
        """
        dispatched: list[str] = []
        reports: list[dict] = []
        escalations: list[dict] = []
        rounds_run = 0
        previous: set[str] = set()
        counted: set[str] = set()
        for round_no in range(1, max(1, rounds) + 1):
            ready = self._ledger.ready_tasks()
            if round_no == 1 and not ready:
                # 준비도를 못 읽었거나(None) 장부에 아직 아무것도 안 올라갔다([]). 둘을 여기서
                # 가를 수 없으므로 실행자를 한 번 부른다 — 무엇이 남았는지는 실행자가 정한다.
                dispatch([])
                return {"rounds": 0, "dispatched": [], "reports": [], "escalations": [], "supervised": False}
            if not ready:
                break  # 첫 묶음을 이미 감독했다. 준비된 것이 없거나 못 읽었으면 여기서 끝낸다.
            waiting = {str(task["id"]) for task in ready}
            if waiting == previous:
                break  # 새로 준비된 일감이 없다 — 같은 묶음을 다시 밀어 넣으면 고리가 안 끝난다
            previous = waiting
            rounds_run = round_no
            dispatched += [str(task["id"]) for task in ready]
            dispatch(ready)
            settled, raised = self._settlement(counted, wait_ms)
            reports += settled
            escalations += raised
            if escalations:
                # 개입이 필요하다 — 다음 묶음을 밀어 넣지 않는다. 그 멈춤을 **갚아야 할 결정**
                # 으로 장부에 남긴다: 여기서 코디네이터는 다음 갈래를 고른 것이 아니라 못 고른
                # 것이고, 그 미결이 어디에도 안 적히면 멈춘 이유가 화면 한 줄로만 지나간다.
                self._halt_gate(round_no, escalations)
                break
        return {
            "rounds": rounds_run,
            "dispatched": dispatched,
            "reports": reports,
            "escalations": escalations,
            "supervised": True,
        }

    def _halt_gate(self, round_no: int, escalations: list[dict]) -> None:
        """멈춘 wave 를 결정 게이트로 남긴다 — 코디네이터가 못 고른 갈래의 자리.

        **워커의 escalation 과 코디네이터의 게이트는 다른 것이다** (`board.gate_create` 의 계약).
        escalation 은 워커가 "개입이 필요하다" 고 보낸 **신호**이고, 그 신호를 받아 다음 준비
        묶음을 안 밀어 넣기로 한 것은 코디네이터의 판단이다. 그런데 그 다음 — 이어서 배차할지,
        계획을 다시 세울지, 사람이 이어받을지 — 는 아직 아무도 안 골랐다. 게이트가 적는 것은
        신호가 아니라 그 **미결**이다. 게이트를 닫아도 워커의 요청에 답이 달리지 않고, 요청에
        답해도 게이트는 안 닫힌다.

        **기다리지 않는다.** 헤드리스 퀘스트에는 답할 사람이 붙어 있지 않으므로 여기서 답을
        기다리면 `asgard run` 이 통째로 멈춘다. 게이트는 관문이 아니라 갚아야 할 결정의 **기록**
        이다 — `asgard siege gates` 가 보여 주고 `asgard siege decide` 가 닫는다.

        게이트를 못 적어도 감독 고리는 하던 대로 멈추고 나간다. 이 계층은 파생 기록이라
        (이 파일의 fail-open 계약) 부기 하나 때문에 진행을 잃는 교환은 성립하지 않는다.
        """
        subjects = " / ".join(str(m.get("subject") or "").strip() or "(제목 없음)" for m in escalations[:3])
        self._ledger.gate(
            f"워커 개입 요청 {len(escalations)}건으로 {round_no}번째 묶음에서 wave 를 멈췄어요 — {subjects[:300]}. "
            "남은 갈래를 골라 주세요.",
            [
                "요청에 답을 주고 남은 단위를 이어서 배차",
                "계획을 다시 세워 재배정",
                "여기서 멈추고 사람이 이어받기",
            ],
            once="wave-halt",
        )

    def _settlement(self, counted: set[str], wait_ms: int) -> tuple[list[dict], list[dict]]:
        """이번 바퀴의 정산 메일을 (완료 보고, 개입 요청)으로 가른다.

        `counted` 는 이미 센 메시지 id 이고 호출자가 바퀴 사이에 들고 있다. 답 못 한 질문이
        남은 묶음은 확인 처리되지 않아 다음 바퀴에 다시 오므로(`BifrostLedger.drain`),
        id 로 거르지 않으면 완료 보고 하나가 두 번 세어진다.
        """
        reports: list[dict] = []
        escalations: list[dict] = []
        for message in self._ledger.drain(None, wait_ms=wait_ms):
            if str(message["id"]) in counted:
                continue
            counted.add(str(message["id"]))
            if message["type"] == "worker_done":
                reports.append(message)
            elif message["type"] == "escalation":
                escalations.append(message)
        return reports, escalations

    # ── 답변 ───────────────────────────────────────────────────────────────────

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
