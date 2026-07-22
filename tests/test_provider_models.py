import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from asgard.agent import onboard, repl
from asgard.providers import PROVIDERS, ResolvedProvider


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return json.dumps(self.payload).encode()


class TestProviderModelDiscovery(unittest.TestCase):
    def _nvidia(self, model=None):
        profile = PROVIDERS["nvidia"]
        return ResolvedProvider(
            profile=profile,
            model=model or profile.default_model,
            base_url=profile.base_url,
            api_key="test-key",
        )

    def test_nvidia_live_catalog_exposes_multiple_models_and_deduplicates(self):
        from asgard.providers import provider_models

        payload = {
            "data": [
                {"id": "meta/llama-3.3-70b-instruct"},
                {"id": PROVIDERS["nvidia"].default_model},
                {"id": "meta/llama-3.3-70b-instruct"},
                {"missing": "id"},
            ]
        }
        with mock.patch("asgard.providers._open_model_catalog", return_value=_Response(payload)) as opened:
            models = provider_models(self._nvidia())

        self.assertEqual(
            models,
            [PROVIDERS["nvidia"].default_model, "meta/llama-3.3-70b-instruct"],
        )
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://integrate.api.nvidia.com/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

    def test_nvidia_catalog_failure_falls_back_to_curated_agent_models(self):
        from asgard.providers import provider_models

        reasons = []
        with mock.patch("asgard.providers._open_model_catalog", side_effect=OSError("offline")):
            models = provider_models(self._nvidia(), on_fallback=reasons.append)

        self.assertGreaterEqual(len(models), 2)
        self.assertEqual(models[0], PROVIDERS["nvidia"].default_model)
        self.assertEqual(reasons, ["live catalog request failed"])

    def test_model_catalog_redirect_handler_refuses_redirect(self):
        from asgard.providers import _NoModelCatalogRedirect

        handler = _NoModelCatalogRedirect()
        self.assertIsNone(
            handler.redirect_request(
                cast(Any, None), cast(Any, None), 302, "Found", cast(Any, {}), "https://other.invalid/models"
            )
        )

    def test_ollama_uses_openai_compatible_live_catalog(self):
        from asgard.providers import provider_models

        profile = PROVIDERS["ollama"]
        rp = ResolvedProvider(
            profile=profile,
            model=profile.default_model,
            base_url=profile.base_url,
            api_key="ollama",
        )
        payload = {
            "data": [
                {"id": "gemma4:12b-mlx"},
                {"id": "nomic-embed-text:latest"},
                {"id": "qwen3:8b"},
            ]
        }
        with mock.patch("asgard.providers._open_model_catalog", return_value=_Response(payload)) as opened:
            self.assertEqual(provider_models(rp), ["gemma4:12b-mlx", "qwen3:8b"])
        self.assertEqual(opened.call_args.args[0].full_url, "http://localhost:11434/v1/models")

    def test_curated_provider_catalog_is_not_reported_as_network_fallback(self):
        from asgard.providers import provider_models

        profile = PROVIDERS["anthropic"]
        reasons = []
        models = provider_models(
            ResolvedProvider(profile=profile, model=profile.default_model), on_fallback=reasons.append
        )
        self.assertGreaterEqual(len(models), 3)
        self.assertEqual(reasons, [])

    def test_catalog_rejects_control_character_model_ids_and_non_http_endpoint(self):
        from asgard.providers import provider_models

        payload = {"data": [{"id": "safe/model"}, {"id": "bad\nmodel"}, {"id": "bad\x1b[31m"}]}
        with mock.patch("asgard.providers._open_model_catalog", return_value=_Response(payload)):
            self.assertEqual(provider_models(self._nvidia()), ["safe/model"])

        rp = self._nvidia()
        rp.base_url = "file:///tmp/not-a-provider"
        with mock.patch("asgard.providers._open_model_catalog") as opened:
            models = provider_models(rp)
        opened.assert_not_called()
        self.assertEqual(models[0], PROVIDERS["nvidia"].default_model)

    def test_nvidia_catalog_never_sends_global_key_to_project_override_origin(self):
        from asgard.providers import provider_models

        rp = self._nvidia()
        rp.base_url = "https://credential-sink.invalid/v1"
        with mock.patch("asgard.providers._open_model_catalog") as opened:
            models = provider_models(rp)
        opened.assert_not_called()
        self.assertEqual(models[0], PROVIDERS["nvidia"].default_model)

    def test_nvidia_extra_body_is_not_forced_on_another_model(self):
        profile = PROVIDERS["nvidia"]
        self.assertTrue(profile.request_extra_body(profile.default_model))
        self.assertEqual(profile.request_extra_body("meta/llama-3.3-70b-instruct"), {})

    def test_openrouter_is_first_class_and_catalog_endpoint_is_pinned(self):
        from asgard.providers import provider_models

        profile = PROVIDERS["openrouter"]
        rp = ResolvedProvider(profile=profile, model="", base_url=profile.base_url, api_key="or-key")
        with mock.patch(
            "asgard.providers._open_model_catalog",
            return_value=_Response({"data": [{"id": "anthropic/claude-sonnet"}]}),
        ) as opened:
            self.assertEqual(provider_models(rp), ["anthropic/claude-sonnet"])
        self.assertEqual(opened.call_args.args[0].full_url, "https://openrouter.ai/api/v1/models")

        rp.base_url = "https://credential-sink.invalid/v1"
        with mock.patch("asgard.providers._open_model_catalog") as blocked:
            self.assertEqual(provider_models(rp), [])
        blocked.assert_not_called()


class TestNativeModelSelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.cred = os.path.join(self.root, "credentials.json")
        self.cred_patch = mock.patch("asgard.providers.CRED_PATH", self.cred)
        self.cred_patch.start()
        self.global_patch = mock.patch("asgard.settings.load_global", return_value={})
        self.global_patch.start()

    def tearDown(self):
        self.global_patch.stop()
        self.cred_patch.stop()
        self.tmp.cleanup()

    def test_nvidia_onboarding_prompts_for_model_after_key_and_persists_choice(self):
        default = PROVIDERS["nvidia"].default_model
        with (
            mock.patch("getpass.getpass", return_value="test-key"),
            mock.patch("asgard.agent.onboard.provider_models", return_value=[default, "meta/llama-3.3-70b-instruct"]),
            mock.patch("builtins.input", side_effect=["", "2"]),  # rpm 엔터(기본 40) → 모델 2번
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            resolved = onboard.onboard(self.root, preselect="nvidia")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.model, "meta/llama-3.3-70b-instruct")
        from asgard.settings import load_project

        self.assertEqual(
            load_project(self.root)["provider"],
            {"name": "nvidia", "model": "meta/llama-3.3-70b-instruct"},
        )
        from asgard.providers import resolve

        self.assertEqual(resolve(self.root).model, "meta/llama-3.3-70b-instruct")
        stored = json.load(open(self.cred))
        self.assertEqual(stored["nvidia"]["api_key"], "test-key")
        self.assertNotIn("model", stored["nvidia"])

    def test_nvidia_onboarding_rpm_input_persists_to_project_config(self):
        default = PROVIDERS["nvidia"].default_model
        with (
            mock.patch("getpass.getpass", return_value="test-key"),
            mock.patch("asgard.agent.onboard.provider_models", return_value=[default]),
            mock.patch("builtins.input", side_effect=["20", "1"]),  # rpm 20 → 모델 1번
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            resolved = onboard.onboard(self.root, preselect="nvidia")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        from asgard.agent.rate_limit import effective_rpm
        from asgard.settings import load_project

        self.assertEqual(load_project(self.root)["provider"]["rpm"], 20)
        self.assertEqual(resolved.rpm, 20)
        self.assertEqual(effective_rpm(resolved), 20)

    def test_nvidia_onboarding_rpm_minus_one_disables_throttle(self):
        default = PROVIDERS["nvidia"].default_model
        with (
            mock.patch("getpass.getpass", return_value="test-key"),
            mock.patch("asgard.agent.onboard.provider_models", return_value=[default]),
            mock.patch("builtins.input", side_effect=["-1", "1"]),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            resolved = onboard.onboard(self.root, preselect="nvidia")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        from asgard.agent.rate_limit import effective_rpm, limiter_for

        self.assertEqual(effective_rpm(resolved), 0)
        self.assertIsNone(limiter_for(resolved))

    def test_credential_replace_failure_preserves_previous_file(self):
        from asgard.providers import save_credential

        previous = {"anthropic": {"api_key": "keep-me"}}
        with open(self.cred, "w", encoding="utf-8") as f:
            json.dump(previous, f)
        with mock.patch("asgard.providers.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_credential("nvidia", "new-key")
        with open(self.cred, encoding="utf-8") as f:
            self.assertEqual(json.load(f), previous)
        self.assertEqual(os.listdir(self.root), ["credentials.json"])

    def test_anthropic_onboarding_uses_curated_model_picker(self):
        with (
            mock.patch("getpass.getpass", return_value="test-key"),
            mock.patch("builtins.input", return_value="2"),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            resolved = onboard.onboard(self.root, preselect="anthropic")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.model, "claude-sonnet-4-6")

    def test_openai_compatible_onboarding_discovers_models_before_selection(self):
        with (
            mock.patch("getpass.getpass", return_value="test-key"),
            mock.patch("asgard.agent.onboard.provider_models", return_value=["vendor/model-a", "vendor/model-b"]),
            mock.patch("builtins.input", side_effect=["https://models.example/v1", "2"]),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            resolved = onboard.onboard(self.root, preselect="openai_compat")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.model, "vendor/model-b")
        self.assertEqual(resolved.base_url, "https://models.example/v1")

    def test_openrouter_resolve_uses_its_own_env_and_fixed_endpoint(self):
        from asgard.providers import resolve

        with (
            mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-key"}, clear=True),
            mock.patch(
                "asgard.settings.load_global",
                return_value={
                    "provider": {
                        "name": "openrouter",
                        "base_url": "https://credential-sink.invalid/v1",
                    }
                },
            ),
            mock.patch("asgard.settings.load_project", return_value={}),
            mock.patch("asgard.providers.load_credentials", return_value={}),
        ):
            rp = resolve(self.root, provider="openrouter", model="vendor/model")
        self.assertEqual(rp.api_key, "or-key")
        self.assertEqual(rp.base_url, "https://openrouter.ai/api/v1")

    def test_ollama_onboarding_lists_installed_models(self):
        with (
            mock.patch("asgard.agent.onboard.provider_models", return_value=["gemma4:12b-mlx", "qwen3:8b"]),
            mock.patch("builtins.input", return_value="2"),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            resolved = onboard.onboard(self.root, preselect="ollama")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.model, "qwen3:8b")

    def test_non_openai_provider_catalogs_offer_multiple_models(self):
        from asgard.providers import provider_models

        for name in ("anthropic", "claude-native"):
            profile = PROVIDERS[name]
            rp = ResolvedProvider(profile=profile, model=profile.default_model)
            with self.subTest(provider=name):
                self.assertGreaterEqual(len(provider_models(rp)), 3)

    def test_switching_to_nvidia_drops_previous_provider_endpoint_and_key_env(self):
        from asgard.providers import save_config_section
        from asgard.settings import load_project

        save_config_section(
            self.root,
            "provider",
            {
                "name": "openai_compat",
                "model": "old-model",
                "base_url": "https://old-provider.invalid/v1",
                "api_key_env": "OLD_PROVIDER_KEY",
            },
        )
        default = PROVIDERS["nvidia"].default_model
        with (
            mock.patch("getpass.getpass", return_value="test-key"),
            mock.patch("asgard.agent.onboard.provider_models", return_value=[default, "meta/llama-3.3-70b-instruct"]),
            mock.patch("builtins.input", side_effect=["", "2"]),  # rpm 엔터(기본 40) → 모델 2번
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            resolved = onboard.onboard(self.root, preselect="nvidia")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.base_url, PROVIDERS["nvidia"].base_url)
        self.assertEqual(
            load_project(self.root)["provider"],
            {"name": "nvidia", "model": "meta/llama-3.3-70b-instruct"},
        )

    def test_nvidia_resolve_ignores_project_base_url_override(self):
        from asgard.providers import resolve, save_config_section, save_credential

        save_credential("nvidia", "test-key")
        save_config_section(
            self.root,
            "provider",
            {
                "name": "nvidia",
                "model": PROVIDERS["nvidia"].default_model,
                "base_url": "https://credential-sink.invalid/v1",
            },
        )
        self.assertEqual(resolve(self.root).base_url, PROVIDERS["nvidia"].base_url)

    def test_nvidia_trinity_role_ignores_project_base_url_override(self):
        from asgard.providers import resolve, resolve_trinity, save_config_section, save_credential

        save_credential("nvidia", "test-key")
        save_config_section(
            self.root,
            "trinity.worker",
            {
                "provider": "nvidia",
                "model": "meta/llama-3.3-70b-instruct",
                "base_url": "https://credential-sink.invalid/v1",
            },
        )
        worker = resolve_trinity(self.root, resolve(self.root))["worker"]
        self.assertEqual(worker.base_url, PROVIDERS["nvidia"].base_url)

    def test_cancelling_nvidia_picker_keeps_credential_but_does_not_select_provider(self):
        from asgard.settings import load_project

        default = PROVIDERS["nvidia"].default_model
        with (
            mock.patch("getpass.getpass", return_value="test-key"),
            mock.patch("asgard.agent.onboard.provider_models", return_value=[default, "meta/llama-3.3-70b-instruct"]),
            mock.patch("builtins.input", return_value="q"),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            resolved = onboard.onboard(self.root, preselect="nvidia")

        self.assertIsNone(resolved)
        self.assertNotIn("provider", load_project(self.root))
        self.assertTrue(json.load(open(self.cred))["nvidia"]["api_key"])

    def test_manual_model_id_rejects_control_characters(self):
        default = PROVIDERS["nvidia"].default_model
        with (
            mock.patch("asgard.agent.onboard.provider_models", return_value=[default]),
            mock.patch("builtins.input", side_effect=["m", "bad\x1b[31m", "q"]),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertIsNone(onboard._pick_model(self._nvidia_resolved()))

    def test_invalid_model_number_reprompts(self):
        default = PROVIDERS["nvidia"].default_model
        alternate = "meta/llama-3.3-70b-instruct"
        with (
            mock.patch("asgard.agent.onboard.provider_models", return_value=[default, alternate]),
            mock.patch("builtins.input", side_effect=["not-a-number", "2"]),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertEqual(onboard._pick_model(self._nvidia_resolved()), alternate)

    def test_model_command_reconfigures_existing_nvidia_connection(self):
        from asgard.providers import save_config_section

        default = PROVIDERS["nvidia"].default_model
        save_config_section(self.root, "provider", {"name": "nvidia", "model": default})
        rp = ResolvedProvider(
            profile=PROVIDERS["nvidia"],
            model=default,
            base_url=PROVIDERS["nvidia"].base_url,
            api_key="test-key",
        )
        with (
            mock.patch("asgard.agent.onboard.provider_models", return_value=[default, "meta/llama-3.3-70b-instruct"]),
            mock.patch("asgard.agent.onboard.can_prompt", return_value=True),
            mock.patch("builtins.input", return_value="2"),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            with self.assertRaises(repl._Reconfigure) as changed:
                repl.slash("/model", self.root, rp)

        self.assertEqual(changed.exception.rp.model, "meta/llama-3.3-70b-instruct")

    def test_selected_nvidia_model_reaches_openai_client_without_default_only_extras(self):
        from asgard.agent.session import AgentSession

        calls = []

        class Completions:
            def create(self, **kwargs):
                calls.append(kwargs)
                delta = SimpleNamespace(content="ok", reasoning_content=None, reasoning=None, tool_calls=[])
                return [SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason="stop", delta=delta)])]

        client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        rp = ResolvedProvider(
            profile=PROVIDERS["nvidia"],
            model="meta/llama-3.3-70b-instruct",
            base_url=PROVIDERS["nvidia"].base_url,
            api_key="test-key",
        )
        session = AgentSession(client, rp, self.root, "system", max_iterations=1)
        result = session.run("hello")

        self.assertEqual(result.text, "ok")
        self.assertEqual(calls[0]["model"], "meta/llama-3.3-70b-instruct")
        self.assertIsNone(calls[0]["extra_body"])

    def test_default_nvidia_model_extras_reach_openai_client(self):
        from asgard.agent.session import AgentSession

        calls = []

        class Completions:
            def create(self, **kwargs):
                calls.append(kwargs)
                delta = SimpleNamespace(content="ok", reasoning_content=None, reasoning=None, tool_calls=[])
                return [SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason="stop", delta=delta)])]

        rp = self._nvidia_resolved()
        client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        AgentSession(client, rp, self.root, "system", max_iterations=1).run("hello")
        self.assertEqual(calls[0]["extra_body"], rp.profile.extra_body)

    def _nvidia_resolved(self, model=None):
        profile = PROVIDERS["nvidia"]
        return ResolvedProvider(
            profile=profile,
            model=model or profile.default_model,
            base_url=profile.base_url,
            api_key="test-key",
        )


if __name__ == "__main__":
    unittest.main()
