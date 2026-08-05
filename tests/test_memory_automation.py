from __future__ import annotations

import datetime as dt
import io
import json
import tempfile
import types
import unittest
from unittest import mock

from asgard.project_memory import automation


class ProjectMemoryAutomationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.cfg = {
            "engine": "hindsight",
            "endpoint": "http://memory",
            "project_id": "asgard-test1",
            "project_uid": "11111111-1111-1111-1111-111111111111",
            "binding_id": "22222222-2222-2222-2222-222222222222",
        }
        self.today = dt.date(2026, 8, 6)

    def tearDown(self):
        self.tmp.cleanup()

    def connected(self, *, trusted: bool = True):
        return (
            mock.patch.object(automation, "find_config", return_value=(self.root, dict(self.cfg))),
            mock.patch.object(automation, "is_backend_trusted", return_value=trusted),
        )

    def test_balanced_is_the_default_and_fifty_percent_alias(self):
        self.assertEqual(automation.management_mode({}), automation.MODE_BALANCED)
        self.assertEqual(automation.management_mode({"auto_manage": 50}), automation.MODE_BALANCED)
        self.assertEqual(automation.management_mode({"auto_manage": "50%"}), automation.MODE_BALANCED)
        self.assertEqual(automation.management_mode({"auto_manage": "off"}), automation.MODE_OFF)
        self.assertEqual(automation.management_mode({"auto_manage": "unknown"}), automation.MODE_OFF)

    def test_connected_trusted_project_starts_only_the_derived_learning_pass(self):
        found, trusted = self.connected()
        with found, trusted, mock.patch.object(automation, "spawn_pass", return_value=True) as spawn:
            line = automation.wake(self.root, today=self.today)

        self.assertIn("balanced: 파생층 자동, 정본 교정은 승인 대기", line or "")
        spawn.assert_called_once_with(self.root, "memory", "project-learn", "--apply", "--json")
        state = automation._state(self.root)
        self.assertEqual(state["mode"], automation.MODE_BALANCED)
        self.assertEqual(state["last_learning_started"], "2026-08-06")

    def test_same_target_is_latched_until_the_interval_passes(self):
        found, trusted = self.connected()
        with found, trusted, mock.patch.object(automation, "spawn_pass", return_value=True) as spawn:
            first = automation.wake(self.root, today=self.today)
            second = automation.wake(self.root, today=self.today + dt.timedelta(days=6))
            third = automation.wake(self.root, today=self.today + dt.timedelta(days=7))

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNotNone(third)
        self.assertEqual(spawn.call_count, 2)

    def test_clock_rollback_rechecks_once_instead_of_waiting_for_the_future_date(self):
        found, trusted = self.connected()
        with found, trusted, mock.patch.object(automation, "spawn_pass", return_value=True) as spawn:
            automation.wake(self.root, today=self.today + dt.timedelta(days=10))
            self.assertIsNotNone(automation.wake(self.root, today=self.today))
        self.assertEqual(spawn.call_count, 2)

    def test_new_target_is_due_without_waiting_for_the_interval(self):
        found, trusted = self.connected()
        with found, trusted, mock.patch.object(automation, "spawn_pass", return_value=True) as spawn:
            automation.wake(self.root, today=self.today)
        self.cfg["binding_id"] = "33333333-3333-3333-3333-333333333333"
        found, trusted = self.connected()
        with found, trusted, mock.patch.object(automation, "spawn_pass", return_value=True) as second_spawn:
            automation.wake(self.root, today=self.today)
        self.assertEqual(spawn.call_count + second_spawn.call_count, 2)

    def test_unconnected_untrusted_and_disabled_projects_are_silent(self):
        with mock.patch.object(automation, "find_config", return_value=None):
            self.assertIsNone(automation.wake(self.root, today=self.today))

        found, untrusted = self.connected(trusted=False)
        with found, untrusted, mock.patch.object(automation, "spawn_pass") as spawn:
            self.assertIsNone(automation.wake(self.root, today=self.today))
        spawn.assert_not_called()

        self.cfg["auto_manage"] = "off"
        found, trusted = self.connected()
        with found, trusted, mock.patch.object(automation, "spawn_pass") as spawn:
            self.assertIsNone(automation.wake(self.root, today=self.today))
        spawn.assert_not_called()

    def test_spawn_failure_does_not_consume_the_next_retry(self):
        found, trusted = self.connected()
        with found, trusted, mock.patch.object(automation, "spawn_pass", side_effect=[False, True]) as spawn:
            self.assertIsNone(automation.wake(self.root, today=self.today))
            self.assertIsNotNone(automation.wake(self.root, today=self.today))
        self.assertEqual(spawn.call_count, 2)

    def test_sync_turn_returns_the_maintenance_signal_without_blocking_json(self):
        from asgard.commands.memory import autosave

        payload = {"user_text": "읽기", "assistant_text": "응답", "verified": False}
        stdout = io.StringIO()
        with (
            mock.patch.object(autosave, "find_config", return_value=(self.root, dict(self.cfg))),
            mock.patch.object(autosave, "auto_retain_turns_state", return_value=autosave.GATE_OFF),
            mock.patch("asgard.project_memory.automation.wake", return_value="mental model 시작"),
            mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
            mock.patch("sys.stdout", stdout),
        ):
            self.assertEqual(autosave.run_sync_turn("codex"), 0)
        self.assertEqual(json.loads(stdout.getvalue())["automation"], "mental model 시작")

    def test_native_quest_close_surfaces_the_same_learning_signal(self):
        from asgard.agent.heimdall.trinity import TrinityRun

        shown: list[str] = []
        run = TrinityRun.__new__(TrinityRun)
        run._hd = types.SimpleNamespace(root=self.root, on_text=shown.append)
        with (
            mock.patch("asgard.memory.norn.wake", return_value=None),
            mock.patch("asgard.memory.pattern.wake", return_value=None),
            mock.patch("asgard.project_memory.evolve.wake", return_value=None),
            mock.patch("asgard.project_memory.automation.wake", return_value="mental model 시작"),
        ):
            run._tend_memory()
        self.assertTrue(any("mental model 시작" in line for line in shown))


if __name__ == "__main__":
    unittest.main()
