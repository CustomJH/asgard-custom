"""doctor — 런타임·PATH 진단, 그리고 스캐폴드된 프로젝트 안에서는 Trinity 자산까지.
프로젝트 검사는 권고다 (경고일 뿐 치명적이지 않다) — AGENTS.md 가 있을 때만 나오므로
프로젝트 밖에서 도는 `asgard doctor` 는 예전 그대로다.

검사 본문은 검사군별 모듈에 있고, 이 파일은 그것들을 모아 한 화면으로 그린다."""

import json as _json
import os
import sys

from ... import __version__, ui
from ...platform import on_path
from .codemap import _codebase_map_check, _custom_manual_check
from .engines import (
    _design_engine_checks,
    _engine_reachable_check,
    _freyja_engine_dir,
    _model_tier_check,
    _office_checks,
)
from .gate import (
    _baseline_checks_check,
    _classify_misroute_check,
    _firing_check,
    _gate_event_check,
    _quest_log_writable_check,
    _route_prior_check,
    _verification_independence_check,
    _workspace_trust_check,
)
from .memory import (
    _bank_reachability_check,
    _injection_budget_check,
    _memory_curator_check,
    _memory_durability_check,
    _memory_semantic_check,
    _personal_memory_check,
    _shared_memory_check,
)
from .wiring import (  # noqa: F401 — 아래 넷은 여기서 안 쓰고 다시 내보내기만 한다
    _PARITY_HOOKS,
    _client_config,
    _client_wiring_checks,
    _einherjar_check,
    _hook_interpreter_check,
    _hook_wired,
    _lagom_mode_check,
    _mode_parity_check,
    _role_agents_check,
    _skill_adapter_check,
    _skill_bank_check,
    _trinity_block_check,
    _trinity_hooks_check,
    _trinity_policy_check,
    _wired_hook_argv,
)

# 검사를 하나씩 직접 부르는 시험(test_doctor_shape·test_mode_parity)이 이 모듈의 속성으로
# 이름을 쥔다. 파일 하나였을 때 닿던 자리에 그대로 있어야 하므로, 여기서 안 쓰는 넷도 위에서
# 같이 받아 둔다 — 지우면 시험이 아니라 `asgard doctor` 를 부르는 바깥 코드가 먼저 깨진다.


def _trinity_checks(root: str) -> list[dict]:
    """Trinity 에셋 진단 — AGENTS.md가 있는 프로젝트에서만. 여기 나열한 순서가 곧 표면 순서다.

    공유 메모리 검사와 **클라이언트 배선 검사**는 AGENTS.md 유무와 무관하다. 앞은 스캐폴드가
    없어도 설정된 프로젝트 메모리가 진단 대상이라서고, 뒤는 AGENTS.md가 배선의 조건이 아니기
    때문이다 — `.claude/`가 있는데 memory-activate가 안 걸린 프로젝트는 스냅샷도 회수도 Stop
    동기화도 한 번을 안 도는데, AGENTS.md 하나가 없다는 이유로 doctor가 그 사실을 통째로
    안 말하고 정책값(`memory inject on`)만 초록으로 보였다. 없는 통로를 켜져 있다고 읽는다.
    `dict | None`을 돌려주는 항목은 그 계층을 못 읽었을 때 빠진다."""
    # 뱅크 상태와 주입 경로는 다른 질문이다 — 앞은 backend 가 살아 있는가, 뒤는 이 저장소의
    # 세션 프롬프트에 그게 들어가는가. 둘이 같이 있어야 "연결은 됐는데 아무 프롬프트에도 안 들어가는"
    # 뱅크가 행 하나로 보인다. 뒤쪽은 정상이면 행을 안 내므로 평소 표면은 안 길어진다.
    memory_rows = [
        row
        for row in (_shared_memory_check(root), _bank_reachability_check(root), _injection_budget_check(root))
        if row
    ]
    if not os.path.exists(os.path.join(root, "AGENTS.md")):
        return _client_wiring_checks(root) + memory_rows
    checks = [
        _trinity_block_check(root),
        _skill_adapter_check(root),
        _trinity_policy_check(root),
        _role_agents_check(root),
        _trinity_hooks_check(root),
    ]
    checks += [row for row in (_custom_manual_check(root), _einherjar_check(root), _lagom_mode_check(root)) if row]
    checks += _client_wiring_checks(root)
    checks += memory_rows
    checks += _codebase_map_check(root)
    checks.append(_quest_log_writable_check(root))
    checks += _classify_misroute_check(root)
    checks += _route_prior_check(root)
    checks += _gate_event_check(root)
    checks += _firing_check(root)
    checks += _skill_bank_check(root)
    checks += _verification_independence_check(root)
    checks += _workspace_trust_check(root)
    return checks


