"""소비 상한 게이트 — 계측원·판정·프로토콜.

이 게이트의 존재 이유가 선행 연구의 실패라서(ref/asgard-helios: SubagentStop 페이로드의
usage 를 읽어 89건 전부 null → 상한이 죽은 코드), 테스트의 첫 번째 의무도 계측이다:
**트랜스크립트의 두 레인이 실제로 집계되는가.** 판정만 맞고 계측이 0이면 게이트는 다시 죽는다.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from unittest import mock

from asgard.hooks import budget_guard as bg


def _line(**row) -> str:
    return json.dumps(row) + "\n"


def _assistant(model="claude-opus-5", **usage) -> str:
    return _line(type="assistant", message={"role": "assistant", "model": model, "usage": usage})


def _task(role, model="claude-sonnet-5", **usage) -> str:
    return _line(
        type="user",
        toolUseResult={
            "agentType": role,
            "resolvedModel": model,
            "totalTokens": sum(usage.values()),
            "usage": usage,
        },
    )


def _transcript(*lines: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    handle.write("".join(lines))
    handle.close()
    return handle.name


class TestLedger(unittest.TestCase):
    """계측 — 헬리오스가 죽은 자리."""

    def test_main_lane_is_counted(self):
        path = _transcript(
            _assistant(input_tokens=10, output_tokens=20, cache_creation_input_tokens=30, cache_read_input_tokens=40),
            _assistant(input_tokens=1, output_tokens=2),
        )
        self.addCleanup(os.unlink, path)
        ledger = bg.read_ledger(path)
        self.assertEqual(ledger.main.input, 11)
        self.assertEqual(ledger.main.output, 22)
        self.assertEqual(ledger.main.cache_write, 30)
        self.assertEqual(ledger.main.cache_read, 40)

    def test_agent_lane_is_counted_from_tool_result(self):
        # 헬리오스는 이 데이터를 훅 페이로드에서 찾다 실패했다 — 정본은 디스크다.
        path = _transcript(
            _task("asgard-worker", input_tokens=100, output_tokens=200),
            _task("asgard-worker", input_tokens=1, output_tokens=2),
            _task("asgard-verifier", input_tokens=5, output_tokens=5),
        )
        self.addCleanup(os.unlink, path)
        ledger = bg.read_ledger(path)
        self.assertEqual(ledger.agent_calls, {"asgard-worker": 2, "asgard-verifier": 1})
        self.assertEqual(ledger.agents["asgard-worker"].input, 101)
        self.assertEqual(ledger.agents["asgard-worker"].output, 202)
        self.assertEqual(ledger.agents["asgard-verifier"].output, 5)

    def test_total_spans_both_lanes(self):
        path = _transcript(_assistant(output_tokens=10), _task("asgard-worker", output_tokens=90))
        self.addCleanup(os.unlink, path)
        self.assertEqual(bg.read_ledger(path).total().output, 100)

    def test_agent_call_without_usage_still_counts_the_call(self):
        # 호출은 났는데 usage 가 없으면 비용은 모르지만 **호출 횟수 상한**은 여전히 살아야 한다.
        path = _transcript(_line(type="user", toolUseResult={"agentType": "asgard-worker", "content": "x"}))
        self.addCleanup(os.unlink, path)
        ledger = bg.read_ledger(path)
        self.assertEqual(ledger.agent_calls["asgard-worker"], 1)
        self.assertNotIn("asgard-worker", ledger.agents)

    def test_broken_lines_do_not_lose_the_rest(self):
        path = _transcript(_assistant(output_tokens=10), '{"usage": broken\n', _assistant(output_tokens=5))
        self.addCleanup(os.unlink, path)
        ledger = bg.read_ledger(path)
        self.assertEqual(ledger.main.output, 15)
        self.assertIn("unparsable", ledger.read_error)  # 조용한 절단 금지

    def test_missing_transcript_reports_why(self):
        ledger = bg.read_ledger("/nonexistent/transcript.jsonl")
        self.assertEqual(ledger.total().raw, 0)
        self.assertTrue(ledger.read_error)

    def test_garbage_usage_values_are_ignored(self):
        path = _transcript(
            _line(type="assistant", message={"usage": {"output_tokens": "many", "input_tokens": -5}}),
            _assistant(output_tokens=7),
        )
        self.addCleanup(os.unlink, path)
        ledger = bg.read_ledger(path)
        self.assertEqual(ledger.main.output, 7)
        self.assertEqual(ledger.main.input, 0)


class TestCostUnits(unittest.TestCase):
    def test_cache_read_is_discounted(self):
        """원시 합으로 재면 캐시 읽기가 지표를 지배한다 — 그 구별이 곧 돈이다."""
        cheap = bg.Usage(cache_read=1_000_000)
        pricey = bg.Usage(output=1_000_000)
        self.assertEqual(cheap.raw, pricey.raw)  # 원시로는 같고
        self.assertLess(cheap.cost_units(), pricey.cost_units())  # 가중으로는 다르다
        self.assertEqual(pricey.cost_units() / cheap.cost_units(), 50.0)

    def test_weights_are_overridable_to_raw(self):
        usage = bg.Usage(input=1, output=1, cache_write=1, cache_read=1)
        flat = {"input": 1, "output": 1, "cache_write": 1, "cache_read": 1}
        self.assertEqual(usage.cost_units(flat), usage.raw)


class TestVerdict(unittest.TestCase):
    LIMITS = {
        "session_cost_units": 1000,
        "warn_cost_units": 500,
        "agent_cost_units": 300,
        "agent_calls": 3,
    }

    def _ledger(self, main_out=0, agents=None, calls=None) -> bg.Ledger:
        ledger = bg.Ledger()
        ledger.main.output = main_out
        for role, out in (agents or {}).items():
            ledger.agents.setdefault(role, bg.Usage()).output = out
        ledger.agent_calls.update(calls or {})
        return ledger

    def test_allows_under_every_limit(self):
        self.assertEqual(bg.verdict(self._ledger(main_out=10), self.LIMITS).action, "allow")

    def test_warns_between_thresholds(self):
        result = bg.verdict(self._ledger(main_out=120), self.LIMITS)  # 600 units
        self.assertEqual(result.action, "warn")
        self.assertIn("600", result.message)

    def test_blocks_at_session_ceiling(self):
        result = bg.verdict(self._ledger(main_out=200), self.LIMITS)  # 1000 units
        self.assertEqual(result.action, "block")
        self.assertEqual(result.code, "budget-ceiling")
        self.assertTrue(result.message.startswith("[gate:budget-ceiling]"))

    def test_session_ceiling_counts_agent_spend(self):
        # 서브에이전트가 태운 것도 세션 지출이다 — 레인이 다르다고 면제되지 않는다.
        result = bg.verdict(self._ledger(main_out=100, agents={"w": 100}), self.LIMITS)
        self.assertEqual(result.action, "block")
        self.assertEqual(result.code, "budget-ceiling")

    def test_blocks_role_over_its_own_ceiling(self):
        ledger = self._ledger(agents={"asgard-worker": 60}, calls={"asgard-worker": 1})  # 300 units
        result = bg.verdict(ledger, self.LIMITS, role="asgard-worker")
        self.assertEqual(result.code, "budget-agent-ceiling")
        self.assertIn("asgard-worker", result.message)

    def test_role_ceiling_is_per_role(self):
        ledger = self._ledger(agents={"asgard-worker": 60}, calls={"asgard-worker": 1})
        self.assertEqual(bg.verdict(ledger, self.LIMITS, role="asgard-verifier").action, "allow")

    def test_blocks_repeated_dispatch_of_one_role(self):
        ledger = self._ledger(calls={"asgard-worker": 3})
        result = bg.verdict(ledger, self.LIMITS, role="asgard-worker")
        self.assertEqual(result.code, "budget-agent-calls")

    def test_role_limits_do_not_apply_in_the_main_lane(self):
        ledger = self._ledger(agents={"asgard-worker": 60}, calls={"asgard-worker": 9})
        self.assertEqual(bg.verdict(ledger, self.LIMITS, role="").action, "allow")

    def test_session_ceiling_outranks_role_limits(self):
        ledger = self._ledger(main_out=200, calls={"asgard-worker": 9})
        self.assertEqual(bg.verdict(ledger, self.LIMITS, role="asgard-worker").code, "budget-ceiling")

    def test_zero_and_junk_limits_fall_back_to_defaults(self):
        # 0 이나 문자열을 상한으로 받으면 "모든 것이 초과"가 되어 게이트가 세션을 인질로 잡는다.
        for junk in ({"session_cost_units": 0}, {"session_cost_units": "many"}, {}):
            self.assertEqual(bg.verdict(self._ledger(main_out=10), junk).action, "allow")

    def test_every_gate_code_renders_with_its_params(self):
        for code in bg.GATE_MESSAGES:
            rendered = bg.gate_message(code, spent="1", limit="2", role="r")
            self.assertTrue(rendered.startswith(f"[gate:{code}]"))
            self.assertNotIn("{", rendered)


def _run(payload: dict, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
        mock.patch("sys.stdout", out),
        mock.patch("sys.stderr", err),
        mock.patch("sys.argv", ["hook", *argv]),
    ):
        try:
            bg.main()
        except SystemExit as exc:
            return int(exc.code or 0), out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


class TestHookProtocol(unittest.TestCase):
    """세 클라이언트가 같은 규율을 지되 각자의 스키마로 — 틀린 스키마는 조용한 통과다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(lambda: None)
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        self.over = _transcript(_assistant(output_tokens=10_000_000))
        self.addCleanup(os.unlink, self.over)
        self.under = _transcript(_assistant(output_tokens=1))
        self.addCleanup(os.unlink, self.under)
        # 홈 설정이 테스트 판정에 새지 않게 격리 (실사용자 한도가 섞이면 결과가 기계마다 달라진다)
        home = mock.patch.dict(os.environ, {"HOME": self.root}, clear=False)
        home.start()
        self.addCleanup(home.stop)

    def _payload(self, transcript, **extra):
        return {"cwd": self.root, "transcript_path": transcript, **extra}

    def test_claude_block_is_exit_two_with_stderr(self):
        code, _, err = _run(self._payload(self.over), ["claude-code", "prompt"])
        self.assertEqual(code, 2)
        self.assertIn("[gate:budget-ceiling]", err)

    def test_codex_block_is_exit_two(self):
        code, _, err = _run(self._payload(self.over), ["codex", "prompt"])
        self.assertEqual(code, 2)
        self.assertIn("budget-ceiling", err)

    def test_cursor_prompt_block_uses_continue_false(self):
        # beforeSubmitPrompt 는 permission 스키마가 아니다 — 한 스키마로 밀면 한쪽이 조용히 통과한다.
        code, out, _ = _run(self._payload(self.over), ["cursor", "prompt"])
        self.assertEqual(code, 0)
        self.assertIs(json.loads(out)["continue"], False)

    def test_cursor_task_block_uses_permission_deny(self):
        code, out, _ = _run(self._payload(self.over, tool_input={"subagent_type": "asgard-worker"}), ["cursor", "task"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["permission"], "deny")

    def test_cursor_task_allow_is_explicit(self):
        code, out, _ = _run(
            self._payload(self.under, tool_input={"subagent_type": "asgard-worker"}), ["cursor", "task"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["permission"], "allow")

    def test_cursor_prompt_warn_emits_nothing(self):
        # 주입 통로가 없는 이벤트에 스키마를 내면 훅 전체가 파싱 실패로 죽어 차단까지 사라진다.
        warn = _transcript(_assistant(output_tokens=1_400_000))  # 7M units — warn 대역
        self.addCleanup(os.unlink, warn)
        code, out, _ = _run(self._payload(warn), ["cursor", "prompt"])
        self.assertEqual((code, out), (0, ""))

    def test_codex_warn_uses_hook_specific_output(self):
        warn = _transcript(_assistant(output_tokens=1_400_000))
        self.addCleanup(os.unlink, warn)
        code, out, _ = _run(self._payload(warn), ["codex", "prompt"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_task_action_reads_the_spawn_role(self):
        payload = self._payload(self.under, tool_input={"subagent_type": "asgard-worker"})
        limits = os.path.join(self.root, ".asgard", "asgard-setting-project.json")
        with open(limits, "w", encoding="utf-8") as handle:
            json.dump({"budget": {"agent_calls": 1}}, handle)
        self.addCleanup(os.unlink, limits)
        agents = _transcript(_assistant(output_tokens=1), _task("asgard-worker", output_tokens=1))
        self.addCleanup(os.unlink, agents)
        payload["transcript_path"] = agents
        code, _, err = _run(payload, ["claude-code", "task"])
        self.assertEqual(code, 2)
        self.assertIn("budget-agent-calls", err)


class TestFailOpen(unittest.TestCase):
    """가드가 죽어서 세션이 멈추는 것은 예산 초과보다 나쁘다."""

    def test_unreadable_stdin_allows(self):
        with (
            mock.patch("sys.stdin", io.StringIO("not json")),
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.argv", ["hook", "claude-code", "prompt"]),
        ):
            with self.assertRaises(SystemExit) as ctx:
                bg.main()
            self.assertEqual(int(ctx.exception.code or 0), 0)

    def test_missing_transcript_allows(self):
        code, _, _ = _run({"cwd": os.getcwd(), "transcript_path": "/nope.jsonl"}, ["claude-code", "prompt"])
        self.assertEqual(code, 0)

    def test_env_kill_switch_disables_everything(self):
        over = _transcript(_assistant(output_tokens=10_000_000))
        self.addCleanup(os.unlink, over)
        with mock.patch.dict(os.environ, {"ASGARD_BUDGET": "off"}):
            code, out, err = _run({"cwd": os.getcwd(), "transcript_path": over}, ["claude-code", "prompt"])
        self.assertEqual((code, out, err), (0, "", ""))

    def test_warn_mode_never_blocks(self):
        over = _transcript(_assistant(output_tokens=10_000_000))
        self.addCleanup(os.unlink, over)
        with mock.patch.dict(os.environ, {"ASGARD_BUDGET": "warn"}):
            code, out, _ = _run({"cwd": os.getcwd(), "transcript_path": over}, ["claude-code", "prompt"])
        self.assertEqual(code, 0)
        self.assertIn("budget-ceiling", out)


class TestLimitsConfig(unittest.TestCase):
    def test_project_overrides_global(self):
        home = tempfile.mkdtemp()
        root = tempfile.mkdtemp()
        for base, value in ((home, 111), (root, 222)):
            os.makedirs(os.path.join(base, ".asgard"), exist_ok=True)
        with open(os.path.join(home, ".asgard", "asgard-setting-global.json"), "w", encoding="utf-8") as handle:
            json.dump({"budget": {"session_cost_units": 111}}, handle)
        with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
            json.dump({"budget": {"session_cost_units": 222}}, handle)
        with mock.patch.dict(os.environ, {"HOME": home}):
            self.assertEqual(bg.load_limits(root)["session_cost_units"], 222)

    def test_defaults_survive_a_partial_section(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".asgard"), exist_ok=True)
        with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
            json.dump({"budget": {"warn_cost_units": 5}}, handle)
        with mock.patch.dict(os.environ, {"HOME": tempfile.mkdtemp()}):
            limits = bg.load_limits(root)
        self.assertEqual(limits["warn_cost_units"], 5)
        self.assertEqual(limits["session_cost_units"], bg.DEFAULTS["session_cost_units"])

    def test_defaults_sit_where_the_measurement_says(self):
        """기본 한도의 근거는 381세션 실측 분포다 — 임의의 숫자면 게이트가 오탐으로 죽는다.

        경고는 p90 아래에서 먼저 울리고, 차단은 p95 이상 p99 이하 — 정상 작업의 95% 이상은
        차단을 느끼지 못하고 걸리는 것은 꼬리뿐이다. 숫자를 흔들면 이 테스트가 먼저 깨진다."""
        p90, p95, p99 = 6_271_519, 13_680_984, 24_504_250
        self.assertLessEqual(bg.DEFAULTS["warn_cost_units"], p90)
        self.assertGreaterEqual(bg.DEFAULTS["session_cost_units"], p95)
        self.assertLessEqual(bg.DEFAULTS["session_cost_units"], p99)
        self.assertLess(bg.DEFAULTS["warn_cost_units"], bg.DEFAULTS["session_cost_units"])


if __name__ == "__main__":
    unittest.main()
