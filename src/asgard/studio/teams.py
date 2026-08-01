"""팀 — 번호의 주인이자 워크플로·사이클·트리아지의 단위.

Linear의 계약을 그대로 든다: **티켓은 팀 하나에만 속한다.** 그래서 `NOR-12`의 앞자리는
팀이고, 번호는 그 팀 안에서만 단조 증가한다. 프로젝트는 팀을 가로지르지만 번호는 안 준다 —
한 티켓에 이름이 둘이면 대화가 깨지기 때문이다.

**폴더는 팀의 출신이지 팀 자체가 아니다.** 저장소에서 처음 티켓을 끊으면 그 폴더 이름에서
팀이 하나 선다(`nordic/` → `NOR`). 그 뒤로 폴더를 옮기든 지우든 팀은 워크스페이스에 남고,
폴더가 없는 팀도 설 수 있다(기획은 코드가 생기기 전에 시작한다). 결속은 양쪽에 적는다 —
워크스페이스의 `team_roots`와 저장소 안의 `.asgard/studio/team.json`.

**상태는 팀이 짓고 범주는 다섯으로 고정이다.** 이름을 열어 두는 이유는 팀마다 일하는 결이
달라서고, 범주를 닫아 두는 이유는 그래야 "열린 건수"를 셀 수 있어서다([[vocab]]).
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from typing import Any
from uuid import uuid4

from .. import errors
from .db import StoreError, exists, meta_get, meta_set, read_bind, reading, write_bind, writing
from .vocab import DEFAULT_STATES, ESTIMATE_SCALES, STATUS_TYPES

__all__ = [
    "StoreError",
    "TeamError",
    "archive_team",
    "close_cycle",
    "create_cycle",
    "create_state",
    "create_team",
    "cycles_for",
    "active_cycle",
    "default_team",
    "delete_state",
    "ensure_team",
    "find_team",
    "get_team",
    "list_states",
    "list_teams",
    "resolve_team",
    "roll_cycle",
    "update_state",
    "update_team",
]

_MAX_NAME = 60
_MAX_BODY = 20_000
_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")
_ID = re.compile(r"^[0-9a-f]{32}$")
_FALLBACK_KEY = "WRK"


class TeamError(errors.InvalidInput, ValueError):
    """팀 어휘를 어겼다 — 호출자가 고칠 수 있는 잘못이다."""

    code = "invalid_team"


def _now() -> float:
    return time.time()


def _text(value: Any, field: str, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise TeamError(f"{field} must be text")
    value = value.strip()
    if required and not value:
        raise TeamError(f"{field} is required")
    if len(value) > limit:
        raise TeamError(f"{field} must be at most {limit} characters")
    return value


# ── 키 ─────────────────────────────────────────────────────────────────────────


def key_from_name(name: str) -> str:
    """이름에서 팀 키를 뽑는다 — 폴더든 사람이 적은 이름이든 같은 규칙으로."""
    letters = re.sub(r"[^A-Za-z0-9]", "", str(name or "")).upper()
    letters = re.sub(r"^[0-9]+", "", letters)
    return (letters[:3] or _FALLBACK_KEY).ljust(2, "X")


def _free_key(conn: sqlite3.Connection, wanted: str) -> str:
    """이미 쓰는 키면 뒤에 숫자를 붙인다. 키는 유일해야 번호가 유일하다."""
    base = wanted[:7]
    taken = {str(row["key"]) for row in conn.execute("SELECT key FROM teams")}
    if base not in taken:
        return base
    for suffix in range(2, 100):
        candidate = f"{base[:6]}{suffix}"
        if candidate not in taken:
            return candidate
    return uuid4().hex[:6].upper()


# ── 팀 ─────────────────────────────────────────────────────────────────────────


def _team_row(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    roots = [
        str(item["root"])
        for item in conn.execute("SELECT root FROM team_roots WHERE team_id = ? ORDER BY created_at", (row["id"],))
    ]
    counts = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN triage = 1 THEN 1 ELSE 0 END) AS triaging "
        "FROM tickets WHERE team_id = ? AND archived_at IS NULL",
        (row["id"],),
    ).fetchone()
    return {
        "id": str(row["id"]),
        "key": str(row["key"]),
        "name": str(row["name"]),
        "description": str(row["description"] or ""),
        "color": str(row["color"] or "gold"),
        "triage": bool(row["triage"]),
        "estimates": str(row["estimates"] or ""),
        "cycle_weeks": int(row["cycle_weeks"] or 0),
        "cycle_cooldown": int(row["cycle_cooldown"] or 0),
        "default_status": str(row["default_status"] or "backlog"),
        "created_at": float(row["created_at"]),
        "archived": row["archived_at"] is not None,
        "roots": roots,
        "tickets": int(counts["total"] or 0) if counts else 0,
        "triaging": int(counts["triaging"] or 0) if counts else 0,
    }


def _seed_states(conn: sqlite3.Connection, team_id: str) -> None:
    now = _now()
    for index, (slug, name, kind, color) in enumerate(DEFAULT_STATES):
        conn.execute(
            "INSERT OR IGNORE INTO states(id, team_id, slug, name, type, color, position, created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (uuid4().hex, team_id, slug, name, kind, color, float(index), now),
        )


def _insert_team(conn: sqlite3.Connection, name: str, key: str, **fields: Any) -> sqlite3.Row:
    team_id = uuid4().hex
    now = _now()
    conn.execute(
        "INSERT INTO teams(id, key, name, description, color, seq, triage, estimates, "
        "cycle_weeks, cycle_cooldown, default_status, created_at) VALUES(?,?,?,?,?,0,?,?,?,?,?,?)",
        (
            team_id,
            key,
            name,
            _text(fields.get("description"), "description", _MAX_BODY),
            _text(fields.get("color") or "gold", "color", 20),
            1 if fields.get("triage") else 0,
            _scale(fields.get("estimates")),
            int(fields.get("cycle_weeks") or 0),
            int(fields.get("cycle_cooldown") or 0),
            _text(fields.get("default_status") or "backlog", "default_status", 40),
            now,
        ),
    )
    _seed_states(conn, team_id)
    return conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()


def _scale(value: Any) -> str:
    scale = str(value or "").strip()
    if scale not in ESTIMATE_SCALES:
        raise TeamError(f"estimates must be one of: {', '.join(k or '(none)' for k in ESTIMATE_SCALES)}")
    return scale


def create_team(name: str, key: str = "", **fields: Any) -> dict[str, Any]:
    """팀 하나를 세운다. 키를 안 주면 이름에서 뽑는다."""
    name = _text(name, "team name", _MAX_NAME, required=True)
    wanted = _text(key, "team key", 8).upper() or key_from_name(name)
    if not _KEY.fullmatch(wanted):
        raise TeamError("team key must be 2-8 characters, starting with a letter (A-Z, 0-9)")
    with writing() as conn:
        if conn.execute("SELECT 1 FROM teams WHERE key = ?", (wanted,)).fetchone():
            raise TeamError(f"team key already in use: {wanted}")
        return _team_row(conn, _insert_team(conn, name, wanted, **fields))


def find_team(conn: sqlite3.Connection, ref: Any) -> sqlite3.Row | None:
    """id 든 키든 이름이든 같은 문으로 받는다 — 사람은 키로 부르고 기계는 id로 부른다."""
    if not isinstance(ref, str):
        return None
    ref = ref.strip()
    if not ref:
        return None
    if _ID.fullmatch(ref):
        found = conn.execute("SELECT * FROM teams WHERE id = ?", (ref,)).fetchone()
        if found:
            return found
    found = conn.execute("SELECT * FROM teams WHERE key = ?", (ref.upper(),)).fetchone()
    if found:
        return found
    return conn.execute("SELECT * FROM teams WHERE name = ? COLLATE NOCASE", (ref,)).fetchone()


def resolve_team(conn: sqlite3.Connection, ref: Any) -> sqlite3.Row:
    row = find_team(conn, ref)
    if row is None:
        raise TeamError(f"team not found: {ref}")
    return row


def get_team(ref: Any) -> dict[str, Any]:
    with reading() as conn:
        return _team_row(conn, resolve_team(conn, ref))


def list_teams(include_archived: bool = False) -> list[dict[str, Any]]:
    # 읽기는 자리를 만들지 않는다 — 창을 열어 본 것만으로 빈 워크스페이스가 생기면,
    # 안 쓴 기능이 사용자의 홈에 파일을 남기는 것이다.
    if not exists():
        return []
    with reading() as conn:
        clause = "" if include_archived else " WHERE archived_at IS NULL"
        rows = conn.execute(f"SELECT * FROM teams{clause} ORDER BY key").fetchall()
        return [_team_row(conn, row) for row in rows]


_TEAM_MUTABLE = (
    "name",
    "description",
    "color",
    "triage",
    "estimates",
    "cycle_weeks",
    "cycle_cooldown",
    "default_status",
)


def update_team(ref: Any, changes: dict[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - set(_TEAM_MUTABLE)
    if unknown:
        raise TeamError(f"unknown team field: {', '.join(sorted(unknown))}")
    with writing() as conn:
        row = resolve_team(conn, ref)
        sets, values = [], []
        for field, value in changes.items():
            if field == "triage":
                value = 1 if value else 0
            elif field == "estimates":
                value = _scale(value)
            elif field in ("cycle_weeks", "cycle_cooldown"):
                value = max(0, min(12, int(value or 0)))
            elif field == "name":
                value = _text(value, "team name", _MAX_NAME, required=True)
            elif field == "description":
                value = _text(value, "description", _MAX_BODY)
            else:
                value = _text(value, field, 40)
            sets.append(f"{field} = ?")
            values.append(value)
        if sets:
            conn.execute(f"UPDATE teams SET {', '.join(sets)} WHERE id = ?", (*values, row["id"]))
        return _team_row(conn, conn.execute("SELECT * FROM teams WHERE id = ?", (row["id"],)).fetchone())


def archive_team(ref: Any, archived: bool = True) -> dict[str, Any]:
    """보관은 삭제가 아니다 — 번호가 가리키던 티켓은 그대로 있고 목록에서만 빠진다."""
    with writing() as conn:
        row = resolve_team(conn, ref)
        conn.execute("UPDATE teams SET archived_at = ? WHERE id = ?", (_now() if archived else None, row["id"]))
        return _team_row(conn, conn.execute("SELECT * FROM teams WHERE id = ?", (row["id"],)).fetchone())


# ── 폴더 ↔ 팀 ──────────────────────────────────────────────────────────────────


def team_for_root(conn: sqlite3.Connection, root: str | None) -> sqlite3.Row | None:
    """이 폴더에 매인 팀 — **자리를 만들지 않는다.** 읽기 경로가 쓰는 문이다.

    저장소 안의 결속 파일을 먼저 본다: 폴더를 옮겼으면 워크스페이스의 표는 옛 경로를 들고
    있지만 파일은 따라왔기 때문이다. 파일이 가리키는 팀이 살아 있으면 표도 그때 고친다."""
    if not root:
        return None
    target = os.path.abspath(root)
    bound = read_bind(target).get("team")
    if bound:
        found = conn.execute("SELECT * FROM teams WHERE id = ?", (bound,)).fetchone()
        if found:
            return found
    return conn.execute(
        "SELECT teams.* FROM teams JOIN team_roots ON team_roots.team_id = teams.id WHERE team_roots.root = ?",
        (target,),
    ).fetchone()


def _bind_root(conn: sqlite3.Connection, team_id: str, key: str, root: str) -> None:
    target = os.path.abspath(root)
    conn.execute(
        "INSERT INTO team_roots(root, team_id, created_at) VALUES(?,?,?) "
        "ON CONFLICT(root) DO UPDATE SET team_id = excluded.team_id",
        (target, team_id, _now()),
    )
    write_bind(target, team_id, key)


def ensure_team(conn: sqlite3.Connection, root: str | None, *, create: bool = True) -> sqlite3.Row | None:
    """이 손이 쓸 팀 — 결속된 폴더면 그 팀, 아니면 워크스페이스의 **기본 팀**.

    여태는 결속이 없는 폴더에서 적으면 폴더 이름으로 팀을 하나 세웠다. 그게 "폴더 = 프로젝트"를
    조용히 되살리고 있었다: 저장소 다섯 곳을 오가며 일한 사람은 팀 다섯 개와 번호 다섯 갈래를
    갖게 되고, 그중 어느 것도 고른 적이 없다. 팀은 사람이 짓는 것이다 — `create_team`과
    `bind_root`가 그 문이고, 여기서는 만들지 않는다.

    (폴더를 팀으로 갖고 싶은 사람은 `asgard ticket team add <이름> --bind`로 그렇게 한다.)"""
    found = team_for_root(conn, root)
    if found is not None:
        return found
    return default_team(conn, create=create)


_DEFAULT_TEAM_NAME = "일감"


def default_team(conn: sqlite3.Connection, *, create: bool = True) -> sqlite3.Row | None:
    """폴더 없이 적는 일감이 서는 자리. meta에 굳어 있어 이름을 바꿔도 안 흔들린다."""
    stored = meta_get(conn, "default_team")
    if stored:
        found = conn.execute("SELECT * FROM teams WHERE id = ?", (stored,)).fetchone()
        if found:
            return found
    found = conn.execute("SELECT * FROM teams WHERE archived_at IS NULL ORDER BY created_at LIMIT 1").fetchone()
    if found:
        meta_set(conn, "default_team", str(found["id"]))
        return found
    if not create:
        return None
    row = _insert_team(conn, _DEFAULT_TEAM_NAME, _free_key(conn, _FALLBACK_KEY))
    meta_set(conn, "default_team", str(row["id"]))
    return row


def bind_root(team_ref: Any, root: str) -> dict[str, Any]:
    """폴더를 팀에 붙인다 — 이미 다른 팀에 매여 있어도 옮겨 붙는다(사용자가 부른 것이다)."""
    with writing() as conn:
        row = resolve_team(conn, team_ref)
        _bind_root(conn, str(row["id"]), str(row["key"]), root)
        return _team_row(conn, row)


def unbind_root(root: str) -> bool:
    with writing() as conn:
        cur = conn.execute("DELETE FROM team_roots WHERE root = ?", (os.path.abspath(root),))
        return cur.rowcount > 0


# ── 번호 ───────────────────────────────────────────────────────────────────────


def next_key(conn: sqlite3.Connection, team: sqlite3.Row) -> tuple[str, int]:
    """다음 번호. 팀의 카운터와 실제 최대값 중 큰 쪽에서 나아간다 — 어느 한쪽이 밀려도 재발급은 없다."""
    stored = int(team["seq"] or 0)
    row = conn.execute("SELECT MAX(seq) AS top FROM tickets WHERE team_id = ?", (team["id"],)).fetchone()
    top = int(row["top"]) if row and row["top"] is not None else 0
    seq = max(stored, top) + 1
    conn.execute("UPDATE teams SET seq = ? WHERE id = ?", (seq, team["id"]))
    return f"{team['key']}-{seq}", seq


# ── 워크플로 상태 ──────────────────────────────────────────────────────────────


def _state_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "slug": str(row["slug"]),
        "name": str(row["name"]),
        "type": str(row["type"]),
        "color": str(row["color"] or "slate"),
        "position": float(row["position"] or 0),
    }


def states_of(conn: sqlite3.Connection, team_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM states WHERE team_id = ? ORDER BY position, created_at", (team_id,)).fetchall()
    return [_state_row(row) for row in rows]


def list_states(team_ref: Any) -> list[dict[str, Any]]:
    if not exists():
        return []
    with reading() as conn:
        return states_of(conn, str(resolve_team(conn, team_ref)["id"]))


def status_type(conn: sqlite3.Connection, team_id: str | None, slug: str) -> str:
    """이 상태가 어느 범주인가. 팀이 지은 이름도, 기본 이름도 같은 문으로 답한다."""
    from .vocab import STATUS_TYPE

    if team_id:
        row = conn.execute("SELECT type FROM states WHERE team_id = ? AND slug = ?", (team_id, slug)).fetchone()
        if row:
            return str(row["type"])
    return STATUS_TYPE.get(slug, "backlog")


def create_state(team_ref: Any, name: str, kind: str, color: str = "slate", slug: str = "") -> dict[str, Any]:
    if kind not in STATUS_TYPES:
        raise TeamError(f"state type must be one of: {', '.join(STATUS_TYPES)}")
    name = _text(name, "state name", _MAX_NAME, required=True)
    wanted = _text(slug, "state slug", 40) or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not wanted:
        raise TeamError("state slug is required")
    with writing() as conn:
        team = resolve_team(conn, team_ref)
        if conn.execute("SELECT 1 FROM states WHERE team_id = ? AND slug = ?", (team["id"], wanted)).fetchone():
            raise TeamError(f"state already exists: {wanted}")
        top = conn.execute("SELECT MAX(position) AS p FROM states WHERE team_id = ?", (team["id"],)).fetchone()
        position = float(top["p"] or 0) + 1
        state_id = uuid4().hex
        conn.execute(
            "INSERT INTO states(id, team_id, slug, name, type, color, position, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (state_id, team["id"], wanted, name, kind, _text(color, "color", 20) or "slate", position, _now()),
        )
        return _state_row(conn.execute("SELECT * FROM states WHERE id = ?", (state_id,)).fetchone())


def update_state(team_ref: Any, slug: str, changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "type", "color", "position"}
    unknown = set(changes) - allowed
    if unknown:
        raise TeamError(f"unknown state field: {', '.join(sorted(unknown))}")
    with writing() as conn:
        team = resolve_team(conn, team_ref)
        row = conn.execute("SELECT * FROM states WHERE team_id = ? AND slug = ?", (team["id"], slug)).fetchone()
        if row is None:
            raise TeamError(f"state not found: {slug}")
        sets, values = [], []
        for field, value in changes.items():
            if field == "type" and value not in STATUS_TYPES:
                raise TeamError(f"state type must be one of: {', '.join(STATUS_TYPES)}")
            if field == "position":
                value = float(value)
            elif field != "type":
                value = _text(value, field, _MAX_NAME, required=field == "name")
            sets.append(f"{field} = ?")
            values.append(value)
        conn.execute(f"UPDATE states SET {', '.join(sets)} WHERE id = ?", (*values, row["id"]))
        return _state_row(conn.execute("SELECT * FROM states WHERE id = ?", (row["id"],)).fetchone())


def delete_state(team_ref: Any, slug: str) -> bool:
    """상태를 지운다 — 다만 그 상태를 쓰는 티켓이 있으면 막는다.

    조용히 지우면 그 티켓들은 이름 없는 칸에 남는다: 보드 어디에도 안 뜨는데 열린 채로
    건수에는 잡히는, 가장 나쁜 종류의 유령이 된다."""
    with writing() as conn:
        team = resolve_team(conn, team_ref)
        row = conn.execute("SELECT * FROM states WHERE team_id = ? AND slug = ?", (team["id"], slug)).fetchone()
        if row is None:
            return False
        used = conn.execute(
            "SELECT COUNT(*) AS n FROM tickets WHERE team_id = ? AND status = ?", (team["id"], slug)
        ).fetchone()
        if int(used["n"] or 0):
            raise TeamError(f"{used['n']} tickets still use '{slug}' — move them first")
        if conn.execute("SELECT COUNT(*) AS n FROM states WHERE team_id = ?", (team["id"],)).fetchone()["n"] <= 1:
            raise TeamError("a team needs at least one workflow state")
        conn.execute("DELETE FROM states WHERE id = ?", (row["id"],))
        return True


# ── 사이클 ─────────────────────────────────────────────────────────────────────

_WEEK = 7 * 24 * 3600


def _cycle_row(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    counts = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status IN ('done','canceled') THEN 1 ELSE 0 END) AS closed "
        "FROM tickets WHERE cycle_id = ? AND archived_at IS NULL",
        (row["id"],),
    ).fetchone()
    total = int(counts["total"] or 0)
    closed = int(counts["closed"] or 0)
    return {
        "id": str(row["id"]),
        "team_id": str(row["team_id"] or ""),
        "number": int(row["number"]),
        "name": str(row["name"] or ""),
        "starts_at": row["starts_at"],
        "ends_at": row["ends_at"],
        "closed_at": row["closed_at"],
        "created_at": float(row["created_at"]),
        "total": total,
        "done": closed,
        "progress": round(closed / total, 3) if total else 0.0,
        "active": row["closed_at"] is None,
    }


def create_cycle(team_ref: Any, name: str = "", starts_at: Any = None, ends_at: Any = None) -> dict[str, Any]:
    """다음 사이클을 연다. 기간을 안 주면 팀이 정한 주 수만큼 오늘부터 잡는다."""
    with writing() as conn:
        team = resolve_team(conn, team_ref)
        row = conn.execute("SELECT MAX(number) AS top FROM cycles WHERE team_id = ?", (team["id"],)).fetchone()
        number = int(row["top"] or 0) + 1
        now = _now()
        weeks = int(team["cycle_weeks"] or 0) or 2
        start = float(starts_at) if starts_at else now
        end = float(ends_at) if ends_at else start + weeks * _WEEK
        if end <= start:
            raise TeamError("a cycle must end after it starts")
        cycle_id = uuid4().hex
        conn.execute(
            "INSERT INTO cycles(id, team_id, number, name, starts_at, ends_at, created_at) VALUES(?,?,?,?,?,?,?)",
            (cycle_id, team["id"], number, _text(name, "cycle name", _MAX_NAME), start, end, now),
        )
        return _cycle_row(conn, conn.execute("SELECT * FROM cycles WHERE id = ?", (cycle_id,)).fetchone())


def find_cycle(conn: sqlite3.Connection, team_id: str | None, ref: Any) -> sqlite3.Row | None:
    if ref in (None, ""):
        return None
    text = str(ref).strip()
    if _ID.fullmatch(text):
        return conn.execute("SELECT * FROM cycles WHERE id = ?", (text,)).fetchone()
    if text.isdigit() and team_id:
        return conn.execute("SELECT * FROM cycles WHERE team_id = ? AND number = ?", (team_id, int(text))).fetchone()
    if team_id:
        return conn.execute(
            "SELECT * FROM cycles WHERE team_id = ? AND name = ? COLLATE NOCASE", (team_id, text)
        ).fetchone()
    return None


def cycles_for(team_ref: Any) -> list[dict[str, Any]]:
    if not exists():
        return []
    with reading() as conn:
        team = resolve_team(conn, team_ref)
        rows = conn.execute("SELECT * FROM cycles WHERE team_id = ? ORDER BY number DESC", (team["id"],)).fetchall()
        return [_cycle_row(conn, row) for row in rows]


def active_cycle(team_ref: Any) -> dict[str, Any] | None:
    """지금 도는 사이클 — 안 닫혔고 오늘이 기간 안에 든 것. 없으면 None."""
    with reading() as conn:
        team = find_team(conn, team_ref) if isinstance(team_ref, str) else None
        if team is None:
            return None
        now = _now()
        row = conn.execute(
            "SELECT * FROM cycles WHERE team_id = ? AND closed_at IS NULL "
            "AND (starts_at IS NULL OR starts_at <= ?) AND (ends_at IS NULL OR ends_at >= ?) "
            "ORDER BY number DESC LIMIT 1",
            (team["id"], now, now),
        ).fetchone()
        return _cycle_row(conn, row) if row else None


def close_cycle(team_ref: Any, ref: Any, roll: bool = True) -> dict[str, Any]:
    """사이클을 닫는다. 안 끝난 티켓은 기본으로 **다음 사이클로 넘긴다**.

    Linear와 같은 계약이다: 안 끝난 일을 닫힌 사이클에 남겨 두면 그 일은 어느 보드에도 안
    뜨면서 열린 채로 남는다 — 사이클이 일을 삼키는 셈이다."""
    with writing() as conn:
        team = resolve_team(conn, team_ref)
        row = find_cycle(conn, str(team["id"]), ref)
        if row is None:
            raise TeamError(f"cycle not found: {ref}")
        conn.execute("UPDATE cycles SET closed_at = ? WHERE id = ?", (_now(), row["id"]))
        moved = 0
        if roll:
            nxt = conn.execute(
                "SELECT * FROM cycles WHERE team_id = ? AND closed_at IS NULL AND number > ? ORDER BY number LIMIT 1",
                (team["id"], row["number"]),
            ).fetchone()
            target = nxt["id"] if nxt else None
            cur = conn.execute(
                "UPDATE tickets SET cycle_id = ?, updated_at = ? "
                "WHERE cycle_id = ? AND status NOT IN ('done','canceled')",
                (target, _now(), row["id"]),
            )
            moved = cur.rowcount
        closed = _cycle_row(conn, conn.execute("SELECT * FROM cycles WHERE id = ?", (row["id"],)).fetchone())
        closed["rolled"] = moved
        return closed


def roll_cycle(team_ref: Any) -> dict[str, Any]:
    """이번 사이클을 닫고 다음 것을 열어 남은 일을 넘긴다 — 한 번에."""
    current = active_cycle(team_ref)
    nxt = create_cycle(team_ref)
    if current:
        closed = close_cycle(team_ref, current["number"], roll=True)
        return {"closed": closed, "opened": nxt, "rolled": closed.get("rolled", 0)}
    return {"closed": None, "opened": nxt, "rolled": 0}
