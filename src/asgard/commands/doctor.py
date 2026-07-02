"""doctor — diagnose runtime & PATH. Canon hooks now run via python3 (was node), so the advisory
checks python3 instead of node."""

import json as _json
import sys

from .. import __version__, ui
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
        ui.head(f"doctor · v{__version__} {ui.dim('(' + runtime + ')')}")
    for ch in checks:
        mark = ui.paint("32", "✔") if ch["ok"] else ui.paint("33", "⚠")
        sys.stdout.write(f"  {mark} {ch['name'].ljust(22)} {ui.dim(ch['detail'])}\n")
        if not ch["ok"]:
            sys.stdout.write(f"      {ui.paint('36', '→')} {ch['fix']}\n")
    if not quiet:
        ui.done() if ok else ui.warn("asgard not on PATH — see fix above.")
    return 0 if ok else 1
