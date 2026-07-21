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


def _shared_memory_check(root: str) -> dict | None:
    """설정된 프로젝트 메모리의 trust·exact binding·readiness를 Trinity와 독립 진단한다."""
    try:
        from ..memory_bridge import find_config, is_backend_trusted, verify_backend_binding
        from ..project_memory_backends import get_backend

        found = find_config(root, strict=True)
        if not found:
            return None
        _, mcfg = found
        try:
            if not is_backend_trusted(mcfg):
                raise PermissionError("untrusted backend target; run asgard memory connect")
            backend = get_backend(mcfg)
            try:
                binding = verify_backend_binding(mcfg, backend=backend)
                readiness = backend.readiness()
                enabled = [name for name, supported in asdict(backend.capabilities()).items() if supported]
                engine, project_id = backend.engine, backend.project_id
            finally:
                backend.close()
            detail = (
                f"engine={engine} · project_id={project_id} · {readiness.status}"
                + f" · binding={binding.binding_id[:8]} · project_uid={binding.project_uid[:8]}"
                + (f" · capabilities={','.join(enabled)}" if enabled else "")
                + (f" · {readiness.detail}" if readiness.detail else "")
            )
            ok = readiness.status == "ready"
        except Exception as exc:
            detail = f"engine={mcfg.get('engine', 'hindsight')} · unavailable · {type(exc).__name__}: {exc}"
            ok = False
        return {
            "name": "shared memory backend",
            "ok": ok,
            "detail": detail,
            "fix": "" if ok else "backend/plugin 설치·기동·인증 확인 또는 asgard memory connect 재설정",
            "security": True,
        }
    except Exception as exc:
        return {
            "name": "shared memory backend",
            "ok": False,
            "detail": f"diagnostic failed closed · {type(exc).__name__}: {exc}",
            "fix": "프로젝트 memory 설정을 점검하고 asgard memory connect 재실행",
            "security": True,
        }


