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


class TestWorkspaceHome(SettingsBase):
    """일감과 기획이 사는 자리 — **하나**여야 하고, 프로젝트 밖이어야 한다."""

    def test_the_workspace_sits_in_the_agent_home_never_in_a_project(self):
        # 스위트는 이 변수를 테스트마다 옮겨 둔다(conftest) — 기본값을 보려면 걷어내야 한다
        override = os.environ.pop(settings.WORKSPACE_HOME_ENV, None)
        try:
            home = settings.workspace_home()
        finally:
            if override is not None:
                os.environ[settings.WORKSPACE_HOME_ENV] = override
        self.assertEqual(home, os.path.join(settings.global_dir(), settings.WORKSPACE_DIR))
        self.assertFalse(home.startswith(os.path.abspath(self.root) + os.sep))

    def test_one_env_moves_both_tickets_and_plans(self):
        """자리를 옮기면 **둘이 같이** 옮겨져야 워크스페이스가 하나라는 말이 참이 된다."""
        from asgard.plan import store as plan_store
        from asgard.studio import db as studio_db

        moved = os.path.join(self.tmp, "elsewhere")
        os.environ[settings.WORKSPACE_HOME_ENV] = moved
        try:
            self.assertEqual(settings.workspace_home(), moved)
            self.assertEqual(studio_db.workspace_path(), os.path.join(moved, "workspace.db"))
            self.assertEqual(plan_store.store_path(), os.path.join(moved, "plans.json"))
        finally:
            os.environ.pop(settings.WORKSPACE_HOME_ENV, None)


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

    def test_concurrent_saves_neither_corrupt_the_file_nor_lose_a_section(self):
        """스튜디오는 요청마다 스레드다 — 설정을 연달아 바꾸면 저장이 겹친다.
        겹친 자리에서 파일이 깨지거나(두 벌의 JSON) 앞서 저장한 섹션이 사라지면 안 된다."""
        import threading

        sections = {
            "provider": {"name": "ollama"},
            "lagom": {"mode": "lite"},
            "ui": {"lang": "ko"},
            "bridge": {"cursor": True},
        }
        errors: list[BaseException] = []

        def write(name, values):
            try:
                for _ in range(12):
                    settings.save_project(self.root, name, values)
            except BaseException as exc:  # noqa: BLE001 — 스레드의 실패는 여기서만 보인다
                errors.append(exc)

        threads = [threading.Thread(target=write, args=item) for item in sections.items()]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        with open(settings.project_path(self.root), encoding="utf-8") as handle:
            data = json.load(handle)  # 깨졌으면 여기서 JSONDecodeError
        for name, values in sections.items():
            self.assertEqual(data.get(name), values, name)

    def test_agent_model_override_merges_global_then_project_per_field(self):
        from asgard.templates.agent_models import agent_model

        settings.save_global("agent_models", {"codex": {"worker": {"model": "global-model", "effort": "low"}}})
        settings.save_project(self.root, "agent_models", {"codex": {"worker": {"model": "project-model"}}})
        self.assertEqual(agent_model(self.root, "codex", "worker"), {"model": "project-model", "effort": "low"})


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
