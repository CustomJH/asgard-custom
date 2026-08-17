#!/usr/bin/env python3
"""실행 진입 — 무인 진행과 프롬프트 루프.

실행: uv run pytest tests/agent  (asgard 패키지 임포트 필요 — subprocess가 -m으로 훅 실행)
"""

import json
import os
import unittest
from unittest import mock


class TestHeadlessProceed(unittest.TestCase):
    """무인 승인 해소 계약 — headless에서 승인 대기 무작업 종료 금지."""

    def _tpl(self, name):
        from asgard.templates.roles import ROLE_AGENTS

        return dict(ROLE_AGENTS)[name]

    def test_canon8_headless_proceeds_with_assumptions(self):
        from asgard.templates.agents import agents_md

        md = agents_md("p")
        self.assertIn("in contexts where Odin cannot answer", md)
        self.assertIn("never end on a question or an approval wait", md)

    def test_canon3_reversible_code_change_not_destructive(self):
        from asgard.templates.agents import agents_md

        self.assertIn("Code changes revertible by commit", agents_md("p"))

    def test_trinity_escalate_blocker_only_and_callers_in_scope(self):
        from asgard.templates.agents import agents_md

        md = agents_md("p")
        self.assertIn("ESCALATE is not an approval request", md)
        self.assertIn("is part of the quest, not out of scope", md)  # 깨진 caller 복구 = 범위 안

    def test_thinker_forbids_option_wait(self):
        self.assertIn("No listing options and waiting for approval", self._tpl("asgard-thinker.md"))
        self.assertIn("가정: ...", self._tpl("asgard-thinker.md"))

    def test_verifier_escalate_not_for_approval(self):
        self.assertIn("never for requesting approval or confirmation", self._tpl("asgard-verifier.md"))

    def test_trinity_roles_carry_vertical_slice_and_two_axis_review_contracts(self):
        self.assertIn("red → green vertical slices", self._tpl("asgard-worker.md"))
        self.assertIn("tracer-bullet vertical slice", self._tpl("asgard-thinker.md"))
        verifier = self._tpl("asgard-verifier.md")
        self.assertIn("Spec axis", verifier)
        self.assertIn("Standards axis", verifier)
        self.assertIn("Smells aid judgment", verifier)

    def test_verifier_carries_architecture_lens(self):
        # 아키텍처 검사 상시 항목 (26-07-21) — 경계 넘는 import의 의존 방향 대조 + 정본 포인터
        verifier = self._tpl("asgard-verifier.md")
        self.assertIn("Architecture check (always-on Standards axis item)", verifier)
        self.assertIn("a new circular dependency", verifier)
        self.assertIn("asgard-hlidskjalf", verifier)


