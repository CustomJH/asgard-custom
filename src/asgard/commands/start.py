"""start — Asgard 네이티브 터미널 세션 진입점.

Asgard 자체에서 돈다 — 모델은 provider 설정으로 연결하고, Claude Code에 얹지 않는다
(.claude/ 스캐폴드는 Claude Code 사용자용 별개 표면 — 2026-07-03 오딘 정정).

이 모듈의 몫은 프리플라이트: 세션을 열 수 없는 환경이면 처방과 함께 명확한 exit code로
멈춘다 (doctor는 advisory, start는 게이트). 세션 루프 자체는 agent 패키지 몫.
"""

import importlib.util
import os
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from .. import errors, profiles, sandbox, ui
from ..providers import ResolvedProvider, resolve

if TYPE_CHECKING:
    from typing import TextIO

    from ..agent.runtime import TurnEvent, TurnResult


def preflight(
    root: str, provider: str | None = None, model: str | None = None
) -> tuple[list[dict], "ResolvedProvider"]:
    """세션 진입 체크리스트. (checks, resolved) — resolved는 에이전트 루프로 핸드오프."""
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

    sdk_mod: str | None
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
                    "fix": "claude-native는 base_url 미지원 — 프록시+구독 조합은 차단 리스크, config에서 제거",
                }
            )
        sdk_mod = "claude_agent_sdk"
    elif rp.profile.api_mode == "codex_responses":
        from ..openai_codex import login_status

        oauth_ok, detail = login_status()
        checks.append(
            {
                "name": "ChatGPT OAuth",
                "ok": oauth_ok,
                "detail": detail,
                "fix": "asgard auth login openai-native" if not oauth_ok else "",
            }
        )
        sdk_mod = "openai"
    else:
        sdk_mod = "anthropic" if rp.profile.api_mode == "anthropic" else "openai"
    if sdk_mod:
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


def preflight_error(checks: list[dict]) -> errors.PreflightFailed | None:
    """못 넘은 점검을 **하나의 사실**로 묶는다 — 통과했으면 None.

    여태 이 사실은 터미널에 그려진 픽셀로만 존재했다. 그래서 같은 실패를 창이 받으면 쓸 것이
    없었다: 스튜디오는 `asgard run --json`을 자식 프로세스로 띄우는데, 프리플라이트가 막히면
    JSON 대신 색칠된 체크리스트가 stdout에 실려 왔고, 창은 그것을 파싱하지 못한 채 결과 칸에
    통째로 부었다. 그게 사용자가 본 난잡함이다.

    처방은 **첫 번째 못 넘은 항목**의 것을 쓴다. 전부 나열하면 처방이 다시 목록이 되고, 목록은
    사람이 무엇부터 할지 못 고른다 — 나머지는 `detail.checks`에 그대로 있으니 잃지 않는다."""
    failed = [c for c in checks if not c.get("ok")]
    if not failed:
        return None
    names = ", ".join(str(c.get("name") or "?") for c in failed)
    remedy = next((str(c.get("fix")) for c in failed if c.get("fix")), "")
    return errors.PreflightFailed(
        f"세션을 열 수 없어요 — 점검 {len(failed)}건이 막고 있어요 ({names})",
        remedy=remedy,
        detail={"checks": checks},
    )


def _render_failure(checks: list[dict], failure: errors.PreflightFailed) -> None:
    """사람이 보는 얼굴 — 점검표를 먼저, 판정을 마지막에.

    처방을 여기서 또 적지 않는다. 못 넘은 줄 바로 아래에 이미 `→`로 붙어 있고, 같은 문장을
    끝에 한 번 더 쓰면 두 줄 중 어느 쪽이 그 항목의 것인지 사람이 다시 짚어야 한다.
    (JSON 쪽은 반대로 `remedy` 필드가 필요하다 — 거기엔 점검표를 그릴 화면이 없다.)

    판정 전에 stdout을 비우는 이유는 두 흐름이기 때문이다: 점검표는 stdout, 판정은 stderr.
    파이프로 물리면 stdout이 블록 버퍼가 되어, 안 비우면 **판정이 점검표보다 먼저** 찍힌다."""
    _render(checks)
    sys.stdout.write("\n")
    sys.stdout.flush()
    ui.fail(failure.message)


def run_start(
    check_only: bool = False,
    agent: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    cont: bool = False,
    execution: str | None = None,
    sandbox_name: str | None = None,
) -> int:
    root = os.getcwd()
    if agent is not None:
        os.environ.update(profiles.env_overlay(agent))

    # --check는 CI/스모크용 게이트 — 프리플라이트만 돌고 종료 (기존 계약 유지).
    if check_only:
        ui.head("start · preflight")
        checks, _ = preflight(root, provider=provider, model=model)
        failure = preflight_error(checks)
        if failure is None:
            _render(checks)
            ui.done("preflight clean — 세션 진입 가능")
            return 0
        _render_failure(checks, failure)
        return failure.exit_code

    try:
        execution = sandbox.choose_mode(execution)
    except ValueError as exc:
        ui.warn(str(exc))
        return 2
    if execution != "local":
        if provider or model or cont:
            ui.warn(
                "sandbox uses its own provider and conversation state; "
                "--provider, --model, and --continue are not inherited from the host"
            )
        if execution.startswith("container"):
            return sandbox.run_container(root, shared=execution == "container-shared", name=sandbox_name)
        return sandbox.run(root, shared=execution == "sandbox-shared", name=sandbox_name)

    # 기본: 터미널을 바로 켠다. provider 미설정은 세션 안에서 온보딩.
    from .. import i18n
    from ..providers import resolve

    i18n.load_lang(root)  # config [ui] lang → env → 기본 en

    rp = resolve(root, provider=provider, model=model)
    from ..agent import repl

    return repl.run(root, rp, cont=cont)


