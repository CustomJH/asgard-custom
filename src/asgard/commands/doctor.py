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


def _stale_role_agents(root: str) -> list[str]:
    """구세대 역할 계약을 들고 있는 스캐폴드 파일 이름.

    존재 확인만 하던 검사는 드리프트를 못 봤다 — 26-07-26 실측: helios 의 역할 문서 10개 중 7개가
    이전 세대였고(판정자 문서에 JS/TS 실행 레인 문단이 없었다) doctor 는 `10/10 present` 로 녹색을
    보고했다. 계약은 파일 존재가 아니라 내용이다. 렌더러는 setup/sync 와 같은 것을 쓴다."""
    from ..skill_registry import skill_catalog
    from ..templates.roles import claude_agent

    stale: list[str] = []
    for fname, body in ROLE_AGENTS:
        path = os.path.join(root, ".claude", "agents", fname)
        agent = fname.removeprefix("asgard-").removesuffix(".md")
        try:
            expected = claude_agent(body, root) + skill_catalog(root, agent, loader="cli")  # setup 과 동일 조립
            with open(path, encoding="utf-8") as handle:
                if handle.read() != expected:
                    stale.append(fname)
        except Exception:
            continue  # 읽기 실패는 존재 검사(missing)가 이미 다룬다 — 여기서 이중 보고하지 않는다
    return stale


def _map_drift_detail(managed) -> str:
    """맵 드리프트 사유 — 항목 집합이 같고 본문만 달라지면 `+0 -0` 이라는 빈 경고가 떴다
    (26-07-26 실측). 무엇이 다른지 못 말하는 경고는 잡음이므로 사실을 그대로 쓴다."""
    if managed.added or managed.removed:
        return f"managed drift: +{len(managed.added)} -{len(managed.removed)}"
    return "managed projection is stale — same entries, changed detail"


