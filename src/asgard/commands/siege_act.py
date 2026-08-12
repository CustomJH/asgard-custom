"""siege — 배차를 사람이 **모는** 표면. 읽는 쪽은 `commands/siege.py` 가 맡는다.

두 모듈로 가른 이유는 책임이 다르기 때문이다. 저쪽은 끝난 뒤 되읽는 질의만 하고, 여기는
Run·Task·Dispatch·우편·게이트의 상태를 만든다. 한 파일에 두면 "이 명령이 장부를 바꾸는가"
를 파일 단위로 답할 수 없다.

이 표면이 없던 동안 `asgard.orchestration` 의 쓰기 절반은 `agent/heimdall/bifrost.py` 에서만
불렸다. 즉 네이티브 Trinity 루프가 도는 동안에만 장부가 적혔고, Claude Code·Cursor·Codex
모드에서는 같은 계약을 부를 자리가 아예 없었다 — 그 세 모드에서 `asgard siege` 는 언제나 빈
장부를 보여 준다. 여기의 명령들은 그 절반을 프로세스 밖으로 낸다: 호스트 도구의 에이전트도
사람도 같은 계약을 같은 문으로 부른다.

계약 셋은 도메인이 갖고 여기서는 안 되풀이한다:
  · `worker_done` 은 `mail.worker_done` 으로만 보낸다 — 메일과 배차 정산이 한 트랜잭션이다.
  · 한 Task 에 살아 있는 Dispatch 는 하나뿐이다 (`dispatch.open_dispatch`).
  · 끝난 Task 는 되살아나지 않는다 (`board.task_update`).

종료 코드는 둘뿐이다. 0 은 했고, 2 는 도메인이 거절했다(`OrchestrationError`). 거절을 0 으로
돌리면 스크립트와 호스트 에이전트가 실패한 배차를 성공으로 읽는다.
"""

from __future__ import annotations

import json
import os

from .. import orchestration as orc
from .. import ui
from .health import _project_root

_SPEC_HEAD = 60  # 목록 한 줄이 드는 만큼. `commands/siege.py` 와 같은 값이라 두 표면이 같은 폭으로 자른다.
# 검증 짝을 맡는 에이전트. 판정을 쓰기 가능한 손에게 주면 자기 diff 를 자기가 판정하므로,
# 이 자리는 Trinity 판정자로 고정한다 (AGENTS.md 의 검증 독립성).
_VERIFY_AGENT = "asgard-verifier"
# 한 번에 깔 수 있는 단위 수. 넘으면 그래프가 아니라 목록이고, 그만큼의 에이전트를 동시에
# 띄우면 호스트의 동시 실행 상한에 걸려 뒤쪽이 조용히 줄을 선다.
_PLAN_MAX_UNITS = 32


def _root() -> str:
    """장부가 있는 프로젝트 루트 — `commands/siege.py` 와 **같은 함수**(`health._project_root`)로 판정한다.

    형제 모듈에서 가져오지 않고 각자 부르는 이유는 `commands` 패키지가 같은 등급끼리의 임포트를
    금하기 때문이다(`tests/test_architecture.py`). 정본은 어차피 `_project_root` 하나이므로
    갈릴 여지는 없고, 실제로 안 갈렸는지는 두 표면 모두에서 시험한다.
    """
    return _project_root(os.getcwd())


def _dump(payload, json_out: bool) -> None:
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _fail(exc: orc.OrchestrationError) -> int:
    """도메인 거절을 사람 문장과 종료 코드 2 로 옮긴다. 문장은 도메인이 이미 해요체로 쓴다."""
    ui.fail(str(exc))
    return 2


def _emit(payload, json_out: bool, message: str) -> int:
    if json_out:
        _dump(payload, True)
        return 0
    ui.ok(message)
    return 0


def run_start(
    objective: str,
    *,
    quest_id: str = "",
    coordinator: str = "",
    shape: str = "",
    why: str = "",
    json_out: bool = False,
) -> int:
    """Run 을 연다 — 배차의 이름 공간이자 코디네이터 우편함.

    `quest_id` 를 주면 `run_bind` 로 간다: 그 퀘스트에 이미 열린 Run 이 있으면 새로 만들지 않고
    그것을 돌려준다. 이 갈래가 있어야 같은 퀘스트를 두 번 부른 에이전트가 Task 와 우편함을 Run
    둘로 가르지 않는다. 퀘스트를 안 주면 `run_create` 로 독립 Run 을 만든다.

    Returns:
        0 이면 열었고, 2 면 도메인이 거절했다(형상 값이 틀렸거나 퀘스트가 충돌했다).
    """
    ui.set_quiet(json_out)
    if shape and shape not in orc.SHAPES:
        ui.fail(f"형상은 {' / '.join(orc.SHAPES)} 중 하나예요: {shape}")
        return 2
    root = _root()
    try:
        # 이미 있었는지를 bind 앞에서 본다. 뒤에서는 못 가른다 — `run_bind` 는 새로 만든 Run 과
        # 찾아낸 Run 을 같은 모양으로 돌려준다. 안 가르면 두 번째 호출이 "열었어요" 라고 답해서,
        # 부른 쪽은 Run 이 둘 생겼다고 읽는다.
        reused = bool(quest_id) and orc.run_for_quest(root, quest_id) is not None
        if quest_id:
            run = orc.run_bind(root, quest_id, objective, coordinator=coordinator)
        else:
            run = orc.run_create(root, objective, coordinator=coordinator)
        if shape:
            orc.run_shape(root, run["id"], shape, why)
            run = orc.run_show(root, run["id"]) or run
    except orc.OrchestrationError as exc:
        return _fail(exc)
    if json_out:
        _dump({**run, "reused": reused}, True)
        return 0
    # Run id 를 반드시 적는다 — 뒤따르는 모든 명령이 받는 손잡이라, 빼면 열고도 못 쓴다.
    ui.ok(f"이 퀘스트의 Run을 이어 써요 — {run['id']}" if reused else f"Run을 열었어요 — {run['id']}")
    ui.step(ui.dim(f'    일감 만들기: `asgard siege add {run["id"]} "<할 일>"`'))
    return 0


