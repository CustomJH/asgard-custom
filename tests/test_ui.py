"""터미널 표시 폭 — 줄을 어디서 자를지의 단일 기준 (ui.disp_width / ui.fit).

글자 수와 칸 수가 갈리는 지점이 결함이 나던 자리다: 한국어 한 글자는 두 칸이라 글자 수로 자르면
절반 폭에서 터미널이 줄을 접고, 접힌 자리에서 진행 보드·하단 독의 열 계산이 함께 무너진다.
"""

from __future__ import annotations

import pytest

from asgard import ui


@pytest.mark.parametrize(
    "text,cols",
    [("ascii only", 10), ("한국어", 6), ("mixed 한글 abc", 14), ("", 0)],
)
def test_disp_width_counts_fullwidth_as_two(text: str, cols: int) -> None:
    assert ui.disp_width(text) == cols


def test_fit_returns_short_text_untouched() -> None:
    assert ui.fit("short", 40) == "short"


def test_fit_folds_newlines_into_one_logical_row() -> None:
    """보드 한 줄은 반드시 한 줄이어야 한다 — 개행이 살아 나가면 아래 줄 산술이 어긋난다."""
    assert ui.fit("first\n\n  second   third", 60) == "first second third"


def test_fit_cuts_ascii_to_the_column_budget() -> None:
    got = ui.fit("x" * 40, 10)
    assert got == "x" * 9 + "…"
    assert ui.disp_width(got) == 10


def test_fit_cuts_korean_by_columns_not_characters() -> None:
    got = ui.fit("가나다라마바사", 10)
    assert got == "가나다라…"  # 4글자 = 8칸 + … = 9칸 (두 칸짜리 하나를 더 넣으면 11칸)
    assert ui.disp_width(got) <= 10


def test_fit_never_returns_an_empty_row() -> None:
    assert ui.fit("가나다", 1) == "…"
