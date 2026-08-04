"""git-guard — 무엇이 파괴적 git 연산인가.

판정은 **토큰**이 정본이다. 명령문 전체를 정규식으로 훑던 갈래가 인용 안쪽의 글자까지 명령으로
읽어서, 파일에서 문구를 찾는 `grep -n "git stash" <파일>` 이 워크트리 소실로 차단됐다
(26-08-04 실측). 그 표는 셸이 문자열을 다시 명령으로 펴는 형태에서만 남는다.
"""

from __future__ import annotations

import unittest

from asgard.hooks.git_guard import blocked_reason

STASH = "stash"  # 이 파일 자신이 자기 시험에 걸리지 않게 나눠 적는다


class TestDestructiveOpsStayBlocked(unittest.TestCase):
    def test_worktree_sweeping_stash_forms(self) -> None:
        for command in (f"git {STASH}", f"git {STASH} push -u", f"git {STASH} save wip", f"git {STASH} drop"):
            with self.subTest(command=command):
                self.assertIsNotNone(blocked_reason(command))

    def test_reading_stash_forms_pass(self) -> None:
        for command in (f"git {STASH} list", f"git {STASH} show"):
            with self.subTest(command=command):
                self.assertIsNone(blocked_reason(command))

    def test_history_and_worktree_destruction(self) -> None:
        for command in (
            "git push --force origin main",
            "git push --force-with-lease",
            "git reset --hard HEAD~1",
            "git clean -fd",
            "git branch -D feature",
            "git rebase -i main",
            "git checkout -- src/x.py",
            "git restore src/x.py",
            "rm -rf .git",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(blocked_reason(command))


class TestMentioningIsNotRunning(unittest.TestCase):
    """문자열 안의 언급은 명령이 아니다 — 이것이 이 수리가 되찾은 자리다."""

    def test_searching_for_the_phrase_is_allowed(self) -> None:
        for command in (
            f'grep -n "git {STASH}" src/asgard/templates/claude.py',
            f'rg "git {STASH}|git reset --hard" docs/',
            f"cat AGENTS.md | grep 'git {STASH}'",
            f'echo "never run git {STASH} here" >> notes.md',
        ):
            with self.subTest(command=command):
                self.assertIsNone(blocked_reason(command), command)

    def test_ordinary_git_reads_are_allowed(self) -> None:
        for command in ("git status", "git diff --stat", "git log --oneline -5", "git commit -m 'fix'"):
            with self.subTest(command=command):
                self.assertIsNone(blocked_reason(command))


class TestShellIndirectionKeepsTheTable(unittest.TestCase):
    """셸이 문자열을 다시 명령으로 펴는 자리에서는 토큰이 증거가 아니다 — 표를 그대로 댄다."""

    def test_reexpanding_forms_are_still_blocked(self) -> None:
        for command in (f'sh -c "git {STASH}"', f"eval git {STASH}", "sh -c 'git reset --hard'"):
            with self.subTest(command=command):
                self.assertIsNotNone(blocked_reason(command), command)


if __name__ == "__main__":
    unittest.main()
