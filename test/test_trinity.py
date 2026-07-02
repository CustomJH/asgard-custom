#!/usr/bin/env python3
"""Trinity 멀티 검증 (CUS-126 로컬 슬라이스) — 로그·전이 함수·게이트·에스컬레이션 E2E 시나리오.

실제 훅 스크립트를 subprocess 로 실행한다 (임포트가 아니라 배포 형태 그대로) — 사용자 repo 에서
python3 <file> 로 도는 것과 동일 경로. 임시 git repo 를 만들어 시나리오별 워킹트리 상태를 재현한다.

실행: python3 test/test_trinity.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "asgard", "hooks")
QLOG = os.path.abspath(os.path.join(SRC, "quest_log.py"))
GATE = os.path.abspath(os.path.join(SRC, "verifier_gate.py"))
TRACKER = os.path.abspath(os.path.join(SRC, "failure_tracker.py"))
SENTINEL = os.path.abspath(os.path.join(SRC, "write_sentinel.py"))


def run(script, args=None, stdin="", cwd=None, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, script] + (args or []), input=stdin,
                          capture_output=True, text=True, cwd=cwd, env=env, timeout=60)


def jout(p):
    return json.loads(p.stdout) if p.stdout.strip() else {}


class TrinityBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "-C", self.root, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", self.root, "config", "user.name", "t"], check=True)
        self.write("README.md", "hello\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "init"], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, content):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    def qlog(self, *args, stdin=""):
        return run(QLOG, list(args), stdin=stdin, cwd=self.root)

    def gate(self, session="s1"):
        return run(GATE, stdin=json.dumps({"session_id": session, "cwd": self.root,
                                           "hook_event_name": "Stop"}), cwd=self.root)

    def open_quest(self, *extra):
        p = self.qlog("open", "q1", "--criteria", "app.py prints ok", *extra)
        self.assertEqual(p.returncode, 0, p.stderr)
        return jout(p)

    def verify(self, verdict="PASS", level=None, commands=None, session="s1"):
        body = {"role": "verifier", "event": "verify",
                "commands": commands if commands is not None else [{"cmd": "python3 app.py", "exit_code": 0}]}
        args = ["append", "--verdict", verdict, "--session", session]
        if level:
            args += ["--level", level]
        return self.qlog(*args, stdin=json.dumps(body))


class TestQuestLog(TrinityBase):
    def test_schema_16_fields_and_turns(self):
        self.open_quest()
        self.qlog("append", "--role", "worker", "--event", "work")
        lines = open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")).read().splitlines()
        self.assertEqual(len(lines), 2)
        ev = json.loads(lines[1])
        want = {"schema", "quest_id", "session_id", "turn", "ts", "role", "event", "base_ref", "risk",
                "criteria", "changed_files", "diff_hash", "commands", "verdict", "failure_sig", "failure_count"}
        self.assertEqual(want - set(ev), set())
        self.assertEqual([json.loads(l)["turn"] for l in lines], [1, 2])
        self.assertTrue(open(os.path.join(self.root, ".asgard", "quest", "ACTIVE")).read().strip() == "q1")

    def test_verify_computes_diff_hash(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        out = jout(self.verify())
        self.assertEqual(out["verdict"], "PASS")
        self.assertTrue(out["diff_hash"])
        st = jout(self.qlog("state"))
        self.assertTrue(st["pass_hash_match"])
        self.assertIn("app.py", st["changed_files"])

    def test_append_rejects_bad_event_and_verify_without_verdict(self):
        self.open_quest()
        self.assertEqual(self.qlog("append", "--event", "nope").returncode, 2)
        self.assertEqual(self.qlog("append", "--event", "verify").returncode, 2)

    def test_close_requires_pass_or_force(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.assertEqual(self.qlog("close").returncode, 1)  # PASS 없음 → 거부
        self.verify()
        self.assertEqual(self.qlog("close").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))


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

    def test_ambiguous_write_and_research_go_thinker(self):
        self.open_quest()
        self.assertEqual(self.next("--ambiguous", "--write-expected")["next_role"], "THINKER")
        self.assertEqual(self.next("--external-research")["next_role"], "THINKER")

    def test_no_write_is_direct_done(self):
        self.open_quest("--no-write")
        self.assertEqual(self.next()["next_role"], "DIRECT_DONE")

    def test_small_write_goes_worker_micro(self):
        self.open_quest()
        out = self.next("--write-expected")
        self.assertEqual((out["next_role"], out["verify_level"]), ("WORKER", "micro"))

    def test_sensitive_write_requires_thinker_then_full(self):
        self.open_quest()
        self.write("hooks/deploy.py", "x = 1\n")  # sensitive path
        out = self.next()
        self.assertEqual((out["next_role"], out["verify_level"]), ("THINKER", "full"))
        self.qlog("append", "--role", "thinker", "--event", "plan")  # 실제 계획 턴
        self.assertEqual(self.next()["next_role"], "WORKER")

    def test_micro_pass_on_sensitive_is_not_done(self):
        """전이·close 는 gate 와 같은 판정을 내야 한다 — micro PASS 로 DONE 이면 Stop 에서 차단당한다."""
        self.open_quest()
        self.write("hooks/deploy.py", "x = 1\n")
        self.verify(level="micro")
        self.assertEqual(self.next()["next_role"], "VERIFIER")
        self.assertEqual(self.qlog("close").returncode, 1)  # gate 가 막을 상태 → close 거부
        self.verify(level="full")
        self.assertEqual(self.next()["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_after_work_goes_verifier(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.assertEqual(self.next()["next_role"], "VERIFIER")


class TestGate(TrinityBase):
    def blocked(self, p):
        out = jout(p)
        return out.get("decision") == "block", out.get("reason", "")

    def test_no_active_quest_allows(self):
        b, _ = self.blocked(self.gate())
        self.assertFalse(b)

    def test_no_write_trivial_allows(self):
        self.open_quest("--no-write")
        b, _ = self.blocked(self.gate())
        self.assertFalse(b)

    def test_write_without_pass_blocks(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        b, reason = self.blocked(self.gate())
        self.assertTrue(b)
        self.assertIn("PASS", reason)

    def test_write_with_pass_allows(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        b, _ = self.blocked(self.gate())
        self.assertFalse(b)

    def test_escalate_allows_stop(self):
        # Canon 9 — verify:ESCALATE 는 정규 종료: 오딘 보고 세션을 게이트가 인질로 잡지 않는다
        # (CUS-126 E2E S4: ESCALATE 기록에도 3회 헛차단 후 fail-open 에 기대던 마찰의 회귀 방지).
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify(verdict="ESCALATE")
        b, _ = self.blocked(self.gate())
        self.assertFalse(b)

    def test_stale_pass_blocks(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.write("app.py", "print('tampered')\n")  # PASS 후 변경
        b, reason = self.blocked(self.gate())
        self.assertTrue(b)
        self.assertIn("stale", reason)

    def test_pass_without_successful_command_blocks(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify(commands=[{"cmd": "python3 app.py", "exit_code": 1}])
        b, reason = self.blocked(self.gate())
        self.assertTrue(b)
        self.assertIn("증거", reason)

    def test_no_criteria_blocks(self):
        p = self.qlog("open", "q1")  # criteria 없이 open
        self.assertEqual(p.returncode, 0)
        self.write("app.py", "print('ok')\n")
        self.verify()
        b, reason = self.blocked(self.gate())
        self.assertTrue(b)
        self.assertIn("criteria", reason)

    def test_sensitive_micro_pass_blocks_full_allows(self):
        self.open_quest()
        self.write("hooks/deploy.py", "x = 1\n")
        self.verify(level="micro")
        b, reason = self.blocked(self.gate())
        self.assertTrue(b)
        self.assertIn("full", reason)
        self.verify(level="full")
        b, _ = self.blocked(self.gate())
        self.assertFalse(b)

    def test_big_diff_requires_full(self):
        self.open_quest()
        self.write("app.py", "x = 1\n" * 100)  # > 80 lines
        self.verify(level="micro")
        b, _ = self.blocked(self.gate())
        self.assertTrue(b)

    def test_block_cap_escalates_then_allows(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        for _ in range(3):
            b, _ = self.blocked(self.gate())
            self.assertTrue(b)
        p = self.gate()  # 4번째 — Canon 9: 인질극 대신 에스컬레이션
        b, _ = self.blocked(p)
        self.assertFalse(b)
        self.assertIn("Canon 9", p.stderr)

    def test_fail_open_bad_stdin_and_non_git(self):
        p = run(GATE, stdin="not json", cwd=self.root)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), "")
        with tempfile.TemporaryDirectory() as d:  # git repo 아님 + 로그 없음
            p = run(GATE, stdin=json.dumps({"session_id": "s", "cwd": d}), cwd=d)
            self.assertEqual(p.returncode, 0)

    def test_ledger_writes_do_not_perturb_hash(self):
        """.asgard/** 제외 — 로그 append 자체가 diff_hash 를 바꾸면 자기참조로 영원히 불일치."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        for _ in range(5):  # PASS 뒤 로그에 계속 써도 물리 대조는 유지되어야 한다
            self.qlog("append", "--role", "worker", "--event", "work")
        b, _ = self.blocked(self.gate())
        self.assertFalse(b)


class TestFailureEscalation(TrinityBase):
    def test_three_failures_inject_replan_and_log_fail_event(self):
        self.open_quest()
        payload = {"tool_name": "Bash", "session_id": "s1", "cwd": self.root,
                   "tool_response": {"is_error": True, "error": "command not found: foo"}}
        outs = [run(TRACKER, stdin=json.dumps(payload), cwd=self.root) for _ in range(3)]
        self.assertEqual([o.stdout.strip() != "" for o in outs], [False, False, True])
        warn = json.loads(outs[2].stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("THINKER_REPLAN", warn)
        events = [json.loads(l) for l in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"))]
        fails = [e for e in events if e["event"] == "fail"]
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0]["failure_count"], 3)
        # 로그의 fail 이벤트가 전이 함수를 재계획으로 이끈다 (CUS-123 배선의 종점)
        out = jout(self.qlog("next"))
        self.assertEqual(out["next_role"], "THINKER_REPLAN")

    def test_tracker_without_quest_still_warns(self):
        payload = {"tool_name": "Bash", "session_id": "s2", "cwd": self.root,
                   "tool_response": {"is_error": True, "error": "boom"}}
        for _ in range(2):
            run(TRACKER, stdin=json.dumps(payload), cwd=self.root)
        p = run(TRACKER, stdin=json.dumps(payload), cwd=self.root)
        self.assertIn("additionalContext", p.stdout)


class TestQuestEnforcement(TrinityBase):
    """write-sentinel + gate — quest 로그 없이 write 하고 끝내는 우회 경로 봉합 검증."""

    def sentinel(self, rel, session="s1", error=False):
        payload = {"tool_name": "Write", "session_id": session, "cwd": self.root,
                   "tool_input": {"file_path": os.path.join(self.root, rel)},
                   "tool_response": {"is_error": True, "error": "boom"} if error else {"ok": True}}
        return run(SENTINEL, stdin=json.dumps(payload), cwd=self.root)

    def blocked(self, p):
        out = jout(p)
        return out.get("decision") == "block", out.get("reason", "")

    def test_questless_write_blocks_at_stop(self):
        self.write("app.py", "print('ok')\n")
        self.sentinel("app.py")
        b, reason = self.blocked(self.gate())
        self.assertTrue(b)
        self.assertIn("퀘스트 로그가 없습니다", reason)

    def test_reverted_write_allows(self):
        self.sentinel("README.md")  # 기록됐지만 워킹트리는 HEAD 그대로 (되돌린 write)
        b, _ = self.blocked(self.gate())
        self.assertFalse(b)

    def test_failed_write_not_recorded(self):
        self.write("app.py", "print('ok')\n")  # 파일은 dirty 지만 write 는 '실패'로 보고됨
        self.sentinel("app.py", error=True)
        b, _ = self.blocked(self.gate())
        self.assertFalse(b)  # 기록 없음 → orphan 검사 대상 아님

    def test_other_session_writes_do_not_block(self):
        self.write("app.py", "print('ok')\n")
        self.sentinel("app.py", session="other")
        b, _ = self.blocked(self.gate(session="s1"))
        self.assertFalse(b)

    def test_closed_quest_pass_exempts_orphan_check(self):
        """close 직후 Stop — 방금 Verifier 가 검증한 write 를 orphan 으로 오차단하면 안 된다."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.sentinel("app.py")
        self.verify()
        self.assertEqual(self.qlog("close").returncode, 0)  # ACTIVE 제거, LAST 기록
        b, _ = self.blocked(self.gate())
        self.assertFalse(b)
        self.write("app.py", "print('more')\n")  # close 후 추가 write → 다시 검증 필요
        b, reason = self.blocked(self.gate())
        self.assertTrue(b)

    def test_asgard_paths_ignored(self):
        self.sentinel(".asgard/quest/q1.jsonl")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "writes-s1.json")))


class TestFullLoopE2E(TrinityBase):
    """CUS-126 시나리오 1 — 정상 경로 전체 루프: open → (전이) → work → verify PASS → gate allow → close."""

    def test_happy_path(self):
        self.open_quest()
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "WORKER")
        self.write("app.py", "print('ok')\n")  # [Worker]
        self.qlog("append", "--role", "worker", "--event", "work",
                    stdin=json.dumps({"commands": [{"cmd": "python3 app.py", "exit_code": 0}]}))
        self.assertEqual(jout(self.qlog("next"))["next_role"], "VERIFIER")
        self.verify()  # [Verifier] PASS + diff_hash 자동
        self.assertEqual(jout(self.qlog("next"))["next_role"], "DONE")
        b = jout(self.gate())
        self.assertNotEqual(b.get("decision"), "block")
        self.assertEqual(self.qlog("close").returncode, 0)
        events = [json.loads(l) for l in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"))]
        self.assertEqual([e["event"] for e in events], ["plan", "work", "verify"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
