"""craft-gate 훅 — 세 게이트를 합쳐 SubagentStop에서 구조적으로 강제한다.

훅은 저장소 안에서 도는 stdlib 전용 복사 배포본이라 엔진을 import 하지 못한다. 그래서 시험이
지켜야 할 것은 셋이다: **합쳐진 판정이 출처를 잃지 않는가**, **한쪽이 죽어도 다른 쪽이 사는가**,
그리고 **craft 수리 레인이 남은 것만 막고 수리 사실을 말하는가**.

실행: uv run pytest tests/test_craft_gate_hook.py
"""

from __future__ import annotations

import contextlib
import io
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


def _label(cmd: list[str]) -> str:
    """호출 하나가 어느 게이트의 어느 레인인지 — craft 만 읽기 전용과 수리 두 레인이 있다."""
    if "thor" in cmd:
        return "thor gate"
    if "freyja-gate" in cmd:
        return "freyja gate"
    return "craft --fix" if "--fix" in cmd else "craft"


def _call(outputs: dict[str, object], paths: list[str] | None = None) -> tuple[list[dict], dict, list[list[str]]]:
    """`_blocking`을 목킹된 판정기 위에서 돌리고 (판정, 수리내역, 실제 명령줄)을 준다.

    `outputs`에 없는 레인은 payload 없음으로 답한다 — 그 게이트를 못 불렀을 때와 같은 상황이다.
    """
    seen: list[list[str]] = []

    def fake(cmd, **kwargs):
        seen.append(list(cmd))
        payload = outputs.get(_label(list(cmd)))
        if isinstance(payload, Exception):
            raise payload
        result = mock.Mock()
        result.stdout = json.dumps(payload)
        return result

    with mock.patch.object(craft_gate.subprocess, "run", side_effect=fake):
        found, fix = craft_gate._blocking("asgard", "/tmp", paths or ["a.py"])
    return found, fix, seen


class MergedJudgement(unittest.TestCase):
    """세 게이트를 각각 부르고, 판정마다 어느 게이트가 냈는지를 붙인다."""

    def _run(self, outputs: dict[str, object]) -> list[dict]:
        return _call(outputs)[0]

    def test_every_gate_is_called_and_tagged(self):
        """세 게이트는 근거가 다르다 — 형상 · 정확성 · 표면. 판정은 합치되 출처는 안 섞는다."""
        found = self._run(
            {
                "craft": {"blocking": [{"rule": "unit-oversize", "path": "a.py", "line": 1}]},
                "thor gate": {"blocking": [{"rule": "sql-interpolated", "path": "a.py", "line": 9}]},
                "freyja gate": {"blocking": [{"gate": "A4", "path": "p.html", "detail": "균일 타일 격자"}]},
            }
        )
        self.assertEqual(["craft", "thor gate", "freyja gate"], [f["gate"] for f in found])
        self.assertEqual({"unit-oversize", "sql-interpolated"}, {f.get("rule") for f in found if f.get("rule")})

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


FIX = {
    "applied": [
        {"path": "src/a.py", "line": 12, "rule": "note-jargon", "before": "# 무매칭", "after": "# 일치 없음"},
        {"path": "src/b.py", "line": 4, "rule": "note-jargon", "before": "# 불요", "after": "# 불필요"},
    ],
    "refused": [{"path": "src/a.py", "line": 40, "rule": "unit-oversize", "detail": "d", "why": "판단이 필요하다"}],
    "files": ["src/a.py", "src/b.py"],
    "remaining_blocking": 1,
}
REMAINDER = {"rule": "unit-oversize", "path": "src/a.py", "line": 40, "detail": "d", "fix": "쪼갠다"}


