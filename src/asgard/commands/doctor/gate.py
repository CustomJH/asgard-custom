"""doctor — 게이트와 퀘스트 검사. 차단 이력·판정 기록·베이스라인 레인·작업공간 신뢰."""

import json as _json
import os


def _classify_misroute_check(root: str) -> list[dict]:
    """DIRECT로 분류했는데 write가 일어난 비율. 기록이 없으면 아무 말도 하지 않는다."""
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
    """task-class 별 게이트-red 이력 (Bayesian-lite). 과반 red 클래스는 승격 문턱이 1로 내려간다."""
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


def _gate_blocks(root: str) -> tuple[dict[str, int], int, dict[str, int]]:
    """(차단 사유별 횟수, 상한 초과 에스컬레이션 수, 무판정 사유별 횟수)."""
    blocks: dict[str, int] = {}
    skipped: dict[str, int] = {}
    escalations = 0
    try:
        with open(os.path.join(root, ".asgard", "state", "gate-events.jsonl"), encoding="utf-8") as handle:
            gate_lines = [ln for ln in handle if ln.strip()]
    except OSError:
        return (blocks, escalations, skipped)
    for ln in gate_lines:
        ev = _json.loads(ln)
        code = str(ev.get("code") or "other")
        if ev.get("event") == "gate_block":
            blocks[code] = blocks.get(code, 0) + 1
        elif ev.get("event") == "gate_escalate":
            escalations += 1
        elif ev.get("event") == "gate_skipped":
            skipped[code] = skipped.get(code, 0) + 1
    return (blocks, escalations, skipped)


# 게이트가 판정 없이 사라진 사유 중 **사람이 손대야 하는** 것과 그 처방. 나머지 사유
# (no-sentinel·no-judged-writes)는 잴 것이 없던 정상 상황이라 세기만 하고 경고로 올리지
# 않는다 — 매번 뜨는 경고는 곧 아무도 안 읽고, 그러면 이 계측이 막으려던 자리가 다시 열린다.
_GATE_SKIP_ACTIONABLE = {
    "no-asgard": "asgard가 PATH에 없어 판정기를 못 불렀어요",
    "hook-error": "훅이 예외로 끝났어요",
}


def _skipped_note(skipped: dict[str, int]) -> tuple[str, list[str]]:
    """(화면 한 줄, 조치가 필요한 사유들). 사유를 안 가르면 '무판정 12회'가 무슨 뜻인지 아무도 모른다."""
    hot = [f"{_GATE_SKIP_ACTIONABLE[c]} {n}회" for c, n in sorted(skipped.items()) if c in _GATE_SKIP_ACTIONABLE]
    quiet = sum(n for c, n in skipped.items() if c not in _GATE_SKIP_ACTIONABLE)
    line = f"게이트 무판정 {sum(skipped.values())}회 (잴 대상 없음 {quiet})"
    return (line + (" · " + " · ".join(hot) if hot else ""), hot)


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
    """차단 자체는 게이트가 일한 증거라 결함이 아니다 — 사람이 수동 우회한 forced close 와,
    게이트가 조치 필요한 사유로 판정 없이 사라진 것만 경고다."""
    try:
        blocks, escalations, skipped = _gate_blocks(root)
        verdicts, forced = _quest_verdicts(root)
    except Exception:
        return []
    if not (blocks or escalations or skipped or forced or any(verdicts.values())):
        return []
    parts = []
    if blocks:
        top = ", ".join(f"{c} {n}" for c, n in sorted(blocks.items(), key=lambda kv: -kv[1])[:4])
        parts.append(f"gate block {sum(blocks.values())}회 ({top})")
    if escalations:
        parts.append(f"차단 상한 초과 에스컬레이션 {escalations}회")
    skip_line, skip_hot = _skipped_note(skipped) if skipped else ("", [])
    if skip_line:
        parts.append(skip_line)
    if any(verdicts.values()):
        parts.append(f"verdict PASS {verdicts['PASS']}·FAIL {verdicts['FAIL']}·ESCALATE {verdicts['ESCALATE']}")
    if forced:
        parts.append(f"forced close {forced}회")
    return [
        {
            "name": "trinity gate events",
            "ok": forced == 0 and not skip_hot,
            "detail": " · ".join(parts),
            "fix": "forced close는 게이트 수동 우회 — 사유를 quest 로그에 남기고 재검증 권장. "
            "게이트 무판정은 잴 대상이 없던 정상 경우가 대부분이고, PATH·훅 오류로 표시된 것만 조치 대상 "
            "(.asgard/state/gate-events.jsonl · quest/*.jsonl 감사)",
        }
    ]


