"""Studio 요청의 에이전트 정체성과 실행 등록부 계약."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.request
from types import SimpleNamespace
from unittest import mock

from asgard import profiles, settings
from asgard.commands import studio


def _clean_env(home: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("ASGARD_")}
    env.update({"HOME": home, "ASGARD_MEMORY_SEMANTIC": "off"})
    return env


class AgentIdentityCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="asgard-studio-agent-identity-")
        self._env = mock.patch.dict(os.environ, _clean_env(self._tmp.name), clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "project")
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)

    def get(self, path: str, **params: str) -> tuple[int, dict]:
        status, _, body = studio.dispatch("GET", path, {key: [value] for key, value in params.items()}, self.root)
        return status, json.loads(body)

    def make(self, name: str) -> None:
        profiles.create(name)


class TestSnapshotIdentity(AgentIdentityCase):
    def test_snapshot_names_the_explicit_agent_and_source(self):
        self.make("loki-check")

        status, data = self.get("/api/snapshot", agent="loki-check")

        self.assertEqual(status, 200, data)
        self.assertEqual(data["agent"]["id"], "loki-check")
        self.assertEqual(data["agent"]["source"], "explicit")
        self.assertEqual(data["agent"]["home"], profiles.profile_dir("loki-check"))
        self.assertTrue(data["agent"]["key"].startswith("agent:loki-check:"))

    def test_an_explicit_post_is_scoped_to_that_request_only(self):
        self.make("loki-check")
        httpd = studio.server._bind("127.0.0.1", 0, self.root)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{httpd.server_address[1]}/api/settings?agent=loki-check",
                data=json.dumps(
                    {"scope": "global", "section": "ui", "values": {"density": "compact"}}
                ).encode(),
                headers={"Content-Type": "application/json", "X-Asgard-Studio": "1"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
        with profiles.scoped("loki-check"):
            self.assertEqual(settings.load_global()["ui"]["density"], "compact")
        with profiles.scoped("default"):
            self.assertNotEqual(settings.load_global().get("ui", {}).get("density"), "compact")
        self.assertFalse(self.get("/api/agent", name="loki-check", agent="loki-check")[1]["active"])
        self.assertEqual(self.get("/api/snapshot")[1]["agent"]["id"], "default")
        self.assertEqual(profiles.sticky(), "default")

    def test_default_agent_is_never_hidden(self):
        status, data = self.get("/api/snapshot")

        self.assertEqual(status, 200)
        self.assertEqual(data["agent"]["id"], "default")
        self.assertTrue(data["agent"]["is_default"])
        self.assertEqual(data["agent"]["source"], "sticky")

    def test_unknown_explicit_agent_is_a_structured_failure(self):
        status, data = self.get("/api/snapshot", agent="missing-agent")

        self.assertEqual(status, 404)
        self.assertEqual(data["error"]["code"], "agent_not_found")
        self.assertTrue(data["error"]["remedy"])


class TestRunsRoute(AgentIdentityCase):
    def test_runs_route_marks_this_window(self):
        record = {
            "id": "run-self",
            "agent": "default",
            "kind": "studio",
            "url": "http://127.0.0.1:45678/",
            "state": "live",
        }
        server = SimpleNamespace(run_id="run-self")

        with mock.patch("asgard.runs.listing", return_value=[record]), mock.patch.object(
            studio.state, "_SERVER", server
        ):
            status, data = self.get("/api/runs")

        self.assertEqual(status, 200)
        self.assertEqual(data["runs"], [record])
        self.assertEqual(data["self"], "run-self")


if __name__ == "__main__":
    unittest.main()
