"""오류 경계 봉인 — 사람 화면에 기계 얼굴이 나오지 않는다.

여기서 재는 것은 세 가지이고, 셋은 한 뿌리다.

  · **누구에게 말하는가** — `--json`을 안 준 실행에서 stdout은 그 명령의 산출물 자리다.
    실패를 거기다 JSON으로 적으면 `asgard agent show X > out.json`이 데이터 스트림에 오류를
    받는다. 사유와 처방은 stderr, 산출물은 stdout.
  · **`--json`은 실패에도 JSON** — 기계가 읽는 표면에서 실패 경로만 사람 말로 새면, 그
    표면은 실패를 다룰 수 없는 표면이다.
  · **종료 코드는 예외가 정한다** — 같은 "없음"이 명령에 따라 1과 2로 갈리면 CI도 스튜디오도
    "사용자 입력 잘못"과 "환경 문제"를 구별할 수 없다.

여기 있는 모든 판정은 `tests/cli_boundary.py`를 지난다. `CliRunner`로 앱을 직접 부르면
`cli.main()`을 건너뛰어 **사용자가 받는 것과 다른 종료 코드**를 재게 된다 — 이 파일이 막으려는
바로 그 종류의 어긋남이다.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from cli_boundary import run_cli

from asgard import errors

# 소유 표면(tools·mode·agent·role·memory)의 실패 경로 — (인자, 사유에 반드시 있어야 하는 조각).
# `--json` 없이 부르는 형태다. 새 실패 경로를 만들면 여기에 한 줄을 더한다.
_FAILURES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("memory", "show", "no-such-page"), "no page"),
    (("memory", "remove", "no-such-page"), "no page"),
    (("memory", "norn-restore", "no-such-page"), "아카이브에 없음"),
    (("memory", "discard", "no-such-proposal"), "없거나 이미 처리된 제안 id"),
    (("memory", "contradiction-seen", "no-a", "no-b"), "장부에 없는 쌍"),
    (("memory", "autosave", "on", "--tier", "everything"), "tier는"),
    (("memory", "autosave", "maybe"), "상태는"),
    (("tools", "list", "--role", "odin"), "role must be one of"),
    (("mode", "show", "nosuchmode"), "mode는"),
    (("mode", "set", "nosuchmode", "worker", "--model", "x"), "mode는"),
    (("mode", "set", "native", "worker", "--agent", "no-such-agent"), "no-such-agent"),
    (("mode", "reset", "nosuchmode"), "mode는"),
    (("mode", "pick"), "TTY"),
    (("agent", "show", "does-not-exist"), "못 찾았어요"),
    (("agent", "describe", "does-not-exist", "설명"), "못 찾았어요"),
    (("agent", "delete", "does-not-exist"), "못 찾았어요"),
    (("agent", "delete", "default"), "기본 에이전트는 지울 수 없어요"),
    (("agent", "bind", "no-such-agent"), "no-such-agent"),
    (("role", "model", "native"), "host와 role이 필요해요"),
    (("role", "model", "unknown", "worker", "x"), "host는"),
    (("role", "run", "odin", "과업"), "role은"),
)

# 위 중 `--json` 플래그가 실제로 있는 자리. 없는 명령(`mode set`·`role *`)에 플래그를 지어내
# 재면 통과하는 것은 테스트의 상상이지 사용자 표면이 아니다.
_JSON_FAILURES: tuple[tuple[str, ...], ...] = (
    ("memory", "show", "no-such-page", "--json"),
    ("memory", "remove", "no-such-page", "--json"),
    ("memory", "norn-restore", "no-such-page", "--json"),
    ("memory", "discard", "no-such-proposal", "--json"),
    ("memory", "contradiction-seen", "no-a", "no-b", "--json"),
    ("memory", "autosave", "maybe", "--json"),
    ("tools", "list", "--role", "odin", "--json"),
    ("mode", "show", "nosuchmode", "--json"),
    ("agent", "show", "does-not-exist", "--json"),
    ("agent", "describe", "does-not-exist", "설명", "--json"),
    ("agent", "delete", "does-not-exist", "--json"),
    ("agent", "bind", "no-such-agent", "--json"),
)

# 찾는 것이 없다 — 명령이 달라도 같은 사건이므로 코드도 종료 코드도 같아야 한다.
# memory 계열이 여기 늦게 들어왔다: 이 표면은 종료 코드 1을 손으로 적고 있었고, 그래서 같은
# "없는 페이지"가 `memory show`에서는 1, `skills show`에서는 2였다.
_NOT_FOUND: tuple[tuple[str, ...], ...] = (
    ("memory", "show", "no-such-page"),
    ("memory", "remove", "no-such-page"),
    ("memory", "merge", "no-such-a", "no-such-b"),
    ("memory", "norn-restore", "no-such-page"),
    ("memory", "discard", "no-such-proposal"),
    ("memory", "contradiction-seen", "no-a", "no-b"),
    ("agent", "show", "does-not-exist"),
    ("agent", "describe", "does-not-exist", "설명"),
    ("agent", "delete", "does-not-exist"),
    ("agent", "bind", "no-such-agent"),
    ("mode", "set", "native", "worker", "--agent", "no-such-agent"),
)


class Sandboxed(unittest.TestCase):
    """남의 홈을 건드리지 않는다 — 실패 경로라도 `~/.asgard`를 읽고 쓰는 자리를 지난다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        home = os.path.join(self._tmp.name, "home")
        project = os.path.join(self._tmp.name, "project")
        os.makedirs(home)
        os.makedirs(project)
        self._env = mock.patch.dict(os.environ, {"HOME": home, "ASGARD_HOME": ""}, clear=False)
        self._env.start()
        self._cwd = os.getcwd()
        os.chdir(project)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._env.stop()
        self._tmp.cleanup()


