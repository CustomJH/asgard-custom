"""에이전트 선택 CLI 계약."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from cli_boundary import run_cli

from asgard import picker, profiles
from asgard.commands import agent as agent_command
from asgard.commands import start as start_command
from asgard.commands import studio


class AgentPickerCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        env = {key: value for key, value in os.environ.items() if not key.startswith("ASGARD_")}
        env["HOME"] = self._tmp.name
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)
        profiles.create("alpha", description="알파 설명")
        profiles.create("beta", description="베타 설명")

    def test_start_agent_passes_the_selected_agent(self) -> None:
        with mock.patch.object(start_command, "run_start", return_value=0) as start:
            result = run_cli("start", "--agent", "alpha")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(start.call_args.kwargs["agent"], "alpha")

    def test_subcommand_agent_overrides_global_agent(self) -> None:
        with mock.patch.object(start_command, "run_start", return_value=0) as start:
            result = run_cli("--agent", "alpha", "start", "--agent", "beta")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(start.call_args.kwargs["agent"], "beta")

    def test_agents_picker_passes_the_choice_to_start_and_raises_a_builtin(self) -> None:
        roster = {"freyja": {"description": "시각 설계", "name": "asgard-freyja"}}
        with (
            mock.patch.object(profiles, "builtin_roster", return_value=roster),
            mock.patch.object(picker, "available", return_value=True),
            mock.patch.object(picker, "pick", return_value="freyja") as pick,
            mock.patch.object(profiles, "ensure") as ensure,
            mock.patch.object(agent_command, "_agent", return_value="freyja"),
            mock.patch.object(start_command, "run_start", return_value=0) as start,
        ):
            result = run_cli("start", "--agents")
        self.assertEqual(result.exit_code, 0, result.output)
        ensure.assert_called_once_with("freyja")
        self.assertEqual(start.call_args.kwargs["agent"], "freyja")
        options = pick.call_args.args[1]
        self.assertTrue(any(option.label.startswith("세운 에이전트 ·") for option in options))
        self.assertTrue(any(option.label == "내장 에이전트 · freyja" for option in options))

    def test_value_less_agent_uses_the_picker(self) -> None:
        with (
            mock.patch.object(picker, "available", return_value=True),
            mock.patch.object(picker, "pick", return_value="alpha") as pick,
            mock.patch.object(start_command, "run_start", return_value=0) as start,
        ):
            result = run_cli("start", "--agent")
        self.assertEqual(result.exit_code, 0, result.output)
        pick.assert_called_once()
        self.assertEqual(start.call_args.kwargs["agent"], "alpha")

    def test_noninteractive_picker_prints_inventory_and_remedy_without_picking(self) -> None:
        roster = {"freyja": {"description": "시각 설계", "name": "asgard-freyja"}}
        with (
            mock.patch.dict(os.environ, {"ASGARD_PLAIN_SELECT": "1"}),
            mock.patch.object(profiles, "builtin_roster", return_value=roster),
            mock.patch.object(picker, "pick") as pick,
        ):
            result = run_cli("start", "--agents")
        self.assertEqual(result.exit_code, 2, result.output)
        pick.assert_not_called()
        self.assertIn("alpha", result.stdout)
        self.assertIn("알파 설명", result.stdout)
        self.assertIn("내장 에이전트 — 아직 안 세웠어요", result.stdout)
        self.assertIn("freyja", result.stdout)
        self.assertIn("asgard start --agent <이름>", result.stderr)

    def test_inventory_separates_configured_and_builtin_agents(self) -> None:
        rows = profiles.listing()
        available = {"freyja": {"description": "시각 설계"}}
        with (
            mock.patch.object(profiles, "listing", return_value=rows),
            mock.patch.object(profiles, "builtin_roster", return_value=available),
        ):
            result = run_cli("agent", "list")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertLess(result.stdout.index("alpha"), result.stdout.index("내장 에이전트"))
        self.assertLess(result.stdout.index("내장 에이전트"), result.stdout.index("freyja"))

    def test_missing_agent_is_not_found_with_a_remedy(self) -> None:
        result = run_cli("start", "--agent", "missing")
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("에이전트 'missing'를 못 찾았어요", result.stderr)
        self.assertIn("asgard agent create missing", result.stderr)

    def test_agent_open_without_a_name_uses_the_picker(self) -> None:
        with (
            mock.patch.object(picker, "available", return_value=True),
            mock.patch.object(picker, "pick", return_value="alpha") as pick,
            mock.patch.object(studio, "run_studio", return_value=0) as open_studio,
        ):
            result = run_cli("agent", "open")
        self.assertEqual(result.exit_code, 0, result.output)
        pick.assert_called_once()
        open_studio.assert_called_once_with(agent="alpha", json_out=False)

    def test_run_start_applies_the_selected_agent_environment(self) -> None:
        with (
            mock.patch("asgard.sandbox.choose_mode", return_value="local"),
            mock.patch("asgard.providers.resolve", return_value=object()),
            mock.patch("asgard.agent.repl.run", return_value=0),
        ):
            self.assertEqual(start_command.run_start(agent="alpha"), 0)
        self.assertEqual(os.environ["ASGARD_PROFILE"], "alpha")
        self.assertEqual(os.environ["ASGARD_HOME"], profiles.profile_dir("alpha"))


if __name__ == "__main__":
    unittest.main()
