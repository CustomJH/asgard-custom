"""개인 메모리 관리 provider 테스트.

검증 축: 해석(기본=메인 provider · 설정 override · env override · 모델 콜론 파싱) /
계약(미충족은 ManagerUnavailable, 조용한 실패 금지) / 진단(관리·주입 두 판정을 한 화면) /
배선(노른이 이 지점을 지난다). 전부 temp HOME 격리 — 실제 LLM 호출 없음.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from asgard import memory
from asgard.memory import manager


class ManagerBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-mgr-")
        self._env = {key: os.environ.get(key) for key in ("HOME", memory.MEMORY_ENV, manager.MANAGER_ENV)}
        os.environ["HOME"] = self.tmp
        self.d = os.path.join(self.tmp, "memory")
        os.environ[memory.MEMORY_ENV] = self.d
        os.environ.pop(manager.MANAGER_ENV, None)
        memory.ensure_home(self.d)
        self.root = os.path.join(self.tmp, "project")
        os.makedirs(self.root, exist_ok=True)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)


class ResolutionTest(ManagerBase):
    def test_default_is_the_main_provider(self):
        self.assertEqual(manager.manager_config(), {})
        resolved, source = manager.resolve_manager(self.root)
        self.assertEqual(source, "main")
        from asgard.providers import resolve

        self.assertEqual(resolved.profile.name, resolve(self.root).profile.name)

    def test_configured_manager_overrides_the_main_provider(self):
        manager.save_manager("ollama:gemma4:12b-mlx")
        configured = manager.manager_config()
        # 모델 id 안의 콜론은 살아 있어야 한다 — 첫 구분자만 자른다
        self.assertEqual(configured["provider"], "ollama")
        self.assertEqual(configured["model"], "gemma4:12b-mlx")
        resolved, source = manager.resolve_manager(self.root)
        self.assertEqual((resolved.profile.name, resolved.model, source), ("ollama", "gemma4:12b-mlx", "config"))

    def test_env_beats_configuration(self):
        manager.save_manager("ollama")
        os.environ[manager.MANAGER_ENV] = "anthropic"
        self.assertEqual(manager.manager_config()["source"], "env")
        self.assertEqual(manager.resolve_manager(self.root)[0].profile.name, "anthropic")

    def test_unknown_provider_is_rejected_at_save_time(self):
        with self.assertRaises(ValueError):
            manager.save_manager("not-a-provider")
        self.assertEqual(manager.manager_config(), {})

    def test_clearing_returns_to_the_main_provider(self):
        manager.save_manager("ollama")
        self.assertEqual(manager.save_manager(""), {})
        self.assertEqual(manager.resolve_manager(self.root)[1], "main")


class ContractTest(ManagerBase):
    def test_unusable_manager_raises_instead_of_answering(self):
        os.environ[manager.MANAGER_ENV] = "anthropic"
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            os.environ.pop(key, None)
        self.assertFalse(manager.available(self.root))
        with self.assertRaises(manager.ManagerUnavailable):
            manager.complete(self.root, "sys", "user")

    def test_main_provider_path_goes_through_complete_once(self):
        with (
            mock.patch.object(manager, "resolve_manager", return_value=(mock.Mock(missing=[]), "main")),
            mock.patch("asgard.agent.oneshot.complete_once", return_value="답") as once,
        ):
            self.assertEqual(manager.complete(self.root, "sys", "user"), "답")
        once.assert_called_once()

    def test_configured_manager_path_carries_its_own_provider(self):
        resolved = mock.Mock(missing=[])
        with (
            mock.patch.object(manager, "resolve_manager", return_value=(resolved, "config")),
            mock.patch("asgard.agent.oneshot.complete_with", return_value="답") as with_provider,
        ):
            self.assertEqual(manager.complete(self.root, "sys", "user"), "답")
        self.assertIs(with_provider.call_args[0][0], resolved)


class DescribeTest(ManagerBase):
    def test_describe_reports_curation_and_injection_together(self):
        row = manager.describe(self.root)
        self.assertEqual(row["source"], "main")
        self.assertTrue(row["inject_enabled"])
        self.assertIn("inject_allowed", row)

    def test_kill_switch_shows_up_in_the_diagnosis(self):
        with mock.patch.dict(os.environ, {"ASGARD_MEMORY_INJECT": "off"}):
            self.assertFalse(manager.describe(self.root)["inject_enabled"])

    def test_configured_manager_reports_the_main_provider_beside_it(self):
        manager.save_manager("ollama")
        row = manager.describe(self.root)
        self.assertEqual(row["provider"], "ollama")
        self.assertIn("main_provider", row)


class WiringTest(ManagerBase):
    def test_norn_routes_its_llm_call_through_the_manager(self):
        from asgard.memory import norn

        with mock.patch.object(manager, "complete", return_value="{}") as call:
            norn._complete(self.root, "sys", "user")
        call.assert_called_once()
        self.assertEqual(call.call_args[0][0], self.root)

    def test_pattern_routes_its_llm_call_through_the_manager(self):
        from asgard.memory import pattern

        with mock.patch.object(manager, "complete", return_value="{}") as call:
            pattern._complete(self.root, "sys", "user")
        call.assert_called_once()


class SemanticDoctorTest(ManagerBase):
    """켜져 있다는 것과 실제로 도는 것을 doctor 가 구분하는가 (기본값이 on 이라 더 중요하다)."""

    def _check(self) -> dict:
        from asgard.commands.doctor import _memory_semantic_check

        row = _memory_semantic_check()
        assert row is not None
        return row

    def test_default_is_on(self):
        from asgard import memory_semantic

        os.environ.pop("ASGARD_MEMORY_SEMANTIC", None)
        self.assertEqual(memory_semantic.mode(), "local")

    def test_running_embedder_is_reported_with_its_model(self):
        from asgard import memory_semantic

        os.environ.pop("ASGARD_MEMORY_SEMANTIC", None)
        memory_semantic.set_embedder(lambda text: [0.1, 0.2, 0.3])
        try:
            row = self._check()
        finally:
            memory_semantic.set_embedder(None)
        self.assertTrue(row["ok"])
        self.assertIn("on", row["detail"])

    def test_explicit_off_is_not_a_failure(self):
        os.environ["ASGARD_MEMORY_SEMANTIC"] = "off"
        try:
            row = self._check()
        finally:
            os.environ.pop("ASGARD_MEMORY_SEMANTIC", None)
        self.assertTrue(row["ok"])  # 의도적으로 끈 것은 결함이 아니다
        self.assertIn("off", row["detail"])

    def test_on_but_unloadable_embedder_is_not_silent(self):
        from asgard import memory_semantic

        os.environ.pop("ASGARD_MEMORY_SEMANTIC", None)
        memory_semantic.set_embedder(None)
        memory_semantic.reset()
        try:
            with mock.patch.object(memory_semantic, "_load_local", return_value=None):
                row = self._check()
        finally:
            memory_semantic.reset()
        self.assertFalse(row["ok"])  # 켠 줄 알았는데 안 도는 상태 — 가장 조용한 실패
        self.assertIn("폴백", row["detail"])
        self.assertIn("warmup", row["fix"])

    def test_hub_noise_is_kept_off_the_user_surface(self):
        from asgard import memory_semantic

        with mock.patch.object(memory_semantic, "model_cached", return_value=True):
            with memory_semantic._quiet_hub():
                self.assertEqual(os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS"), "1")
                self.assertEqual(os.environ.get("HF_HUB_OFFLINE"), "1")
        self.assertIsNone(os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS"))
        self.assertIsNone(os.environ.get("HF_HUB_OFFLINE"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
