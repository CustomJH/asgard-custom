#!/usr/bin/env python3
"""역할 전이 함수 — 다음 역할 판정, 표준 경로, 라우트 사전확률, 무인 승격."""

import json
import os
import subprocess
import time
import unittest

from trinity_base import (
    TrinityBase,
    jout,
)


class TestTransition(TrinityBase):
    def next(self, *flags):
        p = self.qlog("next", *flags)
        self.assertEqual(p.returncode, 0, p.stderr)
        return jout(p)

    def test_destructive_escalates(self):
        self.open_quest()
        self.assertEqual(self.next("--destructive")["next_role"], "ESCALATE_ODIN")

    def test_three_failures_force_replan(self):
        self.open_quest()
        ev = {"role": "worker", "event": "fail", "failure_sig": "x", "failure_count": 3}
        self.qlog("append", stdin=json.dumps(ev))
        self.assertEqual(self.next()["next_role"], "THINKER_REPLAN")

    def test_fail_then_work_reverifies_not_retry(self):
        """FAIL 후 재작업(work)이 오면 재검증 차례 — sticky FAIL이 WORKER_RETRY를 무한 재발화하면 안 된다."""
        self.open_quest()
        self.write("app.py", "print('bad')\n")
        self.verify(verdict="FAIL")
        self.assertEqual(self.next()["next_role"], "WORKER_RETRY")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.assertEqual(self.next()["next_role"], "VERIFIER")

    def test_a_retry_that_changed_nothing_says_so(self):
        """FAIL 뒤 트리를 한 글자도 안 고치고 work 만 적으면 사유가 그 사실을 말한다.

        work 이벤트는 물리 증거를 안 들고 오므로 "고쳤다"는 말만 남는다. 베이스라인은 같은
        diff_hash 기록을 재사용해 같은 판정을 내고, 그 다음 사유는 "연속 FAIL — 접근을
        재설계하라"가 된다 — 원인은 접근이 아니라 아무도 트리를 안 건드린 것이다."""
        self.open_quest()
        self.write("app.py", "print('bad')\n")
        self.verify(verdict="FAIL")
        self.qlog("append", "--role", "worker", "--event", "work")
        frozen = self.next()
        self.assertEqual(frozen["next_role"], "VERIFIER")
        self.assertIn("byte-identical", frozen["why"])

    def test_an_empty_diff_quest_never_claims_the_tree_is_frozen(self):
        """`diff_state` 는 base_ref 가 없는 퀘스트에서 트리를 안 보고 EMPTY 를 돌려준다.

        두 해시가 다 EMPTY 라는 것은 "안 움직였다"의 증거가 아니라 "안 봤다"는 뜻이다.
        거르지 않으면 워커가 무엇을 고쳤든 그 문장이 붙는다."""
        from asgard.hooks.asgard_hooklib.integrity import EMPTY
        from asgard.hooks.asgard_hooklib.summary import frozen_since_fail

        failed = [{"event": "verify", "verdict": "FAIL", "diff_hash": EMPTY}]
        self.assertFalse(frozen_since_fail(failed, True, EMPTY))
        real = [{"event": "verify", "verdict": "FAIL", "diff_hash": "abc123"}]
        self.assertTrue(frozen_since_fail(real, True, "abc123"))

    def test_a_retry_that_edited_the_tree_stays_quiet(self):
        """트리가 움직였으면 그 문장은 안 나온다 — 매 재시도에 붙는 상투구가 되면 못 읽힌다."""
        self.open_quest()
        self.write("app.py", "print('bad')\n")
        self.verify(verdict="FAIL")
        self.write("app.py", "print('fixed')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        moved = self.next()
        self.assertEqual(moved["next_role"], "VERIFIER")
        self.assertNotIn("byte-identical", moved["why"])

    def test_same_sig_fail_streak_forces_replan(self):
        """동종 failure_sig 연속 FAIL 3회 — 이벤트 failure_count 없이도 퀘스트 로그에서 세어 3-strike (Canon 9)."""
        import json as _json

        self.open_quest()
        self.write("app.py", "print('bad')\n")
        for _ in range(3):
            body = {
                "role": "verifier",
                "event": "verify",
                "failure_sig": "same-err",
                "commands": [{"cmd": "python3 app.py", "exit_code": 1}],
            }
            self.qlog("append", "--verdict", "FAIL", stdin=_json.dumps(body))
        self.assertEqual(self.next()["next_role"], "THINKER_REPLAN")
        # 재계획(plan)이 나오면 스트릭 리셋 — REPLAN 무한 루프 방지, 재시도 경로로 복귀
        self.qlog("append", "--role", "thinker", "--event", "plan")
        self.assertNotEqual(self.next()["next_role"], "THINKER_REPLAN")

    def test_heterogeneous_sig_fail_streak_backstop(self):
        """sig가 매번 달라도 연속 FAIL threshold+1 이면 REPLAN — 자유 텍스트 sig 도돌이표 탈출."""
        import json as _json

        self.open_quest()
        self.write("app.py", "print('bad')\n")
        for i in range(4):
            body = {
                "role": "verifier",
                "event": "verify",
                "failure_sig": f"err-{i}",
                "commands": [{"cmd": "python3 app.py", "exit_code": 1}],
            }
            self.qlog("append", "--verdict", "FAIL", stdin=_json.dumps(body))
        self.assertEqual(self.next()["next_role"], "THINKER_REPLAN")

    def test_ambiguous_starts_with_single_worker(self):
        """모호함만으로 순차 Thinker handoff를 만들지 않는다 — Worker가 같은 문맥에서 계획·실행한다."""
        self.open_quest()
        self.assertEqual(self.next("--ambiguous", "--write-expected")["next_role"], "WORKER")

    def test_parallel_request_plans_once_then_works(self):
        self.open_quest()
        self.assertEqual(self.next("--parallel-requested", "--write-expected")["next_role"], "THINKER")
        self.qlog("append", "--role", "thinker", "--event", "plan")
        self.assertEqual(self.next("--parallel-requested", "--write-expected")["next_role"], "WORKER")

    def test_incomplete_ticket_blocks_done_and_close(self):
        self.open_quest()
        self.qlog(
            "append",
            stdin=json.dumps(
                {
                    "role": "thinker",
                    "event": "ticket",
                    "unit": 1,
                    "ticket_status": "todo",
                    "subtask": "unfinished",
                }
            ),
        )
        claimed = self.qlog("ticket-claim", "--unit", "1", "--worker", "still-running")
        self.assertEqual(claimed.returncode, 0)
        self.write("app.py", "print('ok')\n")
        self.verify()
        nxt = self.next()
        self.assertEqual(nxt["next_role"], "WORKER_RETRY")
        self.assertIn("incomplete tickets", nxt["why"])
        self.assertNotEqual(self.qlog("close").returncode, 0)

    def test_concurrent_appends_have_unique_monotonic_turns(self):
        from concurrent.futures import ThreadPoolExecutor

        self.open_quest()

        def append(i):
            return self.qlog(
                "append",
                stdin=json.dumps({"role": "worker", "event": "work", "unit": i, "changed_files": []}),
            )

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(append, range(40)))
        self.assertTrue(all(result.returncode == 0 for result in results))
        path = os.path.join(self.root, ".asgard", "quest", "q1.jsonl")
        events = [json.loads(line) for line in open(path, encoding="utf-8")]
        turns = [event["turn"] for event in events]
        self.assertEqual(turns, list(range(1, len(events) + 1)))

    def test_ticket_claim_is_atomic_and_token_controls_heartbeat_and_finish(self):
        from concurrent.futures import ThreadPoolExecutor

        self.open_quest()
        self.qlog(
            "append",
            stdin=json.dumps(
                {"role": "thinker", "event": "ticket", "unit": 1, "ticket_status": "todo", "subtask": "atomic"}
            ),
        )

        def claim(i):
            return self.qlog(
                "ticket-claim",
                "--unit",
                "1",
                "--worker",
                f"worker-{i}",
                "--lease-seconds",
                "60",
                "--max-attempts",
                "2",
            )

        with ThreadPoolExecutor(max_workers=12) as pool:
            claims = list(pool.map(claim, range(12)))
        winners = [result for result in claims if result.returncode == 0]
        self.assertEqual(len(winners), 1)
        claimed = json.loads(winners[0].stdout)
        token = claimed["claim_token"]
        self.assertTrue(token.startswith("agt_"))
        raw_log = open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")).read()
        self.assertNotIn(token, raw_log)
        self.assertIn("claim_token_hash", raw_log)
        self.assertEqual(claimed["attempt"], 1)
        self.assertNotEqual(
            self.qlog("ticket-heartbeat", "--unit", "1", "--claim-token", "wrong", "--lease-seconds", "60").returncode,
            0,
        )
        self.assertEqual(
            self.qlog("ticket-heartbeat", "--unit", "1", "--claim-token", token, "--lease-seconds", "60").returncode,
            0,
        )
        self.assertEqual(
            self.qlog("ticket-finish", "--unit", "1", "--claim-token", token, "--status", "done").returncode,
            0,
        )
        state = json.loads(self.qlog("state").stdout)
        self.assertEqual(state["tickets"][0]["status"], "done")
        self.assertEqual(state["tickets"][0]["attempt"], 1)

    def test_raw_append_cannot_bypass_ticket_claim_runtime(self):
        self.open_quest()
        todo = self.qlog(
            "append",
            stdin=json.dumps(
                {"role": "thinker", "event": "ticket", "unit": 1, "ticket_status": "todo", "subtask": "safe"}
            ),
        )
        self.assertEqual(todo.returncode, 0)
        bypass = self.qlog(
            "append",
            stdin=json.dumps({"role": "worker", "event": "ticket", "unit": 1, "ticket_status": "done"}),
        )
        self.assertNotEqual(bypass.returncode, 0)
        self.assertIn("ticket runtime", bypass.stderr)
        state = json.loads(self.qlog("state").stdout)
        self.assertEqual(state["tickets"][0]["status"], "todo")

    def test_ticket_recover_requeues_stale_claim_then_blocks_at_retry_budget(self):
        self.open_quest()
        self.qlog(
            "append",
            stdin=json.dumps(
                {"role": "thinker", "event": "ticket", "unit": 1, "ticket_status": "todo", "subtask": "retry"}
            ),
        )
        stale_claim = json.loads(
            self.qlog(
                "ticket-claim",
                "--unit",
                "1",
                "--worker",
                "dead-worker",
                "--lease-seconds",
                "1",
                "--max-attempts",
                "2",
            ).stdout
        )
        time.sleep(1.05)
        expired_heartbeat = self.qlog(
            "ticket-heartbeat",
            "--unit",
            "1",
            "--claim-token",
            stale_claim["claim_token"],
            "--lease-seconds",
            "60",
        )
        self.assertNotEqual(expired_heartbeat.returncode, 0)
        self.assertIn("lease expired", expired_heartbeat.stderr)
        expired_finish = self.qlog(
            "ticket-finish",
            "--unit",
            "1",
            "--claim-token",
            stale_claim["claim_token"],
            "--status",
            "done",
        )
        self.assertNotEqual(expired_finish.returncode, 0)
        self.assertIn("lease expired", expired_finish.stderr)
        recovered = json.loads(self.qlog("ticket-recover").stdout)
        self.assertEqual(recovered["recovered"], [{"unit": 1, "status": "failed"}])
        claim = self.qlog("ticket-claim", "--unit", "1", "--worker", "retry-worker", "--max-attempts", "2")
        self.assertEqual(claim.returncode, 0)
        body = json.loads(claim.stdout)
        self.assertEqual(body["attempt"], 2)
        finished = json.loads(
            self.qlog(
                "ticket-finish",
                "--unit",
                "1",
                "--claim-token",
                body["claim_token"],
                "--status",
                "failed",
                "--error",
                "still broken",
            ).stdout
        )
        self.assertEqual(finished["status"], "blocked")
        state = json.loads(self.qlog("state").stdout)
        self.assertEqual(state["ticket_counts"], {"blocked": 1})
        self.assertIn("retry budget", self.qlog("ticket-claim", "--unit", "1").stderr)

    def test_mode_b_guide_requires_ticketed_parallel_worker_batch(self):
        from asgard.templates.agents import agents_md

        guide = agents_md("demo")
        self.assertIn("Mode B parallel assignment", guide)
        self.assertIn("all in the same assistant message", guide)
        self.assertIn("todo → in_progress", guide)
        self.assertIn("--parallel-requested", guide)
        self.assertIn("[ASGARD_UNIT:<unit-id>]", guide)
        self.assertIn("ticket-claim --unit", guide)
        self.assertIn("ticket-finish --unit", guide)
        self.assertIn("--claim-token", guide)

    def test_fail_minor_retries_structural_replans(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify(verdict="FAIL")
        self.assertEqual(self.next()["next_role"], "WORKER_RETRY")
        self.assertEqual(self.next("--structural")["next_role"], "THINKER_REPLAN")

    def test_pass_with_hash_match_is_done_stale_reverifies(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.assertEqual(self.next()["next_role"], "DONE")
        self.write("app.py", "print('changed')\n")  # PASS 후 변경 → stale
        self.assertEqual(self.next()["next_role"], "VERIFIER")

    def test_external_research_runs_worker_then_thinker_then_implementation(self):
        self.open_quest()
        self.assertEqual(self.next("--ambiguous", "--write-expected")["next_role"], "WORKER")
        self.assertEqual(self.next("--external-research", "--write-expected")["next_role"], "WORKER")
        findings = "https://example.com/source — observed fact"
        self.qlog(
            "append",
            "--role",
            "worker",
            "--event",
            "work",
            stdin=json.dumps({"research_only": True, "research_findings": findings}),
        )
        state = jout(self.qlog("state"))
        self.assertTrue(state["research_pending_plan"])
        self.assertEqual(state["research_findings"], findings)
        self.assertEqual(self.next("--external-research", "--write-expected")["next_role"], "THINKER")
        self.qlog("append", "--role", "thinker", "--event", "plan")
        self.assertEqual(self.next("--external-research", "--write-expected")["next_role"], "WORKER")

    def test_no_write_is_direct_done(self):
        self.open_quest("--no-write")
        self.assertEqual(self.next()["next_role"], "DIRECT_DONE")

    def test_small_write_goes_worker_micro(self):
        self.open_quest()
        out = self.next("--write-expected")
        self.assertEqual((out["next_role"], out["verify_level"]), ("WORKER", "micro"))

    def test_sensitive_write_starts_worker_but_keeps_full_verification(self):
        self.policy(verify_level="high")  # 위험 축 승격 레인 — 기본 low 는 micro 로 고정한다
        self.open_quest()
        self.write("hooks/deploy.py", "x = 1\n")  # sensitive path
        out = self.next()
        self.assertEqual((out["next_role"], out["verify_level"]), ("WORKER", "full"))

    def test_verify_level_setting_decides_the_escalation(self):
        """설정 세 단계 — low 는 승격 없음, high 는 위험 축에서만, full 은 축과 무관하게 full."""
        self.open_quest()
        self.write("hooks/deploy.py", "x = 1\n")  # sensitive path
        for level, expected in (("low", "micro"), ("high", "full"), ("full", "full"), ("nonsense", "micro")):
            self.policy(verify_level=level)
            self.assertEqual(self.next("--write-expected")["verify_level"], expected, level)

    def test_verify_level_full_promotes_a_trivial_change(self):
        """full 은 게이트-우선 레인도 닫는다 — 어차피 micro PASS 는 completion_decision 이 되돌린다."""
        self.policy(verify_level="full", baseline_checks=["python3 -c pass"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        out = self.next()
        self.assertEqual((out["next_role"], out["verify_level"]), ("VERIFIER", "full"))

    def test_micro_pass_on_sensitive_is_not_done(self):
        """전이·close는 gate와 같은 판정을 내야 한다 — micro PASS로 DONE 이면 Stop에서 차단당한다."""
        self.policy(verify_level="high")
        self.open_quest()
        self.write("hooks/deploy.py", "x = 1\n")
        self.verify(level="micro")
        self.assertEqual(self.next()["next_role"], "VERIFIER")
        self.assertEqual(self.qlog("close").returncode, 1)  # gate가 막을 상태 → close 거부
        self.verify(level="full")
        self.assertEqual(self.next()["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_after_work_goes_verifier(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.assertEqual(self.next()["next_role"], "VERIFIER")


class TestStandardTransition(TrinityBase):
    """안전한 소형 write는 baseline 우선, 위험 신호가 있으면 독립 Verifier로 승격한다."""

    def commit_all(self, msg="c"):
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", msg], check=True)

    def work(self):
        self.qlog("append", "--role", "worker", "--event", "work")

    def nxt(self, *flags):
        return jout(self.qlog("next", "--write-expected", *flags))

    def test_work_routes_baseline_when_behavior_tests_exist(self):
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.write("tests/test_app.py", "def test_ok():\n    assert True\n")
        self.work()
        self.assertEqual(self.nxt()["next_role"], "BASELINE_VERIFY")

    def test_write_expected_empty_diff_requires_verifier_and_rejects_baseline(self):
        self.open_quest()
        self.work()
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")
        vb = self.qlog("verify-baseline", "--write-expected")
        self.assertEqual(vb.returncode, 1)
        self.assertEqual(json.loads(vb.stderr)["next_role"], "VERIFIER")

    def test_unflagged_empty_diff_keeps_tree_observation_path(self):
        self.open_quest()
        self.work()
        self.assertEqual(jout(self.qlog("next"))["next_role"], "BASELINE_VERIFY")
        self.assertEqual(jout(self.qlog("verify-baseline"))["verdict"], "PASS")

    def test_role_dispatch_always_keeps_the_llm_verifier_on_a_small_write(self):
        """저장소마다 판정자가 떴다 안 떴다 하는 원인이 이 임계값이다 — always 가 그것을 끈다."""
        self.policy(baseline_checks=["python3 -m pytest -q"], role_dispatch="always")
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.write("tests/test_app.py", "def test_ok():\n    assert True\n")
        self.work()
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")

    def test_role_dispatch_typo_falls_back_to_auto(self):
        """설정 오타 하나가 전이를 바꾸면 안 된다 (fail-open)."""
        self.policy(baseline_checks=["python3 -m pytest -q"], role_dispatch="ALWAYS!")
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.write("tests/test_app.py", "def test_ok():\n    assert True\n")
        self.work()
        self.assertEqual(self.nxt()["next_role"], "BASELINE_VERIFY")

    def test_compile_only_check_keeps_llm_verifier(self):
        self.policy(baseline_checks=["python3 -m compileall -q ."])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.work()
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")

    def test_no_checks_falls_back_to_llm_verifier(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.work()
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")

    def test_green_baseline_closes_safe_small_write(self):
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.write("tests/test_app.py", "def test_ok():\n    assert True\n")
        self.work()
        vb = self.qlog("verify-baseline")
        self.assertEqual(vb.returncode, 0)
        self.assertEqual(jout(vb)["verdict"], "PASS")
        self.assertEqual(self.nxt()["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_red_retries_worker_then_two_reds_escalate(self):
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.write("tests/test_app.py", "def test_red():\n    assert False\n")
        self.work()
        vb = jout(self.qlog("verify-baseline"))
        self.assertEqual(vb["verdict"], "FAIL")
        self.assertEqual(self.nxt()["next_role"], "WORKER_RETRY")
        self.work()
        self.qlog("verify-baseline")
        n = self.nxt()  # red 2회 — threshold(3) 전 선제 Trinity 승격
        self.assertEqual(n["next_role"], "THINKER_REPLAN")
        self.assertIn("promoting", n["why"])

    def test_signature_change_escalates_to_llm_verifier(self):
        self.write("lib.py", "def foo(a):\n    return a\n")
        self.write("tests/test_ok.py", "def test_ok():\n    assert True\n")
        self.commit_all()
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.open_quest()
        self.write("lib.py", "def foo(a, b):\n    return a\n")  # 시그니처 변경 = 숨은-caller 리스크
        self.work()
        self.assertTrue(jout(self.qlog("state"))["sig_risk"])
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")
        vb = self.qlog("verify-baseline")
        self.assertEqual(vb.returncode, 1)
        self.assertEqual(json.loads(vb.stderr)["next_role"], "VERIFIER")

    def test_body_edit_is_not_signature_risk(self):
        self.write("lib.py", "def foo(a):\n    value = a\n    return value\n")
        self.write("tests/test_lib.py", "from lib import foo\n\ndef test_foo():\n    assert foo(1) in (1, 2)\n")
        self.commit_all()
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.open_quest()
        self.write("lib.py", "def foo(a):\n    value = a + 1\n    return value\n")  # 내부 계산만 변경
        self.work()
        self.assertFalse(jout(self.qlog("state"))["sig_risk"])
        self.assertEqual(self.nxt()["next_role"], "BASELINE_VERIFY")

    def test_return_shape_change_escalates_to_llm_verifier(self):
        self.write("lib.py", "def foo(a):\n    return {'value': a}\n")
        self.commit_all()
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.open_quest()
        self.write("lib.py", "def foo(a):\n    return Config(value=a)\n")
        self.work()
        self.assertTrue(jout(self.qlog("state"))["sig_risk"])
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")

    def test_sensitive_path_escalates_to_llm_verifier(self):
        self.policy(baseline_checks=["true"])
        self.open_quest()
        self.write("hooks/h.py", "x = 1\n")  # sensitive 세그먼트 → 게이트-우선 부적격
        self.work()
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")

    def test_ambiguous_excluded_from_gate_first(self):
        # 모호 과업은 게이트-우선 부적격 — plan 충족 후에도 work 다음은 LLM VERIFIER
        self.policy(baseline_checks=["true"])
        self.open_quest()
        self.qlog("append", "--role", "thinker", "--event", "plan")
        self.write("app.py", "print('ok')\n")
        self.work()
        self.assertEqual(self.nxt("--ambiguous")["next_role"], "VERIFIER")

    def test_added_tests_do_not_escalate(self):
        # 스모크 벤치 발견 — 잠금 테스트 추가가 big 오판을 만들면 게이트-우선이 무력화된다
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.write("test_a.py", "def test_a(): assert True\n")
        self.write("test_b.py", "def test_b(): assert True\n")  # changed 3파일 — non-test는 1파일
        self.work()
        self.assertEqual(self.nxt()["next_role"], "BASELINE_VERIFY")
        self.assertEqual(jout(self.qlog("verify-baseline"))["verdict"], "PASS")
        self.assertEqual(self.nxt()["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)
        self.assertNotEqual(jout(self.gate()).get("decision"), "block")

    def test_large_rewrite_escalates_even_without_sig_change(self):
        # 벤치에서 발견된 결함 — def 무변경 리라이트(+52/-11)가 caller를 깨고도 소형 판정돼 close 됨
        self.policy(baseline_checks=["true"])
        self.open_quest()
        self.write("app.py", "\n".join(f"x{i} = {i}" for i in range(30)) + "\n")  # 30 라인 > 상한 25
        self.work()
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")

    def test_deleted_test_escalates_to_llm_verifier(self):
        self.write("tests/test_app.py", "def test_a(): pass\n")
        self.commit_all()
        self.policy(baseline_checks=["true"])
        self.open_quest()
        os.remove(os.path.join(self.root, "tests", "test_app.py"))  # anti-Goodhart — 게이트-우선 부적격
        self.write("app.py", "print('ok')\n")
        self.work()
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")

    def test_verify_baseline_without_checks_errors(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.work()
        p = self.qlog("verify-baseline")
        self.assertEqual(p.returncode, 1)  # 판정 불가 — LLM Verifier 폴백 지시

    def test_verify_baseline_before_work_is_rejected(self):
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.open_quest()
        p = self.qlog("verify-baseline")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stderr)["next_role"], "WORKER")


class TestRoutePriors(TrinityBase):
    """Bayesian-lite — task-class 게이트-red 이력(과반)이 승격 문턱을 2→1로 하향."""

    def priors(self, **classes):
        os.makedirs(os.path.join(self.root, ".asgard", "state"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "state", "route-priors.json"), "w") as f:
            json.dump({"schema": 1, "classes": classes}, f)

    def one_red(self):
        """게이트-우선 적격 상태에서 baseline red 1회까지 진행."""
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.write("tests/test_app.py", "def test_red():\n    assert False\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.qlog("verify-baseline")

    def nxt(self, *flags):
        return jout(self.qlog("next", "--write-expected", *flags))

    def test_red_majority_promotes_on_first_red(self):
        self.priors(standard={"n": 3, "red": 2})
        self.one_red()
        n = self.nxt("--task-class", "standard")
        self.assertEqual(n["next_role"], "THINKER_REPLAN")
        self.assertIn("prior", n["why"])

    def test_red_minority_keeps_default_threshold(self):
        self.priors(standard={"n": 3, "red": 1})
        self.one_red()
        self.assertEqual(self.nxt("--task-class", "standard")["next_role"], "WORKER_RETRY")

    def test_no_history_keeps_default_threshold(self):
        self.one_red()
        self.assertEqual(self.nxt("--task-class", "standard")["next_role"], "WORKER_RETRY")

    def test_other_class_history_does_not_bleed(self):
        self.priors(deep={"n": 3, "red": 3})
        self.one_red()
        self.assertEqual(self.nxt("--task-class", "standard")["next_role"], "WORKER_RETRY")

    def test_no_task_class_flag_keeps_default_threshold(self):
        self.priors(standard={"n": 3, "red": 3})
        self.one_red()
        self.assertEqual(self.nxt()["next_role"], "WORKER_RETRY")

    def test_corrupt_priors_file_fails_open(self):
        os.makedirs(os.path.join(self.root, ".asgard", "state"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "state", "route-priors.json"), "w") as f:
            f.write("{broken")
        self.one_red()
        self.assertEqual(self.nxt("--task-class", "standard")["next_role"], "WORKER_RETRY")

    def test_open_records_task_class_in_risk(self):
        self.open_quest("--task-class", "standard")
        ev = json.loads(open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")).readline())
        self.assertEqual(ev["risk"].get("task_class"), "standard")

    def test_update_priors_roundtrip_and_fail_open(self):
        from asgard.hooks.quest_log import load_priors, update_priors

        update_priors(self.root, "standard", red=True)
        update_priors(self.root, "standard", red=False)
        update_priors(self.root, "deep", red=True)
        p = load_priors(self.root)
        self.assertEqual(p["classes"]["standard"], {"n": 2, "red": 1})
        self.assertEqual(p["classes"]["deep"], {"n": 1, "red": 1})
        with open(os.path.join(self.root, ".asgard", "state", "route-priors.json"), "w") as f:
            f.write("{broken")
        update_priors(self.root, "standard", red=True)  # 깨진 파일 위에서도 예외 없이 재시작
        self.assertEqual(load_priors(self.root)["classes"]["standard"], {"n": 1, "red": 1})


class TestUnattendedTransition(TrinityBase):
    """Canon 8 무인 nudge의 전이측 (네이티브 등가) — ESCALATE → 재계획 1회 → 재-ESCALATE 인정."""

    def nxt(self, *flags):
        return jout(self.qlog("next", "--write-expected", *flags))

    def test_unattended_escalate_replan_once_then_honored(self):
        self.open_quest()
        self.write("app.py", "x\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("ESCALATE")
        self.assertEqual(self.nxt()["next_role"], "ESCALATE_ODIN")  # attended는 즉시 에스컬레이션
        self.assertEqual(self.nxt("--unattended")["next_role"], "THINKER_REPLAN")  # 무인 1회 nudge
        self.qlog("append", "--role", "thinker", "--event", "plan")  # nudge 소비 (재계획 기록)
        self.assertEqual(self.nxt("--unattended")["next_role"], "WORKER")  # 실행 재개 (재-에스컬레이션 아님)
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("ESCALATE")
        self.assertEqual(self.nxt("--unattended")["next_role"], "ESCALATE_ODIN")  # 재-ESCALATE = 진짜 블로커


if __name__ == "__main__":
    unittest.main(verbosity=2)
