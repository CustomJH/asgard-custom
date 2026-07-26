#!/usr/bin/env python3
"""후긴(컨텍스트 압축) 자가 검증 — 사다리 발동·경계 정렬·툴 쌍 무결성·가드.

압축의 실패 모드는 "덜 줄인 것"이 아니라 "살려야 할 걸 태운 것"이라, 앵커는 회수량보다
불변식(툴 쌍·교대·핸드오프 단일성·실패 시 원본 보존)에 몰려 있다.

실행: uv run pytest tests/test_huginn.py
"""

import os
import sys
import tempfile
import unittest
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.agent.huginn import (  # noqa: E402
    HANDOFF_ACK,
    HANDOFF_PREFIX,
    CompressPolicy,
    Huginn,
    classify_failure,
    estimate_tokens,
    extract_handoff,
    hygiene_and_prune,
    is_handoff,
    policy,
    prune_codex_items,
    sanitize_tool_pairs,
    serialize_turns,
)


def _user(text):
    return {"role": "user", "content": text}


def _assistant(text):
    return {"role": "assistant", "content": text}


def _tool_use(cid, name="read", inp=None):
    return {"role": "assistant", "content": [{"type": "tool_use", "id": cid, "name": name, "input": inp or {}}]}


def _tool_result(cid, body):
    return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": cid, "content": body}]}


def _loop(n, body_chars=8000, start=0):
    """tool_use/tool_result 쌍 n 회 — 툴 출력에 질량이 몰린 세션 (T1 이 걷어낼 수 있는 형태)."""
    out = []
    for i in range(start, start + n):
        out.append(_tool_use(f"t{i}", inp={"file_path": f"src/f{i}.py"}))
        out.append(_tool_result(f"t{i}", f"file {i} " + "x" * body_chars))
    return out


def _chat(n, chars=8000, start=0):
    """user/assistant 대화 n 쌍 — 질량이 대화 자체에 있는 세션. T1 이 손댈 수 없으므로
    T2(요약)까지 사다리를 내려가는 경로를 만든다."""
    out = []
    for i in range(start, start + n):
        out.append(_user(f"요청 {i} " + "가" * chars))
        out.append(_assistant(f"응답 {i} " + "나" * chars))
    return out


def _long_session(pairs=40):
    """첫 요청 + 긴 대화 + 최신 요청 — 요약 경로 테스트의 표준 픽스처."""
    return [_user("첫 요청"), _assistant("확인")] + _chat(pairs) + [_user("최신 요청 원문"), _assistant("네")]


class TestPolicy(unittest.TestCase):
    def test_defaults_are_staged(self):
        pol = CompressPolicy()
        self.assertLess(pol.prune_at, pol.summary_at)

    def test_summary_never_fires_before_prune(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "asgard-setting-project.json")
            open(path, "w").write('{"compress": {"prune_at": 0.9, "summary_at": 0.5}}')
            pol = policy(root)
            self.assertGreaterEqual(pol.summary_at, pol.prune_at)

    def test_garbage_values_fall_back(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "asgard-setting-project.json")
            open(path, "w").write('{"compress": {"mode": "wat", "prune_at": "nope", "tail_tokens": null}}')
            pol = policy(root)
            self.assertEqual(pol.mode, "full")
            self.assertEqual(pol.prune_at, CompressPolicy().prune_at)
            self.assertEqual(pol.tail_tokens, CompressPolicy().tail_tokens)


