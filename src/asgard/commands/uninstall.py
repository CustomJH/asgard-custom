"""uninstall — remove asgard (CUS-108 Path B: it's a uv tool). `uv tool uninstall asgard` removes the
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
    ui.head("uninstall")
    if not on_path("uv") or not _installed():
        ui.warn("asgard not installed as a uv tool here.")
        return 0

    if dry_run or not yes:
        ui.step("would run: uv tool uninstall asgard")
        hint = "run 'asgard uninstall --yes' to remove."
        sys.stdout.write(f"\n  {ui.dim(hint)}\n")
        return 0

    result = subprocess.run(["uv", "tool", "uninstall", "asgard"])
    if result.returncode == 0:
        sys.stdout.write(f"\n  {ui.paint('32', '✔')} asgard removed.\n")
        return 0
    sys.stdout.write(f"\n  {ui.paint('33', '!')} uninstall incomplete.\n")
    return 1
