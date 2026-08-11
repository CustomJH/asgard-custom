"""`asgard root` — 뿌리 밖 차단이 처방한 선언을 실제로 적는 손.

여기서 재는 것은 한 바퀴다. 가드가 막고 → 명령이 선언을 적고 → 같은 가드가 연다. 그 왕복이
안 돌면 처방은 문장으로만 존재한다: 선언이 사는 `.asgard/` 는 같은 가드의 통제 표면이라
손으로는 못 고치고, 그래서 26-08-07 에 짝 저장소 편집과 그 처방이 나란히 막혔다.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from unittest import mock

from cli_boundary import run_cli

from asgard.hooks import readonly_guard


def _settings(root: str) -> dict:
    with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), encoding="utf-8") as handle:
        return json.load(handle)


class Paired(unittest.TestCase):
    """저장소 하나와 그 옆의 짝 저장소 — 한 작업이 두 자리를 같이 만지는 판."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(base, "repo")
        self.pair = os.path.join(base, "pair-repo")
        # 홈에 `.asgard` 를 판다 — 전역 에이전트 홈(`settings.global_dir()`)이라 아스가르드를 깐
        # 기계에는 반드시 있다. 이게 없는 모래상자는 실제 형상을 가린다: 홈이 "바깥 프로젝트"로
        # 세어지던 결함이 픽스처 때문에 초록으로 통과했다 (26-08-07 판정).
        for directory in (self.repo, self.pair, os.path.join(self.repo, ".asgard"), os.path.join(base, ".asgard")):
            os.makedirs(directory)
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"HOME": base}, clear=False)
        patch.start()
        # 훅도 CLI 도 이 변수를 뿌리로 집는다 — 사용자의 실제 프로젝트를 끌어들이지 않게 지운다.
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.addCleanup(patch.stop)
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)

    def guard_edit(self, path: str) -> int:
        """가드가 이 편집을 어떻게 보는가 — 0 이면 통과, 2 면 차단."""
        payload = {"cwd": self.repo, "tool_name": "Edit", "tool_input": {"file_path": path}}
        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch("sys.argv", ["hook"]),
        ):
            try:
                readonly_guard.main()
                return 0
            except SystemExit as exc:
                return int(exc.code or 0)

    @property
    def pair_file(self) -> str:
        return os.path.join(self.pair, "src", "api.py")


class TestTheRoundTrip(Paired):
    def test_blocked_then_declared_then_open(self) -> None:
        self.assertEqual(self.guard_edit(self.pair_file), 2)
        outcome = run_cli("root", "add", self.pair, "--yes")
        self.assertEqual(outcome.exit_code, 0, outcome.output)
        self.assertEqual(self.guard_edit(self.pair_file), 0)

    def test_remove_closes_it_again(self) -> None:
        run_cli("root", "add", self.pair, "--yes")
        self.assertEqual(self.guard_edit(self.pair_file), 0)
        outcome = run_cli("root", "remove", self.pair)
        self.assertEqual(outcome.exit_code, 0, outcome.output)
        self.assertEqual(self.guard_edit(self.pair_file), 2)


class TestConsent(Paired):
    def test_non_interactive_without_yes_refuses_and_writes_nothing(self) -> None:
        outcome = run_cli("root", "add", self.pair)
        self.assertEqual(outcome.exit_code, 2)
        self.assertIn("--yes", outcome.output)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".asgard", "asgard-setting-project.json")))
        self.assertEqual(self.guard_edit(self.pair_file), 2)

    def test_a_terminal_is_asked_and_a_no_writes_nothing(self) -> None:
        with (
            mock.patch("asgard.commands.workroots._can_ask", return_value=True),
            mock.patch("builtins.input", return_value="n") as asked,
        ):
            outcome = run_cli("root", "add", self.pair)
        self.assertEqual(outcome.exit_code, 2)
        self.assertTrue(asked.called)
        self.assertEqual(self.guard_edit(self.pair_file), 2)

    def test_a_terminal_that_says_yes_opens_it(self) -> None:
        with (
            mock.patch("asgard.commands.workroots._can_ask", return_value=True),
            mock.patch("builtins.input", return_value="y"),
        ):
            outcome = run_cli("root", "add", self.pair)
        self.assertEqual(outcome.exit_code, 0, outcome.output)
        self.assertEqual(self.guard_edit(self.pair_file), 0)

    def test_json_never_asks_even_on_a_terminal(self) -> None:
        """기계가 읽는 출력에 물음을 섞으면 그 출력은 JSON 이 아니게 된다."""
        with (
            mock.patch("asgard.commands.workroots._can_ask", return_value=True),
            mock.patch("builtins.input", return_value="y") as asked,
        ):
            outcome = run_cli("root", "add", self.pair, "--json")
        self.assertEqual(outcome.exit_code, 2)
        self.assertFalse(asked.called)
        self.assertIn("error", json.loads(outcome.stdout))


