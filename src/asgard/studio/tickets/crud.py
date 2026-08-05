"""티켓 — 쓰는 면. 발급·수정·이동·삭제, 그리고 댓글과 차단 관계."""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any
from uuid import uuid4

from ..db import writing
from ..teams import find_cycle, find_team, next_key
from ..vocab import (
    LINK_KINDS,
    PRIORITY_LABEL,
    SOURCES,
    STATUS_LABEL,
)
from ._core import (
    _MAX_BODY,
    _MAX_COMMENT,
    _MAX_NAME,
    _MAX_TICKETS,
    _MAX_TITLE,
    _MUTABLE,
    _SILENT_FIELDS,
    TicketError,
    _estimate,
    _find,
    _log,
    _moment,
    _now,
    _priority,
    _read_scope,
    _resolve,
    _status,
    _team_statuses,
    _text,
    _type_of,
    _write_team,
)
from .labels import _set_labels
from .views import _detail

# ── 티켓 ───────────────────────────────────────────────────────────────────────


def create_ticket(
    root: str,
    title: str,
    *,
    body: str = "",
    status: str = "todo",
    priority: int = 0,
    estimate: Any = None,
    assignee: str = "",
    reporter: str = "",
    source: str = "user",
    parent: Any = None,
    cycle: Any = None,
    team: Any = None,
    project: Any = None,
    milestone: Any = None,
    triage: bool = False,
    labels: Any = (),
    due_at: Any = None,
    plan_id: str = "",
    plan_record: str = "",
    task_id: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """티켓 한 건을 끊는다. 팀을 안 주면 **결속된 폴더의 팀**이, 결속이 없으면 기본 팀이 받는다."""
    # 검증은 저장소를 열기 전에 끝낸다 — 잘못된 입력이 빈 워크스페이스를 남기지 않게.
    fields = _new_fields(title, body, priority, estimate, assignee, reporter, source, due_at)
    fields |= {
        key: _text(value, key, 64)
        for key, value in (("plan_id", plan_id), ("plan_record", plan_record), ("task_id", task_id))
    }
    with writing() as conn:
        if conn.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"] >= _MAX_TICKETS:
            raise TicketError(f"this workspace already holds {_MAX_TICKETS} tickets")
        owner = _write_team(conn, root, team)
        fields["team_id"] = str(owner["id"])
        fields["status"] = _status(status, _team_statuses(conn, fields["team_id"]))
        fields.update(_status_moments(conn, fields["team_id"], fields["status"]))
        fields["parent_id"] = _new_parent(conn, parent)
        fields["cycle_id"] = _new_cycle(conn, fields["team_id"], cycle)
        fields["project_id"], fields["milestone_id"] = _new_project(conn, project, milestone)
        fields["triage"] = 1 if (triage or (source == "agent" and owner["triage"])) else 0
        fields["root"] = os.path.abspath(root) if root else ""
        fields["key"], fields["seq"] = next_key(conn, owner)
        fields["id"] = uuid4().hex
        fields["position"] = _tail_position(conn, fields["team_id"], fields["status"])
        columns = ", ".join(fields)
        conn.execute(f"INSERT INTO tickets({columns}) VALUES({', '.join('?' * len(fields))})", list(fields.values()))
        if labels:
            _set_labels(conn, fields["id"], list(labels), actor, log=False)
        _log(
            conn,
            fields["id"],
            actor or fields["reporter"],
            "created",
            "",
            f"{fields['key']} · {STATUS_LABEL.get(fields['status'], fields['status'])}",
        )
        return _detail(conn, conn.execute("SELECT * FROM tickets WHERE id = ?", (fields["id"],)).fetchone())


def _new_fields(
    title: str,
    body: str,
    priority: int,
    estimate: Any,
    assignee: str,
    reporter: str,
    source: str,
    due_at: Any,
) -> dict[str, Any]:
    """새 티켓의 검사 끝난 칸들 — 상태와 무관한 것만. 상태가 함의하는 시각은 팀을 알아야
    찍을 수 있어서(범주가 팀의 워크플로에 달렸다) `_status_moments`가 따로 진다."""
    if source not in SOURCES:
        raise TicketError(f"source must be one of: {', '.join(SOURCES)}")
    now = _now()
    return {
        "title": _text(title, "title", _MAX_TITLE, required=True),
        "body": _text(body, "body", _MAX_BODY),
        "priority": _priority(priority),
        "estimate": _estimate(estimate),
        "assignee": _text(assignee, "assignee", _MAX_NAME),
        "reporter": _text(reporter, "reporter", _MAX_NAME),
        "source": source,
        "created_at": now,
        "updated_at": now,
        "due_at": _moment(due_at, "due_at"),
    }


def _status_moments(conn: sqlite3.Connection, team_id: str | None, status: str) -> dict[str, Any]:
    """`todo`로 만든 티켓에 `started_at`이 붙어 있으면 리드타임이 처음부터 거짓말한다."""
    kind, now = _type_of(conn, team_id, status), _now()
    return {
        "started_at": now if kind == "started" else None,
        "completed_at": now if kind == "completed" else None,
        "canceled_at": now if kind == "canceled" else None,
    }


def _new_parent(conn: sqlite3.Connection, parent: Any) -> str | None:
    if not parent:
        return None
    row = _resolve(conn, parent, "parent ticket")
    if row["parent_id"]:
        # 두 겹까지만. 세 겹이 되는 순간 보드는 트리 뷰어가 되고, 사람은 어디가 일감인지 잃는다.
        raise TicketError(f"{row['key']} is already a sub-ticket; nesting stops at one level")
    return str(row["id"])


def _new_cycle(conn: sqlite3.Connection, team_id: str | None, cycle: Any) -> str | None:
    if not cycle:
        return None
    row = find_cycle(conn, team_id, cycle)
    if row is None:
        raise TicketError(f"cycle not found: {cycle}")
    return str(row["id"])


def _new_project(conn: sqlite3.Connection, project: Any, milestone: Any) -> tuple[str | None, str | None]:
    """프로젝트와 그 안의 마일스톤. 마일스톤만 주는 것은 안 받는다 — 어느 프로젝트의
    마일스톤인지 모르면 진척이 어느 쪽으로 굴러가는지도 모른다."""
    if not project:
        if milestone:
            raise TicketError("a milestone needs its project — pass project as well")
        return None, None
    from ..projects import ProjectError, _resolve_milestone, resolve_project

    try:
        row = resolve_project(conn, project)
    except ProjectError as exc:
        raise TicketError(str(exc)) from exc
    if not milestone:
        return str(row["id"]), None
    try:
        stone = _resolve_milestone(conn, str(row["id"]), milestone)
    except ProjectError as exc:
        raise TicketError(str(exc)) from exc
    return str(row["id"]), str(stone["id"])


def _tail_position(conn: sqlite3.Connection, team_id: str | None, status: str) -> float:
    row = conn.execute(
        "SELECT MAX(position) AS top FROM tickets WHERE status = ? AND IFNULL(team_id,'') = ?",
        (status, team_id or ""),
    ).fetchone()
    return (float(row["top"]) if row and row["top"] is not None else 0.0) + 1.0


def update_ticket(root: str, ref: Any, changes: dict[str, Any], actor: str = "") -> dict[str, Any]:
    """부분 갱신 — 준 칸만 바꾼다. 안 준 칸은 남의 수정이라 건드리지 않는다."""
    if not isinstance(changes, dict):
        raise TicketError("changes must be an object")
    unknown = [key for key in changes if key not in _MUTABLE]
    if unknown:
        raise TicketError(f"unknown field(s): {', '.join(sorted(unknown))}")
    with writing() as conn:
        row = _resolve(conn, ref, scope=_read_scope(conn, root))
        return _detail(conn, _apply(conn, row, changes, actor))


def _apply(conn: sqlite3.Connection, row: sqlite3.Row, changes: dict[str, Any], actor: str) -> sqlite3.Row:
    ticket_id = row["id"]
    team_id = row["team_id"]
    sets: dict[str, Any] = {}
    if "team" in changes:
        # 팀을 옮겨도 **번호는 안 바뀐다**. `NOR-12`는 이미 대화에 나온 이름이라, 옮겼다고
        # 다시 발급하면 그 대화가 가리키는 것이 사라진다(Linear도 이때 번호를 새로 준다는
        # 점이 다른데, 여기서는 대화가 유일한 색인이라 이름을 지키는 쪽이 더 크다).
        target = find_team(conn, changes["team"])
        if target is None:
            raise TicketError(f"team not found: {changes['team']}")
        sets["team_id"] = str(target["id"])
        team_id = sets["team_id"]
    if "title" in changes:
        sets["title"] = _text(changes["title"], "title", _MAX_TITLE, required=True)
    if "body" in changes:
        sets["body"] = _text(changes["body"], "body", _MAX_BODY)
    if "priority" in changes:
        sets["priority"] = _priority(changes["priority"])
    if "estimate" in changes:
        sets["estimate"] = _estimate(changes["estimate"])
    if "assignee" in changes:
        sets["assignee"] = _text(changes["assignee"], "assignee", _MAX_NAME)
    if "reporter" in changes:
        sets["reporter"] = _text(changes["reporter"], "reporter", _MAX_NAME)
    if "due_at" in changes:
        sets["due_at"] = _moment(changes["due_at"], "due_at")
    if "triage" in changes:
        sets["triage"] = 1 if changes["triage"] else 0
    for field in ("plan_id", "plan_record", "task_id"):
        if field in changes:
            sets[field] = _text(changes[field], field, 64)
    if "parent" in changes:
        sets["parent_id"] = _parent_id(conn, row, changes["parent"])
    if "cycle" in changes:
        target = find_cycle(conn, team_id, changes["cycle"]) if changes["cycle"] else None
        if changes["cycle"] and target is None:
            raise TicketError(f"cycle not found: {changes['cycle']}")
        sets["cycle_id"] = target["id"] if target is not None else None
    if "project" in changes or "milestone" in changes:
        project = changes.get("project", row["project_id"])
        stone = changes.get("milestone")
        if "project" in changes and not project:
            sets["project_id"], sets["milestone_id"] = None, None
        else:
            sets["project_id"], sets["milestone_id"] = _new_project(conn, project, stone)
    if "status" in changes:
        sets.update(_status_change(conn, row, _status(changes["status"], _team_statuses(conn, team_id))))

    for field, value in sets.items():
        before, after = row[field], value
        if before == after:
            continue
        conn.execute(f"UPDATE tickets SET {field} = ? WHERE id = ?", (after, ticket_id))
        if field not in _SILENT_FIELDS:  # 시각과 자리는 상태 변경의 그림자다 — 따로 안 적는다
            _log(conn, ticket_id, actor, field, _name(conn, field, before), _name(conn, field, after))
    if "labels" in changes:
        _set_labels(conn, ticket_id, changes["labels"], actor)
    conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (_now(), ticket_id))
    return conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()


