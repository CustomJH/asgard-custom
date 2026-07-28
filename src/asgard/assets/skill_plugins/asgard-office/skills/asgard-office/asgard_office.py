#!/usr/bin/env python3
"""Asgard Office (Sága) — one verb surface over the document lanes.

    asgard skills run asgard-office -- <verb> ...

    build docx|pptx|xlsx SPEC -o OUT   spec to document
    read FILE                          document to Markdown or JSON
    verify FILE                        static delivery gate
    fill FILE --values V -o OUT        fill {{placeholders}} in someone else's file
    template ...                       the user-composable template registry
    outline [GENRE]                    genre skeletons
    render FILE                        PDF and page images (needs LibreOffice)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"

VERBS = {
    "read": "extract",
    "extract": "extract",
    "verify": "verify",
    "check": "verify",
    "fill": "fill",
    "template": "template",
    "templates": "template",
    "outline": "outline",
    "genres": "outline",
    "render": "render",
}
BUILDERS = {"docx": "build_docx", "pptx": "build_pptx", "xlsx": "build_xlsx"}

USAGE = __doc__.strip()


def _run(script: str, args: list[str]) -> int:
    path = SCRIPTS / f"{script}.py"
    if not path.is_file():
        print(f"unknown office utility: {script}", file=sys.stderr)
        return 2
    return subprocess.run([sys.executable, str(path), *args], check=False).returncode


def main(argv: list[str]) -> int:
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(USAGE)
        return 0
    verb, args = argv[0], argv[1:]
    if verb == "build":
        if not args or args[0] not in BUILDERS:
            print(f"build needs a lane: {', '.join(BUILDERS)}", file=sys.stderr)
            return 2
        return _run(BUILDERS[args[0]], args[1:])
    if verb == "genres":
        return _run("outline", args or [])
    if verb in VERBS:
        return _run(VERBS[verb], args)
    if verb == "script" and args:  # escape hatch: run a lane script directly
        return _run(args[0], args[1:])
    print(f"unknown verb {verb!r}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
