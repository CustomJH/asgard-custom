"""Windows 콘솔 판정 — 개발기에서 영원히 안 보이는 부류라 가짜 kernel32로 실제로 돌린다.

이 결함의 성질이 시험 방식을 정한다: macOS/Linux 에서는 winterm의 어느 줄도 실행되지 않으므로
"POSIX에서 통과했다"가 아무것도 보증하지 않는다. 그래서 판단(어떤 모드를 어떻게 바꾸는가)은
전부 seam 위로 올려 두고, 여기서 Windows 인 척하며 그 판단을 그대로 밟는다. seam 아래 ctypes
마샬링도 한 번은 가짜 kernel32로 태워 본다 — restype 누락처럼 조용히 전부 실패하는 부류가
거기 살기 때문이다.
"""

from __future__ import annotations

import ctypes

import pytest

from asgard import winterm
from asgard.winterm import _configure

VT = winterm.ENABLE_VIRTUAL_TERMINAL_PROCESSING


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch):
    """모듈 캐시(_VT·_K32·_MSVCRT)는 프로세스 수명 캐시라 테스트 간 새는 것을 막는다."""
    monkeypatch.setattr(winterm, "_VT", None)
    monkeypatch.setattr(winterm, "_K32", None)
    monkeypatch.setattr(winterm, "_MSVCRT", None)


def _fake_console(monkeypatch, modes: dict[int, int], *, settable: bool = True) -> list[tuple[int, int]]:
    """핸들→모드 표로 콘솔을 흉내 낸다. modes에 없는 핸들 = 리다이렉트(콘솔 아님).
    반환 리스트에 SetConsoleMode 호출이 기록된다."""
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(winterm, "IS_WINDOWS", True)
    monkeypatch.setattr(winterm, "_std_handle", lambda which: 100 - which)  # -11 → 111 등 안정 사상
    monkeypatch.setattr(winterm, "_get_console_mode", lambda h: modes.get(h))

    def _set(h: int, mode: int) -> bool:
        calls.append((h, mode))
        if not settable:
            return False
        modes[h] = mode
        return True

    monkeypatch.setattr(winterm, "_set_console_mode", _set)
    return calls


_OUT = 100 - winterm.STD_OUTPUT
_ERR = 100 - winterm.STD_ERROR
_IN = 100 - winterm.STD_INPUT


# — enable_vt: Windows 색 판정의 정본 —


def test_enable_vt_is_false_off_windows(monkeypatch) -> None:
    """POSIX 에서는 kernel32를 건드리지도 않는다 — TERM 규칙이 계속 정본."""
    monkeypatch.setattr(winterm, "IS_WINDOWS", False)
    monkeypatch.setattr(winterm, "_std_handle", lambda which: pytest.fail("POSIX 에서 콘솔 핸들을 요구했다"))
    assert winterm.enable_vt() is False


def test_enable_vt_turns_the_flag_on_when_missing(monkeypatch) -> None:
    calls = _fake_console(monkeypatch, {_OUT: 0x0003, _ERR: 0x0003})
    assert winterm.enable_vt() is True
    assert (_OUT, 0x0003 | VT) in calls  # 기존 모드를 보존한 채 VT만 얹는다
    assert (_ERR, 0x0003 | VT) in calls  # stderr도 곁다리로 함께


def test_enable_vt_accepts_a_console_that_already_has_it(monkeypatch) -> None:
    """Windows Terminal은 켜진 채로 준다 — 다시 쓰지 않는다."""
    calls = _fake_console(monkeypatch, {_OUT: 0x0003 | VT, _ERR: 0x0003 | VT})
    assert winterm.enable_vt() is True
    assert calls == []


def test_enable_vt_is_false_when_stdout_is_redirected(monkeypatch) -> None:
    """GetConsoleMode 실패 = 콘솔이 아니다(파이프·파일) — 색이 저절로 꺼진다."""
    _fake_console(monkeypatch, {_ERR: 0x0003})  # stdout만 리다이렉트
    assert winterm.enable_vt() is False