class TestWhatGetsWritten(Paired):
    def test_declaration_is_relative_so_a_teammate_can_read_it(self) -> None:
        run_cli("root", "add", self.pair, "--yes")
        self.assertEqual(_settings(self.repo)["paths"]["additional_roots"], ["../pair-repo"])

    def test_absolute_is_available_for_a_path_that_is_not_a_sibling(self) -> None:
        run_cli("root", "add", self.pair, "--yes", "--absolute")
        self.assertEqual(_settings(self.repo)["paths"]["additional_roots"], [self.pair])

    def test_a_distant_directory_is_stored_absolute_not_as_a_chain_of_dots(self) -> None:
        """`../../../../..` 를 적어 두면 디프를 읽는 사람이 그 점들이 어디를 가리키는지 셀 수 없다."""
        # 자기 모래상자 밖의 별도 임시 디렉터리 — 뿌리에서 두 단계 이상 거슬러야 하는 자리다.
        # 이름이 겹치지 않으므로 `-n auto` 로 나란히 돌아도 서로를 안 밟는다.
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        distant = os.path.realpath(other.name)
        self.assertTrue(os.path.relpath(distant, self.repo).startswith(os.pardir + os.sep + os.pardir))
        run_cli("root", "add", distant, "--yes")
        self.assertEqual(_settings(self.repo)["paths"]["additional_roots"], [distant])

    def test_declaring_twice_does_not_duplicate(self) -> None:
        run_cli("root", "add", self.pair, "--yes")
        second = run_cli("root", "add", self.pair, "--yes")
        self.assertEqual(second.exit_code, 0)
        self.assertEqual(_settings(self.repo)["paths"]["additional_roots"], ["../pair-repo"])

    def test_other_sections_survive_the_write(self) -> None:
        """`save_project` 는 파일을 통째로 다시 쓴다 — 한 섹션을 고치다 나머지를 잃으면 안 된다."""
        path = os.path.join(self.repo, ".asgard", "asgard-setting-project.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"trinity_policy": {"verify_level": "high"}, "paths": {"ignore": ["build"]}}, handle)
        run_cli("root", "add", self.pair, "--yes")
        data = _settings(self.repo)
        self.assertEqual(data["trinity_policy"], {"verify_level": "high"})
        self.assertEqual(data["paths"]["ignore"], ["build"])
        self.assertEqual(data["paths"]["additional_roots"], ["../pair-repo"])

    def test_a_broken_settings_file_stops_the_write(self) -> None:
        path = os.path.join(self.repo, ".asgard", "asgard-setting-project.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"trinity_policy": {"verify_level": "high",}')
        outcome = run_cli("root", "add", self.pair, "--yes")
        self.assertEqual(outcome.exit_code, 2)
        with open(path, encoding="utf-8") as handle:  # 원본이 그대로 남아야 사람이 고칠 수 있다
            self.assertIn("verify_level", handle.read())


class TestTheBoundaryItselfStaysNarrow(Paired):
    """선언은 가드의 경계 그 자체다 — 넓은 자리 하나가 나머지 판정을 통째로 무의미하게 만든다."""

    def assert_refused(self, directory: str) -> None:
        outcome = run_cli("root", "add", directory, "--yes")
        self.assertEqual(outcome.exit_code, 2, outcome.output)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".asgard", "asgard-setting-project.json")))

    def test_the_machine_root_is_refused(self) -> None:
        self.assert_refused(os.path.abspath(os.sep))

    def test_the_home_directory_is_refused(self) -> None:
        self.assert_refused("~")

    def test_an_ancestor_of_this_project_is_refused(self) -> None:
        """부모를 열면 이웃한 저장소와 그 하네스 상태까지 한꺼번에 딸려 온다."""
        self.assert_refused(os.path.dirname(self.repo))

    def test_a_refused_root_never_reaches_the_guard(self) -> None:
        run_cli("root", "add", os.path.abspath(os.sep), "--yes")
        self.assertEqual(self.guard_edit("/etc/hosts"), 2)


