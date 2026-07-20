#!/usr/bin/env python3
"""asgard sync — 레지스트리·병합 정책·프로젝트 코어 갱신 (전부 결정론, 네트워크 없음).

계약: init 이 레지스트리에 기록하고, sync 는 asgard 소유 파일만 최신화하며 사용자 편집
(AGENTS.md Conventions·settings.json permissions·trinity-policy 튜닝)은 보존한다.

실행: uv run pytest tests/test_sync.py
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from asgard import registry, ui
from asgard.commands.sync import merge_agents_md, merge_cc_settings, run_sync, sync_project
from asgard.templates import agents_md, cc_settings


class Base(unittest.TestCase):
    def setUp(self):
        ui.set_quiet(True)
        self._home = tempfile.TemporaryDirectory()  # ~/.asgard 격리 — 실 레지스트리 오염 방지
        self._proj = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._proj.name)
        self._env = mock.patch.dict(os.environ, {"HOME": self._home.name})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._home.cleanup()
        self._proj.cleanup()


class TestRegistry(Base):
    def test_record_load_dedupe_forget(self):
        registry.record(self.root, cc=True, cursor=False, codex=False)
        registry.record(self.root, cc=True, cursor=True, codex=False)  # upsert — 같은 root 는 교체
        entries = registry.load()
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]["cc"], entries[0]["cursor"], entries[0]["codex"]), (True, True, False))
        registry.forget(self.root)
        self.assertEqual(registry.load(), [])

    def test_load_broken_file_fails_open(self):
        os.makedirs(os.path.join(self._home.name, ".asgard"), exist_ok=True)
        open(os.path.join(self._home.name, ".asgard", "projects.json"), "w").write("{broken")
        self.assertEqual(registry.load(), [])

    def test_setup_records_project(self):
        from asgard.commands.setup import run_setup

        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertEqual(run_setup(cc=True), 0)
        finally:
            os.chdir(cwd)
        entries = registry.load()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["root"], self.root)
        self.assertTrue(entries[0]["cc"])
        self.assertFalse(entries[0]["cursor"])
        self.assertTrue(os.path.exists(os.path.join(self.root, ".asgard", "map", "PROJECT.md")))

    def test_setup_preflights_unsafe_map_before_scaffolding(self):
        from asgard.commands.setup import run_setup

        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        os.makedirs(os.path.join(self.root, ".asgard"))
        os.symlink(outside.name, os.path.join(self.root, ".asgard", "map"))
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            with mock.patch("asgard.commands.setup._scaffold") as scaffold:
                self.assertEqual(run_setup(cc=True), 2)
                scaffold.assert_not_called()
        finally:
            os.chdir(cwd)

    def test_setup_preflights_dangling_map_before_scaffolding(self):
        from asgard.commands.setup import run_setup

        os.makedirs(os.path.join(self.root, ".asgard"))
        os.symlink(os.path.join(self.root, "missing-map"), os.path.join(self.root, ".asgard", "map"))
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            with mock.patch("asgard.commands.setup._scaffold") as scaffold:
                self.assertEqual(run_setup(cc=True), 2)
                scaffold.assert_not_called()
        finally:
            os.chdir(cwd)


class TestAgentsMerge(Base):
    def test_blocks_replaced_user_content_preserved(self):
        new = agents_md("proj")
        old = new.replace("오딘 우선", "옛날 문구")  # 구버전 블록 시뮬레이션
        old = old.replace(
            "<!-- Add project conventions, build/test commands, and architecture notes here. -->",
            "uv run pytest — 우리 팀 규칙",
        )
        merged = merge_agents_md(old, new)
        assert merged is not None
        self.assertIn("오딘 우선", merged)  # 블록은 최신으로
        self.assertNotIn("옛날 문구", merged)
        self.assertIn("uv run pytest — 우리 팀 규칙", merged)  # 블록 밖 사용자 내용 보존

    def test_new_block_inserted_when_missing(self):
        import re

        new = agents_md("proj")
        old = re.sub(r"<!-- >>> asgard:lagom >>> -->\n.*?<!-- <<< asgard:lagom <<< -->", "", new, flags=re.S)
        self.assertNotIn("asgard:lagom", old)
        merged = merge_agents_md(old, new)
        assert merged is not None
        self.assertIn("<!-- >>> asgard:lagom >>> -->", merged)

    def test_user_owned_file_untouched(self):
        self.assertIsNone(merge_agents_md("# My own AGENTS.md\nno markers here\n", agents_md("proj")))

    def test_missing_file_gets_full_template(self):
        new = agents_md("proj")
        self.assertEqual(merge_agents_md(None, new), new)

    def test_gitignore_migrates_legacy_whole_asgard_ignore_so_map_is_trackable(self):
        from asgard.commands.setup import merge_gitignore

        merged = merge_gitignore("cache/\n.asgard\n.asgard/\n")
        self.assertNotIn("\n.asgard\n", "\n" + merged)
        self.assertNotIn("\n.asgard/\n", "\n" + merged)
        self.assertIn("!.asgard/map/", merged)
        self.assertIn("!.asgard/memory/records/", merged)


class TestSettingsMerge(Base):
    def test_hooks_recomputed_user_keys_and_permissions_kept(self):
        tmpl = cc_settings()
        cur = json.loads(tmpl)
        cur["hooks"].pop("SubagentStop")  # 구버전: 훅 하나 없음
        cur["permissions"]["allow"].append("Bash(npm test)")  # 사용자 추가 권한
        cur["model"] = "opus"  # 사용자 최상위 키
        merged = json.loads(merge_cc_settings(json.dumps(cur), tmpl))
        self.assertIn("SubagentStop", merged["hooks"])  # 배선은 최신으로
        self.assertIn("Bash(npm test)", merged["permissions"]["allow"])  # 사용자 권한 보존
        self.assertIn("Bash(git status)", merged["permissions"]["allow"])  # 템플릿 바닥 유지
        self.assertEqual(merged["model"], "opus")

    def test_broken_json_falls_back_to_template(self):
        self.assertEqual(merge_cc_settings("{broken", cc_settings()), cc_settings())


class TestSyncProject(Base):
    def test_fresh_root_scaffolds_everything(self):
        c = sync_project(self.root, cc=True, cursor=False, codex=False)
        self.assertGreater(c["updated"], 10)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".claude", "hooks", "quest-log.py")))
        self.assertEqual(sync_project(self.root, True, False, False)["updated"], 0)  # idempotent

    def test_drift_repaired_user_edits_preserved(self):
        sync_project(self.root, cc=True, cursor=False, codex=False)
        j = os.path.join
        hook = j(self.root, ".claude", "hooks", "git-guard.py")
        open(hook, "w").write("# old version\n")  # 구버전 훅
        agents = j(self.root, "AGENTS.md")
        open(agents, "a").write("\n## Conventions\n우리 팀 규칙 유지\n")
        policy = j(self.root, ".asgard", "asgard-setting-project.json")
        open(policy, "w").write('{"tuned": true}\n')  # 사용자 튜닝 (통합 설정, 26-07-15)
        settings = j(self.root, ".claude", "settings.json")
        s = json.loads(open(settings).read())
        s["permissions"]["allow"].append("Bash(make *)")
        open(settings, "w").write(json.dumps(s))

        c = sync_project(self.root, cc=True, cursor=False, codex=False)
        self.assertGreaterEqual(c["updated"], 2)  # hook + settings(재직렬화)
        self.assertNotIn("old version", open(hook).read())  # asgard 소유 → 최신 복원
        self.assertIn("우리 팀 규칙 유지", open(agents).read())  # 마커 밖 보존
        self.assertEqual(json.loads(open(policy).read()), {"tuned": True})  # keep 정책
        merged = json.loads(open(settings).read())
        self.assertIn("Bash(make *)", merged["permissions"]["allow"])

    def test_sync_migrates_legacy_routed_freyja_adapters_to_direct_loaders(self):
        from asgard.skill_registry import client_skill_bodies
        from asgard.templates.skill_router import routed_skill

        bodies = dict(client_skill_bodies("freyja"))
        clean = os.path.join(self.root, ".claude", "skills", "asgard-freyja-motion", "SKILL.md")
        edited = os.path.join(self.root, ".claude", "skills", "asgard-freyja-hmi", "SKILL.md")
        for path, name in ((clean, "asgard-freyja-motion"), (edited, "asgard-freyja-hmi")):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").write(routed_skill(bodies[name], "freyja"))
        open(edited, "a").write("\nuser edit\n")

        counts = sync_project(self.root, cc=True, cursor=False, codex=False)
        self.assertGreaterEqual(counts["updated"], 1)
        for path, name in ((clean, "asgard-freyja-motion"), (edited, "asgard-freyja-hmi")):
            self.assertIn(f"asgard skills show {name}", open(path).read())
            self.assertNotIn("skills resolve", open(path).read())

    def test_sync_prunes_disabled_generated_adapter(self):
        from asgard.skill_registry import set_skill_enabled

        sync_project(self.root, cc=True, cursor=False, codex=False)
        path = os.path.join(self.root, ".claude", "skills", "ui-ux-pro-max", "SKILL.md")
        self.assertTrue(os.path.exists(path))

        set_skill_enabled(self.root, "ui-ux-pro-max", enabled=False)
        sync_project(self.root, cc=True, cursor=False, codex=False)
        self.assertFalse(os.path.exists(path))

    def test_sync_prunes_user_invoked_adapter_and_codex_policy_together(self):
        from pathlib import Path

        from asgard.skill_registry import install_plugin, set_skill_enabled

        source = os.path.join(self.root, "explicit-source")
        skill = os.path.join(source, "skills", "manual-check")
        os.makedirs(skill)
        Path(os.path.join(source, "plugin.json")).write_text(
            json.dumps({"schema": 1, "name": "explicit", "skills": ["manual-check"]}), encoding="utf-8"
        )
        Path(os.path.join(skill, "SKILL.md")).write_text(
            "---\nname: manual-check\ndescription: Manual check\ntriggers: check\nagent: worker\n"
            "disable-model-invocation: true\n---\n\nMANUAL_ONLY\n",
            encoding="utf-8",
        )
        install_plugin(source)
        sync_project(self.root, cc=False, cursor=False, codex=True)
        directory = os.path.join(self.root, ".agents", "skills", "manual-check")
        self.assertTrue(os.path.exists(os.path.join(directory, "SKILL.md")))
        self.assertTrue(os.path.exists(os.path.join(directory, "agents", "openai.yaml")))

        set_skill_enabled(self.root, "manual-check", enabled=False)
        sync_project(self.root, cc=False, cursor=False, codex=True)
        self.assertFalse(os.path.exists(directory))

    def test_run_sync_prunes_missing_root_and_syncs_rest(self):
        registry.record(j := os.path.join(self.root, "gone"), True, False, False)  # 사라진 루트
        registry.record(self.root, True, False, False)
        cwd = os.getcwd()
        os.chdir(self._home.name)  # cwd 자동등록이 안 걸리는 위치
        try:
            self.assertEqual(run_sync(), 0)
        finally:
            os.chdir(cwd)
        roots = [p["root"] for p in registry.load()]
        self.assertNotIn(j, roots)  # 없어진 루트는 정리
        self.assertIn(self.root, roots)
        self.assertTrue(os.path.exists(os.path.join(self.root, "AGENTS.md")))

    def test_run_sync_autoregisters_legacy_cwd(self):
        sync_project(self.root, cc=True, cursor=False, codex=False)  # 배선은 있으나 레지스트리엔 없음
        self.assertEqual(registry.load(), [])
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertEqual(run_sync(), 0)
        finally:
            os.chdir(cwd)
        entries = registry.load()
        self.assertEqual([p["root"] for p in entries], [self.root])
        self.assertTrue(entries[0]["cc"])


if __name__ == "__main__":
    unittest.main()