class TestPrune(unittest.TestCase):
    def test_prunes_old_tool_results_and_keeps_tail(self):
        msgs = [_user("작업 시작")] + _loop(20)
        out, event = hygiene_and_prune(msgs, tail_tokens=20_000, min_recovery_tokens=1_000)
        self.assertGreater(event["pruned"], 0)
        self.assertGreater(event["recovered"], 0)
        # 최근 출력은 살아 있어야 한다 — 마지막 tool_result 본문 확인
        self.assertNotIn("회수됨", out[-1]["content"][0]["content"])

    def test_below_min_recovery_leaves_history_untouched(self):
        """회수량이 캐시 재작성 값어치에 못 미치면 한 바이트도 안 건드린다."""
        msgs = [_user("q")] + _loop(20)
        out, event = hygiene_and_prune(msgs, tail_tokens=2_000, min_recovery_tokens=10_000_000)
        self.assertIs(out, msgs)
        self.assertEqual(event["recovered"], 0)
        self.assertEqual(event["skipped"], "below_min_recovery")

    def test_original_history_is_not_mutated(self):
        msgs = [_user("q")] + _loop(20)
        snapshot = msgs[2]["content"][0]["content"]
        hygiene_and_prune(msgs, tail_tokens=5_000, min_recovery_tokens=100)
        self.assertEqual(msgs[2]["content"][0]["content"], snapshot)

    def test_openai_tool_role_pruned(self):
        msgs = [_user("q")]
        for i in range(20):
            msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}"}]})
            msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "y" * 8000})
        out, event = hygiene_and_prune(msgs, tail_tokens=10_000, min_recovery_tokens=100)
        self.assertGreater(event["pruned"], 0)
        self.assertIn("회수됨", out[2]["content"])

    def test_images_are_labelled(self):
        msgs = [_user("q")]
        msgs += _loop(10)
        msgs.insert(2, {"role": "user", "content": [{"type": "image", "source": {"data": "z" * 100}}]})
        out, event = hygiene_and_prune(msgs, tail_tokens=5_000, min_recovery_tokens=100)
        self.assertGreater(event["folded"], 0)
        self.assertEqual(out[2]["content"][0]["type"], "text")

    def test_duplicate_outputs_folded_keeping_latest(self):
        body = "same output " + "d" * 5000
        msgs = [_user("q"), _tool_use("a"), _tool_result("a", body), _tool_use("b"), _tool_result("b", body)]
        out, event = hygiene_and_prune(msgs, tail_tokens=1_000_000, min_recovery_tokens=100)
        self.assertGreater(event["folded"], 0)
        self.assertIn("반복", out[2]["content"][0]["content"])
        self.assertEqual(out[4]["content"][0]["content"], body)  # 최신 1건은 보존


class TestCodexPrune(unittest.TestCase):
    def test_function_call_output_pruned(self):
        items = []
        for i in range(30):
            items.append({"type": "function_call", "call_id": f"c{i}", "name": "read", "arguments": "{}"})
            items.append({"type": "function_call_output", "call_id": f"c{i}", "output": "z" * 8000})
        out, recovered = prune_codex_items(items, tail_tokens=10_000, min_recovery_tokens=1_000)
        self.assertGreater(recovered, 0)
        self.assertIn("회수됨", out[1]["output"])
        self.assertEqual(out[-1]["output"], "z" * 8000)

    def test_small_history_untouched(self):
        items = [{"type": "function_call_output", "call_id": "c", "output": "tiny"}]
        out, recovered = prune_codex_items(items, tail_tokens=10_000, min_recovery_tokens=1_000)
        self.assertIs(out, items)
        self.assertEqual(recovered, 0)


class TestToolPairs(unittest.TestCase):
    def test_orphan_tool_result_removed(self):
        msgs = [_user("q"), _tool_result("missing", "출력")]
        self.assertEqual(sanitize_tool_pairs(msgs), [_user("q")])

    def test_orphan_tool_use_removed(self):
        msgs = [_user("q"), _tool_use("t1"), _assistant("끝")]
        out = sanitize_tool_pairs(msgs)
        self.assertEqual([m["role"] for m in out], ["user", "assistant"])
        self.assertEqual(out[1]["content"], "끝")

    def test_matched_pairs_survive(self):
        msgs = [_user("q"), _tool_use("t1"), _tool_result("t1", "출력"), _assistant("끝")]
        self.assertEqual(len(sanitize_tool_pairs(msgs)), 4)

    def test_partial_orphan_blocks_pruned_from_message(self):
        msgs = [
            _user("q"),
            _tool_use("t1"),
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                    {"type": "tool_result", "tool_use_id": "gone", "content": "orphan"},
                ],
            },
        ]
        out = sanitize_tool_pairs(msgs)
        self.assertEqual(len(out[2]["content"]), 1)

    def test_openai_tool_message_orphan_removed(self):
        msgs = [_user("q"), {"role": "tool", "tool_call_id": "gone", "content": "출력"}]
        self.assertEqual(sanitize_tool_pairs(msgs), [_user("q")])


class TestHandoff(unittest.TestCase):
    def test_detect_and_extract(self):
        pair = [{"role": "user", "content": f"{HANDOFF_PREFIX}\n\n## Active Task\n작업"}, _assistant(HANDOFF_ACK)]
        msgs = [_user("첫 요청"), _assistant("네")] + pair + [_user("다음")]
        self.assertTrue(is_handoff(pair[0]))
        body, rest = extract_handoff(msgs)
        self.assertIn("Active Task", body or "")
        self.assertEqual(len(rest), 3)
        self.assertFalse(any(is_handoff(m) for m in rest))

    def test_no_handoff_returns_none(self):
        body, rest = extract_handoff([_user("q"), _assistant("a")])
        self.assertIsNone(body)
        self.assertEqual(len(rest), 2)

    def test_real_user_turn_excludes_handoff(self):
        from asgard.agent.huginn import _is_real_user_turn

        self.assertFalse(_is_real_user_turn({"role": "user", "content": HANDOFF_PREFIX + "\n본문"}))
        self.assertTrue(_is_real_user_turn(_user("진짜 요청")))
        self.assertFalse(_is_real_user_turn(_tool_result("t1", "출력")))