class TestItWritesWhereTheGuardReads(Paired):
    def setUp(self) -> None:
        super().setUp()
        self.inner = os.path.join(self.repo, "nested")
        os.makedirs(os.path.join(self.inner, ".asgard"))

    def test_the_host_session_root_wins_over_the_nearest_marker(self) -> None:
        """가드는 호스트가 넘긴 뿌리의 설정만 읽는다 — 하위 프로젝트에 적으면 아무도 안 읽는다."""
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.repo}):
            os.chdir(self.inner)
            outcome = run_cli("root", "add", self.pair, "--yes")
        self.assertEqual(outcome.exit_code, 0, outcome.output)
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".asgard", "asgard-setting-project.json")))
        self.assertFalse(os.path.exists(os.path.join(self.inner, ".asgard", "asgard-setting-project.json")))
        self.assertEqual(self.guard_edit(self.pair_file), 0)

    def test_a_nested_project_is_told_that_an_outer_session_will_not_read_it(self) -> None:
        os.chdir(self.inner)
        outcome = run_cli("root", "add", self.pair, "--yes", "--json")
        self.assertEqual(outcome.exit_code, 0, outcome.output)
        self.assertEqual(json.loads(outcome.stdout)["outer_project"], self.repo)

    def test_the_agent_home_is_not_an_outer_project(self) -> None:
        """`~/.asgard` 는 전역 에이전트 홈이다 — 그걸 프로젝트로 세면 홈 아래 전부에서 경고가 뜬다."""
        outcome = run_cli("root", "add", self.pair, "--yes", "--json")
        self.assertEqual(outcome.exit_code, 0, outcome.output)
        self.assertNotIn("outer_project", json.loads(outcome.stdout))

    def test_a_home_that_is_itself_a_repository_still_works(self) -> None:
        """dotfiles 를 홈에서 직접 버전 관리하는 형상 — 그때 홈은 진짜 저장소다.

        `.asgard` 를 홈에서 무시하는 규칙이 `.git` 까지 덮으면, 그 사람은 `root add` 를 아예
        못 쓴다. 무시하는 것은 전역 에이전트 홈 한 가지뿐이어야 한다."""
        home = os.path.dirname(self.repo)
        os.makedirs(os.path.join(home, ".git"))
        loose = os.path.join(home, "loose")
        os.makedirs(loose)
        # 홈 아래는 이미 뿌리 안이라 선언할 것이 없다 — 대상은 홈 밖이어야 한다.
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        os.chdir(loose)
        outcome = run_cli("root", "add", outside.name, "--yes", "--json")
        self.assertEqual(outcome.exit_code, 0, outcome.output)
        written = json.loads(outcome.stdout)
        self.assertEqual(written["root"], home)
        self.assertEqual(written["directory"], os.path.realpath(outside.name))
        self.assertEqual(written["declared"], [os.path.relpath(os.path.realpath(outside.name), home)])

    def test_outside_a_project_it_refuses_instead_of_writing_somewhere_unread(self) -> None:
        loose = os.path.join(os.path.dirname(self.repo), "loose")
        os.makedirs(loose)
        os.chdir(loose)
        outcome = run_cli("root", "add", self.pair, "--yes")
        self.assertEqual(outcome.exit_code, 2)
        self.assertFalse(os.path.exists(os.path.join(loose, ".asgard")))
        self.assertFalse(
            os.path.exists(os.path.join(os.path.dirname(self.repo), ".asgard", "asgard-setting-project.json"))
        )


class TestRefusals(Paired):
    def test_a_path_that_is_not_a_directory(self) -> None:
        outcome = run_cli("root", "add", os.path.join(self.pair, "nope"), "--yes")
        self.assertEqual(outcome.exit_code, 2)

    def test_a_paths_section_that_is_not_an_object_is_not_overwritten(self) -> None:
        """`_section` 이 객체 아닌 `paths` 를 `{}` 로 삼키면 그 안의 값이 말없이 증발한다."""
        path = os.path.join(self.repo, ".asgard", "asgard-setting-project.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"trinity_policy": {"verify_level": "high"}, "paths": ["build", "dist"]}, handle)
        outcome = run_cli("root", "add", self.pair, "--yes")
        self.assertEqual(outcome.exit_code, 2)
        self.assertEqual(_settings(self.repo)["paths"], ["build", "dist"])

    def test_removing_something_never_declared(self) -> None:
        outcome = run_cli("root", "remove", self.pair)
        self.assertEqual(outcome.exit_code, 2)
        self.assertIn("root list", outcome.output)


class TestList(Paired):
    def test_json_names_the_roots_in_force(self) -> None:
        run_cli("root", "add", self.pair, "--yes")
        outcome = run_cli("root", "list", "--json")
        data = json.loads(outcome.stdout)
        self.assertEqual(data["root"], self.repo)
        self.assertIn(self.pair, data["work_roots"])
        self.assertEqual(data["declared"], ["../pair-repo"])


if __name__ == "__main__":
    unittest.main()
