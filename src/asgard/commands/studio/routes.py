"""경로표 — 어떤 요청이 어느 함수로 가는가. 이 모듈에는 규칙이 없다.

읽기(GET)와 쓰기(POST/PUT)를 나눠 둔 이유는 접근 검사가 다르기 때문이다: 쓰기는
`loopback`의 Origin 검사를 한 겹 더 지난다.
"""

from __future__ import annotations

import json
from importlib.resources import files as _files

from .. import loopback
from .agents import (
    agent_detail,
    bind_agent,
    create_agent,
    delete_agent,
    describe_agent,
    rename_agent,
    request_scope,
    runs_state,
    unbind_agent,
    use_agent,
)
from .agents import panel_state as agents_state
from .agents import (
    save_config as save_agent_config,
)
from .agents import (
    save_identity as save_agent_identity,
)
from .artifacts import read_artifact, read_diff, reveal_path
from .boundary import _known_root, current_root, resolve_workspace
from .config import save_role, save_settings, save_skill
from .load import live_state, probe_target, start_run, start_selftest, stop_run
from .load import panel_state as load_panel
from .orchestration import panel_state as orchestration_state
from .orchestration import recheck_engines, save_policy
from .snapshot import _catalog_state, _provider_state, settings_state, snapshot_data
from .state import _TASK_LOCK, _TASKS
from .tasks import (
    _feed_snapshot,
    _public_task,
    _task_snapshot,
    approve_task,
    assign_ticket,
    create_task,
    follow_task,
    load_project_tasks,
    pause_task,
    resume_task,
    run_ticket,
    stop_task,
)
from .tutor import answer_point, dismiss_point, panel_state
from .workspaces import add_project, browse_projects, forget_project, pick_folder, prune_projects, use_project

_json_body = loopback.json_body


def _plan_dispatch(method: str, path: str, payload: dict | None, root: str) -> tuple[int, str, bytes]:
    from ..plan_api.server import dispatch as plan_dispatch

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
    explicit = (params.get("agent") or [""])[0]
    scoped, failed = request_scope(root, explicit)
    if scoped is None:
        return failed
    from ... import profiles

    with profiles.scoped(scoped["agent"]):
        return _dispatch(method, path, params, root, scoped["agent"] if explicit else "")


def _dispatch(
    method: str, path: str, params: dict[str, list[str]], root: str, explicit_agent: str = ""
) -> tuple[int, str, bytes]:
    if method not in ("GET", "HEAD"):
        return 405, "text/plain; charset=utf-8", b"method not allowed"
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", render_html().encode()
    if path == "/asset/logo":
        return 200, "image/png", (_files("asgard") / "assets" / "gold-brand-logo.png").read_bytes()
    if path == "/asset/mark":
        # 위그드라실 마크 — asgard map · memory가 쓰는 것과 같은 파일이라 세 창이 같은 마크를 쓴다
        return 200, "image/png", (_files("asgard") / "assets" / "yggdrasil-mark.png").read_bytes()
    if path in ("/asset/app-icon", "/favicon.ico"):
        # 네이티브 창의 앱 아이콘과 같은 그림 — 브라우저로 열어도 탭에 같은 얼굴이 뜬다
        return 200, "image/png", (_files("asgard") / "assets" / "app-icon.png").read_bytes()
    if path == "/api/snapshot":
        return _json_body(200, snapshot_data(root, explicit_agent))
    if path == "/api/runs":
        return _json_body(200, runs_state())
    if path == "/api/tasks":
        # 기본은 이 작업 공간. `?scope=all` 이면 프로젝트를 건너 하나의 목록으로 본다.
        if (params.get("scope") or [""])[0] == "all":
            return _json_body(200, _feed_snapshot(root))
        return _json_body(200, _task_snapshot(root))
    if path == "/api/projects":
        from .. import studio_store

        return _json_body(200, {"projects": studio_store.list_projects(root), "current": root})
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
    if path == "/api/provider":
        # 엔진은 **작업이 도는 자리**가 정한다. 창은 자기가 선 자리의 엔진을 상태 바에 적는데,
        # 독에서 다른 폴더를 골라 보내면 실제로 도는 것은 그 폴더의 엔진이다 — 설정이 없는
        # 폴더는 기본값으로 떨어져 키가 없다며 막힌다. 여태 그 갈림이 화면에 없어서, 초록으로
        # "로컬에서 실행"이라고 적힌 채 보내는 작업마다 죽었다. 자리를 주면 그 자리로 답한다.
        where, failed = _known_root(params, root)
        if failed:
            return _json_body(403, {"error": failed})
        return _json_body(200, _provider_state(where))
    if path == "/api/settings":
        return _json_body(200, settings_state(root))
    if path == "/api/catalog":
        return _json_body(200, _catalog_state(root))
    if path == "/api/tutor":
        # 되짚기 재료 — 물음·성장·부채·recap 네 갈래를 한 왕복으로. span 은 recap 서사의 폭이다.
        return _json_body(200, panel_state(root, (params.get("span") or [""])[0] or "day"))
    if path == "/api/orchestration":
        # 오케스트레이션 재료 — 정책과 엔진 준비 상태. 최초 렌더는 캐시만 읽는다(네트워크 안 탐).
        # 강제 재점검은 POST /api/orchestration/recheck 뿐이다 — GET 이 probe 를 돌면 창이 느려진다.
        return _json_body(200, orchestration_state(root))
    if path == "/api/k6":
        # 부하 재료 — 준비 상태·시나리오·기록·지금 도는 판. 부하는 안 건다(그건 POST 뿐이다).
        return _json_body(200, load_panel(root))
    if path == "/api/k6/live":
        # 도는 동안의 초 단위 기록을 커서부터. 끝난 실행도 같은 주소로 다시 읽힌다.
        return live_state(params, root)
    if path == "/api/agents":
        # 에이전트 재료 — 이 기계의 명부·내장 명부·이 프로젝트의 배치를 한 왕복으로.
        return _json_body(200, agents_state(root))
    if path == "/api/agent":
        # 하나의 상세 — 명부의 줄 + 정체성 원문 + 설정(자기 것·병합 뷰). 편집 화면이 읽는 자리다.
        return agent_detail((params.get("name") or [""])[0], root)
    if path == "/api/plans" or path.startswith("/api/plans/"):
        return _plan_dispatch(method, path, None, root)
    from .. import ticket_api

    if ticket_api.owns(path):
        return _ticket_dispatch(method, path, params, None, root)
    if path == "/health":
        return _json_body(200, {"ok": True, "surface": "studio"})
    return 404, "text/plain; charset=utf-8", b"not found"


