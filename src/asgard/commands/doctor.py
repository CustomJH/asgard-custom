"""doctor — diagnose runtime & PATH, plus Trinity assets when run inside a scaffolded project
(CUS-125). Project checks are advisory (warn, never fatal) and appear only when AGENTS.md exists —
a global `asgard doctor` outside any project stays exactly as before."""

import json as _json
import os
import sys

from .. import __version__, ui
from ..platform import on_path
from ..templates.roles import ROLE_AGENTS


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
    checks.append(
        {
            "name": "trinity block (AGENTS.md)",
            "ok": "asgard:trinity" in txt,
            "detail": "marker found" if "asgard:trinity" in txt else "missing",
            "fix": fix,
        }
    )
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
    agents = [fname for fname, _ in ROLE_AGENTS]  # 역할 3종 + 딜리버리 계층 — 라이브러리가 소스
    missing = [a for a in agents if not os.path.exists(os.path.join(root, ".claude", "agents", a))]
    checks.append(
        {
            "name": "trinity role agents",
            "ok": not missing,
            "detail": f"{len(agents)}/{len(agents)} present" if not missing else "missing: " + ", ".join(missing),
            "fix": fix,
        }
    )
    hooks = [
        "quest-log.py",
        "verifier-gate.py",
        "write-sentinel.py",
        "unattended-context.py",
        "subagent-gate.py",
        "lagom-activate.py",
        "lagom-tracker.py",
        "lagom-subagent.py",
        "lagom-canon.md",
    ]
    missing = [h for h in hooks if not os.path.exists(os.path.join(root, ".claude", "hooks", h))]
    gate_wired = False
    try:
        settings = _json.load(open(os.path.join(root, ".claude", "settings.json")))
        gate_wired = "verifier-gate" in _json.dumps(settings.get("hooks", {}).get("Stop", [])) and "subagent-gate" in (
            _json.dumps(settings.get("hooks", {}).get("SubagentStop", []))
        )
    except Exception:
        pass
    ok = not missing and gate_wired
    checks.append(
        {
            "name": "trinity hooks + Stop gate",
            "ok": ok,
            "detail": "wired" if ok else ("missing: " + ", ".join(missing) if missing else "Stop/SubagentStop 미배선"),
            "fix": fix,
        }
    )
    # Lagom (CUS-207/215) — resolve 결과 + 세션 상태 표시. 정보성 (항상 ok — off 도 유효한 선택).
    try:
        from ..lagom import default_mode, read_state

        st = read_state(root)
        checks.append(
            {
                "name": "lagom mode",
                "ok": True,
                "detail": f"{st or default_mode(root)} ({'session' if st else 'default'})",
                "fix": "",
            }
        )
    except Exception:
        pass
    ledger_ok = os.access(root, os.W_OK)
    checks.append(
        {
            "name": ".asgard quest-log writable",
            "ok": ledger_ok,
            "detail": os.path.join(root, ".asgard") if ledger_ok else "not writable",
            "fix": "프로젝트 루트 쓰기 권한 확인",
        }
    )
    # classify 오분류율 (CUS-179) — misroute = DIRECT 분류인데 write 발생 (소급 검증됨). 기록 있을 때만.
    try:
        events = [
            _json.loads(ln)
            for ln in open(os.path.join(root, ".asgard", "classify.jsonl"), encoding="utf-8")
            if ln.strip()
        ]
        routes = sum(1 for e in events if e.get("event") == "route")
        misroutes = sum(1 for e in events if e.get("event") == "misroute")
        if routes:
            checks.append(
                {
                    "name": "classify misroute rate",
                    "ok": misroutes == 0,
                    "detail": f"{misroutes}/{routes} misroute ({misroutes / routes:.0%})",
                    "fix": "오분류 반복 시 classify 휴리스틱/프롬프트 보강 (.asgard/classify.jsonl 감사)",
                }
            )
    except Exception:
        pass
    # route prior (CUS-127) — task-class별 게이트-red 이력. 과반 red 클래스는 승격 문턱 1로 하향.
    try:
        classes = _json.load(open(os.path.join(root, ".asgard", "route-priors.json"))).get("classes") or {}
        if classes:
            hot = [
                c for c, v in classes.items() if int(v.get("red") or 0) > int(v.get("n") or 0) - int(v.get("red") or 0)
            ]
            detail = ", ".join(f"{c} {v.get('red', 0)}/{v.get('n', 0)} red" for c, v in sorted(classes.items()))
            checks.append(
                {
                    "name": "route priors (Bayesian-lite)",
                    "ok": not hot,
                    "detail": detail + (f" — 승격 문턱 1: {', '.join(hot)}" if hot else ""),
                    "fix": "과반-red 클래스는 red 1회에 Trinity 승격 — 반복되면 baseline_checks/과업 분할 점검",
                }
            )
    except Exception:
        pass
    return checks


def run_doctor(json_out: bool = False, quiet: bool = False) -> int:
    asgard = on_path("asgard")
    py = on_path("python3")
    checks: list[dict] = [
        {
            "name": "asgard on PATH",
            "ok": bool(asgard),
            "detail": asgard or "not found",
            "fix": 'add the install dir to PATH, e.g. export PATH="$HOME/.local/bin:$PATH"',
        },
        {
            "name": "python3 (hooks)",
            "ok": bool(py),
            "detail": py or "not found",
            "fix": "Canon hooks run via python3 — https://www.python.org/downloads/",
        },
    ]
    checks += _trinity_checks(os.getcwd())
    ok = bool(asgard)  # self-contained CLI; only PATH wiring is fatal here.
    runtime = f"python {sys.version.split()[0]}"

    if json_out:
        sys.stdout.write(
            _json.dumps({"version": __version__, "runtime": runtime, "ok": ok, "checks": checks}, indent=2) + "\n"
        )
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
