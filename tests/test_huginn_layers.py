#!/usr/bin/env python3
"""후긴 상위 3층 자가 검증 — T3 서버측 압축 · T4 방출 보관소 · ACON 교훈 루프.

핵심 앵커는 "압축이 파괴가 아니라 이동"이라는 계약이다: 요약이 잘라낸 구간은 보관소에서
원문 그대로 되짚을 수 있어야 하고, 실패한 압축은 다음 요약 프롬프트를 바꿔야 하며,
서버측 압축은 미지원 환경에서 세션을 깨는 대신 조용히 물러나야 한다.

실행: uv run pytest tests/test_huginn_layers.py
"""

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.agent import compact_lessons as L  # noqa: E402
from asgard.agent import evicted  # noqa: E402
from asgard.agent.huginn import (  # noqa: E402
    SERVER_BETA,
    CompressPolicy,
    Huginn,
    build_prompt,
    has_compaction_block,
    is_handoff,
    policy,
    server_side_kwargs,
)


def _user(text):
    return {"role": "user", "content": text}


def _assistant(text):
    return {"role": "assistant", "content": text}


def _chat(n, chars=8000, start=0):
    out = []
    for i in range(start, start + n):
        out.append(_user(f"요청 {i} " + "가" * chars))
        out.append(_assistant(f"응답 {i} " + "나" * chars))
    return out


def _long_session(pairs=40):
    return [_user("첫 요청"), _assistant("확인")] + _chat(pairs) + [_user("최신 요청 원문"), _assistant("네")]


_GOOD_SUMMARY = """## Active Task
User asked: '최신 요청 원문'

## Goal
압축 검증

## Constraints & Preferences
None.

## Completed Actions
1. READ src/a.py:1 — ok [tool: read]

## Active State
branch main

## Blocked
None.

## Key Decisions
None.

## Relevant Files
- src/a.py

## Critical Context
None."""


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        # 보관소는 ~/.asgard/sessions/<sha> 아래 — HOME 을 격리해 실사용 트리를 건드리지 않는다
        self._home = mock.patch.dict(os.environ, {"HOME": self.root})
        self._home.start()

    def tearDown(self):
        self._home.stop()
        self._tmp.cleanup()

    def engine(self, call=None, window=100_000, **overrides):
        settings: dict[str, Any] = {"min_recovery_tokens": 100, "tail_tokens": 4_000, **overrides}
        pol = CompressPolicy(**settings)
        return Huginn(self.root, window, pol, call=call, now=_Clock(), session_id="s1")


# ── T4 방출 보관소 ──────────────────────────────────────────────────────────


