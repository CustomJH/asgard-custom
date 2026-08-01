"""스튜디오 창이 일감을 읽고 고치는 문 — `/api/tickets*` · `/api/teams*` · `/api/projects*`.

라우팅만 진다. 어휘와 규칙은 전부 `asgard.studio`가 소유하고, 여기서는 그것을 JSON으로
옮기기만 한다. 상태·우선순위 목록도 **서버가 함께 보낸다**: 화면이 같은 enum을 하나 더
들고 있으면, 칸 하나를 늘릴 때 두 곳을 고쳐야 하고 언젠가 한 곳만 고친다.

경계는 폴더가 아니라 워크스페이스다. 그래서 모든 읽기는 `team`을 받되, **안 주면 전체**다 —
폴더는 거르는 값이지 경계가 아니다(`.`을 주면 이 폴더에 결속된 팀만, [[studio.tickets]]).
"""

from __future__ import annotations

import json
from typing import Any

from .. import errors
from ..studio import legacy
from ..studio import projects as P
from ..studio import teams as TM
from ..studio import tickets as T
from ..studio import vocab as V

_PATHS = frozenset(
    {
        "/api/tickets",
        "/api/tickets/move",
        "/api/tickets/comment",
        "/api/tickets/link",
        "/api/tickets/unlink",
        "/api/tickets/delete",
        "/api/tickets/label",
        "/api/tickets/label/delete",
        "/api/tickets/cycle",
        "/api/tickets/cycle/close",
        "/api/tickets/cycle/roll",
        "/api/tickets/summary",
        "/api/ticket",
        # 팀 — 번호의 주인, 워크플로·사이클·트리아지의 단위
        "/api/teams",
        "/api/teams/archive",
        "/api/teams/bind",
        "/api/teams/states",
        "/api/teams/states/delete",
        # 프로젝트 — 팀을 가로지르는 축
        "/api/projects",
        "/api/project",
        "/api/projects/archive",
        "/api/projects/delete",
        "/api/projects/team",
        "/api/projects/milestone",
        "/api/projects/milestone/delete",
        "/api/projects/milestone/complete",
        "/api/projects/update",
        "/api/projects/resource",
        "/api/projects/resource/delete",
        "/api/projects/labels",
        "/api/projects/members",
        "/api/initiatives",
        "/api/initiative",
        # 트리아지 — 팀의 인박스
        "/api/triage",
        "/api/triage/accept",
        "/api/triage/decline",
        "/api/triage/snooze",
        # 옛 보드 반입
        "/api/studio/import",
    }
)


def owns(path: str) -> bool:
    return path in _PATHS


def _json(status: int, value: object) -> tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False, allow_nan=False).encode()


def _error(status: int, code: str, message: str) -> tuple[int, str, bytes]:
    """오류 한 겹은 `loopback`이 소유한다 — 이 파일이 네 번째 사본이 되지 않게."""
    from . import loopback

    return loopback.api_error(status, code, message)


def _one(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key) or []
    return str(values[0]).strip() if values else default