_FIRING_FLOOR = 20  # 이보다 적게 불린 훅의 발화 0 은 "값을 그쳤다"가 아니라 "표본이 없다"다


def _firing_check(root: str) -> list[dict]:
    """훅별 발화율 — 사건 장부가 못 가진 분모다.

    `gate-events.jsonl` 은 발화만 적으므로, 한 번도 발화하지 않은 훅과 아직 불린 적 없는 훅이
    똑같은 빈칸으로 보인다. 여기서는 호출 수를 같이 읽어 그 둘을 가르고, 발화 없이 계속 불리는
    훅을 이름으로 부른다 — 그 이름이 반감기 조항(AGENTS.md)이 지울 대상을 고를 때 보는 목록이다.

    예외로 죽은 호출은 발화가 아니라 `errors` 로 세어져 있다. 둘을 합치면 매번 고장 나 있던 훅이
    열심히 일하는 훅과 같은 숫자로 보인다."""
    try:
        with open(os.path.join(root, ".asgard", "state", "gate-firing.json"), encoding="utf-8") as handle:
            gates = (_json.load(handle) or {}).get("gates") or {}
    except OSError, ValueError:
        return []
    if not isinstance(gates, dict) or not gates:
        return []
    silent: list[str] = []
    broken: list[str] = []
    fired = 0
    for name, row in sorted(gates.items()):
        calls = int(row.get("calls") or 0)
        fires = int(row.get("fires") or 0)
        errors = int(row.get("errors") or 0)
        if errors:
            broken.append(f"{name} {errors}회")
        if fires:
            fired += 1
        elif calls >= _FIRING_FLOOR:
            silent.append(f"{name}({calls}회 호출)")
    parts = [f"훅 {len(gates)}개 중 {fired}개 발화"]
    if silent:
        parts.append("발화 없음: " + ", ".join(silent))
    if broken:
        parts.append("예외로 끝난 호출: " + ", ".join(broken))
    return [
        {
            "name": "hook firing rate",
            "ok": not broken,
            "detail": " · ".join(parts),
            "fix": "예외로 끝나는 훅은 fail-open 이라 조용히 죽는다 — 그 훅을 손으로 한 번 돌려 원인을 봐라. "
            f"발화 없음은 결함이 아니라 삭제 후보 목록이다 (호출 {_FIRING_FLOOR}회 이상만 이름을 부른다). "
            "억제 효과는 이 장부에 안 찍히므로, 지우기 전에 그 훅이 막던 것이 무엇이었는지 확인해라 "
            "(.asgard/state/gate-firing.json)",
        }
    ]


def _auto_baseline_check(root: str, policy: dict, quest_log_mod) -> dict | None:
    """자동 감지 레인 — 무엇을 고를지, 그것이 상한 안에 드는지 말한다.

    종전에는 `baseline_checks` 가 비면 아무 말도 안 했다 ("사용자가 적은 것이 없으니 말할 것도
    없다"). 그 침묵이 가장 비싼 자리였다: 감지된 명령이 `baseline_timeout` 보다 느리면 결정론
    레인은 매번 상한을 태우고 증거 없이 끊기고, **모든 쓰기 퀘스트가 LLM Verifier 로 간다**
    (quest_log.transition 의 checks_available 갈림길). 이 저장소 26-08-04 실측: 전체 pytest
    739초 대 상한 120초 — 레인이 원리상 못 선다.

    새로 재지 않는다. 판정 근거는 퀘스트 기장에 이미 있다 — 끊긴 실행은 `timed_out` 로 적힌다."""
    checks = quest_log_mod.detect_checks(root, policy)
    if not checks:
        return {
            "name": "baseline checks",
            "ok": True,
            "detail": "자동 감지 대상 없음 — 게이트는 LLM Verifier 로 판정해요",
            "fix": "",
        }
    timeout = int(policy.get("baseline_timeout") or 120)
    stalled = sorted({cmd for cmd in checks if _ever_timed_out(root, cmd)})
    listed = ", ".join(cmd[:60] for cmd in checks[:2])
    if not stalled:
        return {
            "name": "baseline checks",
            "ok": True,
            "detail": f"자동 감지 · {listed} (상한 {timeout}초)",
            "fix": "",
        }
    # 기장이 받치는 사실만 말한다 — `timed_out` 행은 **그때의** 상한에서 끊겼다는 기록이고,
    # 지금 설정된 초가 그때와 같다는 보장이 없다 (이 저장소의 행은 120초에서 적혔는데 현재
    # 설정은 180초다). 지금 값은 고칠 자리를 가리키는 참고로만 붙인다.
    return {
        "name": "baseline checks",
        "ok": False,
        "detail": f"자동 감지 명령이 이전 실행에서 상한에 끊겼어요: {', '.join(c[:60] for c in stalled)} "
        f"(현재 상한 {timeout}초) — 결정론 레인이 꺼진 채라 쓰기 퀘스트마다 LLM Verifier 가 붙어요",
        "fix": "`.asgard/asgard-setting-project.json` → trinity_policy.baseline_checks 에 이 저장소의 "
        "빠른 행위 검사를 적고(예: `uv run pytest -q -x tests/<범위>`), 필요하면 baseline_timeout 도 "
        "그 명령이 실제로 쓰는 초로 올려 주세요",
    }


