#!/usr/bin/env python3
# Asgard hook-dispatch — 한 이벤트의 **주입 훅들**을 프로세스 하나에서 돌린다.
#
# 왜 있는가. 훅 코드 자신의 실행 시간은 1ms 미만인데, 훅 하나를 띄우는 값이 실측 CPU 15.8ms ·
# 벽시계 17.6ms · RSS 20MB 다 (26-08-14, `uv run --no-project python -c pass` 10회 최솟값).
# 그래서 값은 훅 안이 아니라 **프로세스 수**에 있다. UserPromptSubmit 하나에 훅 11개가 뜨고
# 그중 10개가 주입 훅이다.
#
# **가드와 증거 훅은 여기 안 들어온다.** 가드 8종(secret·readonly·git·release·budget·
# subagent·verifier·craft)은 신뢰 경계 판정이라, 한 프로세스로 합치면 임포트 오류 하나가 그
# 이벤트의 가드를 전부 조용히 없앤다. 증거 훅 3종(verifier-context·failure-tracker·
# write-sentinel)은 판정의 입력을 만드는 자리라, 조용히 죽으면 게이트가 **초록인 채** 증거만
# 사라진다. 둘 다 "막아야 할 때 안 막는" 방향의 실패이고 화면에는 아무것도 안 뜬다.
# 여기 들어오는 것은 이미 전부 fail-open 인 주입 훅뿐이다 — 못 나온 주입은 조언이 없는 것이지
# 판정이 뒤집히는 것이 아니다.
#
# 배선 문법: `hook-dispatch.py [-- <훅 경로> [훅 인자...]]...`
# 훅 경로를 통째로 적는 이유는 진단 때문이다 — `doctor` 의 `_HOOK_IN_COMMAND` 가 명령줄에서
# `hooks/<이름>.py` 를 찾아 배선 누락을 잰다. 이름만 적으면 13종이 그 눈에서 통째로 사라지고,
# 그 상태가 초록으로 읽힌다. 조각 안의 인자는 훅에게 **그대로** 간다 — 배선이
# `tutor-note.py claude brief` 라고 적던 것이 `sys.argv[1:]` 에 같은 순서로 서야 한다.
#
# 내는 형식은 Claude Code·Codex 가 공유하는 것 하나다 (`hookSpecificOutput` · `systemMessage`).
# Cursor 는 여기 안 걸린다: 그쪽 `beforeSubmitPrompt` 에는 컨텍스트 통로가 아예 없어서 주입이
# `sessionStart` 에 서고, 통로가 하나뿐이라 사람 표면과 컨텍스트를 한 번에 못 낸다.
#
# 스레드로 도는 이유: 이 호스트는 한 이벤트의 훅들을 **병렬로** 띄운다 (26-08-14 관측 —
# SubagentStart 주입 블록이 배선 순서가 아니라 완료 순서로 이어붙어 왔다). 훅 절반이 `asgard`
# 자식을 기다리는 자리라, 순차로 돌리면 프로세스는 줄지만 벽시계가 합으로 늘어난다.
#
# 출력은 채널별로 하나로 합쳐 낸다. 컨텍스트(평문 stdout · additionalContext)는 "\n" 으로,
# 사람 표면(systemMessage)은 "\n\n" 로 잇는다. 앞의 구분자는 관측값이고(호스트가 훅 둘의
# 주입 사이에 정확히 개행 하나를 넣는다), 뒤는 memory-activate 가 자기 메시지들을 잇는 값과
# 같게 맞춘 것이라 관측이 아니다.
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import threading

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import record, run  # noqa: E402
from asgard_hooklib.inject import JSON_EVENTS  # noqa: E402
from asgard_hooklib.paths import repo_root  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용
    except Exception:
        pass

CTX_JOIN = "\n"
MSG_JOIN = "\n\n"
# 훅 하나가 걸려도 나머지 주입은 나가야 한다. 프로세스가 따로일 때는 호스트의 상한이 그 일을
# 했다 — 합치면 여기서 해야 한다.
HOOK_TIMEOUT = 60.0

_REAL_ARGV = list(sys.argv)
# 저장소 뿌리는 한 번만 찾는다. `repo_root()` 는 `CLAUDE_PROJECT_DIR` 가 없으면 `git rev-parse`
# 를 띄우는데, 훅마다 프로세스가 따로일 때는 그 자식이 훅 수만큼 떴다.
_ROOT = repo_root()


