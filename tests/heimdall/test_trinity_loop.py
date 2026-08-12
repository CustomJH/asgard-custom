#!/usr/bin/env python3
"""Trinity 순환 본류 — 해피패스·재시도·ESCALATE·게이트 차단 수리와 증거 판정."""

import json
import os
import unittest
from unittest import mock

from asgard.agent.session import SessionResult
from asgard.i18n import t
from heimdall.harness import (
    CLS_DIRECT,
    CLS_WRITE,
    DONE,
    Base,
    FakeHeimdall,
    FakeSession,
    thinker,
    verifier,
    worker,
)


class TestTrinityLoop(Base):
    def test_happy_path_closes_quest_with_report(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        self.assertIn(t("report_evidence"), out)  # 구조화 보고
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier"])

    def test_noop_quest_observational_verifier_pass_closes(self):
        # 무변경 과업(오분류된 인사 등) — verifier의 트리 관측(git status/diff)만으로 PASS 성립.
        # 종전엔 관측 명령이 전부 trivial로 걸러져 PASS가 영구 무효화되는 교착이었다 (26-07-21 실측).
        h = FakeHeimdall(
            self.root,
            [
                worker(None, self.root),  # 아무 것도 쓰지 않는 no-op work
                verifier("PASS", commands=[{"cmd": "git status --porcelain", "exit_code": 0}]),
            ],
            cls=CLS_WRITE,
        )
        out = h.handle("변경이 필요 없는 요청")
        self.assertIn(DONE, out)
        self.assertNotIn("PASS 무효화", "".join(h.texts))

    def test_pass_invalidation_is_visible_and_recoverable(self):
        # diff가 있는 퀘스트의 관측-only PASS는 여전히 무효 (Goodhart 유지) — 단 무효화 사실이
        # 화면에 표시된다 (사용자가 "PASS 직후 FAIL 재시도"라는 모순 화면을 보지 않게, 판정층 정직성)
        h = FakeHeimdall(
            self.root,
            [
                worker({"w1.txt": "x\n"}, self.root),
                verifier("PASS", commands=[{"cmd": "git status --porcelain", "exit_code": 0}]),  # 무효화
                worker({"w1.txt": "x\n"}, self.root),  # WORKER_RETRY
                verifier("PASS"),  # 실증거(pytest) PASS
            ],
            cls=CLS_WRITE,
        )
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        self.assertIn("PASS 무효화", "".join(h.texts))

    def test_dual_mode_runs_two_readonly_thinkers_then_one_worker(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.thinker_alt]\nprovider = "ollama"\nmodel = "alt-m"\n'
        )
        h = FakeHeimdall(
            self.root,
            [
                thinker("계획 A: 호출자를 먼저 찾는다"),
                thinker("계획 B: 회귀 테스트를 먼저 쓴다"),
                worker({"w1.txt": "x\n"}, self.root),
                verifier("PASS"),
            ],
            cls=CLS_WRITE,
        )
        h.dual_mode = True

        out = h.handle("w1.txt 만들어")

        self.assertIn(DONE, out)
        planners = h.consumed[:2]
        self.assertEqual({s.role for s in planners}, {"thinker", "thinker_alt"})
        self.assertTrue(all(s.readonly for s in planners))
        worker_session = h.consumed[2]
        self.assertEqual(worker_session.role, "worker")
        self.assertIn("계획 A", worker_session.prompt)
        self.assertIn("계획 B", worker_session.prompt)
        self.assertIn("single minimal implementation", worker_session.prompt)

    def test_external_research_reenters_thinker_before_implementation(self):
        research = FakeSession(
            SessionResult(
                text="https://example.com/source — observed fact",
                stop_reason="end_turn",
                commands=[{"cmd": "web_fetch https://example.com/source", "exit_code": 0}],
            ),
            label="worker",
        )
        replanner = thinker("조사 결과에 맞춰 w1.txt를 만든다")
        implementation = worker({"w1.txt": "fact-backed\n"}, self.root)
        h = FakeHeimdall(
            self.root,
            [research, replanner, implementation, verifier("PASS")],
            cls={**CLS_WRITE, "external_research": True},
        )

        out = h.handle("외부 자료를 조사해 근거 기반 w1.txt를 만들어")

        self.assertIn(DONE, out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "thinker", "worker", "verifier"])
        self.assertIn("[ASGARD_RESEARCH]", research.prompt)
        self.assertIn("scrapling-official", research.system)
        self.assertNotEqual(research.cwd, self.root)
        self.assertIn("https://example.com/source — observed fact", replanner.prompt)
        self.assertIn("unverified data", replanner.prompt)

    def test_dual_mode_rejects_same_model_before_opening_quest(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        h.dual_mode = True

        out = h.handle("w1.txt 만들어")

        self.assertIn("서로 다른 Thinker 모델", out)
        self.assertEqual(h.consumed, [])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_close_rejection_cannot_be_reported_as_verified_completion(self):
        import subprocess

        from asgard.agent import heimdall

        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        real_ql = heimdall.ql

        def reject_close(root, *args, **kwargs):
            if args and args[0] == "close":
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="stale close")
            return real_ql(root, *args, **kwargs)

        with mock.patch("asgard.agent.heimdall.trinity.verdict.ql", side_effect=reject_close):
            out = h.handle("w1.txt 만들어")

        self.assertIn("close를 거부했어요", out)
        self.assertNotIn(DONE, out)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))
        self.assertIsNone(h._last_completion)

    def test_prose_artifact_style_failure_forces_worker_retry_before_close(self):
        seq = [
            worker({"guide.md": "혁신적 RAGX는 신뢰성을 보장한다.\n"}, self.root),
            verifier("PASS"),
            worker({"guide.md": "RAGX는 JSON 키를 정렬하는 13줄짜리 Python 도구다.\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "criteria": ["guide.md 작성"]})
        out = h.handle("RAGX 소개를 guide.md에 작성해. 사실: Python 13줄, JSON 키 정렬")
        self.assertIn(DONE, out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier", "worker", "verifier"])
        self.assertIn("Lagom prose invariants", h.consumed[1].system)
        self.assertNotIn("efficiency ladder", h.consumed[1].system)  # 전체 Lagom 주입으로 판정 기준을 흔들지 않는다
        self.assertIn("lagom-style", h.consumed[2].prompt)
        self.assertNotIn("혁신적", open(os.path.join(self.root, "guide.md"), encoding="utf-8").read())

    def test_completed_native_turn_is_retained_and_surfaces_approval_proposal(self):
        from asgard.project_memory import CompletionProposalResult, TurnRetentionResult

        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        with (
            mock.patch(
                "asgard.memory_bridge.find_config",
                return_value=(
                    self.root,
                    {"server": "http://memory", "bank": "demo", "auto_retain_turns": True},
                ),
            ),
            mock.patch(
                "asgard.project_memory.retain_turn", return_value=TurnRetentionResult("retained", "asgard:turn:1")
            ) as retain,
            # 리포 설정 한 줄로는 안 켜진다 — 이 기계의 허가가 따로 있다. 여기서 보는 것은 그
            # 게이트가 아니라 켜졌을 때 턴이 어떻게 흐르는가이므로 판정을 세워 두고 들어간다
            # (게이트 자체는 test_memory_bridge의 TestMachineApprovalGate가 잡는다).
            mock.patch("asgard.memory_bridge.auto_retain_turns_enabled", return_value=True),
            mock.patch("asgard.memory_bridge.is_backend_trusted", return_value=True),
            mock.patch(
                "asgard.project_memory.propose_completion",
                return_value=CompletionProposalResult("proposed", "approval-1", "completion.1", "사용자 승인 제안"),
            ) as propose,
        ):
            out = h.handle("w1.txt 만들어")
        self.assertIn("사용자 승인 제안", out)
        self.assertEqual(retain.call_args.kwargs["user_text"], "w1.txt 만들어")
        self.assertIn(DONE, retain.call_args.kwargs["assistant_text"])
        self.assertTrue(propose.call_args.kwargs["verified"])
        self.assertIn("w1.txt", propose.call_args.kwargs["changed_files"])

    def test_exploring_direct_turn_appends_distill_nudge(self):
        """탐색(커맨드 ≥3)이 있었던 DIRECT 턴 — 실존 경로 인용 시 ingest 승인 넛지가 붙는다."""
        os.makedirs(os.path.join(self.root, "src"), exist_ok=True)
        open(os.path.join(self.root, "src", "app.py"), "w").write("X = 1\n")
        direct = FakeSession(
            SessionResult(
                text="답은 src/app.py 의 X 상수에 있다",
                stop_reason="end_turn",
                commands=[{"cmd": f"grep {i}", "exit_code": 0} for i in range(3)],
            ),
            label="direct",
        )
        h = FakeHeimdall(self.root, [direct], cls=CLS_DIRECT)
        out = h.handle("X 값이 어디 있는지 확인해줘")
        self.assertIn("⠶ 탐색 발견 저장 후보", out)
        self.assertIn('asgard memory ingest "', out)
        self.assertIn("src/app.py", out)
        self.assertIn("--kind reference", out)

    def test_shallow_direct_turn_stays_silent(self):
        """탐색이 없던 DIRECT 턴(커맨드 < 문턱) — 넛지 소음 없음."""
        os.makedirs(os.path.join(self.root, "src"), exist_ok=True)
        open(os.path.join(self.root, "src", "app.py"), "w").write("X = 1\n")
        direct = FakeSession(
            SessionResult(text="답은 src/app.py 에 있다", stop_reason="end_turn", commands=[]),
            label="direct",
        )
        h = FakeHeimdall(self.root, [direct], cls=CLS_DIRECT)
        out = h.handle("X 값이 어디 있는지 확인해줘")
        self.assertNotIn("탐색 발견 저장 후보", out)

    def test_memory_kill_switch_suppresses_distill_nudge(self):
        os.makedirs(os.path.join(self.root, "src"), exist_ok=True)
        open(os.path.join(self.root, "src", "app.py"), "w").write("X = 1\n")
        direct = FakeSession(
            SessionResult(
                text="답은 src/app.py 에 있다",
                stop_reason="end_turn",
                commands=[{"cmd": "grep", "exit_code": 0}] * 3,
            ),
            label="direct",
        )
        h = FakeHeimdall(self.root, [direct], cls=CLS_DIRECT)
        with mock.patch.dict(os.environ, {"ASGARD_MEMORY_INJECT": "off"}):
            out = h.handle("X 값이 어디 있는지 확인해줘")
        self.assertNotIn("탐색 발견 저장 후보", out)

    def test_verifier_escalate_reaches_odin_without_worker_spin(self):
        # ESCALATE 데드스테이트 회귀 방지 — 이전엔 WORKER 폴스루로 12턴 공회전
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("ESCALATE")], cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn("오딘이 정해 주셔야 해요", out)
        self.assertEqual(len(h.consumed), 2)  # ESCALATE 후 추가 역할 턴 없음

    def test_structural_fail_goes_straight_to_replan(self):
        # structural FAIL → 3-strike 없이 THINKER_REPLAN
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="wrong-approach", why="접근 자체가 틀림"),
            thinker("재설계 계획"),
            worker({"w1.txt": "good\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        labels = [s.label for s in h.consumed]
        self.assertEqual(labels, ["worker", "verifier", "thinker", "worker", "verifier"])
        replan = h.consumed[2]
        self.assertIn("Failure history", replan.prompt)
        self.assertIn("wrong-approach", replan.prompt)

    def test_retry_gets_failure_context(self):
        # FAILED/Diagnosis 재디스패치 — 백지 재작업 금지
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", sig="test-fails", why="assert 1==2 실패"),
            worker({"w1.txt": "good\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        retry = h.consumed[2]
        self.assertIn("FAILED: test-fails", retry.prompt)
        self.assertIn("assert 1==2", retry.prompt)

    def test_no_verdict_synthesizes_fail(self):
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            verifier(no_tool=True),
            worker({"w1.txt": "y\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        self.assertIn("no-verdict-submitted", self.quest_log_text())

    def test_evidenceless_pass_becomes_fail(self):
        # 관측 성공 명령 없는 PASS = 무효 — FAIL 합성 + 관측 커맨드만 기록
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            verifier("PASS", observed=False),
            worker({"w1.txt": "y\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        log = self.quest_log_text()
        self.assertIn("no-verification-evidence", log)
        self.assertNotIn('"cmd":"fake"', log.replace(" ", ""))  # 자가보고 commands 미기록

    def test_pass_with_unresolved_failed_verification_command_becomes_fail(self):
        incomplete = verifier("PASS")
        incomplete.result.commands = [
            {"cmd": "python -m pytest tests/test_w1.py -q", "exit_code": 1},
            {"cmd": "python -c \"open('w1.txt')\"", "exit_code": 0},
        ]
        seq = [
            worker({"w1.txt": "present\n"}, self.root),
            incomplete,
            worker({"missing.txt": "expected\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        self.assertIn(DONE, h.handle("w1.txt와 missing.txt 만들어"))
        self.assertIn("unresolved-verification-failure", self.quest_log_text())

    def test_grep_no_match_is_absence_evidence_not_unresolved_failure(self):
        # grep/rg 매치 0건(exit 1)은 '패턴 부재' 확인의 성공 — 미해소 실패로 세면 정당한 PASS가
        # 뒤집혀 Worker 재시도+재검증 2턴이 공짜로 낭비된다 (26-07-23 감사).
        absence = verifier("PASS")
        absence.result.commands = [
            {"cmd": "grep -Fx forbidden w1.txt", "exit_code": 1},
            {"cmd": "rg legacy_symbol", "exit_code": 1},
            {"cmd": "git grep TODO -- w1.txt", "exit_code": 1},
            {"cmd": "grep -Fx present w1.txt", "exit_code": 0},
        ]
        h = FakeHeimdall(self.root, [worker({"w1.txt": "present\n"}, self.root), absence], cls=CLS_WRITE)
        self.assertIn(DONE, h.handle("w1.txt 만들어"))
        self.assertNotIn("unresolved-verification-failure", self.quest_log_text())

    def test_failed_verification_command_is_resolved_by_exact_successful_rerun(self):
        resolved = verifier("PASS")
        resolved.result.commands = [
            {"cmd": "pytest -q", "exit_code": 1},
            {"cmd": "pytest -q", "exit_code": 0},
        ]
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), resolved], cls=CLS_WRITE)
        self.assertIn(DONE, h.handle("w1.txt 만들어"))
        self.assertNotIn("unresolved-verification-failure", self.quest_log_text())

    def test_failed_runner_is_resolved_by_equivalent_runner_success(self):
        # 26-07-22 실측: 격리 클론에 .venv가 없어 `uv run pytest` 환경 실패 → 같은 대상을
        # `python -m pytest`로 통과시켰는데 신원 불일치로 PASS 무효화 → 헛 재시도 턴 전체 소모.
        resolved = verifier("PASS")
        resolved.result.commands = [
            {"cmd": "uv run pytest tests/test_memory.py -q", "exit_code": 1},
            {"cmd": "python -m pytest tests/test_memory.py -q", "exit_code": 0},
        ]
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), resolved], cls=CLS_WRITE)
        self.assertIn(DONE, h.handle("w1.txt 만들어"))
        self.assertNotIn("unresolved-verification-failure", self.quest_log_text())

    def test_failed_runner_with_different_target_stays_unresolved(self):
        different = verifier("PASS")
        different.result.commands = [
            {"cmd": "uv run pytest tests/test_a.py -q", "exit_code": 1},
            {"cmd": "python -m pytest tests/test_b.py -q", "exit_code": 0},
        ]
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            different,
            worker({"w1.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        self.assertIn(DONE, h.handle("w1.txt 만들어"))
        self.assertIn("unresolved-verification-failure", self.quest_log_text())

    def test_truncated_command_collision_does_not_resolve_failed_verification(self):
        collision = verifier("PASS")
        collision.result.commands = [
            {"cmd": "x" * 200, "command_hash": "failed-full-command", "exit_code": 1},
            {"cmd": "x" * 200, "command_hash": "different-success-command", "exit_code": 0},
        ]
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            collision,
            worker({"w1.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        self.assertIn(DONE, h.handle("w1.txt 만들어"))
        self.assertIn("unresolved-verification-failure", self.quest_log_text())

    def test_verify_event_records_harness_observed_commands(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        events = [json.loads(ln) for ln in self.quest_log_text().splitlines() if ln.strip()]
        ver = [e for e in events if e.get("event") == "verify"][-1]
        # 관측만, 자가보고 아님 — 하네스가 본 명령이 그대로 오고 verifier 가 신고한 "fake" 는 없다
        self.assertEqual([c["cmd"] for c in ver["commands"]], ["pytest -q", "python3 -m compileall -q ."])

    def test_gate_same_reason_twice_escalates(self):
        # 무수리 fail-open 위장 제거 — 동일 사유 2회 차단 → 정직한 ESCALATE
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            verifier("PASS"),
            verifier("PASS"),  # 게이트 수리 재검증 턴
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        with mock.patch(
            "asgard.agent.heimdall.trinity.verdict.gate", return_value=(True, "stale PASS — 물리 대조 불일치")
        ):
            out = h.handle("w1.txt 만들어")
        self.assertIn("오딘이 정해 주셔야 해요", out)
        self.assertIn("stale-pass", out)
        self.assertNotIn(DONE, out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier", "verifier"])

    def test_gate_block_then_repair_passes(self):
        # 첫 차단은 수리 턴(재검증)으로 회복 — 보고에 차단 이력 표기
        seq = [worker({"w1.txt": "x\n"}, self.root), verifier("PASS"), verifier("PASS")]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        real_gate = [(True, "stale PASS — 물리 대조 불일치"), (False, "")]
        with mock.patch("asgard.agent.heimdall.trinity.verdict.gate", side_effect=real_gate):
            out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        # 단복수까지 맞춘 표면 — "1 gate blocks" 같은 문장은 사람 글로 읽히지 않는다
        self.assertIn(t("report_unit_block", n=1), out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
