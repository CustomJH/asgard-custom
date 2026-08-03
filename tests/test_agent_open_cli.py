"""에이전트-우선 Studio 문과 실행 등록부의 CLI 계약."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.request
from unittest import mock

from cli_boundary import run_cli

from asgard import errors, profiles, runs
from asgard.commands import agent as agent_command
from asgard.commands import studio
from asgard.commands.studio import agents as studio_agents


class AgentOpenCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        env = {key: value for key, value in os.environ.items() if not key.startswith("ASGARD_")}
        env.update({"HOME": self._tmp.name, runs.RUNS_ENV: os.path.join(self._tmp.name, "state")})
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)
        profiles.create("alpha")
        profiles.create("beta")

    def register(self, agent: str = "alpha") -> dict:
        row = runs.register(agent, "studio", "127.0.0.1", 41001, f"http://127.0.0.1:41001/?agent={agent}")
        self.addCleanup(runs.unregister, row["id"], row["token"])
        return row

    def test_open_studio_has_first_class_agent_and_isolated_options(self) -> None:
        result = run_cli("open", "studio", "--help")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--agent", result.stdout)
        self.assertIn("overrides the", result.stdout)
        self.assertIn("global --agent option", result.stdout)
        self.assertIn("--isolated", result.stdout)

    def test_subcommand_agent_overrides_global_agent(self) -> None:
        with mock.patch.object(studio, "run_studio", return_value=0) as start:
            result = run_cli(
                "--agent",
                "alpha",
                "open",
                "studio",
                "--agent",
                "beta",
                "--isolated",
                "--no-open",
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(start.call_args.kwargs["agent"], "beta")
        self.assertIs(start.call_args.kwargs["isolated"], True)

    def test_agent_open_reuses_a_live_registered_window(self) -> None:
        row = self.register()
        with mock.patch.object(studio, "run_studio", return_value=0) as start:
            result = run_cli("agent", "open", "alpha")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(row["url"], result.stdout)
        start.assert_not_called()

    def test_agent_open_new_starts_even_when_a_window_is_live(self) -> None:
        self.register()
        with mock.patch.object(studio, "run_studio", return_value=0) as start:
            result = run_cli("agent", "open", "alpha", "--new")
        self.assertEqual(result.exit_code, 0, result.output)
        start.assert_called_once_with(agent="alpha", json_out=False)

    def test_agent_open_json_reports_reuse_without_human_output(self) -> None:
        row = self.register()
        result = run_cli("agent", "open", "alpha", "--json")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), {"window": {**row, "state": "live"}, "reused": True})

    def test_agent_windows_json_reflects_the_registry_only(self) -> None:
        row = self.register()
        result = run_cli("agent", "windows", "--json")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        current = next(item for item in payload["windows"] if item["id"] == row["id"])
        for key in ("agent", "url", "pid", "state", "started"):
            self.assertIn(key, current)
        self.assertEqual(current["state"], "live")

    def test_windows_explains_stale_and_indeterminate_records(self) -> None:
        rows = [
            {"agent": "alpha", "url": "http://a", "pid": 1, "state": "stale", "started": 1},
            {"agent": "beta", "url": "http://b", "pid": 2, "state": "indeterminate", "started": 2},
        ]
        with mock.patch.object(runs, "listing", return_value=rows):
            result = run_cli("agent", "windows")
        self.assertIn("stale 등록이 있어요", result.stdout)
        self.assertIn("indeterminate 등록은", result.stdout)
        self.assertIn("자동으로 지우지 않아요", result.stdout)

    def test_server_registers_the_actual_port_and_unregisters_on_close(self) -> None:
        httpd = studio.server._bind("127.0.0.1", 0, self._tmp.name, agent="alpha")
        actual = int(httpd.server_address[1])
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{actual}/health", timeout=5) as response:
                self.assertEqual(response.status, 200)
            row = next(item for item in runs.listing(prune=False) if item["id"] == httpd.run_id)
            self.assertNotEqual(actual, 0)
            self.assertEqual(row["port"], actual)
            self.assertEqual(row["agent"], "alpha")
            self.assertIn("agent=alpha", row["url"])
            self.assertEqual(httpd.run_token, row["token"])
        finally:
            run_id = httpd.run_id
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
        self.assertFalse(any(item["id"] == run_id for item in runs.listing(prune=False)))

    def _scope(self, root: str, explicit: str) -> dict:
        """요청 하나의 범위. 거절되면 그 자리에서 실패시킨다 — 뒤 단언이 볼 것이 없다."""
        scoped, refused = studio_agents.request_scope(root, explicit)
        if scoped is None:
            self.fail(f"범위를 못 잡았어요: {refused}")
        return scoped

    def test_startup_url_carries_the_agent_only_when_it_was_named(self) -> None:
        """배지가 왜 그 에이전트인지를 거짓으로 말하지 않는가 — 회귀 방지.

        고친 결함: 시동 URL이 **해석된** 에이전트를 실어서, 배치나 끈끈한 활성으로 연 창도
        `?agent=`를 달고 열렸다. 창은 그 쿼리를 명시 선택으로 읽으므로 배지가 늘 "고정"이라고
        말했다 — 출처를 구분하려고 만든 신호가 통째로 죽어 있었다."""
        profiles.set_active("beta")

        implicit = studio.server._bind("127.0.0.1", 0, self._tmp.name)
        try:
            self.assertEqual(implicit.agent, "beta")  # 해석은 됐다
            self.assertEqual(implicit.agent_explicit, "")  # 그러나 명시는 아니었다
            self.assertEqual(implicit.agent_source, "sticky")
            url = studio.server._studio_url("127.0.0.1", 1, implicit.agent_explicit)
            self.assertNotIn("agent=", url)
        finally:
            implicit.server_close()

        named = studio.server._bind("127.0.0.1", 0, self._tmp.name, agent="alpha")
        try:
            self.assertEqual(named.agent_explicit, "alpha")
            self.assertEqual(named.agent_source, "explicit")
            self.assertIn("agent=alpha", studio.server._studio_url("127.0.0.1", 1, named.agent_explicit))
        finally:
            named.server_close()

    def test_a_named_server_answers_as_that_agent_without_a_query(self) -> None:
        """`--isolated`가 기대는 자리 — 쿼리 없는 요청도 서버가 묶인 에이전트로 답한다.

        시동 URL이 늘 `?agent=`를 실을 때는 모든 요청이 명시로 들어와 이 갈래가 안 드러났다.
        URL을 바로잡으면 서버가 자기 배치를 스스로 알아야 하고, 모르면 격리 서버가 남의
        에이전트로 답한다."""
        profiles.set_active("beta")
        httpd = studio.server._bind("127.0.0.1", 0, self._tmp.name, agent="alpha", isolated=True)
        try:
            scoped = self._scope(httpd.root, "")
            self.assertEqual(scoped["agent"], "alpha")  # 끈끈한 활성(beta)이 아니다
            self.assertEqual(scoped["source"], "explicit")
            other = self._scope(httpd.root, "beta")
            self.assertEqual(other["agent"], "beta")  # 쿼리는 그 요청만 갈아끼운다
        finally:
            httpd.server_close()

    def test_missing_agent_is_not_found_with_a_remedy(self) -> None:
        with self.assertRaises(errors.NotFound) as raised:
            agent_command.run_agent_open("missing")
        self.assertIn("asgard agent create missing", raised.exception.remedy)
        result = run_cli("agent", "open", "missing")
        self.assertEqual(result.exit_code, 2)
        self.assertIn("asgard agent create missing", result.stderr)

    def test_native_shell_receives_the_window_agent(self) -> None:
        with (
            mock.patch.object(studio.server, "_native_candidates", return_value=["/app/asgard-studio"]),
            mock.patch.object(studio.server.subprocess, "run") as run,
        ):
            self.assertTrue(studio.server._open_native("http://127.0.0.1:8766/", "/project", "alpha"))
        self.assertEqual(run.call_args.kwargs["env"]["ASGARD_STUDIO_AGENT"], "alpha")


if __name__ == "__main__":
    unittest.main()
