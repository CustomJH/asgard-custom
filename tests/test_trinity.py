#!/usr/bin/env python3
"""Trinity 멀티 검증 (CUS-126 로컬 슬라이스) — 로그·전이 함수·게이트·에스컬레이션 E2E 시나리오.

실제 훅 스크립트를 subprocess 로 실행한다 (임포트가 아니라 배포 형태 그대로) — 사용자 repo 에서
python3 <file> 로 도는 것과 동일 경로. 임시 git repo 를 만들어 시나리오별 워킹트리 상태를 재현한다.

실행: uv run pytest tests/test_trinity.py
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
UCTX = os.path.abspath(os.path.join(SRC, "unattended_context.py"))
SUBGATE = os.path.abspath(os.path.join(SRC, "subagent_gate.py"))


def run(script, args=None, stdin="", cwd=None, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, script] + (args or []),
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=60,
    )


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
        return run(
            GATE, stdin=json.dumps({"session_id": session, "cwd": self.root, "hook_event_name": "Stop"}), cwd=self.root
        )

    def open_quest(self, *extra):
        p = self.qlog("open", "q1", "--criteria", "app.py prints ok", *extra)
        self.assertEqual(p.returncode, 0, p.stderr)
        return jout(p)

    def policy(self, **kw):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "trinity-policy.json"), "w") as f:
            json.dump(kw, f)

    def verify(self, verdict="PASS", level=None, commands=None, session="s1"):
        body = {
            "role": "verifier",
            "event": "verify",
            "commands": commands if commands is not None else [{"cmd": "python3 app.py", "exit_code": 0}],
        }
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
        want = {
            "schema",
            "quest_id",
            "session_id",
            "turn",
            "ts",
            "role",
            "event",
            "base_ref",
            "risk",
            "criteria",
            "changed_files",
            "diff_hash",
            "commands",
            "verdict",
            "failure_sig",
            "failure_count",
        }
        self.assertEqual(want - set(ev), set())
        self.assertEqual([json.loads(ln)["turn"] for ln in lines], [1, 2])
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

    def test_close_map_nudge_on_structural_change(self):
        # 지도 도입(.asgard/map 존재) + 신규 파일(untracked A) → close 가 지도 갱신 리마인드.
        # .asgard/·닷디렉토리 하위는 소스 구조가 아니므로 넛지 대상에서 제외된다.
        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        self.open_quest()
        self.write("src/new_module.py", "x = 1\n")
        self.write(".claude/hooks/dummy.py", "y = 1\n")  # 닷디렉토리 — 제외돼야 함
        self.verify(level="full")  # hooks 는 민감 경로 — full-verify 없이는 close 가 거부된다
        out = jout(self.qlog("close"))
        self.assertEqual(out["closed"], "q1")
        self.assertIn("A src/new_module.py", out["map_update"])
        self.assertNotIn("A .claude/hooks/dummy.py", out["map_update"])
        self.assertIn("map_hint", out)

    def test_close_map_nudge_silent_without_map_or_change(self):
        # 지도 미도입 → 구조 변경이 있어도 침묵 (기존 프로젝트에 강요하지 않는다 — fail-open)
        self.open_quest()
        self.write("src/new_module.py", "x = 1\n")
        self.verify()
        out = jout(self.qlog("close"))
        self.assertNotIn("map_update", out)
        # 지도 도입 + 내용 수정(M)만 → 구조 변경 아님, 침묵
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)  # 신규 파일 흡수 — base 를 깨끗하게
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "absorb"], check=True)
        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        self.qlog("open", "q2", "--criteria", "edit only")
        self.write("README.md", "hello edited\n")
        self.verify()
        out = jout(self.qlog("close", "q2"))
        self.assertNotIn("map_update", out)


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
        """FAIL 후 재작업(work)이 오면 재검증 차례 — sticky FAIL 이 WORKER_RETRY 를 무한 재발화하면 안 된다."""
        self.open_quest()
        self.write("app.py", "print('bad')\n")
        self.verify(verdict="FAIL")
        self.assertEqual(self.next()["next_role"], "WORKER_RETRY")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.assertEqual(self.next()["next_role"], "VERIFIER")

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
        """sig 가 매번 달라도 연속 FAIL threshold+1 이면 REPLAN — 자유 텍스트 sig 도돌이표 탈출."""
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

    def test_ambiguous_plans_once_then_works(self):
        """모호 플래그는 sticky — Thinker 계획(턴2) 후에는 WORKER 로 넘어가야 한다 (plan 무한 루프 방지)."""
        self.open_quest()
        self.assertEqual(self.next("--ambiguous", "--write-expected")["next_role"], "THINKER")
        self.qlog("append", "--role", "thinker", "--event", "plan")  # 실제 계획 턴
        self.assertEqual(self.next("--ambiguous", "--write-expected")["next_role"], "WORKER")

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

    def test_verify_artifacts_do_not_stale_pass(self):
        # s1 라이브 실측 — .gitignore 없는 프로젝트에서 검증 명령이 만든 __pycache__ 가
        # hash 를 바꿔 PASS 를 stale 로 만들던 자기파괴 회귀 방지 (_junk 제외, 양 훅 동일).
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.write("__pycache__/app.cpython-314.pyc", "bytecode")
        self.write(".pytest_cache/v/cache/lastfailed", "{}")
        b, reason = self.blocked(self.gate())
        self.assertFalse(b, reason)

    def test_closed_quest_escalate_allows_stop(self):
        # s1 라이브 실측 — ESCALATE 로 close 된 quest(LAST) + write 흔적 잔존 시
        # orphan 경로가 PASS 만 인정해 Canon 9 정규 종료를 차단하던 회귀 방지.
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify(verdict="ESCALATE")
        self.assertEqual(self.qlog("close").returncode, 0)  # ESCALATE close 인정
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "writes-s1.json"), "w") as f:
            json.dump(["app.py"], f)  # write-sentinel 흔적 — orphan 경로 진입 조건
        b, reason = self.blocked(self.gate())
        self.assertFalse(b, reason)

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
        payload = {
            "tool_name": "Bash",
            "session_id": "s1",
            "cwd": self.root,
            "tool_response": {"is_error": True, "error": "command not found: foo"},
        }
        outs = [run(TRACKER, stdin=json.dumps(payload), cwd=self.root) for _ in range(3)]
        self.assertEqual([o.stdout.strip() != "" for o in outs], [False, False, True])
        warn = json.loads(outs[2].stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("THINKER_REPLAN", warn)
        events = [json.loads(ln) for ln in open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"))]
        fails = [e for e in events if e["event"] == "fail"]
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0]["failure_count"], 3)
        # 로그의 fail 이벤트가 전이 함수를 재계획으로 이끈다 (CUS-123 배선의 종점)
        out = jout(self.qlog("next"))
        self.assertEqual(out["next_role"], "THINKER_REPLAN")

    def test_tracker_without_quest_still_warns(self):
        payload = {
            "tool_name": "Bash",
            "session_id": "s2",
            "cwd": self.root,
            "tool_response": {"is_error": True, "error": "boom"},
        }
        for _ in range(2):
            run(TRACKER, stdin=json.dumps(payload), cwd=self.root)
        p = run(TRACKER, stdin=json.dumps(payload), cwd=self.root)
        self.assertIn("additionalContext", p.stdout)


class TestQuestEnforcement(TrinityBase):
    """write-sentinel + gate — quest 로그 없이 write 하고 끝내는 우회 경로 봉합 검증."""

    def sentinel(self, rel, session="s1", error=False):
        payload = {
            "tool_name": "Write",
            "session_id": session,
            "cwd": self.root,
            "tool_input": {"file_path": os.path.join(self.root, rel)},
            "tool_response": {"is_error": True, "error": "boom"} if error else {"ok": True},
        }
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
        self.assertEqual([e["event"] for e in events], ["plan", "work", "verify"])


class TestUnattended(TrinityBase):
    """무인 진행 강제층 (CUS-169) — 감지 주입 + 시도-없는 ESCALATE 1회 차단."""

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
            self.assertEqual("무인 세션" in p.stdout, expect, mode)

    def test_context_env_override(self):
        p = run(
            UCTX,
            stdin=json.dumps({"permission_mode": "default"}),
            cwd=self.root,
            env_extra={"ASGARD_UNATTENDED": "1"},
        )
        self.assertIn("무인 세션", p.stdout)

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


class TestBaseline(TrinityBase):
    """CUS-187 — 하네스 소유 베이스라인 체크: 증거 '품질'의 결정론화 (verifier 재량 커맨드 불신)."""

    def last_event(self):
        lines = open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")).read().splitlines()
        return json.loads(lines[-1])

    def test_red_blocks_close_routes_repair_and_gate(self):
        self.policy(baseline_checks=["false"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()  # verifier 는 PASS + echo 급 증거 — 하네스 체크가 red 를 기록한다
        st = jout(self.qlog("state"))
        self.assertEqual(st["baseline_state"], "red")
        self.assertEqual(jout(self.qlog("next"))["next_role"], "WORKER_RETRY")
        self.assertEqual(self.qlog("close").returncode, 1)
        gp = jout(self.gate())
        self.assertEqual(gp.get("decision"), "block")
        self.assertIn("베이스라인", gp.get("reason", ""))

    def test_green_baseline_done_and_close(self):
        self.policy(baseline_checks=["true"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        st = jout(self.qlog("state"))
        self.assertEqual(st["baseline_state"], "green")
        self.assertEqual(jout(self.qlog("next"))["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)
        self.assertNotEqual(jout(self.gate()).get("decision"), "block")

    def test_no_checks_waived(self):
        self.open_quest()  # 체크 미설정 + 자동 감지 대상 없음 → 요건 면제 (구 로그 하위호환)
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.assertEqual(jout(self.qlog("state"))["baseline_state"], "none")
        self.assertEqual(jout(self.qlog("next"))["next_role"], "DONE")

    def test_same_hash_reuses_cached_result(self):
        self.policy(baseline_checks=["echo x >> .asgard/bl-runs"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.verify()  # 동일 트리 재검증 — 체크 재실행 없이 캐시 재사용
        runs = open(os.path.join(self.root, ".asgard", "bl-runs")).read().splitlines()
        self.assertEqual(len(runs), 1)
        self.assertTrue(self.last_event()["baseline"].get("cached"))

    def test_timeout_is_skip_not_red(self):
        self.policy(baseline_checks=["sleep 3"], baseline_timeout=1)
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.assertEqual(jout(self.qlog("state"))["baseline_state"], "none")  # 인질 방지 fail-open

    def test_stdin_baseline_forgery_dropped(self):
        self.policy(baseline_checks=["false"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        body = {
            "role": "verifier",
            "event": "verify",
            "commands": [{"cmd": "python3 app.py", "exit_code": 0}],
            "baseline": {"state": "green"},  # 위조 시도 — normalize 가 버리고 하네스가 red 재계산
        }
        self.qlog("append", "--verdict", "PASS", stdin=json.dumps(body))
        self.assertEqual(self.last_event()["baseline"]["state"], "red")

    def test_deleted_test_file_forces_full_verify(self):
        self.write("tests/test_app.py", "def test_a(): pass\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "add test"], check=True)
        self.open_quest()
        os.remove(os.path.join(self.root, "tests", "test_app.py"))
        self.write("app.py", "print('ok')\n")
        self.verify()  # micro PASS — 테스트 삭제 diff 는 full 을 요구한다 (anti-Goodhart)
        st = jout(self.qlog("state"))
        self.assertIn("tests/test_app.py", st["deleted_tests"])
        self.assertTrue(st["full_required"])
        self.assertEqual(jout(self.qlog("next"))["next_role"], "VERIFIER")
        gp = jout(self.gate())
        self.assertEqual(gp.get("decision"), "block")
        self.assertIn("삭제된 테스트", gp.get("reason", ""))


class TestStandardTransition(TrinityBase):
    """CUS-188 — 게이트-우선 전이: BASELINE_VERIFY 배정·verify-baseline 판정·승격 조건."""

    def commit_all(self, msg="c"):
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", msg], check=True)

    def work(self):
        self.qlog("append", "--role", "worker", "--event", "work")

    def nxt(self, *flags):
        return jout(self.qlog("next", "--write-expected", *flags))

    def test_work_routes_baseline_verify(self):
        self.policy(baseline_checks=["true"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.work()
        self.assertEqual(self.nxt()["next_role"], "BASELINE_VERIFY")

    def test_no_checks_falls_back_to_llm_verifier(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.work()
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")

    def test_verify_baseline_green_done_close_gate(self):
        self.policy(baseline_checks=["true"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.work()
        vb = jout(self.qlog("verify-baseline"))
        self.assertEqual((vb["verdict"], vb["baseline"]), ("PASS", "green"))
        self.assertEqual(self.nxt()["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)
        self.assertNotEqual(jout(self.gate()).get("decision"), "block")

    def test_red_retries_worker_then_two_reds_escalate(self):
        self.policy(baseline_checks=["false"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.work()
        vb = jout(self.qlog("verify-baseline"))
        self.assertEqual(vb["verdict"], "FAIL")
        self.assertEqual(self.nxt()["next_role"], "WORKER_RETRY")
        self.work()
        self.qlog("verify-baseline")
        n = self.nxt()  # red 2회 — threshold(3) 전 선제 Trinity 승격
        self.assertEqual(n["next_role"], "THINKER_REPLAN")
        self.assertIn("승격", n["why"])

    def test_signature_change_escalates_to_llm_verifier(self):
        self.write("lib.py", "def foo(a):\n    return a\n")
        self.commit_all()
        self.policy(baseline_checks=["true"])
        self.open_quest()
        self.write("lib.py", "def foo(a, b):\n    return a\n")  # 시그니처 변경 = 숨은-caller 리스크
        self.work()
        self.assertTrue(jout(self.qlog("state"))["sig_risk"])
        self.assertEqual(self.nxt()["next_role"], "VERIFIER")

    def test_body_edit_is_not_signature_risk(self):
        self.write("lib.py", "def foo(a):\n    return a\n")
        self.commit_all()
        self.policy(baseline_checks=["true"])
        self.open_quest()
        self.write("lib.py", "def foo(a):\n    return a + 1\n")  # 본문만 변경
        self.work()
        self.assertFalse(jout(self.qlog("state"))["sig_risk"])
        self.assertEqual(self.nxt()["next_role"], "BASELINE_VERIFY")

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
        # CUS-189 스모크 발견 — 잠금 테스트 추가가 big 오판을 만들면 게이트-우선이 무력화된다
        self.policy(baseline_checks=["true"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.write("test_a.py", "assert True\n")
        self.write("test_b.py", "assert True\n")  # changed 3파일 — non-test 는 1파일
        self.work()
        self.assertEqual(self.nxt()["next_role"], "BASELINE_VERIFY")
        jout(self.qlog("verify-baseline"))
        self.assertEqual(self.nxt()["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)
        self.assertNotEqual(jout(self.gate()).get("decision"), "block")

    def test_large_rewrite_escalates_even_without_sig_change(self):
        # CUS-194 벤치 결함 — def 무변경 리라이트(+52/-11)가 caller 를 깨고도 소형 판정돼 close 됨
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


class TestRoutePriors(TrinityBase):
    """CUS-127 Bayesian-lite — task-class 게이트-red 이력(과반)이 승격 문턱을 2→1 로 하향."""

    def priors(self, **classes):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "route-priors.json"), "w") as f:
            json.dump({"schema": 1, "classes": classes}, f)

    def one_red(self):
        """게이트-우선 적격 상태에서 baseline red 1회까지 진행."""
        self.policy(baseline_checks=["false"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
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
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "route-priors.json"), "w") as f:
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
        with open(os.path.join(self.root, ".asgard", "route-priors.json"), "w") as f:
            f.write("{broken")
        update_priors(self.root, "standard", red=True)  # 깨진 파일 위에서도 예외 없이 재시작
        self.assertEqual(load_priors(self.root)["classes"]["standard"], {"n": 1, "red": 1})


class TestUnattendedTransition(TrinityBase):
    """Canon 8 무인 nudge 의 전이측 (네이티브 등가) — ESCALATE → 재계획 1회 → 재-ESCALATE 인정."""

    def nxt(self, *flags):
        return jout(self.qlog("next", "--write-expected", *flags))

    def test_unattended_escalate_replan_once_then_honored(self):
        self.open_quest()
        self.write("app.py", "x\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("ESCALATE")
        self.assertEqual(self.nxt()["next_role"], "ESCALATE_ODIN")  # attended 는 즉시 에스컬레이션
        self.assertEqual(self.nxt("--unattended")["next_role"], "THINKER_REPLAN")  # 무인 1회 nudge
        self.qlog("append", "--role", "thinker", "--event", "plan")  # nudge 소비 (재계획 기록)
        self.assertEqual(self.nxt("--unattended")["next_role"], "WORKER")  # 실행 재개 (재-에스컬레이션 아님)
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("ESCALATE")
        self.assertEqual(self.nxt("--unattended")["next_role"], "ESCALATE_ODIN")  # 재-ESCALATE = 진짜 블로커


class TestGoodhartEvidence(TrinityBase):
    """PASS 증거 trivial 필터 — `true`/`echo` 한 방이 증거로 성립하던 구멍 (게이트·전이 동일 기준)."""

    def test_trivial_only_pass_rejected_by_transition_and_gate(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "true", "exit_code": 0}, {"cmd": "echo ok", "exit_code": 0}])
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "VERIFIER")  # 재검증 강제
        out = jout(self.gate())
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("증거", out.get("reason", ""))

    def test_real_command_pass_allowed(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "true", "exit_code": 0}, {"cmd": "python3 app.py", "exit_code": 0}])
        self.assertNotEqual(jout(self.gate()).get("decision"), "block")


class TestSubagentGate(TrinityBase):
    """SubagentStop 역할 로그 규율 (CUS-197) — 미기록 종료 block, 신선도는 앵커(마지막 상대 이벤트) 기준."""

    def sg(self, agent, session="s1"):
        return run(
            SUBGATE,
            stdin=json.dumps(
                {"agent_type": agent, "session_id": session, "cwd": self.root, "hook_event_name": "SubagentStop"}
            ),
            cwd=self.root,
        )

    def blocked(self, p):
        out = jout(p)
        return out.get("decision") == "block", out.get("reason", "")

    def work(self, **extra):
        body = {"role": "worker", "event": "work", "commands": [{"cmd": "python3 app.py", "exit_code": 0}], **extra}
        return self.qlog("append", stdin=json.dumps(body))

    def test_no_active_quest_allows(self):
        b, _ = self.blocked(self.sg("asgard-verifier"))
        self.assertFalse(b)

    def test_non_trinity_agent_allows(self):
        self.open_quest()
        self.work()
        b, _ = self.blocked(self.sg("asgard-loki"))
        self.assertFalse(b)

    def test_verifier_without_verify_blocks(self):
        self.open_quest()
        self.work()
        b, reason = self.blocked(self.sg("asgard-verifier"))
        self.assertTrue(b)
        self.assertIn("verify", reason)

    def test_verifier_with_evidence_pass_allows(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.work()
        self.verify("PASS")
        b, _ = self.blocked(self.sg("asgard-verifier"))
        self.assertFalse(b)

    def test_verifier_trivial_evidence_pass_blocks(self):
        self.open_quest()
        self.work()
        self.verify("PASS", commands=[{"cmd": "echo ok", "exit_code": 0}])
        b, reason = self.blocked(self.sg("asgard-verifier"))
        self.assertTrue(b)
        self.assertIn("증거", reason)

    def test_verifier_fail_verdict_allows(self):
        # FAIL 판정은 증거 요건 없이도 유효한 역할 수행 — 이 게이트는 기록 규율만 본다
        self.open_quest()
        self.work()
        self.verify("FAIL", commands=[])
        b, _ = self.blocked(self.sg("asgard-verifier"))
        self.assertFalse(b)

    def test_worker_without_work_blocks(self):
        self.open_quest()
        b, reason = self.blocked(self.sg("asgard-worker"))
        self.assertTrue(b)
        self.assertIn("work", reason)

    def test_worker_with_work_allows(self):
        self.open_quest()
        self.work()
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertFalse(b)

    def test_worker_stale_work_before_verify_blocks(self):
        # 앵커 신선도 — 직전 판정(verify) 이후의 work 만 이번 턴 기록으로 인정
        self.open_quest()
        self.work()
        self.verify("FAIL")
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertTrue(b)
        self.work()
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertFalse(b)

    def test_thinker_replan_freshness(self):
        # open 의 plan 기록으로 첫 thinker 는 통과, verify 이후 재계획 미기록은 block
        self.open_quest()
        b, _ = self.blocked(self.sg("asgard-thinker"))
        self.assertFalse(b)
        self.work()
        self.verify("FAIL")
        b, _ = self.blocked(self.sg("asgard-thinker"))
        self.assertTrue(b)
        self.qlog("append", stdin=json.dumps({"role": "thinker", "event": "plan", "criteria": ["fix"]}))
        b, _ = self.blocked(self.sg("asgard-thinker"))
        self.assertFalse(b)

    def test_two_block_cap_then_fail_open(self):
        self.open_quest()
        for _ in range(2):
            b, _ = self.blocked(self.sg("asgard-worker"))
            self.assertTrue(b)
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertFalse(b)  # 3번째 = 통과 (최종 담보는 verifier-gate)

    def test_pass_resets_block_counter(self):
        self.open_quest()
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertTrue(b)
        self.work()
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertFalse(b)  # 통과 → 카운터 리셋
        self.verify("FAIL")
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertTrue(b)  # 리셋 후 새 위반은 다시 계수

    def test_malformed_stdin_fail_open(self):
        p = run(SUBGATE, stdin="not-json", cwd=self.root)
        self.assertEqual(p.returncode, 0)


class TestAdversarialSuite(unittest.TestCase):
    """CC4 (CUS-201) 게이트 적대 벡터 통합 — workspace/bench-cc/adversarial.sh 를 CI 에서 구동.
    실 LLM 불필요(훅 직접 구동), 우회 벡터 10종 전수 차단/허용 대조. 벤치 디렉터리 부재 시 skip."""

    def test_adversarial_vectors_all_blocked(self):
        script = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "workspace", "bench-cc", "adversarial.sh")
        )
        if not os.path.exists(script):
            self.skipTest("adversarial.sh 없음 (workspace 미포함 환경)")
        p = subprocess.run(["bash", script], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, f"적대 벡터 실패:\n{p.stdout}\n{p.stderr}")
        self.assertIn("FAIL=0", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
