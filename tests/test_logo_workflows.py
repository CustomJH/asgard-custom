import os
import unittest

from asgard import skill_registry
from asgard.templates.freyja import resolve_freyja_skills


class TestFreyjaLogoWorkflows(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))

    def test_two_primary_workflows_are_pinned_and_freyja_only(self):
        plugin = skill_registry.bundled_plugins()["freyja-logo-workflows"]
        self.assertEqual(plugin["skills"], ["logo-designer", "logo-generator"])
        self.assertEqual(
            plugin["revision"],
            "8f9a4b04009c15b05eeb47b4608d5502abafa609 + bf4e9ac4d4428bda261afcfe981871ceb92d94e6",
        )
        for name in plugin["skills"]:
            self.assertEqual(plugin["routing"][name]["defaults"], ["freyja", "freyja-lead"])
            self.assertIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "freyja")})
            self.assertNotIn(name, {row["name"] for row in skill_registry.available_skills(self.root, "worker")})

    def test_logo_task_matches_both_workflows_without_interactive_figure_collision(self):
        task = "제품 로고 SVG 6개와 interactive showcase 제작"
        native = {name for name, _ in resolve_freyja_skills(task)}
        resolved = {name for name, _ in skill_registry.resolve_skills(self.root, task, "freyja")}
        self.assertNotIn("asgard-freyja-seidr", native)
        self.assertTrue(
            {"asgard-freyja-logo-studio", "logo-designer", "logo-generator"}.issubset(resolved),
            resolved,
        )
        self.assertFalse(
            {"logo-designer", "logo-generator"}
            & {name for name, _ in skill_registry.resolve_skills(self.root, task, "worker")}
        )

    def test_progressive_bodies_cover_direction_generation_and_real_render_gates(self):
        designer = skill_registry.load_skill_for_agent(self.root, "freyja", "logo-designer")
        generator = skill_registry.load_skill_for_agent(self.root, "freyja", "logo-generator")
        for anchor in (
            "3–5개 의미적으로 독립된 방향, 총 6개 이상 후보",
            "16/32px, 흑백, 역상에서 직접 보지 못한 후보는 `UNVERIFIED`",
            "사용자 선택 또는 독립 visual verdict",
            "qlmanage -t -s <px>",
        ):
            self.assertIn(anchor, designer)
        for anchor in (
            "topology를 분산",
            "positive/reverse 버전을 별도 실측",
            "쇼케이스는 승자 확정 **후**",
            "법적 클리어런스가 아니며",
        ):
            self.assertIn(anchor, generator)


if __name__ == "__main__":
    unittest.main()
