#!/usr/bin/env python3
"""claude_cli 트랜스포트 결정론 슬라이스 (CUS-190) — CLI 스폰 없는 부분 전부.

Agent SDK 의 query 만 페이크로 갈고 메시지 타입은 실물 dataclass 사용 — isinstance 분기가
실제 와이어 타입과 어긋나면 여기서 깨진다. 라이브 CLI 스모크는 수동 (구독 한도 소모).

실행: uv run pytest tests/test_claude_native.py
"""

import asyncio
import unittest
from unittest import mock

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from asgard.agent import claude_native
from asgard.agent.session import AgentSession
from asgard.providers import PROVIDERS, resolve


def _result_msg(subtype="success", session_id="sid-1", usage=None, result=None):
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=subtype != "success",
        num_turns=1,
        session_id=session_id,
        usage=usage,
        result=result,
    )


def _fake_query(script):
    """script = 세션별 메시지 리스트의 리스트 — 호출마다 다음 리스트를 방출. 옵션 캡처."""
    calls = []

    async def query(prompt, options):
        calls.append((prompt, options))
        for m in script[len(calls) - 1]:
            yield m

    return query, calls


class TestProfile(unittest.TestCase):
    def test_profile_facts(self):
        p = PROVIDERS["claude-native"]
        self.assertEqual(p.api_mode, "claude_cli")
        self.assertTrue(p.key_optional)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", p.env_vars)

    def test_resolve_keyless_marks_keychain(self):
        import os

        env = {k: v for k, v in os.environ.items() if k not in PROVIDERS["claude-native"].env_vars}
        with mock.patch.dict("os.environ", env, clear=True):
            rp = resolve("/tmp", provider="claude-native")
        self.assertEqual(rp.key_source, "claude login (keychain)")
        self.assertEqual(rp.api_key, "")  # 더미 키 없음 — 인증은 CLI 몫
        self.assertFalse([m for m in rp.missing if "API 키" in m])


class TestNativeClient(unittest.TestCase):
    def test_missing_cli_is_prescriptive(self):
        with mock.patch.object(claude_native.shutil, "which", return_value=None):
            with self.assertRaises(RuntimeError) as cm:
                claude_native.make_native_client()
        self.assertIn("claude CLI", str(cm.exception))

    def test_present_cli(self):
        with mock.patch.object(claude_native.shutil, "which", return_value="/usr/bin/claude"):
            c = claude_native.make_native_client()
        self.assertEqual(c.cli_path, "/usr/bin/claude")


class _Sess(unittest.TestCase):
    """AgentSession 을 claude-native rp 로 구성 — client 는 마커라 None 로 충분."""

    def _session(self, extra_tools=None, handlers=None):
        rp = resolve("/tmp", provider="claude-native")
        self.texts = []
        return AgentSession(
            client=None,
            rp=rp,
            root="/tmp",
            system="you are a test",
            extra_tools=extra_tools,
            tool_handlers=handlers,
            on_text=self.texts.append,
        )


