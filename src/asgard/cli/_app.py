"""루트 Typer 앱과 전역 플래그 — 모든 명령이 반드시 지나는 자리.

그룹 모듈은 여기서 `app`을 받아 자기 명령을 매단다. 앱 객체가 패키지 `__init__`이 아니라
이 파일에 있는 이유는 순환이다: `__init__`이 그룹 모듈을 부르고 그룹 모듈이 `app`을 찾으므로,
앱이 `__init__`에 있으면 절반만 채워진 모듈을 되짚어 읽게 된다."""

import typer

from .. import __version__, i18n

# 도움말 언어를 여기서 정한다. Typer는 데코레이터를 import 시점에 평가하므로 help=t(...)가
# 읽히는 순간에 언어가 이미 정해져 있어야 하고, 명령 안에서 부르는 load_lang은 그보다 늦다.
# 실패해도 조용히 en으로 남는다 (load_lang이 자체 try/except).
i18n.load_lang()

app = typer.Typer(
    name="asgard",
    help="asgard — make anything, your way",
    no_args_is_help=True,
    add_completion=False,  # we ship an explicit `completions` command (byte-compatible with the TS one)
)


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _agent(value: str) -> None:
    """--agent를 ASGARD_PROFILE로 옮긴다 — 하위 명령이 무엇이든 그 에이전트로 돈다.

    is_eager라 하위 명령보다 먼저 실행된다. 홈 해석(profiles.home)은 전부 호출 시점이라
    여기서 env를 세우면 이후 모든 경로가 그 에이전트를 가리킨다 (모듈 상수 캐시 없음)."""
    if not value:
        return
    import os

    from ..profiles import validate

    try:
        os.environ["ASGARD_PROFILE"] = validate(value)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-v", callback=_version, is_eager=True, help="show version and exit"
    ),
    agent: str = typer.Option(
        "",
        "--agent",
        "-A",
        callback=_agent,
        is_eager=True,
        help="run this as one particular agent — it has its own memory, settings and sessions",
    ),
) -> None:
    """Root callback — hosts the global --version / --agent flags.

    여기서 PATH부터 되찾는다. 독에서 띄운 창은 셸을 안 거쳐 사용자 bin 자리를 통째로 잃은 채
    서고, 그러면 `claude`도 `codex`도 없는 기계처럼 보여 **모든 작업이 엔진 없음으로 막힌다**.
    `main()`이 아니라 이 자리인 이유는 문이 하나가 아니기 때문이다 — 콘솔 스크립트가 `app()`을
    직접 부르는 설치본도 있다. 명령이 무엇이든 반드시 지나는 곳은 여기다."""
    from ..platform import ensure_user_path

    ensure_user_path()  # 멱등 — 창이 띄우는 자식(`asgard run`)도 이 PATH를 물려받는다


def main() -> None:
    """터미널의 마지막 방어선 — 아스가르드가 아는 실패는 트레이스백으로 새지 않는다.

    Typer는 명령이 던진 예외를 그대로 위로 올린다. 그래서 여태 `StoreError` 하나가
    사용자 터미널에 40줄짜리 파이썬 스택으로 떨어졌다 — 사용자가 고칠 수 있는 잘못이었는데도
    화면은 "우리가 깨졌다"고 말한 셈이다. 여기서 아는 실패만 골라 사유 한 줄과 처방 한 줄로
    닫고, 그 예외가 정한 종료 코드로 끝낸다.

    **모르는 예외는 그대로 둔다.** 전부 삼키면 진짜 버그의 스택이 사라지고, 그건 진단을
    없애는 것이지 오류 처리가 아니다."""
    import sys

    from .. import errors

    # PATH 되찾기는 `_main` 콜백이 진다 — 이 문으로 안 들어오는 설치본도 있어서다.
    try:
        app()
    except errors.AsgardError as exc:
        errors.render_cli(exc)
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        # Ctrl-C는 사고가 아니다 — 스택을 뱉지 않고 관례대로 130으로 닫는다.
        sys.stderr.write("\n")
        sys.exit(130)
