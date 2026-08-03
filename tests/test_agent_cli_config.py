"""에이전트 설정·정체성·이름·백업 CLI의 실제 저장 경계."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from cli_boundary import run_cli

from asgard import profiles, settings


def _clean_env(home: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("ASGARD_")}
    env["HOME"] = home
    env["ASGARD_MEMORY_SEMANTIC"] = "off"
    env.pop("EDITOR", None)
    return env


class AgentCliConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self._env = mock.patch.dict(os.environ, _clean_env(self.home), clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)
        profiles.create("x")
        profiles.create("y")

    def invoke(self, *args: str, stdin: str | None = None):
        result = run_cli("agent", *args, stdin=stdin)
        self.assertEqual(result.exit_code, 0, result.output)
        return result

    def test_config_set_changes_the_scoped_runtime_view(self) -> None:
        self.invoke(
            "config",
            "x",
            "--set",
            "provider.model=M",
            "--set",
            "provider.retries=3",
            "--set",
            "provider.enabled=true",
        )
        with profiles.scoped("x"):
            provider = settings.load_global()["provider"]
        self.assertEqual(provider["model"], "M")
        self.assertEqual(provider["retries"], 3)
        self.assertIs(provider["enabled"], True)

    def test_one_agents_config_does_not_touch_another(self) -> None:
        self.invoke("config", "x", "--set", "provider.model=M")
        with profiles.scoped("x"):
            self.assertEqual(settings.load_global()["provider"]["model"], "M")
        with profiles.scoped("y"):
            self.assertNotIn("provider", settings.load_global())

    def test_set_preserves_other_keys_in_the_same_section(self) -> None:
        self.invoke("config", "x", "--set", "provider.name=nvidia")
        self.invoke("config", "x", "--set", "provider.model=M")
        self.assertEqual(settings.profile_config("x")["provider"], {"name": "nvidia", "model": "M"})

    def test_unset_removes_only_the_agents_override(self) -> None:
        settings.save_global("provider", {"name": "nvidia", "model": "ROOT"})
        self.invoke("config", "x", "--set", "provider.model=M", "--set", "provider.retries=3")
        self.invoke("config", "x", "--unset", "provider.model")
        self.assertEqual(settings.profile_config("x")["provider"], {"retries": 3})
        self.assertEqual(settings.profile_config_view("x")["provider"]["model"], "ROOT")

    def test_config_reports_profile_and_machine_sources(self) -> None:
        settings.save_global("provider", {"name": "nvidia", "model": "ROOT"})
        self.invoke("config", "x", "--set", "provider.model=M")
        payload = json.loads(self.invoke("config", "x", "--json").stdout)
        self.assertEqual(payload["sources"]["provider"], {"name": "machine", "model": "profile"})

    def test_config_rejects_a_key_without_a_section(self) -> None:
        result = run_cli("agent", "config", "x", "--set", "model=M", "--json")
        self.assertEqual(result.exit_code, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertIn("remedy", payload["error"])

    def test_identity_set_file_is_loaded_by_the_agent_note(self) -> None:
        source = os.path.join(self.home, "identity.md")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("나는 배포 전 회귀만 확인해요.\n")
        self.invoke("identity", "x", "--set-file", source)
        self.assertIn("배포 전 회귀만 확인해요", profiles.note("x"))

    def test_rename_moves_the_profile_and_old_name_is_not_found(self) -> None:
        self.invoke("rename", "x", "renamed")
        missing = run_cli("agent", "config", "x", "--json")
        self.assertEqual(missing.exit_code, 2)
        self.assertEqual(json.loads(missing.stdout)["error"]["code"], "not_found")
        self.invoke("config", "renamed", "--set", "provider.model=M")
        with profiles.scoped("renamed"):
            self.assertEqual(settings.load_global()["provider"]["model"], "M")

    def test_export_import_roundtrip_keeps_config_and_identity(self) -> None:
        source = os.path.join(self.home, "identity.md")
        archive = os.path.join(self.home, "x.tar.gz")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("나는 왕복 뒤에도 남아야 해요.\n")
        self.invoke("config", "x", "--set", "provider.model=M")
        self.invoke("identity", "x", "--set-file", source)
        self.invoke("export", "x", "-o", archive)
        profiles.delete("x")
        self.invoke("import", archive)
        with profiles.scoped("x"):
            self.assertEqual(settings.load_global()["provider"]["model"], "M")
        self.assertIn("왕복 뒤에도 남아야 해요", profiles.note("x"))

    def test_import_refuses_to_overwrite_an_existing_agent(self) -> None:
        archive = os.path.join(self.home, "x.tar.gz")
        self.invoke("export", "x", "-o", archive)
        result = run_cli("agent", "import", archive, "--json")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "conflict")

    def test_json_surfaces_contain_json_only(self) -> None:
        archive = os.path.join(self.home, "renamed.tar.gz")
        results = [
            self.invoke("config", "x", "--set", "provider.enabled=true", "--json"),
            self.invoke("identity", "x", "--set", "-", "--json", stdin="stdin identity\n"),
            self.invoke("rename", "x", "renamed", "--json"),
            self.invoke("export", "renamed", "-o", archive, "--json"),
        ]
        profiles.delete("renamed")
        results.append(self.invoke("import", archive, "--json"))
        for result in results:
            json.loads(result.stdout)
            self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
