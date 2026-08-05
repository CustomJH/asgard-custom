"""Asgard Studio — 작업·산출물·설정을 한 화면에 모으는 로컬 창.

창은 기존 소유권 위에 얇게 얹힌다: 설정은 `settings.py`가, 실행은 `asgard run`이,
스킬 목록은 중앙 레지스트리가 이미 소유하고 있다. 이 패키지는 그것들을 **한 화면으로
모으는 일**만 한다.

여태 이 전부가 파일 하나(1,586줄·최상위 정의 67개)였다. 한 파일이 여덟 가지 일을 지면
고칠 때마다 나머지 일곱을 읽어야 하고, 어디까지가 한 책임인지 아무도 못 말한다. 지금은
아래로만 기대는 한 줄 순서다 — 위 모듈은 아래를 부르고, 아래는 위를 모른다:

    state       변하는 값 전량 (자리·작업·서버 핸들·상한)
    boundary    자리 규칙 — 지금 어디인가, 이 작업은 어디서 도는가, 경로를 어디에 가두는가
    tasks       작업의 수명 — 만들고 돌리고 이어 가고 멈춘다
    snapshot    화면이 한 왕복에 받는 것
    workspaces  작업 공간 등록·찾아보기          artifacts  산출물·diff·폴더 열기
    config      설정·스킬·역할 쓰기
    routes      경로표 (규칙 없음)
    server      소켓·핸들러·네이티브 셸

밖에서 부르는 이름은 여기서만 고정한다. 안에서 자리를 옮겨도 `cli`·`plan_api`·
테스트가 부르던 이름은 그대로다.

주의 — 변하는 값은 `state`가 소유한다. 밖에서 되돌릴 때는
`studio.state._CURRENT_ROOT`처럼 **소유한 모듈**을 짚어야 한다. 여기 재수출된 이름에 대입하면 패키지 이름표만 바뀌고
실제로 읽는 쪽은 옛 값을 계속 든다.
"""

from __future__ import annotations

import signal  # noqa: F401  (계약 재수출 — 창을 멈추는 신호를 밖에서 이 이름으로 짚는다)

from .. import loopback
from . import artifacts, boundary, config, routes, server, snapshot, state, tasks, workspaces
from .artifacts import read_artifact, read_diff, reveal_path
from .boundary import (
    _confine,
    _known_root,
    current_root,
    resolve_start_root,
    resolve_workspace,
    task_root,
    workspace_label,
)
from .config import save_role, save_settings, save_skill
from .routes import dispatch, dispatch_post, dispatch_put
from .server import (
    _bind,
    _Handler,
    _native_candidates,
    _open_native,
    _RootServer,
    install_shell,
    render_html,
    run_studio,
)
from .snapshot import settings_state, snapshot_data
from .state import _ARTIFACT_CAP, _LOADED_ROOTS, _ROOT_LOCK, _SETTING_KEYS, _TASK_LOCK, _TASKS
from .tasks import (
    _changed_by_task,
    _compose,
    _feed_snapshot,
    _public_task,
    _run_task,
    _settle_ticket,
    _start,
    _task_snapshot,
    _workspace_files,
    approve_task,
    create_task,
    follow_task,
    load_project_tasks,
    pause_task,
    resume_task,
    run_ticket,
    stop_task,
)
from .workspaces import (
    _folder_dialog_command,
    add_project,
    browse_projects,
    folder_dialog_available,
    forget_project,
    pick_folder,
    prune_projects,
    use_project,
)

# 루프백 경계는 세 창이 한 곳을 같이 쓴다 (`commands.loopback`)
host_allowed = loopback.host_allowed
origin_allowed = loopback.origin_allowed
_json_body = loopback.json_body
_LOOPBACK_HOSTS = loopback.LOOPBACK_HOSTS

__all__ = [
    "_ARTIFACT_CAP",
    "_LOADED_ROOTS",
    "_LOOPBACK_HOSTS",
    "_ROOT_LOCK",
    "_SETTING_KEYS",
    "_TASKS",
    "_TASK_LOCK",
    "_Handler",
    "_RootServer",
    "_bind",
    "_changed_by_task",
    "_compose",
    "_confine",
    "_feed_snapshot",
    "_folder_dialog_command",
    "_json_body",
    "_known_root",
    "_native_candidates",
    "_open_native",
    "_public_task",
    "_run_task",
    "_settle_ticket",
    "_start",
    "_task_snapshot",
    "_workspace_files",
    "add_project",
    "approve_task",
    "artifacts",
    "boundary",
    "browse_projects",
    "config",
    "create_task",
    "current_root",
    "dispatch",
    "dispatch_post",
    "dispatch_put",
    "folder_dialog_available",
    "follow_task",
    "forget_project",
    "host_allowed",
    "install_shell",
    "load_project_tasks",
    "origin_allowed",
    "pause_task",
    "pick_folder",
    "prune_projects",
    "read_artifact",
    "read_diff",
    "render_html",
    "resolve_start_root",
    "resolve_workspace",
    "resume_task",
    "reveal_path",
    "routes",
    "run_studio",
    "run_ticket",
    "save_role",
    "save_settings",
    "save_skill",
    "server",
    "settings_state",
    "signal",
    "snapshot",
    "snapshot_data",
    "state",
    "stop_task",
    "task_root",
    "tasks",
    "use_project",
    "workspace_label",
    "workspaces",
]
