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

import json

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
# 완료 보고 메일에 남기는 표식 — 이 보고가 종료 훅의 heal 한 번을 이미 가렸다는 뜻이다
# (`consume_self_report`). 메일 payload 에 두는 이유는 그것이 그 보고에 딸린 유일한 자유 칸이라서다.
_HEAL_SKIPPED = "heal_skipped"


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
    # 일감에도 에이전트를 적는다. 훅이 세운 Task 는 이미 그 에이전트의 것이므로, 비워 두면
    # `siege ready` 가 계획된 일감에 대해서만 "누가 맡나" 에 답하고 이쪽에는 못 답한다.
    task = task_create(root, run["id"], (str(spec).strip() or agent)[:_SPEC_CAP], parent=parent, agent=agent)
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


def live_dispatch(root: str, quest_id: str, agent: str) -> str:
    """이 퀘스트에서 그 에이전트가 든 살아 있는 시도의 id — 손잡이를 못 받은 쪽이 묻는 문.

    호스트 모드에서 배차받은 에이전트는 자기 dispatch id 를 모른다. 장부에 세우는 호출은 답을
    안 기다리는 자식 프로세스라(`asgard_hooklib.siege.ledger_call`) 그 id 가 돌아오는 자리가
    없고, SubagentStart 페이로드에도 없다. 그래서 완료를 보고하려는 쪽은 자기가 아는 두 가지,
    퀘스트와 자기 이름으로 묻는다.

    `close_agent` 와 같은 조회를 쓴다 — 이 조합이 연 시도(`role='agent'`)만 본다. 배정 단위
    티켓이 연 시도는 `ticket-finish` 가 정산하므로, 여기서 함께 잡으면 티켓이 정산할 것을 잃는다.

    Raises:
        OrchestrationError: 이 퀘스트에 열린 Run 이 없을 때.
    """
    return _live_dispatch(root, _open_run(root, quest_id), agent)


def consume_self_report(root: str, quest_id: str, agent: str) -> bool:
    """이 종료가 접을 것을 못 찾은 이유가 **에이전트의 자기 완료 보고**인가 — 한 보고에 한 번만.

    종료 훅이 접을 것을 못 찾는 경우는 둘이고, 둘의 처방이 정반대다. 여는 기록이 유실됐으면
    세우고 접어야 장부가 사실과 맞고(`heal`), 에이전트가 스스로 보고했으면 아무것도 하면 안 된다 —
    거기서 세우면 방금 `failed` 로 접힌 시도 옆에 `succeeded` 시도가 새로 생기고, 코디네이터가
    읽는 마지막 줄이 그 성공이 된다.

    가르는 표식은 완료 메일이다. `mail.worker_done` 은 정산과 메일을 한 트랜잭션에 넣으므로,
    그 시도에 `worker_done` 메일이 달려 있다는 것은 정산을 부른 쪽이 에이전트 자신이었다는 뜻이다.
    훅이 부른 `unnote` 는 메일을 안 남긴다.

    쓰는 조회인 이유는 **한 보고가 가리는 종료가 하나**이기 때문이다. 이름만 보고 판정하면, 한 번
    자기 보고를 한 에이전트는 그 뒤로 여는 기록이 진짜 유실돼도 영영 안 메워진다 — 같은 이름의
    재시도가 장부에서 통째로 빠진다. 그래서 쓴 보고에 표식을 남기고, 다음 종료는 다시 heal 로 간다.
    """
    try:
        run_id = _open_run(root, quest_id)
    except OrchestrationError:
        return False
    with connect(root, write=True) as conn:
        rows = conn.execute(
            "SELECT m.id, m.payload FROM messages m JOIN dispatches d ON d.id=m.dispatch_id"
            " WHERE d.run_id=? AND d.agent=? AND d.role=? AND m.type='worker_done'"
            " ORDER BY m.created_at DESC",
            (run_id, agent, _ROLE),
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload"] or "{}")
            except ValueError:
                payload = {}
            if not isinstance(payload, dict) or payload.get(_HEAL_SKIPPED):
                continue
            payload[_HEAL_SKIPPED] = True
            conn.execute(
                "UPDATE messages SET payload=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), row["id"]),
            )
            return True
    return False


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
