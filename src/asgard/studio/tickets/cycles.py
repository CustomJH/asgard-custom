"""티켓 — 주기(사이클). 팀마다 하나가 열려 있고, 닫으면 남은 일감이 다음으로 넘어간다."""

from __future__ import annotations

from typing import Any

from ..db import reading, writing
from ..teams import ensure_team, find_team
from ._core import TicketError, _now, _read_scope, _untouched, _write_team

# ── 주기(사이클) — 정본은 teams.py, 여기는 폴더 기준의 손잡이 ────────────────────


def create_cycle(
    root: str, name: str = "", starts_at: Any = None, ends_at: Any = None, team: Any = None
) -> dict[str, Any]:
    from .. import teams as T

    with writing() as conn:
        team_id = str(_write_team(conn, root, team)["id"])
    return T.create_cycle(team_id, name=name, starts_at=starts_at, ends_at=ends_at)


def close_cycle(root: str, ref: Any, roll: bool = True, team: Any = None) -> dict[str, Any]:
    """사이클은 팀의 것이라 **하나를 골라야** 닫을 수 있다.

    읽기의 기본은 워크스페이스 전체지만 여기서 그 규칙을 쓰면 늘 "팀이 없다"가 된다. 그래서
    자리를 고르는 방식은 `create_cycle`과 같다 — 결속된 폴더면 그 팀, 아니면 기본 팀. 다만
    **만들지는 않는다**: 없는 팀의 사이클을 닫는다는 말은 성립하지 않는다."""
    from .. import teams as T

    with reading() as conn:
        row = find_team(conn, team) if team else ensure_team(conn, root, create=False)
        if row is None:
            raise TicketError(f"team not found: {team}" if team else "no team holds a cycle to close")
        team_id = str(row["id"])
    return T.close_cycle(team_id, ref, roll=roll)


def list_cycles(root: str | None = None, team: Any = None) -> list[dict[str, Any]]:
    if _untouched():
        return []
    from ..teams import _cycle_row  # noqa: PLC0415  (같은 패키지의 표현 재사용)

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
