import os
import unittest
from types import SimpleNamespace
from unittest import mock

from asgard.agent.session import AgentSession, make_client
from asgard.providers import PROVIDERS, ResolvedProvider, resolve


class _Responses:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self._responses)


class TestOpenAIAPIProvider(unittest.TestCase):
    def test_official_profile_is_distinct_from_generic_compat(self):
        profile = PROVIDERS["openai"]
        self.assertEqual(profile.api_mode, "openai_responses")
        self.assertEqual(profile.base_url, "https://api.openai.com/v1")
        self.assertEqual(profile.env_vars, ("OPENAI_API_KEY",))
        self.assertEqual(profile.default_model, "gpt-5.6-sol")
        self.assertIn("gpt-5.6-terra", profile.fallback_models)

    def test_resolve_uses_openai_api_key_without_custom_endpoint(self):
        with (
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True),
            mock.patch("asgard.settings.load_global", return_value={}),
            mock.patch("asgard.settings.load_project", return_value={}),
            mock.patch("asgard.providers.load_credentials", return_value={}),
        ):
            rp = resolve("/tmp", provider="openai")
        self.assertEqual(rp.api_key, "test-key")
        self.assertEqual(rp.base_url, "https://api.openai.com/v1")
        self.assertEqual(rp.missing, [])

    def test_make_client_routes_official_provider_to_openai_sdk(self):
        rp = ResolvedProvider(
            profile=PROVIDERS["openai"],
            model="gpt-5.6-sol",
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
        with mock.patch("openai.OpenAI") as client:
            make_client(rp)
        client.assert_called_once_with(base_url="https://api.openai.com/v1", api_key="test-key")

    def test_responses_api_executes_canonical_function_tool_loop(self):
        call = SimpleNamespace(
            type="function_call",
            id="fc-1",
            call_id="call-1",
            name="probe",
            arguments='{"value":"ok"}',
        )
        first = SimpleNamespace(
            id="resp-1",
            output=[call],
            output_text="",
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
                input_tokens_details=SimpleNamespace(cached_tokens=60),
            ),
        )
        second = SimpleNamespace(
            id="resp-2",
            output=[],
            output_text="done",
            usage=SimpleNamespace(
                input_tokens=80,
                output_tokens=10,
                total_tokens=90,
                input_tokens_details=SimpleNamespace(cached_tokens=40),
            ),
        )
        responses = _Responses([first, second])
        client = SimpleNamespace(responses=responses)
        rp = ResolvedProvider(
            profile=PROVIDERS["openai"],
            model="gpt-5.6-sol",
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
        tool = {
            "name": "probe",
            "description": "return a value",
            "input_schema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        }
        session = AgentSession(client, rp, "/tmp", "system", extra_tools=[tool], tool_handlers={"probe": lambda i: i["value"]})
        result = session.run("hello")

        self.assertEqual(result.text, "done")
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(result.tool_calls[-1]["name"], "probe")
        self.assertEqual(result.tokens, 210)
        self.assertEqual(result.cache_read_tokens, 100)
        first_call, second_call = responses.calls
        self.assertEqual(first_call["instructions"], "system")
        self.assertEqual(first_call["input"], "hello")
        probe = next(tool for tool in first_call["tools"] if tool["name"] == "probe")
        self.assertEqual(probe["type"], "function")
        self.assertNotIn("function", probe)
        self.assertEqual(first_call["max_output_tokens"], 32_768)
        self.assertEqual(first_call["timeout"], 3600.0)
        self.assertEqual(first_call["truncation"], "auto")
        self.assertEqual(second_call["previous_response_id"], "resp-1")
        self.assertEqual(
            second_call["input"],
            [{"type": "function_call_output", "call_id": "call-1", "output": "ok"}],
        )

    def test_internal_responses_completion_is_explicitly_bounded(self):
        from asgard.agent.heimdall import Heimdall

        rp = ResolvedProvider(
            profile=PROVIDERS["openai"],
            model="gpt-5.6-sol",
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
        responses = mock.Mock()
        responses.create.return_value = SimpleNamespace(output_text="classified")
        fake = SimpleNamespace(
            role_rp={},
            rp=rp,
            root="/tmp",
            _client_for=lambda _rp: SimpleNamespace(responses=responses),
        )
        result = Heimdall._complete_text(fake, "system", "user", max_tokens=100)
        self.assertEqual(result, "classified")
        self.assertEqual(responses.create.call_args.kwargs["timeout"], 120.0)
        self.assertEqual(responses.create.call_args.kwargs["max_output_tokens"], 4096)
        self.assertEqual(responses.create.call_args.kwargs["reasoning"], {"effort": "low"})

    def test_incomplete_response_reports_max_tokens_instead_of_clean_end(self):
        response = SimpleNamespace(
            id="resp-incomplete",
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            output=[],
            output_text="partial",
            usage=None,
        )
        rp = ResolvedProvider(profile=PROVIDERS["openai"], model="gpt-5.6-sol")
        session = AgentSession(SimpleNamespace(responses=_Responses([response])), rp, "/tmp", "system")
        result = session.run("hello")
        self.assertEqual(result.stop_reason, "max_tokens")
        self.assertIsNone(session._openai_response_id)

    def test_content_filter_incomplete_is_not_mislabeled_as_token_exhaustion(self):
        response = SimpleNamespace(
            id="resp-filtered",
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="content_filter"),
            output=[],
            output_text="",
            usage=None,
        )
        rp = ResolvedProvider(profile=PROVIDERS["openai"], model="gpt-5.6-sol")
        session = AgentSession(SimpleNamespace(responses=_Responses([response])), rp, "/tmp", "system")
        result = session.run("hello")
        self.assertEqual(result.stop_reason, "content_filter")

    def test_max_iterations_does_not_leave_unresolved_response_chain(self):
        call = SimpleNamespace(type="function_call", call_id="call-1", name="probe", arguments="{}")
        response = SimpleNamespace(
            id="resp-unresolved",
            status="completed",
            output=[call],
            output_text="",
            usage=None,
        )
        rp = ResolvedProvider(profile=PROVIDERS["openai"], model="gpt-5.6-sol")
        session = AgentSession(
            SimpleNamespace(responses=_Responses([response])),
            rp,
            "/tmp",
            "system",
            extra_tools=[{"name": "probe", "input_schema": {"type": "object", "properties": {}}}],
            tool_handlers={"probe": lambda _value: "ok"},
            max_iterations=1,
        )
        result = session.run("hello")
        self.assertEqual(result.stop_reason, "max_iterations")
        self.assertIsNone(session._openai_response_id)


if __name__ == "__main__":
    unittest.main()
