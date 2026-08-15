"""티켓 런타임 — 병렬 단위 하나의 소유권과 lease.

claim 이 토큰을 내주고 heartbeat 만 그 토큰으로 lease 를 민다. raw append 로 열어 두면 토큰
없이 남의 lease 를 미는 문이 되므로 상태 전이는 전부 이 모듈을 지난다. 배차 장부(siege)
반영도 여기서 같이 한다 — 티켓 전이와 장부가 갈라지면 "누가 무엇을 잡았나"가 두 답을 낸다.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time

from .ledger import fold_tickets, load_events, normalize, quest_lock, write_event_unlocked
from .paths import UNREADABLE_RECEIPT
from .siege import ledger_call


def _ticket_recover(emit, tickets: dict, now: float, max_attempts: int) -> tuple[int, dict]:
    """lease 가 끝난 in_progress 를 회수한다 — 재시도 예산이 남았으면 failed, 없으면 blocked."""
    recovered = []
    for ticket in list(tickets.values()):
        if ticket["status"] != "in_progress" or float(ticket.get("lease_expires_at") or 0) > now:
            continue
        exhausted = int(ticket.get("attempt") or 0) >= int(ticket.get("max_attempts") or max_attempts)
        next_status = "blocked" if exhausted else "failed"
        emit(
            {
                "unit": ticket["id"],
                "ticket_status": next_status,
                "ticket_error": "lease expired",
                "attempt": ticket.get("attempt") or 0,
                "max_attempts": ticket.get("max_attempts") or max_attempts,
                "claim_token_hash": ticket.get("claim_token_hash"),
                "worker_id": ticket.get("worker_id"),
                "lease_expires_at": ticket.get("lease_expires_at"),
            }
        )
        recovered.append({"unit": ticket["id"], "status": next_status})
    return 0, {"recovered": recovered}


def _ticket_claim(
    emit, tickets: dict, ticket: dict, now: float, worker, lease_seconds: int, max_attempts: int
) -> tuple[int, dict]:
    """단위 하나를 Worker 한 명에게 준다 — 선행 단위가 done 이고 살아 있는 lease 가 없을 때만."""
    dependencies = [tickets.get(str(dep)) for dep in ticket.get("access") or []]
    if any(not dep or dep.get("status") != "done" for dep in dependencies):
        return 1, {"error": "dependencies incomplete", "unit": ticket["id"]}
    if ticket["status"] == "in_progress" and float(ticket.get("lease_expires_at") or 0) > now:
        return 1, {"error": "ticket already claimed", "unit": ticket["id"]}
    if ticket["status"] in ("done", "blocked"):
        message = "retry budget exhausted" if ticket["status"] == "blocked" else "ticket is terminal"
        return 1, {"error": message, "unit": ticket["id"], "status": ticket["status"]}
    previous_max = int(ticket.get("max_attempts") or max_attempts)
    allowed = min(previous_max, max_attempts) if int(ticket.get("attempt") or 0) else max_attempts
    attempt = int(ticket.get("attempt") or 0) + 1
    if attempt > allowed:
        emit(
            {
                "unit": ticket["id"],
                "ticket_status": "blocked",
                "ticket_error": "retry budget exhausted",
                "attempt": ticket.get("attempt") or 0,
                "max_attempts": allowed,
            }
        )
        return 1, {"error": "retry budget exhausted", "unit": ticket["id"], "status": "blocked"}
    # Keep the first character non-option-like so argparse callers may safely pass
    # the opaque token as a separate value (`--claim-token TOKEN`).
    token = "agt_" + secrets.token_urlsafe(24)
    expiry = now + lease_seconds
    emit(
        {
            "unit": ticket["id"],
            "ticket_status": "in_progress",
            "claim_token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "worker_id": worker or "worker",
            "lease_expires_at": expiry,
            "heartbeat_at": now,
            "attempt": attempt,
            "max_attempts": allowed,
        }
    )
    return 0, {
        "claimed": ticket["id"],
        "claim_token": token,
        "worker_id": worker or "worker",
        "lease_expires_at": expiry,
        "attempt": attempt,
        "max_attempts": allowed,
    }


def _ticket_lease_denial(ticket: dict, claim_token, now: float) -> dict | None:
    """갱신·종료의 자격 검사 — 자기 claim 을 증명해야 한다. None 이면 통과다.

    토큰은 해시로만 대조하고 비교도 상수 시간이다. 토큰 없이 남의 lease 를 밀 수 있으면
    lease 는 소유권이 아니라 권고가 된다."""
    supplied_hash = hashlib.sha256((claim_token or "").encode()).hexdigest()
    stored_hash = str(ticket.get("claim_token_hash") or "")
    if ticket["status"] != "in_progress" or not claim_token or not secrets.compare_digest(supplied_hash, stored_hash):
        return {"error": "claim token mismatch", "unit": ticket["id"]}
    if float(ticket.get("lease_expires_at") or 0) <= now:
        return {"error": "claim lease expired", "unit": ticket["id"]}
    return None


def _ticket_heartbeat(emit, ticket: dict, now: float, lease_seconds: int, max_attempts: int) -> tuple[int, dict]:
    """lease 갱신 — 상태 전이가 아니라 `ticket_lease` 로 적는다.

    갱신이 `ticket` 으로 적히면 티켓 이벤트 열이 "todo→in_progress→done" 이 아니라 "얼마나
    오래 돌았는가"를 적게 되고, 그 열을 읽는 쪽은 벽시계에 따라 다른 역사를 본다."""
    expiry = now + lease_seconds
    emit(
        {
            "event": "ticket_lease",
            "unit": ticket["id"],
            "claim_token_hash": str(ticket.get("claim_token_hash") or ""),
            "worker_id": ticket.get("worker_id"),
            "lease_expires_at": expiry,
            "heartbeat_at": now,
            "attempt": ticket.get("attempt") or 1,
            "max_attempts": ticket.get("max_attempts") or max_attempts,
        }
    )
    return 0, {"heartbeat": ticket["id"], "lease_expires_at": expiry}


