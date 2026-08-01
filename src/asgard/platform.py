"""Host probing — PATH lookups and the release-asset name for this OS/arch."""

import os
import platform as _platform
import shutil
import sys

# 창을 독에서 누르면 그 프로세스의 PATH는 셸의 것이 아니라 launchd/Explorer의 것이다 —
# macOS에서는 `/usr/bin:/bin:/usr/sbin:/sbin` 넉 줄이 전부다. 그 안에는 `claude`도
# `codex`도 없다. 그래서 터미널에서는 되던 일이 창에서는 **엔진이 없다**며 통째로 막혔다.
# (Tauri 셸이 `asgard` 실행 파일을 PATH 없이 후보 목록으로 찾는 것과 같은 이유다 —
#  그 셸은 자기 것만 찾았고, 자식이 찾아야 할 엔진은 아무도 안 챙겼다.)
#
# 여기서 하는 일은 **되찾기지 덮어쓰기가 아니다**: 있는 자리만, 이미 없는 것만, 뒤에 붙인다.
# 사용자가 정한 순서는 그대로 우선한다.
_USER_BIN_DIRS = (
    "~/.local/bin",
    "~/.local/share/mise/shims",
    "~/.bun/bin",
    "~/.volta/bin",
    "~/.npm-global/bin",
    "~/.yarn/bin",
    "~/Library/pnpm",
    "~/.asdf/shims",
    "~/.nix-profile/bin",
    "~/bin",
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
)
_WINDOWS_BIN_DIRS = (
    r"%LOCALAPPDATA%\Programs",
    r"%LOCALAPPDATA%\Microsoft\WindowsApps",
    r"%APPDATA%\npm",
    r"%USERPROFILE%\.local\bin",
    r"%USERPROFILE%\.bun\bin",
)


def user_bin_dirs() -> list[str]:
    """이 기계에서 사용자 도구가 실제로 있는 자리 — 존재하는 것만."""
    raw = _WINDOWS_BIN_DIRS if sys.platform == "win32" else _USER_BIN_DIRS
    found = []
    for entry in raw:
        path = os.path.expandvars(os.path.expanduser(entry))
        if "%" not in path and os.path.isdir(path):
            found.append(os.path.normpath(path))
    return list(dict.fromkeys(found))


def ensure_user_path() -> list[str]:
    """빠진 사용자 bin 자리를 PATH 뒤에 되붙이고, 새로 붙인 것을 돌려준다.

    멱등이다 — 두 번 불러도 같은 자리를 두 번 붙이지 않는다. 자식 프로세스는
    `os.environ`을 물려받으므로, 창이 띄우는 `asgard run`도 같은 PATH로 선다."""
    current = os.environ.get("PATH", "")
    known = {os.path.normpath(p) for p in current.split(os.pathsep) if p}
    added = [d for d in user_bin_dirs() if d not in known]
    if added:
        os.environ["PATH"] = os.pathsep.join([current, *added]) if current else os.pathsep.join(added)
    return added


def on_path(binary: str) -> str | None:
    return shutil.which(binary)


def hook_python() -> str:
    """훅 배선용 파이썬 명령 — POSIX는 python3, Windows는 python3 실행 파일이 없는 게
    보통이라 python → py 런처 순으로 탐지 (스캐폴드는 타깃 머신에서 실행되므로 생성 시점 감지).
    어느 것도 PATH에 없으면 uv 관리 파이썬으로 폴백 — asgard 설치 자체가 uv를 전제하므로
    파이썬 없는 머신에서도 훅이 돈다 (--no-project: 훅은 stdlib-only, 프로젝트 동기화 불필요)."""
    names = ("python3",) if sys.platform != "win32" else ("python", "py")
    found = next((c for c in names if shutil.which(c)), None)
    if found:
        return found
    if shutil.which("uv"):
        return "uv run --no-project python"
    return names[0]


def release_asset() -> str:
    os_name = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform, "")
    machine = _platform.machine().lower()
    arch = "x64" if machine in ("x86_64", "amd64") else "arm64" if machine in ("arm64", "aarch64") else ""
    if not os_name or not arch:
        raise RuntimeError(f"unsupported platform {sys.platform}/{_platform.machine()}")
    return f"asgard-{os_name}-{arch}" + (".exe" if os_name == "windows" else "")
