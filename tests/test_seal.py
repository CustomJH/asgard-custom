#!/usr/bin/env python3
"""asgard-seal 스킬 자가 검증 — 배선, gitmoji 제목 형식, 단일 턴 절차.

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
    """본문 계약 — 빠른 커밋 경로와 안전 규칙을 함께 고정한다."""

    def test_frontmatter(self):
        self.assertTrue(SEAL_SKILL_MD.startswith("---\nname: asgard-seal\n"))

    def test_allowed_tools_preapproval(self):
        """봉인 절차의 git 명령은 스킬 활성 중 사전 승인 — 승인 완화일 뿐, 강제(add -A 금지 등)는
        본문 하드룰 + git-guard 훅이 계속 담당한다."""
        self.assertIn("allowed-tools:", SEAL_SKILL_MD)
        for rule in ("Bash(git status *)", "Bash(git diff *)", "Bash(git add *)", "Bash(git commit *)"):
            self.assertIn(rule, SEAL_SKILL_MD)

    def test_allowed_tools_is_a_comma_separated_list(self):
        """26-08-04 회귀 — 공백으로 이으면 "사전 승인"이 한 건도 안 맞는다.

        allowed-tools 는 쉼표 구분 목록이다. 공백으로 이으면 줄 전체가 항목 **하나**로 파싱되고,
        그 하나는 `Bash(git status *) Bash(git diff *) …` 라는 없는 명령과의 정확 일치라 어느
        호출도 안 맞힌다. 그러면 봉인 절차의 git 명령이 전부 승인 프롬프트를 띄우고, 단순 커밋
        한 번이 승인 열몇 번짜리 일이 된다 (실측 5분 이상). `direct_skill` 이 어댑터 프론트매터를
        쉼표로 잇는 것과 같은 계약이라, 상류가 공백으로 적으면 어댑터에서도 그대로 깨진다."""
        line = next(ln for ln in SEAL_SKILL_MD.splitlines() if ln.startswith("allowed-tools:"))
        rules = [part.strip() for part in line.split(":", 1)[1].split(",")]
        self.assertGreater(len(rules), 1)  # 쉼표로 갈렸다 = 항목이 여럿으로 파싱된다
        for rule in rules:
            # 항목 하나에 `Bash(...)` 가 둘 이상이면 쉼표를 빠뜨린 자리다.
            self.assertEqual(rule.count("Bash("), 1, f"한 항목에 규칙이 여럿 뭉쳤어요: {rule}")
            self.assertRegex(rule, r"^Bash\([^()]+\)$", f"규칙 형태가 아님: {rule}")

    def test_model_tier_is_declared_and_reaches_the_adapter(self):
        """절차가 정해진 스킬은 티어를 스스로 적는다 — 호스트가 읽는 자리는 어댑터 프론트매터다.

        `asgard skills show` 로 받는 본문은 그 턴의 모델이 정해진 뒤에 도착하므로, 상류에만
        적으면 아무 효력이 없다."""
        from asgard.templates.skill_router import direct_skill

        self.assertIn("\nmodel: sonnet\n", SEAL_SKILL_MD)
        adapter = direct_skill(SEAL_SKILL_MD)
        self.assertIn("\nmodel: sonnet\n", adapter.split("---", 2)[1])

    def test_no_attribution_footer_rule(self):
        self.assertIn("Co-Authored-By", SEAL_SKILL_MD)
        self.assertIn("Signed-off-by", SEAL_SKILL_MD)

    def test_staging_hygiene_rule(self):
        self.assertIn("No `git add -A` / `git add .`", SEAL_SKILL_MD)
        self.assertIn("git diff --cached --check", SEAL_SKILL_MD)  # staged 재검증 게이트

    def test_secret_and_noverify_gates(self):
        self.assertIn("Canon 4", SEAL_SKILL_MD)
        self.assertIn("No `--no-verify`", SEAL_SKILL_MD)

    def test_conventional_commit_anchors(self):
        self.assertIn("gitmoji", SEAL_SKILL_MD.lower())
        self.assertIn("<gitmoji> <type>[(<scope>)][!]: <description>", SEAL_SKILL_MD)
        self.assertIn("gitmoji는 필수", SEAL_SKILL_MD)
        self.assertIn("없으면 type 기본값", SEAL_SKILL_MD)
        self.assertIn("BREAKING CHANGE", SEAL_SKILL_MD)

    def test_commit_message_canon(self):
        self.assertIn("✨ feat(seal): gitmoji 제목 형식 적용", SEAL_SKILL_MD)
        self.assertIn("🐛 fix(auth): 만료 토큰 거부", SEAL_SKILL_MD)
        self.assertIn("body는 선택 사항", SEAL_SKILL_MD)

    def test_korean_subject_is_a_noun_phrase_not_a_declarative_sentence(self):
        self.assertIn("개조식 명사형", SEAL_SKILL_MD)
        for ending in ("`한다`", "`된다`", "`했다`", "`였다`"):
            self.assertIn(ending, SEAL_SKILL_MD)
        self.assertNotIn('"만료 토큰을 거부한다" ✓', SEAL_SKILL_MD)

    def test_fast_path_has_no_ceremony_or_second_approval(self):
        for rule in (
            "추가 승인을 묻지 않는다",
            "분류표를 만들지 않는다",
            "브랜치 이름을 검사하거나 바꾸지 않는다",
            "테스트나 QA를 다시 실행하지 않는다",
        ):
            self.assertIn(rule, SEAL_SKILL_MD)
        self.assertNotIn("git branch --show-current", SEAL_SKILL_MD)
        self.assertNotIn("git log --oneline", SEAL_SKILL_MD)

    def test_one_inspection_pass_then_stage_verify_and_commit(self):
        self.assertIn("한 번의 확인", SEAL_SKILL_MD)
        self.assertIn("git status --short", SEAL_SKILL_MD)
        self.assertIn("git diff --cached --check", SEAL_SKILL_MD)
        self.assertIn('git commit -m "<subject>"', SEAL_SKILL_MD)

    def test_one_commit_costs_one_round_trip(self):
        """봉인 한 건은 호출 하나다 — stage·검사·commit 이 `&&` 로 이어져야 한다.

        훅이 아니라 왕복이 남은 값이다 (26-08-05 실측: `git` 호출 자체는 0.2초인데 호출 사이
        모델 왕복이 4~10초). 넷으로 쪼갠 절차는 commit 한 건에 왕복 넷을 쓴다. 순서도 고정한다 —
        `&&` 는 앞이 실패하면 뒤를 안 돌리므로, 검사가 commit **앞**에 있어야 게이트다."""
        chain = 'git add -- <named paths> && git diff --cached --check && git commit -m "<subject>"'
        self.assertIn(chain, SEAL_SKILL_MD)
        body = SEAL_SKILL_MD
        self.assertLess(body.index("git diff --cached --check"), body.index('git commit -m "<subject>"'))

    def test_atomic_commit_rules(self):
        self.assertIn("1 commit = 1 logical change", SEAL_SKILL_MD)
        self.assertIn("구현과 그 구현을 검증하는 테스트는 같은 commit", SEAL_SKILL_MD)


if __name__ == "__main__":
    unittest.main(verbosity=1)
