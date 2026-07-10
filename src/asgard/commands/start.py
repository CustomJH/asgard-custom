"""start — Asgard 네이티브 터미널 세션 진입점 (CUS-135 에픽).

Asgard 자체에서 돈다 — 모델은 provider 설정으로 연결(CUS-141), Claude Code 에 얹지 않는다
(.claude/ 스캐폴드는 Claude Code 사용자용 별개 표면 — 2026-07-03 오딘 정정).

CUS-136 슬라이스: 프리플라이트. 세션을 열 수 없는 환경이면 처방과 함께 명확한 exit code 로
멈춘다 (doctor 는 advisory, start 는 게이트). 세션 루프 자체는 CUS-137.
"""

import importlib.util
import os
import sys

from .. import ui
from ..providers import resolve


def preflight(root: str, provider: str | None = None, model: str | None = None) -> tuple[list[dict], object]:
    """세션 진입 체크리스트. (checks, resolved) — resolved 는 루프(CUS-137)로 핸드오프."""
    rp = resolve(root, provider=provider, model=model)
    checks: list[dict] = [
        {
            "name": "provider",
            "ok": not any("provider" in m for m in rp.missing),
            "detail": f"{rp.profile.display} · {rp.model or '?'} ({rp.source})",
            "fix": rp.missing[0] if rp.missing else "",
        }
    ]
    for m in rp.missing:
        if "provider" in m:
            continue
        key = "API 키" if "API 키" in m else ("base_url" if "base_url" in m else "model")
        checks.append({"name": key, "ok": False, "detail": "missing", "fix": m})
    if rp.api_key_env:
        checks.append({"name": "API 키", "ok": True, "detail": f"${rp.api_key_env}", "fix": ""})

    if rp.profile.api_mode == "claude_cli":
        import shutil

        cli = shutil.which("claude")
        checks.append(
            {
                "name": "claude CLI",
                "ok": bool(cli),
                "detail": cli or "not found",
                "fix": "https://claude.com/claude-code 설치 후 claude /login (구독) 또는 키 export",
            }
        )
        from ..agent.claude_native import detect_auth

        kind, detail = detect_auth()  # 감지만 — 토큰 값은 절대 안 읽는다 (ToS)
        checks.append(
            {
                "name": "인증 (advisory)",
                "ok": kind != "unknown",
                "detail": f"{kind} · {detail}",
                "fix": "claude /login (구독) 또는 CLAUDE_CODE_OAUTH_TOKEN export" if kind == "unknown" else "",
            }
        )
        if rp.base_url:
            checks.append(
                {
                    "name": "base_url",
                    "ok": False,
                    "detail": rp.base_url,
                    "fix": "claude-native 는 base_url 미지원 — 프록시+구독 조합은 차단 리스크, config 에서 제거",
                }
            )
        sdk_mod = "claude_agent_sdk"
    else:
        sdk_mod = "anthropic" if rp.profile.api_mode == "anthropic" else "openai"
    sdk = importlib.util.find_spec(sdk_mod) is not None
    checks.append(
        {
            "name": f"{sdk_mod} SDK",
            "ok": sdk,
            "detail": "importable" if sdk else "not installed",
            "fix": "asgard update (또는 uv tool install asgard --force)",
        }
    )

    # advisory — 없어도 세션은 열린다 (패키지 내장 정체성 사용). 있으면 프로젝트 관례 병합.
    agents_md = os.path.exists(os.path.join(root, "AGENTS.md"))
    checks.append(
        {
            "name": "AGENTS.md (advisory)",
            "ok": True,
            "detail": "프로젝트 관례 병합" if agents_md else "없음 — 내장 정체성 사용 (asgard init 권장)",
            "fix": "",
        }
    )
    return checks, rp


def _render(checks: list) -> None:
    for c in checks:
        mark = ui.paint("32", "✔") if c["ok"] else ui.paint("31", "✘")
        sys.stdout.write(f"  {mark} {c['name'].ljust(22)} {ui.dim(str(c['detail']))}\n")
        if not c["ok"] and c["fix"]:
            sys.stdout.write(f"      {ui.paint(ui._INFO, '→')} {c['fix']}\n")


def run_start(
    check_only: bool = False,
    provider: str | None = None,
    model: str | None = None,
    tui: bool = False,
    plain: bool = False,
) -> int:
    root = os.getcwd()

    # --check 는 CI/스모크용 게이트 — 프리플라이트만 돌고 종료 (기존 계약 유지).
    if check_only:
        ui.head("start · preflight")
        checks, _ = preflight(root, provider=provider, model=model)
        _render(checks)
        if all(c["ok"] for c in checks):
            ui.done("preflight clean — 세션 진입 가능")
            return 0
        ui.warn("세션을 열 수 없습니다 — 위 처방을 적용한 뒤 다시 실행하세요.")
        return 2

    # 기본: 터미널을 바로 켠다 (hermes/opencode 처럼). provider 미설정은 세션 안에서 온보딩.
    from .. import i18n
    from ..providers import resolve

    i18n.load_lang(root)  # config [ui] lang → env → 기본 en

    rp = resolve(root, provider=provider, model=model)
    if tui and not plain:  # 풀스크린 textual TUI (CUS-148, opt-in)
        from ..agent import tui as _tui

        return _tui.run(root, rp)
    from ..agent import repl

    return repl.run(root, rp)
