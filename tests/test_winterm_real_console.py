"""winterm 을 **진짜 콘솔**에 대고 밟는다 — Windows 러너에서만 도는 층.

test_winterm.py 는 가짜 kernel32 로 판단을 검증한다. 그 방식이 원리적으로 못 닿는 자리가 하나
남는다: **ctypes 마샬링이 실제 Win32 와 맞는가**. `restype` 이 틀려 핸들이 잘리거나
CONSOLE_SCREEN_BUFFER_INFO 필드 순서가 어긋나도 가짜 앞에서는 전부 초록이고, 실기에서만
조용히 전부 실패한다 — 색도 독도 안 뜨는데 오류는 한 줄도 없는 그 상태로.

CI 러너는 stdout 이 파이프라 `GetStdHandle` 이 콘솔을 주지 않는다. 그래서 `CONOUT$`/`CONIN$`
를 직접 열어 표준 핸들에 꽂고(끝나면 원복) 진짜 콘솔 모드를 왕복시킨다.
"""

from __future__ import annotations

import os

import pytest

from asgard import winterm

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows 콘솔이 있어야 의미가 있다")

VT = winterm.ENABLE_VIRTUAL_TERMINAL_PROCESSING

_GENERIC_READ, _GENERIC_WRITE = 0x8000_0000, 0x4000_0000
_SHARE_RW = 0x1 | 0x2
_OPEN_EXISTING = 3


@pytest.fixture
def console(monkeypatch):
    """`CONOUT$`/`CONIN$` 를 열어 winterm 의 핸들 seam 에 물린다 — 끝나면 모드 원복 + 핸들 닫기.

    Win32 표준 핸들 표(`SetStdHandle`)를 갈아끼우는 길은 못 쓴다: pytest 의 fd 캡처가 setup 과
    call 국면 사이에 fd 1·2 를 dup2 하고, Windows CRT 는 그때 표준 핸들을 자동으로 되맞춘다 —
    픽스처가 꽂아 둔 콘솔 핸들이 본문에 들어가기 전에 파이프로 되돌아간다(fd 0 은 안 건드려서
    stdin 만 살아남는 비대칭으로 드러났다, 26-07-27 러너 실측). 그래서 프로세스 전역 상태가
    아니라 `_std_handle` 을 직접 물린다 — 어차피 이 층을 위해 낸 seam 이고, 그 아래 ctypes
    마샬링은 진짜 콘솔 핸들을 그대로 받는다.
    """
    import ctypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)  # ty: ignore[unresolved-attribute]
    k.CreateFileW.restype = ctypes.c_void_p
    k.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.AllocConsole()  # 이미 붙어 있으면 실패한다 — 그게 정상이라 반환값을 안 본다

    def _open(name: str):
        h = k.CreateFileW(name, _GENERIC_READ | _GENERIC_WRITE, _SHARE_RW, None, _OPEN_EXISTING, 0, None)
        return None if not h or int(h) in winterm._INVALID else int(h)

    conout, conin = _open("CONOUT$"), _open("CONIN$")
    if conout is None or conin is None:
        pytest.skip("이 호스트에서 콘솔을 열 수 없다")

    monkeypatch.setattr(winterm, "_VT", None)  # 프로세스 캐시를 비워 새 핸들로 다시 판정
    monkeypatch.setattr(winterm, "_std_handle", lambda which: conin if which == winterm.STD_INPUT else conout)

    out_mode, in_mode = winterm._get_console_mode(conout), winterm._get_console_mode(conin)
    if out_mode is None:
        pytest.skip("CONOUT$ 를 열었지만 콘솔이 아니다")
    try:
        yield conout, conin
    finally:
        winterm._set_console_mode(conout, out_mode)
        if in_mode is not None:
            winterm._set_console_mode(conin, in_mode)
        k.CloseHandle(ctypes.c_void_p(conout))
        k.CloseHandle(ctypes.c_void_p(conin))


def test_std_handle_talks_to_real_kernel32() -> None:
    """seam 을 안 물린 맨 경로 — GetStdHandle 호출·restype 이 실제 kernel32 와 맞물리는지.
    (러너는 stdout 이 파이프라 콘솔 여부는 못 묻는다. 핸들이 나오는 것 자체가 시험 대상.)"""
    winterm._K32 = None  # 캐시를 비워 실제 WinDLL 로드부터 다시
    assert isinstance(winterm._std_handle(winterm.STD_OUTPUT), int)


def test_console_mode_round_trips_on_a_real_handle(console) -> None:
    """진짜 콘솔에 대고 읽고 쓴다 — 가짜 kernel32 가 원리적으로 못 닿는 자리."""
    conout, _ = console
    mode = winterm._get_console_mode(conout)
    assert mode is not None
    assert winterm._set_console_mode(conout, mode | VT) is True
    assert (winterm._get_console_mode(conout) or 0) & VT


def test_enable_vt_actually_sets_the_bit_on_the_console(console) -> None:
    """이 저장소가 Windows 에서 색을 켜는 유일한 경로 — 실물에서 켜지는지 본다."""
    conout, _ = console
    winterm._set_console_mode(conout, (winterm._get_console_mode(conout) or 0) & ~VT)  # 꺼진 상태에서 시작
    assert winterm.enable_vt() is True
    assert (winterm._get_console_mode(conout) or 0) & VT


def test_screen_buffer_info_unpacks_a_real_struct(console) -> None:
    """필드 순서가 어긋나면 엉뚱한 좌표가 나온다 — 커서는 창 안에 있어야 한다."""
    handle = winterm._std_handle(winterm.STD_OUTPUT)
    assert handle is not None
    got = winterm._screen_buffer_info(handle)
    assert got is not None
    cursor_y, window_top = got
    assert cursor_y >= window_top >= 0


def test_cursor_row_is_a_plausible_screen_row(console) -> None:
    import shutil

    row = winterm.cursor_row()
    assert row is not None and row >= 1
    assert row <= max(1, shutil.get_terminal_size((80, 25)).lines) + 1  # 화면 밖이면 독이 안 보인다


def test_the_colour_verdict_is_true_on_a_real_console(console, monkeypatch) -> None:
    """결국 사용자가 보는 것 — 이 판정 하나에 색·픽커·독·pt 가 전부 달려 있다.

    러너는 stdout 이 파이프라 isatty 만 대신 세워 준다(콘솔은 위 픽스처가 진짜로 꽂았다).
    이 단언이 깨지면 Windows 에서 `asgard start` 가 다시 민짜로 뜬다.
    """
    from asgard import ui

    class _Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr("sys.stdout", _Tty())
    assert ui.color_capable() is True


def test_cbreak_round_trips_the_real_input_mode(console) -> None:
    """턴 중 에코를 내렸다가 되돌리는 왕복 — 되돌리기가 실패하면 셸이 먹통으로 보인다."""
    _, conin = console
    before = winterm._get_console_mode(conin)
    with winterm.cbreak():
        during = winterm._get_console_mode(conin)
    after = winterm._get_console_mode(conin)
    assert during is not None and not during & winterm.ENABLE_ECHO_INPUT
    assert during & winterm.ENABLE_PROCESSED_INPUT  # Ctrl-C 가 신호로 남는다
    assert after == before
