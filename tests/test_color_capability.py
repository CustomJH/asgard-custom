"""색 능력 판정 — 색만이 아니라 UI 전체가 이 한 판정에 달려 있다.

`ui.color_capable()`이 거짓이면 색·인터랙티브 픽커 패널·하단 입력 독·prompt_toolkit 프레임이
한꺼번에 꺼진다. Windows에서 "UI가 통째로 없는 asgard"로 보이던 것이 정확히 이 경로였다.
"""

from __future__ import annotations

import pytest

from asgard import theme, ui


class _Tty:
    def isatty(self) -> bool:
        return True


class _Pipe:
    def isatty(self) -> bool:
        return False


@pytest.fixture
def _clean_env(monkeypatch):
    """환경변수만 씻는다. sys.stdout은 여기서 못 건다 — pytest가 setup/call 국면마다 캡처를
    새로 꽂아 픽스처가 심어둔 stdout을 덮는다 (본문에서 _tty/_pipe로 건다)."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)


def _tty(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout", _Tty())


def _pipe(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout", _Pipe())


def _posix(monkeypatch) -> None:
    monkeypatch.setattr(ui.winterm, "IS_WINDOWS", False)


def _windows(monkeypatch, vt: bool) -> None:
    monkeypatch.setattr(ui.winterm, "IS_WINDOWS", True)
    monkeypatch.setattr(ui.winterm, "enable_vt", lambda: vt)


def test_windows_console_is_color_capable(monkeypatch, _clean_env) -> None:
    """정확히 이 줄이 사용자가 겪은 결함이다 — Windows는 TERM을 안 쓴다.

    TERM 미설정을 dumb으로 읽는 POSIX 규칙을 Windows에 그대로 태우면 Windows Terminal이
    텔레타이프로 판정돼 색·픽커·독·pt가 한꺼번에 꺼진다 (26-07-27 실측).
    """
    _tty(monkeypatch)
    _windows(monkeypatch, vt=True)
    assert ui.color_capable() is True


def test_windows_console_without_vt_stays_plain(monkeypatch, _clean_env) -> None:
    """VT를 못 켜는 콘솔에 ANSI를 뿌리면 화면이 이스케이프 코드로 뒤덮인다."""
    _tty(monkeypatch)
    _windows(monkeypatch, vt=False)
    assert ui.color_capable() is False


def test_no_color_wins_on_windows_without_touching_the_console(monkeypatch, _clean_env) -> None:
    _tty(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(ui.winterm, "IS_WINDOWS", True)
    monkeypatch.setattr(ui.winterm, "enable_vt", lambda: pytest.fail("NO_COLOR 인데 콘솔 모드를 건드렸다"))
    assert ui.color_capable() is False


def test_redirected_stdout_is_never_colored(monkeypatch, _clean_env) -> None:
    _pipe(monkeypatch)
    _windows(monkeypatch, vt=True)
    assert ui.color_capable() is False


def test_posix_still_treats_unset_term_as_dumb(monkeypatch, _clean_env) -> None:
    """무회귀 — docker exec처럼 TERM 없는 자리에 raw 코드가 뜨던 이유는 그대로 남는다."""
    _tty(monkeypatch)
    _posix(monkeypatch)
    assert ui.color_capable() is False


@pytest.mark.parametrize("term,expected", [("dumb", False), ("xterm-256color", True), ("screen", True)])
def test_posix_reads_term(monkeypatch, _clean_env, term: str, expected: bool) -> None:
    _tty(monkeypatch)
    _posix(monkeypatch)
    monkeypatch.setenv("TERM", term)
    assert ui.color_capable() is expected


def test_posix_never_asks_the_windows_console(monkeypatch, _clean_env) -> None:
    _tty(monkeypatch)
    monkeypatch.setattr(ui.winterm, "IS_WINDOWS", False)
    monkeypatch.setattr(ui.winterm, "enable_vt", lambda: pytest.fail("POSIX 에서 kernel32 를 불렀다"))
    monkeypatch.setenv("TERM", "xterm")
    assert ui.color_capable() is True


# — 24bit 판정 (theme._truecolor) —


def test_windows_console_gets_truecolor(monkeypatch, _clean_env) -> None:
    """COLORTERM은 Windows에 없다 — 없다고 256색으로 낮추면 로고 그라디언트가 뭉갠다."""
    monkeypatch.delenv("COLORTERM", raising=False)
    _windows(monkeypatch, vt=True)
    assert theme._truecolor() is True


def test_posix_without_colorterm_falls_back_to_256(monkeypatch, _clean_env) -> None:
    monkeypatch.delenv("COLORTERM", raising=False)
    _posix(monkeypatch)
    assert theme._truecolor() is False


def test_colorterm_still_wins_everywhere(monkeypatch, _clean_env) -> None:
    monkeypatch.setenv("COLORTERM", "truecolor")
    _posix(monkeypatch)
    assert theme._truecolor() is True
