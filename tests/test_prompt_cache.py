#!/usr/bin/env python3
"""프롬프트 캐싱 자가 검증 — 브레이크포인트 주입(hermes system_and_3 재서술) + anthropic 트랜스포트
배선 + 캐시 포함 usage 정산 (창 80% 프룬 트리거의 과소계상 방지).

실행: uv run pytest tests/test_prompt_cache.py
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.agent.prompt_cache import (  # noqa: E402
    cache_settings,
    cached_openai_request,
    cached_request,
    openai_cache_markers_supported,
)


def _msg(role, content):
    return {"role": role, "content": content}


class TestCachedRequest(unittest.TestCase):
    def test_system_becomes_marked_block(self):
        sys_blocks, _ = cached_request("역할 프롬프트", [])
        self.assertEqual(sys_blocks[0]["text"], "역할 프롬프트")
        self.assertEqual(sys_blocks[0]["cache_control"], {"type": "ephemeral"})

    def test_ttl_1h_marker(self):
        sys_blocks, msgs = cached_request("s", [_msg("user", "q")], ttl="1h")
        self.assertEqual(sys_blocks[0]["cache_control"], {"type": "ephemeral", "ttl": "1h"})
        self.assertEqual(msgs[0]["content"][0]["cache_control"], {"type": "ephemeral", "ttl": "1h"})

    def test_last_three_user_messages_marked_max_four_breakpoints(self):
        msgs = []
        for i in range(5):
            msgs.append(_msg("user", [{"type": "tool_result", "tool_use_id": str(i), "content": "r"}]))
            msgs.append(_msg("assistant", [{"type": "text", "text": "a"}]))
        _, out = cached_request("s", msgs)
        marked = [
            i
            for i, m in enumerate(out)
            if isinstance(m["content"], list) and any("cache_control" in b for b in m["content"] if isinstance(b, dict))
        ]
        self.assertEqual(marked, [4, 6, 8])  # 마지막 user 3개만 — system 1 + 3 = 브레이크포인트 4 (최대치)

    def test_string_user_content_converted_to_block(self):
        _, out = cached_request("s", [_msg("user", "질문")])
        self.assertEqual(out[0]["content"][0], {"type": "text", "text": "질문", "cache_control": {"type": "ephemeral"}})

    def test_assistant_and_sdk_objects_untouched(self):
        # assistant 는 SDK 객체(ThinkingBlock 포함 — cache_control 거부 대상) — 마킹 금지, 참조 그대로
        sdk_obj = SimpleNamespace(type="text", text="a")
        msgs = [_msg("user", "q"), _msg("assistant", [sdk_obj])]
        _, out = cached_request("s", msgs)
        self.assertIs(out[1]["content"][0], sdk_obj)
        self.assertFalse(hasattr(sdk_obj, "cache_control"))

    def test_original_messages_not_mutated(self):
        msgs = [_msg("user", "q"), _msg("user", [{"type": "tool_result", "tool_use_id": "1", "content": "r"}])]
        cached_request("s", msgs)
        self.assertEqual(msgs[0]["content"], "q")  # 문자열 그대로
        self.assertNotIn("cache_control", msgs[1]["content"][0])  # 원본 블록 무마킹


class TestOpenAIWirePolicy(unittest.TestCase):
    """openai_compat 마커 정책 — 실측 검증 조합(hermes)만 화이트리스트, 그 외 미주입 (400 방지)."""

    def test_whitelist(self):
        cases = {
            ("https://openrouter.ai/api/v1", "anthropic/claude-sonnet-5"): True,
            ("https://openrouter.ai/api/v1", "qwen/qwen3-coder"): True,
            ("https://openrouter.ai/api/v1", "openai/gpt-5"): False,
            ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-max"): True,
            ("https://integrate.api.nvidia.com/v1", "nvidia/nemotron-3"): False,  # NIM — 계약 부재
            ("http://localhost:11434/v1", "gemma4:12b-mlx"): False,  # ollama — 로컬 KV 자동
            ("", "claude-opus-4-8"): False,
        }
        for (base, model), expected in cases.items():
            self.assertEqual(openai_cache_markers_supported(base, model), expected, (base, model))


class TestCachedOpenAIRequest(unittest.TestCase):
    """envelope 레이아웃 (비-네이티브 변형) — system + 최근 비-system 3, tool 역할 스킵."""

    def test_system_and_last_three(self):
        sys_msgs = [_msg("system", "s")]
        msgs = [_msg("user", "q1"), _msg("assistant", "a1"), _msg("user", "q2"), _msg("assistant", "a2")]
        out = cached_openai_request(sys_msgs, msgs)
        self.assertIn("cache_control", out[0]["content"][0])  # system
        self.assertNotIn("cache_control", str(out[1]))  # 오래된 user — 마커 밖
        for i in (2, 3, 4):  # 최근 비-system 3
            self.assertIn("cache_control", str(out[i]))

    def test_tool_role_skipped_none_content_gets_envelope(self):
        sys_msgs = [_msg("system", "s")]
        msgs = [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
            _msg("tool", "result"),
            _msg("user", "q"),
        ]
        out = cached_openai_request(sys_msgs, msgs)
        self.assertEqual(out[1].get("cache_control"), {"type": "ephemeral"})  # None content → 봉투 마커
        self.assertNotIn("cache_control", out[2])  # tool 역할 — 스킵 (마커 자리 없음)
        self.assertNotIn("cache_control", str(msgs))  # 원본 불변

    def test_original_untouched(self):
        sys_msgs = [_msg("system", "s")]
        msgs = [_msg("user", "q")]
        cached_openai_request(sys_msgs, msgs)
        self.assertEqual(sys_msgs[0]["content"], "s")
        self.assertEqual(msgs[0]["content"], "q")


class TestModeABScaffoldDiscipline(unittest.TestCase):
    """모드 A/B — 캐싱은 호스트 툴(CC/Codex/Cursor) 소유. 우리 몫 = 스캐폴드 정적 프리픽스 규율:
    같은 입력이면 바이트 동일해야 호스트 캐시가 산다 (타임스탬프·난수 유입 감시)."""

    def test_scaffold_deterministic(self):
        from asgard.commands.setup import plan_files

        a, _ = plan_files(cc=True, cursor=True, codex=True, root="/tmp/x")
        b, _ = plan_files(cc=True, cursor=True, codex=True, root="/tmp/x")
        self.assertEqual(a, b)


class _TmpHome(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self.root  # 글로벌 config 오염 차단

    def tearDown(self):
        if self._home is not None:
            os.environ["HOME"] = self._home
        self._tmp.cleanup()


class TestCacheSettings(_TmpHome):
    def test_default_on_5m(self):
        self.assertEqual(cache_settings(self.root), (True, "5m"))

    def test_config_opt_out_and_ttl(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write('[cache]\nenabled = false\nttl = "1h"\n')
        self.assertEqual(cache_settings(self.root), (False, "1h"))

    def test_bogus_ttl_falls_back_to_5m(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write('[cache]\nttl = "3d"\n')
        self.assertEqual(cache_settings(self.root), (True, "5m"))


class _FakeStream:
    """messages.stream 대역 — 캡처한 kwargs 검증 + 스크립트된 최종 메시지."""

    def __init__(self, resp):
        self.resp = resp
        self.text_stream = iter(["hi"])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.resp


class _FakeClient:
    def __init__(self, resp):
        self.captured: dict = {}
        self._resp = resp
        outer = self

        class _Messages:
            def stream(self, **kw):
                outer.captured = kw
                return _FakeStream(outer._resp)

        self.messages = _Messages()


def _resp(input_tokens=100, output_tokens=10, cache_read=0, cache_write=0):
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )
    block = SimpleNamespace(type="text", text="hi")
    return SimpleNamespace(content=[block], stop_reason="end_turn", usage=usage)


class TestAnthropicWiring(_TmpHome):
    """_run_anthropic 배선 — 요청에 마커 실림 + 원본 불변 + 캐시 포함 컨텍스트 정산."""

    def _session(self):
        from asgard.agent.session import AgentSession
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        client = _FakeClient(_resp(input_tokens=50, output_tokens=10, cache_read=900, cache_write=40))
        return AgentSession(client, rp, self.root, "시스템 프롬프트"), client

    def test_request_carries_markers_history_stays_clean(self):
        s, client = self._session()
        r = s.run("질문")
        self.assertEqual(client.captured["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertIn("cache_control", client.captured["messages"][0]["content"][0])
        self.assertEqual(s.messages[0]["content"], "질문")  # 세션 히스토리는 무마킹 원본
        # 컨텍스트 = 정가 입력 + 캐시 read/write + 출력 — 캐시분 누락 시 프룬 트리거 과소계상
        self.assertEqual(r.context_tokens, 50 + 900 + 40 + 10)
        self.assertEqual((r.cache_read_tokens, r.cache_write_tokens, r.uncached_input_tokens), (900, 40, 50))

    def test_config_off_sends_raw_prompt(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write("[cache]\nenabled = false\n")
        s, client = self._session()
        s.run("질문")
        self.assertEqual(client.captured["system"], "시스템 프롬프트")  # 문자열 그대로 — 무주입
        self.assertNotIn("cache_control", str(client.captured["messages"]))


def _oai_chunks(cached_tokens=0, prompt_tokens=100, total_tokens=110):
    delta = SimpleNamespace(reasoning_content=None, reasoning=None, content="hi", tool_calls=None)
    fin = SimpleNamespace(reasoning_content=None, reasoning=None, content=None, tool_calls=None)
    usage = SimpleNamespace(
        total_tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
    )
    return [
        SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason=None, delta=delta)]),
        SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason="stop", delta=fin)]),
        SimpleNamespace(usage=usage, choices=[]),
    ]


class _FakeOpenAI:
    def __init__(self, chunks):
        self.captured: dict = {}
        outer = self

        class _Completions:
            def create(self, **kw):
                outer.captured = kw
                return iter(chunks)

        self.chat = SimpleNamespace(completions=_Completions())


class TestOpenAIWiring(_TmpHome):
    """_run_openai 배선 — 화이트리스트 조합만 마커 주입, cached_tokens 계측은 공통."""

    def _session(self, base_url, model):
        from asgard.agent.session import AgentSession
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["openai_compat"], model=model, base_url=base_url, api_key="k")
        client = _FakeOpenAI(_oai_chunks(cached_tokens=900, prompt_tokens=990, total_tokens=1000))
        return AgentSession(client, rp, self.root, "시스템"), client

    def test_openrouter_claude_gets_markers_and_metering(self):
        s, client = self._session("https://openrouter.ai/api/v1", "anthropic/claude-sonnet-5")
        r = s.run("질문")
        self.assertIn("cache_control", str(client.captured["messages"][0]))  # system 마커
        self.assertIn("cache_control", str(client.captured["messages"][-1]))  # 최근 메시지 마커
        self.assertEqual(s.messages[0]["content"], "질문")  # 히스토리 무마킹 원본
        self.assertEqual((r.cache_read_tokens, r.uncached_input_tokens), (900, 90))

    def test_unknown_provider_no_markers_metering_still_works(self):
        s, client = self._session("https://integrate.api.nvidia.com/v1", "nvidia/nemotron-3")
        r = s.run("질문")
        self.assertNotIn("cache_control", str(client.captured["messages"]))  # 미주입 — 400 방지
        self.assertEqual(r.cache_read_tokens, 900)  # 리포트되면 계측은 동작 (OpenAI 자동 캐시 대응)


if __name__ == "__main__":
    unittest.main(verbosity=1)
