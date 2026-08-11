"""doctor — 배선 검사. 클라이언트 설정·훅 인터프리터·역할 계약·3모드 동작 일치."""

import json as _json
import os
import shlex
from typing import NamedTuple

from ...platform import hook_python_argv, hook_python_token
from ...templates.roles import ROLE_AGENTS


def _stale_role_agents(root: str) -> list[str]:
    """구세대 역할 계약을 들고 있는 스캐폴드 파일 이름.

    존재 확인만 하던 검사는 드리프트를 못 봤다 — 26-07-26 실측: helios의 역할 문서 10개 중 7개가
    이전 세대였고(판정자 문서에 JS/TS 실행 레인 문단이 없었다) doctor는 `10/10 present`로 녹색을
    보고했다. 계약은 파일 존재가 아니라 내용이다. 렌더러는 setup/sync와 같은 것을 쓴다."""
    from ...skill_registry import skill_catalog
    from ...templates.roles import claude_agent

    stale: list[str] = []
    for fname, body in ROLE_AGENTS:
        path = os.path.join(root, ".claude", "agents", fname)
        agent = fname.removeprefix("asgard-").removesuffix(".md")
        try:
            expected = claude_agent(body, root) + skill_catalog(root, agent, loader="cli")  # setup과 동일 조립
            with open(path, encoding="utf-8") as handle:
                if handle.read() != expected:
                    stale.append(fname)
        except Exception:
            continue  # 읽기 실패는 존재 검사(missing)가 이미 다룬다 — 여기서 이중 보고하지 않는다
    return stale


# Trinity 에셋은 통째로 설치되고 통째로 갱신되므로 이 계층의 fix는 전부 같은 처방이다.
# 항목별 손복구 절차를 적으면 그 절차가 설치기와 어긋나는 순간 거짓 안내가 된다.
#
# 여기 적히는 명령은 실존해야 한다. `asgard setup --force` 는 실존한 적이 없다 —
# `setup` 은 `setup map` 하나만 가진 typer 그룹이라 그 줄을 그대로 치면 exit 2
# ("No such option: --force") 다. 진단이 내미는 유일한 손짓이 실행되지 않는 명령이면
# 사람은 스스로 명령을 추측하게 되고, 그 추측이 `asgard sync` 면 미등록 저장소에서
# 아무것도 안 깔린 채 성공 줄만 본다 (commands/sync.py `_unregistered_cwd_note`).
_TRINITY_FIX = "asgard init --force 로 Trinity 에셋 재설치"

_TRINITY_HOOKS = (
    "quest-log.py",
    "verifier-gate.py",
    "write-sentinel.py",
    "unattended-context.py",
    "subagent-gate.py",
    "lagom-activate.py",
    "lagom-tracker.py",
    "lagom-subagent.py",
    "lagom-canon.md",
)


class _Client(NamedTuple):
    """배선을 재는 데 필요한 클라이언트 좌표. 이벤트 이름이 클라이언트마다 달라 표로 든다."""

    name: str
    folder: str
    config_name: str
    snapshot_event: str
    recall_event: str
    skill_folder: str


_MEMORY_CLIENTS = (
    _Client("CC", ".claude", "settings.json", "SessionStart", "UserPromptSubmit", ".claude"),
    _Client("Cursor", ".cursor", "hooks.json", "sessionStart", "beforeSubmitPrompt", ".agents"),
    _Client("Codex", ".codex", "config.toml", "SessionStart", "UserPromptSubmit", ".agents"),
)


def _client_config(root: str, folder: str, config_name: str) -> dict:
    """클라이언트 설정 파일. 없거나 못 읽거나 매핑이 아니면 빈 설정 — '배선 없음'으로 판정된다."""
    try:
        path = os.path.join(root, folder, config_name)
        if config_name.endswith(".toml"):
            import tomllib

            with open(path, "rb") as handle:
                config = tomllib.load(handle)
        else:
            with open(path, encoding="utf-8") as handle:
                config = _json.load(handle)
    except Exception:
        return {}
    return config if isinstance(config, dict) else {}


def _hook_wired(config: dict, event: str, marker: str) -> bool:
    """그 이벤트에 그 훅이 걸려 있는가. 설정 형상이 어긋나면 '안 걸림'으로 센다."""
    try:
        return marker in _json.dumps(config.get("hooks", {}).get(event, []))
    except Exception:
        return False


