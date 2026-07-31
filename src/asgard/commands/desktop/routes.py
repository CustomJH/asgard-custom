"""경로표 — 어떤 요청이 어느 함수로 가는가. 이 모듈에는 규칙이 없다.

읽기(GET)와 쓰기(POST/PUT)를 나눠 둔 이유는 문지기가 다르기 때문이다: 쓰기는
`loopback`의 Origin 검사를 한 겹 더 지난다.
"""

from __future__ import annotations

import json
from importlib.resources import files as _files

from .. import loopback
from .artifacts import read_artifact, read_diff, reveal_path
from .boundary import _known_root, current_root, resolve_workspace
from .config import save_role, save_settings, save_skill
from .snapshot import _catalog_state, settings_state, snapshot_data
from .state import _TASK_LOCK, _TASKS
from .tasks import (
    _feed_snapshot,
    _public_task,
    _task_snapshot,
    approve_task,
    create_task,
    follow_task,
    load_project_tasks,
    pause_task,
    resume_task,
    run_ticket,
    stop_task,
)
from .workspaces import add_project, browse_projects, forget_project, pick_folder, prune_projects, use_project

_json_body = loopback.json_body


def _plan_dispatch(method: str, path: str, payload: dict | None, root: str) -> tuple[int, str, bytes]:
    from ..plan_dashboard.server import dispatch as plan_dispatch

    body = json.dumps(payload or {}, ensure_ascii=False).encode() if payload is not None else b""
    return plan_dispatch(method, path, body, root)


def _ticket_dispatch(
    method: str, path: str, params: dict[str, list[str]] | None, payload: dict | None, root: str
) -> tuple[int, str, bytes]:
    from .. import ticket_api

    return ticket_api.dispatch(method, path, params, payload, root)


def dispatch(
    method: str, path: str, params: dict[str, list[str]] | None = None, root: str | None = None
) -> tuple[int, str, bytes]:
    root = current_root(root)
    params = params or {}
    if method not in ("GET", "HEAD"):
        return 405, "text/plain; charset=utf-8", b"method not allowed"
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", render_html().encode()
    if path == "/asset/logo":
        return 200, "image/png", (_files("asgard") / "assets" / "gold-brand-logo.png").read_bytes()
    if path == "/asset/mark":
        # 위그드라실 마크 — asgard map · memory가 드는 것과 같은 파일이라 세 창이 같은 마크를 든다
        return 200, "image/png", (_files("asgard") / "assets" / "yggdrasil-mark.png").read_bytes()
    if path in ("/asset/app-icon", "/favicon.ico"):
        # 네이티브 창의 앱 아이콘과 같은 그림 — 브라우저로 열어도 탭에 같은 얼굴이 뜬다
        return 200, "image/png", (_files("asgard") / "assets" / "app-icon.png").read_bytes()
    if path == "/api/snapshot":
        return _json_body(200, snapshot_data(root))
    if path == "/api/tasks":
        # 기본은 이 작업 공간. `?scope=all` 이면 프로젝트를 건너 하나의 목록으로 본다.
        if (params.get("scope") or [""])[0] == "all":
            return _json_body(200, _feed_snapshot(root))
        return _json_body(200, _task_snapshot(root))
    if path == "/api/projects":
        from .. import desktop_store

        return _json_body(200, {"projects": desktop_store.list_projects(root), "current": root})
    if path in ("/api/artifact", "/api/diff"):
        # 산출물은 **그 작업이 돈 자리**에 있다. 창이 다른 프로젝트를 보고 있는데 남의 작업의
        # 변경 파일을 열면, 여태는 같은 상대 경로를 이 저장소에서 찾았다 — 없으면 404,
        # 하필 같은 이름이 있으면 **엉뚱한 파일의 내용**을 그 작업의 산출물이라고 보여 준다.
        where, failed = _known_root(params, root)
        if failed:
            return _json_body(403, {"error": failed})
        return read_artifact(where, params) if path == "/api/artifact" else read_diff(where, params)
    if path == "/api/task":
        task_id = (params.get("id") or [""])[0]
        # 남의 프로젝트의 대화를 목록에서 눌렀을 수 있다 — 그 자리의 기록을 그때 올린다.
        # (창의 경계는 안 옮긴다. 읽는 것과 옮기는 것은 다른 일이다.)
        home = (params.get("root") or [""])[0]
        if home:
            found, failed = resolve_workspace(home, root)
            if not failed:
                load_project_tasks(found)
        with _TASK_LOCK:
            task = _TASKS.get(task_id)
            return _json_body(200, _public_task(task)) if task else _json_body(404, {"error": "task not found"})
    if path == "/api/settings":
        return _json_body(200, settings_state(root))
    if path == "/api/catalog":
        return _json_body(200, _catalog_state(root))
    if path == "/api/plans" or path.startswith("/api/plans/"):
        return _plan_dispatch(method, path, None, root)
    from .. import ticket_api

    if ticket_api.owns(path):
        return _ticket_dispatch(method, path, params, None, root)
    if path == "/health":
        return _json_body(200, {"ok": True, "surface": "desktop"})
    return 404, "text/plain; charset=utf-8", b"not found"


def dispatch_post(path: str, payload: dict, root: str | None = None) -> tuple[int, str, bytes]:
    root = current_root(root)
    if path == "/api/plans" or path.startswith("/api/plans/"):
        return _plan_dispatch("POST", path, payload, root)
    from .. import ticket_api

    if path == "/api/tickets/run":
        return run_ticket(payload, root)
    if ticket_api.owns(path):
        return _ticket_dispatch("POST", path, None, payload, root)
    routes = {
        "/api/tasks": lambda: create_task(payload, root),
        "/api/tasks/approve": lambda: approve_task(payload, root),
        "/api/tasks/follow": lambda: follow_task(payload, root),
        "/api/tasks/stop": lambda: stop_task(payload),
        "/api/tasks/pause": lambda: pause_task(payload),
        "/api/tasks/resume": lambda: resume_task(payload),
        "/api/projects/use": lambda: use_project(payload),
        "/api/projects/add": lambda: add_project(payload),
        "/api/projects/browse": lambda: browse_projects(payload, root),
        "/api/projects/pick": lambda: pick_folder(payload),
        "/api/projects/forget": lambda: forget_project(payload),
        "/api/projects/prune": lambda: prune_projects(payload),
        "/api/reveal": lambda: reveal_path(root, payload),
        "/api/settings": lambda: save_settings(payload, root),
        "/api/skill": lambda: save_skill(payload, root),
        "/api/role": lambda: save_role(payload, root),
    }
    route = routes.get(path)
    return route() if route else (404, "text/plain; charset=utf-8", b"not found")


def dispatch_put(path: str, payload: dict, root: str | None = None) -> tuple[int, str, bytes]:
    root = current_root(root)
    if path.startswith("/api/plans/"):
        return _plan_dispatch("PUT", path, payload, root)
    from .. import ticket_api

    if ticket_api.owns(path):
        return _ticket_dispatch("PUT", path, None, payload, root)
    return 404, "text/plain; charset=utf-8", b"not found"


def render_html() -> str:
    """창의 페이지 — 자립형 단일 파일이라 프로세스가 뜰 때 한 번 읽어 든다."""
    return _PAGE


_PAGE = (_files("asgard") / "assets" / "desktop.html").read_text(encoding="utf-8")
