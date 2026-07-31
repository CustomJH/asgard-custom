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

    def test_allowed_tools_preapproval(self):
        """봉인 절차의 git 명령은 스킬 활성 중 사전 승인 — 승인 완화일 뿐, 강제(add -A 금지 등)는
        본문 하드룰 + git-guard 훅이 계속 담당한다."""
        self.assertIn("allowed-tools:", SEAL_SKILL_MD)
        for rule in ("Bash(git add *)", "Bash(git commit *)", "Bash(git branch --show-current)"):
            self.assertIn(rule, SEAL_SKILL_MD)

    def test_no_attribution_footer_rule(self):
        self.assertIn("Co-Authored-By", SEAL_SKILL_MD)
        self.assertIn("Signed-off-by", SEAL_SKILL_MD)

    def test_staging_hygiene_rule(self):
        self.assertIn("No `git add -A` / `git add .`", SEAL_SKILL_MD)
        self.assertIn("git diff --cached --stat", SEAL_SKILL_MD)  # staged 재검증 게이트

    def test_secret_and_noverify_gates(self):
        self.assertIn("Canon 4", SEAL_SKILL_MD)
        self.assertIn("No `--no-verify`", SEAL_SKILL_MD)

    def test_gitmoji_semver_anchors(self):
        for emoji in ("✨", "🐛", "♻️", "💥", "🎉"):
            self.assertIn(emoji, SEAL_SKILL_MD)
        self.assertIn("BREAKING CHANGE", SEAL_SKILL_MD)  # Conventional Commits 1.0.0
        self.assertIn("major", SEAL_SKILL_MD)  # 💥 semver 매핑

    def test_commit_message_canon(self):
        self.assertIn("If this seal is", SEAL_SKILL_MD)  # 명령형 판별 (cbeams 테스트의 우리 용어판)
        self.assertIn("Target 50 chars, hard cap 72", SEAL_SKILL_MD)
        self.assertIn("Wrap at 72 chars", SEAL_SKILL_MD)

    def test_subject_convention_is_per_language_not_translated_english(self):
        """한국어에는 커밋 명령형이 없다 — 영어 규칙만 주면 모델이 평서형 경구로 메운다."""
        self.assertIn("개조식 명사형", SEAL_SKILL_MD)
        self.assertIn("Korean has no commit imperative", SEAL_SKILL_MD)
        self.assertIn("aphorism", SEAL_SKILL_MD)  # 경구는 제목이 아니라 본문 첫 줄이다

    def test_body_is_an_engineering_record_not_an_essay(self):
        """가장 자주 무너지는 자리 — 규칙을 다 지키고도 정비하는 사람이 쓸 수 없는 글이 나온다."""
        self.assertIn("an engineering record, not an essay", SEAL_SKILL_MD)
        self.assertIn("Name the code", SEAL_SKILL_MD)  # 본문의 주장은 diff 의 무언가를 가리킨다
        self.assertIn("No aphorisms, metaphors, or narration", SEAL_SKILL_MD)
        # 일반론은 이 커밋의 것이 아니다 — 다른 커밋에서도 참이면 지운다
        self.assertIn("survive unchanged in a different commit", SEAL_SKILL_MD)
        self.assertIn("bisecting a regression", SEAL_SKILL_MD)  # 독자를 못 박는다

    def test_grammar_is_not_traded_for_the_line_budget(self):
        """50/72는 줄 예산이지 조사를 떼거나 낱말을 자를 근거가 아니다."""
        self.assertIn("quest_log.py를", SEAL_SKILL_MD)  # 붙여 쓴 본보기
        self.assertIn("never `quest_log.py 를`", SEAL_SKILL_MD)
        self.assertIn("불요", SEAL_SKILL_MD)  # 조어 금지 본보기
        self.assertIn("never a licence to drop a particle", SEAL_SKILL_MD)

    def test_atomic_commit_rules(self):
        self.assertIn("1 commit = 1 logical change", SEAL_SKILL_MD)
        self.assertIn("Independent-revert", SEAL_SKILL_MD)
        self.assertIn("Refactor vs. behavior change", SEAL_SKILL_MD)


if __name__ == "__main__":
    unittest.main(verbosity=1)