def run_doctor(json_out: bool = False, quiet: bool = False) -> int:
    asgard = on_path("asgard")
    # uv 가 설치 경로의 전제다 — install.sh·install.ps1 이 uv → uv 관리 CPython → asgard 순으로
    # 세운다. 그래서 훅 인터프리터도 uv 가 정본이고(platform.hook_python), uv 가 없으면 시스템
    # 파이썬으로 내려가는 폴백일 뿐이다. 두 줄의 순서를 이 사실에 맞춰 둔다.
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
        _hook_interpreter_check(os.getcwd()),
        {
            "name": "uv on PATH",
            "ok": bool(uv),
            "detail": uv or "not found",
            "fix": (
                "uv 를 깔아 주세요 — https://astral.sh/uv · 선택이 아니라 전제예요: "
                "설치·업데이트(asgard update)·훅 인터프리터·베이스라인 검증이 모두 uv 를 써요"
            ),
        },
    ]
    checks += _engine_reachable_check(os.getcwd())
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
    if baseline := _baseline_checks_check(os.getcwd()):
        checks.append(baseline)
    checks += _trinity_checks(os.getcwd())
    checks += _mode_parity_check(os.getcwd())  # 모드 간 규율 대조
    security_ok = all(ch["ok"] for ch in checks if ch.get("security"))
    # 두 판정을 갈라 둔다. blocking 은 "이 설치를 쓸 수 있는가", ok 는 "전부 초록인가"다.
    # 예전에는 ok 가 PATH·security 만 집계해서, 나머지 항목이 몇 개 빨갛든 종료코드가 0 이고
    # 마지막 줄은 done 이었다 — 자동화가 exit code 로 설치 건전성을 물으면 늘 통과가 나왔다.
    blocking_ok = bool(asgard) and security_ok
    ok = blocking_ok and all(ch["ok"] for ch in checks)
    runtime = f"python {sys.version.split()[0]}"

    return _emit_doctor(checks, ok=ok, blocking_ok=blocking_ok, runtime=runtime, json_out=json_out, quiet=quiet)


def _emit_doctor(checks: list[dict], *, ok: bool, blocking_ok: bool, runtime: str, json_out: bool, quiet: bool) -> int:
    """판정 결과를 표면으로. **판정과 갈라 두는 이유**는 종료코드가 하나라는 것이다 —
    두 표면이 같은 `ok`를 쓰는지 한자리에서 보이지 않으면, 한쪽만 고쳐 두 표면이 다른 답을
    내는 일이 조용히 생긴다 (`--json`이 통과인데 화면은 실패인 doctor는 doctor가 아니다).

    종료코드 0 = 전부 초록, 1 = 이 설치를 못 쓴다(PATH·보안), 2 = 쓸 수는 있고 손볼 항목이 있다.
    2 를 따로 둔 이유는 1 의 뜻을 지키기 위해서다 — 지도가 git-ignore 됐다고 설치 실패로
    보고하면 install 스크립트가 멀쩡한 설치를 되돌린다."""
    wants = [ch["name"] for ch in checks if not ch["ok"]]
    code = 0 if ok else (1 if not blocking_ok else 2)
    if json_out:
        sys.stdout.write(
            _json.dumps(
                {
                    "version": __version__,
                    "runtime": runtime,
                    "ok": ok,
                    "blocking_ok": blocking_ok,
                    "wants_attention": wants,
                    # 훅 매니페스트(engine/hooks/)가 `${FREYJA2_ENGINE}`로 참조하는 경로.
                    # 설치 위치는 버전마다 달라지므로 하드코딩 대신 여기서 읽어 간다.
                    "freyja2_engine": str(_freyja_engine_dir()),
                    "checks": checks,
                },
                indent=2,
            )
            + "\n"
        )
        return code
    if not quiet:
        ui.head(f"doctor · v{__version__} {ui.dim('(' + runtime + ')')}")
    for ch in checks:
        mark = ui.paint("32", "✔") if ch["ok"] else ui.paint("33", "⚠")
        sys.stdout.write(f"  {mark} {ch['name'].ljust(22)} {ui.dim(ch['detail'])}\n")
        if not ch["ok"]:
            sys.stdout.write(f"      {ui.paint(ui._INFO, '→')} {ch['fix']}\n")
    if not quiet:
        if ok:
            ui.done()
        elif not blocking_ok:
            ui.warn("asgard 를 못 찾거나 보안 항목이 막혀 있어요 — 위 → 줄을 보세요.")
        else:
            ui.warn(f"{len(wants)}건이 손을 기다려요 — {', '.join(wants)}")
    return code