class TestVault(Base):
    def test_archive_then_recall_returns_original_text(self):
        n = evicted.archive(self.root, [("user", "TypeError: 'NoneType' is not subscriptable in parser.py")])
        self.assertEqual(n, 1)
        hits = evicted.recall(self.root, "NoneType subscriptable")
        self.assertTrue(hits)
        self.assertIn("NoneType", hits[0]["excerpt"])

    def test_blank_rows_are_skipped(self):
        self.assertEqual(evicted.archive(self.root, [("user", "  "), ("assistant", "")]), 0)

    def test_retention_caps_growth(self):
        with mock.patch.object(evicted, "_MAX_ROWS", 10):
            for i in range(30):
                evicted.archive(self.root, [("user", f"span {i} " + "x" * 50)])
            self.assertLessEqual(evicted.stats(self.root)["rows"], 10)

    def test_corrupt_db_is_isolated_and_rebuilt(self):
        evicted.archive(self.root, [("user", "seed content here")])
        with open(evicted.db_path(self.root), "wb") as f:
            f.write(b"not a database at all")
        self.assertEqual(evicted.archive(self.root, [("user", "after corruption rebuild")]), 1)
        self.assertTrue(evicted.recall(self.root, "corruption rebuild"))

    def test_recall_on_empty_vault_says_so(self):
        out = evicted.run_recall(self.root, {"query": "무엇이든"})
        self.assertIn("No compacted spans yet", out)

    def test_recall_requires_query(self):
        self.assertIn("required", evicted.run_recall(self.root, {"query": "  "}))

    def test_recall_miss_reports_span_count(self):
        evicted.archive(self.root, [("user", "완전히 다른 내용 alpha bravo")])
        out = evicted.run_recall(self.root, {"query": "zulu xray whiskey"})
        self.assertIn("No match", out)
        self.assertIn("1 compacted span", out)

    def test_recall_output_is_budgeted(self):
        evicted.archive(self.root, [("user", f"error {i} " + "y" * 4000) for i in range(30)])
        out = evicted.run_recall(self.root, {"query": "error", "limit": 20})
        self.assertLess(len(out), evicted._RECALL_BUDGET + 500)

    def test_summary_archives_the_evicted_window(self):
        engine = self.engine(call=lambda p, m: _GOOD_SUMMARY)
        msgs = _long_session()
        out, event = engine.compress(msgs, context_tokens=95_000)
        self.assertGreater(event.get("archived", 0), 0)
        self.assertTrue(any(is_handoff(m) for m in out))
        # 요약이 태운 내용이 원문으로 남아 있어야 한다
        self.assertTrue(evicted.recall(self.root, "요청 7"))

    def test_vault_disabled_archives_nothing(self):
        engine = self.engine(call=lambda p, m: _GOOD_SUMMARY, vault=False)
        _, event = engine.compress(_long_session(), context_tokens=95_000)
        self.assertEqual(event.get("tier"), "summary")
        self.assertNotIn("archived", event)
        self.assertEqual(evicted.stats(self.root)["rows"], 0)

    def test_archive_failure_does_not_undo_compression(self):
        engine = self.engine(call=lambda p, m: _GOOD_SUMMARY)
        with mock.patch.object(evicted, "archive", side_effect=RuntimeError("disk full")):
            out, event = engine.compress(_long_session(), context_tokens=95_000)
        self.assertEqual(event["tier"], "summary")
        self.assertTrue(any(is_handoff(m) for m in out))

    def test_secrets_are_redacted_before_archiving(self):
        engine = self.engine(call=lambda p, m: _GOOD_SUMMARY)
        msgs = _long_session()
        msgs.insert(4, _user("배포 설정 api_key=" + "S" * 40))
        engine.compress(msgs, context_tokens=95_000)
        hits = evicted.recall(self.root, "배포 설정")
        self.assertTrue(hits)
        self.assertNotIn("S" * 40, " ".join(h["excerpt"] for h in hits))

    def test_tool_is_registered_and_gated_by_policy(self):
        from asgard.agent.tool_kernel import ToolContext, build_session_registry, execute_tool

        registry = build_session_registry()
        ctx = ToolContext(root=self.root, role="worker")
        self.assertIn("context_recall", {s["name"] for s in registry.schemas(ctx)})
        result = execute_tool(registry, "context_recall", {"query": "무엇이든"}, ctx)
        self.assertEqual(result.status, "ok")

        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        from asgard.settings import PROJECT_FILE

        with open(os.path.join(self.root, ".asgard", PROJECT_FILE), "w") as f:
            json.dump({"compress": {"mode": "off"}}, f)
        with mock.patch("asgard.settings.load_global", return_value={}):
            self.assertNotIn("context_recall", {s["name"] for s in registry.schemas(ctx)})

    def test_tool_rejects_missing_query(self):
        from asgard.agent.tool_kernel import ToolContext, build_session_registry, execute_tool

        registry = build_session_registry()
        ctx = ToolContext(root=self.root, role="worker")
        self.assertEqual(execute_tool(registry, "context_recall", {}, ctx).status, "invalid_input")


# ── ACON 교훈 루프 ──────────────────────────────────────────────────────────


