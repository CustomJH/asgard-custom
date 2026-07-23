"""Freyja clean-rebuild baseline."""

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from asgard import skill_registry
from asgard.templates.freyja import FREYJA_SKILLS, freyja_core_skill, resolve_freyja_skills
from asgard.templates.roles import ROLE_AGENTS, delivery_agents


class TestFreyjaBaseline(unittest.TestCase):
    def test_only_initial_freyja_role_is_active(self):
        roles = dict(ROLE_AGENTS)
        self.assertIn("asgard-freyja.md", roles)
        self.assertNotIn("asgard-freyja-lead.md", roles)
        self.assertEqual(delivery_agents()["freyja"], "standard")
        self.assertNotIn("freyja-lead", delivery_agents())

    def test_core_contract_is_the_only_builtin_freyja_skill(self):
        self.assertEqual(FREYJA_SKILLS, [])
        self.assertEqual(resolve_freyja_skills("랜딩 페이지"), [])
        core = freyja_core_skill()
        self.assertIn("name: asgard-freyja", core)
        self.assertIn("기본 성능 — Freyja Design", core)
        self.assertIn("asgard-freyja-design", core)
        self.assertIn("시각 시스템과 feel을 먼저", core)
        self.assertIn("의미 없는 요소만 덜어낸다", core)
        self.assertIn("아토믹 디자인 시스템으로 설정한다", core)
        self.assertIn("components/atoms|molecules|organisms", core)

    def test_design_engine_carries_atomic_structure_canon(self):
        with tempfile.TemporaryDirectory() as root:
            bodies = dict(skill_registry.client_skill_bodies("freyja", root))
        body = bodies["asgard-freyja-design"]
        self.assertIn("Atomic design project structure", body)
        self.assertIn("components/atoms|molecules|organisms", body)
        self.assertIn("Atomic: <level>", body)
        self.assertIn("lower levels never import higher levels", body)

    def test_complete_freyja_design_engine_is_freyja_only(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                [name for name, _ in skill_registry.client_skill_bodies("freyja", root)],
                ["asgard-freyja-design"],
            )
            self.assertNotIn(
                "asgard-freyja-design",
                {name for name, _ in skill_registry.client_skill_bodies("worker", root)},
            )
            self.assertIn(
                "asgard-freyja-design",
                {name for name, _ in skill_registry.resolve_skills(root, "랜딩 페이지 디자인", "freyja")},
            )

    def test_complete_upstream_snapshot_and_restraint_gate_are_byte_locked(self):
        plugin = skill_registry.bundled_plugins()["freyja-design"]
        skill_root = Path(plugin["root"], "skills", "asgard-freyja-design")
        upstream_root = skill_root / "references" / "vanadis"
        files = [item for item in upstream_root.rglob("*") if item.is_file()]
        digest = hashlib.sha256()
        for item in sorted(files, key=lambda value: value.relative_to(upstream_root).as_posix()):
            relative = item.relative_to(upstream_root).as_posix().encode()
            digest.update(relative + b"\0" + item.read_bytes())

        self.assertEqual(len(files), 3256)
        self.assertEqual(digest.hexdigest(), "e1865a71299fcd3abd8439f0788933f25efd3c5deb0f15196fabcc6d482c18df")
        self.assertEqual(len(list((upstream_root / "skills").glob("*/SKILL.md"))), 21)
        self.assertEqual(len(list((upstream_root / "agents").glob("vanadis-*.md"))), 18)
        restraint = skill_registry.show_skill_resource(
            "",
            "asgard-freyja-design",
            "references/vanadis-restraint/SKILL.md",
        )
        self.assertEqual(
            hashlib.sha256(restraint.encode()).hexdigest(),
            "9bbcbb2a23555b0184dff3ae10ec652da06a7746d35582785959f2a2883e935f",
        )

    def test_design_runtime_reads_references_and_extracts_binary_assets(self):
        plugin = skill_registry.bundled_plugins()["freyja-design"]
        self.assertEqual(plugin["entrypoints"], {"asgard-freyja-design": "freyja_design.py"})
        runner = Path(plugin["root"], "skills", "asgard-freyja-design", "freyja_design.py")

        listed = subprocess.run(
            [sys.executable, str(runner), "reference", "list", "toss"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("toss", listed.stdout.splitlines())

        shown = subprocess.run(
            [sys.executable, str(runner), "reference", "show", "toss"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("Toss", shown.stdout)

        with tempfile.TemporaryDirectory() as destination:
            output = Path(destination, "logo-bg.png")
            extracted = subprocess.run(
                [
                    sys.executable,
                    str(runner),
                    "extract",
                    ".github/assets/logo-bg.png",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            self.assertTrue(output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