def test_enable_vt_is_false_when_the_console_refuses(monkeypatch) -> None:
    """VT를 모르는 옛 conhost — 쓰기가 실패하면 ANSI를 뿌리지 않는다."""
    _fake_console(monkeypatch, {_OUT: 0x0003}, settable=False)
    assert winterm.enable_vt() is False


def test_redirected_stderr_does_not_veto_the_stdout_verdict(monkeypatch) -> None:
    """`asgard start 2> log` 하나로 화면 UI를 통째로 끄면 손해가 훨씬 크다."""
    _fake_console(monkeypatch, {_OUT: 0x0003})  # stderr 없음
    assert winterm.enable_vt() is True


def test_enable_vt_is_cached(monkeypatch) -> None:
    calls = _fake_console(monkeypatch, {_OUT: 0x0003})
    assert winterm.enable_vt() is True
    assert winterm.enable_vt() is True
    assert len(calls) == 1  # 두 번째는 캐시 — 콘솔 모드는 프로세스당 한 번


# — cbreak: 턴 중 입력 모드 —


def test_cbreak_drops_echo_and_line_editing(monkeypatch) -> None:
    modes = {_IN: winterm.ENABLE_PROCESSED_INPUT | winterm.ENABLE_LINE_INPUT | winterm.ENABLE_ECHO_INPUT}
    calls = _fake_console(monkeypatch, modes)
    with winterm.cbreak():
        applied = calls[0][1]
    assert not applied & winterm.ENABLE_LINE_INPUT
    assert not applied & winterm.ENABLE_ECHO_INPUT
    assert applied & winterm.ENABLE_VIRTUAL_TERMINAL_INPUT  # 화살표가 ESC 시퀀스로


def test_cbreak_keeps_processed_input_so_ctrl_c_stays_a_signal(monkeypatch) -> None:
    """ENABLE_PROCESSED_INPUT이 빠지면 Ctrl-C가 그냥 한 글자가 되고 턴 중단이 조용히 깨진다."""
    calls = _fake_console(monkeypatch, {_IN: winterm.ENABLE_LINE_INPUT})  # 원래 모드에 없어도
    with winterm.cbreak():
        pass
    assert calls[0][1] & winterm.ENABLE_PROCESSED_INPUT  # 우리가 넣는다


def test_cbreak_restores_the_original_mode(monkeypatch) -> None:
    original = winterm.ENABLE_PROCESSED_INPUT | winterm.ENABLE_LINE_INPUT | winterm.ENABLE_ECHO_INPUT
    calls = _fake_console(monkeypatch, {_IN: original})
    with winterm.cbreak():
        pass
    assert calls[-1] == (_IN, original)


def test_cbreak_restores_even_when_the_turn_raises(monkeypatch) -> None:
    """Ctrl-C로 턴을 끊은 뒤 에코 없는 콘솔에 사람을 남겨 두면 셸이 먹통으로 보인다."""
    original = winterm.ENABLE_PROCESSED_INPUT | winterm.ENABLE_ECHO_INPUT
    calls = _fake_console(monkeypatch, {_IN: original})
    with pytest.raises(KeyboardInterrupt):
        with winterm.cbreak():
            raise KeyboardInterrupt
    assert calls[-1] == (_IN, original)


def test_cbreak_is_a_noop_when_stdin_is_redirected(monkeypatch) -> None:
    calls = _fake_console(monkeypatch, {})  # 콘솔 없음
    with winterm.cbreak():
        pass
    assert calls == []


# — cursor_row: CPR 대응 —


def test_cursor_row_is_measured_from_the_visible_window(monkeypatch) -> None:
    """버퍼 Y를 그대로 쓰면 스크롤백이 쌓인 콘솔에서 독이 화면 밖에 그려진다."""
    _fake_console(monkeypatch, {_OUT: VT})
    monkeypatch.setattr(winterm, "_screen_buffer_info", lambda h: (1_200, 1_150))
    assert winterm.cursor_row() == 51


def test_cursor_row_at_the_top_of_an_unscrolled_console(monkeypatch) -> None:
    _fake_console(monkeypatch, {_OUT: VT})
    monkeypatch.setattr(winterm, "_screen_buffer_info", lambda h: (0, 0))
    assert winterm.cursor_row() == 1  # CPR은 1-based


