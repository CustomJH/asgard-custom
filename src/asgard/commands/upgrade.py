"""upgrade — self-update via uv (CUS-108 Path B). asgard ships as a `uv tool`, so upgrading is
re-installing the latest (or a pinned) version. Requires uv on PATH (the installer bootstraps it)."""

import subprocess
import sys

from .. import ui
from ..platform import on_path


def run_upgrade(rest: list[str], dry_run: bool = False) -> int:
    pin = rest[0] if rest else None
    version = pin[1:] if pin and pin.startswith("v") else pin
    spec = f"asgard@{version}" if version else "asgard@latest"

    ui.head("upgrade")
    if dry_run:
        ui.step(f"would install {ui.dim(spec)} via uv tool")
        return 0
    if not on_path("uv"):
        ui.fail("uv not found — install it first: https://astral.sh/uv")
        return 1
    ui.step(f"installing {ui.bold(spec)} via uv tool")
    result = subprocess.run(["uv", "tool", "install", "--force", "--python", "3.14", spec])
    if result.returncode != 0:
        ui.fail(f"upgrade failed (uv exited {result.returncode})")
        return 1
    ui.ok(f"upgraded → {ui.bold(spec)}")
    return 0
