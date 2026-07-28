"""성장 기록 판정 앵커 — 물음이 놓인 **뒤**의 규칙을 못박는다.

실행: uv run pytest tests/test_tutor_growth.py

이 층이 조용히 죽는 방식은 되짚기 본체와 또 다르다. 본체는 오탐을 내면 안 읽히지만, 여기는
**세는 방식이 한 칸 틀리면 반대로 동작한다**: 회차를 안 세면 사다리가 제자리를 맴돌고(영원히
1일), 짧은 답을 깊은 답으로 세면 `ok` 세 번에 안내가 꺼지고, 재방문을 코드 생사와 무관하게
놓으면 없는 자리를 열라고 말하게 된다. 셋 다 화면에서는 정상으로 보인다 — 그래서 여기 있는
앵커는 대부분 "안 일어나야 하는 일"을 고정한다.

같이 고정하는 계약 둘: ① **채점하지 않는다** — 답의 옳고 그름은 이 층의 판정 대상이 아니다.
② 접는 것은 지우는 것이 아니다 — 낮춘 탐침도 사실은 계속 화면에 남는다.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest

from asgard import tutor, tutor_growth
from asgard.commands import tutor as tutor_cmd

DAY = tutor_growth.DAY
_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _point(kind: str = "silent-failure", path: str = "app.py", unit: str = "go", ask: str = "왜?") -> dict:
    return {"kind": kind, "path": path, "unit": unit, "ask": ask}


class IdentityTest(unittest.TestCase):
    """물음의 이름은 줄 번호에 안 매인다 — 매이면 어제 답한 것을 오늘 다시 묻는다."""

    def test_the_same_place_keeps_the_same_mark(self):
        self.assertEqual(
            tutor_growth.cid("silent-failure", "a.py", "go"), tutor_growth.cid("silent-failure", "a.py", "go")
        )

    def test_a_different_kind_at_the_same_place_is_a_different_question(self):
        self.assertNotEqual(
            tutor_growth.cid("silent-failure", "a.py", "go"), tutor_growth.cid("todo-left", "a.py", "go")
        )

    def test_the_mark_survives_lines_moving(self):
        """줄이 밀려도 같은 이름이어야 한다 — Checkpoint 는 line 을 이름에 안 넣는다."""
        early = tutor.Checkpoint("todo-left", "a.py", 3, "", "w", "y", "q", "TODO:같은 표식")
        late = tutor.Checkpoint("todo-left", "a.py", 900, "", "w", "y", "q", "TODO:같은 표식")
        self.assertEqual(early.cid, late.cid)

    def test_two_dependencies_in_one_file_are_two_questions(self):
        """실측 결함: `unit` 이 빈 물음은 좌표가 같아 한 이름으로 뭉쳤다 — 답 하나가 둘을 닫았다."""
        first = tutor.Checkpoint("new-dependency", "a.py", 1, "", "w", "y", "q", "requests")
        second = tutor.Checkpoint("new-dependency", "a.py", 2, "", "w", "y", "q", "yaml")
        self.assertNotEqual(first.cid, second.cid)

    def test_two_swallows_in_one_function_are_two_questions(self):
        """같은 함수 안의 삼킴 둘은 `unit` 이 같다 — 예외 종류까지 이름에 들어가야 갈린다."""
        first = tutor.Checkpoint("silent-failure", "a.py", 8, "go", "w", "y", "q", "OSError@go")
        second = tutor.Checkpoint("silent-failure", "a.py", 12, "go", "w", "y", "q", "ValueError@go")
        self.assertNotEqual(first.cid, second.cid)

    def test_a_revisit_keeps_the_name_it_was_opened_with(self):
        """되싣는 경로가 구분자를 안 들고 가면 같은 물음이 새 이름으로 다시 열린다."""
        root = tempfile.mkdtemp()
        with open(os.path.join(root, "a.py"), "w", encoding="utf-8") as handle:
            handle.write("import requests\n")
        rows = [{"kind": "new-dependency", "path": "a.py", "unit": "", "key": "requests", "ask": "왜?"}]
        tutor_growth.note_asked(root, rows, now=1000.0)
        opened = set(tutor_growth.load(root)["open"])
        tutor.revisits(root, now=1000.0 + DAY + 1)
        self.assertEqual(set(tutor_growth.load(root)["open"]), opened)


class CountingTest(unittest.TestCase):
    """중복 호출에 안 부풀고, 때가 되면 정확히 한 번 는다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_asking_twice_in_the_same_window_counts_once(self):
        """훅과 네이티브 루프가 같은 턴에 각자 판정을 돌린다 — 두 벌이 두 번으로 세면 안 된다."""
        tutor_growth.note_asked(self.root, [_point()], now=1000.0)
        state = tutor_growth.note_asked(self.root, [_point()], now=1100.0)
        self.assertEqual(list(state.values()), ["waiting"])
        self.assertEqual(tutor_growth.load(self.root)["topics"]["silent-failure"]["asked"], 1)

    def test_asking_again_after_the_due_date_counts_a_skip(self):
        """때가 되도록 답이 없었다 = 직전 회차는 건너뛴 것. 이 한 칸이 조절의 유일한 음성 신호다."""
        tutor_growth.note_asked(self.root, [_point()], now=1000.0)
        state = tutor_growth.note_asked(self.root, [_point()], now=1000.0 + DAY + 1)
        self.assertEqual(list(state.values()), ["again"])
        row = tutor_growth.load(self.root)["topics"]["silent-failure"]
        self.assertEqual((row["asked"], row["skipped"]), (2, 1))

    def test_the_ladder_widens_instead_of_repeating_daily(self):
        """1→3→7 로 벌어져야 한다. 같은 간격이면 재방문이 아니라 잔소리다."""
        now = 1000.0
        tutor_growth.note_asked(self.root, [_point()], now=now)
        tutor_growth.note_asked(self.root, [_point()], now=now + DAY + 1)
        self.assertEqual(tutor_growth.due(self.root, now + 2 * DAY), [])
        self.assertTrue(tutor_growth.due(self.root, now + DAY + 3 * DAY + 2))

    def test_the_ladder_ends_in_expiry_not_in_forever(self):
        """네 번 물어 네 번 다 답이 없으면 다섯 번째는 없다 — 안 닿는 물음을 영구히 놓지 않는다."""
        now = 1000.0
        for rung in (0.0, 1.0, 4.0, 11.0, 32.0):  # 사다리 1·3·7·21 을 그대로 밟는다
            tutor_growth.note_asked(self.root, [_point()], now=now + rung * DAY + 1)
        data = tutor_growth.load(self.root)
        self.assertEqual(data["open"], {})
        self.assertEqual([c["reason"] for c in data["closed"]], ["expired"])


