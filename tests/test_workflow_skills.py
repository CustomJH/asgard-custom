#!/usr/bin/env python3
"""번들 워크플로 스킬 — 목록·호출 방식·본문 계약이 디스크와 일치하는지.

목록을 다시 적는 시험이 아니다. 손으로 유지되는 세 자리(plugin.json 목록, 디스크 디렉터리,
프론트매터)가 서로 어긋나는 형태를 불변식으로 잡는다. 트리거의 한국어 도달도 같은 부류다 —
매칭이 부분 문자열 포함이라 영어만 적힌 트리거는 한국어 지시에서 한 번도 안 걸린다.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import skill_registry  # noqa: E402

_PLUGINS = Path(__file__).resolve().parents[1] / "src" / "asgard" / "assets" / "skill_plugins"
_WORKFLOWS = _PLUGINS / "asgard-workflows"
_SKILLCRAFT = _PLUGINS / "asgard-skillcraft"


def _manifest(plugin: Path) -> dict:
    return json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))


class WorkflowSkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_declared_skills_match_the_directories_on_disk(self):
        for plugin in (_WORKFLOWS, _SKILLCRAFT):
            declared = set(_manifest(plugin)["skills"])
            on_disk = {path.name for path in (plugin / "skills").iterdir() if path.is_dir()}
            self.assertEqual(declared, on_disk, f"{plugin.name}: manifest and disk disagree")
            for name in declared:
                front = (plugin / "skills" / name / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
                self.assertIn(f"name: {name}\n", front, f"{name}: frontmatter name differs from its directory")

    def test_every_route_can_be_reached_from_a_korean_request(self):
        for plugin in (_WORKFLOWS, _SKILLCRAFT):
            for name, route in _manifest(plugin)["routing"].items():
                self.assertTrue(
                    any(not trigger.isascii() for trigger in route["triggers"]),
                    f"{name}: every trigger is ASCII, so a Korean request never matches one",
                )

    def test_invocation_matches_who_has_to_start_each_workflow(self):
        rows = {row["name"]: row for row in skill_registry.skills(self.root)}
        for name in ("council", "blueprint", "quests", "expedition", "inquiry", "lost"):
            self.assertEqual(rows[name]["invocation"], "user", f"{name} must cost nothing per turn")
        for name in ("prototype", "domain-modeling", "codebase-design", "merge-resolution", "escort"):
            self.assertEqual(rows[name]["invocation"], "model", f"{name} must be reachable by the agent")

    def test_council_puts_the_whole_frontier_to_the_user_each_round(self):
        body = skill_registry.show_skill(self.root, "council") or ""
        self.assertIn("frontier", body.lower())
        self.assertIn("in one message", body)
        self.assertIn("asgard-ullr", body)
        self.assertNotIn("exactly one decision question per turn", body)

    def test_lost_stays_one_utterance(self):
        body = skill_registry.show_skill(self.root, "lost") or ""
        self.assertLess(len(body), 600, "a concision corrective fails by growing — keep it one utterance")

    def test_escort_ships_a_library_that_runs(self):
        template = skill_registry.load_skill_for_agent(self.root, "worker", "escort", resource="template.sh")
        for helper in ("ask_secret()", "write_env()", "set_secret()", "open_url()", "stage()"):
            self.assertIn(helper, template)
        path = os.path.join(self.root, "template.sh")
        Path(path).write_text(template, encoding="utf-8")
        self.assertEqual(subprocess.run(["bash", "-n", path], capture_output=True).returncode, 0)

    def test_skillcraft_discloses_skill_packaging_to_its_own_resource(self):
        body = skill_registry.load_skill_for_agent(self.root, "worker", "asgard-skillcraft")
        self.assertIn("`MECHANICS.md`", body)
        self.assertNotIn("disable-model-invocation", body)
        mechanics = skill_registry.load_skill_for_agent(
            self.root, "worker", "asgard-skillcraft", resource="MECHANICS.md"
        )
        self.assertIn("allow_implicit_invocation: false", mechanics)

    def test_expedition_and_prototype_carry_the_current_contract(self):
        expedition = skill_registry.show_skill(self.root, "expedition") or ""
        self.assertIn("decision quest", expedition)
        self.assertIn("in the same message so they run concurrently", expedition)
        prototype = skill_registry.load_skill_for_agent(self.root, "worker", "prototype")
        self.assertIn("prototype/<name>", prototype)
        self.assertIn("self-contained HTML file", prototype)


if __name__ == "__main__":
    unittest.main()
