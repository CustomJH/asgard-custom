"""폴더마다 보드가 하나이던 시절의 저장소를 워크스페이스로 들여온다.

**원본은 안 건드린다.** 옛 파일(`<프로젝트>/.asgard/studio/studio.db`)은 읽기 전용으로만 열고,
반입이 끝나도 지우지 않는다 — 반입이 뭔가 잘못됐을 때 돌아갈 곳이 있어야 하기 때문이다.
두 번 부르면 두 번 들어오지 않는다: 저장소 안 결속 파일이 '이미 왔다'를 들고 있다.

**번호를 지킨다.** 옛 보드의 `ASG-12`는 새 팀에서도 `ASG-12` 다. 접두어가 이미 다른 팀에
쓰이고 있으면 그때만 팀 키를 비켜 주고(`ASG2`), 그 사실을 반입 결과에 적어 돌려준다 —
조용히 번호를 바꾸면 어제 적어 둔 메모가 오늘 다른 티켓을 가리킨다.
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any
from uuid import uuid4

from .db import legacy_db_path, open_legacy, read_bind, write_bind, writing
from .teams import _free_key, _insert_team, key_from_name

__all__ = ["import_root", "pending_roots", "was_imported"]

_MARK = "imported_from"


def was_imported(root: str) -> bool:
    return bool(read_bind(root).get(_MARK))


def pending_roots(roots: list[str]) -> list[str]:
    """아직 안 들여온 옛 보드를 든 폴더들 — 창과 CLI가 '들여올까요?'를 물을 근거."""
    return [root for root in roots if root and os.path.isfile(legacy_db_path(root)) and not was_imported(root)]


def _rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    try:
        return conn.execute(f"SELECT * FROM {table}").fetchall()
    except sqlite3.DatabaseError:
        return []


def _has(row: sqlite3.Row, column: str) -> bool:
    return column in row.keys()


def import_root(root: str, *, force: bool = False) -> dict[str, Any]:
    """옛 보드 하나를 팀 하나로 들여온다. 결과는 무엇이 몇 건 왔는지."""
    root = os.path.abspath(root)
    path = legacy_db_path(root)
    out: dict[str, Any] = {"root": root, "imported": False, "tickets": 0, "reason": ""}
    if not os.path.isfile(path):
        out["reason"] = "이 폴더에는 옛 보드가 없어요"
        return out
    if was_imported(root) and not force:
        out["reason"] = "이미 들여온 보드예요"
        return out

    old = open_legacy(root)
    if old is None:
        out["reason"] = "옛 보드를 열지 못했어요"
        return out
    try:
        tickets = _rows(old, "tickets")
        cycles = _rows(old, "cycles")
        labels = _rows(old, "labels")
        ticket_labels = _rows(old, "ticket_labels")
        links = _rows(old, "ticket_links")
        comments = _rows(old, "comments")
        activity = _rows(old, "activity")
        stored_prefix = ""
        meta = _rows(old, "meta")
        for row in meta:
            if row["key"] == "prefix":
                stored_prefix = str(row["value"])
    finally:
        old.close()

    wanted = stored_prefix or key_from_name(os.path.basename(root))
    now = time.time()
    with writing() as conn:
        key = _free_key(conn, wanted)
        team = _insert_team(conn, os.path.basename(root) or "Work", key)
        team_id = str(team["id"])
        conn.execute(
            "INSERT INTO team_roots(root, team_id, created_at) VALUES(?,?,?) "
            "ON CONFLICT(root) DO UPDATE SET team_id = excluded.team_id",
            (root, team_id, now),
        )

        cycle_map: dict[str, str] = {}
        for row in cycles:
            new_id = uuid4().hex
            cycle_map[str(row["id"])] = new_id
            conn.execute(
                "INSERT INTO cycles(id, team_id, number, name, starts_at, ends_at, closed_at, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    new_id,
                    team_id,
                    int(row["number"]),
                    str(row["name"] or ""),
                    row["starts_at"],
                    row["ends_at"],
                    row["closed_at"],
                    float(row["created_at"] or now),
                ),
            )

        label_map: dict[str, str] = {}
        for row in labels:
            found = conn.execute("SELECT id FROM labels WHERE name = ? COLLATE NOCASE", (str(row["name"]),)).fetchone()
            if found:
                label_map[str(row["id"])] = str(found["id"])
                continue
            new_id = uuid4().hex
            label_map[str(row["id"])] = new_id
            conn.execute(
                "INSERT INTO labels(id, team_id, group_name, name, color, created_at) VALUES(?,NULL,'',?,?,?)",
                (new_id, str(row["name"]), str(row["color"] or "slate"), float(row["created_at"] or now)),
            )

        ticket_map: dict[str, str] = {}
        top_seq = 0
        for row in tickets:
            new_id = uuid4().hex
            ticket_map[str(row["id"])] = new_id
            seq = int(row["seq"])
            top_seq = max(top_seq, seq)
            conn.execute(
                "INSERT INTO tickets(id, key, seq, team_id, title, body, status, priority, estimate, assignee, "
                "reporter, source, parent_id, cycle_id, project_id, milestone_id, triage, snoozed_at, root, "
                "plan_id, plan_record, task_id, position, created_at, updated_at, started_at, completed_at, "
                "canceled_at, due_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,NULL,NULL,0,NULL,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id,
                    f"{key}-{seq}",
                    seq,
                    team_id,
                    str(row["title"]),
                    str(row["body"] or ""),
                    str(row["status"]),
                    int(row["priority"] or 0),
                    row["estimate"],
                    str(row["assignee"] or ""),
                    str(row["reporter"] or ""),
                    str(row["source"] or "user"),
                    cycle_map.get(str(row["cycle_id"] or "")),
                    root,
                    str(row["plan_id"] or ""),
                    str(row["plan_record"] or ""),
                    str(row["task_id"] or ""),
                    float(row["position"] or 0),
                    float(row["created_at"] or now),
                    float(row["updated_at"] or now),
                    row["started_at"],
                    row["completed_at"],
                    row["canceled_at"],
                    row["due_at"],
                ),
            )
        # 상위/하위는 두 번째 바퀴에 잇는다 — 첫 바퀴에서는 부모가 아직 없을 수 있다.
        for row in tickets:
            parent = str(row["parent_id"] or "")
            if parent and parent in ticket_map:
                conn.execute(
                    "UPDATE tickets SET parent_id = ? WHERE id = ?",
                    (ticket_map[parent], ticket_map[str(row["id"])]),
                )
        conn.execute("UPDATE teams SET seq = ? WHERE id = ?", (top_seq, team_id))

        for row in ticket_labels:
            ticket = ticket_map.get(str(row["ticket_id"]))
            label = label_map.get(str(row["label_id"]))
            if ticket and label:
                conn.execute("INSERT OR IGNORE INTO ticket_labels(ticket_id, label_id) VALUES(?,?)", (ticket, label))
        for row in links:
            source = ticket_map.get(str(row["source_id"]))
            target = ticket_map.get(str(row["target_id"]))
            if source and target:
                conn.execute(
                    "INSERT OR IGNORE INTO ticket_links(source_id, target_id, kind, created_at) VALUES(?,?,?,?)",
                    (source, target, str(row["kind"]), float(row["created_at"] or now)),
                )
        for row in comments:
            ticket = ticket_map.get(str(row["ticket_id"]))
            if ticket:
                conn.execute(
                    "INSERT INTO comments(id, ticket_id, author, body, created_at) VALUES(?,?,?,?,?)",
                    (uuid4().hex, ticket, str(row["author"] or ""), str(row["body"]), float(row["created_at"] or now)),
                )
        for row in activity:
            ticket = ticket_map.get(str(row["ticket_id"]))
            if ticket:
                conn.execute(
                    "INSERT INTO activity(ticket_id, actor, field, before, after, created_at) VALUES(?,?,?,?,?,?)",
                    (
                        ticket,
                        str(row["actor"] or ""),
                        str(row["field"]),
                        str(row["before"] or ""),
                        str(row["after"] or ""),
                        float(row["created_at"] or now),
                    ),
                )

    write_bind(root, team_id, key)
    _mark(root, team_id, key, path)
    out.update(
        {
            "imported": True,
            "team": key,
            "team_id": team_id,
            "tickets": len(tickets),
            "cycles": len(cycles),
            "labels": len(labels),
            "comments": len(comments),
            "renamed": bool(stored_prefix and key != stored_prefix),
            "was": stored_prefix,
            "source": path,
        }
    )
    return out


def _mark(root: str, team_id: str, key: str, source: str) -> None:
    """'이미 왔다'를 저장소 안에 적는다 — 두 번 부르면 두 번 들어오지 않게."""
    import json

    payload = {"team": team_id, "key": key, _MARK: source, "imported_at": time.time()}
    try:
        with open(os.path.join(os.path.dirname(source), "team.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
    except OSError:
        pass