def run_prompt(
    prompt: str | None,
    provider: str | None = None,
    model: str | None = None,
    json_out: bool = False,
    resume: bool = False,
    quest_id: str | None = None,
    dual: bool = False,
) -> int:
    """headless 단발 실행 — 벤치·CI 표면. ExecutionSession 턴 1회 후 종료.

    모드 B는 라우팅 논리레이어 주입 불가(벤치 실측) — 게이트-우선의 측정·강제 표면은
    이 네이티브 경로다 (하네스가 전이 산출을 코드로 수행, 채택률 100%).
    exit code: 0 정상 / 1 ⚠ 보고(에스컬레이션·중단·예산 소진) / 2 프리플라이트 실패."""
    import json as _json

    root = os.getcwd()
    from .. import i18n

    i18n.load_lang(root)
    checks, rp = preflight(root, provider=provider, model=model)
    failure = preflight_error(checks)
    if failure is not None:
        # `--json`은 **실패에도 JSON**이다. 여기가 여태 계약이 깨지던 자리다: 성공하면 JSON,
        # 막히면 색칠된 체크리스트 — 그래서 이 명령을 자식 프로세스로 띄우는 스튜디오는
        # 실패할 때만 파싱할 것이 없었고, 원문을 그대로 화면에 부었다. 기계가 읽는 표면에서
        # 실패 경로만 사람 말로 새면, 그 표면은 실패를 다룰 수 없는 표면이다.
        if json_out:
            sys.stdout.write(_json.dumps(errors.json_error(failure), ensure_ascii=False) + "\n")
        else:
            _render_failure(checks, failure)
        return failure.exit_code
    os.environ.setdefault("ASGARD_UNATTENDED", "1")  # Canon 8 — headless는 무인, 게이트도 이 신호를 본다
    from ..agent.runtime import ExecutionSession

    sink = sys.stderr if json_out else sys.stdout  # --json: stdout은 최종 JSON 전용
    session = ExecutionSession(rp, root, dual=dual, on_event=_run_events(sink))
    if resume:
        result = session.resume(quest_id)
    else:
        result = session.submit(prompt or "")
    if json_out:
        sys.stdout.write(_run_summary(result))
    else:
        rendered = "" if result.response_streamed else result.text
        sys.stdout.write("\n" + rendered + "\n")
    return 0 if result.ok else 1


def _run_events(sink: "TextIO") -> "Callable[[TurnEvent], None]":
    """공통 턴 이벤트를 기존 headless 활동·출력 표면에 연결한다."""
    from .. import activity
    from ..agent.runtime import TurnFinished, TurnStarted, TurnStatusChanged, TurnText

    def emit(event: "TurnEvent") -> None:
        if isinstance(event, TurnStarted):
            activity.emit(
                "run.start",
                prompt=event.prompt[:400],
                provider=event.provider,
                model=event.model,
                resume=event.resume,
            )
        elif isinstance(event, TurnText):
            sink.write(event.text)
        elif isinstance(event, TurnStatusChanged):
            activity.emit("status", label=event.label)
        elif isinstance(event, TurnFinished):
            activity.emit("run.end", ok=event.ok, wall_s=event.wall_s, tokens=event.tokens)

    return emit


def _run_summary(result: "TurnResult") -> str:
    """`--json`이 stdout에 내놓는 한 덩이 — 이 명령의 기계용 계약."""
    import json as _json

    return (
        _json.dumps(
            {
                "result": result.text,
                # 이 실행이 연 퀘스트 — 없으면 null (DIRECT 턴은 로그를 안 연다). 종전에는 이 값이
                # 어디에도 안 나와서, `--json` 을 소비하는 쪽이 방금 만들어진 로그를 찾을 길이
                # 없었다: 벤치도 스튜디오도 `.asgard/quest/` 를 시각으로 뒤져 짐작해야 했다.
                "quest_id": result.quest_id,
                "tokens": result.tokens,
                "cache_read_tokens": result.cache_read_tokens,  # 프롬프트 캐시 적중분 (~0.1× 과금) — 벤치 비용 산정용
                "cache_prompt_tokens": result.cache_prompt_tokens,
                "wall_s": result.wall_s,
                "provider": result.provider,
                "model": result.model,
            },
            ensure_ascii=False,
        )
        + "\n"
    )