def _flag(payload: dict, key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes")
    return bool(value)


def vocabulary() -> dict[str, Any]:
    """화면이 칸과 배지를 그릴 때 쓰는 어휘 — 정본은 store 다."""
    return {
        "statuses": [
            {"id": status, "label": V.STATUS_LABEL[status], "type": V.STATUS_TYPE[status]} for status in V.STATUSES
        ],
        "status_types": [{"id": kind, "label": V.STATUS_TYPE_LABEL[kind]} for kind in V.STATUS_TYPES],
        "priorities": [{"value": value, "label": V.PRIORITY_LABEL[value]} for value in (1, 2, 3, 4, 0)],
        "sources": list(V.SOURCES),
        "link_kinds": list(V.LINK_KINDS),
        "label_colors": list(V.LABEL_COLORS),
        "project_statuses": [{"id": status, "label": V.PROJECT_STATUS_LABEL[status]} for status in V.PROJECT_STATUSES],
        "initiative_statuses": [
            {"id": status, "label": V.INITIATIVE_STATUS_LABEL[status]} for status in V.INITIATIVE_STATUSES
        ],
        "healths": [{"id": kind, "label": V.HEALTH_LABEL[kind]} for kind in V.HEALTHS],
        "estimate_scales": list(V.ESTIMATE_SCALES),
    }


def _filters(params: dict[str, list[str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    status = params.get("status") or []
    if status:
        out["status"] = [s for s in status if s]
    for key in ("assignee", "label", "cycle", "source", "parent", "team", "project", "milestone"):
        if key in params:
            out[key] = _one(params, key)
    if _one(params, "priority"):
        out["priority"] = int(_one(params, "priority"))
    if _one(params, "q"):
        out["query"] = _one(params, "q")
    if _one(params, "open") in ("1", "true", "on"):
        out["open_only"] = True
    for flag in ("unassigned", "blocked", "overdue", "include_triage"):
        if _one(params, flag) in ("1", "true", "on"):
            out[flag] = True
    return out


def snapshot(root: str, params: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """보드 한 장 + 현황 + 어휘 + 팀/프로젝트 목록. 창이 화면을 그리는 데 필요한 전부를 한 왕복에."""
    params = params or {}
    filters = _filters(params)
    team = filters.get("team")
    board = T.board(root, **filters)
    return {
        "board": board,
        "tickets": [ticket for column in board["columns"] for ticket in column["tickets"]],
        "summary": T.summary(root, team=team),
        "cycles": T.list_cycles(root, team=team),
        "teams": TM.list_teams() if T.exists() else [],
        "projects": P.list_projects() if T.exists() else [],
        "initiatives": P.list_initiatives() if T.exists() else [],
        "triage": T.triage_queue(root, team=team),
        "legacy": _legacy_roots(root),
        **vocabulary(),
    }


def _legacy_roots(root: str) -> list[str]:
    """옛 폴더 보드가 남은 자리들 — **등록부 전체**를 훑는다.

    창은 이제 개인 작업 공간에서 열린다. 그 자리만 보면 옛 보드는 영영 안 보이고, 사용자는
    자기 티켓이 사라졌다고 읽는다. 반입은 폴더를 열어야 알 수 있는 일이 아니다."""
    from . import studio_store

    try:
        roots = studio_store.known_roots(root or None)
    except Exception:
        roots = [root] if root else []
    return legacy.pending_roots(roots)


def dispatch(
    method: str,
    path: str,
    params: dict[str, list[str]] | None = None,
    payload: dict | None = None,
    root: str = "",
) -> tuple[int, str, bytes]:
    params = params or {}
    payload = payload or {}
    try:
        return _route(method, path, params, payload, root)
    except errors.AsgardError as exc:
        # 상태 코드는 **예외가 안다**. 여기에 표를 하나 더 두면, 새 도메인 오류가 생겼을 때
        # 이 표에 줄을 안 더한 것만으로 "사용자가 고칠 수 있는 잘못"이 500으로 나간다.
        # (정본을 못 연 경우가 503으로 가는 것도 그 규칙의 결과다 — 빈 보드로 가장하지 않는다.)
        from . import loopback

        return loopback.error_result(exc, surface="tickets", root=root, where=path)


def _route(method: str, path: str, params: dict[str, list[str]], payload: dict, root: str) -> tuple[int, str, bytes]:
    if method in ("GET", "HEAD"):
        return _read(path, params, root)
    return _write(method, path, payload, root)


def _read(path: str, params: dict[str, list[str]], root: str) -> tuple[int, str, bytes]:
    if path == "/api/tickets":
        return _json(200, snapshot(root, params))
    if path == "/api/tickets/summary":
        return _json(200, {"summary": T.summary(root, team=_one(params, "team") or None), **vocabulary()})
    if path == "/api/ticket":
        ref = _one(params, "key") or _one(params, "id")
        found = T.find_ticket(root, ref)
        return _json(200, found) if found else _error(404, "ticket_not_found", f"ticket not found: {ref}")
    if path == "/api/teams":
        if not T.exists():
            return _json(200, {"teams": [], "vocabulary": vocabulary()})
        rows = TM.list_teams(include_archived=_one(params, "archived") in ("1", "true"))
        for row in rows:
            row["states"] = TM.list_states(row["id"])
            row["cycles"] = TM.cycles_for(row["id"])
        return _json(200, {"teams": rows, "vocabulary": vocabulary()})
    if path == "/api/teams/states":
        return _json(200, {"states": TM.list_states(_one(params, "team"))})
    if path == "/api/projects":
        if not T.exists():
            return _json(200, {"projects": []})
        return _json(
            200,
            {
                "projects": P.list_projects(
                    status=_one(params, "status"),
                    team=_one(params, "team") or None,
                    initiative=_one(params, "initiative") or None,
                    include_archived=_one(params, "archived") in ("1", "true"),
                )
            },
        )
    if path == "/api/project":
        ref = _one(params, "ref") or _one(params, "id")
        project = P.get_project(ref)
        project["tickets"] = T.list_tickets(root, team="*", project=ref, limit=500)
        return _json(200, project)
    if path == "/api/initiatives":
        return _json(200, {"initiatives": P.list_initiatives() if T.exists() else []})
    if path == "/api/initiative":
        return _json(200, P.get_initiative(_one(params, "ref") or _one(params, "id")))
    if path == "/api/triage":
        return _json(200, {"tickets": T.triage_queue(root, team=_one(params, "team") or None)})
    return _error(405, "method_not_allowed", "method not allowed")


def _write(method: str, path: str, payload: dict, root: str) -> tuple[int, str, bytes]:
    actor = str(payload.get("actor") or "").strip()
    ref = str(payload.get("ref") or payload.get("key") or payload.get("id") or "")

    if path == "/api/tickets" and method == "POST":
        return _json(201, T.create_ticket(root, str(payload.get("title") or ""), **_create_args(payload), actor=actor))
    if path == "/api/tickets" and method == "PUT":
        changes = payload.get("changes")
        if not isinstance(changes, dict):
            return _error(400, "invalid_ticket", "changes must be an object")
        return _json(200, T.update_ticket(root, ref, changes, actor=actor))
    if path == "/api/tickets/move" and method == "POST":
        return _json(
            200,
            T.move_ticket(root, ref, str(payload.get("status") or ""), payload.get("index"), actor=actor),
        )
    if path == "/api/tickets/comment" and method == "POST":
        return _json(201, T.add_comment(root, ref, str(payload.get("body") or ""), author=actor))
    if path == "/api/tickets/link" and method == "POST":
        return _json(
            200,
            T.link_tickets(
                root, ref, str(payload.get("kind") or "blocks"), str(payload.get("other") or ""), actor=actor
            ),
        )
    if path == "/api/tickets/unlink" and method == "POST":
        removed = T.unlink_tickets(root, ref, str(payload.get("kind") or "blocks"), str(payload.get("other") or ""))
        return _json(200, {"removed": removed})
    if path == "/api/tickets/delete" and method == "POST":
        return _json(200, {"deleted": T.delete_ticket(root, ref)})
    if path == "/api/tickets/label" and method == "POST":
        return _json(
            201,
            T.create_label(
                root,
                str(payload.get("name") or ""),
                str(payload.get("color") or "slate"),
                str(payload.get("group") or ""),
            ),
        )
    if path == "/api/tickets/label/delete" and method == "POST":
        return _json(200, {"deleted": T.delete_label(root, str(payload.get("name") or ""))})

    # ── 사이클 ────────────────────────────────────────────────────────────────
    if path == "/api/tickets/cycle" and method == "POST":
        team = payload.get("team")
        if team:
            return _json(
                201,
                TM.create_cycle(team, str(payload.get("name") or ""), payload.get("starts_at"), payload.get("ends_at")),
            )
        return _json(
            201, T.create_cycle(root, str(payload.get("name") or ""), payload.get("starts_at"), payload.get("ends_at"))
        )
    if path == "/api/tickets/cycle/close" and method == "POST":
        roll = _flag(payload, "roll", True)
        team = payload.get("team")
        if team:
            return _json(200, TM.close_cycle(team, ref, roll=roll))
        return _json(200, T.close_cycle(root, ref, roll=roll))
    if path == "/api/tickets/cycle/roll" and method == "POST":
        return _json(200, TM.roll_cycle(payload.get("team") or _team_of(root)))

    # ── 팀 ────────────────────────────────────────────────────────────────────
    if path == "/api/teams" and method == "POST":
        return _json(
            201, TM.create_team(str(payload.get("name") or ""), str(payload.get("key") or ""), **_team_args(payload))
        )
    if path == "/api/teams" and method == "PUT":
        changes = payload.get("changes")
        if not isinstance(changes, dict):
            return _error(400, "invalid_ticket", "changes must be an object")
        return _json(200, TM.update_team(ref, changes))
    if path == "/api/teams/archive" and method == "POST":
        return _json(200, TM.archive_team(ref, _flag(payload, "archived", True)))
    if path == "/api/teams/bind" and method == "POST":
        target = str(payload.get("root") or root)
        if _flag(payload, "unbind"):
            return _json(200, {"unbound": TM.unbind_root(target)})
        return _json(200, TM.bind_root(ref, target))
    if path == "/api/teams/states" and method == "POST":
        return _json(
            201,
            TM.create_state(
                str(payload.get("team") or ""),
                str(payload.get("name") or ""),
                str(payload.get("type") or "unstarted"),
                str(payload.get("color") or "slate"),
                str(payload.get("slug") or ""),
            ),
        )
    if path == "/api/teams/states" and method == "PUT":
        changes = payload.get("changes")
        if not isinstance(changes, dict):
            return _error(400, "invalid_ticket", "changes must be an object")
        return _json(200, TM.update_state(str(payload.get("team") or ""), str(payload.get("slug") or ""), changes))
    if path == "/api/teams/states/delete" and method == "POST":
        return _json(200, {"deleted": TM.delete_state(str(payload.get("team") or ""), str(payload.get("slug") or ""))})

    # ── 프로젝트 ──────────────────────────────────────────────────────────────
    if path == "/api/projects" and method == "POST":
        return _json(201, P.create_project(str(payload.get("name") or ""), **_project_args(payload)))
    if path == "/api/projects" and method == "PUT":
        changes = payload.get("changes")
        if not isinstance(changes, dict):
            return _error(400, "invalid_ticket", "changes must be an object")
        return _json(200, P.update_project(ref, changes))
    if path == "/api/projects/archive" and method == "POST":
        return _json(200, P.archive_project(ref, _flag(payload, "archived", True)))
    if path == "/api/projects/delete" and method == "POST":
        return _json(200, {"deleted": P.delete_project(ref)})
    if path == "/api/projects/team" and method == "POST":
        return _json(200, P.add_project_team(ref, str(payload.get("team") or ""), _flag(payload, "attached", True)))
    if path == "/api/projects/milestone" and method == "POST":
        return _json(
            201,
            P.add_milestone(
                ref, str(payload.get("name") or ""), payload.get("target_at"), str(payload.get("description") or "")
            ),
        )
    if path == "/api/projects/milestone" and method == "PUT":
        changes = payload.get("changes")
        if not isinstance(changes, dict):
            return _error(400, "invalid_ticket", "changes must be an object")
        return _json(200, P.update_milestone(ref, str(payload.get("milestone") or ""), changes))
    if path == "/api/projects/milestone/complete" and method == "POST":
        return _json(200, P.complete_milestone(ref, str(payload.get("milestone") or ""), _flag(payload, "done", True)))
    if path == "/api/projects/milestone/delete" and method == "POST":
        return _json(200, {"deleted": P.delete_milestone(ref, str(payload.get("milestone") or ""))})
    if path == "/api/projects/update" and method == "POST":
        return _json(
            201,
            P.add_update(ref, str(payload.get("body") or ""), str(payload.get("health") or ""), author=actor),
        )
    if path == "/api/projects/resource" and method == "POST":
        return _json(
            201,
            P.add_resource(
                ref, str(payload.get("title") or ""), str(payload.get("url") or ""), str(payload.get("kind") or "link")
            ),
        )
    if path == "/api/projects/resource/delete" and method == "POST":
        return _json(200, {"deleted": P.delete_resource(ref, str(payload.get("resource") or ""))})
    if path == "/api/projects/labels" and method == "POST":
        return _json(200, P.set_labels(ref, payload.get("labels") or []))
    if path == "/api/projects/members" and method == "POST":
        return _json(200, P.set_members(ref, payload.get("members") or []))

    # ── 이니셔티브 ────────────────────────────────────────────────────────────
    if path == "/api/initiatives" and method == "POST":
        return _json(201, P.create_initiative(str(payload.get("name") or ""), **_initiative_args(payload)))
    if path == "/api/initiatives" and method == "PUT":
        changes = payload.get("changes")
        if not isinstance(changes, dict):
            return _error(400, "invalid_ticket", "changes must be an object")
        return _json(200, P.update_initiative(ref, changes))

    # ── 트리아지 ──────────────────────────────────────────────────────────────
    if path == "/api/triage/accept" and method == "POST":
        return _json(
            200, T.triage_accept(root, ref, str(payload.get("status") or ""), actor, str(payload.get("note") or ""))
        )
    if path == "/api/triage/decline" and method == "POST":
        return _json(200, T.triage_decline(root, ref, actor, str(payload.get("note") or "")))
    if path == "/api/triage/snooze" and method == "POST":
        return _json(200, T.triage_snooze(root, ref, payload.get("until"), actor))

    # ── 옛 보드 반입 ──────────────────────────────────────────────────────────
    if path == "/api/studio/import" and method == "POST":
        return _json(200, legacy.import_root(str(payload.get("root") or root)))
    return _error(405, "method_not_allowed", "method not allowed")


def _team_of(root: str) -> str:
    """사이클을 굴릴 팀 — 결속된 폴더면 그 팀, 아니면 워크스페이스 기본 팀.

    사이클은 팀 **하나**의 것이라 전체 보기로는 못 굴린다. 폴더가 결속돼 있지 않은 것이
    이제는 정상이라(폴더가 스스로 팀이 되지 않는다) 여기서 빈 값을 돌려주면, 팀을 손으로
    적기 전까지 창의 '다음 주기로' 버튼이 영영 400을 받는다."""
    from ..studio.db import reading
    from ..studio.teams import ensure_team

    if not T.exists():
        return ""
    with reading() as conn:
        row = ensure_team(conn, root, create=False)
        return str(row["key"]) if row is not None else ""


def _create_args(payload: dict) -> dict[str, Any]:
    """생성 시 받는 칸만 추린다 — 모르는 칸이 조용히 저장소로 새지 않게."""
    out: dict[str, Any] = {}
    for key in (
        "body",
        "status",
        "assignee",
        "reporter",
        "source",
        "parent",
        "cycle",
        "team",
        "project",
        "milestone",
        "plan_id",
        "plan_record",
        "task_id",
    ):
        if payload.get(key) not in (None, ""):
            out[key] = str(payload[key])
    if payload.get("priority") is not None:
        out["priority"] = payload["priority"]
    if payload.get("estimate") not in (None, ""):
        out["estimate"] = payload["estimate"]
    if payload.get("due_at") not in (None, ""):
        out["due_at"] = payload["due_at"]
    if payload.get("triage") is not None:
        out["triage"] = _flag(payload, "triage")
    labels = payload.get("labels")
    if isinstance(labels, list):
        out["labels"] = labels
    return out


def _team_args(payload: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("description", "color", "estimates", "default_status"):
        if payload.get(key) not in (None, ""):
            out[key] = str(payload[key])
    for key in ("cycle_weeks", "cycle_cooldown"):
        if payload.get(key) not in (None, ""):
            out[key] = int(payload[key])
    if payload.get("triage") is not None:
        out["triage"] = _flag(payload, "triage")
    return out


def _project_args(payload: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("description", "icon", "color", "lead", "status", "health", "initiative"):
        if payload.get(key) not in (None, ""):
            out[key] = str(payload[key])
    if payload.get("priority") is not None:
        out["priority"] = payload["priority"]
    for key in ("starts_at", "target_at"):
        if payload.get(key) not in (None, ""):
            out[key] = payload[key]
    for key in ("teams", "members"):
        if isinstance(payload.get(key), list):
            out[key] = payload[key]
    return out


def _initiative_args(payload: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("description", "owner", "status"):
        if payload.get(key) not in (None, ""):
            out[key] = str(payload[key])
    if payload.get("priority") is not None:
        out["priority"] = payload["priority"]
    if payload.get("target_at") not in (None, ""):
        out["target_at"] = payload["target_at"]
    return out
