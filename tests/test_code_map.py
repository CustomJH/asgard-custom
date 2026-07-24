#!/usr/bin/env python3
"""Codebase map — deterministic project orientation and incremental refresh."""

import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from typer.testing import CliRunner

from asgard import ui


class CodeMapBase(unittest.TestCase):
    def setUp(self):
        ui.set_quiet(True)
        self.addCleanup(ui.set_quiet, False)  # 전역 quiet 누출 방지 — 이후 stdout 검증 테스트 보호
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, body: str = "") -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)


class TestProjectMap(CodeMapBase):
    def seed_python_project(self) -> None:
        self.write("pyproject.toml", '[project]\nname = "demo"\n[project.scripts]\ndemo = "demo.cli:app"\n')
        self.write("src/demo/__init__.py")
        self.write("src/demo/cli.py", "app = object()\n")
        self.write("tests/test_cli.py")
        self.write("docs/architecture.md")
        self.write("README.md", "# Demo\n")
        self.write(".git/private", "ignored\n")
        self.write("node_modules/pkg/index.js", "ignored\n")

    def test_setup_builds_evidence_based_orientation(self):
        from asgard.code_map import refresh_map

        self.seed_python_project()
        result = refresh_map(self.root)

        self.assertTrue(result.changed)
        project_map = open(os.path.join(self.root, ".asgard", "map", "PROJECT.md"), encoding="utf-8").read()
        self.assertIn("# Project Map — demo", project_map)
        self.assertIn("- Project root: `./`", project_map)
        self.assertIn("- `pyproject.toml` — Python project manifest", project_map)
        self.assertIn("- `src/demo/` — Python package root", project_map)
        self.assertIn("- `src/demo/cli.py` — CLI entrypoint `demo`", project_map)
        self.assertIn("- `tests/` — test area", project_map)
        self.assertIn("- `docs/` — documentation area", project_map)
        self.assertNotIn("node_modules", project_map)
        self.assertNotIn(".git/private", project_map)
        self.assertEqual(result.files_scanned, 6)

    def test_refresh_is_idempotent_and_preserves_manual_area_maps(self):
        from asgard.code_map import refresh_map

        self.seed_python_project()
        self.write(".asgard/map/api.md", "# map: api\n\n- `src/demo/cli.py` — manual API note\n")
        first = refresh_map(self.root)
        second = refresh_map(self.root)

        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        manual = open(os.path.join(self.root, ".asgard", "map", "api.md"), encoding="utf-8").read()
        self.assertIn("manual API note", manual)

    def test_check_detects_structural_drift_without_writing(self):
        from asgard.code_map import check_map, refresh_map

        self.seed_python_project()
        refresh_map(self.root)
        self.assertTrue(check_map(self.root).ok)

        self.write("src/newpkg/__init__.py", "class Service: ...\n")
        drift = check_map(self.root)
        self.assertFalse(drift.ok)
        self.assertIn("src/newpkg/", drift.added)
        current = open(os.path.join(self.root, ".asgard", "map", "PROJECT.md"), encoding="utf-8").read()
        self.assertNotIn("src/newpkg/", current)

    def test_deleted_landmark_is_removed_on_refresh(self):
        from asgard.code_map import refresh_map

        self.seed_python_project()
        refresh_map(self.root)
        os.remove(os.path.join(self.root, "src", "demo", "cli.py"))
        refresh_map(self.root)
        project_map = open(os.path.join(self.root, ".asgard", "map", "PROJECT.md"), encoding="utf-8").read()
        self.assertNotIn("src/demo/cli.py", project_map)

    def test_gitignored_workspaces_do_not_pollute_landmarks(self):
        from asgard.code_map import refresh_map

        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write(".gitignore", "workspace/\n")
        self.write("pyproject.toml", '[project]\nname = "clean"\n')
        self.write("src/clean/__init__.py")
        self.write("workspace/copy/__init__.py")

        result = refresh_map(self.root)
        project_map = open(os.path.join(self.root, ".asgard", "map", "PROJECT.md"), encoding="utf-8").read()
        self.assertEqual(result.files_scanned, 2)
        self.assertNotIn("workspace/", project_map)

    def test_ignored_nested_project_falls_back_to_walk_boundary(self):
        from pathlib import Path

        from asgard.code_map import _files

        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write(".gitignore", "ref/\n")
        self.write("ref/proj/pyproject.toml", '[project]\nname = "nested"\n')
        self.write("ref/proj/src/app.py", "X = 1\n")
        # 상위 저장소가 ignore 한 사본에서 ls-files 는 빈 성공을 낸다 — 경계 부재로 보고
        # walk 폴백해야 사용자가 가리킨 루트가 조용한 빈 지도가 되지 않는다.
        listed = [p.as_posix() for p in _files(Path(self.root) / "ref" / "proj")]
        self.assertIn("pyproject.toml", listed)
        self.assertIn("src/app.py", listed)

    def test_check_fails_when_managed_map_is_gitignored(self):
        from asgard.code_map import check_map, refresh_map

        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write(".gitignore", ".asgard\n")
        self.write("pyproject.toml", '[project]\nname = "hidden"\n')
        refresh_map(self.root)

        result = check_map(self.root)
        self.assertFalse(result.ok)
        self.assertFalse(result.trackable)

    def test_refresh_rejects_map_directory_symlink(self):
        from asgard.code_map import MapSafetyError, refresh_map

        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        os.makedirs(os.path.join(self.root, ".asgard"))
        os.symlink(outside.name, os.path.join(self.root, ".asgard", "map"))
        with self.assertRaises(MapSafetyError):
            refresh_map(self.root)
        self.assertFalse(os.path.exists(os.path.join(outside.name, "PROJECT.md")))

    def test_refresh_check_and_doctor_reject_dangling_managed_parents(self):
        from asgard.code_map import MapSafetyError, check_map, refresh_map
        from asgard.commands.doctor import _trinity_checks

        self.write("AGENTS.md", "<!-- asgard:trinity -->\n")
        os.symlink(os.path.join(self.root, "missing-asgard"), os.path.join(self.root, ".asgard"))
        with self.assertRaises(MapSafetyError):
            refresh_map(self.root, dry_run=True)
        with self.assertRaises(MapSafetyError):
            check_map(self.root)
        doctor = next(c for c in _trinity_checks(self.root) if c["name"] == "codebase map")
        self.assertFalse(doctor["ok"])
        self.assertIn("symlink", doctor["detail"])

        os.unlink(os.path.join(self.root, ".asgard"))
        os.makedirs(os.path.join(self.root, ".asgard"))
        os.symlink(os.path.join(self.root, "missing-map"), os.path.join(self.root, ".asgard", "map"))
        with self.assertRaises(MapSafetyError):
            refresh_map(self.root, dry_run=True)
        with self.assertRaises(MapSafetyError):
            check_map(self.root)
        doctor = next(c for c in _trinity_checks(self.root) if c["name"] == "codebase map")
        self.assertFalse(doctor["ok"])
        self.assertIn("symlink", doctor["detail"])

    def test_refresh_rejects_reserved_name_collision_and_unowned_project_map(self):
        from asgard.code_map import MapOwnershipError, refresh_map

        self.seed_python_project()
        self.write(".asgard/map/project.md", "# human map\n")
        with self.assertRaises(MapOwnershipError):
            refresh_map(self.root)
        os.remove(os.path.join(self.root, ".asgard", "map", "project.md"))
        self.write(".asgard/map/PROJECT.md", "# human project map\n")
        with self.assertRaises(MapOwnershipError):
            refresh_map(self.root)

        self.write(".asgard/map/PROJECT.md", "# human\n\nmarker example: <!-- asgard:project-map schema=1 -->\n")
        with self.assertRaises(MapOwnershipError):
            refresh_map(self.root)

        self.write(".asgard/map/PROJECT.md", "")
        with self.assertRaises(MapOwnershipError):
            refresh_map(self.root)

    def test_refresh_force_reowns_unowned_project_map(self):
        # init 경로 — force 는 소유권 거부만 우회해 현재 디렉토리 스캔 결과로 엎어쓴다.
        from asgard.code_map import MapOwnershipError, refresh_map

        self.seed_python_project()
        self.write(".asgard/map/PROJECT.md", "# human project map\n")
        result = refresh_map(self.root, force=True)
        self.assertTrue(result.changed)
        body = open(os.path.join(self.root, ".asgard", "map", "PROJECT.md"), encoding="utf-8").read()
        self.assertNotIn("# human project map", body)
        refresh_map(self.root)  # 재귀속 후엔 asgard 소유 — 비강제 갱신이 다시 통과한다
        # force 는 예약 파일명 충돌(안전 검사)은 우회하지 않는다
        os.remove(os.path.join(self.root, ".asgard", "map", "PROJECT.md"))
        self.write(".asgard/map/project.md", "# imposter\n")
        with self.assertRaises(MapOwnershipError):
            refresh_map(self.root, force=True)

    def test_unsafe_filenames_and_manifest_labels_cannot_break_markdown(self):
        from asgard.code_map import refresh_map

        self.write("pyproject.toml", '[project]\nname = "bad\\n`name\\u007f\\u0085\\u202e"\n')
        self.write("src/good/__init__.py")
        self.write("src/bad\n`pkg/__init__.py")
        refresh_map(self.root)
        body = open(os.path.join(self.root, ".asgard", "map", "PROJECT.md"), encoding="utf-8").read()
        self.assertIn("# Project Map — bad _name", body)
        self.assertNotIn("bad\n`pkg", body)
        self.assertNotIn("\x7f", body)
        self.assertNotIn("\x85", body)
        self.assertNotIn("\u202e", body)

    def test_atomic_map_write_does_not_follow_predictable_temp_symlink(self):
        from asgard.code_map import refresh_map

        outside = os.path.join(self.root, "outside.txt")
        self.write("outside.txt", "unchanged\n")
        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        trap = os.path.join(self.root, ".asgard", "map", f".INDEX.md.{os.getpid()}.tmp")
        os.symlink(outside, trap)
        self.write("pyproject.toml", '[project]\nname = "atomic"\n')

        refresh_map(self.root)
        self.assertEqual(open(outside, encoding="utf-8").read(), "unchanged\n")

    def test_check_covers_index_drift(self):
        from asgard.code_map import check_map, refresh_map

        self.seed_python_project()
        refresh_map(self.root)
        self.write(".asgard/map/INDEX.md", "stale\n")
        result = check_map(self.root)
        self.assertFalse(result.ok)
        self.assertFalse(result.index_current)

    def test_manifestless_map_is_independent_of_checkout_directory_name(self):
        from asgard.code_map import refresh_map

        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        for root in (self.root, other.name):
            os.makedirs(os.path.join(root, "src"))
            with open(os.path.join(root, "src", "main.py"), "w", encoding="utf-8") as f:
                f.write("print('same')\n")
            refresh_map(root)
        first = open(os.path.join(self.root, ".asgard", "map", "PROJECT.md"), encoding="utf-8").read()
        second = open(os.path.join(other.name, ".asgard", "map", "PROJECT.md"), encoding="utf-8").read()
        self.assertEqual(first, second)