def _wired_hook_argv(root: str) -> list[str] | None:
    """배선 파일에 실제로 적힌 인터프리터 — 훅 스크립트 인자 앞까지. 못 읽으면 None.

    지금 계산한 인터프리터가 아니라 **적혀 있는 것**을 봐야 uv 가 스캐폴드 이후에 옮겨 간
    경우(경로가 굳어 있다)를 잡는다."""
    try:
        entries = _client_config(root, ".claude", "settings.json")["hooks"]["SessionStart"]
        for entry in entries:
            for hook in entry.get("hooks", []):
                command = str(hook.get("command") or "")
                if "hooks/" not in command:
                    continue
                # posix=False — Windows 경로의 역슬래시를 탈출 문자로 먹지 않는다.
                argv = [token.strip('"') for token in shlex.split(command, posix=False)]
                head = [token for token in argv if "hooks/" not in token.replace("\\", "/")]
                return head or None
    except Exception:
        return None
    return None


def _hook_interpreter_check(root: str) -> dict:
    """배선된 훅 인터프리터를 한 번 실제로 돌려 본다 — PATH 조회는 이 자리를 못 본다.

    훅 줄은 doctor 의 PATH 가 아니라 호스트 프로세스의 PATH 에서 돈다. 독·Finder·launchd 가
    띄운 프로세스는 `/usr/bin:/bin:/usr/sbin:/sbin` 넉 줄만 물려받아 `uv` 를 못 찾고, 훅 계약이
    fail-open 이라 exit 127 은 조용히 삼켜진다 — 가드가 전부 꺼진 상태로 doctor 만 초록이었다.
    `-c pass` 는 인터프리터가 서는지만 묻는다."""
    import subprocess

    argv = _wired_hook_argv(root) or hook_python_argv()
    wired = " ".join(argv)
    try:
        proc = subprocess.run(
            [*argv, "-c", "pass"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,  # 인터프리터가 없는 기계에서는 첫 실행이 CPython 을 내려받는다
        )
        ok = proc.returncode == 0
        detail = wired if ok else "exit %s — %s" % (proc.returncode, (proc.stderr or proc.stdout).strip()[:160])
    except Exception as exc:
        ok, detail = False, "%s: %s" % (type(exc).__name__, exc)
    return {
        "name": "%s (hooks)" % hook_python_token(),
        "ok": ok,
        "detail": detail,
        # python.org 를 가리키면 틀린 처방이에요 — 설치가 세운 파이썬은 uv 가 관리하는 것이고,
        # 이 줄이 빨간 건 거의 언제나 uv 가 없거나 배선 뒤에 자리를 옮겼다는 뜻이에요.
        "fix": (
            "훅이 이 명령으로 돌아요 — `%s`. uv 를 깔고(https://astral.sh/uv) `asgard sync` 로 "
            "배선을 다시 써 주세요 (훅 줄에는 이 기계의 uv 절대 경로가 박혀 있어서, uv 가 자리를 "
            "옮기면 다시 써야 해요)" % wired
        ),
    }


def _trinity_block_check(root: str) -> dict:
    """AGENTS.md에 Trinity 블록 표식이 남아 있는가."""
    try:
        with open(os.path.join(root, "AGENTS.md"), encoding="utf-8") as handle:
            txt = handle.read()
    except Exception:
        txt = ""
    found = "asgard:trinity" in txt
    return {
        "name": "trinity block (AGENTS.md)",
        "ok": found,
        "detail": "marker found" if found else "missing",
        "fix": _TRINITY_FIX,
    }


def _skill_adapter_check(root: str) -> dict:
    """설치된 클라이언트 스코프마다 중앙 스킬 매니저 어댑터가 깔려 있는가."""
    adapters = [
        os.path.join(folder, "skills", "asgard-skills", "SKILL.md")
        for folder in (".claude", ".agents")
        if os.path.isdir(os.path.join(root, folder))
    ]
    missing = [path for path in adapters if not os.path.isfile(os.path.join(root, path))]
    return {
        "name": "central skill manager adapters",
        "ok": bool(adapters) and not missing,
        "detail": (
            f"{len(adapters)}/{len(adapters)} clients wired"
            if adapters and not missing
            else "missing: " + ", ".join(missing or ["client skill scope"])
        ),
        "fix": _TRINITY_FIX,
    }


def _trinity_policy_check(root: str) -> dict:
    """통합 설정(trinity_policy 섹션)을 본다 — 구 trinity-policy.json 폴백은 load_project가 흡수한다."""
    ok, detail = False, "missing"
    try:
        from ...settings import load_project

        if isinstance(load_project(root).get("trinity_policy"), dict):
            ok, detail = True, "asgard-setting-project.json (trinity_policy)"
    except Exception:
        detail = "unparseable settings"
    return {"name": "trinity policy", "ok": ok, "detail": detail, "fix": _TRINITY_FIX}


def _role_agents_check(root: str) -> dict:
    """역할 3종 + 딜리버리 계층 — 라이브러리가 소스다. 존재와 계약 현행성을 같이 본다."""
    agents = [fname for fname, _ in ROLE_AGENTS]
    missing = [a for a in agents if not os.path.exists(os.path.join(root, ".claude", "agents", a))]
    stale = _stale_role_agents(root) if not missing else []
    return {
        "name": "trinity role agents",
        "ok": not missing and not stale,
        "detail": (
            f"{len(agents)}/{len(agents)} present · current"
            if not missing and not stale
            else "missing: " + ", ".join(missing)
            if missing
            else f"{len(stale)}/{len(agents)} on an older contract: " + ", ".join(stale[:4])
        ),
        "fix": _TRINITY_FIX if missing else "asgard sync — 스캐폴드를 현행 역할 계약으로 갱신",
    }


def _trinity_hooks_check(root: str) -> dict:
    """훅 파일 존재 + Stop/SubagentStop 게이트 배선. 깔려만 있고 안 걸린 게이트는 게이트가 아니다."""
    missing = [h for h in _TRINITY_HOOKS if not os.path.exists(os.path.join(root, ".claude", "hooks", h))]
    settings = _client_config(root, ".claude", "settings.json")
    gate_wired = _hook_wired(settings, "Stop", "verifier-gate") and _hook_wired(
        settings, "SubagentStop", "subagent-gate"
    )
    ok = not missing and gate_wired
    return {
        "name": "trinity hooks + Stop gate",
        "ok": ok,
        "detail": "wired" if ok else ("missing: " + ", ".join(missing) if missing else "Stop/SubagentStop 미배선"),
        "fix": _TRINITY_FIX,
    }


def _einherjar_check(root: str) -> dict | None:
    """에인헤랴르 — 이 프로젝트에서 누가 일하는가. 이 계층도 조용히 빗나간다: 없는 이름을 배치하면
    그 자리는 말없이 기본으로 돌고, 서브프로세스에 env를 안 넘기면 자식이 남의 홈에 쓴다.
    배치 없음은 결함이 아니다 (ok) — 조용히 빗나가는 두 경우만 ⚠ 로 세운다. 못 읽으면 None."""
    try:
        from ...profiles import active, fallback_warning, listing
        from ...swarm import describe

        d = describe(root)
        agents = listing()
        problems = []
        for miss in d["missing"]:
            scope = miss["scope"] + (f" {miss['key']}" if miss["key"] else "")
            problems.append(f"{scope}에 배치된 {miss['agent']!r}이 이 기계에 없어요 — 그 자리는 기본 에이전트로 돌아요")
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
            detail = "기본 에이전트 하나 — `asgard agent create <이름>`으로 늘릴 수 있어요"
        return {
            "name": "agents (Einherjar)",
            "ok": not problems,
            "detail": detail if not problems else " · ".join(problems),
            "fix": "asgard agent where — 누가 일하고 어느 선언이 이겼는지 대조",
        }
    except Exception:
        return None


def _lagom_mode_check(root: str) -> dict | None:
    """Lagom — resolve 결과 + 세션 상태 표시. 정보성이라 항상 ok (off도 유효한 선택)."""
    try:
        from ...lagom import default_mode, read_state

        st = read_state(root)
        return {
            "name": "lagom mode",
            "ok": True,
            "detail": f"{st or default_mode(root)} ({'session' if st else 'default'})",
            "fix": "",
        }
    except Exception:
        return None


def _memory_wiring_missing(root: str, client: _Client, config: dict) -> list[str]:
    """한 클라이언트의 Memory v3 배선에서 빠진 항목 — 훅 파일·스냅샷·회수·Stop 동기화·스킬.

    행 렌더와 갈라 둔 이유는 두 번째 소비자다: `memory connect` 도 같은 질문을 묻는데
    (이 저장소 세션 프롬프트에 뱅크가 들어가나), 진단 행의 문자열을 되파싱하면 두 답이 갈라진다."""
    stop_event = "stop" if client.name == "Cursor" else "Stop"
    return [
        label
        for ok, label in (
            (os.path.exists(os.path.join(root, client.folder, "hooks", "memory-activate.py")), "hook file"),
            (_hook_wired(config, client.snapshot_event, "memory-activate"), client.snapshot_event),
            (_hook_wired(config, client.recall_event, "memory-activate"), client.recall_event),
            (_hook_wired(config, stop_event, "memory-activate"), "Stop sync"),
            (
                os.path.exists(os.path.join(root, client.skill_folder, "skills", "asgard-memory", "SKILL.md")),
                "asgard-memory skill",
            ),
        )
        if not ok
    ]


def memory_wiring_gaps(root: str) -> list[tuple[str, list[str]]]:
    """설치된 클라이언트마다 (이름, 빠진 배선 항목). 안 깔린 클라이언트는 목록에 없다.

    빈 목록은 "전부 배선됨"이 아니라 **주입할 클라이언트가 하나도 없음**이다. 그래서 자동
    회수의 유무는 `any(not missing for _, missing in gaps)` 로 묻는다 — 한 클라이언트라도
    빠짐없이 걸려 있어야 그 저장소의 세션 프롬프트에 프로젝트 뱅크가 들어간다."""
    rows = []
    for client in _MEMORY_CLIENTS:
        if not os.path.isdir(os.path.join(root, client.folder)):
            continue
        config = _client_config(root, client.folder, client.config_name)
        rows.append((client.name, _memory_wiring_missing(root, client, config)))
    return rows


def _memory_wiring_row(root: str, client: _Client, config: dict) -> dict:
    """한 클라이언트의 Memory v3 배선 진단 행."""
    missing = _memory_wiring_missing(root, client, config)
    return {
        "name": f"memory wiring ({client.name})",
        "ok": not missing,
        "detail": "wired" if not missing else "missing: " + ", ".join(missing),
        "fix": _TRINITY_FIX,
    }


def _map_wiring_row(root: str, client: _Client, config: dict) -> dict:
    """한 클라이언트의 맵 배선. Cursor에는 서브에이전트 시작 이벤트가 없어 preToolUse도 인정한다."""
    stop_event = "stop" if client.name == "Cursor" else "Stop"
    subagent_event = "subagentStart" if client.name == "Cursor" else "SubagentStart"
    subagent = _hook_wired(config, subagent_event, "map-activate") or (
        client.name == "Cursor" and _hook_wired(config, "preToolUse", "map-activate")
    )
    missing = [
        label
        for ok, label in (
            (os.path.exists(os.path.join(root, client.folder, "hooks", "map-activate.py")), "hook file"),
            (_hook_wired(config, client.snapshot_event, "map-activate"), client.snapshot_event),
            (_hook_wired(config, client.recall_event, "map-activate"), client.recall_event),
            (subagent, "SubagentStart"),
            (_hook_wired(config, stop_event, "map-activate"), "Stop refresh"),
        )
        if not ok
    ]
    return {
        "name": f"map wiring ({client.name})",
        "ok": not missing,
        "detail": "wired" if not missing else "missing: " + ", ".join(missing),
        "fix": _TRINITY_FIX,
    }


def _client_wiring_checks(root: str) -> list[dict]:
    """설치된 클라이언트마다 메모리·맵 배선을 독립 진단한다 — 안 깔린 클라이언트는 건너뛴다.

    설정은 클라이언트당 한 번만 읽고 두 행이 나눠 쓴다. 읽기 실패는 그 클라이언트에서만 빈 설정이다."""
    rows: list[dict] = []
    for client in _MEMORY_CLIENTS:
        if not os.path.isdir(os.path.join(root, client.folder)):
            continue
        config = _client_config(root, client.folder, client.config_name)
        rows.append(_memory_wiring_row(root, client, config))
        rows.append(_map_wiring_row(root, client, config))
    return rows


def _skill_bank_check(root: str) -> list[dict]:
    """라이브러리는 성장이 아니라 큐레이션이 자산이다 — stale은 삭제가 아니라 보관 처방."""
    try:
        import time as _time

        from ...evolution import pending_list, unmined_signals
        from ...skill_bank import learned_skills, usage

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
            "fix": "stale 스킬은 asgard evolve archive <name>으로 보관해요 (삭제 아님, 복원 가능)",
        }
    ]


