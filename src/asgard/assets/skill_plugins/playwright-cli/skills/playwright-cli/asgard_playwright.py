#!/usr/bin/env python3
"""Run the pinned Playwright agent CLI with one session per project."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE = "@playwright/cli@0.1.17"
GLOBAL = {"install", "install-browser", "list", "close-all", "kill-all", "show"}


def main(argv: list[str]) -> int:
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv:
        argv = ["--help"]
    npx = shutil.which("npx")
    if not npx:
        print("Node.js 18+ with npx is required for browser use", file=sys.stderr)
        return 2
    if argv[0] == "open" and not any(arg.startswith("--browser") for arg in argv[1:]):
        argv.append("--browser=chromium")
    command = [npx, "--yes", PACKAGE]
    if argv[0] not in GLOBAL and not argv[0].startswith("-"):
        digest = hashlib.sha256(str(Path.cwd().resolve()).encode()).hexdigest()[:12]
        command.append(f"-s=asgard-{digest}")
    return subprocess.run([*command, *argv], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
