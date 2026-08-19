"""style-gate 훅 — 저장소가 정한 코드 스타일을 Stop·SubagentStop 에서 물린다.

훅은 사용자 저장소 안에서 도는 stdlib 전용 복사 배포본이라 엔진을 import 하지 못한다. 그래서
시험이 지켜야 할 것은 셋이다: **안 들인 저장소에서 자식 프로세스를 안 띄우는가**(값), **이번
세션이 쓴 파일에서 나온 위반만 막는가**(귀속), **막을 수 없을 때 조용히 사라지지 않는가**(정직).

실행: uv run pytest tests/test_style_gate.py
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from unittest import mock

from asgard.hooks import style_gate


def _root(section: dict | None, writes: list[str] | None = None, sid: str = "s1") -> str:
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, ".asgard", "state"), exist_ok=True)
    if section is not None:
        with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
            json.dump({"code_style": section}, handle)
    if writes is not None:
        with open(os.path.join(root, ".asgard", "state", "writes-%s.json" % sid), "w", encoding="utf-8") as handle:
            json.dump(writes, handle)
    return root


def _fire(
    root: str, payload: dict | None, *, sid: str = "s1", agent: str = "session"
) -> tuple[int, str, list[list[str]]]:
    """훅을 한 번 돌리고 (종료 코드, stdout, 실제로 띄운 명령줄들)을 준다."""
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(list(cmd))
        result = mock.Mock()
        result.stdout = json.dumps(payload) if payload is not None else "not json"
        return result

    stdin = io.StringIO(json.dumps({"cwd": root, "session_id": sid, "agent_type": agent}))
    out = io.StringIO()
    with (
        mock.patch.object(style_gate.subprocess, "run", side_effect=fake_run),
        mock.patch.object(style_gate.shutil, "which", return_value="/usr/bin/asgard"),
        mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": root}),
        mock.patch.object(style_gate.sys, "stdin", stdin),
        mock.patch.object(style_gate.sys, "stdout", out),
    ):
        try:
            style_gate.main()
            code = 0
        except SystemExit as exit_:
            code = int(exit_.code or 0)
    return code, out.getvalue(), seen


_TOOLS = {"tools": [{"name": "ruff", "check": "ruff check {files}", "languages": [".py"]}]}


class OptIn(unittest.TestCase):
    """안 들인 저장소는 설정 한 번 읽고 끝난다 — 훅 값의 대부분이 자식 프로세스라서 중요하다."""

    def test_no_section_spawns_nothing(self):
        code, out, seen = _fire(_root(None, ["a.py"]), {"blocking": [{"path": "a.py"}]})
        self.assertEqual((code, out, seen), (0, "", []))

    def test_comment_only_seed_spawns_nothing(self):
        section = {"_comment": "…", "_example": {"tools": [{"name": "x", "check": "true"}]}}
        _, out, seen = _fire(_root(section, ["a.py"]), {"blocking": [{"path": "a.py"}]})
        self.assertEqual((out, seen), ("", []))

    def test_enabled_false_spawns_nothing(self):
        section = {"enabled": False, **_TOOLS}
        _, _, seen = _fire(_root(section, ["a.py"]), {"blocking": [{"path": "a.py"}]})
        self.assertEqual(seen, [])

    def test_a_tool_row_without_a_check_is_not_a_declaration(self):
        _, _, seen = _fire(_root({"tools": [{"name": "x"}]}, ["a.py"]), {"blocking": [{"path": "a.py"}]})
        self.assertEqual(seen, [])


class Scoping(unittest.TestCase):
    def test_only_paths_a_declared_tool_owns_are_sent(self):
        root = _root(_TOOLS, ["src/a.py", "docs/b.md", "src/c.java"])
        _, _, seen = _fire(root, {"blocking": []})
        self.assertEqual(seen[0][seen[0].index("--path") :], ["--path", "src/a.py"])

    def test_a_session_in_another_language_never_spawns(self):
        _, _, seen = _fire(_root(_TOOLS, ["A.java", "b.md"]), {"blocking": [{"path": "A.java"}]})
        self.assertEqual(seen, [])

    def test_declared_paths_narrow_the_scope_further(self):
        section = {"tools": [{"name": "cs", "check": "c", "languages": [".java"], "paths": ["be"]}]}
        root = _root(section, ["be/A.java", "fe/B.java"])
        _, _, seen = _fire(root, {"blocking": []})
        self.assertEqual(seen[0][seen[0].index("--path") :], ["--path", "be/A.java"])

    def test_no_sentinel_means_no_child_process(self):
        _, _, seen = _fire(_root(_TOOLS, None), {"blocking": []})
        self.assertEqual(seen, [])


class Blocking(unittest.TestCase):
    def _reason(self, out: str) -> str:
        return json.loads(out)["reason"]

    def test_violations_in_session_files_block_with_the_fix_command(self):
        payload = {
            "blocking": [{"rule": "ruff", "path": "a.py", "line": 3, "detail": "F401", "fix": "ruff check --fix"}]
        }
        code, out, _ = _fire(_root(_TOOLS, ["a.py"]), payload)
        self.assertEqual(code, 0)  # 차단은 종료 코드가 아니라 payload 로 말한다
        reason = self._reason(out)
        self.assertIn("a.py:3", reason)
        self.assertIn("ruff check --fix", reason)
        self.assertIn("asgard style check", reason)

    def test_an_empty_verdict_does_not_block(self):
        _, out, _ = _fire(_root(_TOOLS, ["a.py"]), {"blocking": []})
        self.assertEqual(out, "")

    def test_a_repair_that_ran_is_named_before_the_findings(self):
        payload = {"repaired": ["ruff format a.py"], "blocking": [{"rule": "ruff", "path": "a.py", "line": 1}]}
        _, out, _ = _fire(_root(_TOOLS, ["a.py"]), payload)
        reason = self._reason(out)
        self.assertLess(reason.index("ruff format a.py"), reason.index("a.py:1"))
        self.assertIn("Re-read", reason)

    def test_a_tool_that_could_not_run_is_stated_not_hidden(self):
        payload = {
            "blocking": [{"rule": "ruff", "path": "a.py", "line": 1}],
            "runs": [{"tool": "checkstyle", "error": "timed out after 300s"}],
        }
        _, out, _ = _fire(_root(_TOOLS, ["a.py"]), payload)
        self.assertIn("timed out after 300s", self._reason(out))

    def test_a_broken_verdict_never_becomes_a_pass_message(self):
        _, out, _ = _fire(_root(_TOOLS, ["a.py"]), None)  # `--json` 이 JSON 이 아니었다
        self.assertEqual(out, "")

    def test_autofix_is_only_asked_for_when_a_tool_declared_it(self):
        _, _, plain = _fire(_root(_TOOLS, ["a.py"]), {"blocking": []})
        section = {"tools": [dict(_TOOLS["tools"][0], autofix=True)]}
        _, _, opted = _fire(_root(section, ["a.py"]), {"blocking": []})
        self.assertNotIn("--autofix", plain[0])
        self.assertIn("--autofix", opted[0])


class Cap(unittest.TestCase):
    """차단이 가르치지 못하면 그것은 순수한 턴 비용이다 — craft-gate 와 같은 상한 2회."""

    def test_the_third_block_lets_the_turn_finish(self):
        root = _root(_TOOLS, ["a.py"])
        payload = {"blocking": [{"rule": "ruff", "path": "a.py", "line": 1}]}
        outs = [_fire(root, payload)[1] for _ in range(style_gate.MAX_BLOCKS + 1)]
        self.assertTrue(all(outs[: style_gate.MAX_BLOCKS]))
        self.assertEqual(outs[style_gate.MAX_BLOCKS], "")

    def test_each_agent_carries_its_own_count(self):
        root = _root(_TOOLS, ["a.py"])
        payload = {"blocking": [{"rule": "ruff", "path": "a.py", "line": 1}]}
        for _ in range(style_gate.MAX_BLOCKS + 1):
            _fire(root, payload, agent="worker")
        self.assertTrue(_fire(root, payload, agent="verifier")[1])


class Ledger(unittest.TestCase):
    """잡은 사실이 장부에 남는가 — 못 잡은 사실만 남으면 억제 효과를 아무도 못 잰다."""

    def _rows(self, root: str) -> list[dict]:
        path = os.path.join(root, ".asgard", "state", "gate-events.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_a_block_names_the_tools_that_fired(self):
        root = _root(_TOOLS, ["a.py"])
        _fire(root, {"blocking": [{"rule": "ruff", "path": "a.py", "line": 1}]})
        blocks = [r for r in self._rows(root) if r.get("event") == "gate_block"]
        self.assertEqual([("style", "ruff")], [(r["gate"], r["code"]) for r in blocks])

    def test_passing_writes_no_block_row(self):
        root = _root(_TOOLS, ["a.py"])
        _fire(root, {"blocking": []})
        self.assertEqual([], [r for r in self._rows(root) if r.get("event") == "gate_block"])

    def test_the_run_past_the_cap_is_recorded_as_an_escalation(self):
        root = _root(_TOOLS, ["a.py"])
        payload = {"blocking": [{"rule": "ruff", "path": "a.py", "line": 1}]}
        for _ in range(style_gate.MAX_BLOCKS + 1):
            _fire(root, payload)
        kinds = [r["event"] for r in self._rows(root) if r.get("gate") == "style"]
        self.assertEqual(["gate_block"] * style_gate.MAX_BLOCKS + ["gate_escalate"], kinds)


class Protocol(unittest.TestCase):
    """세 호스트가 같은 규율을 지려면 차단문의 형식만 갈라야 한다."""

    def _block(self, protocol: str) -> dict:
        out = io.StringIO()
        with mock.patch.object(style_gate.sys, "stdout", out):
            with self.assertRaises(SystemExit):
                style_gate._block(protocol, "why")
        return json.loads(out.getvalue())

    def test_each_host_gets_the_shape_it_reads(self):
        self.assertEqual(self._block("claude"), {"decision": "block", "reason": "why"})
        self.assertEqual(self._block("cursor"), {"followup_message": "why"})
        self.assertEqual(self._block("codex"), {"continue": False, "stopReason": "why"})


if __name__ == "__main__":
    unittest.main()