def _stale_skills(skills: dict, use: dict, cutoff: float) -> list[str]:
    return [name for name in skills if _last_seen(name, skills, use) < cutoff]


def _last_seen(name: str, skills: dict, use: dict) -> float:
    """미사용 스킬은 생성일 기준 — 방금 승인된 스킬을 stale로 오판하지 않는다."""
    import calendar as _cal
    import time as _time

    last_used = use.get(name, {}).get("last_used")
    fmt, val = ("%Y-%m-%dT%H:%M:%SZ", last_used) if last_used else ("%Y-%m-%d", skills[name].get("created"))
    try:
        # 기록은 gmtime(UTC) — mktime(로컬 해석)이면 stale 경계가 오프셋만큼 어긋난다
        return _cal.timegm(_time.strptime(str(val), fmt))
    except ValueError, TypeError:
        return _time.time()  # 날짜 불명 = 판정 보류 (fail-open)


# 세 클라이언트가 공유하는 규율 — 한쪽에만 깔린 게이트는 기능이 아니라 드리프트다.
# lagom-statusline.sh는 CC 에만 있는 표면(statusLine)이라 이 표에 없다.
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

    `asgard init`은 한 표에서 세 클라이언트를 깔지만, 옛 스캐폴드가 남은 프로젝트는 한 모드에만
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
        stale = _stale_hook_copies(hooks_dir)
        # 폴더가 있다고 아스가르드가 깔린 것은 아니다 — 클라이언트가 스스로 만드는 자리이기도 하다
        # (CC는 `.claude/settings.local.json` 만으로도 폴더를 만든다). 훅 디렉터리도 없고 배선도
        # 한 줄 없으면 **설치된 적 없는 모드**이므로 드리프트라고 말할 것이 없다 — 그 자리에 경고를
        # 세우면 `asgard sync`를 시켜도 사라지지 않는 영구 경고가 된다 (26-07-31 실측).
        if not os.path.isdir(hooks_dir) and len(unwired) == len(_PARITY_WIRED):
            continue
        # 배선이 같아도 **강제력**은 호스트가 정한다. Cursor 의 `stop` 훅이 낼 수 있는 필드는
        # `followup_message` 하나뿐이고(cursor.com/docs/hooks), 그건 다음 사용자 메시지를 자동
        # 제출하는 통로라 대화형·루프 흐름에서만 작동한다. 일회성 헤드리스(`cursor-agent -p`)는
        # 그 메시지를 받을 턴이 없어 게이트가 차단을 **기록만 하고** 실행은 그대로 끝난다
        # (26-08-05 실측: hvami-mono 에서 orphan-write 를 적어 놓고 exit 0 · 완료 보고).
        # 배선을 "동일 규율"이라고만 적으면 그 한계가 어느 표면에도 안 나온다.
        detail = "동일 규율 배선"
        if client == "Cursor":
            detail += " · Stop 게이트는 여기서 권고예요 — 호스트에 차단 필드가 없어요"
        if missing or unwired or stale:
            parts = []
            if missing:
                parts.append("파일 없음: " + ", ".join(missing[:6]))
            if unwired:
                parts.append("미배선: " + ", ".join(unwired[:6]))
            if stale:
                parts.append("판본 뒤처짐: " + ", ".join(stale[:6]))
            detail = " · ".join(parts)
        checks.append(
            {
                "name": f"mode parity ({client})",
                "ok": not missing and not unwired and not stale,
                "detail": detail,
                "fix": "asgard sync --here — 이 프로젝트의 훅 표를 다시 깐다",
            }
        )
    return checks


