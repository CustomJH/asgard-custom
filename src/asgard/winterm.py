"""Windows 콘솔 배선 — kernel32 를 만지는 유일한 자리.

Windows 는 TERM 을 쓰지 않는다. POSIX 의 능력 판정("TERM 미설정 = dumb")을 그대로 태우면
Windows Terminal 이 텔레타이프로 판정돼 색·인터랙티브 픽커·하단 독·prompt_toolkit 경로가
**한꺼번에** 꺼진다. 사용자가 본 민짜 `asgard start` 화면(번호 입력 메뉴 + 무색 상태줄)이
그 한 줄의 그림자다 (26-07-27 실측).

Windows 의 정본은 환경변수가 아니라 콘솔 핸들이다: VT 처리를 켤 수 있으면 ANSI 를 이해하는
콘솔이고, GetConsoleMode 가 실패하면 파이프·파일이라 애초에 켤 대상이 아니다 — 리다이렉트
판정까지 같은 호출 하나가 답한다.

개발기(macOS/Linux)에서는 이 파일의 어느 줄도 실행되지 않는다. 그래서 ctypes 마샬링 층은
얇게 유지하고(`_std_handle`·`_get_console_mode`·`_set_console_mode`·`_screen_buffer_info`),
판단은 전부 그 위에 둔다 — 위층은 가짜 kernel32 를 끼워 개발기에서 실제로 돌려볼 수 있다.
"""

from __future__ import annotations

import os
from typing import Any

IS_WINDOWS = os.name == "nt"

# WinBase.h — 출력 핸들 모드
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
# WinBase.h — 입력 핸들 모드
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200

STD_INPUT, STD_OUTPUT, STD_ERROR = -10, -11, -12
# INVALID_HANDLE_VALUE = (HANDLE)-1 — c_void_p 로 받으면 워드 크기만큼의 전부-1 정수로 온다
_INVALID = (2**32 - 1, 2**64 - 1)

_K32: Any = None
_VT: bool | None = None  # enable_vt 캐시 — 콘솔 모드는 프로세스당 한 번만 켜면 된다
_MSVCRT: Any = None  # POSIX 에 없는 모듈 — Any 로 지연 보관 (store.py 의 fcntl/msvcrt 선례)


def _msvcrt() -> Any:
    """msvcrt 지연 로드 — 없으면 None (POSIX·임베디드 빌드)."""
    global _MSVCRT
    if _MSVCRT is None:
        try:
            import msvcrt
        except Exception:
            return None
        _MSVCRT = msvcrt
    return _MSVCRT


def _configure(k: Any) -> Any:
    """호출 시그니처 못 박기 — 기본 restype 은 c_int 라 64bit 핸들의 상위 절반이 잘린다.
    잘린 핸들은 예외를 내지 않고 그냥 무효라, 뒤따르는 GetConsoleMode/SetConsoleMode 가 전부
    조용히 실패한다: 색도 독도 안 뜨는데 오류는 한 줄도 없는 상태가 그 결과다."""
    import ctypes

    k.GetStdHandle.restype = ctypes.c_void_p
    k.GetStdHandle.argtypes = [ctypes.c_uint32]
    return k


def _kernel32() -> Any:
    """kernel32 핸들 (지연 로드·캐시). Windows 가 아니거나 못 열면 None — 위층은 전부 폴백."""
    global _K32
    if _K32 is None:
        if not IS_WINDOWS:
            return None
        try:
            import ctypes

            windll = getattr(ctypes, "WinDLL", None)  # POSIX 빌드엔 없는 심볼 — getattr 로 접근
            _K32 = _configure(windll("kernel32", use_last_error=True)) if windll else None
        except Exception:
            return None
    return _K32


def _std_handle(which: int) -> int | None:
    """표준 핸들 정수값 — 못 얻으면 None."""
    k = _kernel32()
    if k is None:
        return None
    try:
        h = k.GetStdHandle(which)
    except Exception:
        return None
    if not h or int(h) in _INVALID:
        return None
    return int(h)


def _get_console_mode(handle: int) -> int | None:
    """현재 콘솔 모드 — 실패면 None. 실패는 곧 '콘솔이 아니다'(파이프·파일 리다이렉트)."""
    k = _kernel32()
    if k is None:
        return None
    try:
        import ctypes

        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)):
            return None
        return int(mode.value)
    except Exception:
        return None


def _set_console_mode(handle: int, mode: int) -> bool:
    k = _kernel32()
    if k is None:
        return False
    try:
        import ctypes

        return bool(k.SetConsoleMode(ctypes.c_void_p(handle), ctypes.c_uint32(mode)))
    except Exception:
        return False


