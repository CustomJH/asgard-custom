"""siege — 배차 장부를 사람이 읽는 표면.

이름은 `ref/asgard-helios` 의 어휘를 따른다. 거기서 `orchestration` 은 **기제**(설정 절,
verify-fix 루프·병렬 상한)이고 `siege` 는 **사람이 부르는 모드**다. 둘이 같은 것을 가리키는
다른 층의 이름이라 여기서도 그대로 갈라 둔다 — 도메인 패키지는 `asgard.orchestration`,
사람이 치는 명령은 `asgard siege`.

퀘스트가 끝난 뒤 "왜 이 모양으로 돌았고, 어느 시도가 몇 번 만에 붙었고, 무엇이 답을 못
받았는가" 에 답하는 자리다. 장부의 정본은 `orchestration` 패키지가 들고 있고 여기서는
질의와 표시만 한다 — 상태를 바꾸는 명령은 순환이 멈춰 선 자리를 사람이 손으로 푸는 둘
(`answer`·`decide`)과 파생 상태를 지우는 복구(`reset`)뿐이다.

퀘스트 로그(`asgard quest`)와 겹치지 않는다. 저쪽은 **무엇이 검증됐는가**(사건·판정·증거)를
기록하고, 이쪽은 **누가 언제 무엇을 시도했는가**(배차·재시도·질문)를 기록한다.
"""

from __future__ import annotations

import json
import os

from .. import orchestration as orc
from .. import ui
from .health import _project_root

# 상태별 글리프. 색이 아니라 모양으로 구분한다 — 색 능력이 없는 터미널에서도 읽혀야 한다.
_TASK_MARK = {
    "pending": "·",
    "ready": "○",
    "dispatched": "◐",
    "completed": "●",
    "failed": "✘",
    "blocked": "⊘",
}
_GATE_MARK = {"open": "◆", "resolved": "◇"}
_SPEC_HEAD = 60  # 목록 한 줄이 드는 만큼


def _root() -> str:
    """장부가 있는 프로젝트 루트. 저장소의 다른 명령(`ticket`·`craft`·`health`)과 같은 판정이다.

    현재 디렉터리를 그대로 쓰면 하위 디렉터리에서 친 조회가 "배차 장부가 비어 있어요" 라는
    거짓 보고를 낸다 — 장부는 프로젝트 루트의 `.asgard/` 에 있다.
    """
    return _project_root(os.getcwd())


def _dump(payload, json_out: bool) -> None:
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def run_runs(json_out: bool = False, limit: int = 20) -> int:
    """Run 목록 — 최근 것이 위."""
    ui.set_quiet(json_out)
    rows = orc.run_list(_root())[: max(1, limit)]
    if json_out:
        _dump(rows, True)
        return 0
    if not rows:
        ui.step(ui.dim("배차 장부가 비어 있어요 — 아직 오케스트레이션으로 돈 퀘스트가 없네요."))
        return 0
    for row in rows:
        shape = row.get("shape") or "-"
        state = "열림" if row["status"] == "open" else "닫힘"
        ui.step(f"{row['id']}  {shape:<6} {state:<4} {ui.dim(ui.oneline(row.get('objective') or '', _SPEC_HEAD))}")
    return 0