def _ticket_finish(emit, ticket: dict, now: float, max_attempts: int, status, error) -> tuple[int, dict]:
    """단위 종료 — 재시도 예산을 다 쓴 failed 는 blocked 로 닫는다 (다시 못 잡는다)."""
    if status not in ("done", "failed"):
        return 2, {"error": "ticket-finish status must be done or failed"}
    attempts = int(ticket.get("attempt") or 1)
    allowed = int(ticket.get("max_attempts") or max_attempts)
    final_status = "blocked" if status == "failed" and attempts >= allowed else status
    emit(
        {
            "unit": ticket["id"],
            "ticket_status": final_status,
            "ticket_error": error,
            "claim_token_hash": str(ticket.get("claim_token_hash") or ""),
            "worker_id": ticket.get("worker_id"),
            "lease_expires_at": ticket.get("lease_expires_at"),
            "heartbeat_at": now,
            "attempt": attempts,
            "max_attempts": allowed,
        }
    )
    return 0, {"finished": ticket["id"], "status": final_status, "attempt": attempts}


def _siege_register(orc, root: str, run_id: str, tickets: dict) -> dict[str, str]:
    """이 퀘스트의 배정 단위를 Task 로 장부에 세우고 unit → task id 표를 돌려준다.

    `access` 가 곧 의존이다. `task_create` 는 만들 때 의존을 받고 나중에 더할 수 없으므로,
    `topo_waves` 로 단위를 의존이 앞서는 순서로 편 뒤 그 순서대로 만든다. 이미 있는 단위는
    다시 만들지 않는다 — 두 번째 claim 이 같은 Task 를 또 만들면 DAG 가 갈린다.
    """
    known = {str(uid): ticket for uid, ticket in tickets.items()}
    order = orc.topo_waves(
        list(known),
        {uid: [a for a in (ticket.get("access") or []) if str(a) in known] for uid, ticket in known.items()},
    )
    by_unit: dict[str, str] = {}
    for wave in order:
        for uid in wave:
            existing = orc.task_for_unit(root, run_id, uid)
            if existing is not None:
                by_unit[uid] = existing["id"]
                continue
            deps = [by_unit[str(a)] for a in (known[uid].get("access") or []) if str(a) in by_unit]
            spec = str(known[uid].get("subtask") or "").strip() or uid
            by_unit[uid] = orc.task_create(root, run_id, spec, deps=deps, unit_id=uid)["id"]
    return by_unit


def _native_loop_owns_the_ledger(worker_id) -> bool:
    """이 단위를 네이티브 Trinity 루프가 잡았는가.

    네이티브 모드도 이 훅으로 티켓을 잡는다(`agent/heimdall/ticket_lease.py`). 하지만 그
    모드에서는 `agent/heimdall/bifrost.py` 가 이미 같은 배차를 장부에 적고 있어서, 여기서 또
    적으면 한 Task 를 둘이 연다 — 뒤에 부른 쪽이 도메인에 거절당해 조용히 버려지고, 어느 쪽이
    이겼는지는 실행마다 달라진다. 장부의 주인은 한 프로세스여야 한다.

    표식은 `ticket_lease._claim` 이 넘기는 워커 id 접두사다. 그쪽이 형식을 바꾸면 이 판정이
    조용히 무너지므로 `tests/test_siege_act.py` 가 두 문자열을 함께 붙든다.
    """
    return str(worker_id or "").startswith("native:")