class TestLessons(Base):
    def test_clean_summary_has_no_faults(self):
        self.assertEqual(L.critique(_GOOD_SUMMARY, has_user_turn=True, budget_tokens=4000), [])

    def test_missing_sections_detected(self):
        faults = L.critique("## Active Task\n뭔가", has_user_turn=True, budget_tokens=4000)
        self.assertIn("missing_sections", faults)

    def test_empty_active_task_detected(self):
        body = _GOOD_SUMMARY.replace("User asked: '최신 요청 원문'", "")
        self.assertIn("empty_active_task", L.critique(body, has_user_turn=True, budget_tokens=4000))

    def test_invented_user_attribution_detected(self):
        faults = L.critique(_GOOD_SUMMARY, has_user_turn=False, budget_tokens=4000)
        self.assertIn("invented_user", faults)
        # 사용자 턴이 실제로 있으면 같은 문장이 결함이 아니다
        self.assertNotIn("invented_user", L.critique(_GOOD_SUMMARY, has_user_turn=True, budget_tokens=4000))

    def test_credential_leak_detected(self):
        body = _GOOD_SUMMARY.replace("None.", "api_key=" + "Z" * 40, 1)
        self.assertIn("credential_leak", L.critique(body, has_user_turn=True, budget_tokens=4000))

    def test_truncation_detected_at_budget_edge(self):
        body = "## Active Task\n작업\n\n## Goal\n" + "설명 " * 4000
        self.assertIn("truncated_summary", L.critique(body, has_user_turn=True, budget_tokens=3000))

    def test_record_then_guidelines_round_trip(self):
        self.assertEqual(L.guidelines(self.root), [])
        L.record(self.root, ["empty_active_task"])
        lines = L.guidelines(self.root)
        self.assertEqual(len(lines), 1)
        self.assertIn("Active Task", lines[0])
        self.assertIn("LEARNED GUIDELINES", L.guideline_block(self.root))

    def test_unknown_keys_are_ignored(self):
        L.record(self.root, ["made_up_failure"])
        self.assertEqual(L.guidelines(self.root), [])

    def test_frequent_lessons_rank_first(self):
        L.record(self.root, ["missing_sections"])
        for _ in range(3):
            L.record(self.root, ["credential_leak"])
        self.assertIn("credential", L.guidelines(self.root)[0].lower())

    def test_store_is_capped(self):
        with mock.patch.object(L, "_MAX", 2):
            for key in ("missing_sections", "empty_active_task", "invented_user", "credential_leak"):
                L.record(self.root, [key])
            self.assertLessEqual(len(L.load(self.root)), 2)

    def test_corrupt_store_falls_back_to_defaults(self):
        from asgard.settings import ensure_state_dir

        ensure_state_dir(self.root)
        with open(L._path(self.root), "w") as f:
            f.write("{not json")
        self.assertEqual(L.guidelines(self.root), [])
        L.record(self.root, ["missing_sections"])  # 손상 위에 다시 적립돼야 한다
        self.assertEqual(len(L.guidelines(self.root)), 1)

    def test_guidelines_reach_the_summary_prompt(self):
        prompts = []
        L.record(self.root, ["redone_work"])
        engine = self.engine(call=lambda p, m: prompts.append(p) or _GOOD_SUMMARY)
        engine.compress(_long_session(), context_tokens=95_000)
        self.assertIn("LEARNED GUIDELINES", prompts[0])
        self.assertIn("re-ran work", prompts[0])

    def test_lessons_disabled_keeps_prompt_bytes_stable(self):
        prompts = []
        L.record(self.root, ["redone_work"])
        engine = self.engine(call=lambda p, m: prompts.append(p) or _GOOD_SUMMARY, lessons=False)
        engine.compress(_long_session(), context_tokens=95_000)
        self.assertNotIn("LEARNED GUIDELINES", prompts[0])

    def test_bad_summary_is_recorded_as_a_lesson(self):
        engine = self.engine(call=lambda p, m: "## Active Task\n\n## Goal\n뭔가")
        engine.compress(_long_session(), context_tokens=95_000)
        self.assertTrue(set(L.load(self.root)) & {"missing_sections", "empty_active_task"})

    def test_no_lesson_is_truncated_mid_sentence(self):
        """문장 중간에서 잘린 지침은 없는 것보다 나쁘다 — 상한은 안전망이지 절단선이 아니다."""
        for key, text in L._LESSONS.items():
            self.assertLessEqual(len(text), L._MAX_CHARS, key)

    def test_empty_block_when_nothing_learned(self):
        self.assertEqual(L.guideline_block(self.root), "")
        self.assertEqual(build_prompt("turns", None, ""), build_prompt("turns", None))