class _Lane(threading.local):
    """이 스레드가 맡은 훅의 stdin·stdout·argv. 메인 스레드에는 없으므로 원래 것이 쓰인다."""

    out = None
    argv = None
    stdin = None


_LANE = _Lane()


class _RoutedStream:
    """`sys.stdout`/`sys.stdin` 자리에 서서 호출을 그 스레드의 것으로 돌린다.

    훅은 `sys.stdout.write` 와 `json.load(sys.stdin)` 을 그대로 쓴다. 스레드마다 다른 파일을
    보게 하려면 그 이름이 가리키는 객체가 스레드를 알아야 한다 — `contextlib.redirect_stdout`
    는 프로세스 전역이라 스레드 둘의 출력이 한 버퍼에 섞인다.
    """

    def __init__(self, attr: str, real: object) -> None:
        self._attr = attr
        self._real = real

    def _target(self):
        return getattr(_LANE, self._attr, None) or self._real

    def __getattr__(self, name):
        return getattr(self._target(), name)


class _RoutedArgv:
    """`sys.argv` 자리. `__getitem__`·`__len__` 은 타입에서 찾으므로 위임으로는 안 잡힌다."""

    def _target(self) -> list:
        return getattr(_LANE, "argv", None) or _REAL_ARGV

    def __getitem__(self, index):
        return self._target()[index]

    def __len__(self) -> int:
        return len(self._target())

    def __iter__(self):
        return iter(self._target())


def segments(argv: list) -> list:
    """`-- <경로> [인자...]` 조각들. `--` 앞은 디스패처 자신의 인자다."""
    out: list = []
    current = None
    for token in argv:
        if token == "--":
            current = []
            out.append(current)
        elif current is not None:
            current.append(token)
    return [segment for segment in out if segment]


def load(path: str):
    """훅 파일을 모듈로 올린다 — 이름에 하이픈이 있어 `import` 로는 못 부른다.

    `__name__` 이 `__main__` 이 아니라서 훅 끝의 `run(...)` 은 안 뛴다. 본문 호출과 계측은
    디스패처가 직접 한다 (`record` 는 메인 스레드에서 — 그 장부는 읽고-고치고-쓰기라
    스레드 둘이 같이 들어가면 한쪽 갱신이 사라진다)."""
    name = "asgard_dispatch_" + os.path.basename(path)[:-3].replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def channels(text: str) -> tuple:
    """훅 하나의 stdout 을 (컨텍스트, 사람 표면) 으로 가른다.

    같은 이벤트에서도 훅마다 형식이 다르다 — UserPromptSubmit 에서 map-activate 는
    `hookSpecificOutput`, lagom-tracker 는 평문, tutor-note 는 `systemMessage` 를 낸다.
    셋을 한 칸에 넣으면 사람에게 보일 문장이 모델 컨텍스트로 새거나 그 반대가 된다."""
    if not text.strip():
        return "", ""
    try:
        data = json.loads(text)
    except Exception:
        return text, ""  # 평문 stdout = 컨텍스트 주입 (SessionStart·UserPromptSubmit 규약)
    if not isinstance(data, dict):
        return text, ""
    context = ""
    spec = data.get("hookSpecificOutput")
    if isinstance(spec, dict):
        context = str(spec.get("additionalContext") or "")
    if not context:
        context = str(data.get("additional_context") or "")
    message = str(data.get("systemMessage") or data.get("user_message") or data.get("followup_message") or "")
    return context, message


def event_of(data: dict) -> str:
    raw = str(data.get("hook_event_name") or "")
    return {
        "sessionStart": "SessionStart",
        "beforeSubmitPrompt": "UserPromptSubmit",
        "subagentStart": "SubagentStart",
        "stop": "Stop",
    }.get(raw, raw)


