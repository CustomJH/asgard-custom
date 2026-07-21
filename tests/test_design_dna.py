import tempfile
import unittest

from asgard import skill_registry


class DesignDnaSkillTest(unittest.TestCase):
    def test_design_dna_is_pinned_freyja_scoped_and_non_competing(self):
        name = "design-dna"
        with tempfile.TemporaryDirectory() as root:
            plugin = skill_registry.bundled_plugins()[name]
            self.assertEqual(plugin["revision"], "9d9d79568df31cd846681f89fd3be1c3ce0c2aff")
            self.assertEqual(plugin["license"], "MIT")
            self.assertEqual(plugin["routing"][name]["defaults"], ["freyja", "freyja-lead"])

            for agent in ("freyja", "freyja-lead"):
                self.assertIn(name, {row["name"] for row in skill_registry.available_skills(root, agent)})
            self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(root, "worker")})
            with self.assertRaisesRegex(ValueError, "not available"):
                skill_registry.load_skill_for_agent(root, "worker", name)

            targeted = {
                skill
                for skill, _ in skill_registry.resolve_skills(
                    root, "스크린샷 디자인 시스템 추출 후 Design DNA JSON 생성", "freyja"
                )
            }
            self.assertIn(name, targeted)
            generic = {skill for skill, _ in skill_registry.resolve_skills(root, "랜딩 페이지 UI 디자인", "freyja")}
            self.assertNotIn(name, generic)

            body = skill_registry.load_skill_for_agent(root, "freyja", name)
            self.assertIn("It is not Freyja's general design authority", body)
            self.assertIn("reference evidence", body)
            self.assertIn('use `null` or `"unknown"`', body)
            self.assertIn("Do not add a CDN or an unpinned `latest` dependency", body)

            schema = skill_registry.show_skill_resource(root, name, "references/schema.md")
            self.assertIn("design_system", schema)
            self.assertIn("design_style", schema)
            self.assertIn("visual_effects", schema)
            guide = skill_registry.show_skill_resource(root, name, "references/generation-guide.md")
            self.assertIn("# Asgard precedence", guide)
            self.assertNotIn("@latest", guide)


if __name__ == "__main__":
    unittest.main()
