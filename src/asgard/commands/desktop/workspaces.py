"""작업 공간 — 목록에 더하고, 눈으로 찾고, 옮겨 선다.

경로는 사람이 외우는 것이 아니라 **찾아가는 것**이다. 그래서 길이 셋이고(시스템 대화상자·
창 안의 목록·붙여넣기) 셋 다 같은 문으로 들어간다.
"""

from __future__ import annotations

import os
import subprocess

from .. import loopback
from . import dialog, state
from .boundary import current_root, resolve_workspace
from .snapshot import snapshot_data
from .tasks import load_project_tasks

folder_dialog_available = dialog.folder_dialog_available
_folder_dialog_command = dialog._folder_dialog_command

_json_body = loopback.json_body


# ── 프로젝트 전환 ──────────────────────────────────────────────────────────────


def use_project(payload: dict) -> tuple[int, str, bytes]:
    """창이 보는 작업 공간을 바꾼다. 실행 중인 작업은 그 자리에 그대로 둔다 — 경계를 옮긴다고
    남의 프로세스를 죽이지 않는다. 새 경계의 이력은 이때 디스크에서 올라온다."""
    from .. import desktop_store

    wanted = str(payload.get("root") or "").strip()
    if not wanted:
        return _json_body(400, {"error": "존재하는 디렉터리 경로가 필요합니다"})
    target, failed = resolve_workspace(wanted, "")
    if failed or not target:
        return _json_body(400, {"error": failed or "존재하는 디렉터리 경로가 필요합니다"})
    # 되돌아 읽는 쪽(`boundary.current_root`)이 보는 것은 `state`의 값이다. 여기서 `global`
    # 로 선언하면 이 모듈에 같은 이름의 전역이 하나 더 생길 뿐 아무도 그걸 안 본다.
    with state._ROOT_LOCK:
        state._CURRENT_ROOT = target
    if state._SERVER is not None:  # 이후 요청은 핸들러가 서버의 root를 넘긴다 — 거기를 바꿔야 실제로 옮겨진다
        state._SERVER.root = target
    desktop_store.touch_project(target)
    load_project_tasks(target)
    return _json_body(200, {"root": target, "snapshot": snapshot_data(target)})


def add_project(payload: dict) -> tuple[int, str, bytes]:
    from .. import desktop_store

    try:
        added = desktop_store.add_project(str(payload.get("root") or ""))
    except ValueError as exc:
        return _json_body(400, {"error": str(exc)})
    return _json_body(200, {"added": added, "projects": desktop_store.list_projects(current_root())})


def browse_projects(payload: dict, root: str | None = None) -> tuple[int, str, bytes]:
    """`POST /api/projects/browse` — 작업 공간을 고르러 폴더를 열어 본다.

    시작 자리는 사용자가 준 곳, 없으면 지금 보고 있는 자리의 **부모**다. 지금 자리를 열면
    "여기 아래에서 고르라"가 되는데, 형제 폴더를 더하는 것이 훨씬 흔하다."""
    from .. import desktop_store

    where = str(payload.get("path") or "").strip()
    if not where:
        here = current_root(root)
        parent = os.path.dirname(here)
        where = parent if parent and os.path.isdir(parent) and not desktop_store.is_scratch(here) else ""
    try:
        return _json_body(200, desktop_store.browse(where, show_hidden=bool(payload.get("hidden"))))
    except ValueError as exc:
        return _json_body(400, {"error": str(exc)})


# 시스템 폴더 고르기 — 창 안의 목록보다 손에 익은 길이다. 없는 기계도 있으므로 있을 때만
# 문을 연다: 화면은 `snapshot.capabilities.folder_dialog`를 보고 단추를 세운다.


def pick_folder(payload: dict) -> tuple[int, str, bytes]:
    """`POST /api/projects/pick` — 운영체제의 폴더 고르기를 연다.

    취소는 실패가 아니다 — 아무것도 안 고른 것이라 `{"path": ""}`로 조용히 돌아간다.
    화면이 이것을 오류로 띄우면 사용자는 취소할 때마다 빨간 말을 본다."""
    command = _folder_dialog_command()
    if not command:
        return _json_body(501, {"error": "이 기계에는 폴더 고르기 대화상자가 없습니다"})
    try:
        # 인코딩을 안 주면 호스트 로케일이 정한다 — 한국어 Windows(cp949)에서 폴더 이름이
        # 깨져 돌아오고, 그 경로는 존재하지 않는 폴더가 된다. 이 저장소의 텍스트 IO 규약대로 못박는다.
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return _json_body(504, {"error": "폴더 고르기가 너무 오래 열려 있었습니다"})
    except OSError as exc:
        return _json_body(500, {"error": f"폴더 고르기를 열지 못했습니다: {exc}"})
    path = result.stdout.strip()
    if result.returncode != 0 or not path:
        return _json_body(200, {"path": ""})  # 취소
    return _json_body(200, {"path": os.path.abspath(os.path.expanduser(path))})


def forget_project(payload: dict) -> tuple[int, str, bytes]:
    """목록에서만 뺀다. 현재 보고 있는 프로젝트는 뺄 수 없다 — 발밑을 지울 수는 없다."""
    from .. import desktop_store

    target = os.path.abspath(os.path.expanduser(str(payload.get("root") or "").strip()))
    if target == current_root():
        return _json_body(409, {"error": "현재 열려 있는 프로젝트는 목록에서 뺄 수 없습니다"})
    removed = desktop_store.remove_project(target)
    return _json_body(200, {"removed": removed, "projects": desktop_store.list_projects(current_root())})


def prune_projects(payload: dict) -> tuple[int, str, bytes]:
    """자리에 없는 등록을 한 번에 걷어낸다 — 디스크는 건드리지 않는다."""
    from .. import desktop_store

    removed = desktop_store.prune_projects(current_root())
    return _json_body(200, {"removed": removed, "projects": desktop_store.list_projects(current_root())})
