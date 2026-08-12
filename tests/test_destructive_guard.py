"""Canon 3 동의 관문 — 되돌릴 수 없는 자리에서 한 번 멈추고, 동의를 받으면 지나간다.

두 축을 본다. **막아야 할 것을 막는가**, 그리고 **정상 작업을 막지 않는가**. 뒤쪽이 더
중요하다: 오탐이 쌓인 관문은 표기를 바꿔 우회하는 요령만 가르치고, 그렇게 우회되는 관문은
없는 것과 같다. 26-08-13 평가에서 통제 표면 가드가 인용 안쪽 글자를 연산으로 읽어 읽기
명령을 네 번 막았고, 이 파일의 ALLOWED 목록이 같은 실패를 이 관문에서 되풀이하지 않게 한다.

판정 함수와 배포 훅을 둘 다 태운다 — 함수만 보면 배선이 빠져도 초록이 나온다.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from asgard.hooks import git_guard as gg
from asgard.hooks.asgard_hooklib.destructive import consent_given, consent_refusal, consent_token, destructive_reason

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOYED = os.path.join(ROOT, ".claude", "hooks", "git-guard.py")


class TestDestructiveDetection(unittest.TestCase):
    BLOCKED = [
        ("rm -r src/asgard/memory", "recursive delete"),
        ("rm -rf docs", "recursive delete"),
        ("rm -fr /tmp/scratch", "recursive delete"),
        ("rm --recursive data", "recursive delete"),
        ("find . -name '*.tmp' -delete", "find -delete"),
        ("find build -type f -exec rm {} +", "find -exec rm"),
        ('psql -c "DROP DATABASE app"', "destructive DB statement"),
        ('psql -c "drop table users"', "destructive DB statement"),
        ('mysql -e "TRUNCATE TABLE sessions"', "destructive DB statement"),
        ("redis-cli FLUSHALL", "destructive DB statement"),
        ("git merge main", "integration branch"),
        ("git merge origin/main --no-ff", "integration branch"),
        ("git -C /repo merge master", "integration branch"),
        ("python3 -c \"import shutil; shutil.rmtree('build')\"", "tree delete"),
        ("uv run --no-project python -c \"import shutil; shutil.rmtree('x')\"", "tree delete"),
    ]

    # 막으면 안 되는 것 — 읽기, 파일 하나 삭제, 기능 브랜치 병합, 문자열 안의 언급, 그리고
    # 다시 만들어지는 자리 청소. 마지막 축이 없으면 관문이 매 빌드마다 울려 소음이 된다.
    ALLOWED = [
        "rm -rf build",
        "rm -rf node_modules",
        "rm -rf .venv dist",
        "rm -rf __pycache__",
        "rm build/one.txt",
        "rm -f stale.lock",
        "ls -R src",
        "grep -rn 'DROP TABLE' migrations/",
        "cat schema.sql",
        "git merge feature/login",
        "git merge --abort",
        "git merge --continue",
        "python3 -c \"print('shutil.rmtree is what we are documenting')\"",
        "python3 cleanup.py",
        "echo 'rm -rf everything'",
        "codex exec 'explain why rm -rf build is dangerous'",
        "find . -name '*.py' -print",
        "uv run --no-project python -m pytest tests/ -q",
    ]

    def test_blocked(self):
        for command, needle in self.BLOCKED:
            with self.subTest(command=command):
                reason = destructive_reason(command)
                self.assertIsNotNone(reason, f"파괴 연산을 놓쳤다: {command}")
                # 위 단언이 None 을 이미 걷었다. `or ""` 는 판독기가 그 좁힘을 못 따라와서 붙인다.
                self.assertIn(needle, reason or "")

    def test_allowed(self):
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertIsNone(destructive_reason(command), f"정상 명령을 막았다: {command}")


class TestConsentToken(unittest.TestCase):
    def test_token_admits_its_own_command(self):
        command = "rm -rf build"
        token = consent_token(command)
        self.assertTrue(consent_given(f"ASGARD_CONSENT={token} {command}"))

    def test_token_does_not_carry_to_another_command(self):
        token = consent_token("rm -rf build")
        self.assertFalse(consent_given(f"ASGARD_CONSENT={token} rm -rf src"))

    def test_whitespace_does_not_change_the_token(self):
        self.assertEqual(consent_token("rm  -rf   build"), consent_token("rm -rf build"))

    def test_missing_or_wrong_token_is_not_consent(self):
        self.assertFalse(consent_given("rm -rf build"))
        self.assertFalse(consent_given("ASGARD_CONSENT=deadbeef00 rm -rf build"))

    def test_refusal_carries_the_token_the_caller_must_use(self):
        command = "rm -rf build"
        message = consent_refusal("recursive delete (build)", command)
        self.assertIn(consent_token(command), message)
        self.assertIn("ASGARD_CONSENT", message)


def _run_inprocess(command: str) -> tuple[int, str, str]:
    payload = {"tool_input": {"command": command}, "cwd": ROOT}
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
        mock.patch("sys.stdout", out),
        mock.patch("sys.stderr", err),
    ):
        try:
            gg.main()
        except SystemExit as exc:
            return int(exc.code or 0), out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


class TestHookSurface(unittest.TestCase):
    """배선 — 판정이 실제 훅의 종료 코드로 나오는가."""

    def test_blocks_then_admits_with_consent(self):
        command = "rm -rf /tmp/asgard-test-payload"
        code, _, err = _run_inprocess(command)
        self.assertEqual(code, 2, "파괴 명령이 훅을 그대로 통과했다")
        self.assertIn("ASGARD_CONSENT", err)
        token = consent_token(command)
        code, _, _ = _run_inprocess(f"ASGARD_CONSENT={token} {command}")
        self.assertEqual(code, 0, "동의를 달고 온 호출이 여전히 막혔다")

    def test_hard_blocks_have_no_consent_lane(self):
        """git-guard 의 기존 표는 동의로 열리지 않는다 — 그 자리는 되돌릴 수 없다."""
        code, _, err = _run_inprocess("git reset --hard HEAD~3")
        self.assertEqual(code, 2)
        self.assertNotIn("ASGARD_CONSENT", err)
        token = consent_token("git reset --hard HEAD~3")
        code, _, _ = _run_inprocess(f"ASGARD_CONSENT={token} git reset --hard HEAD~3")
        self.assertEqual(code, 2, "하드 블록이 동의 토큰으로 열렸다")

    def test_cursor_protocol_denies_with_a_message(self):
        payload = {"command": "rm -rf /tmp/asgard-test-payload"}
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
            mock.patch("sys.stdout", out),
            mock.patch("sys.stderr", err),
        ):
            with self.assertRaises(SystemExit) as ctx:
                gg.main()
        self.assertEqual(int(ctx.exception.code or 0), 0)
        body = json.loads(out.getvalue())
        self.assertEqual(body["permission"], "deny")
        self.assertIn("ASGARD_CONSENT", body["agent_message"])

    def test_deployed_copy_enforces_the_same_verdict(self):
        """배포본을 별도 프로세스로 태운다 — 패키지만 고치면 실제로 도는 훅은 안 바뀐다."""
        command = "rm -rf /tmp/asgard-test-payload"
        proc = subprocess.run(
            [sys.executable, DEPLOYED],
            input=json.dumps({"tool_input": {"command": command}, "cwd": ROOT}),
            capture_output=True,
            text=True,
            cwd=ROOT,
            env={**os.environ, "CLAUDE_PROJECT_DIR": ROOT},
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn(consent_token(command), proc.stderr)


if __name__ == "__main__":
    unittest.main()