def _unit_agent(root: str, qid: str, unit: str) -> str:
    """이 배정 단위를 어떤 에이전트가 잡았는가 — 디스패치 영수증이 적어 둔 이름.

    티켓 자체는 워커 id 만 든다(`u1`·`worker-3`). 어떤 에이전트가 그 id 로 돌았는지는 디스패치
    시점에만 알 수 있고, 그것을 적는 자리가 `subagent_gate.record_worker_dispatch` 다. 영수증이
    없으면 빈 문자열을 돌려준다 — 서브에이전트가 없는 모드(mode A)에서는 그것이 사실이다.
    """
    directory = os.path.join(root, ".asgard", "quest", "receipts", qid)
    try:
        names = [name for name in os.listdir(directory) if name.startswith("dispatch-")]
    except OSError:
        return ""
    for name in names:
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                record = json.load(handle)
        except UNREADABLE_RECEIPT:  # 읽기·JSON 두 갈래 다 "이 영수증은 못 읽는다" 로 같다
            continue
        if str(record.get("unit")) == str(unit):
            return str(record.get("agent_type") or "")
    return ""


def _siege_mirror(root: str, qid: str, cmd: str, unit: str, payload: dict) -> None:
    """티켓 전이를 배차 장부(`.asgard/orchestration.db`)에도 적으라고 CLI 에 던진다.

    호스트 모드(Claude Code·Cursor·Codex)에서 장부가 적히는 **유일한 경로**다. 네이티브 루프는
    `agent/heimdall/bifrost.py` 가 같은 계약을 프로세스 안에서 부르지만 세 호스트 모드에는 그
    루프가 없어서, 여기가 없으면 그 모드들에서 `asgard siege` 는 언제나 빈 장부를 보여 준다.

    **종전에는 여기서 `from asgard import orchestration` 을 했고, 그 임포트는 한 번도 성공한
    적이 없다.** 배포본 훅은 `uv run --no-project python` 으로 돌아 그 인터프리터에 asgard 가
    없다 (26-08-06 실측). fail-open 이라 실패가 조용해서, 장부를 채우는 코드가 다 있는 채로
    세 모드가 전부 빈 장부를 보고 있었다. 이제 CLI 프로세스로 던진다 (`asgard_hooklib.siege`).

    네이티브 루프가 잡은 단위는 안 던진다 — 그쪽은 이미 프로세스 안에서 같은 배차를 적고
    있고, 둘이 적으면 한 Task 를 둘이 열어 뒤에 부른 쪽이 조용히 버려진다.

    호출은 Quest lock 밖에 있고 답을 안 기다린다. 장부는 퀘스트 로그에서 파생된 것이고,
    파생을 얻으려다 정본의 전이를 늦추면 안 된다.
    """
    try:
        owner = payload.get("worker_id") or (fold_tickets(load_events(root, qid)).get(str(unit)) or {}).get("worker_id")
        if _native_loop_owns_the_ledger(owner):
            return
        ledger_call(root, ["mirror", cmd, "--quest", qid, "--unit", str(unit), "--payload", json.dumps(payload)])
    except Exception:
        # 장부가 없거나 CLI 가 없어도 티켓 전이는 이미 정본에 적혔다.
        return


def ticket_runtime(
    root: str,
    qid: str,
    cmd: str,
    *,
    unit: str | None,
    session: str,
    worker: str | None = None,
    claim_token: str | None = None,
    lease_seconds: int = 300,
    max_attempts: int = 3,
    status: str | None = None,
    error: str | None = None,
) -> tuple[int, dict]:
    """Ticket claim/lease 상태 전이를 Quest lock 아래에서 검사+기록하고, 배차 장부에 옮긴다."""
    now = time.time()
    lease_seconds = max(1, min(int(lease_seconds), 86400))
    max_attempts = max(1, min(int(max_attempts), 20))
    with quest_lock(root, qid):
        events = load_events(root, qid)

        def emit(raw: dict) -> dict:
            event = normalize({"role": "worker", "event": "ticket", **raw}, events, qid, session)
            write_event_unlocked(root, qid, event, events)
            events.append(event)
            return event

        tickets = fold_tickets(events)
        if cmd == "ticket-recover":
            code, payload = _ticket_recover(emit, tickets, now, max_attempts)
        elif not (ticket := tickets.get(str(unit))):
            return 1, {"error": "unknown ticket", "unit": unit}
        elif cmd == "ticket-claim":
            code, payload = _ticket_claim(emit, tickets, ticket, now, worker, lease_seconds, max_attempts)
        elif denial := _ticket_lease_denial(ticket, claim_token, now):
            return 1, denial
        elif cmd == "ticket-heartbeat":
            code, payload = _ticket_heartbeat(emit, ticket, now, lease_seconds, max_attempts)
        elif cmd == "ticket-finish":
            code, payload = _ticket_finish(emit, ticket, now, max_attempts, status, error)
        else:
            return 2, {"error": "unknown ticket runtime command"}
    # 장부는 lock 밖에서 적는다 — 아래를 참조.
    if code == 0 and unit and cmd != "ticket-recover":
        _siege_mirror(root, qid, cmd, str(unit), payload)
    return code, payload
