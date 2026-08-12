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
import os
import tempfile
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


class SilentDisableIsCounted(unittest.TestCase):
    """게이트가 판정 없이 사라지는 네 자리가 전부 셈으로 남는가 (감사 D-7).

    설계 의도는 옳다 — 판정기 고장이 작업을 막으면 안 된다. 문제는 **비활성화가 관측되지
    않는다**는 것이었다: 대상이 빈 경우도, 상태 파일이 지워진 경우도, `asgard` 가 PATH 에 없는
    경우도 화면에서 "막을 것이 없었다"와 똑같이 생겼다. 특히 상태 파일 삭제는 write_sentinel 이
    `.asgard` 경로를 기록하지 않아 삭제 행위 자체도 안 남는다.

    그래서 여기서 재는 것은 "막았는가"가 아니라 "안 막았다는 사실이 남는가"다. 넷 다 exit 0 이고
    출력이 없어야 하며(막지 않는다), gate-events.jsonl 에 사유가 서로 다른 코드로 남아야 한다.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.root, ".asgard", "state"))
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def _sentinel(self, sid, paths):
        path = os.path.join(self.root, ".asgard", "state", "writes-%s.json" % sid)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(paths, handle)

    def _events(self):
        path = os.path.join(self.root, ".asgard", "state", "gate-events.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(ln) for ln in handle if ln.strip()]

    def _run(self, payload, which="/usr/bin/asgard", blow_up=False):
        out = io.StringIO()
        blocking = mock.patch.object(craft_gate, "_blocking", side_effect=RuntimeError("판정기 고장"))
        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
            mock.patch("sys.stdout", out),
            mock.patch("sys.argv", ["hook"]),
            mock.patch.object(craft_gate.shutil, "which", return_value=which),
            blocking if blow_up else contextlib.nullcontext(),
        ):
            with self.assertRaises(SystemExit) as caught:
                craft_gate.main()
        return int(caught.exception.code or 0), out.getvalue()

    def test_a_missing_sentinel_is_recorded(self):
        """Bash 리다이렉션만 쓴 세션과 상태 파일이 지워진 세션이 여기로 온다."""
        self.assertEqual(self._run({"session_id": "s1", "cwd": self.root}), (0, ""))
        self.assertEqual(
            self._events(), [{"event": "gate_skipped", "gate": "craft", "code": "no-sentinel", "sid": "s1"}]
        )

    def test_writes_with_nothing_judgeable_are_recorded_apart(self):
        """목록은 있는데 판정 가능한 언어가 없는 것은 우회가 아니다 — 사유를 갈라 센다."""
        self._sentinel("s2", ["notes.md"])
        self.assertEqual(self._run({"session_id": "s2", "cwd": self.root}), (0, ""))
        self.assertEqual([e["code"] for e in self._events()], ["no-judged-writes"])

    def test_a_read_only_role_is_never_held_for_someone_elses_debt(self):
        """판정 대상은 세션 전체의 쓰기다 — 서브에이전트와 조율자가 같은 sid 로 함께 적는다.

        그래서 한 글자도 안 쓴 읽기 전용 역할이 남의 빚으로 종료를 막히고, 고칠 손이 없어
        같은 차단을 두 번 되풀이한 뒤에야 통과한다 (26-08-12 실측: Thinker 가 그렇게 두 번
        세워졌다). 빚은 여기서 사라지지 않고 쓴 역할의 종료와 세션 Stop 이 다시 판정한다."""
        self._sentinel("s5", ["app.py"])
        for role in ("asgard-thinker", "asgard-verifier", "asgard-loki", "asgard-ullr", "asgard-mimir"):
            self.assertEqual(self._run({"session_id": "s5", "cwd": self.root, "agent_type": role}), (0, ""))
        self.assertEqual([e["code"] for e in self._events()], ["readonly-role"] * 5)

    def test_a_write_capable_role_is_still_judged(self):
        """면제는 고칠 손이 없는 역할에만 준다 — 쓰는 역할은 그대로 판정 레인으로 간다."""
        self._sentinel("s6", ["app.py"])
        self.assertEqual(
            self._run({"session_id": "s6", "cwd": self.root, "agent_type": "asgard-worker"}, which=None), (0, "")
        )
        self.assertEqual([e["code"] for e in self._events()], ["no-asgard"])

    def test_a_missing_asgard_is_recorded(self):
        self._sentinel("s3", ["app.py"])
        self.assertEqual(self._run({"session_id": "s3", "cwd": self.root}, which=None), (0, ""))
        self.assertEqual([e["code"] for e in self._events()], ["no-asgard"])

    def test_a_hook_exception_is_recorded(self):
        """예상하지 못한 비활성화라 가장 중요한 자리다 — 안 세면 훅이 매 턴 죽어도 화면이 조용하다."""
        self._sentinel("s4", ["app.py"])
        self.assertEqual(self._run({"session_id": "s4", "cwd": self.root}, blow_up=True), (0, ""))
        self.assertEqual([e["code"] for e in self._events()], ["hook-error"])

    def test_a_tree_without_asgard_state_is_not_a_disabled_gate(self):
        """`.asgard/state` 가 아예 없는 트리는 게이트가 꺼진 게 아니라 애초에 안 깔린 것이다.

        여기서 세면 asgard 를 안 쓰는 저장소마다 파일을 만들고, 그 잡음이 지표를 못 쓰게 한다.
        """
        bare = tempfile.TemporaryDirectory()
        self.addCleanup(bare.cleanup)
        self.assertEqual(self._run({"session_id": "s5", "cwd": bare.name}), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(bare.name, ".asgard")))

    def test_a_judged_run_records_nothing(self):
        """판정이 실제로 돌면 무판정 셈은 늘지 않는다 — 그러면 모든 실행이 셈에 들어가 신호가 죽는다."""
        self._sentinel("s6", ["app.py"])
        with mock.patch.object(craft_gate, "_blocking", return_value=([], {})):
            self.assertEqual(self._run({"session_id": "s6", "cwd": self.root}), (0, ""))
        self.assertEqual(self._events(), [])


if __name__ == "__main__":
    unittest.main()
