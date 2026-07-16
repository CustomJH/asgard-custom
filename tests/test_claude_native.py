#!/usr/bin/env python3
"""claude_cli 트랜스포트 결정론 슬라이스 — CLI 스폰 없는 부분 전부.

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
    StreamEvent,
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

    def _session(self, extra_tools=None, handlers=None, *, readonly=False, role=None):
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
            readonly=readonly,
            role=role,
        )


class TestTransport(_Sess):
    def test_canonical_readonly_role_wins_when_readonly_flag_is_omitted(self):
        query, calls = _fake_query([[_result_msg()]])
        sess = self._session(readonly=False, role="verifier")
        with mock.patch("claude_agent_sdk.query", query):
            sess.run("verify")
        options = calls[0][1]
        self.assertNotIn("Write", options.tools)
        self.assertNotIn("Edit", options.tools)
        hook = options.hooks["PreToolUse"][0].hooks[0]
        denied = asyncio.run(
            hook(
                {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "printf x > file"}},
                "id",
                {"signal": None},
            )
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_sdk_hook_applies_destructive_guard_to_writable_role(self):
        query, calls = _fake_query([[_result_msg()]])
        sess = self._session(role="worker")
        with mock.patch("claude_agent_sdk.query", query):
            sess.run("work")
        hook = calls[0][1].hooks["PreToolUse"][0].hooks[0]
        denied = asyncio.run(
            hook(
                {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git restore ."}},
                "id",
                {"signal": None},
            )
        )
        allowed = asyncio.run(
            hook(
                {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "printf x > file"}},
                "id",
                {"signal": None},
            )
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(allowed, {})

    def test_readonly_sdk_hook_blocks_mutating_bash(self):
        query, calls = _fake_query([[_result_msg()]])
        sess = self._session(readonly=True, role="verifier")
        with mock.patch("claude_agent_sdk.query", query):
            sess.run("verify")
        hook = calls[0][1].hooks["PreToolUse"][0].hooks[0]
        denied = asyncio.run(
            hook(
                {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "echo x > y"}},
                "id",
                {"signal": None},
            )
        )
        allowed = asyncio.run(
            hook(
                {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git diff"}},
                "id",
                {"signal": None},
            )
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(allowed, {})

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
        self.assertEqual((r.cache_read_tokens, r.cache_write_tokens), (0, 0))  # 캐시 필드 부재 = 0
        # 옵션 계약 — 시스템 프롬프트·cwd·권한 모드·내장 툴 셋·스트리밍·bash 상한
        _, opt = calls[0]
        self.assertEqual(opt.system_prompt, "you are a test")
        self.assertEqual(opt.permission_mode, "bypassPermissions")
        self.assertEqual(opt.tools, claude_native.BUILTIN_TOOLS)
        self.assertIsNone(opt.resume)
        self.assertTrue(opt.include_partial_messages)
        self.assertEqual(opt.env["BASH_MAX_TIMEOUT_MS"], "120000")  # tools._TIMEOUT 패리티
        self.assertTrue(opt.strict_mcp_config)  # 유저/프로젝트 MCP 누출 차단 — Asgard 가 툴 표면 소유

    def test_cache_usage_metered(self):
        # Claude Code 가 자체 캐싱 — 계측 패리티: 캐시 적중분을 지출·적중률에 합산 (누락 시 전부 0 으로 보임)
        script = [
            [
                AssistantMessage(content=[TextBlock(text="ok")], model="m"),
                _result_msg(
                    usage={
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 900,
                        "cache_creation_input_tokens": 40,
                    }
                ),
            ]
        ]
        query, _ = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            r = sess.run("hi")
        self.assertEqual(r.tokens, 20 + 5 + 900 + 40)
        self.assertEqual((r.cache_read_tokens, r.cache_write_tokens, r.uncached_input_tokens), (900, 40, 20))

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


def _delta(text):
    return StreamEvent(
        uuid="u",
        session_id="s",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    )


class TestStreaming(_Sess):
    """텍스트 델타 스트리밍 (include_partial_messages) — anthropic 트랜스포트 체감 패리티."""

    def test_deltas_stream_and_block_not_duplicated(self):
        script = [
            [
                _delta("hel"),
                _delta("lo"),
                AssistantMessage(content=[TextBlock(text="hello")], model="m"),
                _result_msg(),
            ]
        ]
        query, _ = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            r = sess.run("hi")
        self.assertEqual(self.texts, ["hel", "lo"])  # 델타만 방출 — TextBlock 전체 재방출 없음
        self.assertEqual(r.text, "hello")  # result.text 는 여전히 완성 블록 소스

    def test_stream_only_response_is_preserved_in_result(self):
        # 실 Claude CLI에서 최종 AssistantMessage/TextBlock 없이 델타 + ResultMessage만 오는
        # 경로가 있다. 스트리밍 출력만 보이고 `asgard run --json` result가 빈 문자열이면 안 된다.
        script = [
            [
                _delta("stream "),
                _delta("only"),
                AssistantMessage(content=[TextBlock(text="")], model="m"),
                _result_msg(),
            ]
        ]
        query, _ = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            r = sess.run("hi")
        self.assertEqual(self.texts, ["stream ", "only"])
        self.assertEqual(r.text, "stream only")

    def test_non_text_deltas_ignored(self):
        script = [
            [
                StreamEvent(
                    uuid="u",
                    session_id="s",
                    event={"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{"}},
                ),
                StreamEvent(uuid="u", session_id="s", event={"type": "message_start"}),
                AssistantMessage(content=[TextBlock(text="done")], model="m"),
                _result_msg(),
            ]
        ]
        query, _ = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            r = sess.run("hi")
        self.assertEqual(self.texts, ["done"])  # 텍스트 델타 없음 → 폴백 전체 방출
        self.assertEqual(r.text, "done")


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


class TestBanGuards(_Sess):
    """밴/차단 방어 — 캡 감지·프록시 거부·인증 감지·동시성 상한."""

    def test_base_url_rejected(self):
        sess = self._session()
        sess.rp.base_url = "https://proxy.example.com"
        with self.assertRaises(RuntimeError) as cm:
            sess.run("hi")
        self.assertIn("base_url", str(cm.exception))

    def test_usage_cap_in_result_message_raises(self):
        script = [
            [
                ResultMessage(
                    subtype="error_during_execution",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=True,
                    num_turns=1,
                    session_id="s",
                    result="Claude AI usage limit reached|1760000000",
                )
            ]
        ]
        query, _ = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            with self.assertRaises(claude_native.UsageCapError):
                sess.run("hi")

    def test_usage_cap_classified_fatal(self):
        from asgard.agent.heimdall import classify_api_error

        self.assertEqual(classify_api_error(claude_native.UsageCapError("한도")), "fatal")

    def test_non_cap_error_result_passes_through(self):
        script = [[_result_msg(subtype="error_during_execution", result="some other failure")]]
        query, _ = _fake_query(script)
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            r = sess.run("hi")  # 캡 아님 — 예외 없이 stop_reason 으로 표면화
        self.assertEqual(r.stop_reason, "error_during_execution")

    def test_cap_markers(self):
        self.assertTrue(claude_native._is_usage_cap("You've hit your weekly limit · resets Mon 12:00am"))
        self.assertTrue(claude_native._is_usage_cap("You've hit your session limit · resets 3:45pm"))
        self.assertTrue(claude_native._is_usage_cap("You've hit your Opus limit · resets 3:45pm"))
        self.assertTrue(claude_native._is_usage_cap("", "You are out of extra usage"))
        self.assertFalse(claude_native._is_usage_cap("normal text", "tool failed"))

    def test_transient_throttle_is_not_cap(self):
        # 공식 일시 스로틀 문구 — CLI 내장 백오프 대상, fatal 캡으로 오분류 금지
        self.assertFalse(
            claude_native._is_usage_cap("API Error: Server is temporarily limiting requests (not your usage limit)")
        )

    def test_guard_env_neutralizes_proxy_on_subscription(self):
        env = {"ANTHROPIC_BASE_URL": "https://gw.example.com"}
        with mock.patch.dict("os.environ", env):
            with mock.patch.object(claude_native, "detect_auth", return_value=("keychain", "")):
                self.assertEqual(claude_native._guard_env(), {"ANTHROPIC_BASE_URL": ""})
            with mock.patch.object(claude_native, "detect_auth", return_value=("api_key", "")):
                self.assertEqual(claude_native._guard_env(), {})  # API 키 인증은 게이트웨이 존중

    def test_guard_env_noop_without_proxy(self):
        import os

        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_BASE_URL"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(claude_native._guard_env(), {})

    def test_detect_auth_api_key_warns_billing(self):
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-x"}):
            kind, detail = claude_native.detect_auth()
        self.assertEqual(kind, "api_key")
        self.assertIn("과금", detail)

    def test_detect_auth_never_reads_token_values(self):
        # 감지 함수는 파일을 '읽지' 않는다 — 존재 확인만 (ToS: 토큰 추출 금지)
        import os

        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")}
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch("builtins.open", side_effect=AssertionError("token file must not be opened")):
                kind, _ = claude_native.detect_auth()
        self.assertIn(kind, ("keychain", "unknown"))

    def test_concurrency_gate_default(self):
        self.assertEqual(claude_native._MAX_CONCURRENT, 3)
        self.assertIsNotNone(claude_native._spawn_gate)


class TestDaemonLoop(unittest.TestCase):
    """단일 데몬 이벤트 루프 — 매턴 새 루프 대신 재사용으로 asyncgen/child-watcher 잔여 봉인."""

    def test_submit_reuses_single_loop(self):
        async def who():
            return id(asyncio.get_running_loop())

        a, b = claude_native._submit(who()), claude_native._submit(who())
        self.assertEqual(a, b)  # 두 제출이 같은 루프 — 매턴 새 루프 아님

    def test_submit_returns_coro_value(self):
        async def double(n):
            return n * 2

        self.assertEqual(claude_native._submit(double(21)), 42)

    def test_submit_timeout_cancels_and_raises(self):
        """CUS-246 — 행 코루틴은 timeout 에서 취소 + 처방적 TimeoutError (기존: 영구 블록)."""
        with self.assertRaises(TimeoutError) as cm:
            claude_native._submit(asyncio.sleep(30), timeout=0.05)
        self.assertIn("초과", str(cm.exception))
        self.assertIn("ASGARD_CLAUDE_TURN_TIMEOUT_S", str(cm.exception))

    def test_submit_passes_through_inner_timeout_error(self):
        """코루틴 자신이 던진 TimeoutError(SDK 내부) 는 대기 초과로 오인하지 않는다."""

        async def boom():
            raise TimeoutError("inner-cause")

        with self.assertRaises(TimeoutError) as cm:
            claude_native._submit(boom(), timeout=5)
        self.assertIn("inner-cause", str(cm.exception))

    def test_drained_closes_generator(self):
        closed = []

        async def gen():
            try:
                yield 1
                yield 2
            finally:
                closed.append(True)

        async def consume():
            return [m async for m in claude_native._drained(gen())]

        out = claude_native._submit(consume())
        self.assertEqual(out, [1, 2])
        self.assertEqual(closed, [True])  # finally 실행 = 명시적 정리됨


class TestSpawnGateReentrancy(_Sess):
    """CUS-246 — 디스패치 자식의 permit 재요구 데드락 봉인 + permit 수지 보존."""

    def test_nested_dispatch_skips_spawn_gate(self):
        """부모 worker 들이 permit 을 전부 쥔 상황(데드락 조건)에서도 디스패치 자식은 진행한다."""
        query, _ = _fake_query([[_result_msg()]])
        sess = self._session()
        sess._nested_dispatch = True  # _dispatch_handler 가 자식 세션에 다는 마커
        permits = [claude_native._spawn_gate.acquire(timeout=1) for _ in range(claude_native._MAX_CONCURRENT)]
        self.assertTrue(all(permits))  # permit 전량 점유 = 기존 코드라면 영구 대기 지점
        try:
            with mock.patch("claude_agent_sdk.query", query):
                r = sess.run("child task")
        finally:
            for _ in permits:
                claude_native._spawn_gate.release()
        self.assertEqual(r.stop_reason, "end_turn")

    def test_top_level_run_restores_permits(self):
        """acquire/release 수지 — run 후 permit 전량 복원 (BoundedSemaphore 초과 release 는 즉발)."""
        query, _ = _fake_query([[_result_msg()]])
        sess = self._session()
        with mock.patch("claude_agent_sdk.query", query):
            sess.run("task")
        got = [claude_native._spawn_gate.acquire(timeout=1) for _ in range(claude_native._MAX_CONCURRENT)]
        for _ in [g for g in got if g]:
            claude_native._spawn_gate.release()
        self.assertTrue(all(got))


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
        self.assertTrue(opt.strict_mcp_config)  # tools=[] 는 유저 MCP 를 못 막는다 (t1 4/4 fallback 원인)


if __name__ == "__main__":
    unittest.main()
