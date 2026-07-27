"""craft-gate 훅 — 두 게이트를 합쳐 SubagentStop 에서 구조적으로 강제한다.

훅은 저장소 안에서 도는 stdlib 전용 복사 배포본이라 엔진을 import 하지 못한다. 그래서 시험이
지켜야 할 것은 **합쳐진 판정이 출처를 잃지 않는가**와 **한쪽이 죽어도 다른 쪽이 사는가** 둘이다.

실행: uv run pytest tests/test_craft_gate_hook.py
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from asgard.hooks import craft_gate


class WriteFilter(unittest.TestCase):
    def test_accepts_every_language_either_gate_judges(self):
        for name in ("a.py", "A.java", "b.kt", "c.go", "d.ts", "e.cs", "f.c"):
            with self.subTest(name=name):
                self.assertTrue(name.endswith(craft_gate.JUDGED_SUFFIXES))

    def test_rejects_what_neither_gate_reads(self):
        for name in ("README.md", "a.json", "b.yaml", "c.rb"):
            with self.subTest(name=name):
                self.assertFalse(name.endswith(craft_gate.JUDGED_SUFFIXES))


class MergedJudgement(unittest.TestCase):
    """두 게이트를 각각 부르고, 판정마다 어느 게이트가 냈는지를 붙인다."""

    def _run(self, outputs: dict[str, object]) -> list[dict]:
        def fake(cmd, **kwargs):
            verb = "thor gate" if "thor" in cmd else "craft"
            result = mock.Mock()
            payload = outputs.get(verb)
            if isinstance(payload, Exception):
                raise payload
            result.stdout = json.dumps(payload)
            return result

        with mock.patch.object(craft_gate.subprocess, "run", side_effect=fake):
            return craft_gate._blocking("asgard", "/tmp", ["a.py"])

    def test_both_gates_are_called_and_tagged(self):
        found = self._run(
            {
                "craft": {"blocking": [{"rule": "unit-oversize", "path": "a.py", "line": 1}]},
                "thor gate": {"blocking": [{"rule": "sql-interpolated", "path": "a.py", "line": 9}]},
            }
        )
        self.assertEqual(["craft", "thor gate"], [f["gate"] for f in found])
        self.assertEqual({"unit-oversize", "sql-interpolated"}, {f["rule"] for f in found})

    def test_one_gate_failing_does_not_silence_the_other(self):
        """한 호출로 묶으면 하나의 고장이 둘 다 조용히 통과시킨다 — 그래서 따로 부른다."""
        found = self._run(
            {
                "craft": OSError("boom"),
                "thor gate": {"blocking": [{"rule": "secret-literal", "path": "a.py", "line": 3}]},
            }
        )
        self.assertEqual(["thor gate"], [f["gate"] for f in found])

    def test_clean_tree_blocks_nothing(self):
        self.assertEqual([], self._run({"craft": {"blocking": []}, "thor gate": {"blocking": []}}))


class Reason(unittest.TestCase):
    def test_message_names_the_gate_that_found_it(self):
        text = craft_gate._reason(
            [{"gate": "thor gate", "rule": "sql-interpolated", "path": "a.py", "line": 9, "detail": "d", "fix": "f"}],
            0,
        )
        self.assertIn("[thor gate/sql-interpolated]", text)
        self.assertIn("asgard thor gate", text)

    def test_truncation_is_stated_not_hidden(self):
        text = craft_gate._reason([{"rule": "r", "path": "a.py", "line": 1, "detail": "d", "fix": "f"}], 7)
        self.assertIn("7 written path(s) were not judged", text)


if __name__ == "__main__":
    unittest.main()
