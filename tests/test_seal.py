#!/usr/bin/env python3
"""asgard-seal 스킬 자가 검증 — 스캐폴드 배선 + 하드룰·품질 게이트 문구가 본문에 실존하는지.

실행: uv run pytest tests/test_seal.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.templates.seal import SEAL_SKILL_MD  # noqa: E402


class TestScaffold(unittest.TestCase):
    def test_plan_contains_seal_skill_cc(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=False, codex=False, root="/tmp/x")
        paths = [p for p, _ in files]
        self.assertTrue(any(p.endswith(os.path.join("asgard-seal", "SKILL.md")) for p in paths))
        self.assertFalse(any(".agents" in p for p in paths))  # cc 단독은 .claude 스코프만

    def test_plan_contains_seal_skill_agents_scope(self):
        from asgard.commands.setup import plan_files

        for flags in ({"cc": False, "cursor": True, "codex": False}, {"cc": False, "cursor": False, "codex": True}):
            files, _ = plan_files(root="/tmp/x", **flags)
            self.assertTrue(any(".agents" in p and "asgard-seal" in p for p, _ in files), flags)


class TestSkillBody(unittest.TestCase):
    """본문 계약 — 자료조사로 확정한 하드룰이 빠지면 스킬의 존재 이유가 사라진다."""

    def test_frontmatter(self):
        self.assertTrue(SEAL_SKILL_MD.startswith("---\nname: asgard-seal\n"))

    def test_no_attribution_footer_rule(self):
        self.assertIn("Co-Authored-By", SEAL_SKILL_MD)
        self.assertIn("Signed-off-by", SEAL_SKILL_MD)

    def test_staging_hygiene_rule(self):
        self.assertIn("`git add -A` / `git add .` 금지", SEAL_SKILL_MD)
        self.assertIn("git diff --cached --stat", SEAL_SKILL_MD)  # staged 재검증 게이트

    def test_secret_and_noverify_gates(self):
        self.assertIn("Canon 4", SEAL_SKILL_MD)
        self.assertIn("`--no-verify` 금지", SEAL_SKILL_MD)

    def test_gitmoji_semver_anchors(self):
        for emoji in ("✨", "🐛", "♻️", "💥", "🎉"):
            self.assertIn(emoji, SEAL_SKILL_MD)
        self.assertIn("BREAKING CHANGE", SEAL_SKILL_MD)  # Conventional Commits 1.0.0
        self.assertIn("major", SEAL_SKILL_MD)  # 💥 semver 매핑

    def test_commit_message_canon(self):
        self.assertIn("이 봉인을 적용하면", SEAL_SKILL_MD)  # 명령형 판별 (cbeams 테스트의 우리 용어판)
        self.assertIn("50자 목표·72자 상한", SEAL_SKILL_MD)
        self.assertIn("72자 wrap", SEAL_SKILL_MD)

    def test_atomic_commit_rules(self):
        self.assertIn("1 커밋 = 1 논리 변경", SEAL_SKILL_MD)
        self.assertIn("독립 revert", SEAL_SKILL_MD)
        self.assertIn("리팩터 vs 행동 변경", SEAL_SKILL_MD)


if __name__ == "__main__":
    unittest.main(verbosity=1)