class RepairLane(unittest.TestCase):
    """craft 만 수리 레인을 탄다 — 수리는 디스크에 반영되고, 훅은 남은 것만 막는다."""

    def test_craft_is_asked_to_repair_and_the_other_two_are_not(self):
        """thor gate 와 freyja gate 는 기계가 고를 수 없는 것을 재므로 읽기 전용으로만 부른다."""
        _found, _fix, seen = _call(
            {
                "craft --fix": {"blocking": [], "fix": FIX},
                "thor gate": {"blocking": []},
                "freyja gate": {"blocking": []},
            }
        )
        lanes = [_label(cmd) for cmd in seen]
        self.assertEqual(["craft --fix", "thor gate", "freyja gate"], lanes)
        self.assertEqual([], [cmd for cmd in seen if "--fix" in cmd and "craft" not in cmd])

    def test_only_the_remainder_blocks_and_the_repair_is_carried_out(self):
        """`--fix` payload 의 `blocking`은 수리 후 재판정 결과다 — 그것만 막는다."""
        found, fix, seen = _call({"craft --fix": {"blocking": [REMAINDER], "fix": FIX}})
        self.assertEqual([("craft", "unit-oversize")], [(f["gate"], f["rule"]) for f in found])
        self.assertEqual(2, len(fix["applied"]))
        self.assertEqual(1, len([cmd for cmd in seen if _label(cmd).startswith("craft")]))  # 재판정 호출 없음

    def test_a_cli_without_the_repair_lane_falls_back_to_read_only(self):
        """구 CLI 는 `--fix`를 모르는 옵션으로 죽고 stdout 이 빈다 — 버전이 아니라 결과로 가른다."""
        found, fix, seen = _call({"craft --fix": {}, "craft": {"blocking": [REMAINDER]}})
        self.assertEqual(["craft --fix", "craft"], [_label(cmd) for cmd in seen][:2])
        self.assertEqual(["unit-oversize"], [f["rule"] for f in found])
        self.assertEqual({}, fix)

    def test_a_read_only_payload_that_omits_fix_is_not_read_as_a_repair(self):
        """`fix` 칸 없이 판정만 온 경우 — 수리했다고 말하면 없는 변경을 모델에게 알리는 것이다."""
        _found, fix, seen = _call({"craft --fix": {"blocking": [REMAINDER]}, "craft": {"blocking": [REMAINDER]}})
        self.assertEqual({}, fix)
        self.assertEqual(["craft --fix", "craft"], [_label(cmd) for cmd in seen][:2])

    def test_a_crashed_repair_degrades_to_read_only_judging_not_to_allowing(self):
        """수리가 죽어도 판정은 남는다 — 수리 실패가 조용한 통과가 되면 게이트가 없는 것과 같다."""
        found, fix, _seen = _call({"craft --fix": OSError("boom"), "craft": {"blocking": [REMAINDER]}})
        self.assertEqual(["unit-oversize"], [f["rule"] for f in found])
        self.assertEqual({}, fix)

    def test_both_craft_lanes_failing_still_leaves_the_other_gates(self):
        found, _fix, _seen = _call(
            {"craft --fix": OSError("boom"), "craft": OSError("boom"), "thor gate": {"blocking": [REMAINDER]}}
        )
        self.assertEqual(["thor gate"], [f["gate"] for f in found])


class Receipt(unittest.TestCase):
    """수리가 차단을 통과로 바꾼 실행은 증거를 남긴다."""

    def _receipt(self, fix: dict | None) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            craft_gate._receipt(fix)
        return buffer.getvalue()

    def test_everything_repaired_passes_but_says_so(self):
        text = self._receipt(FIX)
        self.assertIn("repaired 2 finding(s)", text)
        self.assertIn("src/a.py", text)
        self.assertIn("src/b.py", text)

    def test_a_run_that_repaired_nothing_stays_silent(self):
        self.assertEqual("", self._receipt({"applied": [], "files": [], "remaining_blocking": 0}))
        self.assertEqual("", self._receipt({}))
        self.assertEqual("", self._receipt(None))


class Reason(unittest.TestCase):
    def test_the_repair_is_stated_before_the_remainder(self):
        """트리가 바뀐 것을 모르는 모델은 마지막으로 읽은 내용으로 다시 써서 수리를 되돌린다."""
        text = craft_gate._reason([{**REMAINDER, "gate": "craft"}], 0, FIX)
        self.assertIn("repaired 2 finding(s)", text)
        self.assertIn("rewrote 2 file(s)", text)
        self.assertIn("src/a.py, src/b.py", text)
        self.assertLess(text.index("repaired 2 finding(s)"), text.index("[craft/unit-oversize]"))

    def test_a_run_without_repairs_reads_exactly_as_before(self):
        findings = [{**REMAINDER, "gate": "craft"}]
        empty = {"applied": [], "refused": [], "files": [], "remaining_blocking": 1}
        self.assertEqual(craft_gate._reason(findings, 0), craft_gate._reason(findings, 0, empty))

    def test_many_repaired_files_are_counted_not_all_named(self):
        names = ["src/f%d.py" % i for i in range(craft_gate.MAX_FILES + 3)]
        fix = {"applied": [{"path": n, "line": 1, "rule": "note-jargon"} for n in names], "files": names}
        text = craft_gate._reason([{**REMAINDER, "gate": "craft"}], 0, fix)
        self.assertIn("rewrote %d file(s)" % len(names), text)
        self.assertIn("and 3 more", text)
        self.assertNotIn(names[-1], text)

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
