"""메시지 — 워커와 코디네이터 사이의 지속되는 우편.

여태 Asgard 의 병렬 워커는 **반환값으로만** 말했다. 단위가 끝나면 결과 문자열이 돌아오고,
그 전까지는 아무 말도 못 한다. 그래서 막힌 워커에게는 두 갈래밖에 없었다 — 추측해서 계속
가거나, 실패로 끝나거나. 이 모듈이 세 번째를 만든다: 묻고 기다린다.

**배달은 묶음이고, 묶음은 ack 까지 재생된다.** `check` 는 가장 오래된 미확인 묶음
(최대 `DELIVERY_CAP` 건)을 돌려주고, `ack` 하기 전까지 **같은 묶음을 다시** 돌려준다.
코디네이터가 묶음을 처리하다 죽어도 그 메일이 사라지지 않게 하는 장치다.

**종류 필터는 깨우는 조건이지 묶음의 내용이 아니다.** `types=("worker_done",)` 로 기다리면
worker_done 이 왔을 때 깨어나지만, 돌려받는 묶음에는 그 사이 쌓인 heartbeat 도 함께 들어
있다. 필터로 묶음을 걸러 내면 걸러진 메일이 영영 ack 되지 않고 우편함에 남는다.

**완료 보고는 `worker_done` 한 문으로만 들어온다.** `send(type="worker_done")` 은 거부한다 —
그 문으로 넣으면 메일만 생기고 배차 정산이 없어서, 코디네이터는 완료를 읽는데 Task 는
`dispatched` 로 남는다.

`ask` 와 `reply` 가 유일한 왕복이다. 나머지는 단방향이며, 답을 기다리지 않는다.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid

from .model import ACTIONABLE_TYPES, DELIVERY_CAP, MESSAGE_TYPES, OUTCOMES, OrchestrationError
from .store import connect

# 대기 중 DB 를 다시 보는 간격. 데몬이 없으므로 조회로 깨어난다 — 이 값보다 빨리 반응할
# 필요가 있는 경로는 아직 없다(워커 한 단위가 분 단위로 돈다).
_POLL_SECONDS = 0.25


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _message_dict(row: sqlite3.Row) -> dict:
    found = dict(row)
    try:
        found["payload"] = json.loads(found.get("payload") or "{}")
    except ValueError:
        found["payload"] = {}
    return found


def send(
    root: str,
    run_id: str,
    message_type: str,
    *,
    subject: str = "",
    body: str = "",
    sender: str = "",
    recipient: str = "",
    task_id: str = "",
    dispatch_id: str = "",
    thread_id: str = "",
    payload: dict | None = None,
    priority: str = "normal",
    outcome: str = "",
) -> dict:
    """메시지를 Run 우편함에 넣는다.

    Raises:
        OrchestrationError: 종류가 `MESSAGE_TYPES` 밖이거나, `worker_done` 이거나, Run 이 없을 때.
    """
    if message_type not in MESSAGE_TYPES:
        raise OrchestrationError(f"type 은 {'/'.join(MESSAGE_TYPES)} 중 하나")
    # 완료 보고는 이 문으로 못 들어온다. 여기서 넣으면 메일만 생기고 정산은 안 일어나서,
    # 코디네이터는 완료를 읽는데 Task 는 `dispatched` 로 남는다. 실패 보고면 outcome 칸도
    # 비어 본문에만 실패가 적힌다 — 계약이 금지하는 "글로만 적은 실패"가 그것이다.
    if message_type == "worker_done":
        raise OrchestrationError("worker_done 은 `worker_done()` 으로 보낸다 — 정산과 한 트랜잭션이다")
    now = time.time()
    message_id = _new_id("msg")
    with connect(root, write=True) as conn:
        if conn.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone() is None:
            raise OrchestrationError(f"없는 Run: {run_id}")
        conn.execute(
            "INSERT INTO messages(id, run_id, task_id, dispatch_id, thread_id, sender, recipient, type,"
            " subject, body, payload, priority, outcome, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                message_id,
                run_id,
                task_id or None,
                dispatch_id or None,
                thread_id,
                sender,
                recipient,
                message_type,
                subject,
                body,
                json.dumps(payload or {}, ensure_ascii=False),
                priority,
                outcome or None,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    return _message_dict(row)


def check(
    root: str,
    run_id: str,
    *,
    ack: str = "",
    types: tuple[str, ...] | None = None,
    peek: bool = False,
    wait: bool = False,
    timeout_ms: int = 0,
) -> dict:
    """우편함에서 가장 오래된 미확인 배달 묶음을 가져온다.

    Args:
        ack: 이 배달 id 를 확인 처리한 뒤 다음 묶음을 본다. 확인과 조회가 한 번에 일어나야
            그 사이에 들어온 메일이 순서를 건너뛰지 않는다.
        types: 대기를 깨울 종류. 묶음의 내용은 거르지 않는다.
        peek: 묶지 않고 들여다보기만 한다 — 이력 확인용이며 재생 계약을 건드리지 않는다.
        wait: 묶을 메일이 없으면 `timeout_ms` 까지 기다린다.

    Returns:
        `{"delivery_id": str|None, "messages": [...], "count": int}`. 빈 묶음은 실패가
        아니라 확인 시점이다 — 워커가 죽었다는 뜻으로 읽으면 안 된다.
    """
    if ack:
        _ack(root, ack)
    deadline = time.monotonic() + (timeout_ms / 1000 if wait else 0)
    while True:
        found = _peek(root, run_id) if peek else _claim(root, run_id, types)
        if found["count"] or not wait or time.monotonic() >= deadline:
            return found
        time.sleep(min(_POLL_SECONDS, max(0.0, deadline - time.monotonic())))


def _ack(root: str, delivery_id: str) -> int:
    now = time.time()
    with connect(root, write=True) as conn:
        cur = conn.execute(
            "UPDATE messages SET acked_at=? WHERE delivery_id=? AND acked_at IS NULL",
            (now, delivery_id),
        )
        return cur.rowcount


def _peek(root: str, run_id: str) -> dict:
    with connect(root) as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE run_id=? AND acked_at IS NULL ORDER BY created_at LIMIT ?",
            (run_id, DELIVERY_CAP),
        ).fetchall()
    return {"delivery_id": None, "messages": [_message_dict(row) for row in rows], "count": len(rows)}


def _has_type(conn: sqlite3.Connection, run_id: str, types: tuple[str, ...]) -> bool:
    """묶지 않은 메일 중 이 종류가 하나라도 있는가 — 배달 상한과 무관하게 우편함 전체를 본다."""
    row = conn.execute(
        "SELECT 1 FROM messages WHERE run_id=? AND delivery_id IS NULL AND acked_at IS NULL"
        f" AND type IN ({','.join('?' * len(types))}) LIMIT 1",
        (run_id, *types),
    ).fetchone()
    return row is not None


def _claim(root: str, run_id: str, types: tuple[str, ...] | None) -> dict:
    """미확인 묶음을 잡는다 — 이미 열린 묶음이 있으면 그것을 그대로 재생한다."""
    with connect(root, write=True) as conn:
        open_rows = conn.execute(
            "SELECT * FROM messages WHERE run_id=? AND delivery_id IS NOT NULL AND acked_at IS NULL"
            " ORDER BY created_at",
            (run_id,),
        ).fetchall()
        if open_rows:
            # 열린 묶음이 둘이면 가장 오래된 것만 돌려준다. 전부 돌려주면 반환한 delivery_id 가
            # 반환한 메시지 목록을 설명하지 못하고, 그 id 로 ack 했을 때 절반만 확인 처리된다.
            oldest = open_rows[0]["delivery_id"]
            batch = [row for row in open_rows if row["delivery_id"] == oldest]
            return {
                "delivery_id": oldest,
                "messages": [_message_dict(row) for row in batch],
                "count": len(batch),
            }
        # 종류 필터는 깨울지만 정한다. 기다리는 종류가 하나도 없으면 아직 묶지 않고 돌아가서,
        # 다음 조회 때 그 메일들이 여전히 가장 오래된 묶음의 앞자리를 지키게 둔다.
        #
        # 판정을 **묶음보다 먼저** 한다. 앞 50건을 잡은 뒤에 그 안에서 종류를 찾으면, heartbeat
        # 가 50건 쌓인 우편함에서는 51번째 worker_done 이 영영 안 보인다. 안 묶으니 ack 도 안
        # 되어 우편함이 스스로 풀리지 않고, 완료 보고를 받고도 코디네이터가 안 깨어난다.
        if types and not _has_type(conn, run_id, types):
            return {"delivery_id": None, "messages": [], "count": 0}
        fresh = conn.execute(
            "SELECT * FROM messages WHERE run_id=? AND delivery_id IS NULL AND acked_at IS NULL"
            " ORDER BY created_at LIMIT ?",
            (run_id, DELIVERY_CAP),
        ).fetchall()
        if not fresh:
            return {"delivery_id": None, "messages": [], "count": 0}
        delivery_id = _new_id("dlv")
        conn.executemany(
            "UPDATE messages SET delivery_id=? WHERE id=?",
            [(delivery_id, row["id"]) for row in fresh],
        )
        return {
            "delivery_id": delivery_id,
            "messages": [_message_dict(row) for row in fresh],
            "count": len(fresh),
        }


def inbox(root: str, run_id: str, *, limit: int = 50) -> list[dict]:
    """확인 여부와 무관한 최근 메일 — 읽기 전용 이력이며 재생 계약을 건드리지 않는다."""
    with connect(root) as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE run_id=? ORDER BY created_at DESC LIMIT ?",
            (run_id, max(1, limit)),
        ).fetchall()
    return [_message_dict(row) for row in rows]


# ── 왕복 (질문과 답) ───────────────────────────────────────────────────────────


def ask(
    root: str,
    run_id: str,
    question: str,
    *,
    options: list[str] | None = None,
    sender: str = "",
    task_id: str = "",
    dispatch_id: str = "",
    timeout_ms: int = 0,
) -> dict:
    """막힌 워커가 코디네이터에게 묻는다.

    `timeout_ms=0` 이면 질문만 만들고 바로 돌아온다. 코디네이터와 워커가 같은 스레드에서
    도는 경로(단일 Worker 턴)에서는 기다리면 교착이므로, 기다릴지는 부르는 쪽이 정한다.

    시간이 다 되어도 질문은 **취소되지 않는다** — 답이 늦게 올 수 있으므로 남겨 두고,
    나중에 같은 message id 로 `wait_answer` 하면 이어 받는다. 같은 질문을 다시 만들면
    코디네이터의 우편함에 같은 물음이 둘 생긴다.
    """
    message = send(
        root,
        run_id,
        "question",
        subject=question[:200],
        body=question,
        sender=sender,
        task_id=task_id,
        dispatch_id=dispatch_id,
        payload={"options": list(options or [])},
    )
    if timeout_ms > 0:
        return wait_answer(root, message["id"], timeout_ms=timeout_ms)
    return message


def wait_answer(root: str, message_id: str, *, timeout_ms: int) -> dict:
    """답이 달릴 때까지 기다린다. 시간이 다 되면 답 없는 상태 그대로 돌려준다."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        with connect(root) as conn:
            row = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if row is None:
            raise OrchestrationError(f"없는 메시지: {message_id}")
        if row["answered_at"] is not None or time.monotonic() >= deadline:
            return _message_dict(row)
        time.sleep(min(_POLL_SECONDS, max(0.0, deadline - time.monotonic())))