def test_cursor_row_is_none_when_unavailable(monkeypatch) -> None:
    """호출부가 최하단 점프 폴백으로 넘어가는 신호."""
    _fake_console(monkeypatch, {_OUT: VT})
    monkeypatch.setattr(winterm, "_screen_buffer_info", lambda h: None)
    assert winterm.cursor_row() is None


def test_cursor_row_is_none_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(winterm, "IS_WINDOWS", False)
    assert winterm.cursor_row() is None


# — poll_key: msvcrt 리더 —


class _FakeMsvcrt:
    def __init__(self, keys: list[str]) -> None:
        self.keys = list(keys)

    def kbhit(self) -> bool:
        return bool(self.keys)

    def getwch(self) -> str:
        return self.keys.pop(0)


@pytest.fixture
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)


def _install_msvcrt(monkeypatch, keys: list[str]) -> _FakeMsvcrt:
    fake = _FakeMsvcrt(keys)
    monkeypatch.setattr(winterm, "_MSVCRT", fake)
    return fake


def test_poll_key_returns_utf8_bytes(monkeypatch, _no_sleep) -> None:
    _install_msvcrt(monkeypatch, ["가"])
    assert winterm.poll_key() == "가".encode()


def test_poll_key_discards_function_key_pairs(monkeypatch, _no_sleep) -> None:
    """0xE0 접두 뒤 스캔코드를 남기면 다음 폴에서 방향키가 글자로 초안에 박힌다."""
    _install_msvcrt(monkeypatch, ["\xe0", "H", "a"])  # ↑ 그리고 'a'
    assert winterm.poll_key() is None  # 짝까지 소비
    assert winterm.poll_key() == b"a"  # 스캔코드가 새지 않았다


def test_poll_key_returns_none_when_nothing_is_typed(monkeypatch, _no_sleep) -> None:
    _install_msvcrt(monkeypatch, [])
    assert winterm.poll_key() is None


# — seam 아래: ctypes 마샬링 (restype 누락처럼 조용히 전부 실패하는 부류) —


class _FakeKernel32:
    """kernel32 흉내 — byref로 받은 out 파라미터에 실제로 써 넣는다."""

    def __init__(self, mode: int = 0x0003, ok: bool = True) -> None:
        self.mode, self.ok, self.set_to = mode, ok, None
        self.GetStdHandle = _FakeFn(lambda which: 0xFFFF_FFFF_0000_0007)  # 32bit로 자르면 0x7이 된다

    def GetConsoleMode(self, handle, ref) -> int:
        ref._obj.value = self.mode
        return 1 if self.ok else 0

    def SetConsoleMode(self, handle, mode) -> int:
        self.set_to = int(mode.value)
        return 1 if self.ok else 0

    def GetConsoleScreenBufferInfo(self, handle, ref) -> int:
        ref._obj.dwCursorPosition.Y = 40
        ref._obj.srWindow.Top = 10
        return 1 if self.ok else 0


class _FakeFn:
    """restype/argtypes를 받아 두는 ctypes 함수 포인터 흉내."""

    def __init__(self, impl) -> None:
        self.impl, self.restype, self.argtypes = impl, None, None

    def __call__(self, *a):
        got = self.impl(*a)
        return ctypes.c_void_p(got).value if self.restype is ctypes.c_void_p else ctypes.c_int(got).value


def test_std_handle_survives_a_64bit_handle(monkeypatch) -> None:
    """restype를 c_void_p로 못 박지 않으면 상위 32비트가 잘려 뒤 호출이 전부 조용히 실패한다."""
    monkeypatch.setattr(winterm, "IS_WINDOWS", True)
    monkeypatch.setattr(winterm, "_K32", _configure(_FakeKernel32()))
    assert winterm._std_handle(winterm.STD_OUTPUT) == 0xFFFF_FFFF_0000_0007


def test_an_unconfigured_kernel32_would_truncate_the_handle() -> None:
    """위 테스트가 무엇을 증명하는지 고정한다 — _configure를 빼면 실제로 잘린다."""
    assert _FakeKernel32().GetStdHandle(winterm.STD_OUTPUT) == 0x7  # 상위 절반 소실


