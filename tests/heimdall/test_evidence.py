#!/usr/bin/env python3
"""판정 증거 — 차단된 호출·러너 신원·하네스 관측 실행 기록·게이트 복제 동등성."""

import json
import os
import tempfile
import unittest
from typing import Any

from asgard.agent.session import SessionResult
from heimdall.harness import (
    CLS_WRITE,
    DONE,
    Base,
    FakeHeimdall,
    FakeSession,
    verifier,
    worker,
)


class TestBlockedEvidenceParity(Base):
    """가드 차단 호출은 실행된 적 없는 명령이다 — 미해소 실패로 PASS를 강등시키지 않는다.

    실증 근거(26-07-21): claude_cli 트랜스포트에서 readonly 가드가 거부한 `git -C "$(pwd)" …`가
    is_error→exit 1로 증거에 승격, 동등 명령으로 이미 해소했어도 unresolved-verification-failure로
    PASS가 강등돼 턴 예산을 태웠다. 커널 경로(blocked 미기록)와 패리티."""

    def _verifier_with(self, commands):
        return FakeSession(
            SessionResult(
                text="verified",
                stop_reason="end_turn",
                commands=commands,
                tool_calls=[
                    {
                        "name": "verdict",
                        "input": {
                            "verdict": "PASS",
                            "criteria": CLS_WRITE["criteria"],
                            "commands": [{"cmd": "fake", "exit_code": 0}],
                        },
                    }
                ],
            ),
            label="verifier",
        )

    def test_blocked_failure_does_not_demote_pass(self):
        cmds = [
            {"cmd": "javac -version", "exit_code": 1, "blocked": True},
            {"cmd": "pytest -q", "exit_code": 0},
        ]
        seq = [worker({"w1.txt": "x\n"}, self.root), self._verifier_with(cmds)]
        out = FakeHeimdall(self.root, seq, cls=CLS_WRITE).handle("w1.txt 만들어")
        self.assertIn(DONE, out)

    def test_executed_failure_still_demotes_pass(self):
        cmds = [
            {"cmd": "javac -version", "exit_code": 1},
            {"cmd": "pytest -q", "exit_code": 0},
        ]
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            self._verifier_with(cmds),
            worker({"w1.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        events = [json.loads(line) for line in self.quest_log_text().splitlines() if line.strip()]
        failures = [event for event in events if event.get("event") == "verify" and event.get("verdict") == "FAIL"]
        self.assertEqual(failures[0]["failure_sig"], "unresolved-verification-failure")


class TestRunnerIdentity(unittest.TestCase):
    """러너 래퍼 정규화 — 동등 러너 신원 일치, 다른 대상·파싱 불가는 그대로 (fail-safe)."""

    def setUp(self):
        from asgard.agent.heimdall.trinity import _runner_identity

        self.identity = _runner_identity

    def test_wrapper_variants_share_identity(self):
        for cmd in (
            "pytest tests -q",
            "uv run pytest tests -q",
            "uv run --no-cache pytest tests -q",
            "python -m pytest tests -q",
            "python3 -m pytest tests -q",
            ".venv/bin/pytest tests -q",
            "env UV_CACHE_DIR=.cache/uv uv run pytest tests -q",
        ):
            self.assertEqual(self.identity(cmd), "pytest tests -q", cmd)

    def test_python_dash_c_smoke_variants_share_identity(self):
        self.assertEqual(
            self.identity("uv run python -c 'import m; m.f()'"),
            self.identity("python3 -c 'import m; m.f()'"),
        )

    def test_distinct_targets_stay_distinct(self):
        self.assertNotEqual(self.identity("pytest tests/a.py -q"), self.identity("pytest tests/b.py -q"))

    def test_unparsable_command_falls_back_to_raw(self):
        self.assertEqual(self.identity('pytest "unclosed'), 'pytest "unclosed')


class TestTrajectoryNote(unittest.TestCase):
    """판정자가 받는 **하네스 관측 실행 기록** — 결과물만 보던 판정에 "무슨 일이 있었나"를 더한다.

    판정 품질을 가장 크게 움직이는 축이 판정자의 입력량이라는 실측(같은 모델로 76.4% 대 58%,
    기제는 매 단계 실행 로그 투입량)이 근거다. 담기는 것은 하네스가 적은 `cmd`·`exit_code`·차단
    여부뿐이라 "Worker commentary is not input" 계약은 그대로다."""

    def _note(self, events):
        import types

        from asgard.agent.heimdall.trinity import TrinityRun

        with tempfile.TemporaryDirectory() as root:
            quest = os.path.join(root, ".asgard", "quest")
            os.makedirs(quest)
            with open(os.path.join(quest, "q.jsonl"), "w", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event) + "\n")
            run: Any = types.SimpleNamespace(_hd=types.SimpleNamespace(root=root), qid="q")
            return TrinityRun._trajectory_note(run)

    def test_commands_and_exit_codes_reach_the_verdict_turn(self):
        note = self._note(
            [
                {
                    "event": "work",
                    "commands": [{"cmd": "pytest -q", "exit_code": 1}, {"cmd": "ruff check .", "exit_code": 0}],
                },
            ]
        )
        self.assertIn("pytest -q", note)
        self.assertIn("exit 1", note)
        self.assertIn("ruff check .", note)

    def test_a_blocked_command_is_named_as_never_run(self):
        note = self._note([{"event": "work", "commands": [{"cmd": "rm -rf x", "blocked": True}]}])
        self.assertIn("blocked", note)
        self.assertIn("rm -rf x", note)

    def test_only_the_turns_since_the_last_verdict_are_shown(self):
        note = self._note(
            [
                {"event": "work", "commands": [{"cmd": "old-command", "exit_code": 0}]},
                {"event": "verify", "verdict": "FAIL"},
                {"event": "work", "commands": [{"cmd": "new-command", "exit_code": 0}]},
            ]
        )
        self.assertIn("new-command", note)
        self.assertNotIn("old-command", note)

    def test_a_quest_with_no_commands_adds_nothing(self):
        self.assertEqual(self._note([{"event": "work"}]), "")
        self.assertEqual(self._note([]), "")

    def test_the_dropped_count_is_not_hidden(self):
        events = [{"event": "work", "commands": [{"cmd": f"cmd-{n}", "exit_code": 0} for n in range(45)]}]
        note = self._note(events)
        self.assertIn("15 more not shown", note)
        self.assertIn("cmd-0", note)
        self.assertNotIn("cmd-44", note)


class TestHookParity(Base):
    """quest_log ↔ verifier_gate 복제 코드 동등성 — 어긋나면 게이트↔전이 판정 분열."""

    def test_sensitive_path_segment_matching(self):
        from asgard.hooks.quest_log import sensitive_path as q
        from asgard.hooks.verifier_gate import sensitive_path as g

        needles = ["hooks", "ci", ".github", "auth", "authentication", "migration", "migrations", "db"]
        cases = {
            "circle.py": False,  # 'ci' substring 오탐 회귀 방지
            "ci/config.yml": True,
            ".github/workflows/x.yml": True,
            "hooks/deploy.py": True,
            "src/authentication.py": True,  # 파생형은 needle 목록에 명시 (substring 매칭 아님)
            "src/oauth.py": False,  # 'auth' 4자+ substring 오탐 회귀 방지 (26-07-23 감사)
            "src/author.py": False,  # 'auth' prefix 오탐 회귀 방지
            "src/auth.py": True,  # [._-] 토큰 정확 일치
            "src/db_pool.py": True,  # 토큰 일치 — db
            "src/circuit.py": False,
            "db/migrations/0001.py": True,
            "readme.md": False,
        }
        for path, want in cases.items():
            self.assertEqual(q(path, needles), want, f"quest_log: {path}")
            self.assertEqual(g(path, needles), want, f"verifier_gate: {path}")

    def test_evidenceless_pass_cannot_close_or_transition_done(self):
        # 깊이 테스트가 발견한 구멍: 무증거 PASS → close → LAST 면제로 게이트 우회
        import subprocess
        import sys as _sys

        def ql(*args, stdin=""):
            return subprocess.run(
                [_sys.executable, "-m", "asgard.hooks.quest_log", *args, "--session", "ev"],
                input=stdin, capture_output=True, text=True, cwd=self.root, timeout=30,
            )  # fmt: skip

        ql("open", "q-ev", "--criteria", "c")
        open(os.path.join(self.root, "f.txt"), "a").write("x\n")
        ql("append", stdin=json.dumps({"role": "worker", "event": "work"}))
        ql("append", "--verdict", "PASS", "--level", "full",
           stdin=json.dumps({"role": "verifier", "event": "verify", "commands": []}))  # fmt: skip
        nxt = json.loads(ql("next", "--write-expected").stdout)
        self.assertEqual(nxt["next_role"], "VERIFIER")  # DONE 금지 — 재검증 지시
        self.assertIn("evidence", nxt["why"])
        self.assertEqual(ql("close").returncode, 1)  # close 거부
        # 증거 추가 후엔 통과
        ql("append", "--verdict", "PASS", "--level", "full",
           stdin=json.dumps({"role": "verifier", "event": "verify",
                             "commands": [{"cmd": "python3 -c 1", "exit_code": 0}]}))  # fmt: skip
        self.assertEqual(json.loads(ql("next", "--write-expected").stdout)["next_role"], "DONE")
        self.assertEqual(ql("close").returncode, 0)

    def test_gate_orphan_last_exemption_requires_evidence(self):
        # 강제 close는 LAST 미기록 — 그리고 구버전 quest-log가 남긴 LAST 라도
        # 무증거 PASS 면 게이트가 orphan write를 차단해야 한다 (심층 방어)
        import subprocess
        import sys as _sys

        def ql(*args, stdin=""):
            return subprocess.run(
                [_sys.executable, "-m", "asgard.hooks.quest_log", *args, "--session", "ev2"],
                input=stdin, capture_output=True, text=True, cwd=self.root, timeout=30,
            )  # fmt: skip

        ql("open", "q-ev2", "--criteria", "c")
        open(os.path.join(self.root, "f.txt"), "a").write("y\n")
        ql("append", stdin=json.dumps({"role": "worker", "event": "work"}))
        ql("append", "--verdict", "PASS", "--level", "full",
           stdin=json.dumps({"role": "verifier", "event": "verify", "commands": []}))  # fmt: skip
        forced = ql("close", "--force")
        self.assertEqual(forced.returncode, 0)
        self.assertFalse(json.loads(forced.stdout).get("gate_exempt", True))
        last = os.path.join(self.root, ".asgard", "quest", "LAST")
        self.assertFalse(os.path.exists(last))  # forced close는 게이트 면제(LAST)를 만들지 않는다
        os.makedirs(os.path.join(self.root, ".asgard", "state"), exist_ok=True)
        json.dump(["f.txt"], open(os.path.join(self.root, ".asgard", "state", "writes-ev2.json"), "w"))

        def gate():
            return subprocess.run(
                [_sys.executable, "-m", "asgard.hooks.verifier_gate"],
                input=json.dumps({"session_id": "ev2", "cwd": self.root}),
                capture_output=True, text=True, cwd=self.root, timeout=60,
            )  # fmt: skip

        self.assertIn('"block"', gate().stdout)  # LAST 없음 → orphan write 차단
        open(last, "w").write("q-ev2\n")  # 구버전 quest-log가 남긴 LAST 시뮬레이션
        self.assertIn('"block"', gate().stdout)  # 무증거 LAST는 면제 불가

    def test_diff_state_parity(self):
        import subprocess

        from asgard.hooks.quest_log import diff_state as q
        from asgard.hooks.verifier_gate import diff_state as g

        head = subprocess.run(
            ["git", "-C", self.root, "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        open(os.path.join(self.root, "f.txt"), "a").write("delta\n")
        open(os.path.join(self.root, "new.txt"), "w").write("n\n")
        os.makedirs(os.path.join(self.root, "__pycache__"), exist_ok=True)
        open(os.path.join(self.root, "__pycache__", "x.pyc"), "w").write("junk")
        self.assertEqual(q(self.root, head), g(self.root, head))
        self.assertIn("new.txt", q(self.root, head)[1])
        self.assertNotIn("__pycache__/x.pyc", q(self.root, head)[1])  # junk 제외 유지


if __name__ == "__main__":
    unittest.main(verbosity=1)
