"""settings (26-07-15 설정 통합) — asgard-setting-{global,project}.json + state/ 격리.

검증 축: 신규 로드/저장(섹션 교체·타 섹션 보존) / 병합 우선순위(프로젝트>글로벌) /
레거시 폴백(config.toml·trinity-policy.json·memory-server.json) / 마이그레이션
(주 경로 + 신파일 선존재 fill 경로 — 유실 방지 회귀) / state 경로 레거시 폴백.
"""

import json
import os
import shutil
import tempfile
import unittest

from asgard import settings


class SettingsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-settings-")
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp  # 글로벌 격리
        self.root = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.root, ".asgard"))

    def tearDown(self):
        if self._home is not None:
            os.environ["HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_legacy_toml(self, body: str, where: str | None = None):
        d = where or os.path.join(self.root, ".asgard")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, settings.LEGACY_TOML), "w").write(body)


class TestLoadSave(SettingsBase):
    def test_save_and_load_roundtrip_project_and_global(self):
        settings.save_project(self.root, "provider", {"name": "ollama", "model": "m1"})
        settings.save_global("ui", {"lang": "ko"})
        self.assertEqual(settings.load_project(self.root)["provider"]["model"], "m1")
        self.assertEqual(settings.load_global()["ui"]["lang"], "ko")

    def test_save_replaces_section_and_preserves_others(self):
        settings.save_project(self.root, "provider", {"name": "ollama", "model": "m1"})
        settings.save_project(self.root, "lagom", {"mode": "lite"})
        settings.save_project(self.root, "provider", {"name": "nvidia"})  # 교체 — m1 잔존 금지
        d = settings.load_project(self.root)
        self.assertEqual(d["provider"], {"name": "nvidia"})
        self.assertEqual(d["lagom"], {"mode": "lite"})  # 타 섹션 보존

    def test_section_merges_project_over_global(self):
        settings.save_global("lagom", {"mode": "off", "subagent_matcher": "x"})
        settings.save_project(self.root, "lagom", {"mode": "full"})
        merged = settings.section("lagom", self.root)
        self.assertEqual(merged["mode"], "full")  # 프로젝트 승
        self.assertEqual(merged["subagent_matcher"], "x")  # 글로벌 키 유지


class TestLegacyFallback(SettingsBase):
    def test_project_legacy_composite(self):
        self.write_legacy_toml('[provider]\nname = "ollama"\n\n[lagom]\nmode = "lite"\n')
        open(os.path.join(self.root, ".asgard", settings.LEGACY_POLICY), "w").write('{"gate_first_max_lines": 30}')
        open(os.path.join(self.root, ".asgard", settings.LEGACY_MEMORY), "w").write(
            '{"server": "http://s:1", "bank": "b"}'
        )
        d = settings.load_project(self.root)
        self.assertEqual(d["provider"]["name"], "ollama")
        self.assertEqual(d["trinity_policy"]["gate_first_max_lines"], 30)
        self.assertEqual(d["memory"], {"server": "http://s:1", "bank": "b"})

    def test_new_file_shadows_legacy(self):
        self.write_legacy_toml('[provider]\nname = "ollama"\n')
        settings.save_project(self.root, "ui", {"lang": "ko"})  # 최초 저장 = 레거시 승계 + 신파일 생성
        d = settings.load_project(self.root)
        self.assertEqual(d["provider"]["name"], "ollama")  # 승계됨
        # 이후 레거시 TOML 수정은 무시 (신파일이 스코프 정본)
        self.write_legacy_toml('[provider]\nname = "nvidia"\n')
        self.assertEqual(settings.load_project(self.root)["provider"]["name"], "ollama")

    def test_global_legacy_toml(self):
        self.write_legacy_toml('[ui]\nlang = "ko"\n', where=os.path.join(self.tmp, ".asgard"))
        self.assertEqual(settings.load_global()["ui"]["lang"], "ko")


class TestMigration(SettingsBase):
    def seed_legacy(self):
        self.write_legacy_toml('[provider]\nname = "ollama"\nmodel = "m1"\n\n[lagom]\nmode = "lite"\n')
        asg = os.path.join(self.root, ".asgard")
        open(os.path.join(asg, settings.LEGACY_POLICY), "w").write('{"gate_first_max_lines": 30}')
        open(os.path.join(asg, settings.LEGACY_MEMORY), "w").write('{"server": "http://s:1", "bank": "b"}')
        open(os.path.join(asg, "lagom-mode.json"), "w").write('{"mode": "lite"}')
        open(os.path.join(asg, "route-priors.json"), "w").write('{"classes": {}}')

    def test_main_path_full_adoption(self):
        self.seed_legacy()
        done = settings.migrate_project(self.root)
        self.assertTrue(any("settings →" in m for m in done))
        d = settings.load_project(self.root)
        self.assertEqual(d["provider"]["model"], "m1")
        self.assertEqual(d["memory"]["bank"], "b")
        self.assertEqual(d["trinity_policy"]["gate_first_max_lines"], 30)
        asg = os.path.join(self.root, ".asgard")
        for legacy in (settings.LEGACY_TOML, settings.LEGACY_POLICY, settings.LEGACY_MEMORY):
            self.assertFalse(os.path.exists(os.path.join(asg, legacy)))  # 이원화 방지
        self.assertTrue(os.path.exists(os.path.join(asg, "state", "lagom-mode.json")))
        self.assertTrue(os.path.exists(os.path.join(asg, "state", "route-priors.json")))
        self.assertEqual(settings.migrate_project(self.root), [])  # 멱등

    def test_fill_path_new_file_preexists(self):
        """실측 회귀 (26-07-15): init --force 가 신파일을 먼저 만든 뒤 sync — 레거시 섹션이
        유실되던 결함. 누락 섹션만 채우고(신파일 우선) 레거시를 제거해야 한다."""
        self.seed_legacy()
        settings._atomic_json(settings.project_path(self.root), {"trinity_policy": {"schema": 1}})
        done = settings.migrate_project(self.root)
        self.assertTrue(any("filled" in m for m in done))
        d = settings.load_project(self.root)
        self.assertEqual(d["provider"]["name"], "ollama")  # 채워짐
        self.assertEqual(d["memory"]["bank"], "b")
        self.assertEqual(d["trinity_policy"], {"schema": 1})  # 신파일 우선 (기존 섹션 불변)

    def test_migrate_global(self):
        self.write_legacy_toml('[provider]\nname = "nvidia"\n', where=os.path.join(self.tmp, ".asgard"))
        done = settings.migrate_global()
        self.assertTrue(done)
        self.assertEqual(json.load(open(settings.global_path()))["provider"]["name"], "nvidia")
        self.assertEqual(settings.migrate_global(), [])  # 멱등


class TestStatePath(SettingsBase):
    def test_state_path_prefers_new_falls_back_legacy(self):
        p = settings.state_path(self.root, "route-priors.json", legacy="route-priors.json")
        self.assertIn(os.path.join(".asgard", "state"), p)  # 아무것도 없으면 신규 경로
        legacy = os.path.join(self.root, ".asgard", "route-priors.json")
        open(legacy, "w").write("{}")
        self.assertEqual(settings.state_path(self.root, "route-priors.json", legacy="route-priors.json"), legacy)
        settings.ensure_state_dir(self.root)
        new = os.path.join(self.root, ".asgard", "state", "route-priors.json")
        open(new, "w").write("{}")
        self.assertEqual(settings.state_path(self.root, "route-priors.json", legacy="route-priors.json"), new)


if __name__ == "__main__":
    unittest.main()
