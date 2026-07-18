import base64
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from asgard.agent.session import AgentSession, make_client
from asgard.providers import PROVIDERS, ResolvedProvider, resolve


def _jwt(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


class _Responses:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self._responses)


class TestOpenAINativeOAuth(unittest.TestCase):
    def test_subscription_profile_is_direct_codex_responses_not_cli(self):
        profile = PROVIDERS["openai-native"]
        self.assertEqual(profile.api_mode, "codex_responses")
        self.assertEqual(profile.base_url, "https://chatgpt.com/backend-api/codex")
        self.assertEqual(profile.env_vars, ())
        self.assertTrue(profile.key_optional)
        self.assertNotIn("CLI", profile.signup_hint)

    def test_resolve_never_adopts_api_key_credentials_or_custom_endpoint(self):
        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "ambient-api-key"}, clear=True),
            mock.patch("asgard.settings.load_global", return_value={}),
            mock.patch("asgard.settings.load_project", return_value={}),
            mock.patch(
                "asgard.openai_codex.load_tokens",
                return_value={"access_token": "stored", "refresh_token": "stored-refresh"},
            ),
            mock.patch(
                "asgard.providers.load_credentials",
                return_value={
                    "openai-native": {
                        "api_key": "stale-secret",
                        "base_url": "https://attacker.invalid/v1",
                        "model": "stale-model",
                    }
                },
            ),
        ):
            rp = resolve("/tmp", provider="openai-native")
        self.assertEqual(rp.api_key, "")
        self.assertEqual(rp.base_url, "https://chatgpt.com/backend-api/codex")
        self.assertNotEqual(rp.model, "stale-model")
        self.assertEqual(rp.key_source, "Asgard ChatGPT OAuth")

    def test_missing_asgard_oauth_marks_provider_disconnected_before_repl_or_tui_builds_client(self):
        from asgard import openai_codex

        with mock.patch.object(
            openai_codex,
            "load_tokens",
            side_effect=openai_codex.OAuthError("missing", code="auth_missing", relogin_required=True),
        ):
            rp = resolve("/tmp", provider="openai-native")
        self.assertTrue(rp.missing)
        self.assertTrue(any("auth login openai-native" in item for item in rp.missing))

    def test_token_store_is_owner_only_and_atomic(self):
        from asgard import openai_codex

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".asgard" / "auth.json"
            with mock.patch.object(openai_codex, "AUTH_PATH", path):
                openai_codex.save_tokens({"access_token": "access", "refresh_token": "refresh"})
                loaded = openai_codex.load_tokens()
            self.assertEqual(loaded["access_token"], "access")
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_runtime_credentials_repr_never_exposes_bearer_token(self):
        from asgard.openai_codex import RuntimeCredentials

        rendered = repr(RuntimeCredentials("bearer-secret", "acct"))
        self.assertNotIn("bearer-secret", rendered)
        self.assertIn("acct", rendered)

    def test_login_save_and_logout_serialize_entire_auth_store_mutation(self):
        from contextlib import contextmanager

        from asgard import openai_codex

        state: dict = {"locked": False, "store": {}}

        @contextmanager
        def lock():
            self.assertFalse(state["locked"])
            state["locked"] = True
            try:
                yield
            finally:
                state["locked"] = False

        def read_store():
            self.assertTrue(state["locked"])
            return dict(state["store"])

        def write_store(value):
            self.assertTrue(state["locked"])
            state["store"] = value

        with (
            mock.patch.object(openai_codex, "_refresh_lock", lock),
            mock.patch.object(openai_codex, "_read_store", side_effect=read_store),
            mock.patch.object(openai_codex, "_write_store", side_effect=write_store),
        ):
            openai_codex.save_tokens({"access_token": "access", "refresh_token": "refresh"})
            self.assertTrue(openai_codex.logout())

    def test_refresh_lock_uses_windows_msvcrt_fallback(self):
        from asgard import openai_codex

        calls = []
        win_lock = SimpleNamespace(
            LK_LOCK=1,
            LK_UNLCK=2,
            locking=lambda fd, mode, size: calls.append((fd, mode, size)),
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".asgard" / "auth.json"
            with (
                mock.patch.object(openai_codex, "AUTH_PATH", path),
                mock.patch.object(openai_codex, "fcntl", None),
                mock.patch.object(openai_codex, "msvcrt", win_lock),
            ):
                with openai_codex._refresh_lock():
                    self.assertTrue(path.with_suffix(".lock").exists())
        self.assertEqual([mode for _, mode, _ in calls], [win_lock.LK_LOCK, win_lock.LK_UNLCK])

    def test_runtime_credentials_refresh_expiring_token_and_persist_rotation(self):
        from asgard import openai_codex

        expiring = _jwt({"exp": 1, "https://api.openai.com/auth": {"chatgpt_account_id": "acct-old"}})
        fresh = _jwt({"exp": 4_102_444_800, "https://api.openai.com/auth": {"chatgpt_account_id": "acct-new"}})
        with (
            mock.patch.object(
                openai_codex,
                "load_tokens",
                return_value={"access_token": expiring, "refresh_token": "refresh-old"},
            ),
            mock.patch.object(
                openai_codex,
                "refresh_tokens",
                return_value={"access_token": fresh, "refresh_token": "refresh-new"},
            ) as refresh,
            mock.patch.object(openai_codex, "_save_tokens_unlocked") as save,
            mock.patch.object(openai_codex, "_refresh_lock"),
        ):
            creds = openai_codex.runtime_credentials()
        refresh.assert_called_once_with("refresh-old")
        save.assert_called_once_with({"access_token": fresh, "refresh_token": "refresh-new"})
        self.assertEqual(creds.access_token, fresh)
        self.assertEqual(creds.account_id, "acct-new")

    def test_opaque_or_malformed_access_token_waits_for_401_instead_of_spending_refresh_token(self):
        from asgard import openai_codex

        tokens = {"access_token": "opaque-access-token", "refresh_token": "refresh"}
        with (
            mock.patch.object(openai_codex, "load_tokens", return_value=tokens),
            mock.patch.object(openai_codex, "refresh_tokens") as refresh,
        ):
            credentials = openai_codex.runtime_credentials()
        self.assertEqual(credentials.access_token, "opaque-access-token")
        refresh.assert_not_called()

    def test_refresh_429_does_not_delete_or_relabel_valid_credentials(self):
        from asgard import openai_codex

        response = SimpleNamespace(status_code=429, headers={"retry-after": "30"}, json=lambda: {})
        with mock.patch.object(openai_codex, "_post", return_value=response):
            with self.assertRaisesRegex(openai_codex.OAuthError, "retry") as raised:
                openai_codex.refresh_tokens("refresh-token")
        self.assertFalse(raised.exception.relogin_required)

    def test_device_login_uses_openai_flow_and_returns_own_token_pair(self):
        from asgard import openai_codex

        responses = [
            SimpleNamespace(
                status_code=200,
                headers={},
                json=lambda: {"user_code": "ABCD-EFGH", "device_auth_id": "device-1", "interval": 0},
            ),
            SimpleNamespace(
                status_code=200,
                headers={},
                json=lambda: {"authorization_code": "code-1", "code_verifier": "verifier-1"},
            ),
            SimpleNamespace(
                status_code=200,
                headers={},
                json=lambda: {"access_token": "access-1", "refresh_token": "refresh-1"},
            ),
        ]
        notices = []
        with (
            mock.patch.object(openai_codex, "_post", side_effect=responses) as post,
            mock.patch("asgard.openai_codex.time.sleep") as sleep,
        ):
            tokens = openai_codex.device_login(notices.append, timeout=5)
        self.assertEqual(tokens, {"access_token": "access-1", "refresh_token": "refresh-1"})
        self.assertIn("https://auth.openai.com/codex/device", notices[0])
        self.assertIn("ABCD-EFGH", notices[0])
        self.assertEqual(post.call_args_list[0].args[0], "https://auth.openai.com/api/accounts/deviceauth/usercode")
        self.assertEqual(post.call_args_list[-1].args[0], "https://auth.openai.com/oauth/token")
        sleep.assert_called_once_with(3.0)

    def test_device_login_retries_initial_429_without_treating_credentials_as_invalid(self):
        from asgard import openai_codex

        rate_limited = SimpleNamespace(status_code=429, headers={"retry-after": "2"}, json=lambda: {})
        responses = [
            rate_limited,
            SimpleNamespace(
                status_code=200,
                headers={},
                json=lambda: {"user_code": "CODE", "device_auth_id": "device", "interval": 3},
            ),
            SimpleNamespace(
                status_code=200,
                headers={},
                json=lambda: {"authorization_code": "code", "code_verifier": "verifier"},
            ),
            SimpleNamespace(
                status_code=200,
                headers={},
                json=lambda: {"access_token": "access", "refresh_token": "refresh"},
            ),
        ]
        with (
            mock.patch.object(openai_codex, "_post", side_effect=responses) as post,
            mock.patch("asgard.openai_codex.time.sleep") as sleep,
        ):
            tokens = openai_codex.device_login(lambda _message: None)
        self.assertEqual(tokens["access_token"], "access")
        self.assertEqual(post.call_count, 4)
        self.assertEqual(sleep.call_args_list[0], mock.call(2.0))

    def test_oauth_transport_and_decode_failures_are_sanitized_oauth_errors(self):
        from asgard import openai_codex

        with mock.patch("httpx.post", side_effect=RuntimeError("token=must-not-leak")):
            with self.assertRaises(openai_codex.OAuthError) as raised:
                openai_codex.refresh_tokens("refresh-secret")
        self.assertNotIn("must-not-leak", str(raised.exception))
        self.assertFalse(raised.exception.relogin_required)

        malformed = SimpleNamespace(status_code=200, content=b"not-json", json=mock.Mock(side_effect=ValueError("bad")))
        responses = [
            SimpleNamespace(
                status_code=200,
                headers={},
                content=b"{}",
                json=lambda: {"user_code": "CODE", "device_auth_id": "device", "interval": 3},
            ),
            malformed,
        ]
        with (
            mock.patch.object(openai_codex, "_post", side_effect=responses),
            mock.patch("asgard.openai_codex.time.sleep"),
        ):
            with self.assertRaises(openai_codex.OAuthError) as decoded:
                openai_codex.device_login(lambda _message: None, timeout=4)
        self.assertEqual(decoded.exception.code, "poll_invalid")

    def test_make_client_uses_oauth_token_and_codex_origin_headers(self):
        from asgard import openai_codex

        token = _jwt(
            {
                "exp": 4_102_444_800,
                "https://api.openai.com/auth": {"chatgpt_account_id": "acct-123"},
            }
        )
        rp = ResolvedProvider(
            profile=PROVIDERS["openai-native"],
            model="gpt-5.6-sol",
            base_url="https://chatgpt.com/backend-api/codex",
        )
        creds = openai_codex.RuntimeCredentials(token, "acct-123")
        with (
            mock.patch("asgard.openai_codex.runtime_credentials", return_value=creds),
            mock.patch("openai.OpenAI") as client,
            mock.patch("httpx.Client") as http_client,
        ):
            make_client(rp)
        kwargs = client.call_args.kwargs
        self.assertEqual(kwargs["api_key"], token)
        self.assertEqual(kwargs["base_url"], "https://chatgpt.com/backend-api/codex")
        self.assertEqual(kwargs["max_retries"], 0)
        self.assertEqual(kwargs["default_headers"]["originator"], "codex_cli_rs")
        self.assertEqual(kwargs["default_headers"]["ChatGPT-Account-ID"], "acct-123")
        self.assertNotIn("OPENAI_API_KEY", kwargs)
        http_client.assert_called_once_with(follow_redirects=False)
        self.assertIs(kwargs["http_client"], http_client.return_value)

    def test_model_catalog_is_account_aware_and_filters_hidden_models(self):
        from asgard import openai_codex
        from asgard.providers import ResolvedProvider, provider_models

        response = SimpleNamespace(
            status_code=200,
            content=json.dumps(
                {
                    "models": [
                        {"slug": "gpt-hidden", "visibility": "hide", "priority": 0},
                        {"slug": "gpt-5.6-terra", "visibility": "list", "priority": 2},
                        {
                            "slug": "gpt-5.6-sol",
                            "visibility": "list",
                            "priority": 1,
                            "context_window": 272_000,
                            "effective_context_window_percent": 95,
                        },
                    ]
                }
            ).encode(),
            json=lambda: {},
        )
        credentials = openai_codex.RuntimeCredentials("oauth-token", "acct")
        rp = ResolvedProvider(
            profile=PROVIDERS["openai-native"],
            model="gpt-5.6-sol",
            base_url="https://chatgpt.com/backend-api/codex",
        )
        with (
            mock.patch("asgard.openai_codex.runtime_credentials", return_value=credentials),
            mock.patch("asgard.openai_codex._get", return_value=response) as get,
        ):
            models = provider_models(rp)
        self.assertEqual(models, ["gpt-5.6-sol", "gpt-5.6-terra"])
        self.assertEqual(rp.context_window, 258_400)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer oauth-token")

    def test_subscription_responses_use_canonical_asgard_function_loop(self):
        call = SimpleNamespace(
            type="function_call",
            id="fc_1",
            call_id="call_1",
            name="probe",
            arguments='{"value":"ok"}',
        )
        reasoning = SimpleNamespace(
            type="reasoning",
            id="rs_1",
            encrypted_content="encrypted-reasoning",
            summary=[],
        )
        first = SimpleNamespace(id="resp-1", status="completed", output=[reasoning, call], output_text="", usage=None)
        second = SimpleNamespace(id="resp-2", status="completed", output=[], output_text="done", usage=None)
        responses = _Responses([first, second])
        rp = ResolvedProvider(
            profile=PROVIDERS["openai-native"],
            model="gpt-5.6-sol",
            base_url="https://chatgpt.com/backend-api/codex",
        )
        tool = {
            "name": "probe",
            "description": "return a value",
            "input_schema": {"type": "object", "properties": {"value": {"type": "string"}}},
        }
        session = AgentSession(
            SimpleNamespace(responses=responses),
            rp,
            "/tmp",
            "system",
            extra_tools=[tool],
            tool_handlers={"probe": lambda value: value["value"]},
        )
        result = session.run("hello")

        self.assertEqual(result.text, "done")
        self.assertEqual(result.tool_calls[-1]["name"], "probe")
        first_request, second_request = responses.calls
        self.assertFalse(first_request["store"])
        self.assertEqual(first_request["instructions"], "system")
        self.assertEqual(first_request["input"][0]["content"][0]["type"], "input_text")
        self.assertNotIn("previous_response_id", second_request)
        replayed_reasoning = next(item for item in second_request["input"] if item.get("type") == "reasoning")
        self.assertEqual(replayed_reasoning["encrypted_content"], "encrypted-reasoning")
        self.assertNotIn("id", replayed_reasoning)
        self.assertTrue(any(item.get("type") == "function_call" for item in second_request["input"]))
        self.assertTrue(any(item.get("type") == "function_call_output" for item in second_request["input"]))

    def test_subscription_401_refreshes_oauth_once_and_retries_without_api_key_fallback(self):
        from asgard import openai_codex

        class Unauthorized(RuntimeError):
            status_code = 401

        class UnauthorizedResponses:
            def create(self, **kwargs):
                raise Unauthorized("expired")

        replacement = _Responses(
            [SimpleNamespace(id="resp", status="completed", output=[], output_text="recovered", usage=None)]
        )
        rp = ResolvedProvider(
            profile=PROVIDERS["openai-native"],
            model="gpt-5.6-sol",
            base_url="https://chatgpt.com/backend-api/codex",
        )
        creds = openai_codex.RuntimeCredentials("fresh-oauth-token", "acct")
        session = AgentSession(SimpleNamespace(responses=UnauthorizedResponses()), rp, "/tmp", "system")
        with (
            mock.patch("asgard.openai_codex.runtime_credentials", return_value=creds) as resolve_creds,
            mock.patch(
                "openai.OpenAI",
                return_value=SimpleNamespace(responses=replacement),
            ) as client,
        ):
            result = session.run("hello")
        self.assertEqual(result.text, "recovered")
        resolve_creds.assert_called_once_with(force_refresh=True)
        self.assertEqual(client.call_args.kwargs["api_key"], "fresh-oauth-token")

    def test_failed_or_cancelled_response_is_never_reported_as_successful_end_turn(self):
        for status in ("failed", "cancelled", "queued", "in_progress"):
            with self.subTest(status=status):
                response = SimpleNamespace(
                    id="resp",
                    status=status,
                    error=SimpleNamespace(code="backend_error", message="sensitive backend detail"),
                    output=[],
                    output_text="",
                    usage=None,
                )
                rp = ResolvedProvider(
                    profile=PROVIDERS["openai-native"],
                    model="gpt-5.6-sol",
                    base_url="https://chatgpt.com/backend-api/codex",
                )
                session = AgentSession(SimpleNamespace(responses=_Responses([response])), rp, "/tmp", "system")
                with self.assertRaisesRegex(RuntimeError, status):
                    session.run("hello")

    def test_max_iteration_persists_executed_codex_tool_history_before_returning(self):
        call = SimpleNamespace(type="function_call", id="fc", call_id="call", name="probe", arguments="{}")
        response = SimpleNamespace(id="resp", status="completed", output=[call], output_text="", usage=None)
        rp = ResolvedProvider(
            profile=PROVIDERS["openai-native"],
            model="gpt-5.6-sol",
            base_url="https://chatgpt.com/backend-api/codex",
        )
        session = AgentSession(
            SimpleNamespace(responses=_Responses([response])),
            rp,
            "/tmp",
            "system",
            extra_tools=[{"name": "probe", "input_schema": {"type": "object", "properties": {}}}],
            tool_handlers={"probe": lambda _value: "executed"},
            max_iterations=1,
        )
        result = session.run("do it")
        self.assertEqual(result.stop_reason, "max_iterations")
        self.assertEqual(session.messages[-1], {"role": "user", "content": "do it"})
        history = session._codex_history_items
        self.assertTrue(any(item.get("type") == "function_call" for item in history))
        self.assertTrue(any(item.get("type") == "function_call_output" for item in history))

    def test_invalid_encrypted_reasoning_is_stripped_and_retried_once(self):
        class InvalidEncryptedContent(Exception):
            status_code = 400
            body = {"error": {"code": "invalid_encrypted_content"}}

        responses = _Responses(
            [
                InvalidEncryptedContent("invalid encrypted replay"),
                SimpleNamespace(
                    id="resp-ok",
                    status="completed",
                    output=[],
                    output_text="recovered",
                    usage=None,
                ),
            ]
        )

        original_create = responses.create

        def create(**kwargs):
            value = next(responses._responses)
            responses.calls.append(kwargs)
            if isinstance(value, Exception):
                raise value
            return value

        responses.create = create  # ty: ignore[invalid-assignment] — 인스턴스 몽키패치
        rp = ResolvedProvider(
            profile=PROVIDERS["openai-native"],
            model="gpt-5.6-sol",
            base_url="https://chatgpt.com/backend-api/codex",
        )
        session = AgentSession(SimpleNamespace(responses=responses), rp, "/tmp", "system")
        session._codex_history_items = [
            {"type": "reasoning", "encrypted_content": "poisoned", "summary": []},
            {"role": "assistant", "content": [{"type": "output_text", "text": "prior"}]},
        ]
        result = session.run("continue")
        self.assertEqual(result.text, "recovered")
        self.assertEqual(len(responses.calls), 2)
        self.assertNotIn("include", responses.calls[1])
        self.assertFalse(any(item.get("type") == "reasoning" for item in responses.calls[1]["input"]))
        self.assertIsNotNone(original_create)

    def test_auth_login_cli_runs_asgard_owned_device_flow_without_printing_tokens(self):
        from typer.testing import CliRunner

        from asgard.cli import app

        tokens = {"access_token": "access-secret", "refresh_token": "refresh-secret"}
        with (
            mock.patch("asgard.openai_codex.device_login", return_value=tokens) as login,
            mock.patch("asgard.openai_codex.save_tokens") as save,
        ):
            result = CliRunner().invoke(app, ["auth", "login", "openai-native"])
        self.assertEqual(result.exit_code, 0, result.stdout or str(result.exception))
        login.assert_called_once()
        save.assert_called_once_with(tokens)
        self.assertNotIn("access-secret", result.stdout)
        self.assertNotIn("refresh-secret", result.stdout)

    def test_auth_status_and_logout_cli_use_asgard_store(self):
        from typer.testing import CliRunner

        from asgard.cli import app

        runner = CliRunner()
        with mock.patch("asgard.openai_codex.login_status", return_value=(True, "logged in · account selected")):
            status = runner.invoke(app, ["auth", "status", "openai-native"])
        self.assertEqual(status.exit_code, 0, status.stdout or str(status.exception))
        self.assertIn("logged in", status.stdout.lower())
        self.assertNotIn("secret-token", status.stdout)

        with mock.patch("asgard.openai_codex.logout", return_value=True) as logout:
            removed = runner.invoke(app, ["auth", "logout", "openai-native"])
        self.assertEqual(removed.exit_code, 0, removed.stdout or str(removed.exception))
        logout.assert_called_once_with()

    def test_login_status_rejects_stale_credential_when_backend_and_refresh_both_reject_it(self):
        from asgard import openai_codex

        credentials = openai_codex.RuntimeCredentials("stale-token", "acct")
        unauthorized = SimpleNamespace(status_code=401, content=b"", headers={})
        with (
            mock.patch.object(
                openai_codex,
                "runtime_credentials",
                side_effect=[credentials, openai_codex.OAuthError("login required")],
            ),
            mock.patch.object(openai_codex, "_get", return_value=unauthorized),
        ):
            ok, detail = openai_codex.login_status()
        self.assertFalse(ok)
        self.assertIn("login", detail.lower())

    def test_preflight_checks_asgard_oauth_not_codex_binary(self):
        from asgard.commands.start import preflight

        with (
            mock.patch("asgard.openai_codex.login_status", return_value=(True, "logged in · account selected")),
            mock.patch("asgard.commands.start.resolve") as resolve_provider,
            mock.patch("shutil.which", side_effect=AssertionError("Codex CLI must not be inspected")),
        ):
            resolve_provider.return_value = ResolvedProvider(
                profile=PROVIDERS["openai-native"],
                model="gpt-5.6-sol",
                base_url="https://chatgpt.com/backend-api/codex",
            )
            checks, _ = preflight("/tmp", provider="openai-native")
        oauth = next(check for check in checks if check["name"] == "ChatGPT OAuth")
        self.assertTrue(oauth["ok"])

    def test_provider_onboarding_runs_chatgpt_login_before_model_selection(self):
        import io

        from asgard.agent import onboard

        tokens = {"access_token": "access", "refresh_token": "refresh"}
        with tempfile.TemporaryDirectory() as root:
            with (
                mock.patch("asgard.openai_codex.device_login", return_value=tokens) as login,
                mock.patch("asgard.openai_codex.save_tokens") as save,
                mock.patch("builtins.input", return_value="1"),
                mock.patch("sys.stdout", new_callable=io.StringIO),
            ):
                selected = onboard.onboard(root, preselect="openai-native")
        self.assertIsNotNone(selected)
        login.assert_called_once()
        save.assert_called_once_with(tokens)

    def test_native_model_picker_does_not_reinsert_model_excluded_by_live_account_catalog(self):
        import io

        from asgard.agent import onboard

        rp = ResolvedProvider(
            profile=PROVIDERS["openai-native"],
            model="not-entitled-model",
            base_url="https://chatgpt.com/backend-api/codex",
        )
        with (
            mock.patch.object(onboard, "provider_models", return_value=["gpt-5.6-sol"]),
            mock.patch("builtins.input", return_value="1"),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            selected = onboard._pick_model(rp)
        self.assertEqual(selected, "gpt-5.6-sol")


if __name__ == "__main__":
    unittest.main()