class AnsweringTest(unittest.TestCase):
    """답은 받되 **채점하지 않는다**. 재는 것은 옮겨 적었는가 하나뿐이다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        tutor_growth.note_asked(self.root, [_point()], now=1000.0)
        self.cid = tutor_growth.cid("silent-failure", "app.py", "go")

    def test_a_wrong_looking_answer_is_still_accepted(self):
        """옳고 그름은 이 층의 판정 대상이 아니다 — 틀린 채점 한 번이면 사람은 이 층을 끈다."""
        ok, _ = tutor_growth.answer(self.root, self.cid, "이건 사실 완전히 틀린 설명이고 근거도 없다 하지만 길다")
        self.assertTrue(ok)

    def test_a_filler_answer_does_not_raise_the_level(self):
        """`ok` 세 번으로 안내를 끌 수 있으면 그건 사용자가 자기를 속이는 통로다."""
        tutor_growth.answer(self.root, self.cid, "ok")
        data = tutor_growth.load(self.root)
        self.assertEqual(data["topics"]["silent-failure"]["answered"], 1)
        self.assertEqual(data["topics"]["silent-failure"]["deep"], 0)
        self.assertEqual(tutor_growth.level(data, "silent-failure"), 1)

    def test_an_answer_that_was_actually_written_raises_the_level(self):
        tutor_growth.answer(
            self.root, self.cid, "네트워크가 죽어도 이 경로는 계속 가야 해서 삼킨다. 화면에는 캐시 값이 남는다."
        )
        data = tutor_growth.load(self.root)
        self.assertEqual(tutor_growth.level(data, "silent-failure"), 2)

    def test_a_prefix_of_the_mark_is_enough(self):
        """여덟 글자를 정확히 옮겨 적게 하면 아무도 안 답한다."""
        ok, _ = tutor_growth.answer(self.root, self.cid[:4], "짧은 앞자리로도 닫혀야 한다 — 여기 적은 이유가 답이다")
        self.assertTrue(ok)

    def test_an_unknown_mark_does_not_pretend_to_close(self):
        ok, message = tutor_growth.answer(self.root, "ffffffff", "아무 말")
        self.assertFalse(ok)
        self.assertIn("ffffffff", message)

    def test_a_dismissal_is_not_an_answer(self):
        """오탐을 답으로 세면 조절이 거꾸로 간다 — 안 맞는 탐침이 '가르친 것'으로 기록된다."""
        tutor_growth.dismiss(self.root, self.cid, "여긴 의도된 fail-open")
        row = tutor_growth.load(self.root)["topics"]["silent-failure"]
        self.assertEqual((row["answered"], row["dismissed"]), (0, 1))


class FadingTest(unittest.TestCase):
    """말은 줄어드는 쪽으로만 움직인다. 그리고 줄어든 사실은 화면에 남는다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def _topic(self, kind: str, **counts):
        data = tutor_growth.load(self.root)
        data["topics"][kind] = {"asked": 0, "answered": 0, "deep": 0, "skipped": 0, "dismissed": 0, **counts}
        tutor_growth.save(self.root, data)
        return tutor_growth.load(self.root)

    def test_an_owned_kind_folds(self):
        data = self._topic("silent-failure", asked=5, answered=3, deep=3)
        self.assertEqual(tutor_growth.level(data, "silent-failure"), 3)
        self.assertEqual(tutor_growth.form(data, "silent-failure"), "fold")

    def test_a_kind_answered_once_drops_the_why_but_keeps_the_question(self):
        data = self._topic("todo-left", asked=2, answered=1, deep=1)
        self.assertEqual(tutor_growth.form(data, "todo-left"), "ask")

    def test_a_kind_never_answered_stays_full(self):
        data = self._topic("new-dependency", asked=2, answered=0)
        self.assertEqual(tutor_growth.form(data, "new-dependency"), "full")

    def test_a_kind_that_never_lands_is_quieted_and_says_so(self):
        """스스로 낮추되 조용히 끄지는 않는다 — 이유가 없으면 사용자는 자기가 뭘 껐는지 모른다."""
        data = self._topic("todo-left", asked=6, skipped=5, deep=0)
        self.assertEqual(tutor_growth.form(data, "todo-left"), "quiet")
        self.assertIn("5번", tutor_growth.quiet_reason(data, "todo-left"))

    def test_repeated_false_alarms_also_quiet_the_probe(self):
        data = self._topic("untested-surface", asked=4, dismissed=3)
        self.assertIn("오탐", tutor_growth.quiet_reason(data, "untested-surface"))

    def test_a_quieted_kind_is_still_counted_in_the_summary(self):
        """접힘은 삭제가 아니다 — 요약에서 사라지면 '0건'과 구별이 안 된다."""
        self._topic("todo-left", asked=6, skipped=5)
        summary = tutor_growth.summary(self.root)
        self.assertIn("todo-left", {row["kind"] for row in summary["topics"]})
        self.assertIn("todo-left", summary["quiet"])