class TestRedoDetection(Base):
    @staticmethod
    def _call(name, **args):
        return {"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": name, "input": args}]}

    def test_call_keys_cover_anthropic_and_openai_wires(self):
        anthropic = self._call("read", file_path="src/a.py")
        openai = {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "bash", "arguments": json.dumps({"command": "pytest -q"})}}],
        }
        keys = L.call_keys([anthropic, openai])
        self.assertIn("read:src/a.py", keys)
        self.assertIn("bash:pytest -q", keys)

    def test_same_command_with_different_whitespace_is_one_key(self):
        a = L.call_keys([self._call("bash", command="pytest  -q")])
        b = L.call_keys([self._call("bash", command="pytest -q")])
        self.assertEqual(a, b)

    def test_watch_fires_on_repeat_then_stops(self):
        watch = L.RedoWatch({"read:src/a.py"})
        self.assertTrue(watch.active)
        self.assertTrue(watch.observe([self._call("read", file_path="src/a.py")]))
        self.assertFalse(watch.active)  # 한 번 잡으면 같은 압축을 반복 청구하지 않는다

    def test_watch_closes_after_window(self):
        watch = L.RedoWatch({"read:src/a.py"}, window=2)
        for _ in range(2):
            self.assertFalse(watch.observe([self._call("read", file_path="src/other.py")]))
        self.assertFalse(watch.active)
        self.assertFalse(watch.observe([self._call("read", file_path="src/a.py")]))

    def test_empty_eviction_never_watches(self):
        self.assertFalse(L.RedoWatch(set()).active)

    def test_engine_records_redone_work_after_compaction(self):
        engine = self.engine(call=lambda p, m: _GOOD_SUMMARY)
        msgs = _long_session()
        msgs.insert(6, self._call("read", file_path="src/target.py"))
        engine.compress(msgs, context_tokens=95_000)
        self.assertTrue(engine.observe_turn([self._call("read", file_path="src/target.py")]))
        self.assertIn("redone_work", L.load(self.root))

    def test_unrelated_work_after_compaction_is_not_a_lesson(self):
        engine = self.engine(call=lambda p, m: _GOOD_SUMMARY)
        msgs = _long_session()
        msgs.insert(6, self._call("read", file_path="src/target.py"))
        engine.compress(msgs, context_tokens=95_000)
        self.assertFalse(engine.observe_turn([self._call("read", file_path="src/brand-new.py")]))
        self.assertNotIn("redone_work", L.load(self.root))

    def test_observe_is_inert_before_any_compaction(self):
        self.assertFalse(self.engine().observe_turn([self._call("read", file_path="src/a.py")]))


# ── T3 서버측 압축 ─────────────────────────────────────────────────────────


