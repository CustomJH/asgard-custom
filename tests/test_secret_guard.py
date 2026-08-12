"""Canon 4 양쪽 절반 — 쓰기(내용이 근거)와 읽기(이름이 근거).

읽기 측이 왜 게이트여야 하고 마스킹이 아닌가: 네이티브 루프는 도구 출력을 그대로 messages에
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

# 이 파일 자신이 가드에 걸리지 않게 조립한다 — 자격 파일 이름을 리터럴로 적으면 이 시험을
# 여는 명령이 곧 유출로 읽힌다.
DOTENV = chr(46) + "env"


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

    # 26-08-05 감사가 통과시킨 형태들. 판정이 **고정된 도구 이름 집합**이라, 같은 파일을 같은
    # 목적으로 읽는 다른 도구는 전부 빠져나갔다. 확장이 커진 만큼 오탐도 ALLOWED 로 함께 잰다.
    # 패턴형 판독기는 첫 비플래그 인자가 **찾을 글자**다 — 그것을 경로로 읽으면 평범한 조사가
    # 막힌다. 확장이 커진 만큼 이 방향도 같이 잰다 (26-08-05 재판정이 재현한 오탐).
    PATTERN_NOT_PATH = [
        "grep -rn database.key src/",
        "rg -n database.key .",
        "grep -rn credentials.json src/",
        "awk '/secrets.yaml/ {print}' notes.md",
        "jq .credentials package.json",
    ]

    def test_a_search_pattern_is_not_a_path(self):
        for command in self.PATTERN_NOT_PATH:
            with self.subTest(command=command):
                self.assertEqual(sg.secret_command(command), "", command)

    BYPASSES = [
        "sed -n 1p .env",
        "awk '{print}' .env",
        "grep . .env",
        "cut -d= -f2 .env",
        "sort .env",
        "cp .env /tmp/leak.txt",
        "tar cf - .env",
        "jq . .env",
        "diff .env other.txt",
        "F=.env; cat $F",  # 피연산자가 변수 뒤에 숨는다
        "while read l; do echo $l; done < .env",  # 표준 입력으로 흘려보낸다
        "cat .env*",  # 글롭이 경로 정규식의 `$` 앵커를 깬다
        "python3 -c \"print(open('.env').read())\"",  # 문자열이 다시 코드가 된다
    ]

    def test_the_bypasses_the_fixed_name_set_let_through(self):
        for command in self.BYPASSES:
            with self.subTest(command=command):
                self.assertTrue(sg.secret_command(command), command)

    def test_a_dotted_identifier_is_not_a_key_file(self):
        """불투명 레인이 명령문 글자를 훑는 값이다 — 점 찍힌 **식별자**까지 경로로 읽으면 안 된다.

        `cfg.get('database.key')` 가 `.key` 확장자에 걸려 읽기 전용 스니펫이 거부됐다
        (26-08-05 판정자 재현). 확장자만 보고 붙는 이름표는 경로처럼 생겼을 때만 받는다."""
        for command in (
            "python3 -c \"print(cfg.get('database.key'))\"",
            "python3 -c \"d.get('api.key')\"",
            'python3 -c "print(settings.cache.key)"',
        ):
            with self.subTest(command=command):
                self.assertEqual(sg.secret_command(command), "", command)
        # 좁힌 만큼 진짜 키 파일이 새지 않는지 같이 잰다 — 구분자가 있으면 그대로 걸린다.
        for command in (
            "python3 -c \"open('certs/server.pem').read()\"",
            "sh -c 'cat ~/.aws/credentials'",
            "python3 -c \"print(open('.env').read())\"",
        ):
            with self.subTest(command=command):
                self.assertTrue(sg.secret_command(command), command)

    # 래퍼 × 자격 경로 전수 대조. 패턴을 하나씩 세는 시험은 다음 래퍼에서 또 뚫린다 —
    # 세 턴 연속 그렇게 뚫렸다 (26-08-05). 고정할 것은 목록이 아니라 **불변식**이다:
    # 감싼 형태와 안 감싼 형태의 답이 갈리면 감싸는 것이 곧 우회다.
    WRAPPERS = [
        "sh -c '%s'",
        'bash -c "%s"',
        "sh -ec '%s'",
        "sh -cx '%s'",
        "zsh -c '%s'",
        "eval '%s'",
        "echo %s | sh",
        "echo %s | bash",
    ]
    # 파일 판독기와 **패턴형 판독기**를 같이 넣는다 — 4차 판정이 잡은 구멍이 정확히 여기였다:
    # 판정이 "이 명령이 파일을 여는가"였던 탓에 패턴형은 그 조건을 영영 만족 못 해,
    # `grep -a PRIVATE bundle.p12` 가 감싸면 통과하고 안 감싸면 막혔다.
    CRED_READS = [
        "cat .env",
        "cat certs/server.key",
        "cat certs.pem",
        "head -1 .pgpass",
        "cat .git-credentials",
        "grep -a PRIVATE bundle.p12",
        "jq . store.jks",
        "sed -n 1p certs/id.key",
    ]

    def test_no_wrapper_unblocks_a_credential_read(self):
        for bare in self.CRED_READS:
            with self.subTest(command=bare):
                self.assertTrue(sg.secret_command(bare), bare)
            for wrapper in self.WRAPPERS:
                command = wrapper % bare
                with self.subTest(command=command):
                    self.assertTrue(sg.secret_command(command), command)

    def test_the_opaque_table_matches_its_twin_in_git_guard(self):
        """두 가드가 같은 질문에 다른 답을 들면, 한쪽에서 막힌 것이 다른 쪽에서는 통과한다.

        실제로 그랬다 — secret 쪽에만 파이프 실행이 빠져 있었다. 훅은 배포 디렉터리에서 서로를
        임포트하지 못하므로(파일 이름이 붙임표다) 같은 글자를 두 벌 두고 여기서 동일성을 잡는다."""
        from asgard.hooks import git_guard as gg

        self.assertEqual(sg._OPAQUE_CORE, gg._OPAQUE_CORE)

    def test_a_file_reader_elsewhere_does_not_promote_a_dotted_identifier(self):
        """판정은 토큰 자신만 본다 — 명령 어딘가의 판독기 이름이 다른 낱말을 키 파일로 올리면,
        같은 검사가 구멍과 오탐을 동시에 만든다 (26-08-05 4차 판정)."""
        for command in (
            "sh -c 'cat src/config.py | grep api.key'",
            "sh -c 'diff old.txt new.txt && echo signing.key'",
            "sh -c 'echo database.key'",
        ):
            with self.subTest(command=command):
                self.assertEqual(sg.secret_command(command), "", command)

    def test_a_language_reader_idiom_is_a_file_read(self):
        self.assertTrue(sg.secret_command("ruby -e 'puts File.read(\"certs/server.key\")'"))
        self.assertTrue(sg.secret_command("node -e \"require('fs').readFileSync('certs/server.pem')\""))

    def test_the_one_shape_this_lane_deliberately_lets_through(self):
        """의도한 잔여 한계를 **시험으로 고정**한다 — 우연히 뚫린 것과 구분되게.

        경로 없는 `*.key` 하나만, 그것도 셸 래퍼로 감쌌을 때만 통과한다. 그 확장자는 설정 키
        이름과 글자로 구분되지 않고(`database.key`), 불투명 명령 안에서 토큰 자리를 알려면
        문자열을 다시 파싱해야 하는데 그건 이 훅이 안 하기로 한 일이다. 오탐 0을 지키는 대가로
        이 한 칸을 남긴다 — 상향 경로는 소스의 `lagom:` 주석에 있다."""
        ext = "." + "key"
        self.assertEqual(sg.secret_command("sh -c 'cat id%s'" % ext), "")  # 남긴 한 칸
        self.assertTrue(sg.secret_command("cat id%s" % ext))  # 안 감싸면 잡힌다
        self.assertTrue(sg.secret_command("sh -c 'cat certs/id%s'" % ext))  # 경로가 붙으면 잡힌다
        self.assertTrue(sg.secret_command("sh -c 'cat id.pem'"))  # 다른 키 확장자는 이름만으로 잡힌다

    def test_wrapping_a_read_does_not_unblock_it(self):
        """감싼 형태와 안 감싼 형태의 답이 갈리면 감싸는 것이 곧 우회다.

        `test_no_wrapper_unblocks_a_credential_read` 가 행렬로 같은 불변식을 재고, 여기는
        읽었을 때 뜻이 바로 보이는 짝 몇 개를 남긴다."""
        for bare, wrapped in (
            ("cat certs/server.key", 'sh -c "cat certs/server.key"'),
            ("cat certs.pem", 'eval "cat certs.pem"'),
            ("cat bundle.p12", "python3 -c \"open('bundle.p12').read()\""),
        ):
            with self.subTest(command=wrapped):
                self.assertTrue(sg.secret_command(bare), bare)
                self.assertTrue(sg.secret_command(wrapped), wrapped)

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
        # grep이 아닌 하류는 전량이 흐른다 — 필터가 아니다
        self.assertTrue(sg.secret_command("env | sort"))
        self.assertTrue(sg.secret_command("env | head"))

    def test_alternatives_are_separate_entries_not_one_and_group(self):
        """한 튜플에 대안을 섞으면 AND가 걸려 아무것도 안 잡힌다 (탐침이 잡은 결함)."""
        self.assertTrue(sg.secret_command("security find-generic-password -s a"))
        self.assertTrue(sg.secret_command("security find-internet-password -s a"))

    def test_unlexable_command_is_allowed(self):
        # 판정 불능은 허용 — 렉싱 실패로 모든 shell이 막히면 가드가 세션을 인질로 잡는다
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

    def test_the_same_literal_written_through_bash_is_blocked_too(self):
        """`content`/`new_string`/`patch` 필드만 보던 판은 Bash 로 적은 자격 증명을 검사조차
        하지 않았다 — 같은 리터럴을 `Write` 툴로 쓰면 거부되는데 (26-08-05 감사). 명령문에 든
        순간 이미 전사에 들어간 것이라, 파일에 닿기 전에 막는 것이 이 계약의 요점이다.

        리터럴은 조립해서 쓴다 — 이 파일 자신이 자기 시험에 걸리지 않게."""
        aws = "AKIA" + "ABCDEFGHIJKLMNOP"
        pat = "ghp" + "_" + "a" * 36
        cred = "pass" + "word=hunter2secret"
        for command in (f"echo {aws} > creds.txt", f"printf {pat} >> notes.md", f'echo "{cred}" > cfg.ini'):
            with self.subTest(command=command):
                code, _, err = _run({"tool_name": "Bash", "tool_input": {"command": command}}, [])
                self.assertEqual(code, 2, command)
                self.assertIn("possible secret", err)

    def test_ordinary_commands_are_not_read_as_credentials(self):
        for command in ("python3 -m pytest -q", "pytest -k password_reset_flow", "grep -rn password src/"):
            with self.subTest(command=command):
                self.assertEqual(_run({"tool_name": "Bash", "tool_input": {"command": command}}, [])[0], 0, command)

    def test_dotenv_write_still_blocked(self):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "app/.env", "content": "X=1"}}
        code, _, err = _run(payload, [])
        self.assertEqual(code, 2)
        self.assertIn("write blocked", err)

    def test_clean_write_still_passes(self):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "x = 1"}}
        self.assertEqual(_run(payload, [])[0], 0)

    def test_payload_without_tool_name_keeps_legacy_behaviour(self):
        """구 스캐폴드는 tool_name을 안 넣는다 — 그 페이로드도 그대로 판정돼야 한다."""
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


class TestTheReaderListIsNotTheWholeWorld(unittest.TestCase):
    """이름을 모르는 프로그램도 자격 파일을 인자로 받으면 잡는다.

    판정이 판독기 이름 목록에만 걸려 있던 판에서는 `python3 dump.py .env` 가 통과했다
    (26-08-13 실측 3건). 목록은 전수일 수 없으므로 근거를 프로그램 이름에서 **피연산자**로
    옮긴다. 반대 방향도 함께 고정한다 — 자격 파일을 설명하는 문장은 유출이 아니다."""

    def test_an_unlisted_program_taking_the_file_is_caught(self):
        for command in (
            f"python3 dump_env.py {DOTENV}",
            f"./mytool --config {DOTENV}",
            f"node read.js {DOTENV}",
            "some-binary /home/u/.aws/credentials",
        ):
            with self.subTest(command=command):
                self.assertTrue(sg.secret_command(command), f"자격 파일을 인자로 받는데 놓쳤다: {command}")

    def test_talking_about_the_file_is_not_reading_it(self):
        for command in (
            f"codex exec 'audit how the tool reads {DOTENV} at startup'",
            f"git commit -m 'docs: explain {DOTENV} handling'",
            f"echo 'the {DOTENV} file holds credentials'",
            "grep -rn 'dotenv' src/",
        ):
            with self.subTest(command=command):
                self.assertEqual(sg.secret_command(command), "", f"설명하는 명령을 막았다: {command}")


if __name__ == "__main__":
    unittest.main()