def reply(root: str, message_id: str, answer: str) -> dict:
    """코디네이터가 워커의 질문에 답한다.

    `question` 메시지에만 답한다. 다른 종류에 답이 달리면 그 메일이 `pending_questions` 에는
    안 잡히면서 answered_at 만 채워져, 무엇이 왕복이었는지가 우편함에서 사라진다. 코디네이터가
    자기 갈래를 고르는 자리는 여기가 아니라 게이트(`board.gate_create`)다.

    Raises:
        OrchestrationError: 없는 메시지이거나, 질문이 아니거나, 이미 답이 달렸을 때. 두 번째
            답을 조용히 덮어쓰면 워커가 어느 답을 읽었는지 알 수 없다.
    """
    now = time.time()
    with connect(root, write=True) as conn:
        row = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if row is None:
            raise OrchestrationError(f"없는 메시지: {message_id}")
        if row["type"] != "question":
            raise OrchestrationError(f"질문이 아닌 메시지에는 답할 수 없다: {message_id} ({row['type']})")
        if row["answered_at"] is not None:
            raise OrchestrationError(f"이미 답한 질문: {message_id}")
        conn.execute(
            "UPDATE messages SET answer=?, answered_at=? WHERE id=?",
            (answer, now, message_id),
        )
        updated = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    return _message_dict(updated)