def test_get_console_mode_reads_the_out_parameter(monkeypatch) -> None:
    monkeypatch.setattr(winterm, "_K32", _FakeKernel32(mode=0x00F7))
    assert winterm._get_console_mode(7) == 0x00F7


def test_get_console_mode_is_none_on_failure(monkeypatch) -> None:
    monkeypatch.setattr(winterm, "_K32", _FakeKernel32(ok=False))
    assert winterm._get_console_mode(7) is None


def test_set_console_mode_passes_the_value_through(monkeypatch) -> None:
    fake = _FakeKernel32()
    monkeypatch.setattr(winterm, "_K32", fake)
    assert winterm._set_console_mode(7, 0x0007 | VT) is True
    assert fake.set_to == 0x0007 | VT


def test_screen_buffer_info_unpacks_cursor_and_window(monkeypatch) -> None:
    monkeypatch.setattr(winterm, "_K32", _FakeKernel32())
    assert winterm._screen_buffer_info(7) == (40, 10)


def test_marshalling_failures_degrade_to_none_check(monkeypatch) -> None:
    """kernel32가 없거나 시그니처가 어긋나도 REPL은 폴백으로 계속 뜬다 — 죽지 않는다."""
    monkeypatch.setattr(winterm, "IS_WINDOWS", False)
    monkeypatch.setattr(winterm, "_K32", None)
    assert winterm._std_handle(winterm.STD_OUTPUT) is None
    assert winterm._get_console_mode(7) is None
    assert winterm._set_console_mode(7, 1) is False
    assert winterm._screen_buffer_info(7) is None


# — REPL 배선 —
#
# winterm이 옳아도 repl이 안 부르면 화면은 그대로다. 세 갈래(커서 조회·입력 모드·키 리더)가
# 실제로 Windows 경로를 타는지 여기서 확인한다. POSIX 경로로 새면 가짜 스트림에서 죽으므로
# 분기 누락이 통과로 보이지 않는다.


class _TtyStream:
    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        raise OSError("Windows 경로가 POSIX fd 를 만졌다")

    def write(self, _s: str) -> int:
        return 0

    def flush(self) -> None:
        pass


def test_repl_cursor_row_asks_the_console_on_windows(monkeypatch) -> None:
    """POSIX는 CPR 왕복 + 100ms 타임아웃이지만 Windows는 그냥 물어보면 된다."""
    from asgard.agent import repl

    monkeypatch.setattr("sys.stdin", _TtyStream())
    monkeypatch.setattr("sys.stdout", _TtyStream())
    monkeypatch.setattr(repl.winterm, "IS_WINDOWS", True)
    monkeypatch.setattr(repl.winterm, "cursor_row", lambda: 17)
    assert repl._cursor_row() == 17


def test_repl_echo_off_switches_console_mode_on_windows(monkeypatch) -> None:
    """안 걸면 턴 중 누른 키가 콘솔 에코로 독 프레임 위에 그대로 찍힌다."""
    from asgard.agent import repl

    calls = _fake_console(monkeypatch, {_IN: winterm.ENABLE_LINE_INPUT | winterm.ENABLE_ECHO_INPUT})
    with repl._echo_off():
        pass
    assert calls, "Windows 인데 콘솔 입력 모드를 건드리지 않았다"
    assert not calls[0][1] & winterm.ENABLE_ECHO_INPUT


def _windows_dock(monkeypatch, keys: list[bytes | None]):
    """키 목록을 다 흘리면 스스로 멈추는 Windows 독 리더."""
    from asgard.agent import repl

    monkeypatch.setattr(repl.winterm, "IS_WINDOWS", True)
    dock = repl._Dock()
    queue = list(keys)

    def _poll(timeout: float = 0.05):
        if not queue:
            dock._stop_reader.set()
            return None
        return queue.pop(0)

    monkeypatch.setattr(repl.winterm, "poll_key", _poll)
    return dock


def test_dock_collects_windows_keystrokes_during_a_turn(monkeypatch) -> None:
    """턴 중 타이핑은 유실되지 않고 다음 프롬프트에 프리필된다 — select 경로면 스레드가 죽어 전부 증발한다."""
    dock = _windows_dock(monkeypatch, [b"h", b"i", None, b"\r"])
    dock._read_keys()
    assert dock.take_pending() == ("hi", True)  # 트레일링 ⏎ = 제출 의사