def _ever_timed_out(root: str, cmd: str) -> bool:
    """이 명령이 퀘스트 기장에서 상한에 끊긴 적이 있는가 — 최근 기장만 훑는다 (판정용 관측)."""
    import glob
    import json as _json

    from ...hooks.asgard_hooklib.baseline import _timed_out_row

    paths = sorted(glob.glob(os.path.join(root, ".asgard", "quest", "*.jsonl")), key=os.path.getmtime)[-20:]
    for path in reversed(paths):
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        event = _json.loads(line)
                    except ValueError:
                        continue
                    rows = (event.get("baseline") or {}).get("results")
                    if _timed_out_row(rows, cmd, 120):
                        return True
        except OSError:
            continue
    return False


def _baseline_checks_check(root: str) -> dict | None:
    """게이트의 독립 증거 레인 — 적어 둔 체크가 실제로 도는가.

    `baseline_checks`는 안전 표를 넘은 것만 실행된다. 표를 못 넘은 항목은 조용히 사라지는데,
    그러면 설정한 사람은 체크가 도는 줄 알고, 게이트는 독립 증거 없이 모델이 신고한 exit code를
    그대로 받는다 (26-07-31 실측: 절대경로 인터프리터 하나로 레인 전체가 침묵했다)."""
    try:
        from ...hooks import quest_log as quest_log_mod

        # 안전 표 판정은 `asgard_hooklib.runners` 에 있다. `quest_log` 는 소비처가 쓰던 이름 일부만
        # 다시 세워 두는 자리라 이 이름은 거기 없다 — 그쪽으로 부르면 AttributeError 가 아래 except
        # 에 삼켜져 이 행이 통째로 사라진다.
        from ...hooks.asgard_hooklib.runners import configured_checks

        policy = quest_log_mod.load_policy(root)
        if not policy.get("baseline_checks"):
            return _auto_baseline_check(root, policy, quest_log_mod)
        accepted, rejected = configured_checks(policy)
    except Exception:
        return None
    if not rejected:
        return {
            "name": "baseline checks",
            "ok": True,
            "detail": f"{len(accepted)}개 실행 대상",
            "fix": "",
        }
    return {
        "name": "baseline checks",
        "ok": False,
        "detail": f"{len(accepted)}개 실행 · 안전 표 밖이라 실행하지 않은 것 {len(rejected)}개: "
        + ", ".join(cmd[:60] for cmd in rejected[:3]),
        "fix": "체크는 테스트 러너 형상만 실행돼요 — `pytest …` / `python -m pytest …` / "
        "`uv run pytest …` 형태로 적어 주세요 (셸 합성·스크립트 직접 실행은 거부해요)",
    }


def _quest_log_writable_check(root: str) -> dict:
    """퀘스트 로그를 놓을 자리가 쓰기 가능한가 — 못 쓰면 기록이 통째로 사라진다."""
    writable = os.access(root, os.W_OK)
    return {
        "name": ".asgard quest-log writable",
        "ok": writable,
        "detail": os.path.join(root, ".asgard") if writable else "not writable",
        "fix": "프로젝트 루트 쓰기 권한 확인",
    }


