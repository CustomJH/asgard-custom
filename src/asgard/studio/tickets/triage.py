"""티켓 — 분류대. 밖에서 들어온 제안을 받거나 물리거나 미룬다."""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

from ..db import reading, writing
from ._core import _LIST_LIMIT, _MAX_COMMENT, TicketError, _log, _moment, _now, _read_scope, _resolve, _untouched
from .crud import _apply
from .views import _decorate, _detail

# ── 트리아지 — 팀의 인박스 ──────────────────────────────────────────────────────


def triage_queue(root: str | None = None, team: Any = None, limit: int = 100) -> list[dict[str, Any]]:
    """아직 받아들이지 않은 것들. 미룬 것(snooze)은 시간이 되기 전까지 빠진다.

    Linear의 트리아지와 같은 뜻이다: 밖에서 들어온 일감을 팀의 워크플로에 **넣기 전에**
    한 번 본다. 에이전트가 스스로 끊은 티켓이 여기 서는 이유가 그거다 — 기계가 만든 일감이
    사람의 백로그에 곧장 섞이면, 백로그는 곧 아무도 안 보는 목록이 된다."""
    if _untouched():
        return []
    now = _now()
    with reading() as conn:
        scope = _read_scope(conn, root, team)
        clause = "" if scope is None else " AND t.team_id = ?"
        args: list[Any] = [now]
        if scope is not None:
            args.append(scope["id"])
        rows = conn.execute(
            f"SELECT t.* FROM tickets t WHERE t.triage = 1 AND t.archived_at IS NULL "
            f"AND (t.snoozed_at IS NULL OR t.snoozed_at <= ?){clause} "
            f"ORDER BY t.created_at DESC LIMIT ?",
            [*args, max(1, min(int(limit), _LIST_LIMIT))],
        ).fetchall()
        return _decorate(conn, rows)


def triage_accept(root: str, ref: Any, status: str = "", actor: str = "", note: str = "") -> dict[str, Any]:
    """받아들인다 — 인박스에서 빼고 팀의 기본 상태로 넣는다."""
    with writing() as conn:
        row = _resolve(conn, ref, scope=_read_scope(conn, root))
        team = conn.execute("SELECT * FROM teams WHERE id = ?", (row["team_id"],)).fetchone()
        target = status or (str(team["default_status"]) if team else "todo")
        _apply(conn, row, {"triage": False, "status": target}, actor)
        if note:
            _comment(conn, row, note, actor)
        return _detail(conn, conn.execute("SELECT * FROM tickets WHERE id = ?", (row["id"],)).fetchone())


def triage_decline(root: str, ref: Any, actor: str = "", note: str = "") -> dict[str, Any]:
    """거절한다 — 취소로 닫고 인박스에서 뺀다. 지우지는 않는다(왜 거절했는지가 기록이다)."""
    with writing() as conn:
        row = _resolve(conn, ref, scope=_read_scope(conn, root))
        _apply(conn, row, {"triage": False, "status": "canceled"}, actor)
        if note:
            _comment(conn, row, note, actor)
        return _detail(conn, conn.execute("SELECT * FROM tickets WHERE id = ?", (row["id"],)).fetchone())


def triage_snooze(root: str, ref: Any, until: Any, actor: str = "") -> dict[str, Any]:
    """미룬다 — 그때가 되면 인박스에 다시 선다. 상태는 안 건드린다."""
    when = _moment(until, "until")
    if when is None:
        raise TicketError("snooze needs a unix timestamp to wake at")
    with writing() as conn:
        row = _resolve(conn, ref, scope=_read_scope(conn, root))
        conn.execute("UPDATE tickets SET snoozed_at = ?, updated_at = ? WHERE id = ?", (when, _now(), row["id"]))
        _log(conn, str(row["id"]), actor, "snoozed", "", time.strftime("%Y-%m-%d %H:%M", time.localtime(when)))
        return _detail(conn, conn.execute("SELECT * FROM tickets WHERE id = ?", (row["id"],)).fetchone())


def _comment(conn: sqlite3.Connection, row: sqlite3.Row, body: str, author: str) -> None:
    conn.execute(
        "INSERT INTO comments(id, ticket_id, author, body, created_at) VALUES(?,?,?,?,?)",
        (uuid4().hex, row["id"], author or "", body[:_MAX_COMMENT], _now()),
    )