class AngleTest(unittest.TestCase):
    """같은 문장을 네 번째로 놓는 것은 재방문이 아니라 반복이다."""

    def test_the_second_pass_asks_a_different_question(self):
        first = tutor.Checkpoint("silent-failure", "a.py", 1, "go", "w", "y", "원래 물음")
        second = tutor.angled(first, asks=2)
        self.assertNotEqual(second.ask, first.ask)
        self.assertIn(second.ask, tutor.ANGLES["silent-failure"])

    def test_the_first_pass_keeps_the_original_wording(self):
        first = tutor.Checkpoint("silent-failure", "a.py", 1, "go", "w", "y", "원래 물음")
        self.assertEqual(tutor.angled(first, asks=1).ask, "원래 물음")

    def test_running_out_of_angles_holds_the_last_one_instead_of_crashing(self):
        first = tutor.Checkpoint("silent-failure", "a.py", 1, "go", "w", "y", "원래 물음")
        self.assertEqual(tutor.angled(first, asks=99).ask, tutor.ANGLES["silent-failure"][-1])

    def test_a_kind_without_angles_keeps_its_only_question(self):
        odd = tutor.Checkpoint("no-such-kind", "a.py", 1, "", "w", "y", "원래 물음")
        self.assertEqual(tutor.angled(odd, asks=3).ask, "원래 물음")


