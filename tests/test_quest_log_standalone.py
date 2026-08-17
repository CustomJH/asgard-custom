"""배포 사본 계약 — `hooks/quest_log.py`는 asgard 없이도 자기 일을 한다.

`tests/architecture/test_layered.py`의 훅 시험 둘은 이 계약을 **모양**으로 본다: 상대 임포트가 없는지,
try 밖에서 asgard를 부르지 않는지, 3.9 문법으로 파싱되는지. 셋 다 AST 검사라 "실제로 도는가"는
아직 아무도 안 묻는다. 이 시험이 그 자리를 맡는다 — 파일을 다른 디렉터리에 복사하고 `asgard`
임포트가 반드시 실패하는 환경에서 CLI를 통째로 태운다.

훅 계약이 fail-open이라 배포 사본의 죽음은 조용하다: 사용자는 퀘스트 로그가 켜진 줄 알고
아무 일도 안 일어난다. 그 침묵을 여기서 깬다.

`asgard`를 못 찾게 만드는 방법은 설치 위치에 기대지 않는다. 임포트하면 곧장 실패하는 스텁
패키지를 PYTHONPATH 맨 앞에 둔다 — venv든 user site든 editable든, 무엇이 설치돼 있어도 같은
결과가 나온다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from asgard.hooks import library_files, script

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "asgard", "hooks", "quest_log.py")
COMMANDS = (
    "open",
    "append",
    "state",
    "replay",
    "next",
    "close",
    "verify-baseline",
    "ticket-claim",
    "ticket-heartbeat",
    "ticket-finish",
    "ticket-recover",
)


class TestDeployedCopyRunsWithoutAsgard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        blocked = os.path.join(self.tmp, "blocked", "asgard")
        os.makedirs(blocked)
        with open(os.path.join(blocked, "__init__.py"), "w", encoding="utf-8") as handle:
            handle.write('raise ImportError("asgard is not installed in this environment")\n')
        # setup이 쓰는 이름 그대로, setup이 쓰는 목록 그대로 깐다 — 배포되는 것은
        # `.claude/hooks/quest-log.py` **와** 그 옆의 `asgard_hooklib/` 다. 목록을 여기 손으로
        # 적으면 배포 표에 파일이 하나 늘 때 이 시험만 옛 배치를 계속 증명한다.
        hooks_dir = os.path.join(self.tmp, "hooks")
        self.tool = os.path.join(hooks_dir, "quest-log.py")
        os.makedirs(hooks_dir)
        for path, body in [("quest-log.py", script("quest-log")), *library_files()]:
            full = os.path.join(hooks_dir, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as handle:
                handle.write(body)
        self.root = os.path.join(self.tmp, "repo")
        os.makedirs(self.root)
        with open(os.path.join(self.root, "app.py"), "w", encoding="utf-8") as handle:
            handle.write("def add(a, b):\n    return a + b\n")
        for args in (
            ["init", "-q", "-b", "main"],
            ["config", "user.email", "probe@example.com"],
            ["config", "user.name", "probe"],
            ["add", "-A"],
            ["commit", "-q", "-m", "seed"],
        ):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def run_tool(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ, PYTHONPATH=os.path.join(self.tmp, "blocked"), CLAUDE_SESSION_ID="standalone")
        env.pop("ASGARD_UNATTENDED", None)
        return subprocess.run(
            [sys.executable, self.tool, *args],
            cwd=self.root,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_the_stub_really_blocks_the_package(self):
        """스텁이 안 먹으면 이 파일의 나머지 시험은 아무것도 증명하지 않는다."""
        env = dict(os.environ, PYTHONPATH=os.path.join(self.tmp, "blocked"))
        proc = subprocess.run(
            [sys.executable, "-c", "import asgard"], env=env, capture_output=True, text=True, timeout=60
        )
        self.assertNotEqual(proc.returncode, 0, "asgard가 여전히 임포트된다 — 이 시험은 무의미하다")

    def test_a_write_quest_runs_end_to_end(self):
        """개설 → 작업 → PASS 판정 → 종료. 배포 사본만으로 한 바퀴가 돌아야 한다."""
        opened = self.run_tool("open", "q1", "--criteria", "add stays total")
        self.assertEqual(opened.returncode, 0, opened.stderr)
        self.assertEqual(json.loads(opened.stdout)["opened"], "q1")

        state = self.run_tool("state")
        self.assertEqual(state.returncode, 0, state.stderr)
        self.assertEqual(json.loads(state.stdout)["quest_id"], "q1")

        nxt = self.run_tool("next", "--write-expected")
        self.assertEqual(nxt.returncode, 0, nxt.stderr)
        self.assertEqual(json.loads(nxt.stdout)["next_role"], "WORKER")

        with open(os.path.join(self.root, "app.py"), "a", encoding="utf-8") as handle:
            handle.write("\n\ndef zero():\n    return 0\n")
        work = self.run_tool(
            "append",
            "--role",
            "worker",
            "--event",
            "work",
            stdin=json.dumps({"commands": [{"cmd": "pytest -q", "exit_code": 0}]}),
        )
        self.assertEqual(work.returncode, 0, work.stderr)

        verify = self.run_tool(
            "append",
            "--role",
            "verifier",
            "--event",
            "verify",
            "--verdict",
            "PASS",
            "--level",
            "full",
            stdin=json.dumps({"commands": [{"cmd": "pytest -q", "exit_code": 0}]}),
        )
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertEqual(json.loads(verify.stdout)["verdict"], "PASS")

        closed = self.run_tool("close", "q1")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertEqual(json.loads(closed.stdout)["closed"], "q1")

        events = self._events("q1")
        self.assertEqual([e["event"] for e in events], ["plan", "work", "verify", "quest_closed"])
        # 종료 이벤트는 자기가 딛고 선 PASS를 가리켜야 한다 — 안 그러면 게이트가 대조할 것이 없다.
        self.assertEqual(events[-1].get("verification_id"), events[-2].get("verification_id"))

    def test_the_ticket_runtime_needs_the_claim_token(self):
        """토큰 없이 남의 lease를 밀 수 있으면 lease는 소유권이 아니라 권고가 된다."""
        self.assertEqual(self.run_tool("open", "q2").returncode, 0)
        todo = self.run_tool(
            "append",
            "--role",
            "thinker",
            "--event",
            "ticket",
            stdin=json.dumps({"unit": "u1", "ticket_status": "todo", "files": ["app.py"], "access": []}),
        )
        self.assertEqual(todo.returncode, 0, todo.stderr)

        claimed = self.run_tool("ticket-claim", "--unit", "u1", "--worker", "w1")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        token = json.loads(claimed.stdout)["claim_token"]

        denied = self.run_tool("ticket-finish", "--unit", "u1", "--status", "done")
        self.assertEqual(denied.returncode, 1)
        self.assertEqual(json.loads(denied.stderr)["error"], "claim token mismatch")

        finished = self.run_tool("ticket-finish", "--unit", "u1", "--claim-token", token, "--status", "done")
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertEqual(json.loads(finished.stdout)["status"], "done")

    def test_reopening_one_id_is_refused(self):
        """한 id는 한 실행이다 — 재개설은 수용 계약 둘을 한 원장에 섞는다."""
        self.assertEqual(self.run_tool("open", "q3").returncode, 0)
        again = self.run_tool("open", "q3")
        self.assertEqual(again.returncode, 1)
        self.assertIn("already exists", json.loads(again.stderr)["error"])

    def test_every_command_reaches_a_branch(self):
        """명령마다 갈래가 있어야 한다 — 없는 명령은 argparse가, 빠진 갈래는 트레이스백이 드러낸다."""
        self.assertEqual(self.run_tool("open", "q4").returncode, 0)
        for cmd in COMMANDS:
            proc = self.run_tool(cmd, "--unit", "u1") if cmd.startswith("ticket-") else self.run_tool(cmd, "q4")
            self.assertNotIn("Traceback", proc.stderr, f"{cmd}: 배포 사본이 죽었다\n{proc.stderr}")
            self.assertIn(proc.returncode, (0, 1, 2), f"{cmd}: 뜻 없는 종료 코드 {proc.returncode}")

    def _events(self, qid: str) -> list[dict]:
        path = os.path.join(self.root, ".asgard", "quest", qid + ".jsonl")
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


if __name__ == "__main__":
    unittest.main()