class TestSerialize(unittest.TestCase):
    def test_secrets_redacted(self):
        text = serialize_turns([_user("설정은 api_key=" + "A" * 40 + " 입니다")])
        self.assertNotIn("A" * 40, text)
        self.assertIn("redacted", text)

    def test_thinking_blocks_dropped(self):
        class _Thinking:
            type = "thinking"
            thinking = "내부 사고"

        text = serialize_turns([{"role": "assistant", "content": [_Thinking()]}])
        self.assertNotIn("내부 사고", text)

    def test_input_is_bounded(self):
        msgs = [_user("x" * 200_000) for _ in range(20)]
        self.assertLess(len(serialize_turns(msgs)), 200_000)


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _engine(call=None, window=100_000, **overrides):
    settings: dict[str, Any] = {"min_recovery_tokens": 100, **overrides}
    pol = CompressPolicy(**settings)
    return Huginn(tempfile.mkdtemp(), window, pol, call=call, now=_Clock())


class TestLadder(unittest.TestCase):
    def test_below_prune_threshold_is_noop(self):
        engine = _engine(call=lambda p, m: "요약")
        msgs = [_user("q")] + _loop(20)
        out, event = engine.compress(msgs, context_tokens=1_000)
        self.assertIs(out, msgs)
        self.assertEqual(event, {})

    def test_mode_off_is_noop(self):
        engine = _engine(call=lambda p, m: "요약", mode="off")
        msgs = [_user("q")] + _loop(20)
        out, event = engine.compress(msgs, context_tokens=99_000)
        self.assertIs(out, msgs)

    def test_prune_only_when_it_clears_summary_threshold(self):
        """프룬으로 임계 아래로 내려가면 요약 LLM 은 호출되지 않는다 — 사다리의 요점."""
        calls = []
        engine = _engine(call=lambda p, m: calls.append(p) or "요약", window=200_000)
        msgs = [_user("q")] + _loop(40, body_chars=8000)
        out, event = engine.compress(msgs, context_tokens=int(200_000 * 0.82))
        self.assertEqual(event["tier"], "prune")
        self.assertEqual(calls, [])
        self.assertLess(estimate_tokens(out), estimate_tokens(msgs))

    def test_summary_fires_above_summary_threshold(self):
        summary = "## Active Task\n최신 요청 처리\n\n## Goal\n테스트"
        engine = _engine(call=lambda p, m: summary, window=100_000, tail_tokens=4_000)
        msgs = _long_session()
        out, event = engine.compress(msgs, context_tokens=95_000)
        self.assertEqual(event["tier"], "summary")
        self.assertNotIn("failure", event)
        self.assertTrue(any(is_handoff(m) for m in out))
        self.assertEqual(sum(1 for m in out if is_handoff(m)), 1)
        self.assertLess(estimate_tokens(out), estimate_tokens(msgs))

    def test_compressed_history_alternates_and_pairs_are_intact(self):
        engine = _engine(call=lambda p, m: "## Active Task\n계속", window=100_000, tail_tokens=4_000)
        msgs = _long_session()
        out, _ = engine.compress(msgs, context_tokens=95_000)
        self.assertEqual(out, sanitize_tool_pairs(out))
        roles = [m["role"] for m in out]
        for a, b in zip(roles, roles[1:], strict=False):
            self.assertNotEqual((a, b), ("user", "user"))
            self.assertNotEqual((a, b), ("assistant", "assistant"))

    def test_latest_user_turn_survives_in_tail(self):
        engine = _engine(call=lambda p, m: "## Active Task\n계속", window=100_000, tail_tokens=4_000)
        msgs = _long_session()
        out, _ = engine.compress(msgs, context_tokens=95_000)
        tail_text = " ".join(str(m.get("content")) for m in out if not is_handoff(m))
        self.assertIn("최신 요청 원문", tail_text)

    def test_recompression_updates_instead_of_stacking(self):
        prompts = []

        def call(prompt, _max):
            prompts.append(prompt)
            return "## Active Task\n갱신됨"

        engine = _engine(call=call, window=100_000, tail_tokens=4_000)
        msgs = _long_session()
        out, _ = engine.compress(msgs, context_tokens=95_000)
        out = out + _chat(40, start=100) + [_user("세번째"), _assistant("네")]
        engine.note_usage(95_000)
        out2, event = engine.compress(out, context_tokens=95_000)
        self.assertTrue(event.get("iterative"))
        self.assertIn("EXISTING HANDOFF", prompts[-1])
        self.assertEqual(sum(1 for m in out2 if is_handoff(m)), 1)