def test_dock_discards_arrow_keys_split_across_polls(monkeypatch) -> None:
    """한 글자씩 오는 ESC[A를 carry가 붙들지 못하면 '[A'가 초안에 글자로 박힌다."""
    dock = _windows_dock(monkeypatch, [b"a", b"\x1b", b"[", b"A", b"b"])
    dock._read_keys()
    assert dock.take_pending() == ("ab", False)


def test_dock_reader_stops_when_asked(monkeypatch) -> None:
    dock = _windows_dock(monkeypatch, [b"x"] * 5)
    dock._stop_reader.set()
    dock._read_keys()
    assert dock.take_pending() == ("", False)


# — 형상 래칫 —
#
# 이 결함의 성질상 회귀는 개발기에서 절대 안 보인다. 그래서 "윈도우가 POSIX 코드에 닿지
# 않는다"와 "독이 쓰는 ANSI를 윈도우 콘솔이 안다"를 형상으로 못 박는다. 둘 다 깨지면
# 증상이 크래시가 아니라 침묵이라 테스트 말고는 잡을 방법이 없다.

_POSIX_ONLY = {"termios", "select", "fcntl"}
_GUARDED = ("_cursor_row", "_echo_off", "_read_keys")


def _repl_ast():
    """repl 패키지 전체를 한 나무로 — 함수가 어느 파일에 사는지는 이 앵커가 볼 일이 아니다."""
    import ast
    import pathlib

    from asgard.agent import repl

    merged = ast.Module(body=[], type_ignores=[])
    for path in sorted(pathlib.Path(repl.__file__).parent.glob("*.py")):
        merged.body.extend(ast.parse(path.read_text(encoding="utf-8")).body)
    return ast, merged


def _function(tree, name):
    import ast

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} 이 사라졌다 — 앵커를 고쳐라")


@pytest.mark.parametrize("name", _GUARDED)
def test_windows_branch_comes_before_any_posix_call(name: str) -> None:
    """윈도우 분기는 POSIX 코드보다 **먼저** 와야 한다.

    순서가 뒤집히면 윈도우에서 termios/select가 먼저 닿는다. select는 소켓 전용이라 리더
    스레드가 조용히 죽고, termios는 아예 없어 예외로 빠진다 — 둘 다 화면엔 흔적이 없다.
    """
    ast, tree = _repl_ast()
    body = _function(tree, name).body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # 독스트링은 코드가 아니다

    guard = posix = None
    for stmt in body:
        for node in ast.walk(stmt):
            if guard is None and isinstance(node, ast.Attribute) and node.attr == "IS_WINDOWS":
                guard = node.lineno
            if posix is None:
                imported = isinstance(node, ast.Import) and any(a.name in _POSIX_ONLY for a in node.names)
                called = (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in _POSIX_ONLY
                )
                if imported or called:
                    posix = node.lineno

    assert guard is not None, f"{name} 에 윈도우 분기가 없다"
    assert posix is None or guard < posix, f"{name}: POSIX 코드(L{posix})가 윈도우 분기(L{guard})보다 앞선다"


def test_the_dock_only_speaks_ansi_that_windows_understands() -> None:
    """독의 커서 산술은 전부 ANSI로 나간다 — 윈도우 콘솔이 모르는 시퀀스가 하나라도 섞이면
    프레임이 깨지는데, 깨진 화면은 예외를 내지 않는다. 최종 바이트를 Microsoft 문서 집합에 가둔다."""
    import inspect
    import re

    from asgard.agent import repl

    folded = re.sub(r"\{[^{}]*\}", "0", inspect.getsource(repl))  # f-string 표현식은 자리표시자로
    finals = {m.group(1) for m in re.finditer(r"\\x1b\[[0-9;?]*([A-Za-z])", folded)}
    # Microsoft "Console Virtual Terminal Sequences" 중 이 저장소가 쓰는 것 + 키 입력 시퀀스
    documented = set("ABCDEFGHJKSTfmnsu~")
    assert finals <= documented, f"윈도우 콘솔이 모르는 CSI 최종바이트: {sorted(finals - documented)}"
