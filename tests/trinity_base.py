#!/usr/bin/env python3
"""Trinity 시험의 공용 토대 — 훅 경로 상수, subprocess 실행기, 임시 repo 픽스처.

실제 훅 스크립트를 subprocess로 실행한다 (임포트가 아니라 배포 형태 그대로) — 사용자 repo에서
python3 <file> 로 도는 것과 동일 경로. 임시 git repo를 만들어 시나리오별 워킹트리 상태를 재현한다.

이 토대를 쓰는 시험은 `tests/test_trinity_*.py` 에 주제별로 나뉘어 있다.
실행: uv run pytest tests/test_trinity_*.py
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
VCONTEXT = os.path.abspath(os.path.join(SRC, "verifier_context.py"))
DCONTEXT = os.path.abspath(os.path.join(SRC, "dispatch_context.py"))
SENTINEL = os.path.abspath(os.path.join(SRC, "write_sentinel.py"))
UCTX = os.path.abspath(os.path.join(SRC, "unattended_context.py"))
SUBGATE = os.path.abspath(os.path.join(SRC, "subagent_gate.py"))


# 자식에게 안 물려주는 것 둘. `ASGARD_UNATTENDED` 는 `run_prompt(json_out=True)` 가 이 프로세스에
# 세우는 Canon 8 헤드리스 신호라, 같은 xdist 워커에서 그 시험이 먼저 돌면 무인 판정이 켜진 채로
# 여기 흘러든다 — 워커 배치가 기계마다 달라 로컬은 초록, 러너는 빨강이 된다.
_NOT_INHERITED = ("CLAUDE_PROJECT_DIR", "ASGARD_UNATTENDED")


def run(script, args=None, stdin="", cwd=None, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in _NOT_INHERITED}
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
        # 정리 실패를 무시한다 — 이 시험들이 부르는 훅은 판정을 돌려준 뒤에도 `<root>/.asgard` 에
        # 상태를 쓰고, 병렬 실행에서 그 쓰기가 tearDown 뒤로 밀리면 rmtree 가 "Directory not empty"
        # 로 죽는다 (26-08-06: 전수 병렬 실행에서 한 건). 검증은 그 전에 이미 끝났고 디렉터리는
        # 버릴 것이라, 여기서 나는 예외는 판정이 아니라 잡음이다.
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = self.tmp.name
        # HOME 격리 — 훅 subprocess가 호스트의 글로벌 git 설정(excludesfile 등)·~/.asgard 상태를
        # 보지 않게 한다. map_current 판정이 호스트 상태에 따라 흔들린 flake 방어 (test_heimdall 관행).
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self.root
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "-C", self.root, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", self.root, "config", "user.name", "t"], check=True)
        self.write("README.md", "hello\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "init"], check=True)

    def tearDown(self):
        if self._home is not None:
            os.environ["HOME"] = self._home
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
            # 기본 증거는 둘 — 깊은 변경의 증거 하한(MIN_DEEP_EVIDENCE)을 지나가야 다른 축을
            # 보는 시험들이 그 하한에 걸려 넘어지지 않는다. 하한 자체는 TestDeepEvidenceFloor 가 본다.
            "commands": commands
            if commands is not None
            else [
                {"cmd": "python3 app.py", "exit_code": 0},
                {"cmd": "python3 -m compileall -q .", "exit_code": 0},
            ],
        }
        args = ["append", "--verdict", verdict, "--session", session]
        if level:
            args += ["--level", level]
        return self.qlog(*args, stdin=json.dumps(body))
