"""티켓 — 라벨. 팀 안에서 이름이 유일하고, 붙이고 떼는 것은 티켓 이력에 남는다."""

from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from ..db import reading, writing
from ..vocab import (
    LABEL_COLORS,
)
from ._core import _MAX_NAME, TicketError, _log, _now, _text, _untouched

# ── 라벨 ───────────────────────────────────────────────────────────────────────


def create_label(root: str, name: str, color: str = "slate", group: str = "") -> dict[str, Any]:
    name = _text(name, "label name", _MAX_NAME, required=True)
    if color not in LABEL_COLORS:
        raise TicketError(f"color must be one of: {', '.join(LABEL_COLORS)}")
    with writing() as conn:
        return _label_row(_ensure_label(conn, name, color, group))


def _ensure_label(conn: sqlite3.Connection, name: str, color: str = "slate", group: str = "") -> sqlite3.Row:
    row = conn.execute("SELECT * FROM labels WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row is not None:
        return row
    label_id = uuid4().hex
    conn.execute(
        "INSERT INTO labels(id, team_id, group_name, name, color, created_at) VALUES(?,NULL,?,?,?,?)",
        (label_id, group or "", name, color, _now()),
    )
    return conn.execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone()


def _label_row(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "color": row["color"], "group": row["group_name"] or ""}


def list_labels(root: str | None = None) -> list[dict[str, Any]]:
    if _untouched():
        return []
    with reading() as conn:
        rows = conn.execute(
            "SELECT l.id, l.name, l.color, l.group_name, COUNT(tl.ticket_id) AS count "
            "FROM labels l LEFT JOIN ticket_labels tl ON tl.label_id = l.id "
            "GROUP BY l.id ORDER BY l.name COLLATE NOCASE"
        ).fetchall()
    return [
        {"id": r["id"], "name": r["name"], "color": r["color"], "group": r["group_name"] or "", "count": r["count"]}
        for r in rows
    ]


def delete_label(root: str, name: str) -> bool:
    with writing() as conn:
        cursor = conn.execute("DELETE FROM labels WHERE name = ? COLLATE NOCASE", (str(name or "").strip(),))
        return cursor.rowcount > 0


def _set_labels(conn: sqlite3.Connection, ticket_id: str, names: Any, actor: str, log: bool = True) -> None:
    if not isinstance(names, (list, tuple)):
        raise TicketError("labels must be a list of names")
    if len(names) > 20:
        raise TicketError("a ticket may carry at most 20 labels")
    wanted = []
    for name in names:
        clean = _text(name, "label name", _MAX_NAME, required=True)
        if clean.lower() not in {x.lower() for x in wanted}:
            wanted.append(clean)
    before = sorted(_label_names(conn, ticket_id), key=str.lower)
    conn.execute("DELETE FROM ticket_labels WHERE ticket_id = ?", (ticket_id,))
    for name in wanted:
        label = _ensure_label(conn, name)
        conn.execute("INSERT OR IGNORE INTO ticket_labels(ticket_id, label_id) VALUES(?,?)", (ticket_id, label["id"]))
    after = sorted(wanted, key=str.lower)
    if log and before != after:
        _log(conn, ticket_id, actor, "labels", ", ".join(before), ", ".join(after))


def _label_names(conn: sqlite3.Connection, ticket_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT l.name FROM ticket_labels tl JOIN labels l ON l.id = tl.label_id WHERE tl.ticket_id = ?",
        (ticket_id,),
    ).fetchall()
    return [r["name"] for r in rows]
