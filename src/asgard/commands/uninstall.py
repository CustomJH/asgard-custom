"""uninstall — remove asgard (it's a uv tool). `uv tool uninstall asgard` removes the
managed env + the `asgard` shim. Preview unless --yes."""

import os
import subprocess
import sys

from .. import ui
from ..platform import on_path


def _installed() -> bool:
    # FORCE_COLOR 류가 켜진 셸에선 uv 가 파이프에도 ANSI 코드를 실어 첫 토큰이
    # "\x1b[1masgard" 가 된다 — 설치돼 있는데 미설치로 오판해 uninstall 이 무동작 (macOS 실측).
    env: dict[str, str] = {**os.environ, "NO_COLOR": "1"}
    env.pop("FORCE_COLOR", None)
    try:
        out = subprocess.run(["uv", "tool", "list"], capture_output=True, text=True, env=env).stdout
    except OSError:
        return False
    return any(line.split(" ", 1)[0] == "asgard" for line in out.splitlines())


def run_uninstall(yes: bool = False, dry_run: bool = False) -> int:
    ui.head("uninstall", steps=1)
    if not on_path("uv") or not _installed():
        ui.warn("asgard not installed as a uv tool here.")
        return 0

    if dry_run or not yes:
        ui.phase("preview")
        ui.step("would run: uv tool uninstall asgard")
        sys.stdout.write("\n  " + ui.dim("run 'asgard uninstall --yes' to remove.") + "\n")
        return 0

    ui.phase("remove uv tool")
    with ui.spin("uninstalling asgard…"):
        result = subprocess.run(["uv", "tool", "uninstall", "asgard"], capture_output=True, text=True)
    if result.returncode == 0:
        ui.done("asgard removed")
        return 0
    ui.warn("uninstall incomplete.")
    return 1
