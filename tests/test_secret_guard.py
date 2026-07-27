"""Canon 4 양쪽 절반 — 쓰기(내용이 근거)와 읽기(이름이 근거).

읽기 측이 왜 게이트여야 하고 마스킹이 아닌가: 네이티브 루프는 도구 출력을 그대로 messages 에
넣고 매 턴 프로바이더로 재전송한다. 읽고 나서 가리는 것은 이미 나간 뒤다. 그래서 이 파일의
테스트는 두 축을 본다 — **막아야 할 것을 막는가**, 그리고 **정상 작업을 막지 않는가**.
뒤쪽이 더 중요하다: 오탐이 쌓인 게이트는 꺼지고, 꺼진 게이트는 없는 것과 같다.
"""

from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from asgard.hooks import secret_guard as sg


def _run(payload: dict, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
        mock.patch("sys.stdout", out),
        mock.patch("sys.stderr", err),
        mock.patch("sys.argv", ["hook", *argv]),
    ):
        try:
            sg.main()
        except SystemExit as exc:
            return int(exc.code or 0), out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


class TestSecretPath(unittest.TestCase):
    """이름만으로 자격 저장소임이 증명되는 파일."""

    BLOCKED = [
        (".env", "dotenv"),
        (".env.local", "dotenv"),
        ("config/.env.production", "dotenv"),
        ("/home/u/.netrc", ".netrc"),
        (".pgpass", ".pgpass"),
        (".git-credentials", "git credential store"),
        ("/Users/x/.aws/credentials", "AWS credentials"),
        (".ssh/id_ed25519", "ssh private key"),
        (".ssh/id_rsa", "ssh private key"),
        ("keys/deploy_ed25519", "ssh private key"),
        ("certs/server.pem", "key material"),
        ("app/release.jks", "key material"),
        ("secrets.yaml", "credential file"),
        ("credentials.json", "credential file"),
        ("gcp-service-account.json", "service account key"),
    ]
    ALLOWED = [
        ".env.example",
        ".env.sample",
        ".env.template",
        "secrets.example.yaml",
        "credentials.yaml.template",
        "k8s/secret.tpl.yaml",
        ".ssh/id_ed25519.pub",  # 공개키 — 핑거프린트 확인은 정상 작업
        ".ssh/authorized_keys",
        "src/environment.ts",
        "docs/env.md",
        "src/keys.py",
        "README.md",
        "package.json",
        ".npmrc",  # 설정과 자격이 섞이는 파일 — 증명 불가라 의도적으로 통과
        ".docker/config.json",
    ]

    def test_credential_stores_are_named(self):
        for path, label in self.BLOCKED:
            self.assertEqual(sg.secret_path(path), label, path)

    def test_ordinary_and_template_paths_pass(self):
        for path in self.ALLOWED:
            self.assertEqual(sg.secret_path(path), "", path)

    def test_windows_separators_are_judged_the_same(self):
        self.assertEqual(sg.secret_path(r"C:\proj\.env"), "dotenv")
        self.assertEqual(sg.secret_path(r"C:\proj\.env.example"), "")

    def test_empty_path_is_not_a_secret(self):
        self.assertEqual(sg.secret_path(""), "")