class RevisitTest(unittest.TestCase):
    """돌아오는 물음은 **코드가 아직 거기 있을 때만** 돌아온다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        with open(os.path.join(self.root, "live.py"), "w", encoding="utf-8") as handle:
            handle.write("def go():\n    return 1\n")

    def test_a_question_on_living_code_comes_back(self):
        tutor_growth.note_asked(self.root, [_point(path="live.py", unit="go")], now=1000.0)
        back = tutor.revisits(self.root, now=1000.0 + DAY + 1)
        self.assertEqual([r.unit for r in back], ["go"])

    def test_a_question_on_deleted_code_expires_instead_of_coming_back(self):
        """없는 자리를 열어 보라고 두 번 말하면 사용자는 이 카드를 통째로 안 믿는다."""
        tutor_growth.note_asked(self.root, [_point(path="gone.py", unit="vanished")], now=1000.0)
        self.assertEqual(tutor.revisits(self.root, now=1000.0 + DAY + 1), [])
        closed = tutor_growth.load(self.root)["closed"]
        self.assertEqual([c["reason"] for c in closed], ["gone"])

    def test_a_question_asked_again_this_turn_is_not_also_shown_as_a_revisit(self):
        """위아래에 같은 물음이 두 번 실리면 읽는 쪽은 두 건으로 세고, 그 화면은 안 읽힌다."""
        tutor_growth.note_asked(self.root, [_point(path="live.py", unit="go")], now=1000.0)
        mark = tutor_growth.cid("silent-failure", "live.py", "go")
        self.assertEqual(tutor.revisits(self.root, now=1000.0 + DAY + 1, skip=[mark]), [])

    def test_showing_a_revisit_reschedules_it(self):
        """보여 준 것은 물은 것이다 — 예약을 안 밀면 다음 턴에도 같은 것이 또 나온다."""
        tutor_growth.note_asked(self.root, [_point(path="live.py", unit="go")], now=1000.0)
        later = 1000.0 + DAY + 1
        self.assertTrue(tutor.revisits(self.root, now=later))
        self.assertEqual(tutor.revisits(self.root, now=later + 60), [])


class BriefTest(unittest.TestCase):
    """앞서 말하는 층 — 가리키는 자리에만 말한다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        with open(os.path.join(self.root, "heimdall.py"), "w", encoding="utf-8") as handle:
            handle.write("def dispatch():\n    return 1\n")
        tutor_growth.note_asked(self.root, [_point(path="heimdall.py", unit="dispatch")], now=1000.0)

    def test_a_request_naming_the_place_gets_the_open_question(self):
        self.assertIn("heimdall.py", tutor.brief(self.root, "heimdall 쪽 라우팅 고쳐줘"))

    def test_a_request_about_something_else_stays_silent(self):
        """아무 요청에나 남의 물음이 붙으면 이 줄은 배경 소음이 된다."""
        self.assertEqual(tutor.brief(self.root, "릴리스 노트 초안 써줘"), "")

    def test_a_bare_structural_word_does_not_match_the_whole_tree(self):
        """`src` 한 조각에 나무 전체가 걸리면 브리핑은 매 턴 나오고, 매 턴 나오면 안 읽힌다."""
        with open(os.path.join(self.root, "src_thing.py"), "w", encoding="utf-8") as handle:
            handle.write("x = 1\n")
        tutor_growth.note_asked(self.root, [_point(path="src/deep/mod.py", unit="fn")], now=1000.0)
        self.assertEqual(tutor.brief(self.root, "src 정리 좀"), "")

    def test_named_paths_beat_guessing(self):
        card = tutor.brief(self.root, "", ["heimdall.py"])
        self.assertIn("heimdall.py", card)

    def test_no_open_questions_means_no_card(self):
        self.assertEqual(tutor.brief(tempfile.mkdtemp(), "heimdall 고쳐줘"), "")

    def test_the_hook_path_stays_completely_silent_when_there_is_nothing(self):
        """훅에게 "없다"는 말은 사용자 화면에 실릴 빈 카드가 된다 — 빈 카드는 다음 카드의 신뢰를 깎는다.

        `ui.ok` 는 판정 줄이라 quiet 을 무시한다(ui 계약). 실측: 이 한 줄이 훅 출력으로 새어
        무관한 요청마다 "없다" 카드가 떴다.
        """
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            tutor_cmd._run_brief(self.root, "릴리스 노트", (), quiet=True)
        self.assertEqual(buffer.getvalue(), "")

    def test_a_person_typing_it_still_gets_an_answer(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            tutor_cmd._run_brief(self.root, "릴리스 노트", (), quiet=False)
        self.assertIn("없다", buffer.getvalue())


class RecallTest(unittest.TestCase):
    """답이 닫히고 끝나면 이 층은 사람만 자라게 하고 자기는 그대로다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        tutor_growth.note_asked(self.root, [_point(path="client.py", unit="fetch")], now=1000.0)
        self.cid = tutor_growth.cid("silent-failure", "client.py", "fetch")

    def test_the_answer_body_is_kept_not_just_the_fact_of_answering(self):
        tutor_growth.answer(self.root, self.cid, "상류가 죽어도 화면은 캐시로 버텨야 해서 삼킨다", now=2000.0)
        said = tutor_growth.recall(self.root, ["client.py"], now=2000.0)
        self.assertEqual(len(said), 1)
        self.assertIn("캐시로 버텨야", said[0].said)

    def test_a_dismissal_reason_comes_back_too_and_says_it_was_a_dismissal(self):
        """오탐으로 닫은 이유도 다음 사람에게는 정보다 — 다만 답과 같은 줄로 보이면 안 된다."""
        tutor_growth.dismiss(self.root, self.cid, "여긴 의도된 fail-open 이라 판정 대상 아님", now=2000.0)
        said = tutor_growth.recall(self.root, ["client.py"], now=2000.0)
        self.assertTrue(said[0].dismissed)

    def test_another_file_does_not_borrow_the_answer(self):
        tutor_growth.answer(self.root, self.cid, "여기 적어 둔 이유가 있다 그것이 답이다", now=2000.0)
        self.assertEqual(tutor_growth.recall(self.root, ["other.py"], now=2000.0), [])

    def test_an_expired_question_leaves_nothing_to_recall(self):
        """답이 없어서 만료된 물음은 되돌려 줄 문장이 없다 — 빈 인용을 만들지 않는다."""
        for rung in (1.0, 4.0, 11.0, 32.0):
            tutor_growth.note_asked(self.root, [_point(path="client.py", unit="fetch")], now=1000.0 + rung * DAY + 1)
        self.assertEqual(tutor_growth.recall(self.root, ["client.py"], now=9_000_000.0), [])

    def test_the_brief_hands_the_old_answer_back_with_a_date(self):
        """되돌려 줄 뿐 판정하지 않는다 — 그때의 답이 지금도 맞는지는 코드가 바뀌었을 수 있어 모른다."""
        with open(os.path.join(self.root, "client.py"), "w", encoding="utf-8") as handle:
            handle.write("def fetch():\n    return 1\n")
        tutor_growth.answer(self.root, self.cid, "상류가 죽어도 화면은 캐시로 버텨야 해서 삼킨다")
        card = tutor.brief(self.root, "client.py 재시도 손보자")
        self.assertIn("예전에 한 답", card)
        self.assertIn("캐시로 버텨야", card)


class CollectTest(unittest.TestCase):
    """보고서에 손으로 적은 답을 걷는다 — 사람이 실제로 답하는 자리는 편집기다."""

    def test_a_filled_slot_is_collected(self):
        text = "- [ ] **x** — `a.py:1` `abcd1234`\n  - 물음: 왜?\n  - 답: 재시도가 죽은 상류를 가리고 있었다\n"
        self.assertEqual(tutor_cmd.collect(text), {"abcd1234": "재시도가 죽은 상류를 가리고 있었다"})

    def test_an_empty_slot_is_not_collected(self):
        """빈 칸을 답으로 걷으면 안 답한 물음이 답한 것으로 기록된다 — 조절이 통째로 거짓이 된다."""
        text = "- [ ] **x** — `a.py:1` `abcd1234`\n  - 답: \n"
        self.assertEqual(tutor_cmd.collect(text), {})

    def test_a_multi_line_answer_is_joined(self):
        text = "- [ ] **x** — `a.py:1` `abcd1234`\n  - 답: 첫 줄\n    이어지는 줄\n"
        self.assertEqual(tutor_cmd.collect(text), {"abcd1234": "첫 줄 이어지는 줄"})

    def test_answers_do_not_leak_into_the_next_item(self):
        text = "- [ ] **x** — `a.py:1` `aaaaaaaa`\n  - 답: 첫 항목 답\n- [ ] **y** — `b.py:2` `bbbbbbbb`\n  - 답: \n"
        self.assertEqual(tutor_cmd.collect(text), {"aaaaaaaa": "첫 항목 답"})

    def test_the_generated_report_round_trips(self):
        """형식과 파서는 한 벌이어야 한다 — 보고서를 고치고 파서를 안 고치면 답이 조용히 안 걷힌다."""
        point = tutor.Checkpoint("todo-left", "a.py", 3, "", "사실", "이유", "물음?")
        lesson = tutor.Lesson("HEAD", (), (point,), ())
        filled = tutor_cmd._report(lesson).replace("  - 답: ", "  - 답: 다음 스프린트에 갚는다", 1)
        self.assertEqual(tutor_cmd.collect(filled), {point.cid: "다음 스프린트에 갚는다"})


class DurabilityTest(unittest.TestCase):
    """기록은 관문이 아니다 — 깨져도 코드는 그대로 간다."""

    def test_a_corrupt_record_reads_as_empty_instead_of_raising(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, tutor_growth.GROWTH_REL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{절단된")
        self.assertEqual(tutor_growth.load(root)["topics"], {})

    def test_the_card_still_renders_when_the_record_cannot_be_written(self):
        """쓰기 불능이 되짚기를 막으면 그 순간 관문이 된다."""
        root = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=root, env=_ENV, capture_output=True, check=False)
        with open(os.path.join(root, "seed.py"), "w", encoding="utf-8") as handle:
            handle.write("x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=root, env=_ENV, capture_output=True, check=False)
        subprocess.run(["git", "commit", "-qm", "s"], cwd=root, env=_ENV, capture_output=True, check=False)
        with open(os.path.join(root, "app.py"), "w", encoding="utf-8") as handle:
            handle.write("# TODO: 나중에\n")
        os.makedirs(os.path.join(root, tutor_growth.GROWTH_REL), exist_ok=True)  # 파일 자리에 디렉터리
        lesson = tutor.review(root, "HEAD")
        tutor.record(root, lesson.ranked)  # 예외가 위로 새면 이 줄에서 턴이 죽는다
        self.assertTrue(tutor.shaped(root, lesson.ranked))  # 못 적어도 화면은 나온다
        self.assertFalse(tutor_growth.save(root, tutor_growth.load(root)))  # 못 적었다고 정직하게 답한다


if __name__ == "__main__":
    unittest.main()