def _shared_memory_check(root: str) -> dict | None:
    """설정된 프로젝트 메모리의 trust·exact binding·readiness를 Trinity와 독립 진단한다."""
    try:
        from ..memory_bridge import find_config, is_backend_trusted, verify_backend_binding
        from ..project_memory_backends import get_backend

        found = find_config(root, strict=True)
        if not found:
            # enabled=false 는 미연결과 다른 의도적 비활성 — 무음이면 "왜 안 쌓이지" 조회가 불가능하다.
            try:
                from ..memory_bridge import project_memory_disabled, project_memory_section
                from ..settings import load_project

                section = project_memory_section(load_project(root))
                if project_memory_disabled(section):
                    return {
                        "name": "shared memory backend",
                        "ok": True,
                        "detail": "off (project_memory.enabled=false — 의도된 비활성)",
                        "fix": "",
                    }
            except Exception:
                pass
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
                learning_detail = ""
                learning_ok = True
                if engine == "hindsight":
                    from ..project_memory.learning import MODEL_SPECS, model_ready

                    read_config = getattr(backend, "bank_config", None)
                    list_models = getattr(backend, "list_mental_models", None)
                    if callable(read_config) and callable(list_models):
                        bank_config = read_config()
                        models = {
                            str(model.get("id") or ""): model for model in list_models() if isinstance(model, dict)
                        }
                        expected = {str(spec["id"]) for spec in MODEL_SPECS}
                        ready_models = sum(model_ready(models.get(model_id, {})) for model_id in expected)
                        learning_ok = (
                            bank_config.get("enable_observations") is True
                            and bank_config.get("enable_auto_consolidation") is False
                            and ready_models == len(expected)
                        )
                        learning_detail = (
                            f" · observations={'on' if bank_config.get('enable_observations') else 'off'}"
                            f" · auto_consolidation={'on' if bank_config.get('enable_auto_consolidation') else 'scoped'}"
                            f" · mental_models={ready_models}/{len(expected)}"
                        )
                    else:
                        learning_ok = False
                        learning_detail = " · learning surface unavailable"
            finally:
                backend.close()
            # auto_retain off 는 유효한 선택이지만 무음이면 "2차 메모리에 안 쌓이는" 증상의
            # 원인 조회가 불가능하다 (1차 inject 게이트와 같은 계열의 무음 비활성) — 상태만 명시.
            detail = (
                f"engine={engine} · project_id={project_id} · {readiness.status}"
                + f" · binding={binding.binding_id[:8]} · project_uid={binding.project_uid[:8]}"
                + f" · auto_retain={'on' if mcfg.get('auto_retain_turns') else 'off'}"
                + (f" · capabilities={','.join(enabled)}" if enabled else "")
                + learning_detail
                + (f" · {readiness.detail}" if readiness.detail else "")
            )
            ok = readiness.status == "ready" and learning_ok
        except Exception as exc:
            detail = f"engine={mcfg.get('engine', 'hindsight')} · unavailable · {type(exc).__name__}: {exc}"
            ok = False
        return {
            "name": "shared memory backend",
            "ok": ok,
            "detail": detail,
            "fix": ("" if ok else "backend 연결을 점검하고 Hindsight면 `asgard memory project-learn --apply` 실행"),
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


def _model_tier_check(root: str) -> dict | None:
    """역할 티어가 실제로 어떤 모델로 해석되는지 — 표가 낡으면 여기서 보인다.

    26-07-26 실측: 티어 표가 이전 세대에 박혀 있어 opus 세션이 역할 턴마다 조용히 내려갔는데
    어느 표면에도 드러나지 않았다. 해석 결과를 보여 주고, API 모드면 카탈로그로 캐시를 갱신한다
    (claude CLI 모드는 계열 별칭이라 갱신 대상이 아니다 — CLI 가 최신 세대로 해석한다)."""
    try:
        from ..model_tiers import TIERS, refresh
        from ..providers import resolve

        rp = resolve(root)
        table, source = refresh(rp.profile.name, rp.profile.api_mode, rp.api_key or "")
        if not table:
            return {
                "name": "model tiers",
                "ok": True,
                "detail": f"n/a · {rp.profile.name} 은 티어 매핑 없음 (설정 모델 그대로 사용)",
                "fix": "",
            }
        shown = " · ".join(f"{tier}={table[tier]}" for tier in TIERS)
        return {"name": "model tiers", "ok": True, "detail": f"{source} · {shown}", "fix": ""}
    except Exception:
        return None


def _personal_memory_check(root: str) -> dict | None:
    """1차(개인) 메모리 주입 게이트 진단 — 무음 차단을 표면화한다.

    26-07-21 실측: 프로젝트 설정이 provider 를 선택하면 inject_allowed 가 개인 메모리 주입을
    전 세션에서 조용히 끈다 (개인정보 방화벽 — 의도된 기본값). 방화벽 자체는 유지하되,
    "저장은 되는데 어떤 세션도 회상하지 못하는" 상태를 사용자가 볼 수 있어야 한다."""
    try:
        from ..memory import inject_allowed, inject_enabled
        from ..providers import resolve

        if not inject_enabled():
            return {
                "name": "personal memory inject",
                "ok": True,
                "detail": "off (kill switch — 의도된 비활성)",
                "fix": "",
            }
        rp = resolve(root)
        if inject_allowed(rp.profile.name, rp.source):
            return {
                "name": "personal memory inject",
                "ok": True,
                "detail": f"on · provider={rp.profile.name}",
                "fix": "",
            }
        return {
            "name": "personal memory inject",
            "ok": False,
            "detail": f"blocked · 프로젝트 선택 provider({rp.profile.name})는 개인 메모리 주입이 기본 거부",
            "fix": f'~/.asgard/asgard-setting-global.json 의 "memory".providers 에 "{rp.profile.name}" 추가 (명시 허용)',
        }
    except Exception:
        return None  # 진단 실패는 doctor 를 막지 않는다 (fail-open)


def _memory_semantic_check() -> dict | None:
    """개인 메모리 시맨틱 스트림 상태 — 켜져 있다는 것과 실제로 도는 것을 구분해 보고한다.

    memory_semantic 계약이 "active() 로 활성/비활성을 대시보드·doctor 에 그대로 노출한다
    (숨기지 않는다)"고 적어 놓고 배선이 없던 자리다. 기본이 켜진 뒤로는 더 중요해졌다 —
    켠 줄 알았는데 임베더를 못 불러 2경로로 도는 상태가 가장 조용한 실패다.

    실측 근거 (26-07-27, 40페이지·80질의): hit@1 0.750→0.850, 놓친 질의 11→2건, 회귀 0건.
    대가는 프로세스당 로드 ~1.2초, 첫 실행은 모델 내려받기 ~35초·약 1GB."""
    try:
        from .. import memory_semantic

        mode = memory_semantic.mode()
        if mode == "off":
            return {
                "name": "personal memory semantic",
                "ok": True,
                "detail": "off — lexical 2경로로 동작 (명시적으로 끈 상태)",
                "fix": "다시 켜려면 asgard memory semantic on",
            }
        active = memory_semantic.active()
        status = memory_semantic.status()
        if active:
            return {
                "name": "personal memory semantic",
                "ok": True,
                "detail": f"on · {status.get('model') or '?'} · {status.get('dim') or 0}d",
                "fix": "",
            }
        cached = memory_semantic.model_cached()
        return {
            "name": "personal memory semantic",
            "ok": False,
            "detail": (
                f"mode={mode} 인데 임베더를 못 불렀다 — 2경로로 폴백 중"
                + ("" if cached else " (모델을 아직 안 받았다)")
            ),
            "fix": "asgard memory semantic warmup (실패하면 asgard memory semantic off 로 명시적으로 끈다)",
        }
    except Exception:
        return None  # 진단 실패는 doctor 를 막지 않는다 (fail-open)


def _memory_curator_check(root: str) -> dict | None:
    """개인 메모리를 손질하는 provider 진단.

    관리자가 없으면 노른·패턴 학습이 멈춘다. 그런데 저장·검색·회상은 LLM 없이 그대로 돌기
    때문에 사용자에게는 아무 일도 안 일어난 것처럼 보인다 — 조용히 멈춘 자가 진화를 보이게 한다."""
    try:
        from ..memory.manager import describe

        row = describe(root)
        origin = {"main": "메인 provider", "config": "설정 지정", "env": "env override"}.get(
            row["source"], row["source"]
        )
        if row.get("ready"):
            return {
                "name": "personal memory curator",
                "ok": True,
                "detail": f"{row.get('provider')} {row.get('model', '')} ({origin})",
                "fix": "",
            }
        return {
            "name": "personal memory curator",
            "ok": False,
            "detail": "없음 — 노른·패턴 학습이 멈춘다 (저장·검색·회상은 정상)",
            "fix": "asgard memory provider --set <provider>[:<model>] (또는 메인 provider 연결)",
        }
    except Exception:
        return None  # 진단 실패는 doctor 를 막지 않는다 (fail-open)


def _memory_durability_check() -> dict | None:
    """개인 메모리의 내구성 — 백업 유무와 동기화 원격. 정본이 한 기계에만 있으면 그렇게 말한다."""
    try:
        from ..memory import backup as backup_mod
        from ..memory import sync as sync_mod

        state = backup_mod.state_note()
        remote = sync_mod.status()
        parts = [f"backups {state['count']}" + (f" (latest {state['latest']})" if state["latest"] else "")]
        parts.append(f"remote {remote['transport']}" if remote["configured"] else "remote 미설정")
        if remote["unresolved_conflicts"]:
            parts.append(f"미해결 충돌 {len(remote['unresolved_conflicts'])}")
        # 빈 위키는 잃을 게 없다 — 아직 아무것도 안 적은 사람에게 백업을 재촉하지 않는다
        durable = state["count"] > 0 or remote["configured"] or remote["local_files"] <= 1
        return {
            "name": "personal memory durability",
            "ok": durable,
            "detail": " · ".join(parts),
            "fix": "" if durable else "asgard memory backup · asgard memory sync --set-remote <path-or-url>",
        }
    except Exception:
        return None


def _manual_area_issues(root: str, mdir: str) -> tuple[list[str], list[str], int, list[str]]:
    """수동 영역 파일의 (유령, 위험, 항목 수, 영역 목록).

    관리 파일 3종은 수동 영역 문법의 대상이 아니다 — map_context.validate_area_maps 와 같은 제외
    목록을 써야 한다. GRAPH.md 가 빠져 있어 그래프의 API 라우트 노드가 절대경로 파일 참조로
    읽혔고, 생성 파일에 대해 영원히 지워지지 않는 unsafe 가 떴다.
    """
    import re as _re

    entry_pat = _re.compile(r"^- `([^`]+)`", _re.M)
    ghosts: list[str] = []
    unsafe: list[str] = []
    entries = 0
    areas = sorted(f for f in os.listdir(mdir) if f.endswith(".md") and f not in ("GRAPH.md", "INDEX.md", "PROJECT.md"))
    for fname in areas:
        area_path = Path(mdir, fname)
        if _is_link(area_path):
            unsafe.append(f"{fname}: symlink/junction")
            continue
        try:
            body = area_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for match in entry_pat.finditer(body):
            entries += 1
            kind = _entry_kind(root, match.group(1))
            if kind == "unsafe":
                unsafe.append(f"{fname}: {match.group(1)}")
            elif kind == "ghost":
                ghosts.append(f"{fname}: {match.group(1)}")
    _add_area_validation(root, ghosts, unsafe)
    return (ghosts, unsafe, entries, areas)


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _entry_kind(root: str, entry_text: str) -> str:
    """항목 하나의 판정 — "ok" | "ghost" | "unsafe". 루트 밖을 가리키면 존재해도 위험이다."""
    entry = entry_text.rstrip("/")
    candidate = Path(root, entry)
    try:
        candidate.resolve(strict=False).relative_to(Path(root).resolve())
    except ValueError:
        return "unsafe"
    if os.path.isabs(entry):
        return "unsafe"
    return "ghost" if not candidate.exists() else "ok"


def _add_area_validation(root: str, ghosts: list[str], unsafe: list[str]) -> None:
    from ..map_context import validate_area_maps

    _, area_issues = validate_area_maps(root)
    for issue in area_issues:
        detail = f"{Path(issue.source).name}: {issue.reason}"
        if detail not in unsafe and not any(detail.startswith(item.split(":", 1)[0] + ":") for item in ghosts):
            unsafe.append(detail)


def _map_status_detail(managed, areas: list[str], entries: int, ghosts: list[str], unsafe: list[str]) -> str:
    if unsafe:
        return "unsafe: " + ", ".join(unsafe[:5])
    if ghosts:
        return "ghost: " + ", ".join(ghosts[:5]) + (f" (+{len(ghosts) - 5})" if len(ghosts) > 5 else "")
    if managed.ok:
        return f"{len(areas)} manual area(s) · {entries} entries · managed current"
    if not managed.owned:
        return "PROJECT.md ownership marker missing"
    if not managed.index_current:
        return "INDEX.md drift"
    if not managed.trackable:
        return "managed map is git-ignored — not shareable"
    return _map_drift_detail(managed)


def _codebase_map_check(root: str) -> list[dict]:
    """유령 엔트리(디스크에 없는 경로) 탐지 — 지도 문법 3: 실재만 기재.

    영역 파일이 아직 없는 것은 정상이다 (fog-of-war). 없는 것을 결함이라 부르면 지도를 처음
    그리는 프로젝트가 영원히 빨간불이 된다.
    """
    from ..code_map import MapError, check_map

    mdir = os.path.join(root, ".asgard", "map")
    unsafe_component = next((p for p in (Path(root, ".asgard"), Path(mdir)) if _is_link(p)), None)
    if unsafe_component is not None:
        detail = f"unsafe managed map path: symlink/junction: {unsafe_component}"
        return [_map_row(False, detail, "symlink/junction 제거 후 asgard map update 실행")]
    if not os.path.isdir(mdir):
        return [_map_row(False, "missing .asgard/map/", "asgard sync (또는 setup --force) 로 지도 시드 생성")]
    ghosts, unsafe, entries, areas = _manual_area_issues(root, mdir)
    try:
        managed = check_map(root)
    except MapError as exc:
        detail = f"unsafe managed map path: {exc}"
        return [_map_row(False, detail, "symlink/junction 제거 후 asgard map update 실행")]
    return [
        _map_row(
            not ghosts and not unsafe and managed.ok,
            _map_status_detail(managed, areas, entries, ghosts, unsafe),
            "asgard map update 실행; 수동 영역의 유령 경로는 제거 (.asgard/map/INDEX.md)",
        )
    ]


def _map_row(ok: bool, detail: str, fix: str) -> dict:
    return {"name": "codebase map", "ok": ok, "detail": detail, "fix": fix}


def _classify_misroute_check(root: str) -> list[dict]:
    """DIRECT 로 분류했는데 write 가 일어난 비율. 기록이 없으면 아무 말도 하지 않는다."""
    try:
        with open(os.path.join(root, ".asgard", "classify.jsonl"), encoding="utf-8") as handle:
            events = [_json.loads(ln) for ln in handle if ln.strip()]
        routes = sum(1 for e in events if e.get("event") == "route")
        misroutes = sum(1 for e in events if e.get("event") == "misroute")
    except Exception:
        return []
    if not routes:
        return []
    return [
        {
            "name": "classify misroute rate",
            "ok": misroutes == 0,
            "detail": f"{misroutes}/{routes} misroute ({misroutes / routes:.0%})",
            "fix": "오분류 반복 시 classify 휴리스틱/프롬프트 보강 (.asgard/classify.jsonl 감사)",
        }
    ]


def _route_prior_check(root: str) -> list[dict]:
    """task-class 별 게이트-red 이력 (Bayesian-lite). 과반 red 클래스는 승격 문턱이 1 로 내려간다."""
    try:
        with open(os.path.join(root, ".asgard", "route-priors.json"), encoding="utf-8") as handle:
            classes = (_json.load(handle) or {}).get("classes") or {}
    except Exception:
        return []
    if not classes:
        return []
    hot = [c for c, v in classes.items() if int(v.get("red") or 0) > int(v.get("n") or 0) - int(v.get("red") or 0)]
    detail = ", ".join(f"{c} {v.get('red', 0)}/{v.get('n', 0)} red" for c, v in sorted(classes.items()))
    return [
        {
            "name": "route priors (Bayesian-lite)",
            "ok": not hot,
            "detail": detail + (f" — 승격 문턱 1: {', '.join(hot)}" if hot else ""),
            "fix": "과반-red 클래스는 red 1회에 Trinity 승격 — 반복되면 baseline_checks/과업 분할 점검",
        }
    ]


def _gate_blocks(root: str) -> tuple[dict[str, int], int]:
    blocks: dict[str, int] = {}
    escalations = 0
    try:
        with open(os.path.join(root, ".asgard", "state", "gate-events.jsonl"), encoding="utf-8") as handle:
            gate_lines = [ln for ln in handle if ln.strip()]
    except OSError:
        return (blocks, escalations)
    for ln in gate_lines:
        ev = _json.loads(ln)
        if ev.get("event") == "gate_block":
            code = str(ev.get("code") or "other")
            blocks[code] = blocks.get(code, 0) + 1
        elif ev.get("event") == "gate_escalate":
            escalations += 1
    return (blocks, escalations)


def _quest_verdicts(root: str) -> tuple[dict[str, int], int]:
    verdicts = {"PASS": 0, "FAIL": 0, "ESCALATE": 0}
    forced = 0
    qdir = os.path.join(root, ".asgard", "quest")
    for fname in os.listdir(qdir) if os.path.isdir(qdir) else []:
        if not fname.endswith(".jsonl"):
            continue
        with open(os.path.join(qdir, fname), encoding="utf-8") as handle:
            quest_lines = [ln for ln in handle if ln.strip()]
        for ln in quest_lines:
            ev = _json.loads(ln)
            if ev.get("event") == "verify" and ev.get("verdict") in verdicts:
                verdicts[ev["verdict"]] += 1
            elif ev.get("event") == "quest_closed" and (ev.get("risk") or {}).get("forced"):
                forced += 1
    return (verdicts, forced)


def _gate_event_check(root: str) -> list[dict]:
    """차단 자체는 게이트가 일한 증거라 결함이 아니다 — 사람이 수동 우회한 forced close 만 경고다."""
    try:
        blocks, escalations = _gate_blocks(root)
        verdicts, forced = _quest_verdicts(root)
    except Exception:
        return []
    if not (blocks or escalations or forced or any(verdicts.values())):
        return []
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
    return [
        {
            "name": "trinity gate events",
            "ok": forced == 0,
            "detail": " · ".join(parts),
            "fix": "forced close 는 게이트 수동 우회 — 사유를 quest 로그에 남기고 재검증 권장 "
            "(.asgard/state/gate-events.jsonl · quest/*.jsonl 감사)",
        }
    ]


def _skill_bank_check(root: str) -> list[dict]:
    """라이브러리는 성장이 아니라 큐레이션이 자산이다 — stale 은 삭제가 아니라 보관 처방."""
    try:
        import time as _time

        from ..evolution import pending_list, unmined_signals
        from ..skill_bank import learned_skills, usage

        skills = learned_skills(root)
        pend = len(pending_list(root))
        unmined = unmined_signals(root)
        if not (skills or pend or unmined):
            return []
        stale = _stale_skills(skills, usage(root), _time.time() - 30 * 86400)
    except Exception:
        return []
    parts = [f"learned {len(skills)}개"]
    if stale:
        parts.append(f"stale(30일+ 미사용) {len(stale)}: {', '.join(stale[:5])}")
    if pend:
        parts.append(f"인박스 대기 {pend}건 (asgard evolve list)")
    if unmined:
        parts.append(f"미채굴 신호 {unmined}건 (asgard evolve scan)")
    return [
        {
            "name": "skill bank (self-evolution)",
            "ok": not stale,
            "detail": " · ".join(parts),
            "fix": "stale 스킬은 asgard evolve archive <name> 로 보관 (삭제 아님, 복원 가능)",
        }
    ]


def _stale_skills(skills: dict, use: dict, cutoff: float) -> list[str]:
    return [name for name in skills if _last_seen(name, skills, use) < cutoff]


def _last_seen(name: str, skills: dict, use: dict) -> float:
    """미사용 스킬은 생성일 기준 — 방금 승인된 스킬을 stale 로 오판하지 않는다."""
    import calendar as _cal
    import time as _time

    last_used = use.get(name, {}).get("last_used")
    fmt, val = ("%Y-%m-%dT%H:%M:%SZ", last_used) if last_used else ("%Y-%m-%d", skills[name].get("created"))
    try:
        # 기록은 gmtime(UTC) — mktime(로컬 해석)이면 stale 경계가 오프셋만큼 어긋난다
        return _cal.timegm(_time.strptime(str(val), fmt))
    except ValueError, TypeError:
        return _time.time()  # 날짜 불명 = 판정 보류 (fail-open)


def _trinity_checks(root: str) -> list[dict]:
    """Trinity 에셋 진단 — AGENTS.md 가 있는 프로젝트에서만. 각 항목의 fix 는 전부 동일한 처방
    (setup --force 재실행)이라 개별 복구 절차를 안내하지 않는다."""
    memory_check = _shared_memory_check(root)
    if not os.path.exists(os.path.join(root, "AGENTS.md")):
        return [memory_check] if memory_check else []
    fix = "asgard setup --force 로 Trinity 에셋 재설치"
    checks = []
    try:
        with open(os.path.join(root, "AGENTS.md"), encoding="utf-8") as handle:
            txt = handle.read()
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
    stale = _stale_role_agents(root) if not missing else []
    checks.append(
        {
            "name": "trinity role agents",
            "ok": not missing and not stale,
            "detail": (
                f"{len(agents)}/{len(agents)} present · current"
                if not missing and not stale
                else "missing: " + ", ".join(missing)
                if missing
                else f"{len(stale)}/{len(agents)} on an older contract: " + ", ".join(stale[:4])
            ),
            "fix": fix if missing else "asgard sync — 스캐폴드를 현행 역할 계약으로 갱신",
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
        with open(os.path.join(root, ".claude", "settings.json"), encoding="utf-8") as handle:
            settings = _json.load(handle)
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
    # 커스텀 매뉴얼 — 오딘이 쓴 프로젝트 규칙. 이 계층은 조용히 실패한다(이름 오타·주석 안·별칭
    # 중복·상한 절단) — 어느 쪽이든 에이전트는 평소처럼 돌고 사용자는 규칙이 먹은 줄 안다.
    # 그래서 "안 실리는 이유"만 ⚠ 로 세운다. 매뉴얼 미작성은 결함이 아니다 (ok).
    try:
        from ..manual import MANUAL_NAMES, MAX_CHARS, discover, enabled, has_marker, load_manual
        from ..manual import label as _rel  # 지역 `label` 루프 변수와 이름이 겹친다 — 검사기가 잡은 자리

        found = discover(root)
        loaded = load_manual(root)
        problems = []
        if found["shadowed"]:
            problems.append("별칭 중복 — 무시된다: " + ", ".join(_rel(root, p) for p in found["shadowed"]))
        if loaded and loaded["truncated"]:
            problems.append(f"상한 절단 {loaded['chars']}자 — 뒷부분 미주입")
        if found["dropped"]:
            problems.append(f"조각 상한 초과 {len(found['dropped'])}개 제외")
        # `MANUAL.md` 는 흔한 이름이다 — 이미 그 이름의 제품 문서를 가진 리포에 설치되면 그 문서가
        # 통째로 프롬프트에 실린다. 손으로 쓴 진짜 매뉴얼과 구분할 방법이 없어 막지는 않고, **큰**
        # 표식 없는 파일만 짚는다 (작은 파일은 사용자가 직접 쓴 규칙일 가능성이 압도적이다).
        if loaded and loaded["chars"] >= MAX_CHARS // 2:
            stranger = [_rel(root, p) for p in found["files"] if os.path.dirname(p) == root and not has_marker(p)]
            if stranger:
                problems.append(
                    f"{', '.join(stranger)} 가 통째로 실리는 중 ({loaded['chars']}자) — 의도한 매뉴얼이 맞는지 확인"
                )
        if not enabled(root):
            detail = "off (manual.mode) — 어떤 모드에도 안 실린다"
        elif loaded:
            layers = f"공통 {len(loaded['common'])} + 프로젝트 {len(loaded['project'])}"
            detail = f"{layers} · {loaded['chars']} chars · 4-mode injected"
        elif found["files"]:
            detail = "파일은 있으나 주입 없음 — 주석뿐 (규칙은 주석 밖에)"
        else:
            detail = f"없음 — 루트 {MANUAL_NAMES[0]} 에 쓰면 4모드에 실린다"
        checks.append(
            {
                "name": "custom manual",
                "ok": not problems,
                "detail": detail if not problems else " · ".join(problems),
                "fix": "asgard manual — 무엇이 어디서 실리는지 대조",
            }
        )
    except Exception:
        pass  # 진단이 진단 대상을 막지 않는다 (fail-open)
    # 에인헤랴르 — 이 프로젝트에서 누가 일하는가. 이 계층도 조용히 빗나간다: 없는 이름을 배치하면
    # 그 자리는 말없이 기본으로 돌고, 서브프로세스에 env 를 안 넘기면 자식이 남의 홈에 쓴다.
    # 배치 없음은 결함이 아니다 (ok) — 조용히 빗나가는 두 경우만 ⚠ 로 세운다.
    try:
        from ..profiles import active, fallback_warning, listing
        from ..swarm import describe

        d = describe(root)
        agents = listing()
        problems = []
        for miss in d["missing"]:
            scope = miss["scope"] + (f" {miss['key']}" if miss["key"] else "")
            problems.append(f"{scope} 에 배치된 {miss['agent']!r} 이 이 기계에 없다 — 기본으로 돈다")
        if warning := fallback_warning():
            problems.append(warning)
        placed = d["binding"]
        if d["swarm"]:
            detail = "스웜 — " + " · ".join(f"{k}={v}" for k, v in sorted(placed["roles"].items()))
        elif placed["default"] or placed["modes"] or placed["roles"]:
            detail = f"이 프로젝트: {d['effective']['session']} · 에이전트 {len(agents)}"
        elif len(agents) > 1:
            detail = f"에이전트 {len(agents)} · 활성 {active()} · 이 프로젝트에 배치 선언 없음"
        else:
            detail = "기본 에이전트 하나 — `asgard agent create <이름>` 으로 늘린다"
        checks.append(
            {
                "name": "agents (Einherjar)",
                "ok": not problems,
                "detail": detail if not problems else " · ".join(problems),
                "fix": "asgard agent where — 누가 일하고 어느 선언이 이겼는지 대조",
            }
        )
    except Exception:
        pass  # fail-open
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

                with open(config_path, "rb") as handle:
                    config = tomllib.load(handle)
            else:
                with open(config_path, encoding="utf-8") as handle:
                    config = _json.load(handle)
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
        map_snapshot = map_recall = map_subagent = map_complete = False
        try:
            hooks = config.get("hooks", {})
            map_snapshot = "map-activate" in _json.dumps(hooks.get(snapshot_event, []))
            map_recall = "map-activate" in _json.dumps(hooks.get(recall_event, []))
            map_subagent = "map-activate" in _json.dumps(
                hooks.get("subagentStart" if client == "Cursor" else "SubagentStart", [])
            )
            map_complete = "map-activate" in _json.dumps(hooks.get("stop" if client == "Cursor" else "Stop", []))
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
                (map_complete, "Stop refresh"),
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
    checks += _codebase_map_check(root)
    ledger_ok = os.access(root, os.W_OK)
    checks.append(
        {
            "name": ".asgard quest-log writable",
            "ok": ledger_ok,
            "detail": os.path.join(root, ".asgard") if ledger_ok else "not writable",
            "fix": "프로젝트 루트 쓰기 권한 확인",
        }
    )
    checks += _classify_misroute_check(root)
    checks += _route_prior_check(root)
    checks += _gate_event_check(root)
    checks += _skill_bank_check(root)
    return checks


# 세 클라이언트가 공유하는 규율 — 한쪽에만 깔린 게이트는 기능이 아니라 드리프트다.
# lagom-statusline.sh 는 CC 에만 있는 표면(statusLine)이라 이 표에 없다.
_PARITY_HOOKS = (
    "git-guard.py",
    "release-guard.py",
    "readonly-guard.py",
    "secret-guard.py",
    "failure-tracker.py",
    "quest-log.py",
    "verifier-gate.py",
    "write-sentinel.py",
    "unattended-context.py",
    "subagent-gate.py",
    "craft-gate.py",
    "budget-guard.py",
    "tutor-note.py",
    "lagom-activate.py",
    "lagom-tracker.py",
    "lagom-subagent.py",
    "lagom-canon.md",
    "memory-activate.py",
    "charter-activate.py",
    "manual-activate.py",
    "agent-activate.py",
    "map-activate.py",
)
# 파일만 깔리고 배선이 없으면 그 규율은 없는 것과 같다 — 설정 원문에 이름이 있는지로 본다.
_PARITY_WIRED = tuple(
    name.removesuffix(".py") for name in _PARITY_HOOKS if name.endswith(".py") and name != "quest-log.py"
)


def _mode_parity_check(root: str) -> list[dict]:
    """모드 간 규율 대조 — 설치된 클라이언트마다 같은 훅이 깔리고 배선돼 있는가.

    `asgard init` 은 한 표에서 세 클라이언트를 깔지만, 옛 스캐폴드가 남은 프로젝트는 한 모드에만
    게이트가 있는 상태로 굳는다. 그 차이는 사용자가 모드를 바꿔 보기 전에는 안 보인다."""
    checks: list[dict] = []
    for client, folder, config_name in (
        ("CC", ".claude", "settings.json"),
        ("Cursor", ".cursor", "hooks.json"),
        ("Codex", ".codex", "config.toml"),
    ):
        if not os.path.isdir(os.path.join(root, folder)):
            continue
        hooks_dir = os.path.join(root, folder, "hooks")
        missing = [name for name in _PARITY_HOOKS if not os.path.exists(os.path.join(hooks_dir, name))]
        try:
            with open(os.path.join(root, folder, config_name), encoding="utf-8") as handle:
                config_text = handle.read()
        except OSError:
            config_text = ""
        unwired = [name for name in _PARITY_WIRED if name not in config_text]
        detail = "동일 규율 배선"
        if missing or unwired:
            parts = []
            if missing:
                parts.append("파일 없음: " + ", ".join(missing[:6]))
            if unwired:
                parts.append("미배선: " + ", ".join(unwired[:6]))
            detail = " · ".join(parts)
        checks.append(
            {
                "name": f"mode parity ({client})",
                "ok": not missing and not unwired,
                "detail": detail,
                "fix": "asgard sync — 세 모드에 같은 훅 표를 다시 깐다",
            }
        )
    return checks


def _freyja_engine_dir() -> Path:
    """Freyja 2 엔진 루트 — 훅 매니페스트의 `${FREYJA2_ENGINE}` 가 가리키는 그 경로.

    번들 플러그인은 설치본에서 그 자리 그대로 실행되므로(복사 설치가 아니다) 경로는
    레지스트리가 아는 자산 루트에서 유도한다 — 두 곳이 갈라지지 않게.
    """
    from ..skill_registry import _BUNDLED_PLUGINS_DIR

    return Path(_BUNDLED_PLUGINS_DIR) / "freyja2/skills/asgard-freyja2/engine"


def _design_engine_checks() -> list[dict]:
    """디자인 엔진이 *실제로 완전체로* 실려 왔는지.

    엔진2의 정적 HTML 검출기는 htmlparser2·css-select·css-tree·domutils 를 bare import
    하고, 실패하면 경고 없이 정규식 경로로 되돌아간다. 원본 대조에서 그 폴백 상태의
    검출력이 규칙 40종→15종이었다 — 조용하기 때문에 쓰는 쪽은 깨끗한 페이지와 구별할 수
    없다. 그래서 번들을 휠에 실었고, 여기서 그 존재와 node 런타임을 확인한다.
    """
    engine = _freyja_engine_dir()
    checks: list[dict] = []
    bundle = engine / "scripts/detector/vendor/static-parser.mjs"
    checks.append(
        {
            "name": "freyja2 static parser",
            "ok": bundle.is_file(),
            "detail": f"vendored ({bundle.stat().st_size // 1024}KB)"
            if bundle.is_file()
            else "missing — detector runs regex-only",
            "fix": "재설치로 복구된다: asgard update (휠에 동봉돼 있어 별도 설치 없음)",
        }
    )
    # 3D 엔진(브리싱아멘)의 값어치는 검증 런타임에 있다 — 스크립트가 빠지면 형상을 측정하지
    # 못한 채 "만들었다"만 남는다. 엔진2 번들과 같은 이유로 존재를 확인한다.
    from ..skill_registry import _BUNDLED_PLUGINS_DIR

    scripts = Path(_BUNDLED_PLUGINS_DIR) / "freyja-3d/skills/asgard-freyja-3d/engine/scripts"
    required = ("shoot.mjs", "mesh_audit.mjs", "scene_audit.mjs", "detect3d.mjs", "preflight.mjs", "cad_build.py")
    missing = [name for name in required if not (scripts / name).is_file()]
    checks.append(
        {
            "name": "freyja 3d runtime",
            "ok": not missing,
            "detail": f"{len(required)} scripts bundled" if not missing else f"missing: {', '.join(missing)}",
            "fix": "재설치로 복구된다: asgard update (휠에 동봉 — 렌더·측정·검출이 전부 이 스크립트에 있다)",
        }
    )

    # 엔진4(마르될)는 규칙 코퍼스 + 결정론 게이트다. 게이트가 빠지면 남는 건 자기채점뿐이고,
    # 자기채점은 리뷰가 아니다 — 그래서 코퍼스가 아니라 판정기의 존재를 본다.
    gate = Path(_BUNDLED_PLUGINS_DIR) / "freyja4/skills/asgard-freyja4/engine/scripts/slop_gate.mjs"
    themes = Path(_BUNDLED_PLUGINS_DIR) / "freyja4/skills/asgard-freyja4/references/tokens.css"
    gate_missing = [
        label for label, path in (("slop_gate.mjs", gate), ("references/tokens.css", themes)) if not path.is_file()
    ]
    checks.append(
        {
            "name": "freyja4 gate runtime",
            "ok": not gate_missing,
            "detail": "gate + 20-theme tokens bundled" if not gate_missing else f"missing: {', '.join(gate_missing)}",
            "fix": "재설치로 복구된다: asgard update (게이트가 없으면 슬롭 판정이 자기보고로 되돌아간다)",
        }
    )

    node = on_path("node")
    version = ""
    if node:
        import subprocess

        try:
            version = subprocess.run(
                [node, "-v"], capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
            ).stdout.strip()
        except Exception:
            version = ""
    major = int(version.lstrip("v").split(".")[0]) if version.lstrip("v").split(".")[0].isdigit() else 0
    checks.append(
        {
            "name": "node (design engines)",
            # 엔진 스크립트는 node >= 22 를 요구한다. 없으면 프레이야 자체는 돌지만
            # 검출기·훅·live 가 전부 죽으므로 침묵보다 경고가 낫다.
            "ok": bool(node) and major >= 22,
            "detail": (f"{version} · {node}" if node else "not found") + ("" if major >= 22 else " — need >= 22"),
            "fix": "install node >= 22 — https://nodejs.org (프레이야 엔진1·2·3D 스크립트 런타임)",
        }
    )
    return checks


def _office_checks() -> list[dict]:
    """Sága 문서 계층. 생성·읽기·검증은 순수 파이썬이라 항상 서야 하고, 렌더만 외부 관문이다."""
    from ..skill_registry import _BUNDLED_PLUGINS_DIR

    checks: list[dict] = []
    missing = []
    for label, module in (("python-docx", "docx"), ("python-pptx", "pptx"), ("openpyxl", "openpyxl")):
        try:
            __import__(module)
        except ImportError:
            missing.append(label)
    checks.append(
        {
            "name": "office engines",
            "ok": not missing,
            "detail": "docx · pptx · xlsx bundled" if not missing else f"missing: {', '.join(missing)}",
            "fix": "재설치로 복구된다: asgard update (기본 의존성 — 빠지면 문서 생성 자체가 죽는다)",
        }
    )

    scripts = Path(_BUNDLED_PLUGINS_DIR) / "asgard-office/skills/asgard-office/scripts"
    required = ("build_docx.py", "build_pptx.py", "build_xlsx.py", "extract.py", "verify.py", "fill.py", "outline.py")
    absent = [name for name in required if not (scripts / name).is_file()]
    checks.append(
        {
            "name": "office lanes",
            "ok": not absent,
            "detail": f"{len(required)} lane scripts bundled" if not absent else f"missing: {', '.join(absent)}",
            "fix": "재설치로 복구된다: asgard update (휠에 동봉 — 생성·읽기·검증이 전부 이 스크립트에 있다)",
        }
    )

    # 렌더는 없어도 되는 게 정상이다. 관문이 없다는 사실만 정확히 알리고 실패로 세지 않는다.
    soffice = on_path("soffice") or on_path("libreoffice") or os.environ.get("ASGARD_SOFFICE", "")
    if not soffice and sys.platform == "darwin" and Path("/Applications/LibreOffice.app").exists():
        soffice = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    checks.append(
        {
            "name": "office render gate",
            "ok": True,
            "detail": (soffice or "LibreOffice not found — verify still runs, render and --recalc do not"),
            "fix": "선택 사항: brew install --cask libreoffice (PDF·페이지 이미지·수식 재계산에만 쓰인다)",
        }
    )
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
    checks += _design_engine_checks()
    checks += _office_checks()
    if personal := _personal_memory_check(os.getcwd()):
        checks.append(personal)
    if curator := _memory_curator_check(os.getcwd()):
        checks.append(curator)
    if semantic := _memory_semantic_check():
        checks.append(semantic)
    if durability := _memory_durability_check():
        checks.append(durability)
    if tiers := _model_tier_check(os.getcwd()):
        checks.append(tiers)
    checks += _trinity_checks(os.getcwd())
    checks += _mode_parity_check(os.getcwd())  # 모드 간 규율 대조
    security_ok = all(ch["ok"] for ch in checks if ch.get("security"))
    ok = bool(asgard) and security_ok
    runtime = f"python {sys.version.split()[0]}"

    if json_out:
        sys.stdout.write(
            _json.dumps(
                {
                    "version": __version__,
                    "runtime": runtime,
                    "ok": ok,
                    # 훅 매니페스트(engine/hooks/)가 `${FREYJA2_ENGINE}` 로 참조하는 경로.
                    # 설치 위치는 버전마다 달라지므로 하드코딩 대신 여기서 읽어 간다.
                    "freyja2_engine": str(_freyja_engine_dir()),
                    "checks": checks,
                },
                indent=2,
            )
            + "\n"
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
