"""호출된 에이전트 한 명을 장부에 세우고 접는 조합 — 호스트 훅이 부르는 문.

네이티브 루프는 `agent/heimdall/bifrost.py` 가 프로세스 안에서 Run·Task·Dispatch 를 직접
엮는다. 호스트 모드(Claude Code·Cursor·Codex)에는 그 루프가 없고, 에이전트 호출을 아는
자리는 훅 하나뿐이다 — 디스패치 도구의 PreToolUse 와 SubagentStop. 그 훅은 스크립트로
복사돼 도는 파일이라 오케스트레이션 계약을 들고 있으면 안 된다. 조합을 여기 두는 이유다.

세우는 단위는 **호출 한 번**이다. 에이전트 호출 하나가 Task 하나 + Dispatch 하나가 된다.
Task 를 재사용하지 않는 이유는 같은 에이전트를 두 번 부르는 것이 재시도가 아니기 때문이다 —
Worker 가 asgard-thor 를 서로 다른 두 표면에 부르면 그것은 일감 둘이고, 한 Task 에 합치면
회로 차단이 두 번째 호출을 "2회 실패" 로 읽는다.

`close_agent` 는 dispatch id 없이 접는다. SubagentStop 페이로드에는 시작 때 받은 손잡이가
없어서, 이 Run 에서 같은 에이전트가 든 **가장 최근의 살아 있는 시도**를 찾아 접는다. 같은
에이전트를 병렬로 둘 부르면 둘 중 어느 것이 먼저 끝났는지는 구별하지 못한다 — 장부는 누가
몇 건을 돌았는지는 맞게 적고, 그 둘의 짝짓기만 최근 순으로 근사한다.

여는 시점은 디스패치 도구를 부르는 순간이라 **뜨지 못한 호출도 열린다** — 예산 가드처럼 다른
훅이 그 호출을 거절하면 시도가 `ready` 로 남아 `siege` 가 계속 "도는 중" 이라고 말한다. 그
자리를 정리하는 손잡이는 이미 있다: `asgard siege reclaim <run> --older-than <초>` 가 그것을
`outcome_unknown` 으로 접는다. 대신 이 시점을 고른 값은 부른 쪽과 지시문이다 — 에이전트가
실제로 뜬 뒤에는 누가 불렀는지가 페이로드에서 사라져 중첩 호출이 평평해진다.

전부 fail-open 이다. 장부는 퀘스트 로그에서 파생된 기록이고, 파생을 얻으려다 디스패치를
막으면 안 된다 — 부르는 쪽은 예외를 삼킨다.
"""

from __future__ import annotations

from .board import run_bind, task_create, task_update
from .dispatch import open_dispatch
from .dispatch import settle as dispatch_settle
from .model import DISPATCH_TERMINAL, OrchestrationError
from .store import connect

_SPEC_CAP = 500
_SUMMARY_CAP = 2000
# 이 조합이 연 시도에만 붙는 `role`. 같은 Run 에 배정 단위 티켓이 적은 시도(`role='worker'`)와
# 네이티브 역할 턴(`role='WORKER'` 등)이 섞여 있어서, 이름만으로 고르면 `close_agent` 가 남의
# 수명을 접는다 — 단위 티켓을 대신 접으면 뒤따르는 ticket-finish 가 정산할 것을 잃는다.
_ROLE = "agent"


