"""프로젝트 자동화 — due 판정과 명시적 실행 경계의 계약."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from cli_boundary import run_cli

from asgard import automations


def _entry(schedule: str, created: datetime, *, enabled: bool = True) -> dict:
    return {
        "id": "a1",
        "name": "daily-check",
        "prompt": "검사해줘",
        "schedule": schedule,
        "enabled": enabled,
        "created_at": created.isoformat(),
        "last_run": None,
        "last_outcome": None,
    }


@contextmanager
def _cwd(path: str):
    before = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


class TestDueComputation(unittest.TestCase):
    """시간은 전부 인자로 준다 — 실제 시계나 Quest는 이 판정에 들어오지 않는다."""

    now = datetime(2026, 8, 3, 10, 30, tzinfo=UTC)  # 월요일

    def test_each_named_schedule_and_five_field_cron(self):
        cases = {
            "hourly": self.now - timedelta(hours=1),
            "daily": self.now - timedelta(days=1),
            "weekdays": self.now - timedelta(days=3),
            "weekly": self.now - timedelta(days=7),
            "30 10 * * 1-5": self.now - timedelta(minutes=1),
        }
        for schedule, created in cases.items():
            with self.subTest(schedule=schedule):
                self.assertTrue(automations.due(_entry(schedule, created), self.now))

    def test_named_schedule_waits_for_its_next_period(self):
        for schedule in automations.NAMED_SCHEDULES:
            with self.subTest(schedule=schedule):
                self.assertFalse(automations.due(_entry(schedule, self.now), self.now + timedelta(minutes=1)))

    def test_cron_catches_up_after_the_exact_minute(self):
        entry = _entry("0 9 * * 1-5", self.now - timedelta(days=1))
        self.assertTrue(automations.due(entry, self.now))

    def test_disabled_entry_is_never_due(self):
        self.assertFalse(automations.due(_entry("hourly", self.now - timedelta(days=1), enabled=False), self.now))

    def test_naive_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            automations.due(_entry("hourly", self.now), self.now.replace(tzinfo=None))


class TestStoreAndOutcome(unittest.TestCase):
    def test_corrupt_file_degrades_to_no_automations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = automations.state_path(tmp)
            path.parent.mkdir(parents=True)
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(automations.list_automations(tmp), [])
            self.assertEqual(automations.due_automations(automations.list_automations(tmp), datetime.now(UTC)), [])

    def test_run_records_failure_in_entry_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            created = datetime(2026, 8, 3, 9, tzinfo=UTC)
            automations.add(tmp, "check", "검사해줘", "hourly", created)
            now = created + timedelta(hours=1)
            finished = now + timedelta(seconds=3)
            result = automations.run_due(tmp, now, lambda _prompt: 7, lambda: finished)
            self.assertEqual(result[0]["status"], "failed")
            entry = automations.list_automations(tmp)[0]
            self.assertEqual(entry["last_outcome"]["exit_code"], 7)
            self.assertEqual(automations.history(tmp)[0]["status"], "failed")


class TestAutomationCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".git").mkdir()
        self.cwd = _cwd(str(self.root))
        self.cwd.__enter__()

    def tearDown(self):
        self.cwd.__exit__(None, None, None)
        self.temp.cleanup()

    def invoke(self, *args: str):
        result = run_cli("automations", *args)
        self.assertEqual(result.stderr, "")
        return result

    def test_add_list_disable_enable_due_history_remove(self):
        added = self.invoke("add", "morning", "검사해줘", "--schedule", "hourly", "--json")
        self.assertEqual(added.exit_code, 0)
        self.assertEqual(json.loads(added.stdout)["name"], "morning")

        listed = json.loads(self.invoke("list", "--json").stdout)
        self.assertEqual(listed["count"], 1)
        self.assertEqual(self.invoke("disable", "morning", "--json").exit_code, 0)
        self.assertFalse(json.loads(self.invoke("list", "--json").stdout)["automations"][0]["enabled"])
        self.assertEqual(self.invoke("enable", "morning", "--json").exit_code, 0)

        path = automations.state_path(self.root)
        state = json.loads(path.read_text(encoding="utf-8"))
        state["automations"][0]["created_at"] = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        path.write_text(json.dumps(state), encoding="utf-8")
        preview = json.loads(self.invoke("due", "--json").stdout)
        self.assertFalse(preview["execute"])
        self.assertEqual(len(preview["due"]), 1)

        with mock.patch("asgard.commands.automations._run_prompt_once", return_value=0) as execute:
            ran = self.invoke("due", "--run", "--json")
        self.assertEqual(ran.exit_code, 0)
        execute.assert_called_once_with(os.path.realpath(self.root), "검사해줘")
        self.assertEqual(json.loads(self.invoke("history", "--json").stdout)["history"][0]["status"], "succeeded")
        self.assertEqual(self.invoke("remove", "morning", "--json").exit_code, 0)
        self.assertEqual(json.loads(self.invoke("list", "--json").stdout)["count"], 0)


if __name__ == "__main__":
    unittest.main()