def _trinity_checks(root: str) -> list[dict]:
    """Trinity 에셋 진단 — AGENTS.md 가 있는 프로젝트에서만. 각 항목의 fix 는 전부 동일한 처방
    (setup --force 재실행)이라 개별 복구 절차를 안내하지 않는다."""
    memory_check = _shared_memory_check(root)
    if not os.path.exists(os.path.join(root, "AGENTS.md")):
        return [memory_check] if memory_check else []
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
    client_adapters = []
    for folder in (".claude", ".agents"):
        if os.path.isdir(os.path.join(root, folder)):
            client_adapters.append(os.path.join(folder, "skills", "asgard-skills", "SKILL.md"))
    missing_adapters = [path for path in client_adapters if not os.path.isfile(os.path.join(root, path))]
    checks.append(
        {
            "name": "central skill manager adapters",
            "ok": bool(client_adapters) and not missing_adapters,
            "detail": (
                f"{len(client_adapters)}/{len(client_adapters)} clients wired"
                if client_adapters and not missing_adapters
                else "missing: " + ", ".join(missing_adapters or ["client skill scope"])
            ),
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
    # Memory v3 — 설치된 각 클라이언트의 snapshot/recall/turn-sync 배선을 독립 진단한다.
    for client, folder, config_name, snapshot_event, recall_event, skill_folder in (
        ("CC", ".claude", "settings.json", "SessionStart", "UserPromptSubmit", ".claude"),
        ("Cursor", ".cursor", "hooks.json", "sessionStart", "beforeSubmitPrompt", ".agents"),
        ("Codex", ".codex", "config.toml", "SessionStart", "UserPromptSubmit", ".agents"),
    ):
        if not os.path.isdir(os.path.join(root, folder)):
            continue
        hook_ok = os.path.exists(os.path.join(root, folder, "hooks", "memory-activate.py"))
        snapshot_wired = recall_wired = sync_wired = False
        skill_ok = os.path.exists(os.path.join(root, skill_folder, "skills", "asgard-memory", "SKILL.md"))
        try:
            config_path = os.path.join(root, folder, config_name)
            if config_name.endswith(".toml"):
                import tomllib

                config = tomllib.load(open(config_path, "rb"))
            else:
                config = _json.load(open(config_path))
            hooks = config.get("hooks", {})
            snapshot_wired = "memory-activate" in _json.dumps(hooks.get(snapshot_event, []))
            recall_wired = "memory-activate" in _json.dumps(hooks.get(recall_event, []))
            sync_wired = "memory-activate" in _json.dumps(hooks.get("stop" if client == "Cursor" else "Stop", []))
        except Exception:
            pass
        missing = []
        for ok, label in (
            (hook_ok, "hook file"),
            (snapshot_wired, snapshot_event),
            (recall_wired, recall_event),
            (sync_wired, "Stop sync"),
            (skill_ok, "asgard-memory skill"),
        ):
            if not ok:
                missing.append(label)
        checks.append(
            {
                "name": f"memory wiring ({client})",
                "ok": not missing,
                "detail": "wired" if not missing else "missing: " + ", ".join(missing),
                "fix": fix,
            }
        )
        map_hook_ok = os.path.exists(os.path.join(root, folder, "hooks", "map-activate.py"))
        map_snapshot = map_recall = map_subagent = False
        try:
            hooks = config.get("hooks", {})
            map_snapshot = "map-activate" in _json.dumps(hooks.get(snapshot_event, []))
            map_recall = "map-activate" in _json.dumps(hooks.get(recall_event, []))
            map_subagent = "map-activate" in _json.dumps(
                hooks.get("subagentStart" if client == "Cursor" else "SubagentStart", [])
            )
            if client == "Cursor":
                map_subagent = map_subagent or "map-activate" in _json.dumps(hooks.get("preToolUse", []))
        except Exception:
            pass
        map_missing = [
            label
            for ok, label in (
                (map_hook_ok, "hook file"),
                (map_snapshot, snapshot_event),
                (map_recall, recall_event),
                (map_subagent, "SubagentStart"),
            )
            if not ok
        ]
        checks.append(
            {
                "name": f"map wiring ({client})",
                "ok": not map_missing,
                "detail": "wired" if not map_missing else "missing: " + ", ".join(map_missing),
                "fix": fix,
            }
        )
    if memory_check:
        checks.append(memory_check)
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
                "fix": "symlink/junction 제거 후 asgard map update 실행",
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
        from ..map_context import validate_area_maps

        _, area_issues = validate_area_maps(root)
        for issue in area_issues:
            detail = f"{Path(issue.source).name}: {issue.reason}"
            if detail not in unsafe and not any(detail.startswith(item.split(":", 1)[0] + ":") for item in ghosts):
                unsafe.append(detail)
        try:
            managed = check_map(root)
        except MapError as exc:
            checks.append(
                {
                    "name": "codebase map",
                    "ok": False,
                    "detail": f"unsafe managed map path: {exc}",
                    "fix": "symlink/junction 제거 후 asgard map update 실행",
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
                    "fix": "asgard map update 실행; 수동 영역의 유령 경로는 제거 (.asgard/map/INDEX.md)",
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
    # 게이트 운영 지표 — Stop 게이트 차단/에스컬레이션(state/gate-events.jsonl) + 퀘스트 종료
    # 판정(quest_closed.risk) 집계. 차단 자체는 게이트가 일한 증거라 결함이 아니다 — 사람이
    # 게이트를 수동 우회한 forced close 만 경고로 승격. 기록 있을 때만 표시 (misroute 관행).
    try:
        blocks: dict[str, int] = {}
        escalations = 0
        try:
            for ln in open(os.path.join(root, ".asgard", "state", "gate-events.jsonl"), encoding="utf-8"):
                if not ln.strip():
                    continue
                ev = _json.loads(ln)
                code = str(ev.get("code") or "other")
                if ev.get("event") == "gate_block":
                    blocks[code] = blocks.get(code, 0) + 1
                elif ev.get("event") == "gate_escalate":
                    escalations += 1
        except OSError:
            pass
        verdicts = {"PASS": 0, "FAIL": 0, "ESCALATE": 0}
        forced = 0
        qdir = os.path.join(root, ".asgard", "quest")
        for fname in os.listdir(qdir) if os.path.isdir(qdir) else []:
            if not fname.endswith(".jsonl"):
                continue
            for ln in open(os.path.join(qdir, fname), encoding="utf-8"):
                if not ln.strip():
                    continue
                ev = _json.loads(ln)
                if ev.get("event") == "verify" and ev.get("verdict") in verdicts:
                    verdicts[ev["verdict"]] += 1
                elif ev.get("event") == "quest_closed" and (ev.get("risk") or {}).get("forced"):
                    forced += 1
        if blocks or escalations or forced or any(verdicts.values()):
            parts = []
            if blocks:
                top = ", ".join(f"{c} {n}" for c, n in sorted(blocks.items(), key=lambda kv: -kv[1])[:4])
                parts.append(f"gate block {sum(blocks.values())}회 ({top})")
            if escalations:
                parts.append(f"차단 상한 초과 에스컬레이션 {escalations}회")
            if any(verdicts.values()):
                parts.append(f"verdict PASS {verdicts['PASS']}·FAIL {verdicts['FAIL']}·ESCALATE {verdicts['ESCALATE']}")
            if forced:
                parts.append(f"forced close {forced}회")
            checks.append(
                {
                    "name": "trinity gate events",
                    "ok": forced == 0,
                    "detail": " · ".join(parts),
                    "fix": "forced close 는 게이트 수동 우회 — 사유를 quest 로그에 남기고 재검증 권장 "
                    "(.asgard/state/gate-events.jsonl · quest/*.jsonl 감사)",
                }
            )
    except Exception:
        pass
    # skill bank (자가발전 CUS-255) — learned 스킬 수·stale 후보·인박스 대기. 라이브러리는
    # 성장이 아니라 큐레이션이 자산이다 — stale 은 asgard evolve archive 처방.
    try:
        import time as _time

        from ..evolution import pending_list, unmined_signals
        from ..skill_bank import learned_skills, usage

        skills = learned_skills(root)
        pend = len(pending_list(root))
        unmined = unmined_signals(root)
        if skills or pend or unmined:
            use = usage(root)
            cutoff = _time.time() - 30 * 86400

            def _last_seen(n: str) -> float:
                # 미사용 스킬은 생성일 기준 — 방금 승인된 스킬을 stale 로 오판하지 않는다
                lu = use.get(n, {}).get("last_used")
                fmt, val = ("%Y-%m-%dT%H:%M:%SZ", lu) if lu else ("%Y-%m-%d", skills[n].get("created"))
                try:
                    import calendar as _cal

                    # 기록은 gmtime(UTC) — mktime(로컬 해석)이면 stale 경계가 오프셋만큼 어긋난다
                    return _cal.timegm(_time.strptime(str(val), fmt))
                except ValueError, TypeError:
                    return _time.time()  # 날짜 불명 = 판정 보류 (fail-open)

            stale = [n for n in skills if _last_seen(n) < cutoff]
            parts = [f"learned {len(skills)}개"]
            if stale:
                parts.append(f"stale(30일+ 미사용) {len(stale)}: {', '.join(stale[:5])}")
            if pend:
                parts.append(f"인박스 대기 {pend}건 (asgard evolve list)")
            if unmined:
                parts.append(f"미채굴 신호 {unmined}건 (asgard evolve scan)")
            checks.append(
                {
                    "name": "skill bank (self-evolution)",
                    "ok": not stale,
                    "detail": " · ".join(parts),
                    "fix": "stale 스킬은 asgard evolve archive <name> 로 보관 (삭제 아님, 복원 가능)",
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
    security_ok = all(ch["ok"] for ch in checks if ch.get("security"))
    ok = bool(asgard) and security_ok
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
