"""Host probing — PATH lookups and the release-asset name for this OS/arch."""

import platform as _platform
import shutil
import sys


def on_path(binary: str) -> str | None:
    return shutil.which(binary)


def release_asset() -> str:
    os_name = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform, "")
    machine = _platform.machine().lower()
    arch = "x64" if machine in ("x86_64", "amd64") else "arm64" if machine in ("arm64", "aarch64") else ""
    if not os_name or not arch:
        raise RuntimeError(f"unsupported platform {sys.platform}/{_platform.machine()}")
    return f"asgard-{os_name}-{arch}" + (".exe" if os_name == "windows" else "")