class TestHumanSurfaceStaysHuman(Sandboxed):
    def test_a_failure_without_json_says_it_in_words_on_stderr(self) -> None:
        for argv, reason in _FAILURES:
            with self.subTest(argv=" ".join(argv)):
                result = run_cli(*argv)
                self.assertIn(reason, result.stderr)
                self.assertIn("✘", result.stderr)

    def test_a_failure_without_json_puts_nothing_machine_shaped_on_stdout(self) -> None:
        """산출물 스트림은 실패해도 산출물의 것이다 — 리다이렉트한 파일이 오류를 받으면 안 된다."""
        for argv, _ in _FAILURES:
            with self.subTest(argv=" ".join(argv)):
                result = run_cli(*argv)
                self.assertNotIn('"error"', result.stdout)
                self.assertEqual(result.stdout.strip(), "")

    def test_the_remedy_rides_on_the_same_stream_as_the_reason(self) -> None:
        """처방이 stdout으로 갈라져 나가면 사유와 처방이 서로 다른 파이프로 흩어진다."""
        result = run_cli("agent", "show", "does-not-exist")
        self.assertIn("→", result.stderr)
        self.assertIn("asgard agent list", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_quiet_does_not_swallow_the_remedy(self) -> None:
        """`--quiet`은 장식을 빼라는 말이지 무엇을 하면 되는지를 감추라는 말이 아니다."""
        result = run_cli("agent", "show", "does-not-exist", "--quiet")
        self.assertIn("asgard agent list", result.stderr)


class TestJsonSurfaceFailsInJson(Sandboxed):
    def test_json_gets_json_even_when_the_command_fails(self) -> None:
        for argv in _JSON_FAILURES:
            with self.subTest(argv=" ".join(argv)):
                result = run_cli(*argv)
                payload = json.loads(result.stdout)
                self.assertIn("error", payload)
                self.assertTrue(payload["error"]["message"])
                self.assertTrue(payload["error"]["code"])

    def test_json_keeps_the_human_face_off_the_stream(self) -> None:
        """한 실행이 두 얼굴을 내면 소비자는 어느 쪽을 파싱할지 매번 골라야 한다."""
        for argv in _JSON_FAILURES:
            with self.subTest(argv=" ".join(argv)):
                result = run_cli(*argv)
                self.assertNotIn("✘", result.output)
                self.assertEqual(result.stderr, "")


class TestExitCodesFollowTheCanon(Sandboxed):
    def test_every_owned_failure_exits_two(self) -> None:
        """소유 표면의 실패는 전부 "호출자가 고칠 수 있는 잘못"이다 — `errors.py`의 정본대로 2."""
        for argv, _ in _FAILURES:
            with self.subTest(argv=" ".join(argv)):
                self.assertEqual(run_cli(*argv).exit_code, 2)

    def test_not_found_is_one_verdict_across_commands(self) -> None:
        for argv in _NOT_FOUND:
            with self.subTest(argv=" ".join(argv)):
                self.assertEqual(run_cli(*argv).exit_code, 2)

    def test_not_found_carries_the_same_code_on_every_command(self) -> None:
        """`mode set`은 여기 없다 — `--json`이 없는 명령에 플래그를 지어내 재면 사용자 표면이 아니다.

        `memory merge`도 빠진다. 그 자리의 "src or dst not found"는 `memory/pages.py`가 통짜
        `ValueError`로 던져서, 표면이 받는 시점에는 없음인지 잘못된 slug인지 갈라볼 근거가 없다.
        종료 코드는 어느 쪽이든 2라 여기 위 두 판정은 통과하지만, 코드까지 `not_found`로 적으려면
        `pages.py`가 갈래를 갖고 던져야 한다."""
        codes = {
            json.loads(run_cli(*argv, "--json").stdout)["error"]["code"]
            for argv in _NOT_FOUND
            if argv[0] in {"agent", "memory"} and argv[1] != "merge"
        }
        self.assertEqual(codes, {"not_found"})

    def test_an_open_quest_is_a_state_conflict_not_a_crash(self) -> None:
        """여태 1로 나가던 자리 — 순서가 어긋난 것이지 우리가 깨진 것이 아니다."""
        result = run_cli("role", "run", "worker", "과업")
        self.assertEqual(result.exit_code, 2)
        self.assertIn("열린 quest가 없어요", result.stderr)
        self.assertIn("quest-log open", result.stderr)

    def test_a_delete_that_needs_confirmation_does_not_read_as_done(self) -> None:
        made = run_cli("agent", "create", "boundary-tester")
        self.assertEqual(made.exit_code, 0, made.output)

        refused = run_cli("agent", "delete", "boundary-tester")
        self.assertEqual(refused.exit_code, 2)
        self.assertIn("--yes", refused.stderr)

        payload = json.loads(run_cli("agent", "delete", "boundary-tester", "--json").stdout)
        self.assertEqual(payload["error"]["code"], "conflict")
        self.assertIn("--yes", payload["error"]["remedy"])


class TestEveryFixableFailureSaysWhatToDo(Sandboxed):
    def test_no_owned_failure_leaves_the_user_without_a_next_step(self) -> None:
        """exit 2는 "고칠 수 있다"는 선언이다 — 처방이 비면 그 선언이 거짓말이 된다."""
        errors.clear_remedyless()
        for argv, _ in _FAILURES:
            run_cli(*argv)
        self.assertEqual(errors.remedyless(), [])

    def test_the_json_face_carries_the_remedy_too(self) -> None:
        """창(`assets/studio.html`)이 읽는 것은 이 칸이다 — 비면 창은 사유만 그린다."""
        for argv in _JSON_FAILURES:
            with self.subTest(argv=" ".join(argv)):
                payload = json.loads(run_cli(*argv).stdout)
                self.assertTrue(payload["error"].get("remedy"))


class TestRemedyInstrument(unittest.TestCase):
    """계측은 런타임을 인질로 잡지 않는다 — 세기만 하고, 판정은 테스트가 한다."""

    def setUp(self) -> None:
        errors.clear_remedyless()

    def tearDown(self) -> None:
        errors.clear_remedyless()

    def test_a_remedyless_exit_two_is_recorded_with_its_birthplace(self) -> None:
        errors.InvalidInput("고칠 수 있다면서 무엇을 할지는 안 적었다")
        noted = errors.remedyless()
        self.assertEqual(len(noted), 1)
        self.assertEqual(noted[0]["code"], "invalid_input")
        self.assertIn("test_error_boundary.py:", noted[0]["where"])

    def test_recording_never_becomes_raising(self) -> None:
        """오류를 내려다 오류가 나면 진짜 사유가 그 순간 사라진다."""
        err = errors.NotFound("처방 없음")
        self.assertEqual(err.exit_code, 2)
        self.assertEqual(err.message, "처방 없음")
        self.assertEqual(len(errors.remedyless()), 1)

    def test_a_filled_remedy_is_not_recorded(self) -> None:
        errors.NotFound("없어요", remedy="`asgard agent list`로 이름을 확인하세요")
        self.assertEqual(errors.remedyless(), [])

    def test_exit_one_failures_are_not_this_instruments_business(self) -> None:
        """1은 "환경이 안 됐다"는 뜻이다 — 사용자 행동으로 안 풀리는 자리에 처방을 강요하지 않는다."""
        errors.Unavailable("저장소를 열 수 없어요")
        self.assertEqual(errors.remedyless(), [])

    def test_the_ledger_does_not_grow_without_bound(self) -> None:
        """긴 프로세스(REPL)에서 계측이 메모리를 먹으면 그건 계측이 아니라 누수다."""
        for index in range(errors._REMEDYLESS_CAP + 20):
            errors.InvalidInput(f"처방 없는 실패 {index}")
        self.assertEqual(len(errors.remedyless()), errors._REMEDYLESS_CAP)


if __name__ == "__main__":
    unittest.main()
