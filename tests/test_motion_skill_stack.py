#!/usr/bin/env python3
"""Purpose-routed Freyja motion/video skills and the Aceternity live catalog."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import skill_bank, skill_registry  # noqa: E402


class MotionSkillStackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = os.path.join(self.tmp.name, "home")
        skill_bank._cache.clear()

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.old_home
        skill_bank._cache.clear()
        self.tmp.cleanup()

    def test_video_and_web_tasks_compose_only_freyja_skills(self):
        video = {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "제품 설명 영상 제작", "freyja")}
        self.assertIn("asgard-freyja-video", video)
        self.assertIn("explainer-video", video)

        web = {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "Lottie 마이크로인터랙션", "freyja")}
        self.assertIn("asgard-freyja-motion", web)
        self.assertIn("lottie-animation", web)
        self.assertIn("micro-interaction", web)
        self.assertNotIn(
            "explainer-video",
            {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "제품 설명 영상 제작", "worker")},
        )

        available = {row["name"] for row in skill_registry.available_skills(self.tmp.name, "freyja")}
        for name in ("chart-animation", "kinetic-typography", "lottie-animation", "aceternity-ui", "21st-cli-use"):
            self.assertIn(name, available)
        self.assertIn(
            "@lottiefiles/dotlottie-web",
            skill_registry.show_skill_resource(
                self.tmp.name, "lottie-animation", "references/integration-and-export.md"
            ),
        )

        from asgard.agent.heimdall import _skill_support

        note, tools, handlers = _skill_support("freyja", self.tmp.name)
        self.assertIn("explainer-video", note)
        self.assertEqual([tool["name"] for tool in tools], ["load_skill"])
        self.assertIn("The pipeline", handlers["load_skill"]({"name": "explainer-video"}))

    def test_aceternity_parser_keeps_only_live_free_components(self):
        plugin = skill_registry.bundled_plugins()["aceternity-ui"]
        script = Path(plugin["root"], "skills", "aceternity-ui", "scripts", "aceternity.py")
        spec = importlib.util.spec_from_file_location("aceternity_skill", script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        old_dont_write_bytecode = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = old_dont_write_bytecode

        rows = [
            {
                "name": "compare",
                "title": "Compare",
                "description": "Interactive comparison slider",
                "categories": ["slider"],
                "dependencies": ["motion"],
                "installCommand": "npx shadcn@latest add @aceternity/compare",
                "documentationUrl": "https://ui.aceternity.com/components/compare",
                "isPro": False,
                "isTemplate": False,
            },
            {
                "name": "paid-block",
                "installCommand": "npx shadcn@latest add @aceternity/paid-block",
                "isPro": True,
            },
        ]
        page = f"<html><pre>{json.dumps(rows).replace('&', '&amp;')}</pre></html>".encode()
        response = io.BytesIO(page)
        with mock.patch.object(module.urllib.request, "urlopen", return_value=response):
            catalog = module._catalog()
        self.assertEqual([row["name"] for row in catalog], ["compare"])
        self.assertEqual(module._search(catalog, "comparison slider", 8)[0]["name"], "compare")

    def test_21st_cli_is_freyja_only_and_uses_the_pinned_official_cli(self):
        hits = {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "21st 컴포넌트 검색", "freyja")}
        self.assertIn("21st-cli-use", hits)
        self.assertNotIn(
            "21st-cli-use",
            {name for name, _ in skill_registry.resolve_skills(self.tmp.name, "21st 컴포넌트 검색", "worker")},
        )
        with mock.patch("asgard.skill_registry.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertEqual(skill_registry.run_skill(self.tmp.name, "21st-cli-use", ["search", "pricing"]), 0)
        self.assertTrue(run.call_args.args[0][1].endswith("scripts/21st.py"))

        plugin = skill_registry.bundled_plugins()["21st-dev"]
        script = Path(plugin["root"], "skills", "21st-cli-use", "scripts", "21st.py")
        spec = importlib.util.spec_from_file_location("twenty_first_skill", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        old_dont_write_bytecode = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = old_dont_write_bytecode
        with mock.patch.object(module.subprocess, "run") as cli:
            cli.return_value.returncode = 0
            self.assertEqual(module.main(["search", "pricing"]), 0)
        self.assertEqual(cli.call_args.args[0], ["npx", "-y", "@21st-dev/cli@1.7.2", "search", "pricing"])


if __name__ == "__main__":
    unittest.main()
