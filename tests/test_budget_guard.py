"""소비 상한 게이트 — 계측원·판정·프로토콜.

이 게이트의 존재 이유가 선행 연구의 실패라서(ref/asgard-helios: SubagentStop 페이로드의
usage를 읽어 89건 전부 null → 상한이 죽은 코드), 테스트의 첫 번째 의무도 계측이다:
**트랜스크립트의 두 레인이 실제로 집계되는가.** 판정만 맞고 계측이 0이면 게이트는 다시 죽는다.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from asgard.commands.budget import SETTABLE
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
        # 호출은 났는데 usage가 없으면 비용은 모르지만 **호출 횟수 상한**은 여전히 살아야 한다.
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


class _CountingFile:
    """읽은 줄의 바이트 수를 세는 파일 껍데기 — 증분 스캔이 실제로 덜 읽는지 재는 자리."""

    def __init__(self, handle, lines: list, reads: list):
        self._handle, self._lines, self._reads = handle, lines, reads

    def __iter__(self):
        for raw in self._handle:
            self._lines.append(len(raw))
            yield raw

    def read(self, *args):
        body = self._handle.read(*args)
        self._reads.append(len(body))
        return body

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)


class TestIncrementalScan(unittest.TestCase):
    """체크포인트는 같은 값을 덜 읽고 낼 뿐이다 — 집계가 달라지면 상한 판정이 어긋난다.

    꼬리 N줄만 읽는 방법이 오답인 이유가 여기 있다: 앞부분을 놓치면 누계가 실제보다 작아지고,
    게이트는 막아야 할 때 안 막는 쪽으로 틀린다. 그래서 이 묶음의 모든 시험이 증분 결과를
    **전량 스캔과 대조**한다."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, ".asgard", "state"), exist_ok=True)

    def _write(self, path: str, *lines: str) -> None:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("".join(lines))

    def _state(self) -> str:
        return os.path.join(self.root, ".asgard", "state")

    def _snapshot(self, ledger: bg.Ledger) -> tuple:
        fields = ("input", "output", "cache_write", "cache_read")
        return (
            tuple(getattr(ledger.main, name) for name in fields),
            {role: tuple(getattr(usage, name) for name in fields) for role, usage in ledger.agents.items()},
            dict(ledger.agent_calls),
            dict(ledger.models),
            ledger.read_error,
        )

    def _assert_matches_full_scan(self, path: str) -> None:
        self.assertEqual(self._snapshot(bg.read_ledger(path, self.root)), self._snapshot(bg.read_ledger(path)))

    def test_totals_match_a_full_scan_as_the_transcript_grows(self):
        path = _transcript(
            _assistant(input_tokens=10, output_tokens=20, cache_creation_input_tokens=30, cache_read_input_tokens=40),
            _task("asgard-worker", input_tokens=100, output_tokens=200),
        )
        self.addCleanup(os.unlink, path)
        self._assert_matches_full_scan(path)
        for extra in (
            _assistant(output_tokens=7),
            _task("asgard-verifier", input_tokens=3),
            _line(type="user", toolUseResult={"agentType": "asgard-worker", "content": "x"}),
        ):
            self._write(path, extra)
            self._assert_matches_full_scan(path)

    def test_the_second_call_reads_only_the_appended_bytes(self):
        path = _transcript(*[_assistant(output_tokens=n) for n in range(400)])
        self.addCleanup(os.unlink, path)
        first = os.path.getsize(path)
        bg.read_ledger(path, self.root)
        appended = _assistant(output_tokens=5)
        self._write(path, appended)

        lines, reads = [], []
        real_open = open

        def counting(target, *args, **kwargs):
            handle = real_open(target, *args, **kwargs)
            return _CountingFile(handle, lines, reads) if str(target).endswith(".jsonl") else handle

        with mock.patch("builtins.open", counting):
            ledger = bg.read_ledger(path, self.root)
        self.assertEqual(sum(lines), len(appended.encode()))  # 줄 스캔은 새로 붙은 만큼만
        self.assertLessEqual(sum(reads), 4096)  # 나머지는 동일성 지문뿐
        self.assertGreater(first, 10 * sum(lines))  # 전량이면 이만큼 읽었다
        self.assertEqual(ledger.main.output, sum(range(400)) + 5)

    def test_a_shrunken_transcript_is_rescanned_whole(self):
        path = _transcript(*[_assistant(output_tokens=100) for _ in range(20)])
        self.addCleanup(os.unlink, path)
        bg.read_ledger(path, self.root)
        with open(path, "w", encoding="utf-8") as handle:  # 회전·교체 — 오프셋이 파일 크기를 넘는다
            handle.write(_assistant(output_tokens=3))
        self.assertEqual(bg.read_ledger(path, self.root).main.output, 3)
        self._assert_matches_full_scan(path)

    def test_a_replacement_of_the_same_size_is_not_resumed(self):
        path = _transcript(_assistant(output_tokens=111), _assistant(output_tokens=222))
        self.addCleanup(os.unlink, path)
        bg.read_ledger(path, self.root)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_assistant(output_tokens=333) + _assistant(output_tokens=444))
        self.assertEqual(bg.read_ledger(path, self.root).main.output, 777)

    def test_a_corrupt_checkpoint_is_discarded(self):
        path = _transcript(_assistant(output_tokens=42))
        self.addCleanup(os.unlink, path)
        bg.read_ledger(path, self.root)
        mark = os.path.join(self._state(), "budget-" + os.path.basename(path)[: -len(".jsonl")] + ".json")
        self.assertTrue(os.path.exists(mark))
        for junk in ('{"version": 1, "offset": "x"}', '{"version": 99}', "not json", "[]"):
            with open(mark, "w", encoding="utf-8") as handle:
                handle.write(junk)
            with self.subTest(junk=junk):
                self.assertEqual(bg.read_ledger(path, self.root).main.output, 42)

    def test_an_unterminated_last_line_is_counted_but_not_committed(self):
        # 호스트가 쓰는 중인 줄을 확정하면 다음 호출이 나머지를 새 줄로 읽어 반쪽만 센다.
        path = _transcript(_assistant(output_tokens=10))
        self.addCleanup(os.unlink, path)
        half = _assistant(output_tokens=90)
        self._write(path, half[:-1])  # 개행 없는 꼬리
        self.assertEqual(bg.read_ledger(path, self.root).main.output, 100)
        self._write(path, "\n" + _assistant(output_tokens=1))
        self.assertEqual(bg.read_ledger(path, self.root).main.output, 101)
        self._assert_matches_full_scan(path)

    def test_a_tree_without_asgard_gets_no_checkpoint(self):
        bare = tempfile.mkdtemp()
        path = _transcript(_assistant(output_tokens=8))
        self.addCleanup(os.unlink, path)
        self.assertEqual(bg.read_ledger(path, bare).main.output, 8)
        self.assertEqual(os.listdir(bare), [])

    def test_a_broken_line_stays_broken_across_calls(self):
        path = _transcript(_assistant(output_tokens=10), '{"usage": broken\n')
        self.addCleanup(os.unlink, path)
        bg.read_ledger(path, self.root)
        self._write(path, _assistant(output_tokens=5))
        ledger = bg.read_ledger(path, self.root)
        self.assertEqual(ledger.main.output, 15)
        self.assertIn("1 unparsable", ledger.read_error)


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
        # 0이나 문자열을 상한으로 받으면 "모든 것이 초과"가 되어 게이트가 세션을 인질로 잡는다.
        for junk in ({"session_cost_units": 0}, {"session_cost_units": "many"}, {}):
            self.assertEqual(bg.verdict(self._ledger(main_out=10), junk).action, "allow")

    def test_every_gate_code_renders_with_its_params(self):
        for code in bg.GATE_MESSAGES:
            rendered = bg.gate_message(code, spent="1", limit="2", role="r")
            self.assertTrue(rendered.startswith(f"[gate:{code}]"))
            self.assertNotIn("{", rendered)


