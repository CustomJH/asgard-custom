"""Run 과 Task — 이름 공간과 일감 DAG.

Run 은 **일정을 짜지 않는다.** 워커를 고르지도, 어디서 돌릴지 정하지도 않는다. 이름 공간
하나와 코디네이터 우편함 하나가 전부다. 배치는 부르는 쪽(Trinity 의 WaveRunner)이 정한다 —
이 경계가 흐려지면 오케스트레이션 계층이 실행 계층을 겸하게 되고, 그때부터 "어느 워커가 왜
거기서 돌았는가" 를 두 곳에서 각자 답한다.

Task 의 상태는 **의존에서 도출한다**(`model.task_status_for`). 호출자가 ready 를 직접 적을 수
없게 한 이유는 드리프트다: 의존이 실패했는데 누군가 ready 로 적어 두면 코디네이터는 돌 수
없는 일감을 배차한다. 상태를 바꾸는 사실은 두 가지뿐이다 — 의존의 변화, 그리고 배차의 결과.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid

from .model import TASK_STATUSES, OrchestrationError, task_status_for, valid_transition
from .store import connect


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _task_dict(row: sqlite3.Row) -> dict:
    task = dict(row)
    task["deps"] = json.loads(task.get("deps") or "[]")
    if task.get("result"):
        try:
            task["result"] = json.loads(task["result"])
        except ValueError:
            pass
    return task


# ── Run ────────────────────────────────────────────────────────────────────────


def run_create(root: str, objective: str, *, quest_id: str = "", coordinator: str = "") -> dict:
    """Run 을 연다. quest_id 를 주면 그 Trinity 퀘스트에 묶인다.

    Raises:
        OrchestrationError: 그 퀘스트에 이미 열린 Run 이 있을 때. 유니크 인덱스가 내는 raw
            IntegrityError 를 그대로 흘리면 `OrchestrationError` 만 잡는 호출자(`siege`)가
            이 경우만 못 받는다.
    """
    now = time.time()
    run_id = _new_id("run")
    with connect(root, write=True) as conn:
        try:
            conn.execute(
                "INSERT INTO runs(id, objective, quest_id, coordinator, status, created_at, updated_at)"
                " VALUES(?,?,?,?,'open',?,?)",
                (run_id, objective, quest_id, coordinator, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise OrchestrationError(f"이 퀘스트에 이미 열린 Run 이 있다: {quest_id}") from exc
    return {
        "id": run_id,
        "objective": objective,
        "quest_id": quest_id,
        "coordinator": coordinator,
        "status": "open",
        "created_at": now,
        "updated_at": now,
    }


def run_for_quest(root: str, quest_id: str) -> dict | None:
    """이 퀘스트에 묶인 열린 Run. 없으면 None — 아직 오케스트레이션을 안 쓴 퀘스트다."""
    with connect(root) as conn:
        return _row(
            conn.execute(
                "SELECT * FROM runs WHERE quest_id=? AND status='open' ORDER BY created_at DESC LIMIT 1",
                (quest_id,),
            ).fetchone()
        )


def run_bind(root: str, quest_id: str, objective: str = "", *, coordinator: str = "") -> dict:
    """이 퀘스트의 Run 을 얻는다 — 없으면 만든다. 같은 퀘스트가 Run 을 둘 갖지 않게 한다.

    조회와 삽입이 **한 쓰기 트랜잭션 안**에 있어야 한다. 나눠 두면 두 스레드가 같은 순간에
    "없다"를 읽고 각자 만들어, 같은 퀘스트의 Task 와 우편함이 Run 둘로 갈린다. 다른 프로세스의
    동시 bind 는 `runs_one_open_per_quest` 유니크 인덱스가 막고, 충돌하면 먼저 삽입된 행을 다시 읽는다.
    """
    now = time.time()
    run_id = _new_id("run")
    with connect(root, write=True) as conn:
        found = conn.execute(
            "SELECT * FROM runs WHERE quest_id=? AND status='open' ORDER BY created_at DESC LIMIT 1",
            (quest_id,),
        ).fetchone()
        if found is not None:
            return dict(found)
        try:
            conn.execute(
                "INSERT INTO runs(id, objective, quest_id, coordinator, status, created_at, updated_at)"
                " VALUES(?,?,?,?,'open',?,?)",
                (run_id, objective, quest_id, coordinator, now, now),
            )
        except sqlite3.IntegrityError:
            # 다른 프로세스가 먼저 열었다. 이 호출은 그 Run 을 그대로 쓴다 — 실패가 아니다.
            existing = conn.execute(
                "SELECT * FROM runs WHERE quest_id=? AND status='open' ORDER BY created_at DESC LIMIT 1",
                (quest_id,),
            ).fetchone()
            if existing is None:
                raise
            return dict(existing)
        return dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())


def run_shape(root: str, run_id: str, shape: str, why: str = "") -> bool:
    """이 Run 이 어떤 형상으로 도는지 적는다 — `strategy.choose` 의 결과를 되읽을 자리.

    형상은 계획이 나오면 바뀔 수 있다(단일로 시작해 배정 단위가 둘 나오면 graph 가 된다).
    마지막에 적힌 것이 실제로 돈 모양이다.
    """
    with connect(root, write=True) as conn:
        cur = conn.execute(
            "UPDATE runs SET shape=?, shape_why=?, updated_at=? WHERE id=?",
            (shape, why, time.time(), run_id),
        )
        return cur.rowcount > 0


def run_show(root: str, run_id: str) -> dict | None:
    with connect(root) as conn:
        return _row(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())


def run_list(root: str, *, status: str = "") -> list[dict]:
    query = "SELECT * FROM runs"
    args: tuple = ()
    if status:
        query += " WHERE status=?"
        args = (status,)
    query += " ORDER BY created_at DESC"
    with connect(root) as conn:
        return [dict(row) for row in conn.execute(query, args).fetchall()]


def run_close(root: str, run_id: str) -> bool:
    """Run 을 닫고, 정산 없이 남은 시도를 회수한다. 이미 닫혀 있으면 False — 실패가 아니다.

    회수가 여기 붙어 있는 이유는 닫힌 Run 에는 그 일을 해 줄 사람이 더 없기 때문이다. 워커가
    보고 없이 사라지면 Dispatch 는 `ready`, Task 는 `dispatched` 로 남는데, 그 상태로 닫으면
    "무엇이 끝났고 무엇이 결과를 모르는가" 가 장부에서 영영 구분되지 않는다.
    """
    now = time.time()
    with connect(root, write=True) as conn:
        cur = conn.execute(
            "UPDATE runs SET status='closed', closed_at=?, updated_at=? WHERE id=? AND status='open'",
            (now, now, run_id),
        )
        if cur.rowcount == 0:
            return False
        _reclaim_within(conn, run_id)
        return True


def reclaim(root: str, run_id: str, *, older_than: float = 0.0) -> list[str]:
    """정산 없이 남은 시도를 회수해 그 Task 를 다시 배차할 수 있게 만든다.

    이것이 재개의 첫 걸음이다. `open_dispatch` 는 한 Task 에 살아 있는 시도가 있으면 거부하므로,
    프로세스가 죽어 정산이 안 된 시도가 남아 있으면 그 Task 는 영원히 배차되지 않는다. 회수는
    시도를 `outcome_unknown` 으로 표시하고 Task 를 `pending` 으로 되돌린 뒤 의존에서 상태를
    다시 도출한다 — 시도 횟수는 그대로 두므로 회로 차단은 여전히 유효하다.

    Args:
        older_than: 이 초 수보다 오래 손대지 않은 시도만 회수한다. 0 이면 열린 시도 전부 —
            프로세스가 이미 죽은 것이 확실한 자리(재개 시작)에서 쓴다.

    Returns:
        회수한 Dispatch id 목록.
    """
    with connect(root, write=True) as conn:
        return _reclaim_within(conn, run_id, older_than=older_than)


def _reclaim_within(conn: sqlite3.Connection, run_id: str, *, older_than: float = 0.0) -> list[str]:
    """열린 커넥션 위에서의 회수 — Run 닫기와 회수가 한 커밋에 끝나게 한다."""
    now = time.time()
    query = "SELECT id, task_id FROM dispatches WHERE run_id=? AND state='ready'"
    args: list = [run_id]
    if older_than > 0:
        query += " AND updated_at < ?"
        args.append(now - older_than)
    rows = conn.execute(query, tuple(args)).fetchall()
    if not rows:
        return []
    for row in rows:
        conn.execute(
            "UPDATE dispatches SET state='outcome_unknown', updated_at=? WHERE id=?",
            (now, row["id"]),
        )
        # 아직 안 끝난 Task 만 되돌린다. 완료·실패로 접힌 Task 를 되살리면 끝난 일이 다시 배차된다.
        conn.execute(
            "UPDATE tasks SET status='pending', updated_at=? WHERE id=? AND status='dispatched'",
            (now, row["task_id"]),
        )
    _refresh(conn, run_id)
    return [str(row["id"]) for row in rows]


# ── Task ───────────────────────────────────────────────────────────────────────


def task_create(
    root: str,
    run_id: str,
    spec: str,
    *,
    deps: list[str] | None = None,
    unit_id: str = "",
    parent: str = "",
) -> dict:
    """일감을 만든다. deps 는 같은 Run 안의 task id 여야 한다.

    Raises:
        OrchestrationError: Run 이 없거나 이미 닫혔을 때, deps 가 이 Run 밖의 id 를 가리킬 때,
            또는 같은 배정 단위의 Task 가 이 Run 에 이미 있을 때. 닫힌 Run 을 거부하는 이유는
            거기 쌓인 일감을 아무도 안 읽기 때문이다 — 끝난 퀘스트의 장부에 새 일감이 들어가면
            `siege` 는 끝난 Run 을 미완으로 보여 준다.
    """
    deps = list(deps or [])
    now = time.time()
    task_id = _new_id("task")
    with connect(root, write=True) as conn:
        run = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise OrchestrationError(f"없는 Run: {run_id}")
        if run["status"] != "open":
            raise OrchestrationError(f"닫힌 Run 에 일감 생성: {run_id}")
        if deps:
            known = {
                row["id"]
                for row in conn.execute(
                    f"SELECT id FROM tasks WHERE run_id=? AND id IN ({','.join('?' * len(deps))})",
                    (run_id, *deps),
                ).fetchall()
            }
            missing = [d for d in deps if d not in known]
            if missing:
                raise OrchestrationError(f"이 Run 에 없는 의존: {', '.join(missing)}")
        status = "ready" if not deps else "pending"
        try:
            conn.execute(
                "INSERT INTO tasks(id, run_id, parent_id, unit_id, spec, deps, status, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (task_id, run_id, parent or None, unit_id, spec, json.dumps(deps), status, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise OrchestrationError(f"이 Run 에 이미 있는 배정 단위: {unit_id}") from exc
        _refresh(conn, run_id)
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _task_dict(row)


def task_for_unit(root: str, run_id: str, unit_id: str) -> dict | None:
    """이 Run 에서 그 배정 단위를 맡은 Task. 다른 프로세스가 먼저 만든 것을 이어 받을 때 쓴다."""
    if not unit_id:
        return None
    with connect(root) as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE run_id=? AND unit_id=? ORDER BY created_at LIMIT 1",
            (run_id, unit_id),
        ).fetchone()
    return _task_dict(row) if row is not None else None


def task_show(root: str, task_id: str) -> dict | None:
    with connect(root) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _task_dict(row) if row is not None else None


def task_list(root: str, run_id: str = "", *, status: str = "", ready: bool = False) -> list[dict]:
    """일감 목록. `ready=True` 면 지금 배차할 수 있는 것만 — 코디네이터의 외부 기억이다."""
    clauses, args = [], []
    if run_id:
        clauses.append("run_id=?")
        args.append(run_id)
    if ready:
        clauses.append("status='ready'")
    elif status:
        clauses.append("status=?")
        args.append(status)
    query = "SELECT * FROM tasks"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at"
    with connect(root) as conn:
        return [_task_dict(row) for row in conn.execute(query, tuple(args)).fetchall()]


def task_update(root: str, task_id: str, *, status: str = "", result: dict | None = None) -> dict:
    """일감 상태를 손으로 바꾼다 — 복구와 명시적 무효화 전용.

    정상 경로에서는 부르지 않는다. 워커의 완료 보고(`mail.worker_done`)가 Task 와 Dispatch 를
    함께 접고, 의존 변화는 `_refresh` 가 반영한다. 여기를 정상 경로로 쓰면 배차 결과와 상태가
    두 곳에서 각자 갱신된다.

    Raises:
        OrchestrationError: 없는 Task 이거나, 끝난 Task(`completed`/`failed`)를 되살리려 할 때.
            되살리기를 열어 두면 완료 보고가 끝낸 일감이 다시 배차되고, 그 사실이 어디에도
            안 남는다. 잘못 접힌 장부를 되돌려야 하면 이 DB 를 지운다 — 파생 상태다.
    """
    if status and status not in TASK_STATUSES:
        raise OrchestrationError(f"status 는 {'/'.join(TASK_STATUSES)} 중 하나")
    now = time.time()
    with connect(root, write=True) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise OrchestrationError(f"없는 Task: {task_id}")
        if status and not valid_transition(row["status"], status):
            raise OrchestrationError(f"허용되지 않는 전이: {task_id} {row['status']} → {status}")
        sets = ["updated_at=?"]
        args: list = [now]  # 시각·상태·JSON 이 섞인다 — 첫 원소로 타입이 굳지 않게 열어 둔다
        if status:
            sets.append("status=?")
            args.append(status)
            if status in ("completed", "failed"):
                sets.append("completed_at=?")
                args.append(now)
        if result is not None:
            sets.append("result=?")
            args.append(json.dumps(result, ensure_ascii=False))
        conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", (*args, task_id))
        _refresh(conn, row["run_id"])
        updated = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _task_dict(updated)


def refresh(root: str, run_id: str) -> int:
    """의존 상태로부터 이 Run 의 Task 상태를 다시 도출한다.

    Returns:
        상태가 바뀐 Task 수.
    """
    with connect(root, write=True) as conn:
        return _refresh(conn, run_id)


def _refresh(conn: sqlite3.Connection, run_id: str) -> int:
    """열린 커넥션 위에서의 준비도 재도출 — 쓰기 경로가 커밋 한 번에 끝나게 한다.

    한 번의 통과로는 부족하다: A→B→C 로 의존이 이어질 때 A 가 방금 완료되면 B 가 ready 로
    바뀌는데, 그 변화는 같은 통과 안에서 C 에게 아직 반영되지 않는다. 상태가 더 바뀌지 않을
    때까지 반복한다.
    """
    rows = conn.execute("SELECT id, status, deps FROM tasks WHERE run_id=?", (run_id,)).fetchall()
    status = {row["id"]: row["status"] for row in rows}
    deps = {row["id"]: json.loads(row["deps"] or "[]") for row in rows}
    changed: dict[str, str] = {}
    for _ in range(len(rows) + 1):
        moved = False
        for tid in status:
            dep_statuses = [status[d] for d in deps[tid] if d in status]
            resolved = task_status_for(status[tid], dep_statuses)
            if resolved != status[tid]:
                status[tid] = resolved
                changed[tid] = resolved
                moved = True
        if not moved:
            break
    now = time.time()
    for tid, resolved in changed.items():
        conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (resolved, now, tid))
    return len(changed)


# ── 게이트 ─────────────────────────────────────────────────────────────────────


def gate_create(root: str, run_id: str, question: str, *, task_id: str = "", options: list[str] | None = None) -> dict:
    """코디네이터가 DAG 를 멈추고 물을 자리를 만든다.

    워커의 `ask` 와 다르다 — 저쪽은 막힌 워커가 코디네이터에게 묻는 것이고, 이쪽은 코디네이터가
    다음 갈래를 고르는 것이다. 둘을 한 표에 합치면 "누가 누구를 기다리는가" 가 사라진다.
    한쪽이 다른 쪽을 끝내지도 않는다: `gate_resolve` 는 질문의 답을 채우지 않고 `mail.reply` 는
    게이트를 닫지 않는다.

    Raises:
        OrchestrationError: Run 이 없거나 이미 닫혔을 때. 닫힌 Run 의 게이트는 고를 사람이 없고,
            없는 Run 에 넣으면 외래키가 raw `sqlite3.IntegrityError` 를 내서 `OrchestrationError`
            만 잡는 호출자(`siege`)가 이 경우만 못 받는다.
    """
    now = time.time()
    gate_id = _new_id("gate")
    with connect(root, write=True) as conn:
        run = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise OrchestrationError(f"없는 Run: {run_id}")
        if run["status"] != "open":
            raise OrchestrationError(f"닫힌 Run 에 게이트 생성: {run_id}")
        conn.execute(
            "INSERT INTO gates(id, run_id, task_id, question, options, status, created_at) VALUES(?,?,?,?,?,'open',?)",
            (gate_id, run_id, task_id or None, question, json.dumps(list(options or []), ensure_ascii=False), now),
        )
    return {
        "id": gate_id,
        "run_id": run_id,
        "task_id": task_id or None,
        "question": question,
        "options": list(options or []),
        "status": "open",
        "created_at": now,
    }


def gate_resolve(root: str, gate_id: str, resolution: str) -> dict:
    now = time.time()
    with connect(root, write=True) as conn:
        cur = conn.execute(
            "UPDATE gates SET status='resolved', resolution=?, resolved_at=? WHERE id=? AND status='open'",
            (resolution, now, gate_id),
        )
        if cur.rowcount == 0:
            raise OrchestrationError(f"열린 게이트가 아님: {gate_id}")
        row = conn.execute("SELECT * FROM gates WHERE id=?", (gate_id,)).fetchone()
    gate = dict(row)
    gate["options"] = json.loads(gate.get("options") or "[]")
    return gate


def gate_list(root: str, *, run_id: str = "", task_id: str = "", status: str = "") -> list[dict]:
    clauses, args = [], []
    for column, value in (("run_id", run_id), ("task_id", task_id), ("status", status)):
        if value:
            clauses.append(f"{column}=?")
            args.append(value)
    query = "SELECT * FROM gates"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at"
    with connect(root) as conn:
        rows = conn.execute(query, tuple(args)).fetchall()
    gates = []
    for row in rows:
        gate = dict(row)
        gate["options"] = json.loads(gate.get("options") or "[]")
        gates.append(gate)
    return gates
