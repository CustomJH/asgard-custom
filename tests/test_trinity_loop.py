#!/usr/bin/env python3
"""루프 전체 — E2E 시나리오, 무인 진행, 정책 미러, 네이티브 루프의 메모리 손질."""

import json
import os
import unittest
from unittest import mock

from trinity_base import (
    GATE,
    UCTX,
    TrinityBase,
    jout,
    run,
)


class TestFullLoopE2E(TrinityBase):
    """정상 경로 전체 루프: open → (전이) → work → verify PASS → gate allow → close."""

    def test_happy_path(self):
        self.open_quest()
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "WORKER")
        self.write("app.py", "print('ok')\n")  # [Worker]
        self.qlog(
            "append",
            "--role",
            "worker",
            "--event",
            "work",
            stdin=json.dumps({"commands": [{"cmd": "python3 app.py", "exit_code": 0}]}),
        )
        self.assertEqual(jout(self.qlog("next"))["next_role"], "VERIFIER")
        self.verify()  # [Verifier] PASS + diff_hash 자동
        self.assertEqual(jout(self.qlog("next"))["next_role"], "DONE")
        b = jout(self.gate())
        self.assertNotEqual(b.get("decision"), "block")
        self.assertEqual(self.qlog("close").returncode, 0)
        events = [json.loads(ln) for ln in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"))]
        self.assertEqual([e["event"] for e in events], ["plan", "work", "verify", "quest_closed"])


class TestUnattended(TrinityBase):
    """무인 진행 강제층 — 감지 주입 + 시도-없는 ESCALATE 1회 차단."""

    def gate_pm(self, mode, session="s1"):
        return run(
            GATE,
            stdin=json.dumps(
                {"session_id": session, "cwd": self.root, "hook_event_name": "Stop", "permission_mode": mode}
            ),
            cwd=self.root,
        )

    def test_context_injected_only_for_automation_modes(self):
        for mode, expect in (("bypassPermissions", True), ("dontAsk", True), ("default", False), ("plan", False)):
            p = run(UCTX, stdin=json.dumps({"permission_mode": mode, "user_prompt": "x"}), cwd=self.root)
            self.assertEqual(p.returncode, 0)
            self.assertEqual("Unattended session" in p.stdout, expect, mode)

    def test_context_env_override(self):
        p = run(
            UCTX,
            stdin=json.dumps({"permission_mode": "default"}),
            cwd=self.root,
            env_extra={"ASGARD_UNATTENDED": "1"},
        )
        self.assertIn("Unattended session", p.stdout)

    def test_workless_escalate_blocked_once_when_unattended(self):
        self.open_quest()
        self.qlog("append", "--role", "thinker", "--event", "plan", stdin=json.dumps({"criteria": ["c"]}))
        self.verify(verdict="ESCALATE", commands=[])
        b = jout(self.gate_pm("bypassPermissions"))
        self.assertEqual(b.get("decision"), "block")
        self.assertIn("가정:", b.get("reason", ""))
        # 2번째 Stop — 마커 존재 → 진짜 블로커로 인정, 통과
        self.assertNotEqual(jout(self.gate_pm("bypassPermissions")).get("decision"), "block")

    def test_workless_escalate_allowed_when_attended(self):
        self.open_quest()
        self.verify(verdict="ESCALATE", commands=[])
        self.assertNotEqual(jout(self.gate()).get("decision"), "block")  # permission_mode 없음 = 인터랙티브

    def test_escalate_after_work_attempt_passes_gate(self):
        self.open_quest()
        self.write("app.py", "print('wip')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify(verdict="ESCALATE", commands=[])
        self.assertNotEqual(jout(self.gate_pm("bypassPermissions")).get("decision"), "block")


class TestPolicyMirror(unittest.TestCase):
    """정책 3중 미러 정합 — 템플릿 시드가 훅 정본을 그대로 실어야 4모드(네이티브·CC·Codex·Cursor)가
    같은 기준으로 판정한다. load_policy는 파일 키가 내장값을 통째로 덮으므로(update) 시드 드리프트는
    패치 무효화와 같다 (26-07-23 sensitive_paths 14→22 드리프트 회귀 방어)."""

    def test_template_seed_equals_quest_log_default(self):
        from asgard.hooks.quest_log import DEFAULT_POLICY
        from asgard.templates.trinity import trinity_policy

        self.assertEqual(json.loads(trinity_policy()), DEFAULT_POLICY)

    def test_project_settings_seed_equals_quest_log_default(self):
        from asgard.hooks.quest_log import DEFAULT_POLICY
        from asgard.templates.trinity import project_settings

        self.assertEqual(json.loads(project_settings())["trinity_policy"], DEFAULT_POLICY)

    def test_verifier_gate_shared_keys_equal_quest_log(self):
        from asgard.hooks import quest_log, verifier_gate

        for key, value in verifier_gate.DEFAULT_POLICY.items():
            self.assertIn(key, quest_log.DEFAULT_POLICY)
            self.assertEqual(value, quest_log.DEFAULT_POLICY[key], key)

    def test_verifier_gate_shares_quest_logs_helpers(self):
        """두 훅이 같은 이름으로 품던 판정 함수 — 이제 같은 객체다.

        사본이던 시절 이 시험은 '같은 입력에 같은 답'을 봤다. 그 대조는 통과하면서도 사본을
        사본으로 남겨 뒀고, 26-08-04 에 새로 복제된 넷은 주석으로만 묶여 있었다. 갈라지면
        게이트가 센 diff 해시와 로그가 적은 해시가 달라져 PASS 가 영구 stale 이 된다."""
        from asgard.hooks import quest_log, verifier_gate

        self.assertIs(quest_log.host_session_id, verifier_gate.host_session_id)
        self.assertIs(quest_log.DEFAULT_POLICY, verifier_gate.DEFAULT_POLICY)
        self.assertIs(quest_log.diff_state, verifier_gate.diff_state)

    def test_generated_paths_stop_at_a_segment_boundary(self):
        """산출물 판정의 경계 — 접두사만 겹치는 이름을 산출물로 세면 소스가 해시에서 사라진다."""
        from asgard_hooklib.paths import is_generated

        for path in ("target/debug/app", "build/x.py", "coverage/lcov.info", "src/__pycache__/app.pyc"):
            self.assertTrue(is_generated(path), path)
        for path in ("src/app.py", "notbuild/app.py"):
            self.assertFalse(is_generated(path), path)

    def test_host_session_id_reads_every_client(self):
        from asgard_hooklib.session import host_session_id

        for name in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID", "CURSOR_SESSION_ID", "CODEX_SESSION_ID"):
            with mock.patch.dict(os.environ, {name: "sid-" + name}, clear=True):
                self.assertEqual(host_session_id(), "sid-" + name, name)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(host_session_id())

    def test_pipeline_eligibility_has_one_definition_and_one_ticket_shape(self):
        """조기 검증 적격 판정 — 함수도 하나, 티켓 형상도 하나.

        26-08-06 까지 subagent-gate 는 자기 `verifiable_units` 사본과 자기 티켓 뷰를 갖고 있었고,
        그 뷰는 단위 식별자를 `unit` 으로, 로그 정본(`fold_tickets`)은 `id` 로 적었다. 같은 개념에
        키가 둘이라 이 시험은 한쪽 입력을 손으로 번역해 대조하고 있었다 — 그 번역이 사라졌다."""
        from asgard_hooklib.ledger import fold_tickets, verifiable_units

        from asgard.hooks import subagent_gate

        self.assertIs(subagent_gate.verifiable_units, verifiable_units)
        self.assertIs(subagent_gate.fold_tickets, fold_tickets)

        cases = [
            ([{"id": 1, "status": "done", "files": ["a.py"]}, {"id": 2, "status": "todo", "files": ["b.py"]}], ["1"]),
            # 열린 단위와 파일이 겹치면 done 이어도 아직 못 본다 (같은 파일을 두 판정이 나눠 갖는다)
            (
                [
                    {"id": 1, "status": "done", "files": ["shared.py"]},
                    {"id": 2, "status": "todo", "files": ["shared.py"]},
                ],
                [],
            ),
            # 파일을 안 밝힌 열린 단위가 있으면 겹침을 알 수 없다 → 아무도 조기 검증 못 한다
            ([{"id": 1, "status": "done", "files": ["a.py"]}, {"id": 2, "status": "todo", "files": []}], []),
            # 경로 표기 차이는 겹침을 못 피한다 (`./a.py` == `a.py`)
            (
                [
                    {"id": 1, "status": "done", "files": ["./a.py"]},
                    {"id": 2, "status": "in_progress", "files": ["a.py"]},
                ],
                [],
            ),
        ]
        for tickets, expected in cases:
            self.assertEqual(verifiable_units(tickets), expected, tickets)

        # 게이트가 실제로 먹이는 형상 — 로그 이벤트를 접은 결과가 그대로 들어간다.
        events = [
            {"event": "ticket", "unit": 1, "ticket_status": "done", "changed_files": ["a.py"]},
            {"event": "ticket", "unit": 2, "ticket_status": "todo", "changed_files": ["b.py"]},
        ]
        self.assertEqual(verifiable_units(list(fold_tickets(events).values())), ["1"])


class TestNativeLoopTendsMemory(unittest.TestCase):
    """퀘스트 close 뒤 위그드라실 손질 신호 — 외부 훅에만 있고 네이티브 루프엔 없던 자리.

    같은 사용자의 같은 기억이 어느 호스트로 들어왔느냐에 따라 다른 속도로 자라면 안 된다
    (policy.CLIENT_MODES). 여기서 보는 것은 배선이다: 판정 자체는 test_memory_norn이 본다."""

    @staticmethod
    def _bare_run(out):
        """__init__ 없이 세운 TrinityRun — 손질 배선만 보려는데 루프 전체를 세울 이유가 없다."""
        import types

        from asgard.agent.heimdall.trinity import TrinityRun

        run = TrinityRun.__new__(TrinityRun)
        run._hd = types.SimpleNamespace(root="/repo", on_text=out.append)
        return run

    def _run(self, norn_line, pattern_line, project_line=None):
        out: list[str] = []
        with (
            mock.patch("asgard.memory.norn.wake", return_value=norn_line) as wake,
            mock.patch("asgard.memory.pattern.wake", return_value=pattern_line) as pattern_wake,
            mock.patch("asgard.project_memory.evolve.wake", return_value=project_line) as project_wake,
        ):
            self._bare_run(out)._tend_memory()
        return out, wake, pattern_wake, project_wake

    def test_every_signal_reaches_the_user(self):
        out, wake, pattern_wake, project_wake = self._run("노른 통합 시작", "관측 학습 시작", "2차 진화 시작")
        for call in (wake, pattern_wake, project_wake):
            self.assertEqual(call.call_args[0][0], "/repo")
        for line in ("노른 통합 시작", "관측 학습 시작", "2차 진화 시작"):
            self.assertTrue(any(line in shown for shown in out), line)

    def test_silence_is_the_normal_outcome(self):
        out, *_calls = self._run(None, None, None)
        self.assertEqual(out, [])

    def test_a_broken_signal_never_blocks_quest_close(self):
        out: list[str] = []
        with (
            mock.patch("asgard.memory.norn.wake", side_effect=RuntimeError("boom")),
            mock.patch("asgard.memory.pattern.wake", return_value="관측 학습 시작"),
            mock.patch("asgard.project_memory.evolve.wake", return_value=None),
        ):
            self._bare_run(out)._tend_memory()  # 던지면 퀘스트 종료가 막힌다
        self.assertTrue(any("관측 학습 시작" in line for line in out))  # 성한 신호는 계속 온다


if __name__ == "__main__":
    unittest.main(verbosity=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
