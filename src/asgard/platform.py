"""Host probing — PATH lookups and the release-asset name for this OS/arch."""

import platform as _platform
import shutil
import sys


def on_path(binary: str) -> str | None:
    return shutil.which(binary)


def hook_python() -> str:
    """훅 배선용 파이썬 명령 — POSIX 는 python3, Windows 는 python3 실행 파일이 없는 게
    보통이라 python → py 런처 순으로 탐지 (스캐폴드는 타깃 머신에서 실행되므로 생성 시점 감지)."""
    if sys.platform != "win32":
        return "python3"
    return next((c for c in ("python", "py") if shutil.which(c)), "python")


def release_asset() -> str:
    os_name = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform, "")
    machine = _platform.machine().lower()
    arch = "x64" if machine in ("x86_64", "amd64") else "arm64" if machine in ("arm64", "aarch64") else ""
    if not os_name or not arch:
        raise RuntimeError(f"unsupported platform {sys.platform}/{_platform.machine()}")
    return f"asgard-{os_name}-{arch}" + (".exe" if os_name == "windows" else "")
