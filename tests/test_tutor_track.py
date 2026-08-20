"""트랙 배치 판정 앵커 — 사람 축의 단계가 **조용히 틀리는** 방식을 못박는다.

실행: uv run pytest tests/test_tutor_track.py

이 층이 죽는 방식은 화면에서 안 보인다. 셈이 한 칸 틀리면 사다리가 반대로 동작하고, 그 결과가
"3단계"라는 그럴듯한 한 글자로 나온다. 그래서 여기 앵커는 대부분 **안 일어나야 하는 일**을
고정한다: 단계가 내려가는 것(기록은 만료와 상한으로 줄어드는데 사람은 안 줄었다), 같은 물음을
여러 번 답해서 올라가는 것, 없는 트랙을 지어내는 것, 지어낸 파일 이름으로 시험을 통과하는 것.

같이 고정하는 계약 둘: ① `growth.json`은 이 층이 **한 바이트도 안 쓴다**. ② 단계 어휘는
`tutor_teach.DEPTHS`가 정본이라 여기서 손으로 다시 적지 않는다 — 사본을 세면 갈린 것을 못 본다.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from asgard import tutor_teach, tutor_track

TRACK = "src/asgard/tutor"


def _write(root: str, rel: str, text: str) -> str:
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as handle:
        handle.write(text)
    return full


def _growth(root: str, open_rows: dict | None = None, closed: list | None = None) -> str:
    body = {"version": 1, "topics": {}, "open": open_rows or {}, "closed": closed or []}
    return _write(root, os.path.join(".asgard", "tutor", "growth.json"), json.dumps(body, ensure_ascii=False))


def _asked(path: str = TRACK + "/a.py", kind: str = "silent-failure", unit: str = "go") -> dict:
    return {"kind": kind, "path": path, "unit": unit, "ask": "왜?", "asks": 1, "opened": 1.0, "due": 2.0}


def _answered(cid: str, path: str = TRACK + "/a.py", kind: str = "silent-failure", unit: str = "go") -> dict:
    return {
        "cid": cid,
        "kind": kind,
        "path": path,
        "unit": unit,
        "ask": "왜?",
        "at": 1.0,
        "reason": "answered",
        "depth": "full",
        "said": "이 자리는 예외를 삼키면 큐가 조용히 빈다",
    }


def _deep(root: str, count: int, path: str = TRACK + "/a.py", unit: str = "go") -> None:
    """서로 다른 물음 `count`건에 자기 문장으로 답한 상태를 만든다."""
    _growth(root, closed=[_answered(f"c{i}", path, "silent-failure", f"{unit}{i}") for i in range(count)])


def _rung(placed: dict, track: str = TRACK) -> str:
    for row in placed["tracks"]:
        if row["track"] == track:
            return row["rung"]
    return "(없음)"


class VocabularyTest(unittest.TestCase):
    """단계 이름과 화면 문장 — 어휘 사본이 갈리면 화면과 판정이 서로 다른 말을 한다."""

    def test_the_rungs_are_the_teach_vocabulary_plus_a_floor(self):
        """`tutor_teach.DEPTHS`를 손으로 베끼면 한쪽만 고쳐져도 아무도 못 본다."""
        self.assertEqual(tutor_track.RUNGS, ("unseen",) + tuple(tutor_teach.DEPTHS))

    def test_every_rung_says_its_bar_in_a_sentence(self):
        """조건만 있고 문장이 없으면 오딘은 무엇을 향해 가는지 모른다."""
        for rung in tutor_track.RUNGS:
            self.assertTrue(tutor_track.bar(rung).strip(), rung)

    def test_every_rung_below_the_top_says_what_is_missing(self):
        for rung in tutor_track.RUNGS[:-1]:
            said = tutor_track.remaining(tutor_track.Count(asked=1), rung, False)
            self.assertTrue(said.strip(), rung)

    def test_the_top_rung_asks_for_nothing_more(self):
        self.assertEqual(tutor_track.remaining(tutor_track.Count(asked=9, deep=9), "owned", True), "")


class PlacementTest(unittest.TestCase):
    """이미 디스크에 있는 것만 읽어 스스로 배치한다 — 설문도, 지어낸 트랙도 없다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_an_empty_repo_yields_no_tracks_and_says_so(self):
        """0건과 "안 봤다"가 화면에서 같아지면 이 도구가 거짓말을 하는 것이다."""
        placed = tutor_track.place(self.root)
        self.assertEqual(placed["tracks"], [])
        self.assertTrue(any("트랙" in note for note in placed["notes"]))

    def test_a_question_that_landed_places_the_track_at_first(self):
        _growth(self.root, open_rows={"aa": _asked()})
        placed = tutor_track.place(self.root)
        self.assertEqual(_rung(placed), "first")
        self.assertEqual([row["asked"] for row in placed["tracks"]], [1])

    def test_two_deep_answers_place_the_track_at_familiar(self):
        _deep(self.root, 2)
        self.assertEqual(_rung(tutor_track.place(self.root)), "familiar")

    def test_deep_answers_alone_never_reach_owned(self):
        """시험을 안 치면 `owned`가 아니다 — 답의 수만으로 오르면 승급 시험이 장식이 된다."""
        _deep(self.root, tutor_track.OWNED_AT + 3)
        self.assertEqual(_rung(tutor_track.place(self.root)), "familiar")

    def test_answering_one_question_many_times_does_not_climb(self):
        """실측 함정: 닫힌 기록을 그냥 세면 같은 물음 하나를 되풀이해 답하는 길이 열린다."""
        _growth(self.root, closed=[_answered("same") for _ in range(tutor_track.OWNED_AT + 3)])
        placed = tutor_track.place(self.root)
        self.assertEqual(_rung(placed), "first")
        self.assertEqual([row["deep"] for row in placed["tracks"]], [1])

    def test_a_question_without_coordinates_is_reported_not_dropped(self):
        _growth(self.root, open_rows={"aa": _asked(path="")})
        placed = tutor_track.place(self.root)
        self.assertEqual(placed["tracks"], [])
        self.assertTrue(any("경로가 없는" in note for note in placed["notes"]))

    def test_the_track_carries_the_next_bar_and_what_is_missing(self):
        _growth(self.root, open_rows={"aa": _asked()})
        row = tutor_track.place(self.root)["tracks"][0]
        self.assertEqual(row["next_bar"], tutor_track.bar("familiar"))
        self.assertIn("답한 물음", row["remaining"])

    def test_open_questions_make_the_track_active(self):
        _growth(self.root, open_rows={"aa": _asked()})
        self.assertEqual(tutor_track.place(self.root)["active"], [TRACK])