def run_show(run_id: str, json_out: bool = False) -> int:
    """Run 하나의 DAG — Task 별 상태·의존·시도 횟수.

    Returns:
        0 이면 찾았고, 2 면 그런 Run 이 없다.
    """
    ui.set_quiet(json_out)
    root = _root()
    run = orc.run_show(root, run_id)
    if run is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2
    tasks = orc.task_list(root, run_id)
    # Task 행에 시도 목록을 얹은 표시용 사본. 값 종류가 섞이므로 행 타입을 열어 둔다.
    detail: list[dict] = [{**task, "attempts_detail": orc.dispatch_history(root, task["id"])} for task in tasks]
    if json_out:
        _dump({"run": run, "tasks": detail, "gates": orc.gate_list(root, run_id=run_id)}, True)
        return 0

    ui.phase(f"{run_id} · {run.get('shape') or '-'}")
    if run.get("shape_why"):
        ui.step(ui.dim(run["shape_why"]))
    if any(str(task.get("unit_id") or "").isdigit() for task in tasks):
        # 배정 단위의 의존은 계획의 `access` 보다 넓다 — `heimdall.bifrost.register_units` 가
        # 실행 일정(`planning._plan_waves`)을 그대로 옮기므로 파일 겹침으로 밀린 것도 여기 보인다.
        # 안 적으면 읽는 사람이 화살표를 전부 계획이 선언한 의존으로 읽는다.
        ui.step(ui.dim("배정 단위의 ←는 wave 일정이에요 — 계획의 access와 파일 겹침을 함께 반영한 결과예요."))
    label = {task["id"]: (task.get("unit_id") or task["id"][-6:]) for task in tasks}
    for task in detail:
        mark = _TASK_MARK.get(task["status"], "?")
        deps = ", ".join(label.get(d, d[-6:]) for d in task["deps"])
        tries = len(task["attempts_detail"])
        line = f"  {mark} {label[task['id']]:<16} {task['status']:<10}"
        if tries > 1:
            line += f" 시도 {tries}회"
        if deps:
            line += f" ← {deps}"
        ui.step(line)
        ui.step(ui.dim(f"      {ui.oneline(task['spec'], _SPEC_HEAD)}"))
    gates = orc.gate_list(root, run_id=run_id, status="open")
    if gates:
        ui.step(ui.dim(f"열린 결정 게이트 {len(gates)}건"))
    return 0


def run_inbox(run_id: str, json_out: bool = False, limit: int = 50) -> int:
    """Run 우편함 — 확인 여부와 무관한 최근 메일. 읽기만 하며 재생 계약을 건드리지 않는다."""
    ui.set_quiet(json_out)
    root = _root()
    if orc.run_show(root, run_id) is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2
    messages = orc.inbox(root, run_id, limit=limit)
    if json_out:
        _dump(messages, True)
        return 0
    if not messages:
        ui.step(ui.dim("메일이 없어요."))
        return 0
    for message in reversed(messages):
        answered = "" if message["type"] != "question" else (" [답함]" if message["answered_at"] else " [대기]")
        ui.step(f"  {message['type']:<12}{answered} {ui.dim(ui.oneline(message.get('subject') or '', _SPEC_HEAD))}")
    return 0


def run_blocked(json_out: bool = False) -> int:
    """지금 답을 기다리는 모든 질문 — 무엇이 순환을 멈춰 세웠는지 한눈에 본다."""
    ui.set_quiet(json_out)
    root = _root()
    waiting = []
    for run in orc.run_list(root, status="open"):
        for question in orc.pending_questions(root, run["id"]):
            waiting.append({"run": run["id"], **question})
    if json_out:
        _dump(waiting, True)
        return 0
    if not waiting:
        ui.step(ui.dim("답을 기다리는 질문이 없어요."))
        return 0
    for question in waiting:
        ui.step(f"  {question['run']}  {ui.oneline(question.get('body') or '', _SPEC_HEAD)}")
    return 0


def run_answer(message_id: str, answer: str, json_out: bool = False) -> int:
    """대기 중인 워커 질문에 오딘이 직접 답한다.

    코디네이터 고리가 답하지 못한 질문(예산 소진·모델 실패)이 여기 남는다. 워커가 이미
    타임아웃으로 진행했을 수 있으므로, 이 답은 다음 턴의 맥락이지 그 워커를 되돌리지 않는다.
    """
    ui.set_quiet(json_out)
    try:
        message = orc.reply(_root(), message_id, answer)
    except orc.OrchestrationError as exc:
        ui.fail(str(exc))
        return 2
    if json_out:
        _dump(message, True)
        return 0
    ui.ok(f"답을 남겼어요 — {message_id}")
    return 0


