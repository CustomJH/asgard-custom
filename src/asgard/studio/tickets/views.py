"""티켓 — 읽는 면. 한 건의 상세, 목록 질의, 보드, 그리고 워크스페이스 요약."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..db import reading
from ..teams import find_cycle, states_of
from ..vocab import (
    OPEN_STATUSES,
    OPEN_TYPES,
    PRIORITIES,
    SOURCES,
    STATUS_LABEL,
    STATUS_TYPE,
    STATUSES,
)
from ..vocab import (
    PRIORITY_RANK as _PRIORITY_RANK,
)
from ._core import (
    _LIST_LIMIT,
    TicketError,
    _find,
    _now,
    _priority,
    _read_scope,
    _resolve,
    _slugs_of_type,
    _status,
    _team_statuses,
    _untouched,
    _workspace_states,
    prefix,
)
from .cycles import active_cycle
from .evidence import _evidence_rows
from .labels import list_labels

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
    from ..teams import _cycle_row

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
        from ..projects import ProjectError, find_project

        row = find_project(conn, project)
        if row is None:
            raise TicketError(f"project not found: {project}")
        clauses.append("t.project_id = ?")
        args.append(row["id"])
        if milestone:
            from ..projects import _resolve_milestone

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