def _screen_buffer_info(handle: int) -> tuple[int, int] | None:
    """(커서 버퍼 Y, 보이는 창 상단 Y) — 실패면 None."""
    k = _kernel32()
    if k is None:
        return None
    try:
        import ctypes

        class _COORD(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class _SMALL_RECT(ctypes.Structure):
            _fields_ = [
                ("Left", ctypes.c_short),
                ("Top", ctypes.c_short),
                ("Right", ctypes.c_short),
                ("Bottom", ctypes.c_short),
            ]

        class _CSBI(ctypes.Structure):
            _fields_ = [
                ("dwSize", _COORD),
                ("dwCursorPosition", _COORD),
                ("wAttributes", ctypes.c_ushort),
                ("srWindow", _SMALL_RECT),
                ("dwMaximumWindowSize", _COORD),
            ]

        info = _CSBI()
        if not k.GetConsoleScreenBufferInfo(ctypes.c_void_p(handle), ctypes.byref(info)):
            return None
        return int(info.dwCursorPosition.Y), int(info.srWindow.Top)
    except Exception:
        return None


def _enable_vt_on(which: int) -> bool:
    """한 핸들에 VT 처리를 켠다 — 이미 켜져 있으면 그대로 True."""
    h = _std_handle(which)
    if h is None:
        return False
    mode = _get_console_mode(h)
    if mode is None:  # 콘솔이 아니다 — 켤 대상이 없다
        return False
    if mode & ENABLE_VIRTUAL_TERMINAL_PROCESSING:
        return True
    return _set_console_mode(h, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING)


def enable_vt() -> bool:
    """콘솔에 ANSI(VT) 처리를 켜고 성공 여부를 돌려준다 — Windows 색 판정의 정본.

    판정은 stdout 이 혼자 정한다. stderr 는 곁다리로 같이 켜되 실패해도 답을 흔들지 않는다:
    stderr 하나가 파일로 물렸다고 화면 UI 를 통째로 끄면 손해가 훨씬 크다.
    """
    global _VT
    if _VT is None:
        _VT = _enable_vt_on(STD_OUTPUT) if IS_WINDOWS else False
        if _VT:
            _enable_vt_on(STD_ERROR)
    return _VT


def cbreak():
    """턴 진행 중 입력 모드 컨텍스트 — 에코·줄 편집을 내려 키를 즉시 흘린다 (POSIX termios 짝).

    ENABLE_PROCESSED_INPUT 은 **남긴다**. 이게 빠지면 Ctrl-C 가 신호가 아니라 그냥 한 글자가
    되고 "Ctrl-C 로 턴 중단" 계약이 조용히 깨진다 (POSIX 쪽 ISIG 유지와 같은 이유). VT 입력을
    켜 두면 화살표가 ESC 시퀀스로 들어와 독의 _decode_keys 가 이미 아는 형식으로 폐기된다.
    """
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        h = _std_handle(STD_INPUT) if IS_WINDOWS else None
        old = _get_console_mode(h) if h is not None else None
        if old is not None and h is not None:
            new = old & ~(ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT)
            new |= ENABLE_PROCESSED_INPUT | ENABLE_VIRTUAL_TERMINAL_INPUT
            _set_console_mode(h, new)
        try:
            yield
        finally:
            if old is not None and h is not None:
                _set_console_mode(h, old)

    return _cm()


def cursor_row() -> int | None:
    """커서의 **화면** 행(1-based) — POSIX 의 CPR(ESC[6n) 대응. 실패면 None (호출부 폴백).

    Windows 는 물어보고 기다릴 필요가 없다. 다만 버퍼 좌표를 보이는 창 기준으로 낮춰야 CPR 과
    같은 수가 나온다 — 스크롤백이 쌓인 콘솔에서 버퍼 Y 를 그대로 쓰면 하단 독이 화면 밖 행에
    그려진다.
    """
    if not IS_WINDOWS:
        return None
    h = _std_handle(STD_OUTPUT)
    if h is None:
        return None
    got = _screen_buffer_info(h)
    if got is None:
        return None
    cursor_y, window_top = got
    return max(1, cursor_y - window_top + 1)


def poll_key(timeout: float = 0.05) -> bytes | None:
    """콘솔에서 키 하나 — UTF-8 바이트. 없으면 timeout 만큼 자고 None.

    `select` 는 Windows 에서 소켓 전용이라 POSIX 리더 스레드가 첫 호출에서 OSError 로 죽는다.
    죽는 방식이 조용해서(데몬 스레드가 사라질 뿐) 턴 중 타이핑이 통째로 유실되는데 화면엔
    아무 흔적이 없다. msvcrt 로 콘솔을 직접 폴링해 같은 _decode_keys 파이프라인에 얹는다.
    """
    import time

    m = _msvcrt()
    if m is None or not m.kbhit():
        time.sleep(timeout)
        return None
    try:
        ch = m.getwch()
        if ch in ("\x00", "\xe0"):  # 기능키 = 접두 + 스캔코드 2바이트 — 짝까지 소비하고 폐기
            if m.kbhit():
                m.getwch()
            return None
    except Exception:
        return None
    return ch.encode("utf-8", "replace")