class TestWarnThresholdIsAShareOfTheCeiling(unittest.TestCase):
    """경고 문턱은 절대값이 아니라 상한의 몫이다.

    절대값이던 때는 상한을 올린 저장소에서 경고가 세션 앞머리에 그대로 남아, 그 뒤 모든 턴이
    "핵심만 끝내고 탐색은 버려라"를 달고 돌았다. 몫이면 상한을 올린 만큼 경고도 따라 올라간다."""

    def test_default_threshold_is_eighty_percent_of_the_ceiling(self):
        self.assertEqual(bg.warn_threshold({}), int(bg.DEFAULTS["session_cost_units"]) * 0.8)

    def test_threshold_follows_a_raised_ceiling(self):
        self.assertEqual(bg.warn_threshold({"session_cost_units": 60_000_000}), 48_000_000)

    def test_an_explicit_threshold_wins(self):
        limits = {"session_cost_units": 60_000_000, "warn_cost_units": 5_000_000}
        self.assertEqual(bg.warn_threshold(limits), 5_000_000)

    def test_junk_falls_back_to_the_share(self):
        # 0·문자열을 문턱으로 받으면 "언제나 경고"가 되어 경고가 신호이기를 그만둔다.
        for junk in ({"warn_cost_units": 0}, {"warn_cost_units": "soon"}):
            self.assertEqual(bg.warn_threshold(junk), int(bg.DEFAULTS["session_cost_units"]) * 0.8)

    def test_verdict_stays_quiet_under_the_share(self):
        ledger = bg.Ledger()
        ledger.main.output = 8_000_000  # 40,000,000 cost units — 기본 상한의 74%
        self.assertEqual(bg.verdict(ledger, {}).action, "allow")

    def test_verdict_warns_over_the_share(self):
        ledger = bg.Ledger()
        ledger.main.output = 9_000_000  # 45,000,000 cost units — 기본 상한의 83%
        result = bg.verdict(ledger, {})
        self.assertEqual(result.action, "warn")
        self.assertIn("83%", result.message)

    def test_the_command_screen_reads_the_same_threshold(self):
        # 화면이 적어 놓은 문턱과 게이트가 울리는 문턱이 갈라지면, 벽에 닿기 전에 보이게 한다는
        # 이 명령의 계약이 깨진다.
        from asgard.commands.budget import _payload

        limits = dict(bg.DEFAULTS)
        payload = json.loads(_payload(bg.Ledger(), limits, 0.0))
        self.assertEqual(payload["warn_cost_units"], round(bg.warn_threshold(limits)))


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
        self.over = _transcript(_assistant(output_tokens=12_000_000))  # 60M units — 기본 상한 54M 초과
        self.addCleanup(os.unlink, self.over)
        self.under = _transcript(_assistant(output_tokens=1))
        self.addCleanup(os.unlink, self.under)
        # 홈 설정이 테스트 판정에 새지 않게 격리 (실사용자 한도가 섞이면 결과가 기계마다 달라진다)
        home = mock.patch.dict(os.environ, {"HOME": self.root}, clear=False)
        home.start()
        self.addCleanup(home.stop)

    def _payload(self, transcript, **extra):
        return {"cwd": self.root, "transcript_path": transcript, **extra}

    def test_claude_prompt_ceiling_injects_instead_of_erasing(self):
        # exit 2는 방금 입력한 프롬프트를 지운다 — 지출은 그대로고 마무리를 지시할 통로만 없어진다.
        code, out, err = _run(self._payload(self.over), ["claude-code", "prompt"])
        self.assertEqual(code, 0)
        self.assertIn("[gate:budget-ceiling]", out)
        self.assertEqual(err, "")

    def test_codex_prompt_ceiling_injects_instead_of_erasing(self):
        code, out, err = _run(self._payload(self.over), ["codex", "prompt"])
        self.assertEqual(code, 0)
        self.assertIn("budget-ceiling", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(err, "")

    def test_cursor_prompt_ceiling_does_not_stop_the_prompt(self):
        # 남은 출력이 continue=False 뿐이고 그것이 곧 지우는 동작이라, Cursor 메인 레인은 조용하다.
        code, out, err = _run(self._payload(self.over), ["cursor", "prompt"])
        self.assertEqual((code, out, err), (0, "", ""))

    def test_claude_task_ceiling_still_denies_the_spawn(self):
        # 스폰 거부는 회복 가능하다 — 도구 호출 하나가 거절되고 모델이 사유를 읽는다.
        payload = self._payload(self.over, tool_input={"subagent_type": "asgard-worker"})
        code, _, err = _run(payload, ["claude-code", "task"])
        self.assertEqual(code, 2)
        self.assertIn("[gate:budget-ceiling]", err)

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
        warn = _transcript(_assistant(output_tokens=9_000_000))  # 45M units — 기본 상한 54M 의 83%
        self.addCleanup(os.unlink, warn)
        code, out, _ = _run(self._payload(warn), ["cursor", "prompt"])
        self.assertEqual((code, out), (0, ""))

    def test_codex_warn_uses_hook_specific_output(self):
        warn = _transcript(_assistant(output_tokens=9_000_000))  # 45M units — 경고 대역
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
        # 상한은 이 시험이 직접 정한다. `os.getcwd()` 를 뿌리로 쓰면 저장소 자신의 설정을 읽어,
        # 사람이 상한을 올린 날 "상한을 넘겼는가"를 묻는 시험이 조용히 반대 답을 낸다.
        root, home = tempfile.mkdtemp(), tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".asgard"), exist_ok=True)
        with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
            json.dump({"budget": {"session_cost_units": 1_000_000}}, handle)
        over = _transcript(_assistant(output_tokens=10_000_000))
        self.addCleanup(os.unlink, over)
        with mock.patch.dict(os.environ, {"ASGARD_BUDGET": "warn", "HOME": home}):
            code, out, _ = _run({"cwd": root, "transcript_path": over}, ["claude-code", "prompt"])
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

        차단은 **p99 이상**이다 — 종전에는 p95~p99 사이였고, 그 상한이 잡은 것은 폭주가 아니라
        긴 정상 세션이었다. 26-08-11 실측: 판정 왕복이 있는 한 세션이 15M 에서 막혔는데 그때 남은
        일은 독립 판정 하나뿐이었고, 배차가 막혀 그 턴이 판정 없이 끝났다(같은 세션이 이어서
        21.5M 을 썼다). 상한의 값은 폭주를 끊는 것인데 판정을 끊으면 게이트가 지키려던 것을
        게이트가 깎는다. 26-08-12 에 기본값을 한 번 더 80% 올려 54M(p99 의 2.2배)에 뒀다 —
        좁히는 쪽은 저장소가 설정으로 언제든 하고, 내장 기본값은 정상 작업을 안 끊는 자리에 둔다.

        위 문턱은 분포가 아니라 안전장치다: 오타 하나로 게이트가 사실상 꺼지는 것을 막을 뿐이라
        p99 의 네 배로 넉넉히 잡는다. 그 사이에서 정확히 어디에 둘지는 저장소가 정한다
        (`asgard budget --set session_cost_units=<n>`).

        경고는 상한의 80% 다. 절대값 6M(p90 아래)이던 때는 상한의 11% 지점부터 경고가 붙어 세션이
        남은 89% 를 "마무리하라"는 지시와 함께 썼다. 몫으로 두면 경고는 실측 상위 5% 대역 위에서
        울리고, 울린 뒤에도 정상 세션 하나(p75)보다 넓은 여유가 차단까지 남는다."""
        p75, p95, p99 = 1_325_794, 13_680_984, 24_504_250
        # DEFAULTS는 enforce("block") 때문에 str|int 표다 — 숫자로 좁혀야 비교가 성립한다.
        ceiling, warn = int(bg.DEFAULTS["session_cost_units"]), bg.warn_threshold({})
        self.assertGreaterEqual(ceiling, p99, "긴 정상 세션을 끊으면 판정이 먼저 죽는다")
        self.assertLessEqual(ceiling, p99 * 4, "상한이 이만큼 높으면 게이트가 꺼진 것과 같다")
        self.assertGreaterEqual(warn, p95, "경고가 이보다 낮으면 정상 세션이 지시를 달고 돈다")
        self.assertGreaterEqual(ceiling - warn, p75, "예고 뒤에 세션 하나만큼은 남아야 한다")
        self.assertLess(warn, ceiling)


class TestTheGateNamesAWayThrough(unittest.TestCase):
    """게이트가 안내하는 처방은 실제로 실행할 수 있어야 한다.

    종전 문구는 `.asgard/asgard-setting-project.json` 을 직접 고치라고 했는데, 통제 표면 가드는
    그 파일을 어느 역할에게도 안 연다 — 하네스가 자기가 막는 편집을 지시하던 자리다 (26-08-05).
    """

    def test_no_gate_message_tells_a_role_to_edit_the_settings_file(self) -> None:
        for code, template in bg.GATE_MESSAGES.items():
            with self.subTest(code=code):
                self.assertNotIn("asgard-setting-project.json", template)

    def test_every_gate_message_names_a_command_that_exists(self) -> None:
        from asgard.commands.budget import SETTABLE

        for code, template in bg.GATE_MESSAGES.items():
            with self.subTest(code=code):
                named = re.findall(r"asgard budget --set ([a-z_]+)=", template)
                self.assertTrue(named, f"{code} 가 처방을 하나도 안 가리킨다")
                for key in named:
                    self.assertIn(key, SETTABLE, f"{code} 가 없는 손잡이를 가리킨다")


class TestBudgetSet(unittest.TestCase):
    """`asgard budget --set` — 게이트가 가리키는 좁은 동사."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        # `.asgard` 를 먼저 만든다 — `_project_root` 는 조상으로 올라가며 이 폴더나 `.git` 을
        # 찾으므로, 없으면 임시 폴더 위에 무엇이 있느냐에 따라 쓰는 자리가 달라진다.
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        self.cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(lambda: os.chdir(self.cwd))

    def _set(self, *args: str) -> tuple[int, dict]:
        from asgard.commands.budget import run_budget_set

        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = run_budget_set(list(args), json_out=True)
        try:
            return code, json.loads(out.getvalue() or "{}")
        except json.JSONDecodeError:
            return code, {}

    def _section(self) -> dict:
        with open(os.path.join(self.root, ".asgard", "asgard-setting-project.json"), encoding="utf-8") as handle:
            return json.load(handle).get("budget") or {}

    def test_it_writes_only_the_named_key(self) -> None:
        code, _ = self._set("session_cost_units=60000000")
        self.assertEqual(code, 0)
        self.assertEqual(self._section(), {"session_cost_units": 60_000_000})

    def test_it_keeps_the_keys_it_was_not_asked_about(self) -> None:
        self._set("warn_cost_units=24000000")
        self._set("session_cost_units=60000000")
        self.assertEqual(self._section(), {"warn_cost_units": 24_000_000, "session_cost_units": 60_000_000})

    def test_the_hook_reads_back_what_the_command_wrote(self) -> None:
        self._set("session_cost_units=60000000", "agent_calls=48")
        limits = bg.load_limits(self.root)
        self.assertEqual(limits["session_cost_units"], 60_000_000)
        self.assertEqual(limits["agent_calls"], 48)

    def test_turning_enforcement_off_is_not_a_handle_this_command_gives(self) -> None:
        # 막 막힌 역할이 자기를 막은 문을 떼는 손잡이는 없다 — 상한을 올리는 것과 다른 결정이다.
        self.assertNotIn("enforce", SETTABLE)
        self.assertEqual(self._set("enforce=off")[0], 2)

    def test_an_unknown_key_is_refused_and_writes_nothing(self) -> None:
        code, payload = self._set("nope=1")
        self.assertEqual(code, 2)
        self.assertIn("nope", payload.get("error", ""))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "asgard-setting-project.json")))

    def test_a_bad_value_is_refused(self) -> None:
        for assignment in (
            "session_cost_units=abc",
            "session_cost_units=0",
            "session_cost_units=-1",
            "session_cost_units=inf",
            "session_cost_units=1e400",
            "session_cost_units",
        ):
            with self.subTest(assignment=assignment):
                self.assertEqual(self._set(assignment)[0], 2)

    def test_an_unreadable_settings_file_is_not_overwritten(self) -> None:
        # `load_project` 는 못 읽는 파일에 빈 dict 로 물러서고 `save_project` 는 섹션을 통째로
        # 교체한다 — 그대로 두면 쉼표 하나가 trinity_policy·paths·agents 를 한 번에 지운다.
        path = os.path.join(self.root, ".asgard", "asgard-setting-project.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        broken = '{"trinity_policy": {"baseline_timeout": 180},}'
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(broken)
        self.assertEqual(self._set("session_cost_units=60000000")[0], 2)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), broken)

    def test_it_writes_where_the_settings_are_actually_read(self) -> None:
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        nested = os.path.join(self.root, "src", "deep")
        os.makedirs(nested)
        os.chdir(nested)
        self._set("session_cost_units=60000000")
        self.assertFalse(os.path.exists(os.path.join(nested, ".asgard")))
        self.assertEqual(bg.load_limits(self.root)["session_cost_units"], 60_000_000)


if __name__ == "__main__":
    unittest.main()