class TestRunPrompt(unittest.TestCase):
    """asgard run — headless 단발 실행. Heimdall/preflight을 대역으로 결정론 검증."""

    def setUp(self):
        import io
        import sys as _sys

        from asgard.commands import start as S

        self.S = S
        self._stdout = _sys.stdout
        self._unattended = os.environ.pop("ASGARD_UNATTENDED", None)
        self.out = io.StringIO()
        _sys.stdout = self.out
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        import sys as _sys

        _sys.stdout = self._stdout
        if self._unattended is not None:
            os.environ["ASGARD_UNATTENDED"] = self._unattended
        else:
            os.environ.pop("ASGARD_UNATTENDED", None)

    def _patch(self, result_text="과업 완수 — 보고", tokens=1234, last_response=""):
        import asgard.agent.heimdall as H

        class FakeRP:
            class profile:
                name = "anthropic"

            model = "claude-x"

        class Calls(list):
            dual_states: list[bool]

        calls = Calls()
        calls.dual_states = []

        class FakeHeimdall:
            def __init__(self, rp, root, on_text, on_status=None):
                self.total_tokens = tokens
                self.cache_read_tokens = 0  # 프롬프트 캐시 계측 — json 출력 계약
                self.cache_prompt_tokens = 0
                self.last_response_text = last_response
                on_text("stream-line\n")

            def handle(self, prompt):
                calls.append(("handle", prompt))
                calls.dual_states.append(bool(getattr(self, "dual_mode", False)))
                return result_text

            def resume(self, quest_id=None):
                calls.append(("resume", quest_id))
                return result_text

        mock.patch.object(
            self.S, "preflight", lambda root, provider=None, model=None: ([{"ok": True}], FakeRP())
        ).start()
        mock.patch.object(H, "Heimdall", FakeHeimdall).start()
        return calls

    def test_json_output_and_exit_zero(self):
        self._patch()
        rc = self.S.run_prompt("작업해줘", json_out=True)
        self.assertEqual(rc, 0)
        d = json.loads(self.out.getvalue())
        self.assertEqual(d["result"], "과업 완수 — 보고")

    def test_the_summary_names_the_quest_it_opened(self):
        """소비자가 방금 만들어진 로그를 찾을 길이 없었다 — 시각으로 뒤져 짐작해야 했다.

        퀘스트를 안 연 턴(DIRECT)에는 null 이다: 없는 것을 있는 척하지 않는다."""
        self._patch()
        self.S.run_prompt("작업해줘", json_out=True)
        d = json.loads(self.out.getvalue())
        self.assertIn("quest_id", d)
        self.assertIsNone(d["quest_id"])  # FakeHeimdall 은 퀘스트를 안 연다
        self.assertEqual(d["tokens"], 1234)
        self.assertEqual(os.environ.get("ASGARD_UNATTENDED"), "1")  # Canon 8 headless 신호

    def test_warning_result_exits_one(self):
        self._patch(result_text="⚠ Odin 결정 필요 — 게이트 차단")
        self.assertEqual(self.S.run_prompt("작업해줘", json_out=True), 1)

    def test_dual_flag_reaches_headless_heimdall(self):
        calls = self._patch()

        self.assertEqual(self.S.run_prompt("작업해줘", json_out=True, dual=True), 0)
        self.assertEqual(calls.dual_states, [True])

    def test_json_uses_direct_response_not_empty_stream_sentinel(self):
        self._patch(result_text="", last_response="direct answer")
        self.assertEqual(self.S.run_prompt("읽어줘", json_out=True), 0)
        self.assertEqual(json.loads(self.out.getvalue())["result"], "direct answer")

    def test_preflight_failure_exits_two(self):
        mock.patch.object(
            self.S,
            "preflight",
            lambda root, provider=None, model=None: ([{"ok": False, "name": "k", "detail": "", "fix": ""}], None),
        ).start()
        self.assertEqual(self.S.run_prompt("작업해줘"), 2)

    def _blocked_preflight(self):
        """claude CLI가 없어 막힌 프리플라이트 — 사용자가 실제로 본 그 형상."""
        checks = [
            {"name": "provider", "ok": True, "detail": "Claude Code · haiku", "fix": ""},
            {
                "name": "claude CLI",
                "ok": False,
                "detail": "not found",
                "fix": "https://claude.com/claude-code 설치 후 claude /login",
            },
            {"name": "claude_agent_sdk SDK", "ok": True, "detail": "importable", "fix": ""},
        ]
        mock.patch.object(self.S, "preflight", lambda root, provider=None, model=None: (checks, None)).start()
        return checks

    def test_json_run_answers_json_even_when_preflight_blocks(self):
        """`--json`은 실패에도 JSON이다.

        여태 이 자리가 스튜디오 화면을 망가뜨렸다: 성공하면 JSON, 막히면 색칠된 체크리스트가
        stdout으로 나갔다. 창은 `asgard run --json`을 자식 프로세스로 띄우므로 실패할 때만
        파싱할 것이 없었고, 그래서 터미널용 원문을 결과 칸에 통째로 부었다."""
        self._blocked_preflight()
        self.assertEqual(self.S.run_prompt("작업해줘", json_out=True), 2)
        payload = json.loads(self.out.getvalue())
        self.assertEqual(payload["error"]["code"], "preflight_failed")
        self.assertIn("claude CLI", payload["error"]["message"])
        # 처방이 필드로 온다 — 창이 "그래서 뭘 하면 되나"를 말할 수 있는 근거
        self.assertIn("claude.com/claude-code", payload["error"]["remedy"])
        # 점검표 전량이 들어간다 — 통과분까지 있어야 화면이 무엇을 감췄는지 고를 수 있다
        self.assertEqual(
            [c["name"] for c in payload["error"]["detail"]["checks"]],
            ["provider", "claude CLI", "claude_agent_sdk SDK"],
        )

    def test_blocked_preflight_prints_no_ansi_checklist_under_json(self):
        """JSON 표면에는 사람 말이 섞이지 않는다 — 한 줄이 곧 전부여야 파싱이 선다."""
        self._blocked_preflight()
        self.S.run_prompt("작업해줘", json_out=True)
        printed = self.out.getvalue()
        self.assertNotIn("✘", printed)
        self.assertNotIn("\x1b[", printed)
        self.assertEqual(len([line for line in printed.splitlines() if line.strip()]), 1)

    def test_human_run_still_gets_the_checklist_and_the_remedy(self):
        """터미널은 반대다 — 사람에게는 점검표가 가장 빠른 진단이라 그대로 그린다."""
        self._blocked_preflight()
        self.assertEqual(self.S.run_prompt("작업해줘", json_out=False), 2)
        printed = self.out.getvalue()
        self.assertIn("claude CLI", printed)
        self.assertIn("claude.com/claude-code", printed)
        self.assertNotIn('"error"', printed)

    def test_the_remedy_is_printed_once_beside_the_check_that_needs_it(self):
        """같은 처방을 끝에 한 번 더 적으면, 두 줄 중 어느 쪽이 그 항목의 것인지 다시 짚어야 한다."""
        self._blocked_preflight()
        self.S.run_prompt("작업해줘", json_out=False)
        self.assertEqual(self.out.getvalue().count("claude.com/claude-code"), 1)

    def test_resume_calls_durable_quest_path_without_new_prompt(self):
        calls = self._patch(result_text="resumed")
        self.assertEqual(self.S.run_prompt(None, json_out=True, resume=True, quest_id="native-old"), 0)
        self.assertEqual(calls, [("resume", "native-old")])
        self.assertEqual(json.loads(self.out.getvalue())["result"], "resumed")


if __name__ == "__main__":
    unittest.main(verbosity=1)
