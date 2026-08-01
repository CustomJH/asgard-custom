"""프로젝트 · 마일스톤 · 이니셔티브 — 팀을 가로지르는 축.

팀이 "누가 번호를 주는가"라면 프로젝트는 "무엇을 위해 하는가"다. 둘이 갈리는 이유는 실제
일이 그렇게 생겨서다: 결제 개편 하나가 서버 팀과 앱 팀을 동시에 건드리는데, 번호는 각자
팀에서 나와야 하고(대화의 이름) 진척은 하나로 세어야 한다(약속의 단위).

  이니셔티브 ── 프로젝트 여럿          회사/개인의 목표 (분기·반기 단위)
       프로젝트 ── 마일스톤 여럿       끝이 있는 일 (리드·목표일·건강도)
            └─ 티켓 (팀을 가로질러)    티켓은 프로젝트 **하나**에만 속한다

**티켓은 프로젝트 하나에만 속한다.** Linear와 같은 제약이고, 이유는 진척률이다: 한 티켓이
두 프로젝트에 걸리면 "80% 왔다"가 어느 쪽 80%인지 아무도 모른다.

**건강도는 사람이 적는다.** 진척률에서 자동으로 뽑으면 '늦고 있지만 괜찮은'과 '빠르지만
틀린'을 구분하지 못한다 — 계기가 아니라 위안이 된다([[vocab]]).
"""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any
from uuid import uuid4

from .. import errors
from .db import StoreError, exists, reading, writing
from .teams import resolve_team
from .vocab import (
    HEALTHS,
    INITIATIVE_STATUSES,
    PROJECT_OPEN,
    PROJECT_STATUSES,
)

__all__ = [
    "ProjectError",
    "StoreError",
    "add_milestone",
    "add_project_team",
    "add_resource",
    "add_update",
    "archive_project",
    "complete_milestone",
    "create_initiative",
    "create_project",
    "delete_milestone",
    "delete_project",
    "delete_resource",
    "find_project",
    "get_initiative",
    "get_project",
    "list_initiatives",
    "list_milestones",
    "list_projects",
    "list_resources",
    "list_updates",
    "resolve_project",
    "set_labels",
    "set_members",
    "update_initiative",
    "update_milestone",
    "update_project",
]

_MAX_NAME = 120
_MAX_BODY = 20_000
_MAX_UPDATE = 10_000
_ID = re.compile(r"^[0-9a-f]{32}$")


class ProjectError(errors.InvalidInput, ValueError):
    """프로젝트 어휘를 어겼다 — 호출자가 고칠 수 있는 잘못이다."""

    code = "invalid_project"


def _now() -> float:
    return time.time()


