#!/usr/bin/env python3
"""툴 계약 — text_editor/bash 왕복과 출력 절단.

실행: uv run pytest tests/agent  (asgard 패키지 임포트 필요 — subprocess가 -m으로 훅 실행)
"""

import os
import tempfile
import unittest

from agent.agent_base import Base
from asgard.agent import tools as T


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

    def test_git_guard_blocks_worktree_discard(self):
        for command in (
            "git checkout HEAD -- .",
            "git checkout -- f.txt",
            "git -C . checkout HEAD -- .",
            "git -C. restore .",
            "git -c core.quotePath=false restore .",
            "git --config-env=core.foo=FOO restore .",
            "git --config-env=alias.wipe=WIPE wipe .",
            "git --config-env=Alias.wipe=WIPE wipe .",
            "git --no-optional-locks reset --hard",
            "git --exec-path=/tmp reset --hard",
            'git -C "dir with spaces" reset --hard',
            "git -p restore .",
            "git -c alias.wipe=restore wipe .",
            "git -c Alias.wipe=restore wipe .",
            "git checkout -f main",
            "git switch --discard-changes main",
            "git -C . switch -f main",
            "git restore .",
            "git --work-tree=. restore .",
            "git restore --source=HEAD --worktree .",
        ):
            with self.assertRaises(T.ToolError, msg=command):
                T.run_bash(self.root, {"command": command})

    def test_git_guard_blocks_stash_sweep(self):
        # 헬리오스 교훈 — bare stash는 전체 트리를 걷어가 병렬 세션 미커밋분까지 소실.
        for command in (
            "git stash",
            "git stash push -m wip",
            "git stash save wip",
            "git stash -u",
            "git stash --include-untracked",
            "git -C . stash",
            "git stash drop",
            "git stash clear",
        ):
            with self.assertRaises(T.ToolError, msg=command):
                T.run_bash(self.root, {"command": command})

    def test_git_guard_allows_stash_readonly(self):
        from asgard.hooks.git_guard import blocked_reason

        for command in (
            "git stash list",
            "git stash show -p",
            "git stash apply",
            "git stash pop",
            "git stash branch wip-restore",
        ):
            self.assertIsNone(blocked_reason(command), msg=command)

    def test_git_guard_blocks_rm_force_and_dot_git(self):
        for command in (
            "git rm -rf src",
            "git rm -f f.txt",
            "git rm -r dir",
            "rm -rf .git",
            "rm .git/index",
            "cd sub && rm -rf ../.git",
        ):
            with self.assertRaises(T.ToolError, msg=command):
                T.run_bash(self.root, {"command": command})

    def test_git_guard_allows_dot_git_lookalikes(self):
        from asgard.hooks.git_guard import blocked_reason

        for command in (
            "rm -rf .github",
            "rm .gitignore",
            "git rm --cached f.txt",
            "git rm f.txt",
        ):
            self.assertIsNone(blocked_reason(command), msg=command)

    def test_restart_is_ack(self):
        out, code = T.run_bash(self.root, {"restart": True})
        self.assertEqual(code, 0)


class TestTruncation(unittest.TestCase):
    """bash=실행 중 상한 꼬리 버퍼, view=머리 유지 — 오류는 출력 끝에 몰린다는 비대칭이 정책의 근거."""

    def test_tail_buffer_keeps_tail_and_counts_dropped(self):
        buf = T._TailBuffer(limit=10)
        for chunk in ("aaaaa", "bbbbb", "ccccc"):
            buf.add(chunk)
        text = buf.text()
        self.assertTrue(text.endswith("bbbbbccccc"))
        self.assertIn("앞 5 chars 절단", text)

    def test_tail_buffer_single_oversized_chunk(self):
        buf = T._TailBuffer(limit=10)
        buf.add("x" * 25)
        self.assertEqual(buf.size, 10)
        self.assertEqual(buf.dropped, 15)

    def test_tail_buffer_noop_under_limit(self):
        buf = T._TailBuffer(limit=10)
        buf.add("short")
        self.assertEqual(buf.text(), "short")

    def test_cap_head_kept_for_view(self):
        s = "y" * (T._MAX_OUT + 7)
        out = T._cap(s)
        self.assertTrue(out.startswith("yyy"))
        self.assertIn("절단", out)

    def test_run_bash_large_output_keeps_tail_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            n = T._MAX_OUT + 5000
            cmd = f"python3 -c \"import sys; sys.stdout.write('L'*{n} + chr(10) + 'TAIL_MARK')\""
            out, code = T.run_bash(root, {"command": cmd})
            self.assertEqual(code, 0)
            self.assertIn("TAIL_MARK", out)
            self.assertIn("절단", out)
            self.assertLessEqual(len(out), T._MAX_OUT + 200)  # 상한 + 마커 여유

    def test_successful_repeated_log_lines_are_compacted(self):
        line = "Compiling same-package"
        out = T._dedup_log("\n".join([line] * 100 + ["done"]))
        self.assertEqual(out, f"{line}\n[... 99 duplicate lines]\ndone")

    def test_failed_command_keeps_repeated_stdout_verbatim(self):
        with tempfile.TemporaryDirectory() as root:
            cmd = "python3 -c \"print('same\\n' * 100, end=''); raise SystemExit(1)\""
            out, code = T.run_bash(root, {"command": cmd})
        self.assertEqual(code, 1)
        self.assertNotIn("duplicate lines", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