def run_close_cmd(run_id: str, json_out: bool = False) -> int:
    """Run 을 닫는다. 닫힌 Run 에는 Task·게이트가 더 안 들어가고 배차도 안 열린다.

    Returns:
        0 이면 닫았고, 2 면 그런 Run 이 없다(이미 닫힌 Run 을 다시 닫는 것은 0 이다).
    """
    ui.set_quiet(json_out)
    root = _root()
    if orc.run_show(root, run_id) is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2
    changed = orc.run_close(root, run_id)
    return _emit(
        {"run": run_id, "closed": changed},
        json_out,
        f"Run을 닫았어요 — {run_id}" if changed else f"이미 닫혀 있었어요 — {run_id}",
    )


def run_add(
    run_id: str,
    spec: str,
    *,
    deps: list[str] | None = None,
    unit_id: str = "",
    parent: str = "",
    agent: str = "",
    verify: bool = False,
    json_out: bool = False,
) -> int:
    """일감 하나를 DAG 에 넣는다. `deps` 가 있으면 pending, 없으면 곧장 ready 로 난다.

    의존은 **같은 Run 안의 task id** 여야 한다. 배정 단위 이름(`--unit`)으로는 못 건다 —
    도메인이 id 로만 검사하므로, 단위 이름을 넣으면 "이 Run에 없는 의존" 으로 거절된다.

    `verify` 는 이 일감 하나에만 의존하는 검증 일감을 짝으로 세운다. 의존을 하나로 묶는 것이
    요점이다 — 단위 A 의 검증은 A 가 끝나는 순간 ready 가 되고, 단위 B 가 아직 도는 중이어도
    기다리지 않는다. 검증을 맨 끝에 하나로 두면 그 병렬이 사라진다.

    Returns:
        0 이면 만들었고, 2 면 도메인이 거절했다(닫힌 Run·없는 의존·중복 단위).
    """
    ui.set_quiet(json_out)
    try:
        task = orc.task_create(
            _root(), run_id, spec, deps=list(deps or []), unit_id=unit_id, parent=parent, agent=agent
        )
        checker = _verify_task(run_id, task) if verify else None
    except orc.OrchestrationError as exc:
        return _fail(exc)
    if json_out:
        # 만든 일감을 그대로 최상위에 둔다. 검증 짝은 열쇠 하나로 얹을 뿐이라, `--verify` 를
        # 안 쓰던 호출자가 읽던 `["id"]` 자리가 그대로 남는다.
        _dump({**task, "verify": checker}, True)
        return 0
    ui.ok(f"일감을 만들었어요 — {task['id']} ({task['status']}){_agent_suffix(agent)}")
    ui.step(ui.dim(f"    {ui.oneline(spec, _SPEC_HEAD)}"))
    if checker is not None:
        ui.step(ui.dim(f"    검증 짝 {checker['id']} — {task['id']} 만 기다려요"))
    return 0


def _agent_suffix(agent: str) -> str:
    return f" → {agent}" if agent else ""


def _verify_task(run_id: str, task: dict) -> dict:
    """일감 하나를 판정할 검증 Task 를 그 일감에만 걸어 세운다."""
    return orc.task_create(
        _root(),
        run_id,
        f"verify: {task['spec']}",
        deps=[task["id"]],
        agent=_VERIFY_AGENT,
        kind="verify",
    )


