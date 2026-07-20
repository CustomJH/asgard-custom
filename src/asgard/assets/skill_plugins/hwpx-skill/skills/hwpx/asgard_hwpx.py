#!/usr/bin/env python3
"""Thin Asgard dispatcher for the vendored hwpx skill."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
EXCLUDED = {"gyehoek_hook", "hwpx_guard_hook", "report_placeholder_hook"}


def _run(script: str, args: list[str]) -> int:
    path = SCRIPTS / f"{script}.py"
    if script in EXCLUDED or not path.is_file():
        print(f"unknown hwpx utility: {script}", file=sys.stderr)
        return 2
    return subprocess.run([sys.executable, str(path), *args], check=False).returncode


def main(argv: list[str]) -> int:
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: asgard skills run hwpx -- extract FILE [ARGS] | convert ARGS | script NAME ARGS")
        return 0
    command, args = argv[0], argv[1:]
    if command == "convert":
        return _run("convert_hwp", args)
    if command == "script" and args:
        return _run(args[0], args[1:])
    if command != "extract" or not args:
        print("expected extract FILE, convert, or script NAME", file=sys.stderr)
        return 2

    source = Path(args[0])
    extract_args = args if any(arg in {"--format", "-f"} for arg in args) else [*args, "--format", "markdown"]
    if source.suffix.lower() != ".hwp":
        return _run("text_extract", extract_args)
    with tempfile.TemporaryDirectory(prefix="asgard-hwp-read-") as temp:
        converted = Path(temp) / f"{source.stem}.hwpx"
        code = _run("convert_hwp", [str(source), "-o", str(converted)])
        return code or _run("text_extract", [str(converted), *extract_args[1:]])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
