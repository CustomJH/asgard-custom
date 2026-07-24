#!/usr/bin/env python3
"""Native document reading and bundled browser/HWPX skill regressions."""

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from asgard import skill_registry
from asgard.agent import tools
from asgard.agent.tool_kernel import ToolContext, build_session_registry, execute_tool


class DocumentToolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def test_docx_is_readable_by_readonly_native_roles(self):
        path = Path(self.root, "sample.docx")
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>첫 문단</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>둘째</w:t><w:tab/><w:t>문단</w:t></w:r></w:p></w:body></w:document>"
        )
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", xml)

        registry = build_session_registry()
        context = ToolContext(root=self.root, role="mimir", readonly=True)
        result = execute_tool(registry, "read_document", {"path": "sample.docx", "limit": 1}, context)

        self.assertEqual(result.status, "ok")
        self.assertIn("[DOCX · lines 1-1/2]", result.content)
        self.assertIn("다음: offset=2", result.content)
        self.assertIn("첫 문단", result.content)
        self.assertIn("read_document", {row["name"] for row in registry.schemas(context)})

    def test_document_reader_confines_paths_and_normalizes_errors(self):
        registry = build_session_registry()
        result = execute_tool(
            registry,
            "read_document",
            {"path": "../outside.pdf"},
            ToolContext(root=self.root, role="worker"),
        )
        self.assertEqual(result.status, "error")
        self.assertIn("프로젝트 루트를 벗어납니다", result.content)

    def test_pdf_reader_is_paginated(self):
        Path(self.root, "sample.pdf").write_bytes(b"%PDF-test")
        with mock.patch.object(tools, "_extract_pdf", return_value="one\ntwo\nthree"):
            result = tools.run_document(self.root, {"path": "sample.pdf", "offset": 2, "limit": 2})
        self.assertIn("[PDF · lines 2-3/3]", result)
        self.assertTrue(result.endswith("two\nthree"))

    def test_hwp_read_uses_only_an_ephemeral_hwpx(self):
        source = Path(self.root, "sample.hwp")
        source.write_bytes(b"hwp")

        def converted(command, **_kwargs):
            Path(command[-1]).write_bytes(b"hwpx")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(tools.subprocess, "run", side_effect=converted) as run,
            mock.patch.object(tools, "_extract_hwpx", return_value="한글 본문") as extract,
        ):
            result = tools.run_document(self.root, {"path": "sample.hwp"})

        converted_path = Path(run.call_args.args[0][-1])
        extract.assert_called_once()
        self.assertFalse(converted_path.exists())
        self.assertEqual(source.read_bytes(), b"hwp")
        self.assertIn("한글 본문", result)


class BundledDocumentSkillTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(Path(self.root, "home"))

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        self.temp.cleanup()

    def test_hwpx_and_playwright_are_bundled_and_routed(self):
        plugins = skill_registry.bundled_plugins()
        self.assertEqual(plugins["hwpx-skill"]["revision"], "e5e35cbf0bcd8e9aae8013bff1003ab9c5beaf6f")
        self.assertEqual(plugins["playwright-cli"]["version"], "0.1.17")

        worker = {row["name"] for row in skill_registry.available_skills(self.root, "worker")}
        self.assertIn("hwpx", worker)
        self.assertIn("playwright-cli", worker)
        self.assertEqual(
            {row["name"] for row in skill_registry.available_skills(self.root, "freyja")},
            {"asgard-freyja-design", "asgard-freyja-fjadrhamr"},
        )
        self.assertIn(
            "hwpx", {name for name, _ in skill_registry.resolve_skills(self.root, "한글 HWP 문서 읽기", "worker")}
        )
        self.assertIn(
            "playwright-cli",
            {name for name, _ in skill_registry.resolve_skills(self.root, "브라우저로 UI 테스트", "worker")},
        )

    def test_skill_bodies_stay_small_and_full_guides_are_lazy_resources(self):
        hwpx = skill_registry.load_skill_for_agent(self.root, "worker", "hwpx")
        browser = skill_registry.load_skill_for_agent(self.root, "worker", "playwright-cli")
        self.assertLess(len(hwpx), 4_000)
        self.assertLess(len(browser), 4_000)
        self.assertIn("asgard skills run hwpx", hwpx)
        self.assertIn("asgard skills run playwright-cli", browser)
        self.assertIn("HWPX 통합 문서 스킬", skill_registry.show_skill_resource(self.root, "hwpx", "UPSTREAM.md"))
        self.assertIn(
            "Browser Automation with playwright-cli",
            skill_registry.show_skill_resource(self.root, "playwright-cli", "UPSTREAM.md"),
        )

    def test_declared_entrypoints_use_the_existing_python_only_gate(self):
        with mock.patch("asgard.skill_registry.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertEqual(skill_registry.run_skill(self.root, "hwpx", ["--help"]), 0)
            self.assertEqual(skill_registry.run_skill(self.root, "playwright-cli", ["--version"]), 0)
        scripts = [Path(call.args[0][1]).name for call in run.call_args_list]
        self.assertEqual(scripts, ["asgard_hwpx.py", "asgard_playwright.py"])


if __name__ == "__main__":
    unittest.main()
