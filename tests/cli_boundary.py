"""사용자가 실제로 지나는 경계를 테스트에서 재현한다.

`CliRunner().invoke(app, ...)`는 Typer 앱을 **직접** 부른다 — `cli.main()`을 지나지 않는다.
그런데 아스가르드가 아는 실패를 사람 문장과 종료 코드로 바꾸는 자리가 바로 그 `main()`이다.
그래서 명령이 던진 `AsgardError`를 CliRunner가 자기 예외 처리로 삼켜 종료 코드를 1로 적는
동안, 같은 명령을 터미널에서 친 사용자는 2를 받는다. 그 차이만큼 기존 CLI 테스트는
**사용자와 다른 경계를 재고 있었다**.

여기 헬퍼는 `main()`과 같은 처리를 하고, stdout과 stderr를 갈라서 돌려준다. 두 흐름을 갈라
두는 것이 이 파일의 두 번째 이유다: "기계 JSON이 사람 화면으로 샌다"는 결함은 합쳐 놓은
출력에서는 아예 보이지 않는다. 산출물은 stdout, 사유와 처방은 stderr — 그 경계를 재려면
테스트도 두 흐름을 따로 들고 있어야 한다.
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
from dataclasses import dataclass

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """색 코드를 걷어낸 화면 — Rich 가 칠하는 출력(도움말 표)에 문자열 단언을 걸 때 쓴다.

    로컬에서 파이프로 받으면 색이 꺼지지만 GitHub Actions 러너에서는 Rich 가 CI 를 알아보고
    켠다. 그러면 `--agent` 가 `-`+`-agent` 두 조각으로 칠해져 리터럴 검색이 로컬에서만 통과하는
    테스트가 된다 — 실측(26-08-03): v0.10.2 릴리스 파이프라인이 이것 하나로 멈췄다."""
    return _ANSI.sub("", text)


@dataclass(frozen=True)
class Outcome:
    """한 번의 CLI 실행이 남긴 것 — 종료 코드와 두 흐름."""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        """사람이 화면에서 보는 것 — 두 흐름이 섞여 보이는 그대로."""
        return self.stdout + self.stderr

    @property
    def plain_stdout(self) -> str:
        """색을 걷어낸 stdout — 칠해진 출력에 문자열 단언을 걸 자리."""
        return strip_ansi(self.stdout)


@contextlib.contextmanager
def _surface_state():
    """표면 선언과 조용함을 실행 하나의 수명으로 묶는다 — 실행 전에 끄고, 끝나면 되돌린다.

    `errors.set_json_surface`와 `ui.set_quiet`은 모듈 전역이고, 명령은 `--json`을 받으면
    그것을 켠 채 끝난다. 실측: `--json` 실행 하나가 지나가면 `errors._json_surface`가 True로
    남고, 그 뒤 `--json` 없이 부른 명령의 실패가 사람 문장 대신 JSON으로 나간다. 한 프로세스에서
    여러 번 부르는 테스트에서만 생기는 어긋남이라 여기서 닫는다."""
    from asgard import errors, ui

    before_json, before_quiet = errors._json_surface, ui._QUIET
    errors.set_json_surface(False)
    ui.set_quiet(False)
    try:
        yield
    finally:
        errors.set_json_surface(before_json)
        ui.set_quiet(before_quiet)


@contextlib.contextmanager
def _stdin(text: str):
    """실행 동안 표준 입력을 이 문자열로 갈아 끼운다 (`redirect_stdout`의 입력 쪽 짝)."""
    before = sys.stdin
    sys.stdin = io.StringIO(text)
    try:
        yield
    finally:
        sys.stdin = before


def run_cli(*argv: str, stdin: str | None = None) -> Outcome:
    """`asgard <argv...>`를 프로세스 안에서 돌리되, 경계는 터미널과 같게.

    `cli.main()`을 그대로 부르지 않고 여기서 다시 적는 이유는 `main()`이 `sys.exit`으로 끝나고
    `sys.argv`를 읽기 때문이다 — 테스트가 잡아야 하는 것은 종료 코드지 프로세스 종료가 아니다.
    잡는 예외와 렌더러는 같은 것을 쓰므로, 갈라질 수 있는 것은 인자를 받는 방식뿐이다.
    `prog_name`을 박는 것도 같은 이유다: 안 주면 click이 `sys.argv[0]`을 읽어 사용법 줄에
    러너 이름(`pytest`)을 적고, 그러면 사용자가 보는 문장을 재지 못한다.

    `stdin`을 주면 그 문자열이 그 실행의 표준 입력이 된다 (인자를 생략하면 stdin에서 읽는
    `skills resolve` 같은 명령용). 안 주면 건드리지 않는다 — 입력을 안 읽는 명령에까지 가짜
    스트림을 끼우면 `isatty` 판정이 러너마다 달라진다."""
    from asgard import errors
    from asgard.cli import app

    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.ExitStack() as stack:
        stack.enter_context(_surface_state())
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        if stdin is not None:
            stack.enter_context(_stdin(stdin))
        try:
            app(list(argv), prog_name="asgard", standalone_mode=True)
        except SystemExit as exc:  # click이 정상 종료를 이렇게 낸다
            code = exc.code if isinstance(exc.code, int) else 0
        except errors.AsgardError as exc:
            errors.render_cli(exc)
            code = exc.exit_code
    return Outcome(code, out.getvalue(), err.getvalue())