def _parent_id(conn: sqlite3.Connection, row: sqlite3.Row, value: Any) -> str | None:
    if not value:
        return None
    parent = _resolve(conn, value, "parent ticket")
    if parent["id"] == row["id"]:
        raise TicketError("a ticket cannot be its own parent")
    if parent["parent_id"]:
        raise TicketError(f"{parent['key']} is already a sub-ticket; nesting stops at one level")
    kids = conn.execute("SELECT COUNT(*) AS n FROM tickets WHERE parent_id = ?", (row["id"],)).fetchone()["n"]
    if kids:
        raise TicketError(f"{row['key']} already has sub-tickets; it cannot become one")
    return str(parent["id"])


def _status_change(conn: sqlite3.Connection, row: sqlite3.Row, status: str) -> dict[str, Any]:
    """상태와 그 상태가 함의하는 시각을 함께 낸다.

    되돌릴 때 시각을 지우는 것이 핵심이다 — `completed_at`이 남은 '진행 중' 티켓은 리드타임을
    조용히 거짓말한다. 다시 진행으로 가면 `started_at`은 **처음 시작한 때를 지킨다**(재개는
    새 시작이 아니다)."""
    if status == row["status"]:
        return {}
    kind = _type_of(conn, row["team_id"], status)
    now = _now()
    out: dict[str, Any] = {"status": status, "position": _tail_position(conn, row["team_id"], status)}
    if kind == "started":
        out["started_at"] = row["started_at"] or now  # 재개는 새 시작이 아니다
    elif kind in {"backlog", "unstarted"}:
        out["started_at"] = None  # 아직 손대지 않은 자리로 되돌렸다
    else:
        out["started_at"] = row["started_at"]  # 끝나거나 접혀도 언제 시작했는지는 지킨다
    out["completed_at"] = now if kind == "completed" else None
    out["canceled_at"] = now if kind == "canceled" else None
    return out


