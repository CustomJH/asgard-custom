"""doctor — diagnose runtime & PATH. Canon hooks now run via python3 (was node), so the advisory
checks python3 instead of node."""

import json as _json
import sys

from .. import __version__
from ..platform import on_path


def run_doctor(json_out: bool = False, quiet: bool = False) -> int:
    asgard = on_path("asgard")
    py = on_path("python3")
    checks = [
        {"name": "asgard on PATH", "ok": bool(asgard), "detail": asgard or "not found",
         "fix": 'add the install dir to PATH, e.g. export PATH="$HOME/.local/bin:$PATH"'},
        {"name": "python3 (hooks)", "ok": bool(py), "detail": py or "not found",
         "fix": "Canon hooks run via python3 — https://www.python.org/downloads/"},
    ]
    ok = bool(asgard)  # self-contained CLI; only PATH wiring is fatal here.
    runtime = f"python {sys.version.split()[0]}"

    if json_out:
        sys.stdout.write(_json.dumps({"version": __version__, "runtime": runtime, "ok": ok, "checks": checks}, indent=2) + "\n")
        return 0 if ok else 1
    if not quiet:
        sys.stdout.write(f"asgard doctor — v{__version__}  ({runtime})\n\n")
    for ch in checks:
        sys.stdout.write(f"  {'✔' if ch['ok'] else '⚠'} {ch['name'].ljust(22)} {ch['detail']}\n")
        if not ch["ok"]:
            sys.stdout.write(f"      → {ch['fix']}\n")
    if not quiet:
        sys.stdout.write("\n  ok.\n" if ok else "\n  ⚠ asgard not on PATH — see fix above.\n")
    return 0 if ok else 1
