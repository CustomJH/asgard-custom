#!/usr/bin/env python3
"""네이티브 에이전트 루프 결정론 슬라이스 (CUS-137/142) — API 호출 없는 부분 전부.

툴 계약(text_editor/bash)·경로 격리·git-guard 배선·원장 래퍼(ql/gate)·delegate 이벤트·
write-sentinel 미러. 라이브 루프(실 모델)는 test/e2e_trinity.sh 의 start 아암(CUS-140) 몫.

실행: uv run python test/test_agent.py  (asgard 패키지 임포트 필요 — subprocess 가 -m 으로 훅 실행)
"""

import json
import os
import subprocess
import tempfile
import unittest

from asgard.agent import tools as T
from asgard.agent.heimdall import _record_writes
from asgard.agent.session import gate, ql


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

        def run(*a):
            return subprocess.run(a, cwd=self.root, capture_output=True, check=True)

        run("git", "init", "-q")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        open(os.path.join(self.root, "f.txt"), "w").write("base\n")
        run("git", "add", "-A")
        run("git", "commit", "-qm", "init")

    def tearDown(self):
        self._tmp.cleanup()


class TestEditor(Base):
    def test_create_view_roundtrip(self):
        w = []
        T.run_editor(self.root, {"command": "create", "path": "a/b.py", "file_text": "x = 1\n"}, w)
        self.assertEqual(w, [os.path.join("a", "b.py")])
        out = T.run_editor(self.root, {"command": "view", "path": "a/b.py"}, [])
        self.assertIn("x = 1", out)

    def test_str_replace_requires_exactly_one_match(self):
        w = []
        T.run_editor(self.root, {"command": "create", "path": "c.txt", "file_text": "aa\naa\n"}, w)
        with self.assertRaises(T.ToolError):  # 2회 매치
            T.run_editor(self.root, {"command": "str_replace", "path": "c.txt", "old_str": "aa", "new_str": "bb"}, w)
        T.run_editor(self.root, {"command": "str_replace", "path": "c.txt", "old_str": "aa\naa", "new_str": "bb"}, w)
        self.assertEqual(open(os.path.join(self.root, "c.txt")).read(), "bb\n")

    def test_path_escape_rejected(self):
        for bad in ("../evil.txt", "/etc/passwd", "a/../../evil"):
            with self.assertRaises(T.ToolError, msg=bad):
                T.run_editor(self.root, {"command": "create", "path": bad, "file_text": "x"}, [])

    def test_insert_bounds(self):
        w = []
        T.run_editor(self.root, {"command": "create", "path": "d.txt", "file_text": "1\n2\n"}, w)
        T.run_editor(self.root, {"command": "insert", "path": "d.txt", "insert_line": 1, "insert_text": "x"}, w)
        self.assertEqual(open(os.path.join(self.root, "d.txt")).read(), "1\nx\n2\n")
        with self.assertRaises(T.ToolError):
            T.run_editor(self.root, {"command": "insert", "path": "d.txt", "insert_line": 99, "insert_text": "x"}, w)


class TestBash(Base):
    def test_runs_and_captures_exit(self):
        out, code = T.run_bash(self.root, {"command": "echo hi"})
        self.assertEqual((out, code), ("hi", 0))

    def test_git_guard_blocks_force_push(self):
        with self.assertRaises(T.ToolError):
            T.run_bash(self.root, {"command": "git push --force origin main"})

    def test_restart_is_ack(self):
        out, code = T.run_bash(self.root, {"restart": True})
        self.assertEqual(code, 0)


class TestLedgerWiring(Base):
    """네이티브 루프가 쓰는 subprocess 계약 — 훅을 배포 형태 그대로."""

    def test_full_cycle_gate_pass(self):
        sid = "native-t1"
        self.assertEqual(ql(self.root, "open", "q1", "--criteria", "c", session=sid).returncode, 0)
        open(os.path.join(self.root, "f.txt"), "a").write("more\n")
        _record_writes(self.root, sid, ["f.txt"])
        ql(
            self.root,
            "append",
            session=sid,
            stdin=json.dumps(
                {
                    "role": "worker",
                    "event": "work",
                    "changed_files": ["f.txt"],
                    "commands": [{"cmd": "true", "exit_code": 0}],
                }
            ),
        )
        ql(
            self.root,
            "append",
            "--verdict",
            "PASS",
            "--level",
            "micro",
            session=sid,
            stdin=json.dumps({"role": "verifier", "event": "verify", "commands": [{"cmd": "true", "exit_code": 0}]}),
        )
        blocked, _ = gate(self.root, sid)
        self.assertFalse(blocked)
        self.assertEqual(ql(self.root, "close", session=sid).returncode, 0)

    def test_gate_blocks_unverified_write(self):
        sid = "native-t2"
        ql(self.root, "open", "q2", "--criteria", "c", session=sid)
        open(os.path.join(self.root, "f.txt"), "a").write("tamper\n")
        _record_writes(self.root, sid, ["f.txt"])
        blocked, reason = gate(self.root, sid)
        self.assertTrue(blocked)
        self.assertIn("PASS", reason)

    def test_delegate_event_accepted(self):
        sid = "native-t3"
        ql(self.root, "open", "q3", "--criteria", "c", session=sid)
        p = ql(
            self.root,
            "append",
            session=sid,
            stdin=json.dumps(
                {
                    "role": "worker",
                    "event": "delegate",
                    "commands": [{"cmd": "dispatch:freyja — 프론트 전담", "exit_code": 0}],
                }
            ),
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        log = open(os.path.join(self.root, ".asgard", "quest", "q3.jsonl")).read()
        self.assertIn('"delegate"', log)

    def test_record_writes_merges(self):
        _record_writes(self.root, "s", ["a.py"])
        _record_writes(self.root, "s", ["a.py", "b.py"])
        data = json.load(open(os.path.join(self.root, ".asgard", "writes-s.json")))
        self.assertEqual(data, ["a.py", "b.py"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