class TestServerSide(Base):
    def test_disabled_by_default(self):
        self.assertEqual(server_side_kwargs(CompressPolicy(), 200_000), {})
        self.assertEqual(self.engine().server_kwargs(), {})

    def test_enabled_emits_beta_and_edit(self):
        kwargs = server_side_kwargs(CompressPolicy(server_side=True), 200_000)
        self.assertEqual(kwargs["betas"], [SERVER_BETA])
        edit = kwargs["context_management"]["edits"][0]
        self.assertEqual(edit["type"], "compact_20260112")
        self.assertEqual(edit["trigger"], {"type": "input_tokens", "value": 180_000})
        # instructions 는 기본 프롬프트를 '대체'한다 — 비우면 우리 규율이 사라진다
        self.assertIn("## Active Task", edit["instructions"])

    def test_trigger_respects_api_minimum(self):
        kwargs = server_side_kwargs(CompressPolicy(server_side=True), 20_000)
        self.assertEqual(kwargs["context_management"]["edits"][0]["trigger"]["value"], 50_000)

    def test_explicit_trigger_overrides_ratio(self):
        pol = CompressPolicy(server_side=True, server_trigger_tokens=120_000)
        kwargs = server_side_kwargs(pol, 1_000_000)
        self.assertEqual(kwargs["context_management"]["edits"][0]["trigger"]["value"], 120_000)

    def test_mode_off_suppresses_server_kwargs(self):
        self.assertEqual(self.engine(mode="off", server_side=True).server_kwargs(), {})

    def test_compaction_block_detection(self):
        self.assertTrue(has_compaction_block([{"type": "compaction", "content": "요약"}]))
        self.assertTrue(has_compaction_block([SimpleNamespace(type="compaction", content="요약")]))
        self.assertFalse(has_compaction_block([{"type": "text", "text": "보통 응답"}]))

    def test_engine_counts_server_compactions_and_holds_off_refire(self):
        engine = self.engine(call=lambda p, m: _GOOD_SUMMARY, server_side=True)
        self.assertTrue(engine.note_server_compaction([{"type": "compaction", "content": "요약"}]))
        self.assertEqual(engine.server_compactions, 1)
        self.assertEqual(engine.summary_blocked(), "awaiting_usage")
        self.assertFalse(engine.note_server_compaction([{"type": "text", "text": "보통"}]))

    def test_policy_parses_server_keys(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        from asgard.settings import PROJECT_FILE

        with open(os.path.join(self.root, ".asgard", PROJECT_FILE), "w") as f:
            json.dump({"compress": {"server_side": "true", "vault": False, "lessons": "off"}}, f)
        with mock.patch("asgard.settings.load_global", return_value={}):
            pol = policy(self.root)
        self.assertTrue(pol.server_side)
        self.assertFalse(pol.vault)
        self.assertFalse(pol.lessons)


class TestServerSideWiring(Base):
    def _session(self, *, server_side: bool):
        from asgard.agent.session import AgentSession
        from asgard.providers import PROVIDERS, ResolvedProvider

        rp = ResolvedProvider(profile=PROVIDERS["anthropic"], model="m", api_key="k")
        client = SimpleNamespace(
            messages=SimpleNamespace(stream=mock.MagicMock(return_value="plain")),
            beta=SimpleNamespace(messages=SimpleNamespace(stream=mock.MagicMock(return_value="beta"))),
        )
        session = AgentSession(client, rp, self.root, "sys")
        session._huginn = Huginn(self.root, 200_000, CompressPolicy(server_side=server_side), call=None, now=_Clock())
        return session, client

    def test_plain_path_when_disabled(self):
        session, client = self._session(server_side=False)
        self.assertEqual(session._anthropic_stream(messages=[]), "plain")
        client.beta.messages.stream.assert_not_called()

    def test_beta_path_when_enabled(self):
        session, client = self._session(server_side=True)
        self.assertEqual(session._anthropic_stream(messages=[]), "beta")
        sent = client.beta.messages.stream.call_args.kwargs
        self.assertEqual(sent["betas"], [SERVER_BETA])

    def test_unsupported_sdk_falls_back_once(self):
        session, client = self._session(server_side=True)
        client.beta.messages.stream.side_effect = TypeError("unexpected keyword 'context_management'")
        self.assertEqual(session._anthropic_stream(messages=[]), "plain")
        # 두 번째부터는 beta 를 다시 두드리지 않는다
        client.beta.messages.stream.reset_mock()
        self.assertEqual(session._anthropic_stream(messages=[]), "plain")
        client.beta.messages.stream.assert_not_called()

    def test_request_error_triggers_one_retry_then_disables(self):
        session, _ = self._session(server_side=True)
        session._anthropic_stream(messages=[])  # beta 경로 활성
        self.assertTrue(session._server_compaction_retry())  # 400/403 → 끄고 재시도
        self.assertFalse(session._server_compaction_retry())  # 두 번째는 재시도 아님

    def test_retry_is_false_on_plain_path(self):
        session, _ = self._session(server_side=False)
        session._anthropic_stream(messages=[])
        self.assertFalse(session._server_compaction_retry())

    def test_session_reports_server_compaction(self):
        session, _ = self._session(server_side=True)
        lines = []
        session.on_text = lines.append
        session._note_server_compaction([{"type": "compaction", "content": "요약"}])
        self.assertTrue(any("서버측" in line for line in lines))
        self.assertEqual(session.huginn.server_compactions, 1)


if __name__ == "__main__":
    unittest.main()