def _text(value: Any, field: str, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ProjectError(f"{field} must be text")
    value = value.strip()
    if required and not value:
        raise ProjectError(f"{field} is required")
    if len(value) > limit:
        raise ProjectError(f"{field} must be at most {limit} characters")
    return value


def _moment(value: Any, field: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectError(f"{field} must be a unix timestamp")
    return float(value)


def _priority(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1, 2, 3, 4):
        raise ProjectError("priority must be 0 (none), 1 (urgent), 2 (high), 3 (medium), or 4 (low)")
    return int(value)


# ── 프로젝트 ───────────────────────────────────────────────────────────────────


def _progress(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    """이 프로젝트의 진척 — 티켓 수로 센다.

    추정치(estimate)가 있으면 그쪽이 더 정확하지만, 팀마다 눈금이 다르고 안 쓰는 팀도 있다.
    두 수를 다 넣어 보내고 **어느 쪽을 볼지는 표면이 고른다** — 여기서 하나로 접으면
    추정을 안 쓰는 팀의 진척이 0으로 보인다."""
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done, "
        "SUM(CASE WHEN status = 'canceled' THEN 1 ELSE 0 END) AS canceled, "
        "SUM(CASE WHEN status NOT IN ('done','canceled') THEN 1 ELSE 0 END) AS open, "
        "IFNULL(SUM(estimate), 0) AS points, "
        "IFNULL(SUM(CASE WHEN status = 'done' THEN estimate ELSE 0 END), 0) AS points_done "
        "FROM tickets WHERE project_id = ? AND archived_at IS NULL",
        (project_id,),
    ).fetchone()
    total = int(row["total"] or 0)
    done = int(row["done"] or 0)
    scope = total - int(row["canceled"] or 0)
    points = int(row["points"] or 0)
    return {
        "total": total,
        "done": done,
        "open": int(row["open"] or 0),
        "canceled": int(row["canceled"] or 0),
        "progress": round(done / scope, 3) if scope else 0.0,
        "points": points,
        "points_done": int(row["points_done"] or 0),
        "points_progress": round(int(row["points_done"] or 0) / points, 3) if points else 0.0,
    }


def _project_row(conn: sqlite3.Connection, row: sqlite3.Row, *, deep: bool = False) -> dict[str, Any]:
    teams = [
        {"id": str(item["id"]), "key": str(item["key"]), "name": str(item["name"])}
        for item in conn.execute(
            "SELECT teams.* FROM teams JOIN project_teams ON project_teams.team_id = teams.id "
            "WHERE project_teams.project_id = ? ORDER BY teams.key",
            (row["id"],),
        )
    ]
    members = [
        str(item["member"])
        for item in conn.execute(
            "SELECT member FROM project_members WHERE project_id = ? ORDER BY member", (row["id"],)
        )
    ]
    out = {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "description": str(row["description"] or ""),
        "icon": str(row["icon"] or ""),
        "color": str(row["color"] or "gold"),
        "lead": str(row["lead"] or ""),
        "status": str(row["status"]),
        "priority": int(row["priority"] or 0),
        "health": str(row["health"] or ""),
        "initiative_id": str(row["initiative_id"] or ""),
        "starts_at": row["starts_at"],
        "target_at": row["target_at"],
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "completed_at": row["completed_at"],
        "canceled_at": row["canceled_at"],
        "archived": row["archived_at"] is not None,
        "open": str(row["status"]) in PROJECT_OPEN,
        "teams": teams,
        "members": members,
        **_progress(conn, str(row["id"])),
    }
    out["labels"] = [
        {"name": str(item["name"]), "color": str(item["color"] or "slate")}
        for item in conn.execute(
            "SELECT l.name, l.color FROM project_labels pl JOIN labels l ON l.id = pl.label_id "
            "WHERE pl.project_id = ? ORDER BY l.name COLLATE NOCASE",
            (row["id"],),
        )
    ]
    if deep:
        out["milestones"] = _milestones(conn, str(row["id"]))
        out["updates"] = _updates(conn, str(row["id"]))
        out["resources"] = _resources(conn, str(row["id"]))
        out["breakdown"] = _breakdown(conn, str(row["id"]))
    return out


def _breakdown(conn: sqlite3.Connection, project_id: str) -> dict[str, list[dict[str, Any]]]:
    """진척을 세 갈래로 쪼갠다 — 담당·라벨·사이클.

    Linear의 Progress 판이 이 셋을 탭으로 든다. 총계 하나만 보면 "80% 왔다"까지는 알아도
    **누가 남은 20%를 들고 있는지**를 모르는데, 프로젝트가 늦는 이유는 대개 거기 있다.
    담당 없는 몫은 지우지 않고 그대로 센다 — 주인 없는 일이 몇인지가 가장 쓸모 있는 수다."""

    def rows(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in conn.execute(sql, (project_id, *args)):
            total = int(item["total"] or 0)
            done = int(item["done"] or 0)
            out.append(
                {
                    "name": str(item["name"] or ""),
                    "total": total,
                    "done": done,
                    "progress": round(done / total, 3) if total else 0.0,
                }
            )
        return sorted(out, key=lambda item: (-item["total"], item["name"]))

    return {
        "assignees": rows(
            "SELECT assignee AS name, COUNT(*) AS total, "
            "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done "
            "FROM tickets WHERE project_id = ? AND archived_at IS NULL GROUP BY assignee"
        ),
        "labels": rows(
            "SELECT l.name AS name, COUNT(*) AS total, "
            "SUM(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) AS done "
            "FROM tickets t JOIN ticket_labels tl ON tl.ticket_id = t.id JOIN labels l ON l.id = tl.label_id "
            "WHERE t.project_id = ? AND t.archived_at IS NULL GROUP BY l.name"
        ),
        "cycles": rows(
            "SELECT IFNULL(c.name, '') AS name, COUNT(*) AS total, "
            "SUM(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) AS done "
            "FROM tickets t LEFT JOIN cycles c ON c.id = t.cycle_id "
            "WHERE t.project_id = ? AND t.archived_at IS NULL GROUP BY IFNULL(c.name, '')"
        ),
    }


# ── 자료(Resources) — 프로젝트가 기대는 바깥의 것들 ────────────────────────────


def _resources(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "url": str(row["url"] or ""),
            "kind": str(row["kind"] or "link"),
            "created_at": float(row["created_at"]),
        }
        for row in conn.execute(
            "SELECT * FROM project_resources WHERE project_id = ? ORDER BY position, created_at", (project_id,)
        )
    ]


def list_resources(ref: Any) -> list[dict[str, Any]]:
    if not exists():
        return []
    with reading() as conn:
        return _resources(conn, str(resolve_project(conn, ref)["id"]))


_URL_OK = ("http://", "https://", "file://")


def add_resource(ref: Any, title: str, url: str = "", kind: str = "link") -> dict[str, Any]:
    """자료 한 줄. 주소는 **열 수 있는 것만** 받는다 — `javascript:`를 목록에 담아 두면
    그 목록이 언젠가 클릭되는 실행 경로가 된다."""
    title = _text(title, "resource title", _MAX_NAME, required=True)
    url = _text(url, "resource url", 2000)
    if url and not url.startswith(_URL_OK):
        raise ProjectError(f"url must start with one of: {', '.join(_URL_OK)}")
    with writing() as conn:
        project = resolve_project(conn, ref)
        top = conn.execute(
            "SELECT MAX(position) AS p FROM project_resources WHERE project_id = ?", (project["id"],)
        ).fetchone()
        resource_id = uuid4().hex
        conn.execute(
            "INSERT INTO project_resources(id, project_id, title, url, kind, position, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (resource_id, project["id"], title, url, kind or "link", float(top["p"] or 0) + 1, _now()),
        )
        row = conn.execute("SELECT * FROM project_resources WHERE id = ?", (resource_id,)).fetchone()
        return {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "url": str(row["url"] or ""),
            "kind": str(row["kind"] or "link"),
            "created_at": float(row["created_at"]),
        }


def delete_resource(ref: Any, resource_id: str) -> bool:
    with writing() as conn:
        project = resolve_project(conn, ref)
        cur = conn.execute(
            "DELETE FROM project_resources WHERE project_id = ? AND id = ?", (project["id"], str(resource_id or ""))
        )
        return cur.rowcount > 0


def set_labels(ref: Any, names: Any) -> dict[str, Any]:
    """프로젝트 라벨을 통째로 갈아 끼운다 — 티켓 라벨과 같은 표를 쓴다(어휘가 하나여야 한다)."""
    if not isinstance(names, (list, tuple)):
        raise ProjectError("labels must be a list of names")
    with writing() as conn:
        project = resolve_project(conn, ref)
        conn.execute("DELETE FROM project_labels WHERE project_id = ?", (project["id"],))
        for name in names[:20]:
            clean = _text(name, "label name", 60, required=True)
            found = conn.execute("SELECT id FROM labels WHERE name = ? COLLATE NOCASE", (clean,)).fetchone()
            if found is None:
                label_id = uuid4().hex
                conn.execute(
                    "INSERT INTO labels(id, team_id, group_name, name, color, created_at) "
                    "VALUES(?,NULL,'',?,'slate',?)",
                    (label_id, clean, _now()),
                )
            else:
                label_id = str(found["id"])
            conn.execute(
                "INSERT OR IGNORE INTO project_labels(project_id, label_id) VALUES(?,?)", (project["id"], label_id)
            )
        return _project_row(conn, conn.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone())


def set_members(ref: Any, members: Any) -> dict[str, Any]:
    if not isinstance(members, (list, tuple)):
        raise ProjectError("members must be a list of names")
    with writing() as conn:
        project = resolve_project(conn, ref)
        conn.execute("DELETE FROM project_members WHERE project_id = ?", (project["id"],))
        for member in members[:50]:
            conn.execute(
                "INSERT OR IGNORE INTO project_members(project_id, member) VALUES(?,?)",
                (project["id"], _text(member, "member", 60, required=True)),
            )
        return _project_row(conn, conn.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone())


def create_project(name: str, **fields: Any) -> dict[str, Any]:
    name = _text(name, "project name", _MAX_NAME, required=True)
    status = str(fields.get("status") or "planned")
    if status not in PROJECT_STATUSES:
        raise ProjectError(f"project status must be one of: {', '.join(PROJECT_STATUSES)}")
    health = str(fields.get("health") or "")
    if health and health not in HEALTHS:
        raise ProjectError(f"health must be one of: {', '.join(HEALTHS)}")
    now = _now()
    project_id = uuid4().hex
    with writing() as conn:
        initiative_id = None
        if fields.get("initiative"):
            initiative_id = str(_resolve_initiative(conn, fields["initiative"])["id"])
        conn.execute(
            "INSERT INTO projects(id, name, description, icon, color, lead, status, priority, health, "
            "initiative_id, starts_at, target_at, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                project_id,
                name,
                _text(fields.get("description"), "description", _MAX_BODY),
                _text(fields.get("icon"), "icon", 8),
                _text(fields.get("color") or "gold", "color", 20),
                _text(fields.get("lead"), "lead", 60),
                status,
                _priority(fields.get("priority", 0)),
                health,
                initiative_id,
                _moment(fields.get("starts_at"), "starts_at"),
                _moment(fields.get("target_at"), "target_at"),
                now,
                now,
            ),
        )
        for team_ref in fields.get("teams") or ():
            team = resolve_team(conn, team_ref)
            conn.execute(
                "INSERT OR IGNORE INTO project_teams(project_id, team_id) VALUES(?,?)", (project_id, team["id"])
            )
        for member in fields.get("members") or ():
            conn.execute(
                "INSERT OR IGNORE INTO project_members(project_id, member) VALUES(?,?)",
                (project_id, _text(member, "member", 60, required=True)),
            )
        return _project_row(conn, conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())


def find_project(conn: sqlite3.Connection, ref: Any) -> sqlite3.Row | None:
    if not isinstance(ref, str):
        return None
    ref = ref.strip()
    if not ref:
        return None
    if _ID.fullmatch(ref):
        found = conn.execute("SELECT * FROM projects WHERE id = ?", (ref,)).fetchone()
        if found:
            return found
    return conn.execute("SELECT * FROM projects WHERE name = ? COLLATE NOCASE", (ref,)).fetchone()


def resolve_project(conn: sqlite3.Connection, ref: Any) -> sqlite3.Row:
    row = find_project(conn, ref)
    if row is None:
        raise ProjectError(f"project not found: {ref}")
    return row


def get_project(ref: Any) -> dict[str, Any]:
    with reading() as conn:
        return _project_row(conn, resolve_project(conn, ref), deep=True)


def list_projects(
    status: str = "", team: Any = None, initiative: Any = None, include_archived: bool = False
) -> list[dict[str, Any]]:
    if not exists():  # 읽기는 자리를 만들지 않는다
        return []
    with reading() as conn:
        clauses, values = [], []
        if not include_archived:
            clauses.append("projects.archived_at IS NULL")
        if status == "open":
            clauses.append(f"projects.status IN ({','.join('?' * len(PROJECT_OPEN))})")
            values.extend(PROJECT_OPEN)
        elif status:
            if status not in PROJECT_STATUSES:
                raise ProjectError(f"project status must be one of: {', '.join(PROJECT_STATUSES)}")
            clauses.append("projects.status = ?")
            values.append(status)
        join = ""
        if team:
            join = " JOIN project_teams ON project_teams.project_id = projects.id"
            clauses.append("project_teams.team_id = ?")
            values.append(str(resolve_team(conn, team)["id"]))
        if initiative:
            clauses.append("projects.initiative_id = ?")
            values.append(str(_resolve_initiative(conn, initiative)["id"]))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT projects.* FROM projects{join}{where} ORDER BY projects.target_at IS NULL, "
            "projects.target_at, projects.created_at",
            values,
        ).fetchall()
        return [_project_row(conn, row) for row in rows]