class TestMapCLI(CodeMapBase):
    def test_setup_map_gitignore_writes_do_not_follow_predictable_temp_symlinks(self):
        from asgard.cli import app

        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write("pyproject.toml", '[project]\nname = "atomic-cli"\n')
        self.write("outside.txt", "unchanged\n")
        outside = os.path.join(self.root, "outside.txt")
        os.symlink(outside, os.path.join(self.root, f"..gitignore.{os.getpid()}.tmp"))
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        os.symlink(outside, os.path.join(self.root, ".asgard", f"..gitignore.{os.getpid()}.tmp"))

        with mock.patch("asgard.commands.map.os.getcwd", return_value=self.root):
            result = CliRunner().invoke(app, ["setup", "map", "--json"])
        self.assertEqual(result.exit_code, 0, result.stdout)
        self.assertEqual(open(outside, encoding="utf-8").read(), "unchanged\n")

    def test_asgard_setup_map_and_check(self):
        from asgard.cli import app

        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write(".gitignore", ".asgard\n")
        self.write("Cargo.toml", '[package]\nname = "forge"\n')
        self.write("src/main.rs", "fn main() {}\n")
        runner = CliRunner()
        with mock.patch("asgard.commands.map.os.getcwd", return_value=self.root):
            setup = runner.invoke(app, ["setup", "map", "--json"])
            self.assertEqual(setup.exit_code, 0, setup.stdout)
            payload = json.loads(setup.stdout)
            self.assertEqual(payload["project"], "forge")
            self.assertTrue(payload["changed"])
            ignored = subprocess.run(
                ["git", "-C", self.root, "check-ignore", ".asgard/map/PROJECT.md"], capture_output=True
            )
            self.assertNotEqual(ignored.returncode, 0, ignored.stdout)

            check = runner.invoke(app, ["setup", "map", "--check", "--json"])
            self.assertEqual(check.exit_code, 0, check.stdout)
            self.assertTrue(json.loads(check.stdout)["ok"])

        self.write("src/lib.rs", "pub fn ready() -> bool { true }\n")
        with mock.patch("asgard.commands.map.os.getcwd", return_value=self.root):
            stale = runner.invoke(app, ["setup", "map", "--check", "--json"])
        self.assertEqual(stale.exit_code, 1, stale.stdout)
        self.assertIn("src/lib.rs", json.loads(stale.stdout)["added"])

    def test_doctor_reports_managed_map_drift(self):
        from asgard.code_map import refresh_map
        from asgard.commands.doctor import _trinity_checks

        self.write("AGENTS.md", "<!-- asgard:trinity -->\n")
        self.write("pyproject.toml", '[project]\nname = "demo"\n')
        self.write("src/demo/__init__.py")
        refresh_map(self.root)
        current = next(c for c in _trinity_checks(self.root) if c["name"] == "codebase map")
        self.assertTrue(current["ok"], current)

        self.write("src/added/__init__.py")
        drift = next(c for c in _trinity_checks(self.root) if c["name"] == "codebase map")
        self.assertFalse(drift["ok"])
        self.assertIn("managed drift", drift["detail"])

    def test_setup_map_uses_git_root_from_nested_directory(self):
        from asgard.cli import app

        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write("pyproject.toml", '[project]\nname = "nested"\n')
        self.write("src/nested/__init__.py")
        nested = os.path.join(self.root, "src", "nested")
        cwd = os.getcwd()
        os.chdir(nested)
        try:
            result = CliRunner().invoke(app, ["setup", "map", "--json"])
        finally:
            os.chdir(cwd)
        self.assertEqual(result.exit_code, 0, result.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".asgard", "map", "PROJECT.md")))
        self.assertFalse(os.path.exists(os.path.join(nested, ".asgard")))

    def test_setup_map_rejects_check_with_dry_run(self):
        from asgard.cli import app

        result = CliRunner().invoke(app, ["setup", "map", "--check", "--dry-run"])
        self.assertEqual(result.exit_code, 2, result.stdout)

    def test_dry_run_reports_index_and_gitignore_changes_without_writing(self):
        from asgard.cli import app

        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write("pyproject.toml", '[project]\nname = "preview"\n')
        with mock.patch("asgard.commands.map.os.getcwd", return_value=self.root):
            CliRunner().invoke(app, ["setup", "map", "--json"])
        self.write(".asgard/map/INDEX.md", "stale\n")
        self.write(".gitignore", ".asgard\n")
        before_index = open(os.path.join(self.root, ".asgard", "map", "INDEX.md")).read()
        with mock.patch("asgard.commands.map.os.getcwd", return_value=self.root):
            result = CliRunner().invoke(app, ["setup", "map", "--dry-run", "--json"])
        payload = json.loads(result.stdout)
        self.assertTrue(payload["changed"])
        self.assertTrue(payload["index_changed"])
        self.assertTrue(payload["gitignore_changed"])
        self.assertEqual(open(os.path.join(self.root, ".asgard", "map", "INDEX.md")).read(), before_index)

    def test_doctor_rejects_manual_map_paths_outside_project(self):
        from asgard.code_map import refresh_map
        from asgard.commands.doctor import _trinity_checks

        self.write("AGENTS.md", "<!-- asgard:trinity -->\n")
        self.write("pyproject.toml", '[project]\nname = "unsafe"\n')
        refresh_map(self.root)
        self.write(".asgard/map/api.md", "# map: api\n\n- `/etc/passwd` — outside\n- `../outside` — traversal\n")
        check = next(c for c in _trinity_checks(self.root) if c["name"] == "codebase map")
        self.assertFalse(check["ok"])
        self.assertIn("unsafe", check["detail"])

    def test_doctor_reports_managed_map_symlink_instead_of_crashing(self):
        from asgard.commands.doctor import _trinity_checks

        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        self.write("AGENTS.md", "<!-- asgard:trinity -->\n")
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        os.symlink(outside.name, os.path.join(self.root, ".asgard", "map"))

        check = next(c for c in _trinity_checks(self.root) if c["name"] == "codebase map")
        self.assertFalse(check["ok"])
        self.assertIn("unsafe", check["detail"])