def run_plan(run_id: str, units_json: str, json_out: bool = False) -> int:
    """단위 목록 하나로 그래프 전체를 깐다 — 배차 전에 모양을 적게 하는 자리.

    `add` 를 여러 번 치는 것과 결과는 같지만 값이 다르다. 손으로 치면 id 를 받아 다음 호출의
    `--dep` 에 옮겨야 해서, 의존을 적는 일이 귀찮은 만큼 자주 생략된다 — 그러면 남는 것은
    그래프가 아니라 평평한 목록이고, 무엇이 무엇을 기다리는지는 부르는 쪽 머릿속에만 있다.
    여기서는 의존을 **배열 색인**으로 적으므로 id 를 기다릴 일이 없다.

    단위 하나의 모양::

        {"spec": "무엇을", "agent": "asgard-thor", "deps": [0], "verify": true, "unit": "u1"}

    `deps` 는 같은 배열의 앞선 항목을 가리키는 색인이다. 뒤나 자기를 가리키면 순환이므로
    거절한다 — 도메인의 순환 검사보다 여기서 먼저 잡는 이유는, 절반만 만들어진 그래프를
    남기지 않기 위해서다.

    Returns:
        0 이면 깔았고, 2 면 JSON 이 틀렸거나 도메인이 거절했다.
    """
    ui.set_quiet(json_out)
    root = _root()
    try:
        units = _parse_units(units_json)
    except ValueError as exc:
        ui.fail(str(exc))
        return 2
    if orc.run_show(root, run_id) is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2

    created: list[dict] = []
    checkers: list[dict] = []
    try:
        for unit in units:
            deps = [created[d]["id"] for d in unit["deps"]]
            task = orc.task_create(
                root,
                run_id,
                unit["spec"],
                deps=deps,
                unit_id=unit["unit"],
                agent=unit["agent"],
            )
            created.append(task)
            if unit["verify"]:
                checkers.append(_verify_task(run_id, task))
    except orc.OrchestrationError as exc:
        return _fail(exc)

    tasks = created + checkers
    if json_out:
        _dump({"tasks": tasks, "waves": _wave_view(root, run_id)}, True)
        return 0
    ui.ok(f"그래프를 깔았어요 — 일감 {len(created)}개, 검증 {len(checkers)}개")
    for task in tasks:
        waiting = f"  ({len(task['deps'])}개 기다림)" if task["deps"] else ""
        ui.step(f"  ○ {task['id']}{_agent_suffix(task['agent'])}{waiting}")
        ui.step(ui.dim(f"      {ui.oneline(task['spec'], _SPEC_HEAD)}"))
    return 0