class TestGuards(unittest.TestCase):
    def test_summary_failure_preserves_original(self):
        def boom(_p, _m):
            raise RuntimeError("connection reset by peer")

        engine = _engine(call=boom, window=100_000, tail_tokens=4_000)
        msgs = _long_session()
        out, event = engine.compress(msgs, context_tokens=95_000)
        self.assertIs(out, msgs)
        self.assertEqual(event["failure"], "network")
        self.assertTrue(event["aborted"])

    def test_failure_sets_cooldown(self):
        def boom(_p, _m):
            raise RuntimeError("boom")

        engine = _engine(call=boom, window=100_000, tail_tokens=4_000)
        msgs = _long_session()
        engine.compress(msgs, context_tokens=95_000)
        self.assertEqual(engine.summary_blocked(), "cooldown")

    def test_low_savings_marks_ineffective_and_eventually_stops(self):
        big = "설명 " * 200_000  # 요약이 원문만큼 크다 — 캐시만 날리고 얻는 게 없는 경우

        engine = _engine(call=lambda p, m: big, window=100_000, tail_tokens=4_000)
        msgs = _long_session()
        for _ in range(2):
            out, event = engine.compress(msgs, context_tokens=95_000)
            self.assertIs(out, msgs)
            engine._awaiting_usage = False
        self.assertEqual(engine.summary_blocked(), "ineffective")

    def test_awaiting_usage_blocks_immediate_refire(self):
        engine = _engine(call=lambda p, m: "## Active Task\n계속", window=100_000, tail_tokens=4_000)
        msgs = _long_session()
        engine.compress(msgs, context_tokens=95_000)
        self.assertEqual(engine.summary_blocked(), "awaiting_usage")
        engine.note_usage(40_000)
        self.assertEqual(engine.summary_blocked(), "")

    def test_no_caller_degrades_to_prune(self):
        engine = _engine(call=None, window=100_000, tail_tokens=4_000)
        msgs = _long_session()
        out, event = engine.compress(msgs, context_tokens=95_000)
        self.assertEqual(event.get("blocked"), "no_caller")
        self.assertIs(out, msgs)  # 요약이 불가능하면 원본 그대로 — 조용한 손실 없음

    def test_tail_budget_capped_to_quarter_window(self):
        engine = _engine(window=40_000, tail_tokens=200_000)
        self.assertEqual(engine.effective_tail_tokens(), 10_000)

    def test_classify_failure(self):
        # 실제로 오는 예외는 SDK 가 status_code 를 달아 보낸다 — 표준 예외엔 없는 속성이라 흉내낸다
        class _HttpError(RuntimeError):
            status_code = 401

        auth = _HttpError("x")
        self.assertEqual(classify_failure(auth), "auth")
        self.assertEqual(classify_failure(RuntimeError("Connection timed out")), "network")
        self.assertEqual(classify_failure(ValueError("bad json")), "other")


class TestSessionWiring(unittest.TestCase):
    def test_session_exposes_compaction_hooks(self):
        from asgard.agent import session as session_mod

        for name in ("_maybe_compress", "_maybe_compress_codex", "_report_compaction", "_window"):
            self.assertTrue(hasattr(session_mod.AgentSession, name), name)
        self.assertFalse(hasattr(session_mod.AgentSession, "_prune_history"))

    def test_all_client_side_transports_call_compaction(self):
        """anthropic·openai_compat·codex 세 경로 전부 배선돼야 한다 (구 코드의 누락 지점)."""
        src = open(os.path.join(os.path.dirname(__file__), "..", "src", "asgard", "agent", "session.py")).read()
        self.assertEqual(src.count("self._maybe_compress(result)"), 2)
        self.assertIn("self._maybe_compress_codex(pending_input, result)", src)

    def test_caller_is_none_for_engines_that_own_compaction(self):
        from types import SimpleNamespace

        from asgard.agent.huginn import make_caller

        for mode in ("claude_cli", "openai_responses"):
            fake = SimpleNamespace(rp=SimpleNamespace(profile=SimpleNamespace(api_mode=mode)))
            self.assertIsNone(make_caller(fake))


if __name__ == "__main__":
    unittest.main()