def _name(conn: sqlite3.Connection, field: str, value: Any) -> str:
    """활동 줄에 적힐 사람 말.

    id를 그대로 적으면 안 된다 — '주기 → 0ff957e74e7c…'는 아무에게도 아무 말이 아니다.
    이 자리는 나중에 읽는 사람을 위한 것이라, 저장하는 순간의 이름을 굳혀 둔다(주기 이름이
    나중에 바뀌어도 그때 그렇게 불렀다는 기록은 그대로다)."""
    if field == "status":
        return STATUS_LABEL.get(str(value), str(value or ""))
    if field == "priority":
        return PRIORITY_LABEL.get(int(value or 0), str(value))
    if field == "triage":
        return "트리아지" if value else ""
    if value in (None, ""):
        return ""
    if field == "parent_id":
        row = conn.execute("SELECT key FROM tickets WHERE id = ?", (value,)).fetchone()
        return str(row["key"]) if row else ""
    if field == "team_id":
        row = conn.execute("SELECT key FROM teams WHERE id = ?", (value,)).fetchone()
        return str(row["key"]) if row else ""
    if field == "project_id":
        row = conn.execute("SELECT name FROM projects WHERE id = ?", (value,)).fetchone()
        return str(row["name"]) if row else ""
    if field == "milestone_id":
        row = conn.execute("SELECT name FROM milestones WHERE id = ?", (value,)).fetchone()
        return str(row["name"]) if row else ""
    if field == "cycle_id":
        row = conn.execute("SELECT number, name FROM cycles WHERE id = ?", (value,)).fetchone()
        return str(row["name"] or f"주기 {row['number']}") if row else ""
    if field == "due_at":
        return time.strftime("%Y-%m-%d", time.localtime(float(value)))
    return str(value)


