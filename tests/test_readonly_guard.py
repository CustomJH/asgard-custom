#!/usr/bin/env python3
"""읽기전용 레인의 예외 하나 — 하네스가 어차피 자기 손으로 돌리는 명령.

판정자 주입면은 이 판정이 무엇으로 채점되는지를 알려 준다 (선언된 verify 계약과 프로젝트
베이스라인). 알려 주고 실행은 막으면 판정자는 채점 기준을 알고도 그것을 못 돌리고, 판정이 자기
명령 대신 우회 계산 위에 선다 — 26-08-14 판정이 실제로 그렇게 섰다.

여기서 고정하는 것은 그 예외가 **출처로만** 열린다는 것이다. 통과하는 문자열은 하네스가 PASS 를
적을 때 돌리는 바로 그것이라 새로 열리는 실행 능력이 없고, 인자 하나가 달라지면 다시 임의
실행이다. 목록을 손으로 넓히는 방식이 이 저장소에서 오탐과 구멍을 번갈아 냈기 때문에, 시험도
"어떤 명령이 되는가" 가 아니라 "왜 되는가" 를 잡는다.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from unittest import mock

from asgard_hooklib.baseline import harness_owned_command

from asgard.hooks import readonly_guard

CONTRACT = "uv run --no-project python benchmarks/continual-harness/harness.py"
BASELINE = "python3 -m pytest -q"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        os.makedirs(os.path.join(self.root, ".asgard", "quest"))

    def policy(self, **trinity) -> None:
        path = os.path.join(self.root, ".asgard", "asgard-setting-project.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"trinity_policy": trinity}, handle)

    def quest(self, *criteria: str, later: tuple[str, ...] = (), qid: str = "q1") -> None:
        """개봉 기록 하나짜리 퀘스트. `later` 는 그 뒤에 덧붙는 이벤트의 criteria 다."""
        qdir = os.path.join(self.root, ".asgard", "quest")
        with open(os.path.join(qdir, qid + ".jsonl"), "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"role": "thinker", "event": "plan", "criteria": list(criteria)}) + "\n")
            if later:
                handle.write(json.dumps({"role": "verifier", "event": "verify", "criteria": list(later)}) + "\n")
        with open(os.path.join(qdir, "ACTIVE"), "w", encoding="utf-8") as handle:
            handle.write(qid)

    def run_hook(self, command: str, agent: str = "asgard-verifier", tool: str = "Bash", **extra) -> int:
        """훅을 in-process 로 돌린 종료 코드 — claude 프로토콜에서 2 는 차단, 0 은 허용이다."""
        payload = {"agent_type": agent, "tool_name": tool, "tool_input": {"command": command, **extra}}
        payload["cwd"] = self.root
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
            mock.patch("sys.stdout", out),
            mock.patch("sys.stderr", err),
            mock.patch("sys.argv", ["hook"]),
        ):
            try:
                readonly_guard.main()
                return 0
            except SystemExit as exc:
                return int(exc.code or 0)


class TestTheSourceIsWhatOpensIt(Base):
    def test_a_declared_verify_contract_runs(self) -> None:
        """판정자가 채점 기준으로 통보받는 바로 그 명령이다 — 못 돌리면 판정이 우회로 선다."""
        self.quest("벤치가 네 축을 낸다 | verify: %s | artifacts: benchmarks" % CONTRACT)
        self.assertTrue(harness_owned_command(self.root, CONTRACT))
        self.assertEqual(self.run_hook(CONTRACT), 0)

    def test_the_project_baseline_runs(self) -> None:
        """하네스는 PASS 를 적을 때 이 명령을 어차피 돌린다."""
        self.policy(baseline_checks=[BASELINE])
        self.assertTrue(harness_owned_command(self.root, BASELINE))
        self.assertEqual(self.run_hook(BASELINE), 0)

    def test_whitespace_folds_but_arguments_do_not(self) -> None:
        """계약 원문과 정책에 적힌 형태는 들여쓰기로 갈릴 수 있다. 인자는 그렇지 않다."""
        self.quest("벤치 | verify: %s" % CONTRACT)
        self.assertTrue(
            harness_owned_command(self.root, "uv  run --no-project  python benchmarks/continual-harness/harness.py")
        )
        self.assertFalse(harness_owned_command(self.root, CONTRACT + " --json"))
        self.assertEqual(self.run_hook(CONTRACT + " --json"), 2)

    def test_a_baseline_command_past_the_cap_stays_blocked(self) -> None:
        """상한 밖 명령은 하네스도 안 돌린다 — 그러면 이 예외의 근거가 그 명령에는 없다."""
        checks = ["python3 -m compileall app%d.py" % i for i in range(12)]
        self.policy(baseline_checks=checks)
        self.assertTrue(harness_owned_command(self.root, checks[0]))
        self.assertFalse(harness_owned_command(self.root, checks[-1]))


class TestNothingElseWidens(Base):
    def test_without_a_quest_or_policy_nothing_opens(self) -> None:
        self.assertFalse(harness_owned_command(self.root, CONTRACT))
        self.assertEqual(self.run_hook(CONTRACT), 2)

    def test_the_exception_does_not_reach_write_tools(self) -> None:
        """계약 문자열을 들고 있어도 판정자는 파일을 못 고친다 — 완화는 Bash 한 자리다."""
        self.quest("벤치 | verify: %s" % CONTRACT)
        code = self.run_hook("", tool="Edit", file_path=os.path.join(self.root, "app.py"))
        self.assertEqual(code, 2)

    def test_a_write_role_is_unaffected(self) -> None:
        """이 갈래는 읽기전용 역할에만 있다 — 워커는 원래 이 자리에서 안 걸린다."""
        self.assertEqual(self.run_hook(CONTRACT, agent="asgard-worker"), 0)

    def test_an_unreadable_source_does_not_relax(self) -> None:
        """출처를 못 읽으면 막는 쪽이 기본이다 — 완화가 fail-open 이면 그것이 곧 우회다."""
        self.quest("벤치 | verify: %s" % CONTRACT)
        with mock.patch("asgard_hooklib.baseline.detect_checks", side_effect=OSError("boom")):
            self.assertFalse(harness_owned_command(self.root, CONTRACT))

    def test_a_criteria_line_appended_after_the_opening_does_not_open_it(self) -> None:
        """읽기전용 역할은 기장에 criteria 를 덧붙일 수 있다 — 그것을 세면 자기 허용을 자기가 적는다.

        `quest-log.py append --criteria "... | verify: <명령>"` 은 이 레인에서 허용되는 호출이다.
        개봉 기록만 보는 이유가 그것이고, 이 시험이 그 경계를 잡는다."""
        self.quest("실제 기준 하나", later=("자기가 적은 것 | verify: %s" % CONTRACT,))
        self.assertFalse(harness_owned_command(self.root, CONTRACT))
        self.assertEqual(self.run_hook(CONTRACT), 2)


if __name__ == "__main__":
    unittest.main()
