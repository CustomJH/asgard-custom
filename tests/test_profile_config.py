"""에이전트 설정·정체성·개명·내보내기의 코어 계약."""

from __future__ import annotations

import io
import json
import os
import tarfile
import tempfile
import unittest
from unittest import mock

from asgard import profiles, settings


def _clean_env(home: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("ASGARD_")}
    env["HOME"] = home
    env["ASGARD_MEMORY_SEMANTIC"] = "off"
    return env


class ProfileConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self._env = mock.patch.dict(os.environ, _clean_env(self.home), clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_save_profile_config_writes_only_the_named_agent(self) -> None:
        profiles.create("active")
        profiles.create("target")
        profiles.set_active("active")
        with profiles.scoped("active"):
            settings.save_global("provider", {"name": "active"})

        settings.save_profile_config("target", "provider", {"name": "target"})

        self.assertEqual(settings.profile_config("target"), {"provider": {"name": "target"}})
        self.assertEqual(settings.profile_config("active"), {"provider": {"name": "active"}})
        self.assertEqual(profiles.sticky(), "active")

    def test_declared_config_excludes_machine_values_but_view_inherits_them(self) -> None:
        os.makedirs(profiles.root(), exist_ok=True)
        with open(settings.global_path(), "w", encoding="utf-8") as handle:
            json.dump({"ui": {"lang": "ko"}, "provider": {"model": "root"}}, handle)
        profiles.create("alpha")

        self.assertEqual(settings.profile_config("alpha"), {})
        self.assertEqual(
            settings.profile_config_view("alpha"),
            {"ui": {"lang": "ko"}, "provider": {"model": "root"}},
        )

    def test_saved_config_changes_the_scoped_runtime_view(self) -> None:
        profiles.create("alpha")
        path = settings.save_profile_config("alpha", "provider", {"model": "agent-model"})

        self.assertEqual(path, settings.profile_config_path("alpha"))
        with profiles.scoped("alpha"):
            self.assertEqual(settings.load_global()["provider"]["model"], "agent-model")

    def test_rename_moves_the_sticky_pointer(self) -> None:
        profiles.create("old")
        profiles.set_active("old")

        path = profiles.rename("old", "new")

        self.assertEqual(path, profiles.profile_dir("new"))
        self.assertFalse(profiles.exists("old"))
        self.assertTrue(profiles.exists("new"))
        self.assertEqual(profiles.sticky(), "new")
        self.assertEqual(profiles.manifest("new")["id"], "new")
        self.assertEqual(profiles.manifest("new")["name"], "new")

    def test_export_import_roundtrip_keeps_public_profile_data_only(self) -> None:
        source = profiles.create("source")
        profiles.write_identity("source", "나는 배포 검증 에이전트예요.\n")
        settings.save_profile_config("source", "provider", {"model": "M"})
        skill = os.path.join(source, "skills", "review", "SKILL.md")
        os.makedirs(os.path.dirname(skill), exist_ok=True)
        with open(skill, "w", encoding="utf-8") as handle:
            handle.write("# Review\n")
        memory = os.path.join(source, "memory", "pages", "private.md")
        os.makedirs(os.path.dirname(memory), exist_ok=True)
        with open(memory, "w", encoding="utf-8") as handle:
            handle.write("옮기면 안 되는 기억\n")
        archive = os.path.join(self.home, "source.tar.gz")

        profiles.export_archive("source", archive)
        profiles.delete("source")
        imported = profiles.import_archive(archive)

        self.assertEqual(imported, profiles.profile_dir("source"))
        self.assertEqual(profiles.identity("source"), "나는 배포 검증 에이전트예요.\n")
        self.assertEqual(settings.profile_config("source")["provider"], {"model": "M"})
        self.assertTrue(os.path.isfile(os.path.join(imported, "skills", "review", "SKILL.md")))
        self.assertFalse(os.path.exists(os.path.join(imported, "memory", "pages", "private.md")))

    def test_import_rejects_parent_path_escape(self) -> None:
        archive = os.path.join(self.home, "malicious.tar.gz")
        with tarfile.open(archive, "w:gz") as bundle:
            manifest = json.dumps({"id": "evil"}).encode()
            info = tarfile.TarInfo("profile.json")
            info.size = len(manifest)
            bundle.addfile(info, io.BytesIO(manifest))
            payload = b"escaped"
            info = tarfile.TarInfo("../escaped.txt")
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))

        with self.assertRaises(ValueError):
            profiles.import_archive(archive)
        self.assertFalse(os.path.exists(os.path.join(self.home, "escaped.txt")))
        self.assertFalse(profiles.exists("evil"))


if __name__ == "__main__":
    unittest.main()
