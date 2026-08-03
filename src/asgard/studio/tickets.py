"""티켓 — 스튜디오가 스스로 발급하고 관리하는 일감 한 건.

형상은 Linear를 따른다. 그 도구가 옳아서가 아니라, **일을 세는 어휘가 이미 그 모양으로
합의돼 있어서**다: 상태 이름은 팀이 짓되 범주는 다섯으로 접히고, 우선순위는 '없음'이 맨
뒤로 가라앉으며, 하위 티켓과 차단 관계는 별개의 축이다([[vocab]]).

  워크스페이스 ── 팀 ── **티켓**        번호의 주인은 팀이다 (`NOR-12`)
        ├─ 프로젝트 ── 마일스톤         팀을 가로지르는 축 — 티켓은 프로젝트 하나에만
        └─ 이니셔티브

**번호는 한 번만 발급된다.** `NOR-12`는 그 팀에서 영원히 그 티켓이다 — 지워도 번호는
재사용하지 않는다. 사람이 대화에서 부르는 이름이라, 같은 이름이 두 번 나오면 대화가 깨진다.

**상태 변경은 시각을 남긴다.** 진행으로 옮기면 `started_at`, 완료면 `completed_at`. 되돌리면
지운다 — 완료 표시가 남아 있는 '진행 중' 티켓은 리드타임 통계를 조용히 거짓말하게 만든다.

**보이는 범위는 폴더가 정한다, 사는 곳은 워크스페이스다.** 저장소 안에서 부르면 그 저장소에
매인 팀의 일감을 본다(여태와 같은 손맛). 아직 안 매인 자리거나 `team="*"` 면 워크스페이스
전체를 본다 — 폴더를 안 열고도 "지금 뭘 해야 하지"에 답할 수 있어야 하기 때문이다.

정본은 `<에이전트 홈>/studio/workspace.db` ([[db]]). 이 모듈은 그 위의 어휘와 규칙만 진다.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from typing import Any
from uuid import uuid4

from .. import errors
from .db import StoreError, exists, reading, writing
from .teams import ensure_team, find_cycle, find_team, next_key, states_of, team_for_root
from .vocab import (
    LABEL_COLORS,
    LINK_KINDS,
    OPEN_STATUSES,
    OPEN_TYPES,
    PRIORITIES,
    PRIORITY_LABEL,
    SOURCES,
    STATUS_LABEL,
    STATUS_TYPE,
    STATUS_TYPES,
    STATUSES,
)
from .vocab import (
    PRIORITY_RANK as _PRIORITY_RANK,
)

__all__ = [
    "StoreError",
    "STATUSES",
    "STATUS_LABEL",
    "STATUS_TYPE",
    "OPEN_STATUSES",
    "PRIORITIES",
    "PRIORITY_LABEL",
    "SOURCES",
    "LINK_KINDS",
    "TicketError",
    "create_ticket",
    "update_ticket",
    "move_ticket",
    "delete_ticket",
    "get_ticket",
    "list_tickets",
    "add_comment",
    "link_tickets",
    "unlink_tickets",
    "EVIDENCE_VERDICTS",
    "attach_evidence",
    "list_evidence",
    "detach_evidence",
    "list_labels",
    "create_label",
    "delete_label",
    "list_cycles",
    "create_cycle",
    "close_cycle",
    "active_cycle",
    "tickets_for_task",
    "triage_queue",
    "triage_accept",
    "triage_decline",
    "triage_snooze",
    "summary",
    "board",
    "prefix",
    "sort_key",
]

_MAX_TITLE = 300
_MAX_BODY = 20_000
_MAX_COMMENT = 10_000
_MAX_NAME = 60
_MAX_TICKETS = 50_000
_MAX_EVIDENCE_NOTE = 500
_ID = re.compile(r"^[0-9a-f]{32}$")
_KEY = re.compile(r"^([A-Z][A-Z0-9]{1,7})-([0-9]{1,7})$")
_LIST_LIMIT = 500

# 부하 실행 하나의 판정. 세 갈래인 것이 계약이다 — 임계값이 없던 실행은 통과가 아니라 미판정이다.
EVIDENCE_VERDICTS = ("pass", "fail", "unjudged")
# 실행 표식의 모양. 이 값은 사람이 손으로 치고 `runs/<표식>/report.json` 으로 조립되므로,
# 경로 성분 하나로 안 떨어지는 것은 받지 않는다. 첫 글자를 영숫자로 못 정하면 `..` 과
# 숨은 이름이 그대로 통과하고, 구분자를 뺀 것이 디렉터리 밖을 가리키는 조립을 막는다.
_STAMP = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,119}$")

_SILENT_FIELDS = frozenset({"started_at", "completed_at", "canceled_at", "position"})
_MUTABLE = (
    "title",
    "body",
    "status",
    "priority",
    "estimate",
    "assignee",
    "reporter",
    "parent",
    "cycle",
    "team",
    "project",
    "milestone",
    "triage",
    "due_at",
    "plan_id",
    "plan_record",
    "task_id",
    "labels",
)


class TicketError(errors.InvalidInput, ValueError):
    """티켓 어휘를 어겼다 — 호출자가 고칠 수 있는 잘못이다.

    `ValueError`를 함께 상속하는 것은 하위 호환이다: 이 예외를 `except ValueError`로 받는
    자리가 아직 남아 있고, 그 자리들을 한꺼번에 고치는 것과 이 계층을 들이는 것은 다른 일이다.
    """

    code = "invalid_ticket"


def _now() -> float:
    return time.time()


def _untouched() -> bool:
    """워크스페이스를 아직 한 번도 안 만졌는가.

    **읽기는 자리를 만들지 않는다.** 처음 쓰는 것은 언제나 쓰기(create_ticket)이므로 잃는
    것은 없고, 창을 열어 보기만 한 사람의 홈에 빈 저장소가 생기지 않는다."""
    return not exists()


def _text(value: Any, field: str, limit: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise TicketError(f"{field} must be text")
    value = value.strip()
    if required and not value:
        raise TicketError(f"{field} is required")
    if len(value) > limit:
        raise TicketError(f"{field} must be at most {limit} characters")
    return value


def _status(value: Any, allowed: tuple[str, ...] = STATUSES) -> str:
    if value not in allowed:
        raise TicketError(f"status must be one of: {', '.join(allowed)}")
    return str(value)


def _workspace_states(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """워크스페이스 전체를 볼 때의 칸 — **모든 팀의 상태를 합친다.**

    전체 보기가 이제 기본이라, 여기서 기본 여섯 칸으로 접으면 팀이 지은 '배포 대기'에 선
    티켓은 어느 칸에도 못 들어가고 보드에서 **사라진다**(셈에서도 빠진다). 범주 순서로 묶고
    같은 슬러그는 한 번만 세운다 — 두 팀이 같은 이름을 쓰는 것이 정상이기 때문이다."""
    order = {kind: index for index, kind in enumerate(STATUS_TYPES)}
    rows = conn.execute(
        "SELECT states.* FROM states JOIN teams ON teams.id = states.team_id "
        "WHERE teams.archived_at IS NULL ORDER BY states.position, states.created_at"
    ).fetchall()
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        slug = str(row["slug"])
        if slug not in found:
            found[slug] = {
                "slug": slug,
                "name": str(row["name"]),
                "type": str(row["type"]),
                "color": str(row["color"] or "slate"),
            }
    for slug in STATUSES:  # 아직 팀이 쓰지 않는 기본 칸도 보드에는 서 있어야 한다
        found.setdefault(slug, {"slug": slug, "name": STATUS_LABEL[slug], "type": STATUS_TYPE[slug], "color": "slate"})
    return sorted(found.values(), key=lambda state: order.get(state["type"], len(order)))


def _team_statuses(conn: sqlite3.Connection, team_id: str | None) -> tuple[str, ...]:
    """이 팀이 쓰는 상태 슬러그들. 팀이 없으면 워크스페이스 전체가 쓰는 것 전부."""
    if not team_id:
        return tuple(state["slug"] for state in _workspace_states(conn))
    found = tuple(state["slug"] for state in states_of(conn, team_id))
    return found or STATUSES


def _slugs_of_type(conn: sqlite3.Connection, team_id: str | None, kinds: frozenset[str]) -> tuple[str, ...]:
    """이 범주에 드는 상태 슬러그들 — **셈은 범주가 한다**.

    기본 여섯 칸의 이름표로 세면 팀이 만든 '배포 대기'(범주 started)가 어느 셈에도 안 잡힌다:
    보드에는 카드가 있는데 '진행 0'이라고 말하는 계기판이 된다. 이름은 팀이 짓고, 열림·진행을
    세는 것은 언제나 다섯 범주다.

    팀을 안 고른 자리(워크스페이스 전체)에서도 같다 — 그때는 **모든 팀의 이름**을 합쳐 센다."""
    if team_id:
        found = tuple(state["slug"] for state in states_of(conn, team_id) if state["type"] in kinds)
        if found:
            return found
        return tuple(slug for slug in STATUSES if STATUS_TYPE[slug] in kinds)
    return tuple(state["slug"] for state in _workspace_states(conn) if state["type"] in kinds)


def _type_of(conn: sqlite3.Connection, team_id: str | None, slug: str) -> str:
    from .teams import status_type

    return status_type(conn, team_id, slug)


def _priority(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in PRIORITIES:
        raise TicketError("priority must be 0 (none), 1 (urgent), 2 (high), 3 (medium), or 4 (low)")
    return int(value)


def _estimate(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 999:
        raise TicketError("estimate must be an integer between 0 and 999")
    return int(value)


def _moment(value: Any, field: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TicketError(f"{field} must be a unix timestamp")
    return float(value)


# ── 범위 ───────────────────────────────────────────────────────────────────────

_EVERY = frozenset({"*", "all", "workspace"})
# 이 폴더에 매인 팀만 보겠다는 손. 예전의 **기본값**이 이제 여기로 내려왔다.
_HERE = frozenset({".", "here", "folder", "root"})


def _read_scope(conn: sqlite3.Connection, root: str | None, team: Any = None) -> sqlite3.Row | None:
    """읽을 때 어느 팀을 볼 것인가. None 이면 워크스페이스 전체다 — **그게 기본이다.**

    여태는 아무것도 안 주면 이 폴더에 매인 팀을 봤다. 그래서 같은 `asgard ticket list`가 선
    자리에 따라 다른 답을 냈고, 저장소 밖에서 켠 창은 자기 일감을 못 찾았다. 일감은 폴더의
    것이 아니라 사람의 것이다 — 폴더는 이제 **거르는 값**이지 경계가 아니다.

    규칙 셋: 명시한 팀이 우선한다 · `.`은 이 폴더에 매인 팀 · 나머지는 전부 워크스페이스 전체."""
    if not team:
        return None
    if isinstance(team, str):
        token = team.strip().lower()
        if token in _EVERY:
            return None
        if token in _HERE:
            return team_for_root(conn, root)
    row = find_team(conn, team)
    if row is None:
        raise TicketError(f"team not found: {team}")
    return row


def _write_team(conn: sqlite3.Connection, root: str | None, team: Any = None) -> sqlite3.Row:
    """적을 때 어느 팀에 적을 것인가 — 없으면 만든다(쓰기 경로라 자리를 만들어도 된다).

    폴더가 팀을 **암묵으로** 만들지는 않는다(`ensure_team`을 보라). 결속을 걸어 둔 폴더에서는
    그 팀에 적히고, 아니면 워크스페이스의 기본 팀에 적힌다."""
    if isinstance(team, str) and team.strip().lower() in _EVERY | _HERE:
        team = None
    if team:
        row = find_team(conn, team)
        if row is None:
            raise TicketError(f"team not found: {team}")
        return row
    row = ensure_team(conn, root, create=True)
    if row is None:
        raise TicketError("no team available to hold this ticket")
    return row


def prefix(root: str) -> str:
    """지금 새 티켓이 받을 번호의 앞자리 — 결속된 폴더면 그 팀, 아니면 워크스페이스 기본 팀."""
    from .teams import default_team, key_from_name

    if _untouched():
        return key_from_name("")
    with reading() as conn:
        row = team_for_root(conn, root) or default_team(conn, create=False)
        return str(row["key"]) if row is not None else key_from_name("")


# ── 참조 해석 ──────────────────────────────────────────────────────────────────


def _resolve(
    conn: sqlite3.Connection, ref: Any, field: str = "ticket", scope: sqlite3.Row | None = None
) -> sqlite3.Row:
    row = _find(conn, ref, scope)
    if row is None:
        raise TicketError(f"{field} not found: {ref}")
    return row


def _find(conn: sqlite3.Connection, ref: Any, scope: sqlite3.Row | None = None) -> sqlite3.Row | None:
    """id 든 `NOR-12` 든 같은 문으로 받는다 — 사람은 번호로 부르고 기계는 id로 부른다."""
    if not isinstance(ref, str):
        return None
    ref = ref.strip()
    if not ref:
        return None
    if _ID.fullmatch(ref):
        return conn.execute("SELECT * FROM tickets WHERE id = ?", (ref,)).fetchone()
    upper = ref.upper()
    if _KEY.fullmatch(upper):
        return conn.execute("SELECT * FROM tickets WHERE key = ?", (upper,)).fetchone()
    # 접두어 없이 번호만 부르는 손을 받아 준다 — 대화에서는 "12번"이라고 말한다.
    # 번호는 팀 안에서만 유일하므로, 어느 팀을 보고 있는지가 답을 가른다.
    if ref.isdigit():
        if scope is not None:
            return conn.execute(
                "SELECT * FROM tickets WHERE team_id = ? AND seq = ?", (scope["id"], int(ref))
            ).fetchone()
        rows = conn.execute("SELECT * FROM tickets WHERE seq = ? LIMIT 2", (int(ref),)).fetchall()
        if len(rows) == 1:
            return rows[0]
        if len(rows) > 1:
            raise TicketError(f"'{ref}' matches tickets in more than one team — use the full key (e.g. NOR-{ref})")
    return None


def _log(conn: sqlite3.Connection, ticket_id: str, actor: str, field: str, before: Any, after: Any) -> None:
    conn.execute(
        "INSERT INTO activity(ticket_id, actor, field, before, after, created_at) VALUES(?,?,?,?,?,?)",
        (
            ticket_id,
            actor or "",
            field,
            "" if before is None else str(before),
            "" if after is None else str(after),
            _now(),
        ),
    )


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


# ── 주기(사이클) — 정본은 teams.py, 여기는 폴더 기준의 손잡이 ────────────────────


def create_cycle(
    root: str, name: str = "", starts_at: Any = None, ends_at: Any = None, team: Any = None
) -> dict[str, Any]:
    from . import teams as T

    with writing() as conn:
        team_id = str(_write_team(conn, root, team)["id"])
    return T.create_cycle(team_id, name=name, starts_at=starts_at, ends_at=ends_at)


def close_cycle(root: str, ref: Any, roll: bool = True, team: Any = None) -> dict[str, Any]:
    """사이클은 팀의 것이라 **하나를 골라야** 닫을 수 있다.

    읽기의 기본은 워크스페이스 전체지만 여기서 그 규칙을 쓰면 늘 "팀이 없다"가 된다. 그래서
    자리를 고르는 방식은 `create_cycle`과 같다 — 결속된 폴더면 그 팀, 아니면 기본 팀. 다만
    **만들지는 않는다**: 없는 팀의 사이클을 닫는다는 말은 성립하지 않는다."""
    from . import teams as T
    from .teams import ensure_team

    with reading() as conn:
        row = find_team(conn, team) if team else ensure_team(conn, root, create=False)
        if row is None:
            raise TicketError(f"team not found: {team}" if team else "no team holds a cycle to close")
        team_id = str(row["id"])
    return T.close_cycle(team_id, ref, roll=roll)


def list_cycles(root: str | None = None, team: Any = None) -> list[dict[str, Any]]:
    if _untouched():
        return []
    from .teams import _cycle_row  # noqa: PLC0415  (같은 패키지의 표현 재사용)

    with reading() as conn:
        scope = _read_scope(conn, root, team)
        if scope is None:
            rows = conn.execute("SELECT * FROM cycles ORDER BY number DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cycles WHERE team_id = ? ORDER BY number DESC", (scope["id"],)
            ).fetchall()
        return [_cycle_row(conn, row) for row in rows]


def active_cycle(root: str | None = None, team: Any = None) -> dict[str, Any] | None:
    """지금 도는 주기 — 닫히지 않은 것 중 기간이 오늘을 품은 것, 없으면 가장 최근 것."""
    cycles = [c for c in list_cycles(root, team) if not c["closed_at"]]
    now = _now()
    for cycle in cycles:
        start, end = cycle["starts_at"], cycle["ends_at"]
        if start is not None and end is not None and start <= now <= end:
            return cycle
    return cycles[0] if cycles else None


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
    from .projects import ProjectError, _resolve_milestone, resolve_project

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


# ── 부하 근거 — 이 티켓의 성능 주장이 어느 실행에서 나왔는가 ─────────────────────
#
# **판정이 아니라 참조다.** 모든 티켓이 부하와 관계있지는 않으므로 여기에 게이트를 두지 않는다.
# 무관한 티켓을 부하 시험으로 막으면 그 게이트는 우회되고, 우회된 게이트는 아무것도 재지 않는다.
# 매다는 것도 떼는 것도 티켓의 상태를 안 건드린다.
#
# 미판정 실행(`verdict="unjudged"`)도 받는다. 거절하는 쪽이 더 엄격해 보이지만, 거절은 매달기를
# 막을 뿐이라 그 사람이 하는 일은 아무것도 안 매다는 것이고 그러면 성능 주장은 다시 사람의
# 기억으로 돌아간다 — 이 계층이 닫으려던 구멍 그대로다. 저장소가 최근에 고친 자리도 미판정을
# **금지**한 것이 아니라 통과와 **다르게 읽히게** 한 것이다(`k6.Report.judged`, 종료 코드 3).
# 같은 형상을 따른다: 기록은 남기고, 판정 칸이 그것을 통과로 위장하지 못하게 한다.


def _stamp(value: Any) -> str:
    stamp = str(value or "").strip()
    if not _STAMP.fullmatch(stamp):
        raise TicketError(f"'{stamp}' is not a run stamp — expected one path segment like 20260803T151258-http-smoke")
    return stamp


def _judged(payload: dict) -> bool:
    """이 실행에 판정할 것이 있었는가.

    `judged` 칸이 있으면 그것을 읽고, 없으면 임계값 목록으로 되짚는다. 그 칸이 생기기 전에
    적힌 기록이 아직 남아 있고, 없는 칸을 참으로 읽으면 판정 안 받은 실행이 통과로 굳는다.
    되짚는 방법은 정본과 같은 정의다 — `k6.Report.judged` 가 곧 `bool(thresholds)` 다."""
    if "judged" in payload:
        return bool(payload["judged"])
    return bool(payload.get("thresholds"))


def _verdict(payload: dict) -> str:
    if not _judged(payload):
        return "unjudged"
    return "pass" if bool(payload.get("ok")) else "fail"


def _run_payload(root: str, stamp: str = "", scenario: str = "") -> tuple[str, dict]:
    """기록된 실행 하나를 찾아 (표식, 요약 본문)으로 돌려준다. 없으면 거절한다.

    `k6` 는 같은 계층의 형제라 모듈 최상단에서 부르지 않는다(계층 규칙은 임포트 시점에 도는
    것만 본다). 경로를 직접 조립하지 않고 그쪽에 묻는 이유는 `runs/` 의 배치가 그 모듈의
    계약이어서다 — 여기에 사본을 두면 한쪽만 옮겨졌을 때 이 표가 없는 파일을 가리킨다."""
    from ..k6 import find_recorded_run

    if stamp:
        stamp = _stamp(stamp)
    record = find_recorded_run(root or ".", stamp, scenario=scenario)
    if record is None:
        if stamp:
            raise TicketError(f"no recorded load run for stamp {stamp} — run `asgard k6 run` first")
        where = f" for scenario {scenario}" if scenario else ""
        raise TicketError(f"there is no recorded load run{where} in this project yet — run `asgard k6 run` first")
    return _stamp(record.stamp), record.payload


def _evidence_root(root: str, filed: str) -> str:
    """어느 폴더의 기록을 볼 것인가 — 부르는 자리가 먼저고, 거기 기록이 하나도 없을 때만 티켓의 자리다.

    보드는 폴더에 안 매이지만 `runs/` 는 프로젝트 안에 있다. 창은 개인 작업 공간에서 열려서
    그 자리에만 물으면 창으로 매다는 길이 영영 "기록이 없다"로 끝난다.

    그렇다고 티켓의 자리를 먼저 보면 안 된다: 프로젝트 A 에서 방금 잰 사람이 B 에 적힌 티켓에
    매달면, **다른 실행**이 조용히 근거로 붙는다. 그건 이 계층이 막으려는 것보다 나쁘다 — 근거가
    없는 것은 화면에 보이지만 틀린 근거는 안 보인다. 그래서 부르는 자리에 기록이 하나도 없어
    헷갈릴 것이 없을 때만 물러난다."""
    from ..k6 import recorded_runs

    if not filed or not os.path.isdir(filed) or recorded_runs(root or "."):
        return root
    return filed


def attach_evidence(
    root: str, ref: Any, stamp: str = "", *, scenario: str = "", note: str = "", actor: str = ""
) -> dict[str, Any]:
    """부하 실행 하나를 티켓에 매단다. 표식을 안 주면 이 프로젝트의 가장 최근 기록이다.

    수치를 스냅샷으로 함께 적는다 — 원본(`.asgard/k6/runs/`)은 gitignore이고 정리 정책이 없어서,
    가리키는 값만 적어 두면 그 디렉터리가 없어진 뒤에 성능 주장의 근거도 조용히 사라진다.

    같은 실행을 두 번 매달면 행이 늘지 않고 스냅샷이 다시 적힌다: 한 티켓에 같은 실행이 두 번
    붙으면 목록을 읽는 사람이 두 번 쟀다고 읽는다."""
    note = _text(note, "note", _MAX_EVIDENCE_NOTE)
    actor = _text(actor, "actor", _MAX_NAME)
    if _untouched():
        raise TicketError(f"ticket not found: {ref}")
    # 티켓을 먼저 푼다 — 어느 폴더의 기록을 볼지가 그 티켓이 적어 둔 자리에 달려 있고, 없는
    # 티켓에 대고 "기록이 없다"고 답하면 사람은 엉뚱한 것을 고치러 간다.
    with reading() as conn:
        filed = str(_resolve(conn, ref, scope=_read_scope(conn, root))["root"] or "")
    where = _evidence_root(root, filed)
    found, payload = _run_payload(where, stamp, scenario)
    verdict = _verdict(payload)
    latency = payload.get("latency_ms") or {}
    requests = payload.get("requests") or {}
    with writing() as conn:
        row = _resolve(conn, ref, scope=_read_scope(conn, root))
        now = _now()
        conn.execute(
            "INSERT INTO ticket_evidence(id, ticket_id, stamp, scenario, verdict, p95_ms, failed_rate, rate_per_s, "
            "runner, k6_version, target, root, note, actor, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(ticket_id, stamp) DO UPDATE SET "
            "scenario = excluded.scenario, verdict = excluded.verdict, p95_ms = excluded.p95_ms, "
            "failed_rate = excluded.failed_rate, rate_per_s = excluded.rate_per_s, runner = excluded.runner, "
            "k6_version = excluded.k6_version, target = excluded.target, root = excluded.root, "
            # 다시 매달 때 한 줄을 안 주면 먼저 적어 둔 것을 그대로 남긴다 — 수치를 새로 재려고 부른
            # 호출이 "이 실행이 왜 근거인가"까지 조용히 비우면, 그 문장을 다시 적을 사람이 없다.
            "note = CASE WHEN excluded.note = '' THEN ticket_evidence.note ELSE excluded.note END, "
            "actor = excluded.actor, created_at = excluded.created_at",
            (
                uuid4().hex,
                row["id"],
                found,
                str(payload.get("scenario") or ""),
                verdict,
                float(latency.get("p95") or 0.0),
                float(requests.get("failed_rate") or 0.0),
                float(requests.get("rate_per_s") or 0.0),
                str(payload.get("runner") or ""),
                str(payload.get("k6_version") or ""),
                str(payload.get("target") or ""),
                os.path.abspath(where) if where else "",
                note,
                actor,
                now,
            ),
        )
        conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now, row["id"]))
        _log(conn, str(row["id"]), actor, "evidence", "", f"{found} · {verdict}")
        return _evidence_rows(conn, str(row["id"]), found)[0]


def list_evidence(root: str | None = None, ref: Any = None) -> list[dict[str, Any]]:
    """이 티켓에 매달린 부하 근거 전부, 최근에 매단 것부터."""
    if _untouched():
        return []
    with reading() as conn:
        row = _resolve(conn, ref, scope=_read_scope(conn, root))
        return _evidence_rows(conn, str(row["id"]))


def detach_evidence(root: str, ref: Any, stamp: str) -> bool:
    """근거 하나를 뗀다. 원본 기록은 안 건드린다 — 이 표가 소유한 것은 참조뿐이다."""
    with writing() as conn:
        row = _find(conn, ref, _read_scope(conn, root))
        if row is None:
            return False
        cursor = conn.execute(
            "DELETE FROM ticket_evidence WHERE ticket_id = ? AND stamp = ?", (row["id"], _stamp(stamp))
        )
        return cursor.rowcount > 0


def _evidence_rows(conn: sqlite3.Connection, ticket_id: str, stamp: str = "") -> list[dict[str, Any]]:
    """읽기 모델. 스냅샷에 **원본이 아직 있는가**를 함께 붙인다.

    이 한 칸이 표면의 문장을 가른다: 원본이 있으면 스탬프로 전문을 열 수 있고, 없으면 화면이
    "여기 적힌 수치가 남은 전부"라고 말해야 한다. 그 사실을 화면이 스스로 알아내게 두면
    창·CLI·툴이 각각 경로를 조립하고, 그중 하나는 언젠가 다른 자리를 본다."""
    clause = " AND stamp = ?" if stamp else ""
    args: list[Any] = [ticket_id, stamp] if stamp else [ticket_id]
    out: list[dict[str, Any]] = []
    for row in conn.execute(
        f"SELECT * FROM ticket_evidence WHERE ticket_id = ?{clause} ORDER BY created_at DESC", args
    ):
        path = _report_path(str(row["root"] or ""), str(row["stamp"]))
        out.append(
            {
                "stamp": row["stamp"],
                "scenario": row["scenario"],
                "verdict": row["verdict"],
                "judged": row["verdict"] != "unjudged",
                "p95_ms": row["p95_ms"],
                "failed_rate": row["failed_rate"],
                "rate_per_s": row["rate_per_s"],
                "runner": row["runner"],
                "k6_version": row["k6_version"],
                "target": row["target"],
                "root": row["root"],
                "note": row["note"],
                "actor": row["actor"],
                "created_at": row["created_at"],
                "report_path": path,
                "report_exists": bool(path) and os.path.isfile(path),
            }
        )
    return out


def _report_path(root: str, stamp: str) -> str:
    """스냅샷이 나온 원본 요약의 자리. 매단 폴더를 모르면 빈 문자열이다."""
    if not root or not _STAMP.fullmatch(stamp):
        return ""
    from ..k6 import runs_dir

    return str(runs_dir(root) / stamp / "report.json")


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


# ── 읽기 ───────────────────────────────────────────────────────────────────────


def _base(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "key": row["key"],
        "seq": row["seq"],
        "team_id": row["team_id"] or "",
        "title": row["title"],
        "body": row["body"],
        "status": row["status"],
        "status_type": STATUS_TYPE.get(row["status"], "backlog"),
        "priority": row["priority"],
        "estimate": row["estimate"],
        "assignee": row["assignee"],
        "reporter": row["reporter"],
        "source": row["source"],
        "parent_id": row["parent_id"],
        "cycle_id": row["cycle_id"],
        "project_id": row["project_id"] or "",
        "milestone_id": row["milestone_id"] or "",
        "triage": bool(row["triage"]),
        "snoozed_at": row["snoozed_at"],
        "root": row["root"] or "",
        "plan_id": row["plan_id"],
        "plan_record": row["plan_record"],
        "task_id": row["task_id"],
        "position": row["position"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "canceled_at": row["canceled_at"],
        "due_at": row["due_at"],
    }


def _decorate(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """목록에 붙는 부속(팀·프로젝트·라벨·하위·차단·댓글 수)을 **한 묶음씩** 읽는다.

    티켓마다 여섯 번 물어보면 40건짜리 보드가 240개 질의가 된다 — 화면이 목록 길이에 비례해
    느려지는 것은 저장소를 바꾼 이유를 스스로 무르는 일이다."""
    out = [_base(row) for row in rows]
    ids = [item["id"] for item in out]
    if not ids:
        return out
    marks = ",".join("?" * len(ids))
    index = {item["id"]: item for item in out}
    for item in out:
        item.update({"labels": [], "children": 0, "children_done": 0, "comments": 0, "blocked_by": [], "blocks": []})

    teams = {
        str(row["id"]): {"key": str(row["key"]), "name": str(row["name"]), "color": str(row["color"] or "gold")}
        for row in conn.execute("SELECT id, key, name, color FROM teams")
    }
    states = {
        (str(row["team_id"]), str(row["slug"])): {
            "name": str(row["name"]),
            "type": str(row["type"]),
            "color": str(row["color"]),
        }
        for row in conn.execute("SELECT team_id, slug, name, type, color FROM states")
    }
    projects = {
        str(row["id"]): {"name": str(row["name"]), "color": str(row["color"] or "gold"), "icon": str(row["icon"] or "")}
        for row in conn.execute("SELECT id, name, color, icon FROM projects")
    }
    stones = {str(row["id"]): str(row["name"]) for row in conn.execute("SELECT id, name FROM milestones")}
    # 상위 티켓 — 목록의 한 줄도 "이게 무엇의 조각인가"를 말해야 한다. 상세에만 넣으면
    # 하위 티켓이 목록에서 고아처럼 보이고, 사람은 그것만 보고 우선순위를 매긴다.
    parents = {
        str(row["id"]): {"key": str(row["key"]), "title": str(row["title"])}
        for row in conn.execute("SELECT id, key, title FROM tickets WHERE parent_id IS NULL")
    }
    for item in out:
        team = teams.get(item["team_id"])
        item["team"] = {"id": item["team_id"], **team} if team else None
        item["team_key"] = team["key"] if team else ""
        state = states.get((item["team_id"], item["status"]))
        item["status_label"] = state["name"] if state else STATUS_LABEL.get(item["status"], item["status"])
        item["status_type"] = state["type"] if state else STATUS_TYPE.get(item["status"], "backlog")
        item["status_color"] = state["color"] if state else "slate"
        project = projects.get(item["project_id"])
        item["project"] = {"id": item["project_id"], **project} if project else None
        item["milestone"] = (
            {"id": item["milestone_id"], "name": stones.get(item["milestone_id"], "")} if item["milestone_id"] else None
        )
        item["parent"] = parents.get(str(item["parent_id"] or "")) if item["parent_id"] else None

    for row in conn.execute(
        f"SELECT tl.ticket_id, l.name, l.color FROM ticket_labels tl JOIN labels l ON l.id = tl.label_id "
        f"WHERE tl.ticket_id IN ({marks}) ORDER BY l.name COLLATE NOCASE",
        ids,
    ):
        index[row["ticket_id"]]["labels"].append({"name": row["name"], "color": row["color"]})

    for row in conn.execute(
        f"SELECT parent_id, COUNT(*) AS total, SUM(status = 'done') AS done FROM tickets "
        f"WHERE parent_id IN ({marks}) GROUP BY parent_id",
        ids,
    ):
        index[row["parent_id"]]["children"] = row["total"]
        index[row["parent_id"]]["children_done"] = row["done"] or 0

    for row in conn.execute(
        f"SELECT ticket_id, COUNT(*) AS n FROM comments WHERE ticket_id IN ({marks}) GROUP BY ticket_id", ids
    ):
        index[row["ticket_id"]]["comments"] = row["n"]

    open_marks = ",".join("?" * len(OPEN_STATUSES))
    for row in conn.execute(
        f"SELECT k.target_id, t.key, t.status FROM ticket_links k JOIN tickets t ON t.id = k.source_id "
        f"WHERE k.kind = 'blocks' AND k.target_id IN ({marks}) AND t.status IN ({open_marks})",
        [*ids, *OPEN_STATUSES],
    ):
        index[row["target_id"]]["blocked_by"].append(row["key"])

    for row in conn.execute(
        f"SELECT k.source_id, t.key FROM ticket_links k JOIN tickets t ON t.id = k.target_id "
        f"WHERE k.kind = 'blocks' AND k.source_id IN ({marks})",
        ids,
    ):
        index[row["source_id"]]["blocks"].append(row["key"])
    return out


def _detail(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    from .teams import _cycle_row

    ticket = _decorate(conn, [row])[0]
    ticket["children_list"] = _decorate(
        conn,
        conn.execute(
            "SELECT * FROM tickets WHERE parent_id = ? ORDER BY position, created_at", (row["id"],)
        ).fetchall(),
    )
    parent = (
        conn.execute("SELECT key, title, status FROM tickets WHERE id = ?", (row["parent_id"],)).fetchone()
        if row["parent_id"]
        else None
    )
    ticket["parent"] = {"key": parent["key"], "title": parent["title"], "status": parent["status"]} if parent else None
    cycle = (
        conn.execute("SELECT * FROM cycles WHERE id = ?", (row["cycle_id"],)).fetchone() if row["cycle_id"] else None
    )
    ticket["cycle"] = _cycle_row(conn, cycle) if cycle else None
    ticket["comments_list"] = [
        {"id": r["id"], "author": r["author"], "body": r["body"], "created_at": r["created_at"]}
        for r in conn.execute("SELECT * FROM comments WHERE ticket_id = ? ORDER BY created_at", (row["id"],)).fetchall()
    ]
    # 부하 근거는 상세에만 붙인다 — 목록의 한 줄마다 물으면 보드가 티켓 수만큼 질의를 더 낸다.
    ticket["evidence"] = _evidence_rows(conn, str(row["id"]))
    ticket["activity"] = [
        {
            "actor": r["actor"],
            "field": r["field"],
            "before": r["before"],
            "after": r["after"],
            "created_at": r["created_at"],
        }
        for r in conn.execute(
            "SELECT * FROM activity WHERE ticket_id = ? ORDER BY id DESC LIMIT 60", (row["id"],)
        ).fetchall()
    ]
    return ticket


def get_ticket(root: str, ref: Any) -> dict[str, Any]:
    if _untouched():
        raise TicketError(f"ticket not found: {ref}")
    with reading() as conn:
        return _detail(conn, _resolve(conn, ref, scope=_read_scope(conn, root)))


def find_ticket(root: str, ref: Any) -> dict[str, Any] | None:
    if _untouched():
        return None
    with reading() as conn:
        row = _find(conn, ref, _read_scope(conn, root))
        return _detail(conn, row) if row is not None else None


def tickets_for_task(root: str, task_id: str) -> list[dict[str, Any]]:
    """그 스튜디오 작업이 나온 티켓들 — 끝난 작업이 결과를 돌려줄 자리를 찾는 문.

    범위를 안 좁힌다: 작업 id는 워크스페이스에서 유일하고, 작업이 어느 팀의 티켓에서
    나왔는지는 그 티켓이 안다."""
    task_id = str(task_id or "").strip()
    if not task_id or _untouched():
        return []
    with reading() as conn:
        rows = conn.execute("SELECT * FROM tickets WHERE task_id = ?", (task_id,)).fetchall()
        return _decorate(conn, rows)


def list_tickets(
    root: str | None = None,
    *,
    status: Any = None,
    priority: Any = None,
    assignee: Any = None,
    label: Any = None,
    cycle: Any = None,
    parent: Any = None,
    source: Any = None,
    team: Any = None,
    project: Any = None,
    milestone: Any = None,
    query: str = "",
    open_only: bool = False,
    unassigned: bool = False,
    blocked: bool = False,
    overdue: bool = False,
    include_triage: bool = False,
    limit: int = _LIST_LIMIT,
) -> list[dict[str, Any]]:
    """필터는 전부 AND 다. 안 준 것은 안 거른다.

    `unassigned`·`blocked`·`overdue`는 화면의 현황 타일이 그대로 누르는 문이다. 셋 다 여기서
    거른다 — 화면이 받아 놓고 한 번 더 거르면 칸 머리의 건수와 카드 수가 어긋난다.

    트리아지 대기분은 **기본으로 빠진다**: 아직 받아들이지 않은 일감이 보드에 섞이면
    인박스를 따로 둔 뜻이 없어진다."""
    if _untouched():
        return []
    with reading() as conn:
        scope = _read_scope(conn, root, team)
        clauses, args = _column_clauses(
            conn, scope, status, priority, assignee, source, query, open_only, unassigned, blocked, overdue
        )
        if not include_triage:
            clauses.append("t.triage = 0")
        clauses.append("t.archived_at IS NULL")
        if scope is not None:
            clauses.append("t.team_id = ?")
            args.append(scope["id"])
        joins = _join_clauses(conn, scope, clauses, args, label, cycle, parent, project, milestone)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT t.* FROM tickets t{joins}{where} ORDER BY t.position, t.created_at LIMIT ?",
            [*args, max(1, min(int(limit), _LIST_LIMIT))],
        ).fetchall()
        return _decorate(conn, rows)


def _column_clauses(
    conn: sqlite3.Connection,
    scope: sqlite3.Row | None,
    status: Any,
    priority: Any,
    assignee: Any,
    source: Any,
    query: str,
    open_only: bool,
    unassigned: bool,
    blocked: bool,
    overdue: bool,
) -> tuple[list[str], list[Any]]:
    """티켓 표만 보고 세울 수 있는 조건들."""
    clauses: list[str] = []
    args: list[Any] = []
    allowed = _team_statuses(conn, str(scope["id"]) if scope is not None else None)
    open_marks = ",".join("?" * len(OPEN_STATUSES))
    wanted = [status] if isinstance(status, str) else list(status or [])
    if open_only:
        wanted = [s for s in (wanted or OPEN_STATUSES) if s in OPEN_STATUSES] or list(OPEN_STATUSES)
    if wanted:
        for value in wanted:
            _status(value, allowed)
        clauses.append(f"t.status IN ({','.join('?' * len(wanted))})")
        args.extend(wanted)
    if priority is not None:
        clauses.append("t.priority = ?")
        args.append(_priority(priority))
    if assignee is not None:
        clauses.append("t.assignee = ? COLLATE NOCASE" if assignee else "t.assignee = ''")
        if assignee:
            args.append(str(assignee).strip())
    if unassigned:
        clauses.append("t.assignee = ''")
    if overdue:
        clauses.append(f"(t.due_at IS NOT NULL AND t.due_at < ? AND t.status IN ({open_marks}))")
        args.extend([_now(), *OPEN_STATUSES])
    if blocked:
        clauses.append(
            "EXISTS (SELECT 1 FROM ticket_links k JOIN tickets s ON s.id = k.source_id "
            f"WHERE k.kind = 'blocks' AND k.target_id = t.id AND s.status IN ({open_marks}))"
        )
        args.extend(OPEN_STATUSES)
    if source is not None:
        if source not in SOURCES:
            raise TicketError(f"source must be one of: {', '.join(SOURCES)}")
        clauses.append("t.source = ?")
        args.append(source)
    if query:
        # LIKE로 충분하다: 워크스페이스의 티켓은 수천 건 규모라 FTS 인덱스를 따로 재우고
        # 동기화 어긋남을 감시하는 비용이 얻는 것보다 크다. 한국어도 부분 문자열로 걸린다.
        needle = f"%{str(query).strip().lower()}%"
        clauses.append("(LOWER(t.title) LIKE ? OR LOWER(t.body) LIKE ? OR LOWER(t.key) LIKE ?)")
        args.extend([needle, needle, needle])
    return clauses, args


def _join_clauses(
    conn: sqlite3.Connection,
    scope: sqlite3.Row | None,
    clauses: list[str],
    args: list[Any],
    label: Any,
    cycle: Any,
    parent: Any,
    project: Any,
    milestone: Any,
) -> str:
    """이름을 id로 풀어야 하는 조건들 — 저장소가 열려 있어야 세울 수 있다. clauses/args를 늘린다."""
    joins = ""
    if label:
        joins = " JOIN ticket_labels tl ON tl.ticket_id = t.id JOIN labels l ON l.id = tl.label_id"
        clauses.append("l.name = ? COLLATE NOCASE")
        args.append(str(label).strip())
    if cycle:
        row = find_cycle(conn, str(scope["id"]) if scope is not None else None, cycle)
        if row is None:
            raise TicketError(f"cycle not found: {cycle}")
        clauses.append("t.cycle_id = ?")
        args.append(row["id"])
    if project:
        from .projects import ProjectError, find_project

        row = find_project(conn, project)
        if row is None:
            raise TicketError(f"project not found: {project}")
        clauses.append("t.project_id = ?")
        args.append(row["id"])
        if milestone:
            from .projects import _resolve_milestone

            try:
                stone = _resolve_milestone(conn, str(row["id"]), milestone)
            except ProjectError as exc:
                raise TicketError(str(exc)) from exc
            clauses.append("t.milestone_id = ?")
            args.append(stone["id"])
    if parent is not None:
        if parent in ("", "none", False):
            clauses.append("t.parent_id IS NULL")
        else:
            clauses.append("t.parent_id = ?")
            args.append(_resolve(conn, parent, "parent ticket", scope)["id"])
    return joins


def board(root: str | None = None, **filters: Any) -> dict[str, Any]:
    """상태 칸으로 나눈 보드 한 장 — 화면이 그대로 그릴 수 있는 형태.

    칸은 **그 팀의 워크플로**에서 나온다. 워크스페이스 전체를 볼 때는 모든 팀의 칸을 범주
    순서로 합친다 — 기본 여섯으로 접으면 팀이 지은 칸에 선 티켓이 보드에서 사라진다."""
    tickets = list_tickets(root, **filters)
    states: list[dict[str, Any]] = []
    if not _untouched():  # 읽기는 자리를 만들지 않는다 — 빈 보드도 저장소 없이 그린다
        with reading() as conn:
            scope = _read_scope(conn, root, filters.get("team"))
            states = states_of(conn, str(scope["id"])) if scope is not None else _workspace_states(conn)
    if not states:
        states = [{"slug": s, "name": STATUS_LABEL[s], "type": STATUS_TYPE[s], "color": "slate"} for s in STATUSES]
    columns = []
    for state in states:
        items = [t for t in tickets if t["status"] == state["slug"]]
        columns.append(
            {
                "status": state["slug"],
                "label": state["name"],
                "type": state["type"],
                "color": state["color"],
                "tickets": items,
            }
        )
    return {"columns": columns, "total": len(tickets)}


def sort_key(ticket: dict[str, Any]) -> tuple:
    """우선순위 → 마감 → 번호. '없음'이 맨 뒤로 가라앉는 것이 이 표의 전부다."""
    return (
        _PRIORITY_RANK.get(int(ticket.get("priority") or 0), 4),
        ticket.get("due_at") if ticket.get("due_at") is not None else float("inf"),
        ticket.get("seq") or 0,
    )


def summary(root: str | None = None, team: Any = None) -> dict[str, Any]:
    """메뉴와 상태 막대가 드는 현황 — 한 번의 왕복으로 셈이 끝나야 한다."""
    if _untouched():
        return _empty_summary(root)
    with reading() as conn:
        scope = _read_scope(conn, root, team)
        team_id = str(scope["id"]) if scope is not None else None
        open_slugs = _slugs_of_type(conn, team_id, OPEN_TYPES)
        started_slugs = _slugs_of_type(conn, team_id, frozenset({"started"}))
        done_slugs = _slugs_of_type(conn, team_id, frozenset({"completed"}))
        canceled_slugs = _slugs_of_type(conn, team_id, frozenset({"canceled"}))
        tally = _tally(conn, _now(), team_id, open_slugs)
        tally["prefix"] = str(scope["key"]) if scope is not None else ""
        tally["team"] = (
            {"id": team_id, "key": str(scope["key"]), "name": str(scope["name"])} if scope is not None else None
        )
        tally["teams"] = [
            {"id": str(r["id"]), "key": str(r["key"]), "name": str(r["name"])}
            for r in conn.execute("SELECT id, key, name FROM teams WHERE archived_at IS NULL ORDER BY key")
        ]
        tally["states"] = _team_statuses(conn, team_id)
        tally["triage"] = _triage_count(conn, team_id)
    counts, by_priority = tally.pop("_status"), tally.pop("_priority")
    if not tally["prefix"]:
        tally["prefix"] = prefix(root or "")
    return {
        **tally,
        "total": sum(counts.values()),
        "open": sum(counts.get(status, 0) for status in open_slugs),
        "started": sum(counts.get(status, 0) for status in started_slugs),
        "done": sum(counts.get(status, 0) for status in done_slugs),
        "canceled": sum(counts.get(status, 0) for status in canceled_slugs),
        "status": {status: counts.get(status, 0) for status in tally["states"]},
        "priority": {str(value): by_priority.get(value, 0) for value in PRIORITIES},
        "urgent": by_priority.get(1, 0) + by_priority.get(2, 0),
        "labels": list_labels(),
        "cycle": active_cycle(root, team),
    }


def _triage_count(conn: sqlite3.Connection, team_id: str | None) -> int:
    clause = "" if team_id is None else " AND team_id = ?"
    args = [_now()] + ([team_id] if team_id else [])
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM tickets WHERE triage = 1 AND archived_at IS NULL "
        f"AND (snoozed_at IS NULL OR snoozed_at <= ?){clause}",
        args,
    ).fetchone()
    return int(row["n"] or 0)


def _tally(
    conn: sqlite3.Connection, now: float, team_id: str | None, open_slugs: tuple[str, ...] = OPEN_STATUSES
) -> dict[str, Any]:
    """현황의 셈 부분. `_`로 시작하는 두 칸은 호출자가 접어서 쓰는 원자재다.

    '열린 것'의 목록을 인자로 받는 이유: 팀이 상태 이름을 스스로 짓기 때문이다. 기본 여섯의
    슬러그로 굳혀 두면 팀이 만든 칸의 티켓이 어느 셈에도 안 잡힌다."""
    week = now - 7 * 86_400
    marks = ",".join("?" * len(open_slugs))
    scope = "" if team_id is None else " AND team_id = ?"
    tail: list[Any] = [team_id] if team_id else []
    one = lambda sql, args: conn.execute(sql, args).fetchone()["n"]  # noqa: E731
    return {
        "_status": {
            row["status"]: row["n"]
            for row in conn.execute(
                f"SELECT status, COUNT(*) AS n FROM tickets WHERE triage = 0 AND archived_at IS NULL"
                f"{scope} GROUP BY status",
                tail,
            )
        },
        "_priority": {
            int(row["priority"]): row["n"]
            for row in conn.execute(
                f"SELECT priority, COUNT(*) AS n FROM tickets WHERE status IN ({marks}) AND triage = 0{scope} "
                f"GROUP BY priority",
                [*open_slugs, *tail],
            )
        },
        "unassigned": one(
            f"SELECT COUNT(*) AS n FROM tickets WHERE assignee = '' AND triage = 0 AND status IN ({marks}){scope}",
            [*open_slugs, *tail],
        ),
        # 막힌 것 = 열린 티켓을 열린 티켓이 막고 있는 경우. 막는 쪽이 닫히면 더는 막힘이 아니다.
        "blocked": one(
            f"SELECT COUNT(DISTINCT k.target_id) AS n FROM ticket_links k "
            f"JOIN tickets s ON s.id = k.source_id JOIN tickets t ON t.id = k.target_id "
            f"WHERE k.kind = 'blocks' AND s.status IN ({marks}) AND t.status IN ({marks})"
            f"{scope.replace('team_id', 't.team_id')}",
            [*open_slugs, *open_slugs, *tail],
        ),
        "overdue": one(
            f"SELECT COUNT(*) AS n FROM tickets WHERE due_at IS NOT NULL AND due_at < ? "
            f"AND triage = 0 AND status IN ({marks}){scope}",
            [now, *open_slugs, *tail],
        ),
        "created_week": one(f"SELECT COUNT(*) AS n FROM tickets WHERE created_at >= ?{scope}", [week, *tail]),
        "done_week": one(
            f"SELECT COUNT(*) AS n FROM tickets WHERE completed_at IS NOT NULL AND completed_at >= ?{scope}",
            [week, *tail],
        ),
        "assignees": [
            {"name": row["assignee"], "open": row["n"]}
            for row in conn.execute(
                f"SELECT assignee, COUNT(*) AS n FROM tickets WHERE assignee <> '' AND status IN ({marks}){scope}"
                f" GROUP BY assignee ORDER BY n DESC LIMIT 12",
                [*open_slugs, *tail],
            )
        ],
        "recent": [
            {
                "key": row["key"],
                "title": row["title"],
                "actor": row["actor"],
                "field": row["field"],
                "after": row["after"],
                "created_at": row["created_at"],
            }
            for row in conn.execute(
                f"SELECT a.actor, a.field, a.after, a.created_at, t.key, t.title FROM activity a "
                f"JOIN tickets t ON t.id = a.ticket_id "
                f"{'WHERE t.team_id = ?' if team_id else ''} ORDER BY a.id DESC LIMIT 12",
                tail,
            )
        ],
    }


def _empty_summary(root: str | None) -> dict[str, Any]:
    """아직 한 건도 없는 워크스페이스의 현황. 셈은 전부 0 이지만 **어휘와 접두어는 진짜다** —
    화면이 '첫 티켓을 만들면 NOR-1이 됩니다'를 말할 수 있어야 한다."""
    return {
        "prefix": prefix(root or ""),
        "team": None,
        "teams": [],
        "states": list(STATUSES),
        "triage": 0,
        "total": 0,
        "open": 0,
        "started": 0,
        "done": 0,
        "canceled": 0,
        "status": dict.fromkeys(STATUSES, 0),
        "priority": {str(value): 0 for value in PRIORITIES},
        "urgent": 0,
        "unassigned": 0,
        "blocked": 0,
        "overdue": 0,
        "created_week": 0,
        "done_week": 0,
        "assignees": [],
        "labels": [],
        "cycle": None,
        "recent": [],
    }
