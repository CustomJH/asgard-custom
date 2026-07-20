#!/usr/bin/env python3
"""Bundled instruction compiler: discovery, memory boundary, and lazy reference."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import skill_registry  # noqa: E402


class InstructionCompilerSkillTest(unittest.TestCase):
    def test_worker_can_discover_and_load_compiler_without_exposing_raw_memory(self):
        with tempfile.TemporaryDirectory() as root:
            name = "asgard-instruction-compiler"
            self.assertEqual(
                skill_registry.bundled_plugins()[name]["revision"],
                "f41b650435b62dec6d5b1dc3598ac4679f8b7ae7",
            )
            self.assertIn(name, {row["name"] for row in skill_registry.available_skills(root, "worker")})
            self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(root, "freyja")})
            self.assertIn(name, dict(skill_registry.resolve_skills(root, "서브 에이전트에게 지시를 위임", "worker")))

            body = skill_registry.load_skill_for_agent(root, "worker", name)
            self.assertIn("Never request or expose private chain-of-thought", body)
            self.assertIn("Do not forward raw `<memory-context>`", body)
            self.assertNotIn("Vague request recovery", body)

            patterns = skill_registry.load_skill_for_agent(root, "worker", name, "references/PATTERNS.md")
            self.assertIn("Vague request recovery", patterns)
            self.assertIn("The coordinator owns cross-agent synthesis", patterns)

            from asgard.commands.setup import plan_files

            files, _ = plan_files(cc=True, cursor=False, codex=True, root=root)
            adapter = dict(files)[os.path.join(root, ".agents", "skills", name, "SKILL.md")]
            self.assertIn(f"asgard skills show {name}", adapter)


if __name__ == "__main__":
    unittest.main()