class NeverFallsTest(unittest.TestCase):
    """단계는 오르기만 한다. `growth.json`은 만료와 상한으로 줄어드는 기록이라서다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_a_rung_survives_the_evidence_disappearing(self):
        _deep(self.root, 2)
        self.assertEqual(_rung(tutor_track.place(self.root)), "familiar")
        _growth(self.root)  # 코드가 사라져 물음이 만료된 상태
        self.assertEqual(_rung(tutor_track.place(self.root)), "familiar")

    def test_the_drop_is_written_to_history_instead(self):
        """조용히 유지하면 화면이 기록과 어긋난 이유를 아무도 못 찾는다."""
        _deep(self.root, 2)
        tutor_track.place(self.root)
        _growth(self.root)
        tutor_track.place(self.root)
        history = tutor_track.load(self.root)["tracks"][TRACK]["history"]
        self.assertTrue(any(row["rung"] == "unseen" for row in history))

    def test_the_same_drop_is_not_written_twice(self):
        """매 호출마다 같은 회귀를 적으면 기록이 한 문장으로 가득 찬다."""
        _deep(self.root, 2)
        tutor_track.place(self.root)
        _growth(self.root)
        tutor_track.place(self.root)
        first = len(tutor_track.load(self.root)["tracks"][TRACK]["history"])
        tutor_track.place(self.root)
        self.assertEqual(len(tutor_track.load(self.root)["tracks"][TRACK]["history"]), first)


class ExamTest(unittest.TestCase):
    """승급 시험 — 묻는 양에 상한이 있고, 회수만 세고, 지어낸 이름은 떨어뜨린다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        _write(self.root, "pkg/tool.py", "def widget():\n    return 1\n")
        for caller in ("a.py", "b.py", "c.py", "d.py", "e.py", "f.py", "g.py"):
            _write(self.root, caller, "from pkg.tool import widget\n\nwidget()\n")
        _write(self.root, "small/thing.py", "def knob():\n    return 2\n")
        _write(self.root, "z.py", "from small.thing import knob\n\nknob()\n")
        _growth(
            self.root,
            closed=[
                _answered("c0", "pkg/tool.py", "silent-failure", "widget"),
                _answered("c1", "small/thing.py", "silent-failure", "knob"),
            ],
        )

    def _open(self) -> None:
        tutor_track.pick_exam(self.root, "pkg")

    def test_a_track_with_no_answers_gets_no_exam(self):
        self.assertEqual(tutor_track.pick_exam(self.root, "tests"), ("", ""))

    def test_the_exam_asks_about_a_unit_the_answer_already_touched(self):
        question, qualname = tutor_track.pick_exam(self.root, "pkg")
        self.assertEqual(qualname, "widget")
        self.assertIn("widget", question)

    def test_the_exam_never_asks_for_more_than_the_cap(self):
        """마흔 곳 중 스물일곱을 대라는 시험은 이해가 아니라 암기를 재고, owned를 닫아 버린다."""
        self._open()
        _, _, total, _ = tutor_track.grade(self.root, "pkg", "a.py")
        self.assertEqual(total, tutor_track.EXAM_CAP)

    def test_the_question_says_how_many_it_asked_and_what_it_cannot_see(self):
        """채점이 전지해 보이면 떨어진 사람은 도구를 끈다 — 못 보는 것을 같이 적는다."""
        question, _ = tutor_track.pick_exam(self.root, "pkg")
        self.assertIn("7곳 중 5곳", question)
        self.assertIn("동적 호출", question)

    def test_a_unit_with_too_few_call_sites_gets_no_exam(self):
        """부르는 자리가 셋 이하면 2/3가 사실상 전부라 시험이 아니라 받아쓰기다."""
        self.assertEqual(tutor_track.pick_exam(self.root, "small"), ("", ""))

    def test_the_same_track_gives_the_same_exam_every_round(self):
        """고르는 자리가 회차마다 바뀌면 "통과"가 무슨 뜻인지 아무도 못 말한다."""
        first, _ = tutor_track.pick_exam(self.root, "pkg")
        asked = tutor_track.load(self.root)["tracks"]["pkg"]["exam"]["sites"]
        second, _ = tutor_track.pick_exam(self.root, "pkg")
        self.assertEqual(first, second)
        self.assertEqual(asked, ["a.py", "b.py", "c.py", "d.py", "e.py"])  # 경로 정렬 앞에서 다섯
        self.assertEqual(tutor_track.load(self.root)["tracks"]["pkg"]["exam"]["sites"], asked)

    def test_grading_before_an_exam_was_picked_says_nothing_rather_than_passing(self):
        self.assertEqual(tutor_track.grade(self.root, "pkg", "a.py"), (False, 0, 0, []))

    def test_four_of_five_pass_and_the_rest_is_named(self):
        self._open()
        passed, hit, total, missing = tutor_track.grade(self.root, "pkg", "a.py b.py c.py d.py 에서요")
        self.assertEqual((passed, hit, total), (True, 4, 5))
        self.assertEqual(missing, ["e.py"])

    def test_three_of_five_falls_short_of_the_bar(self):
        self._open()
        passed, hit, _, _ = tutor_track.grade(self.root, "pkg", "a.py b.py c.py")
        self.assertEqual((passed, hit), (False, 3))

    def test_naming_a_call_site_outside_the_five_does_not_subtract(self):
        """후보 밖의 이름을 깎으면 정밀도를 재는 것이고, 이름 대조로는 정밀도를 못 잰다."""
        self._open()
        passed, hit, _, _ = tutor_track.grade(self.root, "pkg", "a.py b.py c.py d.py f.py")
        self.assertEqual((passed, hit), (True, 4))

    def test_a_file_that_does_not_exist_fails_even_with_full_recall(self):
        """지어낸 이름을 통과시키면 시험이 기억이 아니라 요령을 재게 된다."""
        self._open()
        passed, hit, _, _ = tutor_track.grade(self.root, "pkg", "a.py b.py c.py d.py e.py ghost.py")
        self.assertEqual((passed, hit), (False, 5))

    def test_the_defining_file_is_not_one_of_the_answers(self):
        """물음이 "부르는 자리"라 정의된 파일은 답이 아니다."""
        self._open()
        _, _, _, missing = tutor_track.grade(self.root, "pkg", "a.py")
        self.assertNotIn("pkg/tool.py", missing)

    def test_the_exam_is_what_opens_owned(self):
        _growth(self.root, closed=[_answered(f"c{i}", "pkg/tool.py", "silent-failure", "widget") for i in range(5)])
        self._open()
        self.assertEqual(_rung(tutor_track.place(self.root), "pkg"), "familiar")
        tutor_track.grade(self.root, "pkg", "a.py b.py c.py d.py")
        self.assertEqual(_rung(tutor_track.place(self.root), "pkg"), "owned")


