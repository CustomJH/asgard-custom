"""Unified mode configuration matrix and write-path regression tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from typer.testing import CliRunner


class TestModeConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.root = os.path.join(self.tmp.name, "project")
        os.makedirs(self.root)
        self.environment = mock.patch.dict(os.environ, {"HOME": self.home})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("ASGARD_HOME", None)
        os.environ.pop("ASGARD_PROFILE", None)

    def _write(self, path: str, data: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def test_matrix_resolves_each_axis_and_its_source(self) -> None:
        from asgard.commands.mode import mode_state

        self._write(
            os.path.join(self.home, ".asgard", "asgard-setting-global.json"),
            {
                "agent_models": {"codex": {"worker": {"model": "global-worker", "effort": "low"}}},
                "trinity": {"worker": {"provider": "ollama", "model": "global-native"}},
            },
        )
        self._write(
            os.path.join(self.root, ".asgard", "asgard-setting-project.json"),
            {
                "agent_models": {"codex": {"worker": {"effort": "high"}}},
                "trinity": {"worker": {"model": "project-native"}},
                "agents": {"roles": {"worker": "default"}},
            },
        )

        state = mode_state(self.root)
        self.assertEqual(tuple(state["modes"]), ("native", "claude-code", "cursor", "codex"))
        codex = state["modes"]["codex"]["roles"]["worker"]
        self.assertEqual(
            (codex["agent"], codex["provider"], codex["model"], codex["effort"]),
            (
                "default",
                "codex",
                "global-worker",
                "high",
            ),
        )
        self.assertEqual(
            codex["source"],
            {
                "model": "global",
                "effort": "project",
                "provider": "built-in default",
                "agent": "project",
            },
        )
        native = state["modes"]["native"]["roles"]["worker"]
        self.assertEqual((native["provider"], native["model"]), ("ollama", "project-native"))
        self.assertEqual(native["source"]["provider"], "global")
        self.assertEqual(native["source"]["model"], "project")

    def test_set_and_reset_round_trip_through_existing_stores(self) -> None:
        from asgard import swarm
        from asgard.commands.mode import configure_mode, mode_state, reset_mode
        from asgard.providers import project_section

        configure_mode(
            self.root,
            "codex",
            "worker",
            agent="default",
            model="custom-worker",
            effort="max",
        )
        self.assertEqual(
            project_section(self.root, "agent_models.codex.worker"),
            {"model": "custom-worker", "effort": "max"},
        )
        self.assertEqual(swarm.binding(self.root)["roles"]["worker"], "default")
        cell = mode_state(self.root, "codex")["modes"]["codex"]["roles"]["worker"]
        self.assertEqual((cell["agent"], cell["model"], cell["effort"]), ("default", "custom-worker", "max"))
        self.assertEqual(cell["source"]["agent"], "project")
        self.assertEqual(cell["source"]["model"], "project")

        reset_mode(self.root, "codex", "worker")
        self.assertEqual(project_section(self.root, "agent_models.codex.worker"), {})
        self.assertNotIn("worker", swarm.binding(self.root)["roles"])
        reset_cell = mode_state(self.root, "codex")["modes"]["codex"]["roles"]["worker"]
        self.assertEqual(reset_cell["model"], "gpt-5.6-terra")
        self.assertEqual(reset_cell["source"]["model"], "built-in default")

    def test_mode_agent_and_bulk_model_reset(self) -> None:
        from asgard import swarm
        from asgard.commands.mode import configure_mode, reset_mode
        from asgard.providers import project_section

        configure_mode(self.root, "cursor", agent="default")
        configure_mode(self.root, "cursor", "worker", model="custom-worker")
        configure_mode(self.root, "cursor", "thinker", model="custom-thinker")
        self.assertEqual(swarm.binding(self.root)["modes"]["cursor"], "default")

        reset_mode(self.root, "cursor")
        self.assertNotIn("cursor", swarm.binding(self.root)["modes"])
        self.assertEqual(project_section(self.root, "agent_models.cursor"), {})

    def test_validation_matches_role_model_contract(self) -> None:
        from asgard.commands.mode import configure_mode

        invalid = (
            ("native", "worker", {"effort": "high"}, "native"),
            ("cursor", "worker", {"effort": "high"}, "model slug"),
            ("codex", "worker", {"provider": "ollama"}, "native"),
            ("codex", None, {"model": "x"}, "role"),
            ("unknown", "worker", {"model": "x"}, "mode"),
            ("codex", "unknown", {"model": "x"}, "role"),
            ("codex", "worker", {"agent": "missing-agent"}, "없음"),
        )
        for mode, role, options, message in invalid:
            with self.subTest(mode=mode, role=role, options=options):
                with self.assertRaisesRegex((ValueError, FileNotFoundError), message):
                    configure_mode(self.root, mode, role, **options)

    def test_cli_matrix_show_round_trip_and_non_tty_picker(self) -> None:
        from asgard.cli import app

        runner = CliRunner()
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            listed = runner.invoke(app, ["mode", "--json"])
            shown = runner.invoke(app, ["mode", "show", "codex", "--json"])
            changed = runner.invoke(app, ["mode", "set", "codex", "worker", "--model", "cli-worker"])
            reset = runner.invoke(app, ["mode", "reset", "codex", "worker"])
            picked = runner.invoke(app, ["mode", "pick"])
        finally:
            os.chdir(cwd)

        self.assertEqual(listed.exit_code, 0, listed.output)
        self.assertEqual(tuple(json.loads(listed.output)["modes"]), ("native", "claude-code", "cursor", "codex"))
        self.assertEqual(shown.exit_code, 0, shown.output)
        self.assertEqual(tuple(json.loads(shown.output)["modes"]), ("codex",))
        self.assertEqual(changed.exit_code, 0, changed.output)
        self.assertEqual(json.loads(changed.output)["effective"]["roles"]["worker"]["model"], "cli-worker")
        self.assertEqual(reset.exit_code, 0, reset.output)
        self.assertEqual(picked.exit_code, 2)
        self.assertIn("TTY", picked.output)


if __name__ == "__main__":
    unittest.main()
