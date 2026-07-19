#!/usr/bin/env python3
"""턴 영속 계약 — 완결 문답만 저장, 손상 라인 내성, 루트 격리, 소유자 전용 권한.

실행: uv run pytest tests/test_turn_store.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.agent import turn_store  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "proj")
        os.makedirs(self.root)
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmp.name  # ~/.asgard/sessions 격리

    def tearDown(self):
        if self._home is not None:
            os.environ["HOME"] = self._home
        self._tmp.cleanup()


class TestTurnStore(Base):
    def test_roundtrip_and_limit(self):
        for i in range(9):
            turn_store.append_turn(self.root, f"질문{i}", f"응답{i}")
        turns = turn_store.load_turns(self.root, limit=6)
        self.assertEqual(len(turns), 6)
        self.assertEqual(turns[-1], ("질문8", "응답8"))
        self.assertEqual(turns[0], ("질문3", "응답3"))

    def test_empty_request_or_response_not_stored(self):
        turn_store.append_turn(self.root, "질문", "")
        turn_store.append_turn(self.root, "  ", "응답")
        self.assertEqual(turn_store.load_turns(self.root), [])

    def test_corrupt_final_line_tolerated(self):
        turn_store.append_turn(self.root, "질문", "응답")
        with open(turn_store._path(self.root), "a", encoding="utf-8") as f:
            f.write('{"request": "잘린')  # 중단으로 절단된 마지막 라인
        turns = turn_store.load_turns(self.root)
        self.assertEqual(turns, [("질문", "응답")])

    def test_missing_store_returns_empty(self):
        self.assertEqual(turn_store.load_turns(self.root), [])

    def test_roots_are_isolated_even_with_same_basename(self):
        other_parent = os.path.join(self._tmp.name, "elsewhere")
        other = os.path.join(other_parent, "proj")  # 같은 basename
        os.makedirs(other)
        turn_store.append_turn(self.root, "A질문", "A응답")
        turn_store.append_turn(other, "B질문", "B응답")
        self.assertEqual(turn_store.load_turns(self.root), [("A질문", "A응답")])
        self.assertEqual(turn_store.load_turns(other), [("B질문", "B응답")])

    def test_owner_only_permissions(self):
        turn_store.append_turn(self.root, "질문", "응답")
        d = turn_store._dir(self.root)
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(turn_store._path(self.root)).st_mode & 0o777, 0o600)

    @unittest.skipUnless(os.name == "posix", "권한 보정은 POSIX 시맨틱")
    def test_permissions_repaired_on_existing_loose_store(self):
        turn_store.append_turn(self.root, "질문", "응답")
        os.chmod(turn_store._dir(self.root), 0o755)  # 외부 요인으로 느슨해진 기존 저장소
        os.chmod(turn_store._path(self.root), 0o644)
        turn_store.append_turn(self.root, "질문2", "응답2")
        self.assertEqual(os.stat(turn_store._dir(self.root)).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(turn_store._path(self.root)).st_mode & 0o777, 0o600)

    def test_response_capped(self):
        turn_store.append_turn(self.root, "질문", "x" * 10_000)
        ((_, a),) = turn_store.load_turns(self.root)
        self.assertEqual(len(a), turn_store._RESPONSE_CAP)


if __name__ == "__main__":
    unittest.main()
