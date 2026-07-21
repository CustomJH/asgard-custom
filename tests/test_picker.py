"""picker — 인터랙티브 선택 패널 계약.

pt pipe input 으로 키 시퀀스를 실주입해 화살표 이동·타이핑 필터·수동 행·취소를 검증한다.
available() 폴백 게이트는 비-tty 에서 False — 기존 번호 입력 경로 무회귀의 단일 조건.
"""

from __future__ import annotations

import pytest

from asgard import picker
from asgard.picker import Option

OPTS = [
    Option("anthropic", "Anthropic (Claude)", detail="claude-opus-4-8"),
    Option("claude-native", "Claude Code (native CLI)", detail="opus", current=True),
    Option("openai", "OpenAI API", detail="gpt-5.6-sol"),
]


def _run(keys: str, options=OPTS, **kw):
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        pipe.send_text(keys)
        return picker.pick("select a provider", options, **kw)


def test_enter_selects_default_first_option() -> None:
    assert _run("\r") == "anthropic"


def test_arrow_down_moves_cursor_before_enter() -> None:
    assert _run("\x1b[B\r") == "claude-native"


def test_arrow_up_wraps_to_last_option() -> None:
    assert _run("\x1b[A\r") == "openai"


def test_default_index_sets_initial_cursor() -> None:
    assert _run("\r", default=2) == "openai"


def test_typing_filters_and_enter_takes_top_match() -> None:
    assert _run("openai\r") == "openai"


def test_filter_matches_detail_text_too() -> None:
    assert _run("opus\r") == "anthropic"  # claude-opus-4-8 vs opus — 첫 매치


def test_escape_cancels_to_none() -> None:
    assert _run("\x1b") is None


def test_ctrl_c_cancels_to_none() -> None:
    assert _run("\x03") is None


def test_manual_hint_row_returns_raw_query() -> None:
    got = _run("custom/model-x\r", manual_hint='use "{q}" as model ID')
    assert got == "custom/model-x"


def test_no_match_without_manual_ignores_enter_then_cancels() -> None:
    # 매치 0 + 수동 행 없음 — enter 는 no-op, esc 로만 나간다
    assert _run("zzzzz\r\x1b") is None


def test_backspace_reopens_matches() -> None:
    # 'zz' 매치 0 → 백스페이스 2회 → 전체 복귀 → enter = 첫 옵션
    assert _run("zz\x7f\x7f\r") == "anthropic"


def test_empty_options_short_circuits_none() -> None:
    assert picker.pick("empty", []) is None


def test_available_is_false_without_tty(monkeypatch) -> None:
    assert picker.available() is False  # pytest 캡처 하 stdin/stdout 은 tty 가 아니다


def test_available_env_killswitch(monkeypatch) -> None:
    monkeypatch.setenv("ASGARD_PLAIN_SELECT", "1")
    assert picker.available() is False


@pytest.mark.parametrize("query,expect", [("claude", 2), ("네오", 0)])
def test_match_terms_all_required(query: str, expect: int) -> None:
    terms = query.lower().split()
    assert sum(1 for o in OPTS if picker._match(o, terms)) == expect
