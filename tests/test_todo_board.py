"""배정 단위 진행 보드 — 여는 목록·상태 전이 한 줄·닫는 최종판의 계약.

보드는 append-only 스트림에 그려진다 (커서를 올려 다시 못 그린다). 그래서 검증 대상은 화면이
아니라 **방출 순서와 각 줄의 내용**이다: 무엇을 몇 개로 쪼갰는지, 지금 무엇이 도는지, 몇 개가
닫혔는지가 줄만 읽어도 복원돼야 한다.
"""

from __future__ import annotations

import pytest

from asgard import i18n
from asgard.agent.heimdall.todo import TodoBoard, files_note


@pytest.fixture(autouse=True)
def _english_surface():
    """기본 언어 고정 — 다른 테스트가 set_lang 한 잔여로 문장이 흔들리지 않게."""
    before = i18n.current()
    i18n.set_lang("en")
    yield
    i18n.set_lang(before)


def _board(**kw):
    out: list[str] = []
    return TodoBoard(out.append, **kw), out


def test_plan_opens_the_full_list_with_pending_marks() -> None:
    board, out = _board()
    board.plan([(1, "parse units"), (2, "wire the board")])
    text = "".join(out)
    assert i18n.t("todo_head", n=2) in text
    assert "· 1  parse units" in text
    assert "· 2  wire the board" in text


def test_single_unit_skips_the_board_entirely() -> None:
    """단위가 하나면 여는 보드는 진행 줄과 같은 말이다 — 두 번 찍으면 그게 소음이다."""
    board, out = _board()
    board.plan([(1, "the whole task")])
    board.close()
    assert out == []


def test_start_marks_running_units_with_their_subtask() -> None:
    """wave 줄의 id 목록만으로는 '지금 무엇이 도는가'가 안 읽힌다 — 과업 문장을 같이 낸다."""
    board, out = _board()
    board.plan([(1, "parse units"), (2, "wire the board")])
    out.clear()
    board.start([1, 2])
    assert "".join(out) == "    ▸ 1  parse units\n    ▸ 2  wire the board\n"


def test_resolved_units_carry_a_running_counter() -> None:
    board, out = _board()
    board.plan([(1, "a"), (2, "b"), (3, "c")])
    out.clear()
    board.mark(1, "done", files_note(2))
    board.mark(2, "failed", i18n.t("todo_unit_retry", e="RuntimeError"))
    assert out[0] == f"    ✓ 1  a · {files_note(2)}  [1/3]\n"
    assert out[1] == f"    ✗ 2  b · {i18n.t('todo_unit_retry', e='RuntimeError')}  [2/3]\n"
    assert board.resolved() == 2 and board.total() == 3


def test_retry_reopens_a_failed_unit_and_the_counter_follows() -> None:
    """재배정은 되돌림이다 — 실패로 세었던 것이 다시 진행으로 돌아가고 카운터도 내려간다."""
    board, _ = _board()
    board.plan([(1, "a"), (2, "b")])
    board.mark(2, "failed", "retrying")
    assert board.resolved() == 1
    board.start([2])
    assert board.resolved() == 0


def test_close_prints_the_final_board_with_a_summary() -> None:
    board, out = _board()
    board.plan([(1, "a"), (2, "b")])
    board.mark(1, "done", files_note(1))
    board.mark(2, "blocked", i18n.t("todo_unit_exhausted"))
    out.clear()
    board.close()
    text = "".join(out)
    assert i18n.t("todo_summary_done", n=1) in text
    assert i18n.t("todo_summary_left", n=1) in text
    assert "✓ 1  a" in text and "⚠ 2  b" in text
    assert "[" not in text  # 최종판은 카운터를 달지 않는다 — 요약이 그 자리를 갖는다


def test_close_is_idempotent() -> None:
    """정상 종료와 finally 정리가 둘 다 닫으러 온다 — 두 번 찍히면 보드가 아니라 로그가 된다."""
    board, out = _board()
    board.plan([(1, "a"), (2, "b")])
    out.clear()
    board.close()
    first = len(out)
    board.close()
    assert len(out) == first and first > 0


def test_unplanned_unit_is_appended_rather_than_dropped() -> None:
    """재개 스냅샷·재배정은 계획에 없던 단위를 늦게 실어 올 수 있다 — 표면에서 사라지면 안 된다."""
    board, out = _board()
    board.plan([(1, "a"), (2, "b")])
    out.clear()
    board.mark(7, "done")
    assert board.total() == 3
    assert out[-1] == "    ✓ 7  7  [1/3]\n"


@pytest.mark.parametrize("subtask", ["x" * 400, "퀘스트 로그 티켓 장부와 같은 목록을 표면에 세운다" * 8])
def test_long_subtask_is_cut_to_the_stream_width(subtask: str) -> None:
    """넘치면 터미널이 접어 버려 보드 정렬이 무너진다 — ANSI 를 입히기 전 원문에서 자른다.
    한국어 한 글자는 두 칸이라 글자 수로 자르면 절반 폭에서 접힌다 — 기준은 표시 폭이다."""
    from asgard import ui

    board, out = _board()
    board.plan([(1, subtask), (2, "b")])
    board.mark(1, "done", files_note(3))
    rows = [line for line in "".join(out).splitlines() if line.strip()]
    assert "…" in rows[1]  # 헤더 다음이 잘린 단위 1
    assert all(ui.disp_width(line) < ui.stream_width() for line in rows)


def test_korean_surface_follows_the_ui_language() -> None:
    i18n.set_lang("ko")
    board, out = _board()
    board.plan([(1, "a"), (2, "b")])
    assert "배정 단위 2개" in "".join(out)


def test_squad_head_key_labels_the_squad_batch() -> None:
    board, out = _board(head_key="todo_squad_head")
    board.plan([("alpha", "a"), ("beta", "b")])
    assert i18n.t("todo_squad_head", n=2) in "".join(out)


@pytest.mark.parametrize("n,expect", [(1, "1 file"), (2, "2 files"), (0, "0 files")])
def test_english_file_count_matches_number(n: int, expect: str) -> None:
    assert files_note(n) == expect