def move_ticket(root: str, ref: Any, status: str, index: Any = None, actor: str = "") -> dict[str, Any]:
    """보드에서 칸을 옮기고 그 칸 안의 자리를 정한다.

    자리는 옮긴 뒤 그 칸을 통째로 0,1,2… 로 다시 매긴다. 부동소수 중점을 쪼개는 방식보다
    쓰기가 몇 줄 더 늘지만(칸 하나는 수십 건이다) 순서가 표류하지 않는다."""
    with writing() as conn:
        row = _resolve(conn, ref, scope=_read_scope(conn, root))
        status = _status(status, _team_statuses(conn, row["team_id"]))
        if row["status"] != status:
            _apply(conn, row, {"status": status}, actor)
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (row["id"],)).fetchone()
        order = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM tickets WHERE status = ? AND IFNULL(team_id,'') = ? ORDER BY position, created_at",
                (status, row["team_id"] or ""),
            ).fetchall()
        ]
        order = [x for x in order if x != row["id"]]
        seat = len(order) if index is None else max(0, min(int(index), len(order)))
        order.insert(seat, row["id"])
        for position, ticket_id in enumerate(order):
            conn.execute("UPDATE tickets SET position = ? WHERE id = ?", (float(position), ticket_id))
        conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (_now(), row["id"]))
        return _detail(conn, conn.execute("SELECT * FROM tickets WHERE id = ?", (row["id"],)).fetchone())