class TestSecretCommand(unittest.TestCase):
    BLOCKED = [
        "cat .env",
        "head -5 .env.local",
        "tail -3 config/.env",
        "sudo cat /root/.netrc",
        "strings ~/.ssh/id_rsa",
        "openssl rsa -in certs/server.pem",
        "env",
        "printenv",
        "env | sort",
        "env | tee /tmp/dump",
        "env | grep -i key",
        "env | grep -i TOKEN",
        "printenv AWS_SECRET_ACCESS_KEY",
        "security find-generic-password -s github",
        "security find-internet-password -s x",
        "gcloud auth print-access-token",
        "gcloud auth print-identity-token",
        "aws configure get aws_secret_access_key",
        "kubectl get secret db -o yaml",
        "echo start && cat .env",
    ]
    ALLOWED = [
        "cat .env.example",
        "cat src/app.py",
        "ls -la",
        "grep -rn TODO src/",
        "npm run build",
        "env FOO=1 npm test",
        "NODE_ENV=prod npm run build",
        "git config --list",  # 토큰이 섞일 수 있을 뿐 — 증명 불가, 정상 사용이 압도적
        "git status",
        "printenv PATH",
        "printenv HOME",
        "env | grep -i asgard",  # 필터가 먼저 걸린다 — 전체 환경은 안 나간다
        "env | grep TMPDIR",
        "env | grep -ci anthropic || true",
        "gcloud auth list",
        "aws s3 ls",
        "kubectl get pods",
        "cat .ssh/id_ed25519.pub",
        "docker compose up -d",
        "pytest tests/ -q",
    ]

    def test_credential_dumps_are_blocked(self):
        for command in self.BLOCKED:
            self.assertTrue(sg.secret_command(command), command)

    def test_ordinary_commands_pass(self):
        for command in self.ALLOWED:
            self.assertEqual(sg.secret_command(command), "", command)

    def test_pipe_into_a_filter_is_not_a_dump(self):
        """실코퍼스에서 히트 23건 중 다수가 이 형상이었다 — 규칙이 아니라 계측이 틀렸던 자리."""
        self.assertEqual(sg.secret_command("env | grep -i linear"), "")
        self.assertTrue(sg.secret_command("env | grep -i password"))
        # grep 이 아닌 하류는 전량이 흐른다 — 필터가 아니다
        self.assertTrue(sg.secret_command("env | sort"))
        self.assertTrue(sg.secret_command("env | head"))

    def test_alternatives_are_separate_entries_not_one_and_group(self):
        """한 튜플에 대안을 섞으면 AND 가 걸려 아무것도 안 잡힌다 (탐침이 잡은 결함)."""
        self.assertTrue(sg.secret_command("security find-generic-password -s a"))
        self.assertTrue(sg.secret_command("security find-internet-password -s a"))

    def test_unlexable_command_is_allowed(self):
        # 판정 불능은 허용 — 렉싱 실패로 모든 shell 이 막히면 가드가 세션을 인질로 잡는다
        self.assertEqual(sg.secret_command("cat 'unterminated"), "")

    def test_empty_command_is_allowed(self):
        self.assertEqual(sg.secret_command(""), "")


class TestHookReadSide(unittest.TestCase):
    def test_read_of_dotenv_is_blocked_in_every_mode(self):
        payload = {"tool_name": "Read", "tool_input": {"file_path": "/p/.env"}}
        self.assertEqual(_run(payload, [])[0], 2)
        self.assertEqual(_run(payload, ["codex"])[0], 2)
        code, out, _ = _run(payload, ["cursor"])
        self.assertEqual((code, json.loads(out)["permission"]), (0, "deny"))

    def test_read_of_template_passes(self):
        payload = {"tool_name": "Read", "tool_input": {"file_path": "/p/.env.example"}}
        self.assertEqual(_run(payload, [])[0], 0)
        code, out, _ = _run(payload, ["cursor"])
        self.assertEqual((code, json.loads(out)["permission"]), (0, "allow"))

    def test_bash_credential_dump_is_blocked(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "cat .env"}}
        code, _, err = _run(payload, [])
        self.assertEqual(code, 2)
        self.assertIn("Canon Law 4", err)
        self.assertIn("provider", err)  # 왜 막는지가 메시지에 있어야 재작업을 안내한다

    def test_bash_ordinary_command_passes(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}}
        self.assertEqual(_run(payload, [])[0], 0)

    def test_grep_over_a_credential_store_is_blocked(self):
        payload = {"tool_name": "Grep", "tool_input": {"path": "/p/.aws/credentials"}}
        self.assertEqual(_run(payload, [])[0], 2)


class TestHookWriteSideUnchanged(unittest.TestCase):
    """읽기 측을 얹으면서 기존 쓰기 판정이 흔들리면 안 된다."""

    def test_secret_content_still_blocked(self):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "AKIAABCDEFGHIJKLMNOP"}}
        self.assertEqual(_run(payload, [])[0], 2)

    def test_dotenv_write_still_blocked(self):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "app/.env", "content": "X=1"}}
        code, _, err = _run(payload, [])
        self.assertEqual(code, 2)
        self.assertIn("write blocked", err)

    def test_clean_write_still_passes(self):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "x = 1"}}
        self.assertEqual(_run(payload, [])[0], 0)

    def test_payload_without_tool_name_keeps_legacy_behaviour(self):
        """구 스캐폴드는 tool_name 을 안 싣는다 — 그 페이로드도 그대로 판정돼야 한다."""
        self.assertEqual(_run({"tool_input": {"file_path": "a.py", "content": "x = 1"}}, [])[0], 0)
        self.assertEqual(_run({"tool_input": {"file_path": "a.py", "content": "ghp_" + "a" * 36}}, [])[0], 2)
        self.assertEqual(_run({"tool_input": {"file_path": ".env", "content": "X=1"}}, [])[0], 2)

    def test_broken_stdin_is_fail_open(self):
        with (
            mock.patch("sys.stdin", io.StringIO("not json")),
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.argv", ["hook"]),
        ):
            with self.assertRaises(SystemExit) as ctx:
                sg.main()
            self.assertEqual(int(ctx.exception.code or 0), 0)


if __name__ == "__main__":
    unittest.main()