def _workspace_trust_check(root: str) -> list[dict]:
    """호스트가 이 프로젝트의 권한 선언을 실제로 읽는가.

    `asgard init` 은 `.claude/settings.json` 에 허용 항목을 적어 두는데, Claude Code 는 사람이
    그 폴더를 한 번 신뢰하기 전까지 그 항목을 **통째로 무시한다** — 그리고 그 사실을 실행 첫
    줄에 한 번 말하고 만다 (26-08-05 실측: 갓 init 한 저장소에서 "Ignoring 17 permissions.allow
    entries … this workspace has not been trusted"). 배선은 초록인데 힘이 없는 상태라, doctor 가
    안 보면 아무 표면에도 안 나온다.

    신뢰 여부는 오딘이 정할 일이라 여기서 켜 주지 않는다 — 꺼져 있다는 사실만 말한다."""
    settings = os.path.join(root, ".claude", "settings.json")
    if not os.path.isfile(settings):
        return []
    try:
        with open(settings, encoding="utf-8") as handle:
            declared = ((_json.load(handle) or {}).get("permissions") or {}).get("allow") or []
    except Exception:
        return []
    if not isinstance(declared, list) or not declared:
        return []
    record = os.path.join(os.path.expanduser("~"), ".claude.json")
    trusted: object = None
    try:
        with open(record, encoding="utf-8") as handle:
            projects = (_json.load(handle) or {}).get("projects") or {}
        entry = projects.get(os.path.realpath(root)) or projects.get(root) or {}
        trusted = entry.get("hasTrustDialogAccepted")
    except Exception:
        return []  # 기록을 못 읽으면 말하지 않는다 — 추측으로 경고하지 않는다
    return [
        {
            "name": "workspace trust (CC)",
            "ok": bool(trusted),
            "detail": (
                f"허용 항목 {len(declared)}개가 힘을 받고 있어요"
                if trusted
                else f"허용 항목 {len(declared)}개를 Claude Code 가 무시해요 — 이 폴더가 아직 신뢰되지 않았어요"
            ),
            "fix": "이 폴더에서 claude 를 한 번 대화형으로 열어 신뢰 대화상자를 수락해 주세요.",
        }
    ]


# 호스트별 표면 라벨 — 다른 행("mode parity (CC)")과 같은 표기를 쓴다.
_HOST_SURFACES = (("claude-code", ".claude", "CC"), ("cursor", ".cursor", "Cursor"), ("codex", ".codex", "Codex"))


def _verification_independence_check(root: str) -> list[dict]:
    """판정자가 만든 이와 같은 모델로 도는가 — 검증 독립성이 가장 얇아지는 자리.

    자기 선호 편향은 같은 모델이 **자기 산출을** 판정할 때 나온다. 아스가르드는 판정자를 구조로
    떼어 놓지만(무주입·쓰기 가능한 하위 에이전트 금지·해시 물리 대조) 모델까지 떼지는 않아,
    claude-code 는 worker·verifier 가 둘 다 `inherit` 이라 한 모델이 자기 diff 를 심판한다.

    막지 않는다 (`ok` 는 늘 True). 이건 결함이 아니라 **고를 수 있는 선택**인데 아무 표면에도
    안 보여서, 설치한 사람이 판정을 독립이라고 읽는 것이 문제였다 — 배선(`asgard mode`,
    `agent_models.<host>.verifier`, 그리고 외부 제공자로 넘기는 `/bridge`)은 이미 다 있다.
    빨간불로 올리면 기본 설정의 모든 설치가 늘 경고를 달고, 늘 켜진 경고는 아무도 안 읽는다."""
    rows: list[dict] = []
    try:
        from ...templates.agent_models import agent_model
    except Exception:
        return rows
    for host, marker, label in _HOST_SURFACES:
        if not os.path.isdir(os.path.join(root, marker)):
            continue
        try:
            worker = agent_model(root, host, "worker").get("model", "")
            verifier = agent_model(root, host, "verifier").get("model", "")
        except Exception:
            continue
        same = worker == verifier
        rows.append(
            {
                "name": f"verification independence ({label})",
                "ok": True,
                "detail": (
                    f"worker 와 verifier 가 같은 모델({verifier}) — 구조는 분리, 모델은 공유"
                    if same
                    else f"worker={worker} · verifier={verifier} — 교차 모델"
                ),
                "fix": "",
            }
        )
    return rows