_PROJECT_MUTABLE = (
    "name",
    "description",
    "icon",
    "color",
    "lead",
    "status",
    "priority",
    "health",
    "initiative",
    "starts_at",
    "target_at",
)


def update_project(ref: Any, changes: dict[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - set(_PROJECT_MUTABLE)
    if unknown:
        raise ProjectError(f"unknown project field: {', '.join(sorted(unknown))}")
    with writing() as conn:
        row = resolve_project(conn, ref)
        sets: list[str] = []
        values: list[Any] = []
        for field, value in changes.items():
            if field == "status":
                if value not in PROJECT_STATUSES:
                    raise ProjectError(f"project status must be one of: {', '.join(PROJECT_STATUSES)}")
                # 상태가 함의한 시각도 같이 움직인다 — 되돌리면 지운다. 완료 시각이 남은
                # '진행 중' 프로젝트는 리드타임을 조용히 거짓말하게 만든다.
                sets += ["completed_at = ?", "canceled_at = ?"]
                values += [
                    _now() if value == "completed" else None,
                    _now() if value == "canceled" else None,
                ]
            elif field == "health":
                if value and value not in HEALTHS:
                    raise ProjectError(f"health must be one of: {', '.join(HEALTHS)}")
            elif field == "priority":
                value = _priority(value)
            elif field in ("starts_at", "target_at"):
                value = _moment(value, field)
            elif field == "initiative":
                value = str(_resolve_initiative(conn, value)["id"]) if value else None
                sets.append("initiative_id = ?")
                values.append(value)
                continue
            else:
                value = _text(
                    value, field, _MAX_BODY if field == "description" else _MAX_NAME, required=field == "name"
                )
            sets.append(f"{field} = ?")
            values.append(value)
        sets.append("updated_at = ?")
        values.append(_now())
        conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", (*values, row["id"]))
        return _project_row(
            conn, conn.execute("SELECT * FROM projects WHERE id = ?", (row["id"],)).fetchone(), deep=True
        )


def add_project_team(ref: Any, team_ref: Any, attached: bool = True) -> dict[str, Any]:
    with writing() as conn:
        row = resolve_project(conn, ref)
        team = resolve_team(conn, team_ref)
        if attached:
            conn.execute(
                "INSERT OR IGNORE INTO project_teams(project_id, team_id) VALUES(?,?)", (row["id"], team["id"])
            )
        else:
            conn.execute("DELETE FROM project_teams WHERE project_id = ? AND team_id = ?", (row["id"], team["id"]))
        return _project_row(conn, conn.execute("SELECT * FROM projects WHERE id = ?", (row["id"],)).fetchone())


def archive_project(ref: Any, archived: bool = True) -> dict[str, Any]:
    with writing() as conn:
        row = resolve_project(conn, ref)
        conn.execute(
            "UPDATE projects SET archived_at = ?, updated_at = ? WHERE id = ?",
            (_now() if archived else None, _now(), row["id"]),
        )
        return _project_row(conn, conn.execute("SELECT * FROM projects WHERE id = ?", (row["id"],)).fetchone())


def delete_project(ref: Any) -> bool:
    """프로젝트를 지운다 — 티켓은 안 지운다(프로젝트에서만 풀린다).

    티켓까지 지우면 프로젝트 하나를 잘못 지운 손이 몇 달치 일감을 같이 가져간다."""
    with writing() as conn:
        row = find_project(conn, ref)
        if row is None:
            return False
        conn.execute("UPDATE tickets SET project_id = NULL, milestone_id = NULL WHERE project_id = ?", (row["id"],))
        conn.execute("DELETE FROM projects WHERE id = ?", (row["id"],))
        return True


# ── 마일스톤 ───────────────────────────────────────────────────────────────────


def _milestone_row(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    counts = conn.execute(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done "
        "FROM tickets WHERE milestone_id = ? AND archived_at IS NULL",
        (row["id"],),
    ).fetchone()
    total = int(counts["total"] or 0)
    done = int(counts["done"] or 0)
    return {
        "id": str(row["id"]),
        "project_id": str(row["project_id"]),
        "name": str(row["name"]),
        "description": str(row["description"] or ""),
        "target_at": row["target_at"],
        "position": float(row["position"] or 0),
        "created_at": float(row["created_at"]),
        "completed_at": row["completed_at"],
        "done": done,
        "total": total,
        "progress": round(done / total, 3) if total else 0.0,
    }


def _milestones(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM milestones WHERE project_id = ? ORDER BY position, created_at", (project_id,)
    ).fetchall()
    return [_milestone_row(conn, row) for row in rows]


def list_milestones(ref: Any) -> list[dict[str, Any]]:
    with reading() as conn:
        return _milestones(conn, str(resolve_project(conn, ref)["id"]))


def add_milestone(ref: Any, name: str, target_at: Any = None, description: str = "") -> dict[str, Any]:
    name = _text(name, "milestone name", _MAX_NAME, required=True)
    with writing() as conn:
        project = resolve_project(conn, ref)
        top = conn.execute(
            "SELECT MAX(position) AS p FROM milestones WHERE project_id = ?", (project["id"],)
        ).fetchone()
        milestone_id = uuid4().hex
        conn.execute(
            "INSERT INTO milestones(id, project_id, name, description, target_at, position, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                milestone_id,
                project["id"],
                name,
                _text(description, "description", _MAX_BODY),
                _moment(target_at, "target_at"),
                float(top["p"] or 0) + 1,
                _now(),
            ),
        )
        return _milestone_row(conn, conn.execute("SELECT * FROM milestones WHERE id = ?", (milestone_id,)).fetchone())


def _resolve_milestone(conn: sqlite3.Connection, project_id: str | None, ref: Any) -> sqlite3.Row:
    text = str(ref or "").strip()
    if _ID.fullmatch(text):
        row = conn.execute("SELECT * FROM milestones WHERE id = ?", (text,)).fetchone()
    elif project_id:
        row = conn.execute(
            "SELECT * FROM milestones WHERE project_id = ? AND name = ? COLLATE NOCASE", (project_id, text)
        ).fetchone()
    else:
        row = None
    if row is None:
        raise ProjectError(f"milestone not found: {ref}")
    return row


def update_milestone(project_ref: Any, ref: Any, changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "description", "target_at", "position"}
    unknown = set(changes) - allowed
    if unknown:
        raise ProjectError(f"unknown milestone field: {', '.join(sorted(unknown))}")
    with writing() as conn:
        project = resolve_project(conn, project_ref)
        row = _resolve_milestone(conn, str(project["id"]), ref)
        sets, values = [], []
        for field, value in changes.items():
            if field == "target_at":
                value = _moment(value, field)
            elif field == "position":
                value = float(value)
            else:
                value = _text(
                    value, field, _MAX_BODY if field == "description" else _MAX_NAME, required=field == "name"
                )
            sets.append(f"{field} = ?")
            values.append(value)
        conn.execute(f"UPDATE milestones SET {', '.join(sets)} WHERE id = ?", (*values, row["id"]))
        return _milestone_row(conn, conn.execute("SELECT * FROM milestones WHERE id = ?", (row["id"],)).fetchone())


def complete_milestone(project_ref: Any, ref: Any, done: bool = True) -> dict[str, Any]:
    with writing() as conn:
        project = resolve_project(conn, project_ref)
        row = _resolve_milestone(conn, str(project["id"]), ref)
        conn.execute("UPDATE milestones SET completed_at = ? WHERE id = ?", (_now() if done else None, row["id"]))
        return _milestone_row(conn, conn.execute("SELECT * FROM milestones WHERE id = ?", (row["id"],)).fetchone())


def delete_milestone(project_ref: Any, ref: Any) -> bool:
    with writing() as conn:
        project = resolve_project(conn, project_ref)
        try:
            row = _resolve_milestone(conn, str(project["id"]), ref)
        except ProjectError:
            return False
        conn.execute("UPDATE tickets SET milestone_id = NULL WHERE milestone_id = ?", (row["id"],))
        conn.execute("DELETE FROM milestones WHERE id = ?", (row["id"],))
        return True


# ── 프로젝트 업데이트 ──────────────────────────────────────────────────────────


def _updates(conn: sqlite3.Connection, project_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM project_updates WHERE project_id = ? ORDER BY created_at DESC LIMIT ?", (project_id, limit)
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "author": str(row["author"] or ""),
            "health": str(row["health"] or ""),
            "body": str(row["body"]),
            "created_at": float(row["created_at"]),
        }
        for row in rows
    ]


def list_updates(ref: Any, limit: int = 20) -> list[dict[str, Any]]:
    with reading() as conn:
        return _updates(conn, str(resolve_project(conn, ref)["id"]), limit)


def add_update(ref: Any, body: str, health: str = "", author: str = "") -> dict[str, Any]:
    """진행 보고 한 줄. 건강도를 같이 주면 프로젝트의 현재 건강도도 그것으로 옮긴다 —
    보고와 계기판이 다른 말을 하면 둘 다 안 믿게 된다."""
    body = _text(body, "update body", _MAX_UPDATE, required=True)
    if health and health not in HEALTHS:
        raise ProjectError(f"health must be one of: {', '.join(HEALTHS)}")
    with writing() as conn:
        project = resolve_project(conn, ref)
        update_id = uuid4().hex
        conn.execute(
            "INSERT INTO project_updates(id, project_id, author, health, body, created_at) VALUES(?,?,?,?,?,?)",
            (update_id, project["id"], _text(author, "author", 60), health, body, _now()),
        )
        if health:
            conn.execute("UPDATE projects SET health = ?, updated_at = ? WHERE id = ?", (health, _now(), project["id"]))
        row = conn.execute("SELECT * FROM project_updates WHERE id = ?", (update_id,)).fetchone()
        return {
            "id": str(row["id"]),
            "author": str(row["author"] or ""),
            "health": str(row["health"] or ""),
            "body": str(row["body"]),
            "created_at": float(row["created_at"]),
        }


# ── 이니셔티브 ─────────────────────────────────────────────────────────────────


def _initiative_row(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    projects = conn.execute(
        "SELECT id, name, status FROM projects WHERE initiative_id = ? AND archived_at IS NULL ORDER BY created_at",
        (row["id"],),
    ).fetchall()
    rolled = [_progress(conn, str(item["id"])) for item in projects]
    total = sum(item["total"] for item in rolled)
    done = sum(item["done"] for item in rolled)
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "description": str(row["description"] or ""),
        "owner": str(row["owner"] or ""),
        "status": str(row["status"]),
        "priority": int(row["priority"] or 0),
        "target_at": row["target_at"],
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "archived": row["archived_at"] is not None,
        "projects": [
            {"id": str(item["id"]), "name": str(item["name"]), "status": str(item["status"])} for item in projects
        ],
        "total": total,
        "done": done,
        "progress": round(done / total, 3) if total else 0.0,
    }


def _resolve_initiative(conn: sqlite3.Connection, ref: Any) -> sqlite3.Row:
    text = str(ref or "").strip()
    if _ID.fullmatch(text):
        row = conn.execute("SELECT * FROM initiatives WHERE id = ?", (text,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM initiatives WHERE name = ? COLLATE NOCASE", (text,)).fetchone()
    if row is None:
        raise ProjectError(f"initiative not found: {ref}")
    return row


def create_initiative(name: str, **fields: Any) -> dict[str, Any]:
    name = _text(name, "initiative name", _MAX_NAME, required=True)
    status = str(fields.get("status") or "planned")
    if status not in INITIATIVE_STATUSES:
        raise ProjectError(f"initiative status must be one of: {', '.join(INITIATIVE_STATUSES)}")
    now = _now()
    initiative_id = uuid4().hex
    with writing() as conn:
        conn.execute(
            "INSERT INTO initiatives(id, name, description, owner, status, priority, target_at, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                initiative_id,
                name,
                _text(fields.get("description"), "description", _MAX_BODY),
                _text(fields.get("owner"), "owner", 60),
                status,
                _priority(fields.get("priority", 0)),
                _moment(fields.get("target_at"), "target_at"),
                now,
                now,
            ),
        )
        return _initiative_row(
            conn, conn.execute("SELECT * FROM initiatives WHERE id = ?", (initiative_id,)).fetchone()
        )


def list_initiatives(include_archived: bool = False) -> list[dict[str, Any]]:
    if not exists():
        return []
    with reading() as conn:
        clause = "" if include_archived else " WHERE archived_at IS NULL"
        rows = conn.execute(f"SELECT * FROM initiatives{clause} ORDER BY created_at").fetchall()
        return [_initiative_row(conn, row) for row in rows]


def get_initiative(ref: Any) -> dict[str, Any]:
    with reading() as conn:
        return _initiative_row(conn, _resolve_initiative(conn, ref))


def update_initiative(ref: Any, changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "description", "owner", "status", "priority", "target_at"}
    unknown = set(changes) - allowed
    if unknown:
        raise ProjectError(f"unknown initiative field: {', '.join(sorted(unknown))}")
    with writing() as conn:
        row = _resolve_initiative(conn, ref)
        sets, values = [], []
        for field, value in changes.items():
            if field == "status" and value not in INITIATIVE_STATUSES:
                raise ProjectError(f"initiative status must be one of: {', '.join(INITIATIVE_STATUSES)}")
            if field == "priority":
                value = _priority(value)
            elif field == "target_at":
                value = _moment(value, field)
            elif field != "status":
                value = _text(
                    value, field, _MAX_BODY if field == "description" else _MAX_NAME, required=field == "name"
                )
            sets.append(f"{field} = ?")
            values.append(value)
        sets.append("updated_at = ?")
        values.append(_now())
        conn.execute(f"UPDATE initiatives SET {', '.join(sets)} WHERE id = ?", (*values, row["id"]))
        return _initiative_row(conn, conn.execute("SELECT * FROM initiatives WHERE id = ?", (row["id"],)).fetchone())