def _stale_hook_copies(hooks_dir: str) -> list[str]:
    """배포된 훅이 패키지본과 다른가 — 이름이 같다고 같은 파일은 아니다.

    이 검사가 **이름과 배선만** 보던 판은 판본 드리프트를 통째로 못 봤다: 배포된
    `quest-log.py` 가 패키지본보다 50줄 뒤처져 있어 같은 저장소에서 네이티브와 Claude Code 가
    서로 다른 베이스라인을 검출하고 있었는데, doctor 는 "동일 규율 배선"이라고 적었다
    (26-08-05 감사). 훅은 sync 가 바이트 그대로 복사하므로 내용 비교가 곧 판본 비교다.

    패키지본을 못 읽으면 아무 말도 하지 않는다 — 추측으로 경고하지 않는다."""
    try:
        from ... import hooks as _hooks

        source_dir = os.path.dirname(_hooks.__file__)
    except Exception:
        return []
    stale: list[str] = []
    for name in _PARITY_HOOKS:
        if not name.endswith(".py"):
            continue
        deployed = os.path.join(hooks_dir, name)
        source = os.path.join(source_dir, name.replace("-", "_"))
        if not (os.path.isfile(deployed) and os.path.isfile(source)):
            continue
        try:
            with open(deployed, "rb") as a, open(source, "rb") as b:
                if a.read() != b.read():
                    stale.append(name)
        except OSError:
            continue
    return stale
