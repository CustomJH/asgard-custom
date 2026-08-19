"""code_style — 저장소가 정한 스타일 규격을 선언하고, 이 세션이 쓴 파일에만 물린다.

이 판정기의 값은 규칙이 아니라 **귀속**이다. 규칙은 checkstyle.xml 쪽에 있고, 여기서 틀릴 수
있는 것은 셋이다: ① 감지가 남의 빌드를 이 프로젝트 규격이라고 적는가, ② 도구 출력에서 파일과
줄을 못 읽고도 "위반 없음"으로 보이는가, ③ 물려받은 부채로 종료를 막는가. 시험은 그 셋을 본다.

실행: uv run pytest tests/test_code_style.py
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest

from asgard import code_style, code_style_catalog


def _repo(**files: str) -> str:
    root = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q", root], check=True, capture_output=True)
    for rel, body in files.items():
        path = os.path.join(root, rel.replace("|", "/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
    return root


def _settings(root: str, section: dict) -> None:
    os.makedirs(os.path.join(root, ".asgard"), exist_ok=True)
    with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), "w", encoding="utf-8") as handle:
        json.dump({"code_style": section}, handle)


class Detection(unittest.TestCase):
    """감지는 규격 파일의 존재로 하고, 명령이 도는 자리를 같이 정한다."""

    def test_module_root_becomes_cwd_and_scope(self):
        root = _repo(**{
            "be|gradlew": "", "be|build.gradle": "plugins { id 'checkstyle' }",
            "be|config|checkstyle|checkstyle.xml": "<module/>",
            "fe|package.json": "{}", "fe|eslint.config.mjs": "export default []",
        })  # fmt: skip
        by_name = {t.name: t for t in code_style_catalog.detect(root)}
        self.assertIn("checkstyle:be", by_name)
        self.assertIn("eslint:fe", by_name)
        self.assertEqual(by_name["checkstyle:be"].cwd, "be")
        self.assertEqual(by_name["checkstyle:be"].paths, ("be",))
        self.assertEqual(by_name["eslint:fe"].cwd, "fe")

    def test_gitignored_trees_are_not_this_project(self):
        """gitignore 된 자산 안의 빌드는 이 저장소의 규격이 아니다 — 26-08-19 에 넷이 그렇게 걸렸다."""
        root = _repo(**{
            ".gitignore": "workspace/\n",
            "workspace|other|gradlew": "", "workspace|other|checkstyle.xml": "<module/>",
        })  # fmt: skip
        self.assertEqual([t.name for t in code_style_catalog.detect(root)], [])

    def test_one_name_belongs_to_one_candidate(self):
        """gradle 과 maven 이 둘 다 맞아도 checkstyle 은 하나다 — 같은 검사를 두 번 돌리지 않는다."""
        root = _repo(**{"gradlew": "", "pom.xml": "<project/>", "checkstyle.xml": "<module/>"})
        names = [t.name for t in code_style_catalog.detect(root)]
        self.assertEqual(names.count("checkstyle"), 1)
        self.assertIn("./gradlew", {t.name: t.check for t in code_style_catalog.detect(root)}["checkstyle"])

    def test_lockfile_picks_the_package_manager(self):
        root = _repo(**{"pnpm-lock.yaml": "", "package.json": "{}", ".prettierrc": "{}"})
        prettier = {t.name: t for t in code_style_catalog.detect(root)}["prettier"]
        self.assertTrue(prettier.check.startswith("pnpm exec prettier"))

    def test_config_file_alone_is_not_enough_when_a_runner_is_required(self):
        root = _repo(**{"eslint.config.mjs": "export default []"})  # package.json 없음
        self.assertEqual([t.name for t in code_style_catalog.detect(root)], [])


class Declaration(unittest.TestCase):
    """선언이 있으면 그것이 전부다 — 감지는 `style init` 이 한 번 부르고 끝난다."""

    def test_comment_only_seed_is_not_configured(self):
        root = _repo()
        _settings(root, {"_comment": "…", "_example": {"tools": [{"name": "x", "check": "true"}]}})
        self.assertFalse(code_style.configured(root))
        self.assertEqual(code_style.declared(root), [])

    def test_enabled_false_switches_the_lane_off_but_keeps_the_declaration(self):
        """게이트는 꺼지고 선언은 남는다 — 손으로 부른 `style check` 까지 막을 이유가 없다."""
        root = _repo()
        _settings(root, {"enabled": False, "tools": [{"name": "x", "check": "true"}]})
        self.assertFalse(code_style.configured(root))
        self.assertEqual([t.name for t in code_style.declared(root)], ["x"])

    def test_declared_tools_are_read_whole(self):
        root = _repo()
        _settings(root, {"tools": [{"name": "cs", "check": "c", "fix": "f", "languages": [".java"], "cwd": "be"}]})
        tool = code_style.declared(root)[0]
        self.assertEqual(
            (tool.name, tool.check, tool.fix, tool.languages, tool.cwd), ("cs", "c", "f", (".java",), "be")
        )

    def test_a_row_without_a_check_command_is_not_a_tool(self):
        root = _repo()
        _settings(root, {"tools": [{"name": "cs"}]})
        self.assertEqual(code_style.declared(root), [])


class Ownership(unittest.TestCase):
    def test_language_and_path_must_both_match(self):
        tool = code_style.Tool("x", "true", languages=(".java",), paths=("be",))
        self.assertTrue(tool.owns("be/src/A.java"))
        self.assertFalse(tool.owns("fe/src/A.java"))
        self.assertFalse(tool.owns("be/src/a.ts"))

    def test_no_declaration_means_every_file(self):
        self.assertTrue(code_style.Tool("x", "true").owns("anything.md"))


class Parsing(unittest.TestCase):
    """도구마다 진단 형식이 다르다 — 못 읽은 줄은 "위반 없음"이 아니라 못 읽었다고 적는다."""

    CASES = {
        "gradle-checkstyle": ("[ant:checkstyle] [ERROR] /r/A.java:12:5: Missing a comment. [Javadoc]", "/r/A.java", 12),
        "maven-checkstyle": ("[ERROR] /r/B.java:[7,3] (blocks) NeedBraces: use braces.", "/r/B.java", 7),
        "tsc": ("app/index.vue(43,20): error TS2345: bad argument", "app/index.vue", 43),
        "ruff": ("src/x.py:3:1: F401 `os` imported but unused", "src/x.py", 3),
        "flake8-short": ("src/y.py:9 E501 line too long", "src/y.py", 9),
    }

    def test_every_known_format_yields_file_and_line(self):
        for name, (line, path, number) in self.CASES.items():
            with self.subTest(format=name):
                rows, unparsed = code_style.parse(line)
                self.assertEqual(rows, [(path, number, rows[0][2])])
                self.assertEqual(unparsed, 0)

    def test_eslint_stylish_carries_the_path_down_to_its_findings(self):
        rows, _ = code_style.parse("/r/a.vue\n  12:3  error  Missing semicolon  semi\n  14:1  warning  x  y\n")
        self.assertEqual([(r[0], r[1]) for r in rows], [("/r/a.vue", 12), ("/r/a.vue", 14)])

    def test_unreadable_output_is_counted_not_swallowed(self):
        rows, unparsed = code_style.parse("BUILD FAILED\nsomething went wrong\n")
        self.assertEqual(rows, [])
        self.assertEqual(unparsed, 2)

    def test_a_declared_regex_wins_over_the_builtin_family(self):
        rows, _ = code_style.parse(
            "VIOLATION at Foo.java line 4: bad", r"at (?P<file>\S+) line (?P<line>\d+): (?P<message>.+)"
        )
        self.assertEqual(rows, [("Foo.java", 4, "bad")])


class Attribution(unittest.TestCase):
    """도구가 저장소 뿌리에서 안 돌면 경로 표기가 갈린다 — 끝자리로 이어 붙인다."""

    def test_same_path_matches(self):
        self.assertTrue(code_style.attributes({"be/src/A.java"}, "be/src/A.java"))

    def test_subproject_relative_output_matches_the_session_path(self):
        self.assertTrue(code_style.attributes({"fe/app/x.vue"}, "app/x.vue"))
        self.assertTrue(code_style.attributes({"app/x.vue"}, "fe/app/x.vue"))

    def test_a_different_file_never_matches(self):
        self.assertFalse(code_style.attributes({"be/src/A.java"}, "be/src/B.java"))
        self.assertFalse(code_style.attributes({"src/A.java"}, "other/src/AA.java"))


class Ratchet(unittest.TestCase):
    """물려받은 부채로 종료를 막으면 사람이 게이트를 끈다 — 이번에 쓴 파일만 막는다."""

    def _tool(self, output: str) -> code_style.Tool:
        """이 출력을 그대로 뱉고 1로 끝나는 도구 — 실제 린터 자리를 대신한다."""
        body = "import sys;sys.stdout.write(%r);sys.exit(1)" % output
        return code_style.Tool("fake", "%s -c %s" % (shlex.quote(sys.executable), shlex.quote(body)))

    def test_only_scoped_paths_block(self):
        root = _repo()
        tool = self._tool("mine.py:1:1: E1 bad\ntheirs.py:2:1: E2 old\n")
        report = code_style.run(root, [tool], ("mine.py",))
        self.assertEqual([f.path for f in report.blocking], ["mine.py"])
        self.assertEqual(report.inherited, 1)

    def test_without_scope_everything_blocks(self):
        root = _repo()
        report = code_style.run(root, [self._tool("a.py:1:1: E1 bad\nb.py:2:1: E2 bad\n")], ())
        self.assertEqual(len(report.blocking), 2)

    def test_a_tool_whose_language_this_session_never_touched_does_not_run(self):
        root = _repo()
        tool = code_style.Tool("java", "exit 9", languages=(".java",))
        report = code_style.run(root, [tool], ("x.py",))
        self.assertEqual(report.tools, [])
        self.assertEqual(report.runs, [])

    def test_a_tool_that_cannot_run_is_undetermined_not_clean(self):
        root = _repo()
        report = code_style.run(root, [code_style.Tool("missing", "no-such-binary-xyz")], ("a.py",))
        self.assertEqual(report.blocking, [])
        self.assertEqual([r.tool for r in report.undetermined], ["missing"])


class Batching(unittest.TestCase):
    """경로가 상한을 넘을 때 자르면 판정 못 받은 파일이 초록으로 읽힌다 — 나눈다."""

    def test_every_path_reaches_a_command(self):
        paths = ["f%03d.py" % i for i in range(code_style.MAX_INLINE_PATHS + 10)]
        batches = code_style._batches("ruff check {files}", paths)
        self.assertEqual(sorted(p for batch in batches for p in batch), sorted(paths))
        self.assertEqual(len(batches), 2)

    def test_a_command_without_the_slot_is_one_run(self):
        paths = ["f%03d.java" % i for i in range(code_style.MAX_INLINE_PATHS + 10)]
        self.assertEqual(code_style._batches("./gradlew check", paths), [paths])

    def test_a_run_is_recorded_for_every_batch(self):
        root = _repo()
        body = "import sys;sys.stdout.write('a.py:1:1: E1 bad');sys.exit(1)"
        tool = code_style.Tool("fake", "%s -c %s {files}" % (shlex.quote(sys.executable), shlex.quote(body)))
        paths = tuple("f%03d.py" % i for i in range(code_style.MAX_INLINE_PATHS + 1))
        report = code_style.run(root, [tool], paths)
        self.assertEqual(len(report.runs), 2)
        self.assertEqual(sum(r.findings for r in report.runs), len(report.findings))

    def test_repair_never_widens_past_the_files_it_was_given(self):
        """넘칠 때 저장소 전체로 넓히면 이번에 안 건드린 파일까지 수정 명령이 다시 쓴다."""
        root = _repo()
        seen = os.path.join(tempfile.mkdtemp(), "args")
        writer = "printf '%s\\n' {files} >> " + shlex.quote(seen)
        tool = code_style.Tool("t", "true", fix=writer, autofix=True)
        paths = tuple("f%03d.py" % i for i in range(code_style.MAX_INLINE_PATHS + 5))
        code_style.run(root, [tool], paths, repair="auto")
        with open(seen, encoding="utf-8") as handle:
            written = [line.strip() for line in handle if line.strip()]
        self.assertEqual(sorted(written), sorted(paths))
        self.assertNotIn(".", written)


class Rendering(unittest.TestCase):
    def test_a_long_path_list_is_not_silently_shortened(self):
        paths = ["f%03d.py" % i for i in range(code_style.MAX_INLINE_PATHS + 10)]
        rendered = code_style._render("lint {files}", "/r", "", paths)
        self.assertEqual(len(rendered.split()) - 1, len(paths))

    def test_files_slot_is_replaced_relative_to_the_tools_cwd(self):
        root = _repo(**{"be|src|A.java": "class A {}"})
        rendered = code_style._render("check {files}", root, "be", ["be/src/A.java"])
        self.assertEqual(rendered, "check src/A.java")

    def test_a_command_without_the_slot_runs_over_the_whole_project(self):
        self.assertEqual(code_style._render("./gradlew check", "/r", "be", ["be/x.java"]), "./gradlew check")

    def test_no_paths_falls_back_to_the_current_directory(self):
        self.assertEqual(code_style._render("lint {files}", "/r", "", []), "lint .")


class Repair(unittest.TestCase):
    """디스크를 말없이 고치는 것이 기본이면 안 된다 — 켜는 것은 설정에 적는 사람이다."""

    def _tool(self, **kw) -> tuple[code_style.Tool, str]:
        """수정 명령이 실제로 돌면 파일 하나가 생긴다 — 돌았는지를 그 파일로 본다."""
        marker = os.path.join(tempfile.mkdtemp(), "ran")
        return code_style.Tool("t", "true", fix="touch %s" % shlex.quote(marker), **kw), marker

    def test_auto_runs_only_what_declared_autofix(self):
        root = _repo()
        off, off_marker = self._tool()
        on, on_marker = self._tool(autofix=True)
        code_style.run(root, [off, on], (), repair="auto")
        self.assertFalse(os.path.exists(off_marker))
        self.assertTrue(os.path.exists(on_marker))

    def test_all_runs_every_declared_fix(self):
        root = _repo()
        tool, marker = self._tool()
        report = code_style.run(root, [tool], (), repair="all")
        self.assertTrue(os.path.exists(marker))
        self.assertEqual(len(report.repaired), 1)

    def test_nothing_runs_by_default(self):
        root = _repo()
        tool, marker = self._tool(autofix=True)
        report = code_style.run(root, [tool], ())
        self.assertFalse(os.path.exists(marker))
        self.assertEqual(report.repaired, [])


if __name__ == "__main__":
    unittest.main()
