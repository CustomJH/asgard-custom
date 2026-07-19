"""prompt-toolkit 세션 구성 스모크 — CI 헤드리스 러너용.

Windows 러너엔 콘솔이 없어 Win32Output 이 NoConsoleScreenBufferError 로 죽는다.
파이프 입력 + DummyOutput app session 으로 감싸 구성 경로만 검증한다.
실행: uv run python tests/smoke_pt_session.py
"""

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

with create_pipe_input() as pipe:
    with create_app_session(input=pipe, output=DummyOutput()):
        from asgard.agent import repl

        repl._pt_session()
print("pt session constructed headless OK")
