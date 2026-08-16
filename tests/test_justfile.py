#!/usr/bin/env python3
"""asgard just — 감지, 관리 구역 소유권, 드리프트, 설치 보장 (전부 결정론, 네트워크 없음).

계약: 표식 사이는 asgard 가 매번 다시 그리고 그 밖은 사람의 것이다. 이름이 겹치면 사람이
적은 쪽을 남긴다 — just 는 중복 정의된 레시피를 만나면 파일 전체를 거부하므로, 이 규칙이
깨지면 저장소의 모든 `just` 호출이 죽는다.

실행: uv run pytest tests/test_justfile.py
"""

import os
import tempfile
import unittest
from unittest import mock

from asgard import justfile


def _repo(root: str, **files: str) -> None:
    for name, content in files.items():
        path = os.path.join(root, name.replace("__", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def read(self) -> str:
        with open(justfile.find_justfile(self.root) or "", encoding="utf-8") as handle:
            return handle.read()


class DetectTest(Base):
    def test_python_manifest_becomes_named_recipes(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n[tool.ty]\n", "tests__test_a.py": ""})
        names = {recipe.name: recipe.commands for recipe in justfile.detect_recipes(self.root)}
        self.assertEqual(names["test"], ("python -m pytest",))
        self.assertEqual(names["lint"], ("ruff check .",))
        self.assertEqual(names["fmt-check"], ("ruff format --check .",))
        self.assertEqual(names["typecheck"], ("ty check",))

    def test_polyglot_repo_folds_both_test_commands_into_one_recipe(self):
        _repo(
            self.root,
            **{
                "pyproject.toml": "[tool.pytest.ini_options]\n",
                "tests__test_a.py": "",
                "package.json": '{"scripts": {"test": "vitest"}}',
            },
        )
        test = next(r for r in justfile.detect_recipes(self.root) if r.name == "test")
        self.assertEqual(test.commands, ("npm run test", "python -m pytest"))

    def test_aggregate_check_is_skipped_when_a_manifest_already_claims_the_name(self):
        _repo(self.root, **{"Cargo.toml": "[package]\n"})
        recipes = {recipe.name: recipe for recipe in justfile.detect_recipes(self.root)}
        # cargo 는 test 와 check 를 둘 다 낸다 — 집계 레시피를 하나 더 내면 just 가 파일을 거부한다.
        self.assertEqual(recipes["check"].commands, ("cargo check",))
        self.assertEqual(recipes["check"].deps, ())

    def test_a_uv_locked_repo_gets_commands_that_actually_run(self):
        # dev 그룹 도구는 잠긴 환경 안에만 산다 — 맨 `ruff check .` 는 command not found 로 죽는다.
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n[tool.ty]\n", "uv.lock": "version = 1\n"})
        names = {recipe.name: recipe.commands for recipe in justfile.detect_recipes(self.root)}
        self.assertEqual(names["lint"], ("uv run ruff check .",))
        self.assertEqual(names["typecheck"], ("uv run ty check",))

    def test_a_repo_without_a_uv_lock_keeps_the_bare_command(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        names = {recipe.name: recipe.commands for recipe in justfile.detect_recipes(self.root)}
        self.assertEqual(names["lint"], ("ruff check .",))

    def test_a_command_with_no_recipe_name_is_left_out(self):
        self.assertIsNone(justfile.recipe_name("docker compose up"))
        self.assertEqual(justfile.recipe_name("make deploy"), "deploy")
        self.assertEqual(justfile.recipe_name("pnpm typecheck"), "typecheck")


class OwnershipTest(Base):
    def test_a_fresh_repo_gets_a_file_that_just_can_read(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        result = justfile.sync(self.root)
        self.assertTrue(result.created)
        self.assertTrue(result.changed)
        text = self.read()
        self.assertIn("default:", text)
        self.assertIn(justfile.BEGIN, text)
        self.assertIn("lint:", text)

    def test_sync_is_idempotent(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        justfile.sync(self.root)
        before = self.read()
        self.assertFalse(justfile.sync(self.root).changed)
        self.assertEqual(self.read(), before)
        self.assertEqual(justfile.check(self.root), [])

    def test_everything_outside_the_markers_survives_byte_for_byte(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        justfile.sync(self.root)
        path = justfile.find_justfile(self.root)
        assert path is not None
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n# Deploy to staging\ndeploy env:\n    ./bin/ship {{env}}\n")
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n[tool.ty]\n"})
        justfile.sync(self.root)
        text = self.read()
        self.assertIn("deploy env:\n    ./bin/ship {{env}}", text)
        self.assertIn("typecheck:", text)  # 새 매니페스트가 관리 구역에 들어왔다

    def test_a_user_recipe_of_the_same_name_is_kept_and_not_duplicated(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n", "tests__test_a.py": ""})
        with open(justfile.default_path(self.root), "w", encoding="utf-8") as handle:
            handle.write("# My own suite\ntest:\n    ./run-tests.sh\n")
        result = justfile.sync(self.root)
        text = self.read()
        self.assertTrue(result.appended)
        self.assertEqual(result.skipped, ("test",))
        self.assertEqual([name for name, _ in justfile.parse_recipes(text)].count("test"), 1)
        self.assertIn("./run-tests.sh", text)
        self.assertNotIn("python -m pytest", text)

    def test_an_aggregate_loses_the_dependencies_the_user_took(self):
        # 사용자가 lint·test 를 다 가져가면 남는 의존이 없다 — 없는 이름을 부르는 집계는 안 낸다.
        block = justfile.managed_block(justfile.detect_recipes(self.root), skip={"lint", "test", "fmt-check"})
        self.assertNotIn("check:", block)

    def test_an_unattended_pass_never_creates_the_file(self):
        """`asgard sync`·셋업이 쓰는 갈래. 레시피가 감지돼도 안 만든다 — 실행 표면은 저장소가 고른다."""
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n[tool.ty]\n", "tests__test_a.py": ""})
        self.assertTrue(justfile.detect_recipes(self.root), "이 저장소는 낼 레시피가 있다 (전제)")
        result = justfile.sync(self.root, create=False)
        self.assertFalse(result.changed)
        self.assertFalse(result.created)
        self.assertIsNone(justfile.find_justfile(self.root))

    def test_an_unattended_pass_still_refreshes_a_file_the_repository_already_chose(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        justfile.sync(self.root)  # 저장소가 들였다
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n[tool.ty]\n"})
        self.assertTrue(justfile.sync(self.root, create=False).changed)
        self.assertIn("typecheck:", self.read())

    def test_a_human_written_justfile_keeps_its_own_header(self):
        with open(os.path.join(self.root, "justfile"), "w", encoding="utf-8") as handle:
            handle.write("set dotenv-load\n\nserve:\n    ./serve\n")
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        result = justfile.sync(self.root)
        text = self.read()
        self.assertTrue(result.appended)
        self.assertTrue(text.startswith("set dotenv-load"))
        self.assertIn(justfile.BEGIN, text)


class ParseTest(Base):
    def test_settings_assignments_and_aliases_are_not_recipes(self):
        text = (
            'set shell := ["bash", "-uc"]\n'
            'gradlew := "./gradlew"\n'
            "alias b := build\n"
            'export FOO := "1"\n'
            "# Build it\n"
            "build:\n"
            "    ./gradlew build\n"
            "@quiet:\n"
            "    echo hi\n"
            "    not-a-recipe:\n"
        )
        self.assertEqual(justfile.parse_recipes(text), [("build", "Build it"), ("quiet", "")])

    def test_an_attribute_line_keeps_the_doc_above_it(self):
        text = "# Clean everything\n[unix]\nclean:\n    rm -rf out\n\n[windows]\nclean:\n    Remove-Item out\n"
        self.assertEqual(justfile.parse_recipes(text), [("clean", "Clean everything"), ("clean", "")])

    def test_os_gated_twins_are_not_a_duplicate(self):
        # just 는 플랫폼마다 하나만 살린다 — 이것을 중복이라 부르면 두 벌을 쓰는 저장소가 영원히 빨간불이 된다.
        text = "[unix]\nclean:\n    rm -rf out\n\n[windows]\nclean:\n    Remove-Item out\n"
        self.assertEqual(justfile._duplicates(text), [])
        self.assertEqual(justfile._duplicates(text + "\nclean:\n    true\n"), ["clean"])

    def test_marker_lines_never_become_a_recipe_doc(self):
        recipes = justfile.parse_recipes(
            justfile.managed_block([justfile.Recipe("test", "Run the tests", ("pytest",))])
        )
        self.assertEqual(recipes, [("test", "Run the tests")])


class CheckTest(Base):
    def test_no_justfile_is_not_drift(self):
        """실행 표면을 안 들인 것은 어긋난 것이 아니다 — 안 고른 것을 결함으로 부르면 도구가 고른 셈이다."""
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        self.assertEqual(justfile.check(self.root), [])

    def test_a_stale_region_is_reported_once_the_repository_has_one(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        justfile.sync(self.root)
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n[tool.ty]\n"})
        self.assertIn("stale", justfile.check(self.root)[0])

    def test_a_duplicate_recipe_is_named_because_just_refuses_the_whole_file(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        justfile.sync(self.root)
        path = justfile.find_justfile(self.root)
        assert path is not None
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\nlint:\n    ./lint\n")
        self.assertTrue(any("more than once" in issue for issue in justfile.check(self.root)))


class DoctorRowTest(Base):
    """진단에 행이 뜨는 조건 — 이 저장소가 실행 표면을 들였는가 하나다.

    안 들인 저장소에 행을 내면 초록이든 노랑이든 "들여야 할 것을 안 들였다"로 읽힌다. 그 판단은
    도구가 아니라 사람이 한다. 이 시험이 없으면 `codemap.py` 의 `return None` 한 줄을 지워도
    스위트가 초록이라, 조건이 조용히 되돌아간다."""

    def _row(self):
        from asgard.commands.doctor.codemap import _run_surface_check

        return _run_surface_check(self.root)

    def test_a_repository_without_a_justfile_gets_no_row(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n", "tests__test_a.py": ""})
        self.assertTrue(justfile.detect_recipes(self.root), "낼 레시피는 있다 — 그래도 행은 없어야 한다 (전제)")
        self.assertIsNone(self._row())

    def test_a_repository_that_adopted_one_gets_a_row(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        justfile.sync(self.root)
        row = self._row()
        assert row is not None
        self.assertEqual(row["name"], "run surface")

    def test_the_row_reports_drift_once_the_manifests_move(self):
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n"})
        justfile.sync(self.root)
        _repo(self.root, **{"pyproject.toml": "[tool.ruff]\n[tool.ty]\n"})
        row = self._row()
        assert row is not None
        self.assertFalse(row["ok"])
        self.assertIn("stale", row["detail"])


class EnsureTest(unittest.TestCase):
    def test_an_installed_just_is_left_alone(self):
        with mock.patch.object(justfile, "just_version", return_value="just 1.51.0") as probe:
            with mock.patch("subprocess.run", side_effect=AssertionError("must not install")):
                self.assertEqual(justfile.ensure_just(), ("present", "just 1.51.0"))
        probe.assert_called_once()

    def test_a_missing_just_is_installed_through_the_uv_that_installed_asgard(self):
        calls: list[list[str]] = []

        def fake_run(argv, **_kwargs):
            calls.append(list(argv))
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(justfile, "just_version", side_effect=[None, "just 1.58.0"]):
            with mock.patch("shutil.which", return_value="/opt/uv"):
                with mock.patch("subprocess.run", side_effect=fake_run):
                    self.assertEqual(justfile.ensure_just(), ("installed", "just 1.58.0"))
        self.assertEqual(calls, [["/opt/uv", "tool", "install", "--quiet", "rust-just"]])

    def test_no_uv_reports_instead_of_raising(self):
        with mock.patch.object(justfile, "just_version", return_value=None):
            with mock.patch("shutil.which", return_value=None):
                state, detail = justfile.ensure_just()
        self.assertEqual(state, "unavailable")
        self.assertIn("just.systems", detail)


if __name__ == "__main__":
    unittest.main()
