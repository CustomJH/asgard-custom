#!/usr/bin/env python3
"""작업 형상·전문가 표면 주입 — 어느 이벤트에 어느 역할로 묻는가, 그리고 누구에게는 묻지 않는가.

이 층이 없는 동안 `skill_scope.scope_note` 는 네이티브 루프와 사람이 치는 CLI 에서만 닿았고,
세 호스트 모드에서는 모델이 스스로 `asgard skills resolve` 를 치기를 기다렸다 (26-08-13 실측:
Bash 258회 중 0회).
"""

import io
import json
import subprocess
import unittest
from unittest import mock


class Base(unittest.TestCase):
    def invoke(self, payload: dict, mode: str = "claude-code", stdout_text: str | None = None, code: int = 0):
        from asgard.hooks import scope_activate

        completed = subprocess.CompletedProcess(
            ["asgard"],
            code,
            stdout="## Work shape (harness-sized, deterministic)\nshape: **slice** — canary\n"
            if stdout_text is None
            else stdout_text,
            stderr="",
        )
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(scope_activate.sys, "argv", ["scope-activate.py", mode]),
            mock.patch.object(scope_activate.sys, "stdin", io.StringIO(json.dumps(payload))),
            mock.patch.object(scope_activate.sys, "stdout", out),
            mock.patch.object(scope_activate.sys, "stderr", err),
            mock.patch.object(scope_activate.shutil, "which", return_value="/bin/asgard"),
            mock.patch.object(scope_activate.subprocess, "run", return_value=completed) as run,
        ):
            result = scope_activate.main()
        return result, out.getvalue(), err.getvalue(), run


class TestInjection(Base):
    def test_prompt_asks_as_worker_and_injects(self):
        result, stdout, stderr, run = self.invoke(
            {"hook_event_name": "UserPromptSubmit", "prompt": "위젯 뱃지가 행 높이를 따라 줄어들게 해줘", "cwd": "/tmp"}
        )
        self.assertEqual((result, stderr), (0, ""))
        self.assertIn("canary", json.loads(stdout)["hookSpecificOutput"]["additionalContext"])
        argv = run.call_args.args[0]
        self.assertEqual(argv[1:5], ["skills", "resolve", "--agent", "worker"])
        self.assertIn("--scope-only", argv)  # 스킬 본문은 주입면에 넣지 않는다

    def test_cursor_uses_its_own_schema(self):
        _, stdout, _, _ = self.invoke(
            {"hook_event_name": "beforeSubmitPrompt", "prompt": "차트 축 라벨 크기를 조정해줘", "cwd": "/tmp"},
            "cursor",
        )
        self.assertIn("canary", json.loads(stdout)["additional_context"])

    def test_dispatched_specialist_is_asked_as_itself(self):
        for agent, role in (("asgard-freyja", "freyja"), ("asgard-thor", "thor"), ("asgard-eitri", "eitri")):
            with self.subTest(agent=agent):
                _, stdout, _, run = self.invoke(
                    {
                        "hook_event_name": "SubagentStart",
                        "agent_type": agent,
                        "prompt": "이 표면을 손봐줘",
                        "cwd": "/tmp",
                    }
                )
                self.assertEqual(run.call_args.args[0][4], role)
                self.assertIn("canary", stdout)


class TestSilence(Base):
    def test_judging_surfaces_never_receive_it(self):
        """판정자와 로키에게 advisory 지식을 주면 판정이 그 지식을 따라간다 (AGENTS.md 스킬 절)."""
        for agent in ("asgard-verifier", "asgard-loki"):
            with self.subTest(agent=agent):
                _, stdout, _, run = self.invoke(
                    {"hook_event_name": "SubagentStart", "agent_type": agent, "prompt": "판정해줘", "cwd": "/tmp"}
                )
                self.assertEqual(stdout, "")
                run.assert_not_called()

    def test_unknown_agent_is_not_asked_as_worker(self):
        """표에 없는 이름에 worker 를 넘기면 남의 역할 규율을 읽힌다."""
        _, stdout, _, run = self.invoke(
            {"hook_event_name": "SubagentStart", "agent_type": "some-other-agent", "prompt": "무언가", "cwd": "/tmp"}
        )
        self.assertEqual(stdout, "")
        run.assert_not_called()

    def test_short_prompt_gets_no_planning_discipline(self):
        _, stdout, _, run = self.invoke({"hook_event_name": "UserPromptSubmit", "prompt": "고마워", "cwd": "/tmp"})
        self.assertEqual(stdout, "")
        run.assert_not_called()

    def test_stop_and_other_events_are_untouched(self):
        for event in ("Stop", "SessionStart", "PostToolUse"):
            with self.subTest(event=event):
                _, stdout, _, run = self.invoke({"hook_event_name": event, "prompt": "무언가 긴 요청", "cwd": "/tmp"})
                self.assertEqual(stdout, "")
                run.assert_not_called()

    def test_cli_failure_is_silent(self):
        """형상 힌트가 없다고 잘못되는 것은 없다 — 훅이 실패해도 턴은 돈다."""
        _, stdout, stderr, _ = self.invoke(
            {"hook_event_name": "UserPromptSubmit", "prompt": "긴 요청 문장 하나", "cwd": "/tmp"},
            stdout_text="",
            code=2,
        )
        self.assertEqual((stdout, stderr), ("", ""))


class TestWiring(unittest.TestCase):
    def test_every_host_wires_it(self):
        from asgard.templates import claude, codex, cursor

        for name, body in (
            ("claude", claude.cc_settings()),
            ("codex", codex.codex_config()),
            ("cursor", cursor.cursor_hooks_json()),
        ):
            with self.subTest(host=name):
                self.assertIn("scope-activate.py", body)

    def test_setup_ships_the_file(self):
        from asgard.commands import setup

        files, _ = setup.plan_files(cc=True, cursor=False, codex=False)
        self.assertTrue(any(path.endswith("scope-activate.py") for path, _ in files))


if __name__ == "__main__":
    unittest.main()