def _parse_units(units_json: str) -> list[dict]:
    """단위 배열을 읽고 정규화한다. 틀린 모양은 ValueError 로 돌려 절반짜리 그래프를 막는다."""
    try:
        raw = json.loads(units_json)
    except ValueError as exc:
        raise ValueError(f"단위 목록이 JSON 이 아니에요: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("단위 목록은 비어 있지 않은 JSON 배열이어야 해요.")
    if len(raw) > _PLAN_MAX_UNITS:
        raise ValueError(f"한 번에 깔 수 있는 단위는 {_PLAN_MAX_UNITS}개까지예요: {len(raw)}개")

    units: list[dict] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{index}번 단위가 객체가 아니에요.")
        spec = str(item.get("spec") or "").strip()
        if not spec:
            raise ValueError(f"{index}번 단위에 spec 이 없어요 — 무엇을 할 일감인지가 비면 띄울 수 없어요.")
        deps = item.get("deps") or []
        if not isinstance(deps, list):
            raise ValueError(f"{index}번 단위의 deps 는 색인 배열이어야 해요.")
        parsed_deps: list[int] = []
        for dep in deps:
            if not isinstance(dep, int) or isinstance(dep, bool) or not 0 <= dep < index:
                raise ValueError(f"{index}번 단위의 의존 {dep!r} 은 자기보다 앞선 단위의 색인이어야 해요.")
            parsed_deps.append(dep)
        units.append(
            {
                "spec": spec,
                "agent": str(item.get("agent") or "").strip(),
                "unit": str(item.get("unit") or "").strip(),
                "deps": parsed_deps,
                "verify": bool(item.get("verify")),
            }
        )
    return units


def _wave_view(root: str, run_id: str) -> list[list[dict]]:
    """그래프를 동시에 뜰 수 있는 묶음으로 편다 — 각 항목은 그대로 배차 지시다."""
    tasks = orc.task_list(root, run_id)
    by_id = {task["id"]: task for task in tasks}
    try:
        waves = orc.topo_waves([t["id"] for t in tasks], {t["id"]: t["deps"] for t in tasks})
    except orc.OrchestrationError:
        return []
    return [[_launch_row(by_id[tid]) for tid in wave] for wave in waves]


def _launch_row(task: dict) -> dict:
    """일감 한 줄을 배차에 필요한 것만으로 줄인다 — 읽는 쪽이 다시 고를 것이 없게.

    `label` 은 사람이 읽는 짧은 이름이고 나머지가 배차 지시다. 둘을 한 줄에 두는 이유는 이
    모양을 `waves` 와 `plan` 이 같이 쓰기 때문이다 — 한쪽은 그림을, 한쪽은 띄울 것을 읽는다.
    """
    return {
        "id": task["id"],
        "label": task.get("unit_id") or task["id"][-6:],
        "agent": task.get("agent") or "",
        "kind": task.get("kind") or "work",
        "spec": task.get("spec") or "",
        "unit_id": task.get("unit_id") or "",
        "status": task.get("status") or "",
        "deps": task.get("deps") or [],
    }


def run_ready(run_id: str, json_out: bool = False) -> int:
    """지금 배차할 수 있는 Task — 의존이 모두 끝났고 아직 아무도 안 잡은 것.

    `siege show` 와 다른 자리다. 저쪽은 DAG 전체를 사람이 읽는 그림이고, 이쪽은 코디네이터가
    다음 wave 에 무엇을 띄울지 고르는 목록이다. 조회 전에 `refresh` 를 한 번 돌려 의존에서
    상태를 다시 도출한다 — 안 하면 앞 Task 가 끝났는데도 뒤 Task 가 pending 으로 보인다.

    Returns:
        0 이면 훑었고, 2 면 그런 Run 이 없다.
    """
    ui.set_quiet(json_out)
    root = _root()
    if orc.run_show(root, run_id) is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2
    orc.refresh(root, run_id)
    tasks = orc.task_list(root, run_id, ready=True)
    if json_out:
        _dump(tasks, True)
        return 0
    if not tasks:
        ui.step(ui.dim("지금 배차할 수 있는 일감이 없어요."))
        return 0
    for task in tasks:
        mark = "◇" if task.get("kind") == "verify" else "○"
        ui.step(f"  {mark} {task['id']}{_agent_suffix(task.get('agent') or '')}")
        ui.step(ui.dim(f"      {ui.oneline(task['spec'], _SPEC_HEAD)}"))
    ui.step(ui.dim(f"  이 {len(tasks)}개를 한 메시지에서 같이 띄워요 — 한 번에 하나씩은 그래프가 아니에요."))
    return 0


def run_waves(run_id: str, json_out: bool = False) -> int:
    """DAG 를 동시에 돌 수 있는 묶음의 순열로 편다 — 같은 묶음은 서로 의존하지 않는다.

    끝난 Task 도 묶음에 남는다. 이 명령은 실행 계획이 아니라 DAG 의 모양을 보여 주는 자리이고,
    끝난 것을 빼면 남은 묶음의 번호가 실행 순서와 어긋난다.

    Returns:
        0 이면 폈고, 2 면 그런 Run 이 없거나 의존이 순환한다.
    """
    ui.set_quiet(json_out)
    root = _root()
    if orc.run_show(root, run_id) is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2
    tasks = orc.task_list(root, run_id)
    rows = {task["id"]: _launch_row(task) for task in tasks}
    try:
        waves = orc.topo_waves([task["id"] for task in tasks], {task["id"]: task["deps"] for task in tasks})
    except orc.OrchestrationError as exc:
        return _fail(exc)
    if json_out:
        _dump([[rows[tid] for tid in wave] for wave in waves], True)
        return 0
    if not waves:
        ui.step(ui.dim("펼 일감이 없어요."))
        return 0
    for index, wave in enumerate(waves, start=1):
        ui.step(f"  {index}차  {' · '.join(_wave_label(rows[tid]) for tid in wave)}")
    return 0


def _wave_label(row: dict) -> str:
    """묶음 한 칸 — 맡을 에이전트가 정해져 있으면 그것까지 보인다."""
    agent = row["agent"]
    return f"{row['label']}→{agent.removeprefix('asgard-')}" if agent else row["label"]


def run_refresh(run_id: str, json_out: bool = False) -> int:
    """의존 상태로부터 Task 상태를 다시 도출한다 — 손으로 고친 뒤 DAG 를 맞추는 자리.

    Returns:
        0 이면 맞췄고, 2 면 그런 Run 이 없다.
    """
    ui.set_quiet(json_out)
    root = _root()
    if orc.run_show(root, run_id) is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2
    changed = orc.refresh(root, run_id)
    return _emit(
        {"run": run_id, "changed": changed},
        json_out,
        f"일감 {changed}건의 상태를 다시 도출했어요." if changed else "바뀐 상태가 없어요.",
    )


def run_reclaim(run_id: str, *, older_than: float = 0.0, json_out: bool = False) -> int:
    """죽은 시도를 회수한다 — 워커가 정산 없이 사라진 Dispatch 를 `outcome_unknown` 으로 접는다.

    회수한 Task 는 의존에서 상태를 다시 도출해 대개 ready 로 돌아간다. `older_than` 초 안에
    갱신된 시도는 건드리지 않는다: 살아 있는 워커의 배차를 회수하면 같은 Task 를 둘이 동시에
    잡는다.

    Returns:
        0 이면 훑었고, 2 면 그런 Run 이 없다.
    """
    ui.set_quiet(json_out)
    root = _root()
    if orc.run_show(root, run_id) is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2
    reclaimed = orc.reclaim(root, run_id, older_than=older_than)
    return _emit(
        {"run": run_id, "reclaimed": reclaimed},
        json_out,
        f"시도 {len(reclaimed)}건을 회수했어요." if reclaimed else "회수할 시도가 없었어요.",
    )


def run_force(task_id: str, status: str, *, result: str = "", json_out: bool = False) -> int:
    """Task 상태를 손으로 적는다 — 복구와 명시적 무효화 전용.

    정상 경로에서는 부르지 않는다. 워커의 완료 보고(`siege done`)가 Task 와 Dispatch 를 함께
    접는다. 여기를 정상 경로로 쓰면 배차 결과와 상태가 두 곳에서 각자 갱신되고, 그때 `siege
    show` 의 시도 횟수는 상태와 안 맞는다.

    Returns:
        0 이면 적었고, 2 면 도메인이 거절했다(없는 Task·허용 안 되는 전이·틀린 상태 이름).
    """
    ui.set_quiet(json_out)
    payload = None
    if result:
        try:
            payload = json.loads(result)
        except json.JSONDecodeError as exc:
            ui.fail(f"--result는 JSON 객체여야 해요: {exc}")
            return 2
        if not isinstance(payload, dict):
            ui.fail("--result는 JSON 객체여야 해요 — 배열이나 값 하나는 못 적어요.")
            return 2
    try:
        task = orc.task_update(_root(), task_id, status=status, result=payload)
    except orc.OrchestrationError as exc:
        return _fail(exc)
    return _emit(task, json_out, f"일감 상태를 적었어요 — {task_id} → {task['status']}")


def run_open(
    task_id: str,
    *,
    worker: str = "",
    role: str = "",
    agent: str = "",
    model: str = "",
    retry_of: str = "",
    json_out: bool = False,
) -> int:
    """이 Task 의 새 시도를 연다 — Task 를 dispatched 로 옮기고 시도 횟수를 올린다.

    연속 실패가 `MAX_ATTEMPTS` 에 닿으면 회로가 끊겨 더 안 열린다. 그 거절은 실패가 아니라
    같은 일감을 무한히 다시 배차하지 않겠다는 계약이다 — 회로를 다시 잇는 방법은 Task 를 고쳐
    새로 만드는 쪽이지 재시도가 아니다.

    Returns:
        0 이면 열었고, 2 면 도메인이 거절했다(없는 Task·닫힌 Run·이미 활성 시도·회로 차단).
    """
    ui.set_quiet(json_out)
    try:
        dispatch = orc.open_dispatch(
            _root(), task_id, worker=worker, role=role, agent=agent, model=model, retry_of=retry_of
        )
    except orc.OrchestrationError as exc:
        return _fail(exc)
    if json_out:
        _dump(dispatch, True)
        return 0
    # Dispatch id 를 적는다 — `settle`·`done`·`heartbeat` 가 받는 유일한 손잡이다.
    ui.ok(f"시도를 열었어요 — {dispatch['id']} (Task {task_id})")
    ui.step(ui.dim(f"    끝나면: `asgard siege done {dispatch['id']} succeeded|failed`"))
    return 0


def run_settle(
    dispatch_id: str,
    outcome: str,
    *,
    summary: str = "",
    files: list[str] | None = None,
    json_out: bool = False,
) -> int:
    """시도를 정산한다 — 완료 메일 없이 배차만 접는 자리.

    워커가 스스로 끝내는 정상 경로는 `siege done` 이다. 저쪽은 메일과 정산이 한 트랜잭션이라
    코디네이터가 완료를 읽는 시점과 Task 가 접히는 시점이 같다. 여기는 워커가 보고를 못 남기고
    끝났을 때 코디네이터가 대신 접는 자리다.

    Returns:
        0 이면 정산했고, 2 면 도메인이 거절했다(없는 Dispatch·이미 끝남·틀린 outcome).
    """
    ui.set_quiet(json_out)
    try:
        settled = orc.dispatch_settle(_root(), dispatch_id, outcome, summary=summary, files_modified=list(files or []))
    except orc.OrchestrationError as exc:
        return _fail(exc)
    task = settled.get("task") or {}
    return _emit(settled, json_out, f"시도를 정산했어요 — {dispatch_id} ({outcome}), 일감은 {task.get('status', '?')}")


def run_mark(dispatch_id: str, state: str, json_out: bool = False) -> int:
    """시도에 복구 표시를 남긴다 — `stopped` 나 `outcome_unknown` 둘뿐이다.

    둘 다 Task 를 접지 않는다. 무엇이 남았는지는 코디네이터가 보고 정한다. 성공·실패는
    `siege settle` 만 적는다 — 여기서 실패를 적으면 outcome 도 시도 횟수도 안 남는다.

    Returns:
        0 이면 남겼고, 2 면 도메인이 거절했다(복구 상태 밖·없는 Dispatch·이미 끝남).
    """
    ui.set_quiet(json_out)
    try:
        marked = orc.dispatch_mark(_root(), dispatch_id, state)
    except orc.OrchestrationError as exc:
        return _fail(exc)
    return _emit(marked, json_out, f"시도에 표시를 남겼어요 — {dispatch_id} ({state})")


def run_send(
    run_id: str,
    message_type: str,
    *,
    subject: str = "",
    body: str = "",
    sender: str = "",
    recipient: str = "",
    task_id: str = "",
    dispatch_id: str = "",
    priority: str = "normal",
    json_out: bool = False,
) -> int:
    """Run 우편함에 메시지를 넣는다.

    `worker_done` 은 이 문으로 안 들어간다 — 도메인이 거절한다. 여기서 넣으면 메일만 생기고
    배차 정산은 안 일어나서, 코디네이터는 완료를 읽는데 Task 는 dispatched 로 남는다.
    완료 보고는 `siege done` 이다.

    Returns:
        0 이면 넣었고, 2 면 도메인이 거절했다(종류 밖·`worker_done`·없는 Run).
    """
    ui.set_quiet(json_out)
    try:
        message = orc.send(
            _root(),
            run_id,
            message_type,
            subject=subject or body[:200],
            body=body,
            sender=sender,
            recipient=recipient,
            task_id=task_id,
            dispatch_id=dispatch_id,
            priority=priority,
        )
    except orc.OrchestrationError as exc:
        return _fail(exc)
    return _emit(message, json_out, f"메일을 넣었어요 — {message['id']} ({message_type})")


def run_check(
    run_id: str,
    *,
    ack: str = "",
    types: list[str] | None = None,
    peek: bool = False,
    wait_ms: int = 0,
    json_out: bool = False,
) -> int:
    """코디네이터가 우편함에서 가장 오래된 미확인 묶음을 가져온다.

    `siege inbox` 와 다른 자리다. 저쪽은 확인 여부와 무관하게 읽기만 하고 재생 계약을 안
    건드린다. 여기는 묶음을 잡고, `--ack` 로 앞 묶음을 확인 처리한 뒤 다음 것을 본다 —
    확인과 조회가 한 번에 일어나야 그 사이 들어온 메일이 순서를 건너뛰지 않는다.

    빈 묶음은 실패가 아니라 확인 시점이다. 종료 코드 0 으로 돌려준다 — 2 로 돌리면 폴링하는
    코디네이터 고리가 매번 실패를 읽는다.

    Returns:
        0 이면 확인했고, 2 면 그런 Run 이 없다.
    """
    ui.set_quiet(json_out)
    root = _root()
    if orc.run_show(root, run_id) is None:
        ui.fail(f"그런 Run이 없어요: {run_id}")
        return 2
    try:
        found = orc.check(
            root,
            run_id,
            ack=ack,
            types=tuple(types) if types else None,
            peek=peek,
            wait=wait_ms > 0,
            timeout_ms=wait_ms,
        )
    except orc.OrchestrationError as exc:
        return _fail(exc)
    if json_out:
        _dump(found, True)
        return 0
    if not found["count"]:
        ui.step(ui.dim("확인할 메일이 없어요."))
        return 0
    # 배달 id 를 적는다 — 다음 `check --ack` 가 받는 손잡이라, 빼면 같은 묶음이 계속 재생된다.
    ui.ok(f"메일 {found['count']}건 — 배달 {found['delivery_id']}")
    for message in found["messages"]:
        ui.step(f"  {message['type']:<12} {ui.dim(ui.oneline(message.get('subject') or '', _SPEC_HEAD))}")
    ui.step(ui.dim(f"    확인 처리: `asgard siege check {run_id} --ack {found['delivery_id']}`"))
    return 0


def run_ask(
    run_id: str,
    question: str,
    *,
    options: list[str] | None = None,
    sender: str = "",
    task_id: str = "",
    dispatch_id: str = "",
    wait_ms: int = 0,
    json_out: bool = False,
) -> int:
    """막힌 워커가 코디네이터에게 묻는다 — 답을 기다릴지는 부르는 쪽이 정한다.

    `--wait-ms` 를 안 주면 질문만 만들고 바로 돌아온다. 코디네이터와 워커가 같은 스레드에서
    도는 경로에서 기다리면 교착이기 때문이다. 시간이 다 되어도 질문은 취소되지 않으므로,
    같은 질문을 다시 만들지 말고 `siege blocked` 로 찾아 이어 받는다.

    Returns:
        0 이면 물었고, 2 면 도메인이 거절했다(없는 Run).
    """
    ui.set_quiet(json_out)
    try:
        message = orc.ask(
            _root(),
            run_id,
            question,
            options=list(options or []),
            sender=sender,
            task_id=task_id,
            dispatch_id=dispatch_id,
            timeout_ms=wait_ms,
        )
    except orc.OrchestrationError as exc:
        return _fail(exc)
    if json_out:
        _dump(message, True)
        return 0
    answer = message.get("answer") or ""
    if answer:
        ui.ok(f"답을 받았어요 — {ui.oneline(answer, _SPEC_HEAD)}")
        return 0
    ui.ok(f"물었어요 — {message['id']}")
    ui.step(ui.dim(f'    답 달기: `asgard siege answer {message["id"]} "<답>"`'))
    return 0


def run_done(
    dispatch_id: str,
    outcome: str,
    *,
    run_id: str = "",
    task_id: str = "",
    subject: str = "",
    body: str = "",
    files: list[str] | None = None,
    sender: str = "",
    json_out: bool = False,
) -> int:
    """워커가 시도를 끝내며 한 번 보내는 보고 — 완료 메일과 배차 정산이 한 트랜잭션이다.

    `--run`·`--task` 를 주면 도메인이 Dispatch 의 실제 소속과 대조한다. 짝이 안 맞는 보고를
    받아 주면 죽은 재시도의 뒤늦은 완료가 다른 Task 를 끝난 것으로 만든다. 안 주면 대조를
    건너뛰므로, 워커가 자기 신원을 아는 자리에서는 주는 편이 낫다.

    Returns:
        0 이면 보고했고, 2 면 도메인이 거절했다(없는 Dispatch·신원 불일치·이미 끝남·틀린 outcome).
    """
    ui.set_quiet(json_out)
    try:
        reported = orc.worker_done(
            _root(),
            run_id,
            task_id,
            dispatch_id,
            outcome,
            subject=subject,
            body=body,
            files_modified=list(files or []),
            sender=sender,
        )
    except orc.OrchestrationError as exc:
        return _fail(exc)
    task = reported.get("task") or {}
    return _emit(reported, json_out, f"완료를 보고했어요 — {dispatch_id} ({outcome}), 일감은 {task.get('status', '?')}")


def run_escalate(
    run_id: str,
    reason: str,
    *,
    task_id: str = "",
    dispatch_id: str = "",
    sender: str = "",
    json_out: bool = False,
) -> int:
    """코디네이터가 개입해야 한다고 알린다 — 막혔지만 물을 것이 정해지지 않았을 때.

    `siege ask` 와 가르는 기준은 답할 것이 정해졌는가다. 물을 것이 문장으로 서면 `ask` 이고,
    무엇을 물어야 할지부터 코디네이터가 정해야 하면 이쪽이다.

    Returns:
        0 이면 알렸고, 2 면 도메인이 거절했다(없는 Run).
    """
    ui.set_quiet(json_out)
    try:
        message = orc.escalate(_root(), run_id, reason, task_id=task_id, dispatch_id=dispatch_id, sender=sender)
    except orc.OrchestrationError as exc:
        return _fail(exc)
    return _emit(message, json_out, f"에스컬레이션을 남겼어요 — {message['id']}")


def run_heartbeat(run_id: str, task_id: str, dispatch_id: str, *, phase: str = "", json_out: bool = False) -> int:
    """아직 살아 있다는 신호. 완료가 아니며, 이것만으로 워커를 정리하면 안 된다.

    `siege reclaim --older-than` 이 보는 것이 이 신호가 갱신한 시각이다 — 오래 도는 워커가
    안 보내면 살아 있는 배차가 회수된다.

    Returns:
        0 이면 보냈고, 2 면 도메인이 거절했다(없는 Run).
    """
    ui.set_quiet(json_out)
    try:
        message = orc.heartbeat(_root(), run_id, task_id, dispatch_id, phase)
    except orc.OrchestrationError as exc:
        return _fail(exc)
    return _emit(message, json_out, f"살아 있음을 알렸어요 — {task_id}")


def run_note(
    quest_id: str,
    agent: str,
    *,
    spec: str = "",
    objective: str = "",
    caller: str = "",
    json_out: bool = False,
) -> int:
    """호출된 에이전트 하나를 장부에 세운다 — 디스패치 훅이 부르는 문.

    사람이 쓸 자리가 아니라 훅 전용이다(`asgard siege note`, 숨김). 네이티브 루프는 같은
    조합을 프로세스 **안에서** 부르지만, 호스트 모드의 훅은 `asgard` 를 임포트할 수 없는
    인터프리터에서 돌아 이 문 말고는 장부에 닿을 길이 없다.

    Returns:
        0 이면 세웠고, 2 면 도메인이 거절했다(빈 이름·닫힌 Run·이미 활성 시도).
    """
    ui.set_quiet(json_out)
    try:
        dispatch = orc.note_agent(_root(), quest_id, agent, spec=spec, objective=objective or quest_id, caller=caller)
    except orc.OrchestrationError as exc:
        return _fail(exc)
    return _emit(dispatch, json_out, f"장부에 세웠어요 — {agent} ({dispatch['id']})")


def run_unnote(
    quest_id: str, agent: str, *, summary: str = "", spec: str = "", heal: bool = False, json_out: bool = False
) -> int:
    """그 에이전트의 살아 있는 시도를 접는다 — 디스패치 훅이 종료에서 부르는 문.

    결과는 언제나 `succeeded` 다. 이 자리가 아는 것은 호출이 답을 들고 돌아왔다는 사실뿐이고,
    판정의 옳고 그름은 다른 축이다 — 판정자의 FAIL 은 `summary` 로 간다.

    `heal` 은 **여는 쪽이 유실됐을 때** 종료에서 그 자리를 메운다. 장부 쓰기는 디스패치를
    붙잡지 않으려고 답을 안 기다리는 자식 프로세스로 나가고 그 실패는 조용하다 — 26-08-12 에
    Thinker 의 여는 기록이 그렇게 사라져 그 역할이 장부에 아예 안 남았다. 종료에 닿았다는 것은
    그 에이전트가 실제로 돌았다는 뜻이라, 세우고 곧바로 접으면 장부가 사실과 다시 맞는다.
    부르는 쪽은 단위 티켓이 쥔 수명에는 이 갈래를 켜지 않는다 — 거기서 세우면 한 Task 를 둘이 연다.

    Returns:
        0 이면 접었고, 2 면 접을 시도가 없었다(장부를 안 거친 디스패치의 종료 — 정상이다).
    """
    ui.set_quiet(json_out)
    root = _root()
    try:
        settled = orc.close_agent(root, quest_id, agent, "succeeded", summary=summary)
    except orc.OrchestrationError as exc:
        if not heal:
            return _fail(exc)
        try:
            orc.note_agent(root, quest_id, agent, spec=spec, objective=quest_id)
            settled = orc.close_agent(root, quest_id, agent, "succeeded", summary=summary)
        except orc.OrchestrationError as healing:
            return _fail(healing)
    return _emit(settled, json_out, f"시도를 접었어요 — {agent}")


def run_mirror(quest_id: str, cmd: str, unit: str, payload_json: str = "{}", json_out: bool = False) -> int:
    """티켓 전이 하나를 장부에 옮긴다 — 티켓 훅이 부르는 문.

    `run_note` 와 같은 이유로 여기 있다: 이 몸통은 종전에 배포본 훅
    (`asgard_hooklib/tickets._siege_mirror`) 안에서 `from asgard import orchestration` 으로
    시작했고, 그 임포트는 배포 인터프리터에서 한 번도 선 적이 없다. 계약은 그대로 두고
    부르는 자리만 asgard 가 임포트되는 프로세스로 옮긴 것이다.

    단위 Task 는 `access` 를 의존으로 삼아 DAG 로 세운다 — 훅 쪽의 `_siege_register` 가
    그것을 이미 알고 있어 그대로 쓴다(그 함수는 asgard 를 안 부르는 순수 조합이다).

    Returns:
        0 이면 옮겼거나 옮길 것이 없었고, 2 면 도메인이 거절했다.
    """
    ui.set_quiet(json_out)
    from ..hooks.asgard_hooklib.ledger import fold_tickets, load_events
    from ..hooks.asgard_hooklib.tickets import _siege_register, _unit_agent

    try:
        payload = json.loads(payload_json or "{}")
    except json.JSONDecodeError as exc:
        ui.fail(f"--payload는 JSON 객체여야 해요: {exc}")
        return 2
    root = _root()
    events = load_events(root, quest_id)
    tickets = fold_tickets(events)
    objective = next((event.get("request") for event in events if event.get("request")), "") or quest_id
    try:
        run = orc.run_bind(root, quest_id, str(objective)[:500], coordinator="heimdall")
        task_id = _siege_register(orc, root, run["id"], tickets).get(str(unit))
        if not task_id:
            return _emit({"unit": unit, "mirrored": False}, json_out, f"장부에 세울 단위가 없어요 — {unit}")
        if cmd == "ticket-claim":
            orc.open_dispatch(
                root,
                task_id,
                worker=str(payload.get("worker_id") or ""),
                role="worker",
                agent=_unit_agent(root, quest_id, unit),
            )
            return _emit({"unit": unit, "task": task_id, "mirrored": True}, json_out, f"단위를 잡았어요 — {unit}")
        live = orc.dispatch_show(root, task_id=task_id)
        if live is None or live["state"] != "ready":
            return _emit({"unit": unit, "mirrored": False}, json_out, f"살아 있는 시도가 없어요 — {unit}")
        if cmd == "ticket-heartbeat":
            orc.heartbeat(root, run["id"], task_id, live["id"])
            return _emit({"unit": unit, "mirrored": True}, json_out, f"살아 있음을 알렸어요 — {unit}")
        if cmd == "ticket-finish":
            ticket = tickets.get(str(unit)) or {}
            outcome = "succeeded" if payload.get("status") == "done" else "failed"
            orc.worker_done(
                root,
                run["id"],
                task_id,
                live["id"],
                outcome,
                subject=str(ticket.get("error") or "")[:200] or outcome,
                files_modified=[str(path) for path in (ticket.get("files") or [])][:50],
                sender=str(ticket.get("worker_id") or ""),
            )
            return _emit({"unit": unit, "outcome": outcome, "mirrored": True}, json_out, f"단위를 접었어요 — {unit}")
    except orc.OrchestrationError as exc:
        return _fail(exc)
    ui.fail(f"모르는 티켓 명령이에요: {cmd}")
    return 2


def run_gate(
    run_id: str,
    question: str,
    *,
    options: list[str] | None = None,
    task_id: str = "",
    json_out: bool = False,
) -> int:
    """코디네이터가 DAG 를 멈추고 물을 자리를 만든다 — 사람이 `siege decide` 로 닫는다.

    워커의 `ask` 와 반대편이다. 저쪽은 막힌 워커가 코디네이터에게 묻고, 이쪽은 코디네이터가
    다음 갈래를 고른다. 한쪽이 다른 쪽을 끝내지도 않는다: `decide` 는 질문의 답을 안 채우고
    `answer` 는 게이트를 안 닫는다.

    Returns:
        0 이면 만들었고, 2 면 도메인이 거절했다(없는 Run·닫힌 Run).
    """
    ui.set_quiet(json_out)
    try:
        gate = orc.gate_create(_root(), run_id, question, task_id=task_id, options=list(options or []))
    except orc.OrchestrationError as exc:
        return _fail(exc)
    if json_out:
        _dump(gate, True)
        return 0
    ui.ok(f"결정 게이트를 열었어요 — {gate['id']}")
    ui.step(ui.dim(f'    닫기: `asgard siege decide {gate["id"]} "<고른 것>"`'))
    return 0