def dispatch_post(
    path: str,
    payload: dict,
    root: str | None = None,
    params: dict[str, list[str]] | None = None,
) -> tuple[int, str, bytes]:
    root = current_root(root)
    explicit = ((params or {}).get("agent") or [""])[0]
    scoped, failed = request_scope(root, explicit)
    if scoped is None:
        return failed
    from ... import profiles

    with profiles.scoped(scoped["agent"]):
        return _dispatch_post(path, payload, root)


def _dispatch_post(path: str, payload: dict, root: str) -> tuple[int, str, bytes]:
    if path == "/api/plans" or path.startswith("/api/plans/"):
        return _plan_dispatch("POST", path, payload, root)
    from .. import ticket_api

    if path == "/api/tickets/run":
        return run_ticket(payload, root)
    # 부름은 실행이다 — 그래서 티켓 API(기록)가 아니라 여기(작업 계층)가 소유한다.
    if path == "/api/tickets/assign":
        return assign_ticket(payload, root)
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
        "/api/tutor/answer": lambda: answer_point(payload, root),
        "/api/tutor/dismiss": lambda: dismiss_point(payload, root),
        "/api/orchestration/policy": lambda: save_policy(payload, root),
        "/api/orchestration/recheck": lambda: recheck_engines(payload, root),
        # 에이전트 — 명부를 고치는 쓰기(create·use·describe·identity·config·rename·delete)와
        # 이 프로젝트의 배치를 고치는 쓰기(bind·unbind)가 한 묶음이다. 축이 둘이라는 사실은
        # 주소가 아니라 응답이 든다(`state.binding` 대 `state.agents`).
        "/api/agents/create": lambda: create_agent(payload, root),
        "/api/agents/use": lambda: use_agent(payload, root),
        "/api/agents/describe": lambda: describe_agent(payload, root),
        "/api/agents/identity": lambda: save_agent_identity(payload, root),
        "/api/agents/config": lambda: save_agent_config(payload, root),
        "/api/agents/rename": lambda: rename_agent(payload, root),
        "/api/agents/bind": lambda: bind_agent(payload, root),
        "/api/agents/unbind": lambda: unbind_agent(payload, root),
        "/api/agents/delete": lambda: delete_agent(payload, root),
        # 부하는 쓰기다 — 표적에 실제 트래픽을 건다. 그래서 GET 에는 한 줄도 두지 않는다.
        "/api/k6/run": lambda: start_run(payload, root),
        "/api/k6/stop": lambda: stop_run(payload),
        "/api/k6/selftest": lambda: start_selftest(payload, root),
        "/api/k6/probe": lambda: probe_target(payload),
    }
    route = routes.get(path)
    return route() if route else (404, "text/plain; charset=utf-8", b"not found")


def dispatch_put(
    path: str,
    payload: dict,
    root: str | None = None,
    params: dict[str, list[str]] | None = None,
) -> tuple[int, str, bytes]:
    root = current_root(root)
    explicit = ((params or {}).get("agent") or [""])[0]
    scoped, failed = request_scope(root, explicit)
    if scoped is None:
        return failed
    from ... import profiles

    with profiles.scoped(scoped["agent"]):
        return _dispatch_put(path, payload, root)


def _dispatch_put(path: str, payload: dict, root: str) -> tuple[int, str, bytes]:
    if path.startswith("/api/plans/"):
        return _plan_dispatch("PUT", path, payload, root)
    from .. import ticket_api

    if ticket_api.owns(path):
        return _ticket_dispatch("PUT", path, None, payload, root)
    return 404, "text/plain; charset=utf-8", b"not found"


def render_html() -> str:
    """창의 페이지 — 자립형 단일 파일이라 프로세스가 뜰 때 한 번 읽어 든다."""
    return _PAGE


_PAGE = (_files("asgard") / "assets" / "studio.html").read_text(encoding="utf-8")