def note_agent(
    root: str,
    quest_id: str,
    agent: str,
    *,
    spec: str = "",
    objective: str = "",
    caller: str = "",
    worker: str = "",
    model: str = "",
) -> dict:
    """에이전트 호출 하나를 Run·Task·Dispatch 로 세우고 그 Dispatch 를 돌려준다.

    Args:
        agent: 호출된 에이전트 이름 (`asgard-verifier`·`asgard-thor` 등). 장부에서 "누구를
            불렀나" 에 답하는 유일한 칸이라 빈 값은 거부한다.
        caller: 부른 쪽의 에이전트 이름. 그쪽의 살아 있는 시도가 이 Run 에 있으면 그 Task 를
            부모로 단다 — 중첩 디스패치가 장부에서 평평해지지 않게.

    Raises:
        OrchestrationError: agent 가 비었거나, Run·Task·Dispatch 중 하나가 거절될 때.
            Dispatch 가 안 열리면 방금 만든 Task 를 실패로 접는다 — 배차 없는 Task 를
            남기면 Run 이 영영 미완으로 보인다.
    """
    if not agent:
        raise OrchestrationError("장부에 세울 에이전트 이름이 없어요")
    run = run_bind(root, quest_id, str(objective or quest_id)[:_SPEC_CAP], coordinator="heimdall")
    parent = _live_task(root, run["id"], caller) if caller else ""
    task = task_create(root, run["id"], (str(spec).strip() or agent)[:_SPEC_CAP], parent=parent)
    try:
        return open_dispatch(
            root,
            task["id"],
            worker=worker or f"{quest_id}:{agent}",
            role=_ROLE,
            agent=agent,
            model=model,
        )
    except OrchestrationError:
        task_update(root, task["id"], status="failed")
        raise


def close_agent(root: str, quest_id: str, agent: str, outcome: str = "succeeded", *, summary: str = "") -> dict:
    """이 퀘스트에서 그 에이전트가 든 가장 최근의 살아 있는 시도를 접는다.

    Raises:
        OrchestrationError: 이 퀘스트에 열린 Run 이 없거나, 접을 시도가 없을 때. 후자는
            정상이기도 하다 — 장부를 안 거친 디스패치(단위 티켓·차단된 호출)의 종료다.
    """
    run = _open_run(root, quest_id)
    live = _live_dispatch(root, run, agent)
    if not live:
        raise OrchestrationError(f"접을 시도가 없어요: {agent}")
    return dispatch_settle(root, live, outcome, summary=str(summary)[:_SUMMARY_CAP])


def live_agents(root: str, run_id: str) -> list[dict]:
    """지금 이 Run 에서 답을 기다리는 중인 시도 — 최근 것이 앞. 표시 전용."""
    with connect(root) as conn:
        rows = conn.execute(
            "SELECT * FROM dispatches WHERE run_id=? AND state='ready' ORDER BY created_at DESC",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _open_run(root: str, quest_id: str) -> str:
    with connect(root) as conn:
        row = conn.execute(
            "SELECT id FROM runs WHERE quest_id=? AND status='open' ORDER BY created_at DESC LIMIT 1",
            (quest_id,),
        ).fetchone()
    if row is None:
        raise OrchestrationError(f"이 퀘스트엔 열린 Run이 없어요: {quest_id}")
    return str(row["id"])


def _live_dispatch(root: str, run_id: str, agent: str) -> str:
    """이 Run 에서 그 에이전트가 든 살아 있는 시도의 id. 없으면 빈 문자열."""
    with connect(root) as conn:
        row = conn.execute(
            "SELECT id FROM dispatches WHERE run_id=? AND agent=? AND role=? AND state NOT IN (%s)"
            " ORDER BY created_at DESC LIMIT 1" % ",".join("?" * len(DISPATCH_TERMINAL)),
            (run_id, agent, _ROLE, *sorted(DISPATCH_TERMINAL)),
        ).fetchone()
    return str(row["id"]) if row is not None else ""


def _live_task(root: str, run_id: str, agent: str) -> str:
    """그 에이전트의 살아 있는 시도가 맡은 Task. 부모로 달 자리가 없으면 빈 문자열."""
    with connect(root) as conn:
        row = conn.execute(
            "SELECT task_id FROM dispatches WHERE run_id=? AND agent=? AND role=? AND state='ready'"
            " ORDER BY created_at DESC LIMIT 1",
            (run_id, agent, _ROLE),
        ).fetchone()
    return str(row["task_id"]) if row is not None else ""
