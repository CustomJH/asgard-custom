"""uninstall — remove asgard (it's a uv tool). `uv tool uninstall asgard` removes the
managed env + the `asgard` shim. Preview unless --yes."""

import subprocess
import sys

from .. import ui
from ..platform import on_path


def _installed() -> bool:
    try:
        out = subprocess.run(["uv", "tool", "list"], capture_output=True, text=True).stdout
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
