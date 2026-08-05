"""티켓의 공용 바닥 — 한계값, 오류, 보이는 범위, 그리고 필드 하나를 받아들이는 규칙.

`TicketError` 가 28곳, `_read_scope` 가 19곳에서 불린다. 표면을 갈랐어도 "어디까지 보이는가"와
"이 값을 받는가"는 한 자리에 있어야 티켓마다 답이 달라지지 않는다."""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from ... import errors
from ..db import exists, reading
from ..teams import ensure_team, find_team, states_of, team_for_root
from ..vocab import (
    PRIORITIES,
    STATUS_LABEL,
    STATUS_TYPE,
    STATUS_TYPES,
    STATUSES,
)

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
    from ..teams import status_type

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
    from ..teams import default_team, key_from_name

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