class BoundaryTest(unittest.TestCase):
    """이 층이 남의 기록을 만지지 않고, 깨진 기록에도 안 죽는다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_growth_is_never_written_to(self):
        """채점 결과가 growth로 새면 카드 물음까지 점수가 붙는다(계약 ①)."""
        _write(self.root, "pkg/tool.py", "def widget():\n    return 1\n")
        for caller in ("a.py", "b.py", "c.py", "d.py"):
            _write(self.root, caller, "widget()\n")
        path = _growth(self.root, closed=[_answered("c0", "pkg/tool.py", "silent-failure", "widget")])
        with open(path, encoding="utf-8") as handle:
            before = handle.read()
        tutor_track.place(self.root)
        tutor_track.pick_exam(self.root, "pkg")
        tutor_track.grade(self.root, "pkg", "a.py")
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)

    def test_broken_records_do_not_raise(self):
        _write(self.root, os.path.join(".asgard", "tutor", "growth.json"), "{절단된")
        _write(self.root, os.path.join(".asgard", "tutor", "track.json"), "[아무것도 아님]")
        placed = tutor_track.place(self.root)
        self.assertEqual(placed["tracks"], [])
        self.assertEqual(tutor_track.pick_exam(self.root, "pkg"), ("", ""))
        self.assertEqual(tutor_track.grade(self.root, "pkg", "a.py"), (False, 0, 0, []))

    def test_an_unwritable_record_does_not_stop_the_screen(self):
        """기록 실패가 화면을 막으면 이 층이 관문이 된다."""
        _growth(self.root, open_rows={"aa": _asked()})
        os.makedirs(os.path.join(self.root, ".asgard", "tutor", "track.json"), exist_ok=True)
        self.assertEqual(_rung(tutor_track.place(self.root)), "first")


if __name__ == "__main__":
    unittest.main()