# ── 완료 보고 ──────────────────────────────────────────────────────────────────


def worker_done(
    root: str,
    run_id: str,
    task_id: str,
    dispatch_id: str,
    outcome: str,
    *,
    subject: str = "",
    body: str = "",
    files_modified: list[str] | None = None,
    sender: str = "",
) -> dict:
    """워커가 시도를 끝내며 한 번 보내는 보고 — 메일과 배차 정산이 한 트랜잭션으로 끝난다.

    둘이 한 함수이자 한 트랜잭션인 이유는 어느 쪽만 남아도 코디네이터가 잘못 읽기 때문이다.
    정산만 남으면 완료 메일 없이 Task 가 끝나 있고, 메일만 남으면 완료를 받고도 Task 가
    dispatched 로 보인다.

    보고된 `run_id`·`task_id` 는 Dispatch 의 실제 소속과 **대조한다**. 짝이 안 맞는 보고를
    받아 주면 죽은 재시도의 뒤늦은 완료가 다른 Task 를 끝난 것으로 만든다.

    Raises:
        OrchestrationError: outcome 이 `OUTCOMES` 밖이거나, Dispatch 가 없거나, 신원이 안 맞거나,
            그 Dispatch 가 이미 끝났을 때(같은 보고의 두 번째 전송).
    """
    if outcome not in OUTCOMES:
        raise OrchestrationError(f"outcome 은 {'/'.join(OUTCOMES)} 중 하나")
    from .dispatch import settle_within

    now = time.time()
    message_id = _new_id("msg")
    with connect(root, write=True) as conn:
        owner = conn.execute("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
        if owner is None:
            raise OrchestrationError(f"없는 Dispatch: {dispatch_id}")
        if task_id and owner["task_id"] != task_id:
            raise OrchestrationError(f"Dispatch {dispatch_id} 는 Task {task_id} 의 것이 아니다")
        if run_id and owner["run_id"] != run_id:
            raise OrchestrationError(f"Dispatch {dispatch_id} 는 Run {run_id} 의 것이 아니다")
        settled = settle_within(conn, dispatch_id, outcome, summary=body[:2000], files_modified=files_modified)
        conn.execute(
            "INSERT INTO messages(id, run_id, task_id, dispatch_id, thread_id, sender, recipient, type,"
            " subject, body, payload, priority, outcome, created_at) VALUES(?,?,?,?,'',?,'','worker_done',"
            "?,?,?,'normal',?,?)",
            (
                message_id,
                owner["run_id"],
                owner["task_id"],
                dispatch_id,
                sender,
                subject or outcome,
                body,
                json.dumps({"files_modified": list(files_modified or [])}, ensure_ascii=False),
                outcome,
                now,
            ),
        )
        message = _message_dict(conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone())
    return {"message": message, **settled}


def escalate(
    root: str,
    run_id: str,
    reason: str,
    *,
    task_id: str = "",
    dispatch_id: str = "",
    sender: str = "",
) -> dict:
    """코디네이터가 개입해야 한다고 알린다 — 워커가 막혔지만 물을 것이 정해지지 않았을 때."""
    return send(
        root,
        run_id,
        "escalation",
        subject=reason[:200],
        body=reason,
        sender=sender,
        task_id=task_id,
        dispatch_id=dispatch_id,
        priority="high",
    )


def heartbeat(root: str, run_id: str, task_id: str, dispatch_id: str, phase: str = "") -> dict:
    """아직 살아 있다는 신호. 완료가 아니며, 이것만으로 워커를 정리하면 안 된다."""
    return send(
        root,
        run_id,
        "heartbeat",
        subject="alive",
        task_id=task_id,
        dispatch_id=dispatch_id,
        payload={"phase": phase},
    )


def pending_questions(root: str, run_id: str) -> list[dict]:
    """아직 답이 안 달린 질문 — 코디네이터가 무엇을 막고 있는지 보는 자리."""
    with connect(root) as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE run_id=? AND type='question' AND answered_at IS NULL ORDER BY created_at",
            (run_id,),
        ).fetchall()
    return [_message_dict(row) for row in rows]


def actionable_types() -> tuple[str, ...]:
    """코디네이터가 기다릴 값이 있는 종류 — `check(types=...)` 의 기본값."""
    return ACTIONABLE_TYPES