def call(module, payload: str, argv: list) -> tuple:
    """훅 본문 하나 — (stdout, 죽었는가). 어떤 예외도 여기서 멈춘다.

    프로세스가 따로일 때는 훅 하나가 죽어도 나머지가 계속 도는 것이 공짜였다. 합치면 공짜가
    아니다: 여기서 안 잡으면 예외 하나가 그 이벤트의 주입을 통째로 없앤다."""
    buffer = io.StringIO()
    _LANE.out = buffer
    _LANE.stdin = io.StringIO(payload)
    _LANE.argv = argv
    failed = True
    try:
        try:
            module.main()
        except SystemExit:
            pass  # 훅은 전부 exit 0 으로 끝난다 — 주입 훅에 차단 코드가 없다
        failed = False
    except BaseException:
        pass  # fail-open — 주입 하나의 죽음이 나머지 주입을 데려가지 않는다
    finally:
        _LANE.out = None
        _LANE.stdin = None
        _LANE.argv = None
    return buffer.getvalue(), failed


def emit(out, event: str, context: str, message: str) -> None:
    """합친 것을 한 번에 낸다 — 채널이 둘이면 한 JSON 안에 둘 다 담는다.

    평문 stdout 은 컨텍스트만 있을 때만 쓴다. 사람 표면이 하나라도 있으면 JSON 이어야 하고,
    그러면 컨텍스트도 같은 객체에 실어야 한다 (한 훅이 낼 수 있는 stdout 은 하나다)."""
    body: dict = {}
    if message:
        body["systemMessage"] = message
    if context and (event in JSON_EVENTS or body):
        body["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": context}
    if body:
        out.write(json.dumps(body, ensure_ascii=False) + "\n")
    elif context:
        out.write(context)  # SessionStart — 평문 stdout 이 주입 통로다


def main() -> int:
    # 부르는 쪽이 세워 둔 stdout — `firing.run` 아래에서는 그 계측 버퍼다. 여기서 진짜 stdout 을
    # 잡아 두면 낸 것이 계측을 지나치고, 장부에는 "한 번도 발화 안 한 훅"으로 남는다.
    base = sys.stdout
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    event = event_of(data if isinstance(data, dict) else {})

    loaded = []
    for segment in segments(_REAL_ARGV[1:]):
        path = segment[0]
        name = os.path.basename(path)[:-3] if path.endswith(".py") else os.path.basename(path)
        try:
            loaded.append((name, load(path), list(segment)))
        except Exception:
            record(_ROOT, name, False, True)  # 임포트 실패도 침묵이 아니라 장부에 남는다

    # 두 스트림은 구조적으로 TextIO 를 만족해 억제가 필요 없다. `_RoutedArgv` 는 `list[str]` 이
    # 아니라 그 자리만 남는다 — 안 쓰는 억제를 남기면 검사기가 그것을 다시 경고로 낸다.
    sys.stdout = _RoutedStream("out", base)
    sys.stdin = _RoutedStream("stdin", sys.stdin)
    sys.argv = _RoutedArgv()  # ty: ignore[invalid-assignment]
    results: dict = {}
    threads = []
    for name, module, argv in loaded:
        thread = threading.Thread(
            target=lambda key, mod, args: results.__setitem__(key, call(mod, raw, args)),
            args=(name, module, argv),
            daemon=True,
        )
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join(HOOK_TIMEOUT)
    # 여기서 통로를 되돌리지 않는 이유: 상한에 걸려 아직 도는 스레드의 `sys.stdout.write` 가
    # 자기 버퍼로 가야 한다. 다만 이 함수가 돌아가는 순간 통로는 어차피 풀린다 — 디스패처를
    # 감싸는 `asgard_hooklib/firing.py` 의 `run()` 이 `redirect_stdout` 을 쓰기 때문이다.
    # 늦게 깨어난 훅이 호스트가 읽는 JSON 을 못 깨뜨리는 진짜 근거는 통로가 아니라 수명이다:
    # 스레드가 daemon 이고 `main()` 직후 프로세스가 끝난다. 도달 창은 그 사이뿐이다.

    contexts, messages = [], []
    for name, _module, _argv in loaded:
        text, failed = results.get(name, ("", True))
        context, message = channels(text)
        if context.strip():
            contexts.append(context.rstrip("\n"))
        if message.strip():
            messages.append(message.rstrip("\n"))
        record(_ROOT, name, bool(text), failed)
    emit(base, event, CTX_JOIN.join(contexts), MSG_JOIN.join(messages))
    return 0


if __name__ == "__main__":
    run("hook-dispatch", main)