def run_gates(run_id: str = "", json_out: bool = False, all_gates: bool = False) -> int:
    """사람의 선택을 기다리는 결정 게이트.

    `blocked` 의 짝이 아니라 반대편이다 — 저쪽은 막힌 워커가 코디네이터에게 묻는 것이고
    이쪽은 코디네이터가 다음 갈래를 고르려고 스스로 멈춘 것이다(`board.gate_create` 참조).
    Run 을 안 주면 장부 전체를 훑는다: 게이트 행이 run_id 를 들고 있어 Run 별로 나눠 물을
    까닭이 없고, 닫힌 Run 에 열린 채 남은 게이트도 그래야 보인다 — 아무도 안 볼 자리에서
    기다리는 그것이 가장 닫아야 할 것이다.

    Returns:
        0 이면 훑었고, 2 면 준 Run 이 없다.
    """
    ui.set_quiet(json_out)
    root = _root()
    if run_id and orc.run_show(root, run_id) is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2
    gates = orc.gate_list(root, run_id=run_id, status="" if all_gates else "open")
    if json_out:
        _dump(gates, True)
        return 0
    if not gates:
        ui.step(ui.dim("결정 게이트가 없어요." if all_gates else "답을 기다리는 결정 게이트가 없어요."))
        return 0
    for gate in gates:
        mark = _GATE_MARK.get(gate["status"], "?")
        # 게이트 id 를 반드시 적는다 — `decide` 가 받는 유일한 손잡이라, 빼면 목록을 보고도 못 닫는다.
        ui.step(f"  {mark} {gate['id']}  {gate['run_id']}  {ui.oneline(gate.get('question') or '', _SPEC_HEAD)}")
        if gate["options"]:
            ui.step(ui.dim(f"      {' / '.join(gate['options'])}"))
        if gate.get("resolution"):
            ui.step(ui.dim(f"      → {ui.oneline(gate['resolution'], _SPEC_HEAD)}"))
    return 0


def run_decide(gate_id: str, resolution: str, json_out: bool = False) -> int:
    """열린 결정 게이트를 오딘의 선택으로 닫는다.

    코디네이터 고리가 못 고른 갈래(예산 소진·모델 실패)가 게이트로 남는다. `answer` 와 달리
    이건 다음 턴의 맥락이 아니라 진행 조건이다 — 게이트가 열려 있는 동안 코디네이터는 그
    갈래를 고르지 못한 채로 있다.

    Returns:
        0 이면 닫았고, 2 면 닫을 게이트가 없다.
    """
    ui.set_quiet(json_out)
    try:
        gate = orc.gate_resolve(_root(), gate_id, resolution)
    except orc.OrchestrationError:
        # 도메인은 "없음" 과 "이미 닫힘" 을 한 오류로 답한다. 사람에게도 같은 말이라 굳이 안 가른다.
        ui.fail(f"열린 결정 게이트가 아니에요: {gate_id} — 이미 닫혔거나 없는 게이트예요.")
        return 2
    if json_out:
        _dump(gate, True)
        return 0
    ui.ok(f"게이트를 닫았어요 — {gate_id}: {ui.oneline(resolution, _SPEC_HEAD)}")
    return 0


def run_reset(json_out: bool = False, *, tasks: bool = False, messages: bool = False, all_: bool = False) -> int:
    """배차 장부를 지운다. 퀘스트 로그는 그대로 — 이것은 파생 상태다.

    아무 범위도 안 주면(또는 `--all`) 오늘까지의 기본 동작 그대로 장부 파일 전체를 지운다.
    `--tasks`·`--messages` 는 그중 한 부분만 지운다 — Orca 의 `reset --tasks|--messages|--all`
    과 같은 자리다. 둘을 같이 주면 무엇을 지운 것인지 확인문이 설명할 수 없어 거부한다.

    Returns:
        0 이면 지웠고, 2 면 범위 조합이 잘못됐다(둘 이상을 같이 줬다).
    """
    ui.set_quiet(json_out)
    if sum((tasks, messages, all_)) > 1:
        ui.fail("--tasks·--messages·--all 은 하나만 골라요 — 같이 주면 무엇을 지운 건지 말할 수 없어요.")
        return 2
    root = _root()
    if tasks:
        removed = orc.reset_tasks(root)
        if json_out:
            _dump({"scope": "tasks", "removed": removed}, True)
            return 0
        ui.ok(f"Task를 지웠어요 — {removed}건. Run과 메일함은 그대로예요." if removed else "지울 Task가 없었어요.")
        return 0
    if messages:
        removed = orc.reset_messages(root)
        if json_out:
            _dump({"scope": "messages", "removed": removed}, True)
            return 0
        ui.ok(f"메일함을 비웠어요 — {removed}건. Run과 Task DAG는 그대로예요." if removed else "지울 메일이 없었어요.")
        return 0
    removed = orc.reset(root)
    if json_out:
        _dump({"scope": "all", "removed": removed, "path": orc.db_path(root)}, True)
        return 0
    ui.ok("배차 장부를 지웠어요." if removed else "지울 배차 장부가 없었어요.")
    return 0
