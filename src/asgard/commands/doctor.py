"""doctor — diagnose runtime & PATH, plus Trinity assets when run inside a scaffolded project.
Project checks are advisory (warn, never fatal) and appear only when AGENTS.md exists —
a global `asgard doctor` outside any project stays exactly as before."""

import json as _json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .. import __version__, ui
from ..platform import hook_python, on_path
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
    pol_ok, detail = False, "missing"
    try:  # 통합 설정(trinity_policy 섹션) 우선, 구 trinity-policy.json 폴백 (settings.load_project)
        from ..settings import load_project

        if isinstance(load_project(root).get("trinity_policy"), dict):
            pol_ok, detail = True, "asgard-setting-project.json (trinity_policy)"
    except Exception:
        detail = "unparseable settings"
    checks.append({"name": "trinity policy", "ok": pol_ok, "detail": detail, "fix": fix})
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
    # Lagom — resolve 결과 + 세션 상태 표시. 정보성 (항상 ok — off 도 유효한 선택).
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
    # Memory v3 — CC 배선(훅 + snapshot/recall + 사용 skill) 단선 탐지.
    # .claude 가 있는 프로젝트만 — 배선 자체가 CC 스캐폴드 소속. 개인 위키 건강은 memory lint 몫.
    if os.path.isdir(os.path.join(root, ".claude")):
        hook_ok = os.path.exists(os.path.join(root, ".claude", "hooks", "memory-activate.py"))
        snapshot_wired = recall_wired = False
        skill_ok = os.path.exists(os.path.join(root, ".claude", "skills", "asgard-memory", "SKILL.md"))
        try:
            settings = _json.load(open(os.path.join(root, ".claude", "settings.json")))
            hooks = settings.get("hooks", {})
            snapshot_wired = "memory-activate" in _json.dumps(hooks.get("SessionStart", []))
            recall_wired = "memory-activate" in _json.dumps(hooks.get("UserPromptSubmit", []))
        except Exception:
            pass
        ok = hook_ok and snapshot_wired and recall_wired and skill_ok
        missing = []
        if not hook_ok:
            missing.append("hook file")
        if not snapshot_wired:
            missing.append("SessionStart")
        if not recall_wired:
            missing.append("UserPromptSubmit")
        if not skill_ok:
            missing.append("asgard-memory skill")
        checks.append(
            {
                "name": "memory wiring (CC)",
                "ok": ok,
                "detail": "wired" if ok else "missing: " + ", ".join(missing),
                "fix": fix,
            }
        )
    # 선택형 공유 메모리 backend — 설정된 프로젝트만, readiness/capability advisory.
    try:
        from ..memory_bridge import find_config, is_backend_trusted, verify_backend_binding
        from ..project_memory_backends import get_backend

        found = find_config(root)
        if found:
            _, mcfg = found
            try:
                if not is_backend_trusted(mcfg):
                    raise PermissionError("untrusted backend target; run asgard memory connect")
                backend = get_backend(mcfg)
                try:
                    binding = verify_backend_binding(mcfg, backend=backend)
                    readiness = backend.readiness()
                    enabled = [name for name, supported in asdict(backend.capabilities()).items() if supported]
                finally:
                    backend.close()
                detail = (
                    f"engine={backend.engine} · project_id={backend.project_id} · {readiness.status}"
                    + f" · binding={binding.binding_id[:8]} · project_uid={binding.project_uid[:8]}"
                    + (f" · capabilities={','.join(enabled)}" if enabled else "")
                    + (f" · {readiness.detail}" if readiness.detail else "")
                )
                ok = readiness.status == "ready"
            except Exception as exc:
                detail = f"engine={mcfg.get('engine', 'hindsight')} · unavailable · {type(exc).__name__}: {exc}"
                ok = False
            checks.append(
                {
                    "name": "shared memory backend",
                    "ok": ok,
                    "detail": detail,
                    "fix": ""
                    if ok
                    else "backend/plugin 설치·기동·인증 확인 또는 asgard memory connect 재설정",
                }
            )
    except Exception:
        pass
    # 코드베이스 지도 — 유령 엔트리(디스크에 없는 경로) 탐지 (지도 문법 3: 실재만 기재).
    # INDEX.md 는 규칙 문서(예시 엔트리 포함)라 제외. 영역 파일이 아직 없는 건 정상 (fog-of-war).
    from ..code_map import MapError, check_map

    mdir = os.path.join(root, ".asgard", "map")
    map_components = (Path(root, ".asgard"), Path(mdir))
    unsafe_component = next(
        (p for p in map_components if p.is_symlink() or bool(getattr(p, "is_junction", lambda: False)())),
        None,
    )
    if unsafe_component is not None:
        checks.append(
            {
                "name": "codebase map",
                "ok": False,
                "detail": f"unsafe managed map path: symlink/junction: {unsafe_component}",
                "fix": "symlink/junction 제거 후 asgard setup map 실행",
            }
        )
    elif not os.path.isdir(mdir):
        checks.append(
            {
                "name": "codebase map",
                "ok": False,
                "detail": "missing .asgard/map/",
                "fix": "asgard sync (또는 setup --force) 로 지도 시드 생성",
            }
        )
    else:
        import re as _re

        entry_pat = _re.compile(r"^- `([^`]+)`", _re.M)
        ghosts: list[str] = []
        unsafe: list[str] = []
        entries = 0
        areas = sorted(f for f in os.listdir(mdir) if f.endswith(".md") and f not in ("INDEX.md", "PROJECT.md"))
        for fname in areas:
            area_path = Path(mdir, fname)
            if area_path.is_symlink() or bool(getattr(area_path, "is_junction", lambda: False)()):
                unsafe.append(f"{fname}: symlink/junction")
                continue
            try:
                body = area_path.read_text(encoding="utf-8")
            except Exception:
                continue
            for m in entry_pat.finditer(body):
                entries += 1
                entry = m.group(1).rstrip("/")
                candidate = Path(root, entry)
                try:
                    candidate.resolve(strict=False).relative_to(Path(root).resolve())
                except ValueError:
                    unsafe.append(f"{fname}: {m.group(1)}")
                    continue
                if os.path.isabs(entry) or not candidate.exists():
                    if os.path.isabs(entry):
                        unsafe.append(f"{fname}: {m.group(1)}")
                    else:
                        ghosts.append(f"{fname}: {m.group(1)}")
        try:
            managed = check_map(root)
        except MapError as exc:
            checks.append(
                {
                    "name": "codebase map",
                    "ok": False,
                    "detail": f"unsafe managed map path: {exc}",
                    "fix": "symlink/junction 제거 후 asgard setup map 실행",
                }
            )
            managed = None
        if managed is None:
            pass
        else:
            checks.append(
                {
                    "name": "codebase map",
                    "ok": not ghosts and not unsafe and managed.ok,
                    "detail": (
                        f"{len(areas)} manual area(s) · {entries} entries · managed current"
                        if managed.ok
                        else (
                            "PROJECT.md ownership marker missing"
                            if not managed.owned
                            else (
                                "INDEX.md drift"
                                if not managed.index_current
                                else (
                                    "managed map is git-ignored — not shareable"
                                    if not managed.trackable
                                    else f"managed drift: +{len(managed.added)} -{len(managed.removed)}"
                                )
                            )
                        )
                    )
                    if not ghosts and not unsafe
                    else (
                        "unsafe: " + ", ".join(unsafe[:5])
                        if unsafe
                        else "ghost: " + ", ".join(ghosts[:5]) + (f" (+{len(ghosts) - 5})" if len(ghosts) > 5 else "")
                    ),
                    "fix": "asgard setup map 실행; 수동 영역의 유령 경로는 제거 (.asgard/map/INDEX.md)",
                }
            )
    ledger_ok = os.access(root, os.W_OK)
    checks.append(
        {
            "name": ".asgard quest-log writable",
            "ok": ledger_ok,
            "detail": os.path.join(root, ".asgard") if ledger_ok else "not writable",
            "fix": "프로젝트 루트 쓰기 권한 확인",
        }
    )
    # classify 오분류율 — misroute = DIRECT 분류인데 write 발생 (소급 검증됨). 기록 있을 때만.
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
    # route prior (Bayesian-lite) — task-class별 게이트-red 이력. 과반 red 클래스는 승격 문턱 1로 하향.
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
    py_cmd = hook_python()  # Windows 는 python3 가 PATH 에 없는 게 정상 (python/py 런처)
    py = on_path(py_cmd.split()[0])  # uv 폴백이면 "uv run --no-project python" — 첫 토큰만 PATH 조회
    uv = on_path("uv")
    path_fix = (
        "add the uv tool dir to PATH — run: uv tool update-shell, then restart the terminal"
        if sys.platform == "win32"
        else 'add the install dir to PATH, e.g. export PATH="$HOME/.local/bin:$PATH"'
    )
    checks: list[dict] = [
        {
            "name": "asgard on PATH",
            "ok": bool(asgard),
            "detail": asgard or "not found",
            "fix": path_fix,
        },
        {
            "name": f"{py_cmd} (hooks)",
            "ok": bool(py),
            "detail": py or "not found",
            "fix": f"Canon hooks run via {py_cmd} — https://www.python.org/downloads/",
        },
        {
            "name": "uv on PATH",
            "ok": bool(uv),
            "detail": uv or "not found",
            "fix": "install uv — https://astral.sh/uv (asgard update · 훅 인터프리터 폴백 · uv 프로젝트 베이스라인에 필요)",
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