def delete_ticket(root: str, ref: Any) -> bool:
    """티켓을 지운다. 번호는 돌아오지 않는다 — 대화에 남은 이름이 다른 일감을 가리키면 안 된다."""
    with writing() as conn:
        row = _find(conn, ref, _read_scope(conn, root))
        if row is None:
            return False
        conn.execute("DELETE FROM tickets WHERE id = ?", (row["id"],))
        return True


def add_comment(root: str, ref: Any, body: str, author: str = "") -> dict[str, Any]:
    body = _text(body, "comment", _MAX_COMMENT, required=True)
    author = _text(author, "author", _MAX_NAME)
    with writing() as conn:
        row = _resolve(conn, ref, scope=_read_scope(conn, root))
        comment_id = uuid4().hex
        now = _now()
        conn.execute(
            "INSERT INTO comments(id, ticket_id, author, body, created_at) VALUES(?,?,?,?,?)",
            (comment_id, row["id"], author, body, now),
        )
        conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now, row["id"]))
        _log(conn, row["id"], author, "comment", "", body[:120])
        return {"id": comment_id, "ticket": row["key"], "author": author, "body": body, "created_at": now}


def link_tickets(root: str, ref: Any, kind: str, other: Any, actor: str = "") -> dict[str, Any]:
    """`kind='blocks'` 면 ref가 other를 막는다. 방향은 한 번만 적고 반대편은 질의로 읽는다."""
    if kind not in LINK_KINDS:
        raise TicketError(f"kind must be one of: {', '.join(LINK_KINDS)}")
    with writing() as conn:
        scope = _read_scope(conn, root)
        source = _resolve(conn, ref, scope=scope)
        target = _resolve(conn, other, "linked ticket", scope=scope)
        if source["id"] == target["id"]:
            raise TicketError("a ticket cannot link to itself")
        if kind == "blocks" and _blocks(conn, target["id"], source["id"]):
            raise TicketError(f"{target['key']} already blocks {source['key']} — that would be a cycle")
        conn.execute(
            "INSERT OR IGNORE INTO ticket_links(source_id, target_id, kind, created_at) VALUES(?,?,?,?)",
            (source["id"], target["id"], kind, _now()),
        )
        _log(conn, source["id"], actor, kind, "", target["key"])
        return _detail(conn, conn.execute("SELECT * FROM tickets WHERE id = ?", (source["id"],)).fetchone())


def _blocks(conn: sqlite3.Connection, source_id: str, target_id: str) -> bool:
    """source가 target을 (여러 다리 건너서라도) 막고 있는가 — 순환 차단 검사."""
    seen, frontier = {source_id}, [source_id]
    while frontier:
        current = frontier.pop()
        rows = conn.execute(
            "SELECT target_id FROM ticket_links WHERE source_id = ? AND kind = 'blocks'", (current,)
        ).fetchall()
        for row in rows:
            if row["target_id"] == target_id:
                return True
            if row["target_id"] not in seen:
                seen.add(row["target_id"])
                frontier.append(row["target_id"])
    return False


def unlink_tickets(root: str, ref: Any, kind: str, other: Any) -> bool:
    with writing() as conn:
        scope = _read_scope(conn, root)
        source, target = _find(conn, ref, scope), _find(conn, other, scope)
        if source is None or target is None:
            return False
        cursor = conn.execute(
            "DELETE FROM ticket_links WHERE source_id = ? AND target_id = ? AND kind = ?",
            (source["id"], target["id"], kind),
        )
        return cursor.rowcount > 0
