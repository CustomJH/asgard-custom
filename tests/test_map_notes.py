#!/usr/bin/env python3
"""근거 주석 레인 — 표식이 있는 것만 근거로 세고, 귀속은 증명되는 만큼만 한다."""

import os
import tempfile
import unittest


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, body: str) -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(body)

    def notes(self):
        from asgard.map_notes import collect_notes

        return collect_notes(self.root)


class TestMarkers(Base):
    def test_only_marked_comments_count_as_rationale(self):
        """표식 없는 주석은 설명이지 근거가 아니다 — 문장을 보고 판단하면 그게 지어내기다."""
        self.write(
            "m.py",
            "# 이 함수는 값을 더한다\n"
            "def add(a, b):\n"
            "    # 정수로 고정한다 — float 로 두면 합산 오차가 누적된다 (26-01-02)\n"
            "    return a + b\n",
        )

        found = self.notes()

        self.assertEqual(
            [note.text for note in found], ["정수로 고정한다 — float 로 두면 합산 오차가 누적된다 (26-01-02)"]
        )

    def test_english_rationale_is_weighed_the_same(self):
        """`code_map._files` 의 근거가 한국어 표식이 없다는 이유만으로 안 보이던 것을 재보고 넣었다."""
        self.write(
            "m.py",
            "# Git is the canonical project boundary. This prevents build outputs from\n"
            "# becoming false landmarks.\n"
            "def scan():\n"
            "    return []\n",
        )

        self.assertEqual(len(self.notes()), 1)

    def test_a_common_connective_is_not_a_marker(self):
        """`그래서`는 흔한 접속사라 196건을 끌고 들어왔고 그중 대부분이 근거가 아니었다."""
        self.write("m.py", "# 값을 정렬한다 그래서 순서가 안정적이다\ndef run():\n    return 1\n")

        self.assertEqual(self.notes(), [])

    def test_consecutive_comment_lines_are_one_note(self):
        """근거가 여러 줄에 걸치면 표식 있는 줄만 남길 때 뜻이 반토막 난다."""
        self.write(
            "m.py",
            "# 재시도는 세 번이다.\n# 네 번째부터는 상류가 이미 죽은 경우라 대기만 늘었다 (26-01-02).\ndef go():\n    return 1\n",
        )

        found = self.notes()

        self.assertEqual(len(found), 1)
        self.assertIn("재시도는 세 번이다", found[0].text)
        self.assertIn("대기만 늘었다", found[0].text)


class TestAttribution(Base):
    def test_python_attribution_names_the_enclosing_unit(self):
        self.write(
            "m.py",
            "class Runner:\n    def go(self):\n        # 순서를 고정한다 — 안 그러면 재현이 안 된다\n        return 1\n",
        )

        found = self.notes()

        self.assertEqual(found[0].unit, "go")

    def test_docstrings_carry_rationale_too(self):
        self.write("m.py", 'def go():\n    """순서를 고정한다. 흔들리면 재현이 안 된다 (26-01-02)."""\n    return 1\n')

        found = self.notes()

        self.assertEqual([(note.unit, "재현" in note.text) for note in found], [("go", True)])

    def test_a_broken_file_yields_nothing_instead_of_guessing(self):
        self.write("m.py", "def broken(:\n    # 이유는 여기 있다\n")

        # 주석 덩이는 ast 없이도 읽히지만 귀속은 증명이 없다 — 단위를 비워 둔다.
        self.assertEqual([note.unit for note in self.notes()], [""])


class TestRanking(Base):
    def test_ranking_prefers_notes_covering_more_query_concepts(self):
        from asgard.map_notes import rank_notes

        self.write(
            "ticket.py",
            "def move():\n    # 티켓 상태는 팀이 정한 칸으로만 옮긴다 — 기본 슬러그로 세면 안 된다\n    return 1\n",
        )
        self.write("auth.py", "def login():\n    # 상태는 캐시하지 않는다 — 만료를 못 본다\n    return 1\n")

        ranked = rank_notes(self.notes(), "티켓 상태", limit=1)

        self.assertEqual(ranked[0].path, "ticket.py")

    def test_an_unrelated_query_returns_nothing(self):
        from asgard.map_notes import rank_notes

        self.write("m.py", "def go():\n    # 순서를 고정한다 — 안 그러면 재현이 안 된다\n    return 1\n")

        self.assertEqual(rank_notes(self.notes(), "quarterly revenue forecast"), [])


if __name__ == "__main__":
    unittest.main()
