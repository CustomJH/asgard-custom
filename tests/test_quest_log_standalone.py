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

import ast
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from asgard.hooks import library_files, script
from asgard.hooks.asgard_hooklib.ledger import EVENT_FIELDS, HARNESS_FIELDS, normalize

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "asgard", "hooks", "quest_log.py")
COMMANDS = (
    "open",
    "append",
    "state",
    "replay",
    "next",
    "close",
    "verify-baseline",
    "amend-criteria",
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
            # 단위의 파일 목록은 이벤트에 `changed_files` 로 들어간다 (`heimdall/ticket_lease.py:51`).
            # `files` 는 계획 구조와 `fold_tickets` 의 접힌 뷰가 쓰는 이름이라 여기서는 버려진다.
            stdin=json.dumps({"unit": "u1", "ticket_status": "todo", "changed_files": ["app.py"], "access": []}),
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

    def test_a_field_the_schema_drops_is_refused_not_swallowed(self):
        """스키마 밖 필드를 조용히 버리면 쓴 쪽과 읽는 쪽의 기록이 갈린다.

        판정자는 이 로그만 읽는다. 워커가 `summary` 에 적은 근거가 사라지면 판정은 근거가 없다고
        읽고, 워커는 적었다고 본다 — 그렇게 FAIL 이 한 번 났다. 거절이 그 침묵을 쓰는 쪽으로
        되돌린다.
        """
        self.assertEqual(self.run_tool("open", "q5", "--criteria", "add stays total").returncode, 0)
        refused = self.run_tool(
            "append",
            "--role",
            "worker",
            "--event",
            "work",
            stdin=json.dumps({"summary": "오딘이 범위를 좁혔다", "commands": []}),
        )
        self.assertEqual(refused.returncode, 2, refused.stdout)
        self.assertIn("summary", refused.stderr, "버려질 필드 이름을 안 말하면 쓴 쪽이 뭘 고칠지 모른다")
        self.assertIn("subtask", refused.stderr, "갈 곳을 안 말하는 거절은 막다른 길이다")
        self.assertEqual([e["event"] for e in self._events("q5")], ["plan"], "거절된 append가 기록을 늘렸다")

        accepted = self.run_tool(
            "append",
            "--role",
            "worker",
            "--event",
            "work",
            stdin=json.dumps({"subtask": "오딘이 범위를 좁혔다", "commands": []}),
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(self._events("q5")[-1]["subtask"], "오딘이 범위를 좁혔다")

    def _events(self, qid: str) -> list[dict]:
        path = os.path.join(self.root, ".asgard", "quest", qid + ".jsonl")
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


class TestEventFieldsCoversNormalize(unittest.TestCase):
    """`EVENT_FIELDS` 가 `normalize` 보다 좁아지면 그 키는 다시 조용히 버려진다.

    집합을 손으로 베껴 둔 시험은 다음 사람이 `normalize` 에 키를 더할 때 같이 낡는다. 그래서
    목록을 대조하지 않고 `normalize` 의 소스를 읽어 그것이 실제로 꺼내는 키를 뽑는다.
    """

    def _keys_normalize_reads(self) -> set[str]:
        fn = ast.parse(textwrap.dedent(inspect.getsource(normalize))).body[0]
        keys: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                target = node.func.value
                if isinstance(target, ast.Name) and target.id == "ev" and node.args:
                    if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        keys.add(node.args[0].value)
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "ev":
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    keys.add(node.slice.value)
            # `for key in ("a", "b"): ev.get(key)` — 이름으로 꺼내는 자리는 상수 튜플에서 읽는다.
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):
                for element in node.iter.elts:
                    if isinstance(element, ast.Constant) and isinstance(element.value, str):
                        keys.add(element.value)
        return keys

    def test_the_scan_finds_something(self):
        """스캔이 비면 아래 시험은 아무것도 증명하지 않는다."""
        self.assertGreater(len(self._keys_normalize_reads()), 20)

    def test_every_key_normalize_reads_is_declared(self):
        missing = sorted(self._keys_normalize_reads() - EVENT_FIELDS)
        self.assertEqual(missing, [], f"normalize가 읽지만 EVENT_FIELDS에 없다 — append가 이 키를 거절한다: {missing}")

    def test_harness_owned_names_are_not_caller_writable(self):
        """한 이름이 양쪽에 있으면 하네스가 쓰는 칸을 호출자도 쓴다는 뜻이라 둘 다 거짓이 된다."""
        self.assertEqual(sorted(HARNESS_FIELDS & EVENT_FIELDS), [])

    def test_no_declared_key_is_unread(self):
        """읽지 않는 키를 선언해 두면 append가 받아 놓고 normalize가 버린다 — 원래 결함 그대로다."""
        stale = sorted(EVENT_FIELDS - self._keys_normalize_reads())
        self.assertEqual(stale, [], f"EVENT_FIELDS에 있지만 normalize가 안 읽는다: {stale}")


if __name__ == "__main__":
    unittest.main()
