import tempfile
import unittest

from asgard import skill_registry
from asgard.templates.roles import ROLE_AGENTS


class DesignMdUsageTest(unittest.TestCase):
    def test_freyja_is_guided_to_validate_existing_design_md(self):
        with tempfile.TemporaryDirectory() as root:
            applied = {
                name
                for name, _ in skill_registry.resolve_skills(
                    root, "DESIGN.md를 적용해 새 랜딩 페이지를 구현해줘", "freyja"
                )
            }
            self.assertIn("design-md-review", applied)
            generic = {name for name, _ in skill_registry.resolve_skills(root, "새 랜딩 페이지 구현", "freyja")}
            self.assertNotIn("design-md-review", generic)

            body = skill_registry.load_skill_for_agent(root, "freyja", "design-md-review")
            self.assertIn("run lint before editing", body)
            self.assertIn("After implementation", body)
            self.assertIn("browser and accessibility checks", body)

            role = dict(ROLE_AGENTS)["asgard-freyja.md"]
            self.assertIn("`design-md-review`로 lint", role)
            self.assertIn("없으면 생략", role)


if __name__ == "__main__":
    unittest.main()