class TestLanguageSurfaceCoverage(CodeMapBase):
    """Public-surface symbol extraction for languages beyond Python."""

    def render(self) -> str:
        from asgard.code_map import refresh_map

        refresh_map(self.root)
        return open(os.path.join(self.root, ".asgard", "map", "PROJECT.md"), encoding="utf-8").read()

    def test_c_surface_excludes_static_and_control_flow(self):
        self.write("pyproject.toml", '[project]\nname = "cdemo"\n')
        self.write(
            "src/point.c",
            "static int helper(int x) {\n"
            "    if (x > 0) {\n"
            "        return x;\n"
            "    }\n"
            "    return -x;\n"
            "}\n\n"
            "int add(int a, int b) {\n"
            "    return a + b;\n"
            "}\n\n"
            "struct Point {\n"
            "    int x;\n"
            "};\n",
        )
        project_map = self.render()
        self.assertIn("- `src/point.c` — public surface:", project_map)
        self.assertIn("add", project_map)
        self.assertIn("Point", project_map)
        self.assertNotIn("helper", project_map)
        self.assertIn("- Languages by observed source files: C (1)", project_map)

    def test_php_surface_public_methods_only(self):
        self.write("pyproject.toml", '[project]\nname = "phpdemo"\n')
        self.write(
            "src/Widget.php",
            "<?php\nclass Widget {\n    public function render() {}\n    private function hidden() {}\n}\n",
        )
        project_map = self.render()
        self.assertIn("- `src/Widget.php` — public surface:", project_map)
        self.assertIn("Widget", project_map)
        self.assertIn("render", project_map)
        self.assertNotIn("hidden", project_map)

    def test_ruby_swift_csharp_cpp_vue_surfaces_and_language_counts(self):
        self.write("pyproject.toml", '[project]\nname = "polyglot"\n')
        self.write("src/circle.rb", "module Shapes\n  class Circle\n    def area\n      3.14\n    end\n  end\nend\n")
        self.write(
            "src/point.swift",
            "public struct Point {\n    public func distance() -> Double { 0 }\n}\n\nclass Hidden {}\n",
        )
        self.write(
            "src/Widget.cs",
            "namespace Demo {\n    public class Widget {\n        public void Render() {}\n    }\n    internal class Hidden {}\n}\n",
        )
        self.write("src/vector.cpp", "namespace geo {\n\nclass Vector {\npublic:\n    int x, y;\n};\n\n}\n")
        self.write(
            "src/Widget.vue",
            "<template><div>{{ msg }}</div></template>\n<script>\nexport function helper() {}\n</script>\n",
        )
        self.write("src/legacy.jsx", "export function Button() { return null; }\n")

        project_map = self.render()
        self.assertIn("- `src/circle.rb` — public surface:", project_map)
        self.assertIn("Circle", project_map)
        self.assertIn("- `src/point.swift` — public surface:", project_map)
        self.assertIn("Point", project_map)
        self.assertNotIn("Hidden", project_map)
        self.assertIn("- `src/Widget.cs` — public surface:", project_map)
        self.assertIn("- `src/vector.cpp` — public surface:", project_map)
        self.assertIn("Vector", project_map)
        self.assertIn("- `src/Widget.vue` — public surface:", project_map)
        self.assertIn("helper", project_map)
        self.assertIn("- `src/legacy.jsx` — public surface:", project_map)
        self.assertIn("Button", project_map)
        self.assertIn("Ruby (1)", project_map)
        self.assertIn("Swift (1)", project_map)
        self.assertIn("C# (1)", project_map)
        self.assertIn("C++ (1)", project_map)
        self.assertIn("Vue (1)", project_map)
        self.assertIn("JavaScript (1)", project_map)


if __name__ == "__main__":
    unittest.main()
