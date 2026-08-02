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
from dataclasses import dataclass


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


def run_cli(*argv: str) -> Outcome:
    """`asgard <argv...>`를 프로세스 안에서 돌리되, 경계는 터미널과 같게.

    `cli.main()`을 그대로 부르지 않고 여기서 다시 적는 이유는 `main()`이 `sys.exit`으로 끝나고
    `sys.argv`를 읽기 때문이다 — 테스트가 잡아야 하는 것은 종료 코드지 프로세스 종료가 아니다.
    잡는 예외와 렌더러는 같은 것을 쓰므로, 갈라질 수 있는 것은 인자를 받는 방식뿐이다."""
    from asgard import errors, ui
    from asgard.cli import app

    # 새 프로세스에서 시작하는 것과 같은 상태로 — 표면 선언과 조용함은 실행 하나의 수명이다.
    errors.set_json_surface(False)
    ui.set_quiet(False)

    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            app(list(argv), standalone_mode=True)
        except SystemExit as exc:  # click이 정상 종료를 이렇게 낸다
            code = exc.code if isinstance(exc.code, int) else 0
        except errors.AsgardError as exc:
            errors.render_cli(exc)
            code = exc.exit_code
    return Outcome(code, out.getvalue(), err.getvalue())