class TestTransport(_Sess):
    def test_text_tokens_stop_reason(self):
        script = [
            [
                AssistantMessage(content=[TextBlock(text="hello ")], model="m"),
                AssistantMessage(content=[TextBlock(text="world")], model="m"),
                _result_msg(usage={"input_tokens": 10, "output_tokens": 5}),
            ]
        ]
        query, calls = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            r = sess.run("hi")
        self.assertEqual(self.texts, ["hello ", "world"])
        self.assertEqual(r.text, "world")  # anthropic 트랜스포트 계약 — 마지막 어시스턴트 텍스트
        self.assertEqual(r.tokens, 15)
        self.assertEqual(r.stop_reason, "end_turn")
        # 옵션 계약 — 시스템 프롬프트·cwd·권한 모드·내장 툴 셋
        _, opt = calls[0]
        self.assertEqual(opt.system_prompt, "you are a test")
        self.assertEqual(opt.permission_mode, "bypassPermissions")
        self.assertEqual(opt.tools, claude_native.BUILTIN_TOOLS)
        self.assertIsNone(opt.resume)

    def test_resume_on_second_turn(self):
        script = [[_result_msg(session_id="sid-42")], [_result_msg(session_id="sid-42")]]
        query, calls = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            sess.run("one")
            sess.run("two")
        self.assertIsNone(calls[0][1].resume)
        self.assertEqual(calls[1][1].resume, "sid-42")

    def test_commands_and_exit_code_approximation(self):
        use = ToolUseBlock(id="t1", name="Bash", input={"command": "false"})
        bad = ToolResultBlock(tool_use_id="t1", content="err", is_error=True)
        script = [
            [
                AssistantMessage(content=[use], model="m"),
                UserMessage(content=[bad]),
                _result_msg(),
            ]
        ]
        query, _ = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            r = sess.run("run false")
        self.assertEqual(r.commands, [{"cmd": "false", "exit_code": 1}])

    def test_writes_recorded_on_success_only(self):
        ok_use = ToolUseBlock(id="w1", name="Write", input={"file_path": "a.txt"})
        ok_res = ToolResultBlock(tool_use_id="w1", content="ok", is_error=None)
        bad_use = ToolUseBlock(id="w2", name="Edit", input={"file_path": "b.txt"})
        bad_res = ToolResultBlock(tool_use_id="w2", content="fail", is_error=True)
        script = [
            [
                AssistantMessage(content=[ok_use, bad_use], model="m"),
                UserMessage(content=[ok_res, bad_res]),
                _result_msg(),
            ]
        ]
        query, _ = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            r = sess.run("write files")
        self.assertEqual(r.writes, ["a.txt"])

    def test_max_turns_maps_to_max_iterations(self):
        script = [[_result_msg(subtype="error_max_turns")]]
        query, _ = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            r = sess.run("loop")
        self.assertEqual(r.stop_reason, "max_iterations")

    def test_result_text_fallback(self):
        script = [[_result_msg(result="final answer")]]
        query, _ = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            r = sess.run("q")
        self.assertEqual(r.text, "final answer")


class TestCustomToolBridge(_Sess):
    TOOL = {
        "name": "verdict",
        "description": "판정",
        "input_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
    }

    def test_mcp_server_registered_and_allowed(self):
        script = [[_result_msg()]]
        query, calls = _fake_query(script)
        sess = self._session(extra_tools=[self.TOOL], handlers={"verdict": lambda i: "ok"})
        with mock.patch("claude_agent_sdk.query", query):
            sess.run("judge")
        _, opt = calls[0]
        self.assertIn("asgard", opt.mcp_servers)
        self.assertIn("mcp__asgard__*", opt.allowed_tools)

    def test_bridge_runs_sync_handler_and_records_call(self):
        seen = []
        result = mock.Mock(tool_calls=[])
        sess = self._session(extra_tools=[self.TOOL], handlers={"verdict": lambda i: seen.append(i) or "PASS"})
        t = claude_native._bridge_tool(sess, self.TOOL, result)
        out = asyncio.run(t.handler({"ok": True}))
        self.assertEqual(seen, [{"ok": True}])
        self.assertEqual(out["content"][0]["text"], "PASS")
        self.assertEqual(result.tool_calls, [{"name": "verdict", "input": {"ok": True}}])

    def test_bridge_crash_is_error_result(self):
        def boom(i):
            raise RuntimeError("nope")

        result = mock.Mock(tool_calls=[])
        sess = self._session(extra_tools=[self.TOOL], handlers={"verdict": boom})
        t = claude_native._bridge_tool(sess, self.TOOL, result)
        out = asyncio.run(t.handler({"ok": False}))
        self.assertTrue(out["is_error"])
        self.assertIn("nope", out["content"][0]["text"])


class TestCompleteText(unittest.TestCase):
    def test_tools_removed_single_turn(self):
        calls = []

        async def query(prompt, options):
            calls.append((prompt, options))
            yield _result_msg(result='{"ok":true}')

        with mock.patch("claude_agent_sdk.query", query):
            out = claude_native.complete_text("classifier", "1+1?", model="claude-haiku-4-5-20251001")
        self.assertEqual(out, '{"ok":true}')
        _, opt = calls[0]
        self.assertEqual(opt.tools, [])
        self.assertEqual(opt.max_turns, 1)
        self.assertEqual(opt.model, "claude-haiku-4-5-20251001")


if __name__ == "__main__":
    unittest.main()
