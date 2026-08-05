"""Dispatch — Task 한 번의 시도. 수명 권한이 있는 자리.

Task 는 "무엇을 해야 하는가" 이고 Dispatch 는 "누가 언제 그것을 시도했는가" 다. 재시도가
둘을 갈라 놓는다: 한 Task 가 세 번 시도되면 Dispatch 가 셋 생기고 각각 다른 워커·다른 결과를
갖는다. 한 행에 합치면 두 번째 시도가 첫 번째 결과를 덮어써서 실패 이력을 잃는다.

**회로 차단**은 여기 있다. 같은 Task 가 `model.MAX_ATTEMPTS` 번 실패하면 더 배차하지 않고
Task 를 failed 로 접는다. 없으면 실패하는 일감 하나가 예산을 다 먹을 때까지 재배차된다.

`outcome_unknown` 은 실패가 아니다. 워커가 보고 없이 사라졌다는 뜻이고, 그 프로세스와 파일은
아직 살아 있을 수 있다. 실패로 접으면 살아 있는 워커를 죽은 것으로 세고 같은 파일에 두 번째
워커를 배차하게 된다.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid

from .board import _refresh, _task_dict
from .mail import heartbeat_message
from .model import DISPATCH_TERMINAL, MAX_ATTEMPTS, OUTCOMES, OrchestrationError, circuit_broken
from .store import META_MAX_ATTEMPTS, connect, get_meta

# 배차를 거부하는 Task 상태. `completed`/`failed` 는 끝난 일이고, `blocked` 는 선행 의존이
# 실패해 돌 수 없는 일이다. 셋 다 배차하면 결과를 아무도 안 읽는다 — 특히 `blocked` 를 열어
# 두면 Task 가 `dispatched` 로 바뀌면서 "의존이 실패했다" 는 사실이 장부에서 사라진다.
_UNDISPATCHABLE = ("completed", "failed", "blocked")

# `mark` 가 적을 수 있는 상태. 복구가 쓸 수 있는 표시는 이 둘뿐이고, 성공·실패는 `settle` 만
# 적는다. 계약의 복구 경로도 셋으로 갈린다 — 중지(stopped), 결과 모름(outcome_unknown),
# 그리고 새 시도(`open_dispatch(retry_of=...)`). 실패를 적는 복구 동작은 없다.
RECOVERY_STATES = ("stopped", "outcome_unknown")


def _new_id() -> str:
    return f"disp_{uuid.uuid4().hex[:12]}"


def _max_attempts(conn: sqlite3.Connection) -> int:
    """이 저장소의 재시도 상한 — 정책이 적어 둔 값이 있으면 그것, 없으면 기본값.

    배차(`open_dispatch`)와 정산(`settle_within`)이 **같은 수**를 봐야 한다. 갈리면 배차는
    다섯 번을 허용하는데 정산이 세 번째에 Task 를 접어, 실제로 돈 횟수와 장부가 어긋난다.
    """
    try:
        return max(1, min(int(get_meta(conn, META_MAX_ATTEMPTS, "") or MAX_ATTEMPTS), 20))
    except ValueError:
        return MAX_ATTEMPTS


def _consecutive_failures(conn: sqlite3.Connection, task_id: str) -> int:
    """마지막 성공 뒤의 실패 결과 수 — 결과 없는 복구 시도는 실패 예산을 쓰지 않는다."""
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM dispatches WHERE task_id=? AND outcome='failed'"
        " AND attempt > COALESCE((SELECT MAX(attempt) FROM dispatches"
        " WHERE task_id=? AND outcome='succeeded'), 0)",
        (task_id, task_id),
    ).fetchone()
    return int(row["count"])


def _attempt_digest(conn: sqlite3.Connection, task_id: str, limit: int = 5) -> str:
    """이 Task 의 지난 시도를 한 줄로 — 회로가 끊긴 자리에서 같이 내미는 값.

    끊긴 회로는 막다른 길처럼 읽힌다: "세 번 실패했어요" 뒤에 남는 선택지가 없어 보인다.
    그런데 세 번의 결과는 이미 장부에 있고, 그중 하나가 나머지보다 멀리 갔을 수 있다 —
    SWE-agent 의 재시도 루프가 상한에 닿았을 때 하는 일이 정확히 그것이다(시도를 버리지 않고
    **그중 최선을 고른다**). 여기서 점수를 매기지는 않는다. 판정은 코디네이터 몫이고, 이
    자리가 할 수 있는 것은 고를 것이 있다는 사실을 refusal 문구에 넣는 것이다.
    """
    rows = conn.execute(
        "SELECT attempt, agent, outcome, summary FROM dispatches WHERE task_id=? ORDER BY attempt DESC LIMIT ?",
        (task_id, max(1, limit)),
    ).fetchall()
    parts = []
    for row in reversed(rows):
        summary = (row["summary"] or "").strip().replace("\n", " ")
        head = f"{row['attempt']}회 {row['agent'] or row['outcome'] or 'ready'}"
        parts.append(f"{head} — {summary[:80]}" if summary else head)
    return " · ".join(parts) or "기록 없음"


def _dispatch_dict(row: sqlite3.Row) -> dict:
    found = dict(row)
    found["files_modified"] = json.loads(found.get("files_modified") or "[]")
    return found


def open_dispatch(
    root: str,
    task_id: str,
    *,
    worker: str = "",
    role: str = "",
    agent: str = "",
    model: str = "",
    retry_of: str = "",
) -> dict:
    """이 Task 의 새 시도를 연다. Task 를 dispatched 로 옮기고 시도 횟수를 올린다.

    Raises:
        OrchestrationError: Task 가 없거나 돌 수 없는 상태일 때(completed/failed/blocked),
            Run 이 닫혔을 때, 이미 활성 시도가 있을 때, 또는 회로가 끊긴 뒤일 때.
    """
    now = time.time()
    dispatch_id = _new_id()
    with connect(root, write=True) as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise OrchestrationError(f"없는 Task예요: {task_id}")
        if task["status"] in _UNDISPATCHABLE:
            # 회로가 끊겨 접힌 Task 는 여기로 온다 (아래 회로 검사보다 이 상태 검사가 먼저다).
            # 그 거절이 지난 시도를 같이 말해야 코디네이터가 처음부터 다시 짜지 않는다.
            tried = f" 지난 시도: {_attempt_digest(conn, task_id)}" if task["status"] == "failed" else ""
            raise OrchestrationError(f"배차할 수 없는 Task예요: {task_id} ({task['status']}).{tried}")
        run = conn.execute("SELECT status FROM runs WHERE id=?", (task["run_id"],)).fetchone()
        if run is not None and run["status"] != "open":
            raise OrchestrationError(f"닫힌 Run에는 배차할 수 없어요: {task['run_id']}")
        # 한 Task 에 살아 있는 시도는 하나뿐이다. 둘을 열면 두 워커가 같은 파일을 동시에 고치고,
        # 먼저 끝난 쪽 결과를 나중 쪽이 덮어쓴다. 재배차는 앞 시도를 정산한 **뒤**에 한다.
        active = conn.execute(
            "SELECT id FROM dispatches WHERE task_id=? AND state='ready' LIMIT 1", (task_id,)
        ).fetchone()
        if active is not None:
            raise OrchestrationError(f"이미 활성 Dispatch가 있어요: {task_id} → {active['id']}")
        failures = _consecutive_failures(conn, task_id)
        if circuit_broken(failures, _max_attempts(conn)):
            raise OrchestrationError(
                f"회로 차단 — {task_id}의 최근 결과가 {failures}회 연속 실패했어요. "
                f"지난 시도: {_attempt_digest(conn, task_id)}"
            )
        attempts = int(task["attempts"]) + 1
        try:
            conn.execute(
                "INSERT INTO dispatches(id, run_id, task_id, worker, role, agent, model, attempt, retry_of,"
                " state, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,'ready',?,?)",
                (
                    dispatch_id,
                    task["run_id"],
                    task_id,
                    worker,
                    role,
                    agent,
                    model,
                    attempts,
                    retry_of or None,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError:
            active = conn.execute(
                "SELECT id FROM dispatches WHERE task_id=? AND state='ready' LIMIT 1", (task_id,)
            ).fetchone()
            if active is not None:
                raise OrchestrationError(f"이미 활성 Dispatch가 있어요: {task_id} → {active['id']}") from None
            raise
        conn.execute(
            "UPDATE tasks SET status='dispatched', attempts=?, updated_at=? WHERE id=?",
            (attempts, now, task_id),
        )
        row = conn.execute("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
    return _dispatch_dict(row)


def settle(
    root: str,
    dispatch_id: str,
    outcome: str,
    *,
    summary: str = "",
    files_modified: list[str] | None = None,
) -> dict:
    """시도를 끝낸다 — 성공이면 Task 도 completed, 실패면 재시도 여지를 보고 정한다.

    실패 처리: 회로가 끊길 횟수에 닿았으면 Task 를 failed 로 접고, 아니면 의존에서 상태를
    다시 도출한다(대개 ready 로 돌아가 다음 시도를 받는다).

    Returns:
        `{"dispatch": ..., "task": ...}` — 둘 다 갱신된 뒤의 값.
    """
    if outcome not in OUTCOMES:
        raise OrchestrationError(f"outcome은 {'/'.join(OUTCOMES)} 중 하나여야 해요")
    with connect(root, write=True) as conn:
        settled = settle_within(conn, dispatch_id, outcome, summary=summary, files_modified=files_modified)
    return settled


def settle_within(
    conn: sqlite3.Connection,
    dispatch_id: str,
    outcome: str,
    *,
    summary: str = "",
    files_modified: list[str] | None = None,
) -> dict:
    """열린 쓰기 커넥션 위에서의 정산 — 완료 보고가 메일과 한 트랜잭션으로 끝나게 한다.

    `settle` 과 같은 규칙을 쓴다. 갈라 둔 이유는 원자성뿐이다: `mail.worker_done` 이 정산과
    메일을 각자 커밋하면, 정산만 남고 메일이 없는 상태가 생겨 코디네이터가 완료를 못 읽는다.
    """
    if outcome not in OUTCOMES:
        raise OrchestrationError(f"outcome은 {'/'.join(OUTCOMES)} 중 하나여야 해요")
    now = time.time()
    row = conn.execute("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
    if row is None:
        raise OrchestrationError(f"없는 Dispatch예요: {dispatch_id}")
    if row["state"] in DISPATCH_TERMINAL:
        raise OrchestrationError(f"이미 끝난 Dispatch는 다시 정산할 수 없어요: {dispatch_id} ({row['state']})")
    conn.execute(
        "UPDATE dispatches SET state=?, outcome=?, summary=?, files_modified=?, settled_at=?, updated_at=? WHERE id=?",
        (
            "settled" if outcome == "succeeded" else "failed",
            outcome,
            summary,
            json.dumps(list(files_modified or []), ensure_ascii=False),
            now,
            now,
            dispatch_id,
        ),
    )
    task_id = row["task_id"]
    task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    # 뒤늦은 보고는 자기 Dispatch 만 적고 Task 는 안 건드린다. 재시도가 이미 붙은 뒤에 죽은
    # 시도가 결과를 보고하면(느린 스레드·재시작), 그대로 반영할 경우 completed 였던 Task 가
    # pending 으로 되살아나 이미 끝난 일이 다시 배차된다.
    latest = conn.execute(
        "SELECT id FROM dispatches WHERE task_id=? ORDER BY attempt DESC LIMIT 1", (task_id,)
    ).fetchone()
    superseded = latest is not None and latest["id"] != dispatch_id
    if not (superseded or task["status"] in ("completed", "failed")):
        if outcome == "succeeded":
            conn.execute(
                "UPDATE tasks SET status='completed', completed_at=?, updated_at=? WHERE id=?",
                (now, now, task_id),
            )
        elif circuit_broken(_consecutive_failures(conn, task_id), _max_attempts(conn)):
            conn.execute(
                "UPDATE tasks SET status='failed', completed_at=?, updated_at=? WHERE id=?",
                (now, now, task_id),
            )
        else:
            # 다음 시도를 받을 수 있게 되돌린다. 실제 상태는 의존이 정한다 — 선행 Task 가
            # 그 사이 실패했으면 ready 가 아니라 blocked 다.
            conn.execute("UPDATE tasks SET status='pending', updated_at=? WHERE id=?", (now, task_id))
    _refresh(conn, row["run_id"])
    dispatch_row = conn.execute("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
    task_row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return {"dispatch": _dispatch_dict(dispatch_row), "task": _task_dict(task_row)}


def mark(root: str, dispatch_id: str, state: str) -> dict:
    """시도를 stopped 나 outcome_unknown 으로 표시한다 — 복구 경로 전용.

    `stopped` 는 코디네이터가 명시적으로 중지시킨 것, `outcome_unknown` 은 결과를 모르는
    것이다. 둘 다 Task 를 접지 않는다: 무엇이 남았는지는 코디네이터가 보고 정한다.

    적을 수 있는 상태는 이 둘뿐이다. `failed` 를 여기서 적으면 outcome 도 settled_at 도 비고
    시도 횟수도 안 세어져, 자원이 아직 살아 있을 수 있는 `outcome_unknown` 이 실패로 접힌다.
    성공·실패는 `settle` 만 적는다.

    Raises:
        OrchestrationError: state 가 복구 상태 둘 밖일 때, 없는 Dispatch 일 때, 또는 이미 끝난
            Dispatch 일 때. 끝난 시도를 다시 표시하면 기록된 outcome 과 state 가 어긋난다.
    """
    if state not in RECOVERY_STATES:
        raise OrchestrationError(f"mark의 state는 {'/'.join(RECOVERY_STATES)} 중 하나여야 해요")
    now = time.time()
    with connect(root, write=True) as conn:
        row = conn.execute("SELECT state FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
        if row is None:
            raise OrchestrationError(f"없는 Dispatch예요: {dispatch_id}")
        if row["state"] in DISPATCH_TERMINAL:
            raise OrchestrationError(f"이미 끝난 Dispatch에는 표시를 남길 수 없어요: {dispatch_id} ({row['state']})")
        conn.execute(
            "UPDATE dispatches SET state=?, updated_at=? WHERE id=?",
            (state, now, dispatch_id),
        )
        marked = conn.execute("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
    return _dispatch_dict(marked)


def heartbeat(root: str, run_id: str, task_id: str, dispatch_id: str, phase: str = "") -> dict:
    """시도가 아직 살아 있다고 알린다 — 우편함과 Dispatch 의 `updated_at` 둘 다에.

    신호가 메일에만 남으면 `board.reclaim(older_than=N)` 이 그것을 못 본다. 그쪽은
    `dispatches.updated_at` 으로만 오래된 시도를 고르기 때문이다. 그러면 30초마다 신호를
    보내는 워커도 `--older-than 60` 에 회수되고, 회수된 Task 에 두 번째 워커가 열린다 —
    한 Task 에 살아 있는 시도는 하나뿐이라는 계약이 신호를 보낸 쪽에서 깨진다.

    끝난 Dispatch 에는 안 적는다. 정산된 시도의 `updated_at` 을 뒤로 미루면 그 시도가
    언제 끝났는지가 기록에서 밀린다.

    Raises:
        OrchestrationError: 없는 Dispatch 이거나 이미 끝난 Dispatch 일 때.
    """
    with connect(root, write=True) as conn:
        row = conn.execute("SELECT state FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
        if row is None:
            raise OrchestrationError(f"없는 Dispatch예요: {dispatch_id}")
        if row["state"] in DISPATCH_TERMINAL:
            raise OrchestrationError(f"이미 끝난 Dispatch는 살아 있다고 알릴 수 없어요: {dispatch_id} ({row['state']})")
        conn.execute("UPDATE dispatches SET updated_at=? WHERE id=?", (time.time(), dispatch_id))
    return heartbeat_message(root, run_id, task_id, dispatch_id, phase)


def show(root: str, *, dispatch_id: str = "", task_id: str = "") -> dict | None:
    """Dispatch 하나를 본다. task_id 로 물으면 그 Task 의 **가장 최근** 시도를 돌려준다."""
    if not (dispatch_id or task_id):
        raise OrchestrationError("dispatch_id나 task_id 중 하나는 있어야 해요")
    with connect(root) as conn:
        if dispatch_id:
            row = conn.execute("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM dispatches WHERE task_id=? ORDER BY attempt DESC LIMIT 1",
                (task_id,),
            ).fetchone()
    return _dispatch_dict(row) if row is not None else None


def history(root: str, task_id: str) -> list[dict]:
    """이 Task 의 시도 전부 — 왜 세 번 만에 접었는지를 읽는 자리."""
    with connect(root) as conn:
        rows = conn.execute("SELECT * FROM dispatches WHERE task_id=? ORDER BY attempt", (task_id,)).fetchall()
    return [_dispatch_dict(row) for row in rows]
