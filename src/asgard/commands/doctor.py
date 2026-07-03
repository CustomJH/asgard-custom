"""doctor — diagnose runtime & PATH, plus Trinity assets when run inside a scaffolded project
(CUS-125). Project checks are advisory (warn, never fatal) and appear only when AGENTS.md exists —
a global `asgard doctor` outside any project stays exactly as before."""

import json as _json
import os
import sys

from .. import __version__, ui
from ..platform import on_path


def _trinity_checks(root: str) -> list[dict]:
    """Trinity 에셋 진단 — AGENTS.md 가 있는 프로젝트에서만. 각 항목의 fix 는 전부 동일한 처방
    (setup --force 재실행)이라 개별 복구 절차를 안내하지 않는다."""
    if not os.path.exists(os.path.join(root, "AGENTS.md")):
        return []
    fix = "asgard setup --force 로 Trinity 에셋 재설치"
    checks = []
    try:
        txt = open(os.path.join(root, "AGENTS.md"), encoding="utf-8").read()
    except Exception:
        txt = ""
    checks.append({"name": "trinity block (AGENTS.md)", "ok": "asgard:trinity" in txt,
                   "detail": "marker found" if "asgard:trinity" in txt else "missing", "fix": fix})
    pol = os.path.join(root, ".asgard", "trinity-policy.json")
    pol_ok, detail = False, "missing"
    try:
        _json.load(open(pol))
        pol_ok, detail = True, pol
    except FileNotFoundError:
        pass
    except Exception:
        detail = "unparseable JSON"
    checks.append({"name": "trinity-policy.json", "ok": pol_ok, "detail": detail, "fix": fix})
    agents = ["asgard-thinker.md", "asgard-worker.md", "asgard-verifier.md"]
    missing = [a for a in agents if not os.path.exists(os.path.join(root, ".claude", "agents", a))]
    checks.append({"name": "trinity role agents", "ok": not missing,
                   "detail": "3/3 present" if not missing else "missing: " + ", ".join(missing), "fix": fix})
    hooks = ["quest-log.py", "verifier-gate.py", "write-sentinel.py"]
    missing = [h for h in hooks if not os.path.exists(os.path.join(root, ".claude", "hooks", h))]
    gate_wired = False
    try:
        settings = _json.load(open(os.path.join(root, ".claude", "settings.json")))
        gate_wired = "verifier-gate" in _json.dumps(settings.get("hooks", {}).get("Stop", []))
    except Exception:
        pass
    ok = not missing and gate_wired
    checks.append({"name": "trinity hooks + Stop gate", "ok": ok,
                   "detail": "wired" if ok else ("missing: " + ", ".join(missing) if missing else "Stop hook not wired"),
                   "fix": fix})
    ledger_ok = os.access(root, os.W_OK)
    checks.append({"name": ".asgard quest-log writable", "ok": ledger_ok,
                   "detail": os.path.join(root, ".asgard") if ledger_ok else "not writable",
                   "fix": "프로젝트 루트 쓰기 권한 확인"})
    return checks


def run_doctor(json_out: bool = False, quiet: bool = False) -> int:
    asgard = on_path("asgard")
    py = on_path("python3")
    checks = [
        {"name": "asgard on PATH", "ok": bool(asgard), "detail": asgard or "not found",
         "fix": 'add the install dir to PATH, e.g. export PATH="$HOME/.local/bin:$PATH"'},
        {"name": "python3 (hooks)", "ok": bool(py), "detail": py or "not found",
         "fix": "Canon hooks run via python3 — https://www.python.org/downloads/"},
    ]
    checks += _trinity_checks(os.getcwd())
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
            sys.stdout.write(f"      {ui.paint(ui._INFO, '→')} {ch['fix']}\n")
    if not quiet:
        ui.done() if ok else ui.warn("asgard not on PATH — see fix above.")
    return 0 if ok else 1
