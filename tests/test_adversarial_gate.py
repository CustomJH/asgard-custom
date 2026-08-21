#!/usr/bin/env python3
"""게이트 적대 벡터 — 크로스 플랫폼 포트 (Windows 포함 전 OS pytest).

정본 bash 하네스는 tests/fixtures/bench-cc/adversarial.sh (POSIX smoke·bench 전용).
같은 벡터 V1~V7을 bash·python3 없이 sys.executable로 돌린다 — 훅은 배포 형태 그대로
새 프로세스로 구동 (임포트 아님). CI windows 잡이 이 파일을 실행해 "게이트가 Windows 에서도
실제로 차단하는가"를 회귀 가드한다.

인코딩 회귀 (V8): Windows en-US 콘솔/파이프(cp1252)에서 한국어 차단 사유가
UnicodeEncodeError → 전역 fail-open에 삼켜져 block이 조용한 allow로 증발했던 실버그.
PYTHONIOENCODING=cp1252로 어느 OS 에서나 재현된다.

실행: uv run pytest tests/test_adversarial_gate.py
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
SUBGATE = os.path.abspath(os.path.join(SRC, "subagent_gate.py"))
SENTINEL = os.path.abspath(os.path.join(SRC, "write_sentinel.py"))


def run(script, args=None, stdin="", cwd=None, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, script] + (args or []),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",  # 훅 출력은 UTF-8 고정 — 호스트 로케일(cp1252 등)로 읽으면 안 된다
        cwd=cwd,
        env=env,
        timeout=60,
    )


class AdversarialBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        # HOME 격리 — 훅 subprocess가 호스트 git 설정·~/.asgard를 보지 않게 (TrinityBase 관행).
        # Windows는 HOME 대신 USERPROFILE을 보므로 둘 다 격리한다.
        self._saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
        os.environ["HOME"] = self.root
        os.environ["USERPROFILE"] = self.root
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "-C", self.root, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", self.root, "config", "user.name", "t"], check=True)
        self.write("app.py", "print('ok')\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "init"], check=True)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def write(self, rel, content):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def commit_all(self, msg="c"):
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", msg], check=True)

    def qlog(self, *args, stdin=""):
        return run(QLOG, list(args), stdin=stdin, cwd=self.root, env_extra={"CLAUDE_PROJECT_DIR": self.root})

    def open_quest(self, qid="q", criteria="c"):
        p = self.qlog("open", qid, "--criteria", criteria)
        self.assertEqual(p.returncode, 0, p.stderr)

    def policy(self, **kw):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "trinity-policy.json"), "w", encoding="utf-8") as f:
            json.dump(kw, f)

    def gate(self, session="s1", env_extra=None):
        env = {"CLAUDE_PROJECT_DIR": self.root, **(env_extra or {})}
        return run(
            GATE,
            stdin=json.dumps({"session_id": session, "cwd": self.root, "hook_event_name": "Stop"}),
            cwd=self.root,
            env_extra=env,
        )

    def gate_decision(self, session="s1", env_extra=None):
        p = self.gate(session, env_extra)
        return ("block" if '"decision": "block"' in p.stdout else "allow"), p

    def subgate_decision(self, agent, session="s1"):
        p = run(
            SUBGATE,
            stdin=json.dumps(
                {"agent_type": agent, "session_id": session, "cwd": self.root, "hook_event_name": "SubagentStop"}
            ),
            cwd=self.root,
            env_extra={"CLAUDE_PROJECT_DIR": self.root},
        )
        return ("block" if '"decision": "block"' in p.stdout else "allow"), p

    def sentinel(self, session, rel):
        return run(
            SENTINEL,
            stdin=json.dumps(
                {"session_id": session, "cwd": self.root, "tool_name": "Write", "tool_input": {"file_path": rel}}
            ),
            cwd=self.root,
            env_extra={"CLAUDE_PROJECT_DIR": self.root},
        )


class TestAdversarialVectors(AdversarialBase):
    def test_v1_forged_diff_hash_blocked(self):
        """V1. 로그 직접 위조 — 체인 밖 가짜 PASS append는 물리 대조 전에 ledger가 차단."""
        self.open_quest(criteria="add feature")
        self.write("app.py", "print('changed')\n")
        forged = {
            "schema": 1,
            "quest_id": "q",
            "turn": 9,
            "role": "verifier",
            "event": "verify",
            "verdict": "PASS",
            "diff_hash": "deadbeef",
            "commands": [{"cmd": "pytest", "exit_code": 0}],
            "criteria": ["x"],
        }
        with open(os.path.join(self.root, ".asgard", "quest", "q.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(forged) + "\n")
        got, p = self.gate_decision("v1")
        self.assertEqual(got, "block", p.stdout + p.stderr)

    def test_v2_max_blocks_escalation_not_silent(self):
        """V2. MAX_BLOCKS 소진 후 fail-open이 성공 위장이 아닌가 — 4번째는 allow 지만 에스컬레이션 지시."""
        self.open_quest()
        self.write("app.py", "x=1\n")  # 검증 안 된 write, PASS 레코드 없음
        for i in range(3):
            got, p = self.gate_decision("v2")
            self.assertEqual(got, "block", f"무판정 write 차단 {i + 1}/3: {p.stdout}{p.stderr}")
        got, p = self.gate_decision("v2")
        self.assertEqual(got, "allow", p.stdout)
        self.assertIn("escalation", p.stderr, "4번째 fail-open 인데 에스컬레이션 지시 없음 — 조용한 성공 금지")

    def test_v3_no_verify_record_in_new_quest_blocked(self):
        """V3. 증거 재활용 — 이전 quest 증거는 신규 quest에 무효, verify 레코드 없으면 차단."""
        self.open_quest("q1", "c1")
        self.write("app.py", "y=2\n")
        self.qlog("append", "--verdict", "PASS", stdin="")
        self.qlog("close")
        self.open_quest("q2", "c2")
        self.write("app.py", "y=2\nz=3\n")
        got, p = self.gate_decision("v3")
        self.assertEqual(got, "block", p.stdout + p.stderr)

    def test_v4_sensitive_path_micro_pass_blocked(self):
        """V4. sensitive 경로 우회 — 훅 파일 변경을 micro PASS로 통과 시도 → full 강제 차단.
        위험 축 승격은 verify_level=high 부터다 (기본 low 는 micro 로 판정한다)."""
        self.policy(verify_level="high")
        self.write(os.path.join(".claude", "hooks", "x.py"), "orig\n")
        self.commit_all("hooks")
        self.open_quest(criteria="edit hook")
        self.write(os.path.join(".claude", "hooks", "x.py"), "tampered\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        body = {"role": "verifier", "event": "verify", "commands": [{"cmd": "python3 -c pass", "exit_code": 0}]}
        self.qlog("append", "--verdict", "PASS", "--level", "micro", stdin=json.dumps(body))
        got, p = self.gate_decision("v4")
        self.assertEqual(got, "block", p.stdout + p.stderr)

    def test_v5_verifier_trivial_evidence_blocked_at_subgate(self):
        """V5. subagent-gate 우회 — verifier가 trivial(echo) 증거 PASS 기록 후 종료 → 차단."""
        self.open_quest()
        self.qlog("append", "--role", "worker", "--event", "work")
        body = {"role": "verifier", "event": "verify", "commands": [{"cmd": "echo done", "exit_code": 0}]}
        self.qlog("append", "--verdict", "PASS", stdin=json.dumps(body))
        got, p = self.subgate_decision("asgard-verifier", "v5")
        self.assertEqual(got, "block", p.stdout + p.stderr)

    def test_v6_reverted_orphan_write_not_hostage(self):
        """V6. 되돌린 orphan write는 인질 금지 — sentinel 기록 후 원복(clean)이면 차단 안 함."""
        self.write("app.py", "tmp\n")  # quest 미개설 write
        self.sentinel("v6", "app.py")
        subprocess.run(["git", "-C", self.root, "checkout", "--", "app.py"], check=True)
        got, p = self.gate_decision("v6")
        self.assertEqual(got, "allow", p.stdout + p.stderr)

    def test_v7_live_orphan_write_blocked(self):
        """V7. orphan write 살아있으면 차단 (V6 대조 — 원복 안 함)."""
        self.write("app.py", "leftover\n")
        self.sentinel("v7", "app.py")
        got, p = self.gate_decision("v7")
        self.assertEqual(got, "block", p.stdout + p.stderr)


class TestEncodingDisarm(AdversarialBase):
    """V8. 인코딩 무장해제 회귀 — cp1252 파이프에서도 block 판정이 증발하면 안 된다.

    실측 버그: 훅이 한국어 사유를 cp1252 stdout에 쓰다 UnicodeEncodeError → 전역
    fail-open(sys.exit(0))이 삼킴 → 판정 무출력 = CC는 allow로 해석. en-US Windows에서
    게이트 전체가 조용히 꺼지는 조건이었다. 훅의 UTF-8 reconfigure 가드가 방어한다.
    """

    def test_v8_block_survives_cp1252_pipe(self):
        self.open_quest()
        self.write("app.py", "x=1\n")
        got, p = self.gate_decision("v8", env_extra={"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(got, "block", f"cp1252 파이프에서 차단 증발: stdout={p.stdout!r} stderr={p.stderr!r}")

    def test_v8_subgate_survives_cp1252_pipe(self):
        self.open_quest()
        self.qlog("append", "--role", "worker", "--event", "work")
        p = run(
            SUBGATE,
            stdin=json.dumps(
                {
                    "agent_type": "asgard-verifier",
                    "session_id": "v8s",
                    "cwd": self.root,
                    "hook_event_name": "SubagentStop",
                }
            ),
            cwd=self.root,
            env_extra={"CLAUDE_PROJECT_DIR": self.root, "PYTHONIOENCODING": "cp1252"},
        )
        self.assertIn('"decision": "block"', p.stdout, f"stdout={p.stdout!r} stderr={p.stderr!r}")


class TestSessionIdentityDisarm(AdversarialBase):
    """세션 신원이 안 맞을 때 게이트가 조용히 사라지던 자리.

    모델은 `quest-log.py open`을 **--session 없이** 부른다 (AGENTS.md의 지시) — 그 기본값은
    `$CLAUDE_SESSION_ID` 또는 `"-"` 다. 그런데 Stop 게이트는 Cursor에서 `"cursor"`를 고정으로
    봤다. 이름이 영영 안 맞으니 "활성이 정확히 1개면 승계" 규칙에 기대게 되고, 버려진 quest가
    하나만 더 쌓이면 그 규칙마저 비켜서 **write가 판정 없이 통과**했다 (26-07-31 실측: 실제
    저장소에 활성 포인터 6개가 남아 있었다)."""

    def gate_raw(self, payload, argv=None):
        return run(
            GATE,
            args=argv or [],
            stdin=json.dumps({**payload, "cwd": self.root, "hook_event_name": "Stop"}),
            cwd=self.root,
            env_extra={"CLAUDE_PROJECT_DIR": self.root},
        )

    def blocked(self, payload, argv=None):
        out = self.gate_raw(payload, argv).stdout
        return "[gate:" in out

    def abandon(self, qid, session):
        """크래시·중단으로 활성인 채 남은 quest — 실사용에서 쌓이는 그 상태."""
        p = self.qlog("open", qid, "--criteria", "c", "--session", session)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_default_session_write_is_gated_in_every_client(self):
        self.qlog("open", "q", "--criteria", "c")  # --session 없이 (기본값 "-")
        self.write("app.py", "print('changed')\n")
        for argv in ([], ["cursor"], ["codex"]):
            self.assertTrue(self.blocked({}, argv), argv)

    def test_an_abandoned_quest_does_not_disarm_the_gate(self):
        self.qlog("open", "q", "--criteria", "c")
        self.write("app.py", "print('changed')\n")
        for index, argv in enumerate(([], ["cursor"], ["codex"]), 1):
            self.abandon(f"stale{index}", f"abandoned{index}")  # 활성이 2개, 3개, 4개로 늘어난다
            self.assertTrue(self.blocked({}, argv), argv)

    def test_a_closed_session_does_not_inherit_someone_elses_quest(self):
        """인질극 방지 — 자기 quest를 정상으로 닫은 세션은 남의 활성에 걸리지 않는다."""
        self.qlog("open", "q", "--criteria", "c")
        self.write("app.py", "print('changed')\n")
        self.qlog(
            "append",
            "--verdict",
            "PASS",
            "--level",
            "full",
            stdin=json.dumps(
                {
                    "role": "verifier",
                    "event": "verify",
                    "criteria": ["c"],
                    "commands": [{"cmd": "python -m compileall -q app.py", "exit_code": 0}],
                }
            ),
        )
        self.assertEqual(self.qlog("close").returncode, 0)
        self.abandon("theirs", "someone-else")
        for argv in ([], ["cursor"], ["codex"]):
            self.assertFalse(self.blocked({}, argv), argv)


class TestGateEventMetrics(AdversarialBase):
    """게이트 운영 지표 — 차단·에스컬레이션이 durable 하게 남고(doctor 집계 원천) 코드가 붙는다.

    차단 카운터(gate-blocks-*.json)는 통과 시 삭제되므로 지표가 못 된다 — append-only
    state/gate-events.jsonl이 운영 지표의 단일 원천이다.
    """

    def events_path(self):
        return os.path.join(self.root, ".asgard", "state", "gate-events.jsonl")

    def read_events(self):
        with open(self.events_path(), encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]

    def test_blocks_and_escalation_logged_with_codes(self):
        self.open_quest()
        self.write("app.py", "x=1\n")
        for _ in range(4):  # 3회 block + 4번째 fail-open 에스컬레이션
            self.gate_decision("m1")
        events = self.read_events()
        kinds = [e["event"] for e in events]
        self.assertEqual(kinds.count("gate_block"), 3, events)
        self.assertEqual(kinds.count("gate_escalate"), 1, events)
        self.assertEqual({e["code"] for e in events}, {"no-verdict"})

    def test_unprotected_forged_pass_is_rejected_by_ledger(self):
        self.open_quest()
        self.write("app.py", "print('changed')\n")
        forged = {
            "role": "verifier",
            "event": "verify",
            "verdict": "PASS",
            "diff_hash": "deadbeef",
            "commands": [{"cmd": "pytest", "exit_code": 0}],
            "criteria": ["x"],
        }
        with open(os.path.join(self.root, ".asgard", "quest", "q.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(forged) + "\n")
        got, p = self.gate_decision("m2")
        self.assertEqual(got, "block", p.stdout + p.stderr)
        self.assertEqual(self.read_events()[-1], {"event": "gate_block", "gate": "verifier", "code": "ledger-invalid"})
        payload = json.loads(p.stdout)
        self.assertEqual(payload.get("code"), "ledger-invalid")  # payload 코드 직독 — 문장 파싱 불필요
        self.assertIn("[gate:ledger-invalid]", payload["reason"])  # 프로토콜 공통 운반자 = 메시지 태그

    def test_doctor_aggregates_gate_events(self):
        from asgard.commands.doctor import _trinity_checks

        self.write("AGENTS.md", "asgard\n")  # 프로젝트 체크는 AGENTS.md 있는 루트에서만
        os.makedirs(os.path.dirname(self.events_path()), exist_ok=True)
        with open(self.events_path(), "w", encoding="utf-8") as f:
            for code in ("stale-pass", "stale-pass", "no-evidence"):
                f.write(json.dumps({"event": "gate_block", "code": code}) + "\n")
            f.write(json.dumps({"event": "gate_escalate", "code": "no-verdict"}) + "\n")
        qdir = os.path.join(self.root, ".asgard", "quest")
        os.makedirs(qdir, exist_ok=True)
        with open(os.path.join(qdir, "q9.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"event": "verify", "verdict": "PASS"}) + "\n")
            f.write(json.dumps({"event": "verify", "verdict": "FAIL"}) + "\n")
            f.write(json.dumps({"event": "quest_closed", "risk": {"forced": True, "decision": "REJECTED"}}) + "\n")
        check = next(c for c in _trinity_checks(self.root) if c["name"] == "trinity gate events")
        self.assertFalse(check["ok"], check)  # forced close = 게이트 수동 우회 경고
        self.assertIn("gate block 3회", check["detail"])
        self.assertIn("stale-pass 2", check["detail"])
        self.assertIn("에스컬레이션 1회", check["detail"])
        self.assertIn("PASS 1·FAIL 1", check["detail"])
        self.assertIn("forced close 1회", check["detail"])

    def test_doctor_ok_without_forced_close(self):
        from asgard.commands.doctor import _trinity_checks

        self.write("AGENTS.md", "asgard\n")
        os.makedirs(os.path.dirname(self.events_path()), exist_ok=True)
        with open(self.events_path(), "w", encoding="utf-8") as f:
            f.write(json.dumps({"event": "gate_block", "code": "no-criteria"}) + "\n")
        check = next(c for c in _trinity_checks(self.root) if c["name"] == "trinity gate events")
        self.assertTrue(check["ok"], check)  # 차단은 게이트가 일한 증거 — 경고 아님


class TestARunningWaveIsNotACompletionClaim(AdversarialBase):
    """단위가 아직 도는 턴을 게이트가 막으면, 코디네이터가 자기가 부른 판정자를 못 기다린다.

    26-08-21 실측: 호스트 모드에서 워커 일곱을 비동기로 띄운 턴이 `no-verdict` 로 세 번 막혔다.
    그 시각 일곱은 전부 정상적으로 돌고 있었고, 판정이 읽을 결과는 아직 없었다. 완료 주장은
    여기서 안 새어 나간다 — `close` 는 판정 없이 그대로 거부한다."""

    def declare(self, unit: str, status: str = "todo") -> None:
        body = json.dumps({"role": "thinker", "event": "ticket", "ticket_status": status, "unit": unit})
        p = self.qlog("append", "q", "--json", body)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_a_turn_with_units_still_running_is_not_blocked(self):
        self.open_quest()
        self.write("app.py", "x = 1\n")
        self.declare("u-1")
        decision, _ = self.gate_decision("wave")
        self.assertEqual(decision, "allow", "단위가 도는 중인데 판정을 요구했다")

    def test_the_same_turn_is_blocked_once_every_unit_has_settled(self):
        self.open_quest()
        self.write("app.py", "x = 1\n")
        self.declare("u-1")
        self.assertEqual(self.gate_decision("wave")[0], "allow")
        # 티켓 전이는 전용 동사로만 간다 — 날 append 는 thinker 의 todo 선언만 받는다.
        claim = self.qlog("ticket-claim", "q", "--unit", "u-1", "--worker", "w-1")
        self.assertEqual(claim.returncode, 0, claim.stderr)
        token = json.loads(claim.stdout)["claim_token"]
        done = self.qlog("ticket-finish", "q", "--unit", "u-1", "--claim-token", token, "--status", "done")
        self.assertEqual(done.returncode, 0, done.stderr)
        decision, _ = self.gate_decision("wave")
        self.assertEqual(decision, "block", "단위가 다 끝났는데 판정 없이 통과했다")

    def test_a_turn_that_dispatched_a_verifier_is_not_blocked(self):
        """호스트에서 서브에이전트는 비동기라, 판정자를 부른 턴은 자기가 부른 판정을 못 기다린다.

        그 턴을 막으면 남는 길이 둘뿐이다 — 자기 판정을 자기가 적거나(독립성 위반), 상한
        세 번을 버리거나. 26-08-21 실측으로 이 저장소에 `no-verdict` 차단 148회와 상한 초과
        통과 95회가 쌓여 있었다."""
        self.open_quest()
        self.write("app.py", "x = 1\n")
        self.assertEqual(self.gate_decision("dispatched")[0], "block", "배차 전에는 막혀야 한다")
        self._open_verifier_dispatch("q")
        decision, _ = self.gate_decision("dispatched")
        self.assertEqual(decision, "allow", "판정이 오는 중인데 판정을 요구했다")

    def test_a_settled_verifier_dispatch_no_longer_shields_the_turn(self):
        """돌아온 판정자는 더 가려 주지 않는다 — 그때는 기록할 판정이 실제로 있다."""
        self.open_quest()
        self.write("app.py", "x = 1\n")
        self._open_verifier_dispatch("q", settled=True)
        decision, _ = self.gate_decision("settled")
        self.assertEqual(decision, "block")

    def test_another_agents_open_dispatch_does_not_shield_the_turn(self):
        """판정자가 아닌 배차는 판정을 약속하지 않는다."""
        self.open_quest()
        self.write("app.py", "x = 1\n")
        self._open_verifier_dispatch("q", agent="asgard-worker")
        decision, _ = self.gate_decision("worker-only")
        self.assertEqual(decision, "block")

    def _open_verifier_dispatch(self, qid: str, *, agent: str = "asgard-verifier", settled: bool = False) -> None:
        """배차 장부에 이 퀘스트의 시도 하나를 세운다 — 훅이 배차 때 적는 것과 같은 모양."""
        import sqlite3

        db = os.path.join(self.root, ".asgard", "orchestration.db")
        os.makedirs(os.path.dirname(db), exist_ok=True)
        conn = sqlite3.connect(db)
        try:
            conn.executescript(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, quest_id TEXT, status TEXT, created_at REAL);"
                "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, run_id TEXT);"
                "CREATE TABLE IF NOT EXISTS dispatches ("
                "  id TEXT PRIMARY KEY, task_id TEXT, agent TEXT, settled_at REAL);"
            )
            conn.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?)", ("run_x", qid, "open", 0.0))
            conn.execute("INSERT OR REPLACE INTO tasks VALUES (?,?)", ("task_x", "run_x"))
            conn.execute(
                "INSERT OR REPLACE INTO dispatches VALUES (?,?,?,?)",
                ("disp_x", "task_x", agent, 1.0 if settled else None),
            )
            conn.commit()
        finally:
            conn.close()

    def test_a_quest_with_no_units_is_unaffected(self):
        """티켓을 안 쓰는 보통 쓰기 퀘스트는 종전 그대로 막힌다."""
        self.open_quest()
        self.write("app.py", "x = 1\n")
        decision, _ = self.gate_decision("plain")
        self.assertEqual(decision, "block")

    def test_close_still_refuses_while_the_wave_runs(self):
        """게이트가 비켜 준다고 완료가 열리는 것은 아니다 — 그 문은 따로 잠겨 있다."""
        self.open_quest()
        self.write("app.py", "x = 1\n")
        self.declare("u-1")
        self.assertEqual(self.gate_decision("wave")[0], "allow")
        self.assertNotEqual(self.qlog("close", "q").returncode, 0, "판정 없이 닫혔다")


if __name__ == "__main__":
    unittest.main(verbosity=2)
