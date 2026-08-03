"""Studio 프로파일 전환이 창과 작업 기록에 적용되는지 확인한다."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from asgard import profiles
from asgard.commands import studio, studio_store


def _clean_env(home: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("ASGARD_")}
    env.update(
        {
            "HOME": home,
            "ASGARD_MEMORY_SEMANTIC": "off",
            studio_store.STUDIO_STATE_ENV: os.path.join(home, "studio-state"),
        }
    )
    return env


class AgentSwitchCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="asgard-studio-agent-switch-")
        self._env = mock.patch.dict(os.environ, _clean_env(self._tmp.name), clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "project")
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        profiles.create("switch-a")
        profiles.create("switch-b")
        with studio.state._TASK_LOCK:
            studio.state._TASKS.clear()
        studio.state._LOADED_ROOTS.clear()

    def get_tasks(self, agent: str, *, all_projects: bool = False) -> list[dict]:
        params = {"agent": [agent]}
        if all_projects:
            params["scope"] = ["all"]
        studio.dispatch("GET", "/api/snapshot", {"agent": [agent]}, self.root)
        status, _, body = studio.dispatch("GET", "/api/tasks", params, self.root)
        self.assertEqual(status, 200)
        return json.loads(body)

    def create_task(self, agent: str, prompt: str) -> dict:
        status, _, body = studio.dispatch_post(
            "/api/tasks",
            {"prompt": prompt, "permission": "manual"},
            self.root,
            {"agent": [agent]},
        )
        self.assertEqual(status, 202)
        return json.loads(body)


class TestTaskProfileBoundary(AgentSwitchCase):
    def test_two_profiles_do_not_see_each_others_tasks_or_feed(self) -> None:
        a = self.create_task("switch-a", "A 프로파일 작업")
        b = self.create_task("switch-b", "B 프로파일 작업")

        self.assertEqual([row["id"] for row in self.get_tasks("switch-a")], [a["id"]])
        self.assertEqual([row["id"] for row in self.get_tasks("switch-b")], [b["id"]])
        self.assertEqual([row["id"] for row in self.get_tasks("switch-a", all_projects=True)], [a["id"]])
        self.assertEqual([row["id"] for row in self.get_tasks("switch-b", all_projects=True)], [b["id"]])

    def test_same_task_id_is_kept_separately_in_process_state(self) -> None:
        base = {"id": "same", "status": "ready", "created": 1, "updated": 1, "root": self.root}
        studio_store.save_task(self.root, {**base, "prompt": "A 작업", "agent": "switch-a"})
        studio_store.save_task(self.root, {**base, "prompt": "B 작업", "agent": "switch-b"})

        with profiles.scoped("switch-a"):
            studio.load_project_tasks(self.root)
            self.assertEqual(studio.state._TASKS["same"]["prompt"], "A 작업")
        with profiles.scoped("switch-b"):
            studio.load_project_tasks(self.root)
            self.assertEqual(studio.state._TASKS["same"]["prompt"], "B 작업")

    def test_a_row_without_agent_is_visible_only_to_default(self) -> None:
        studio_store.save_task(
            self.root,
            {"id": "legacy", "prompt": "예전 작업", "status": "ready", "created": 1, "updated": 1},
        )

        self.assertEqual(self.get_tasks("switch-a"), [])
        self.assertEqual(self.get_tasks("switch-b", all_projects=True), [])
        self.assertEqual([row["id"] for row in self.get_tasks("default")], ["legacy"])
        self.assertEqual([row["id"] for row in self.get_tasks("default", all_projects=True)], ["legacy"])

    def test_default_task_keeps_the_existing_command_shape(self) -> None:
        task = self.create_task("default", "기본 작업")

        self.assertEqual(task["agent"], "")
        self.assertEqual(self.get_tasks("default")[0]["id"], task["id"])
        with profiles.scoped("default"):
            self.assertNotIn("--agent", studio.state._TASKS[task["id"]]["command"])


if __name__ == "__main__":
    unittest.main()
