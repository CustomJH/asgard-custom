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

    def test_the_runner_hidden_in_a_variable_is_still_the_runner(self) -> None:
        """`g=git; $g stash` 는 `git stash` 다.

        토큰 분류기는 `$g` 를 git 이 아니라고 읽었고, 정규식 표는 `git` 과 하위 명령이
        텍스트상 떨어져 있어 역시 못 봤다 — 두 갈래가 같은 자리에서 함께 비껴갔다
        (26-08-05 감사)."""
        for command in (f"g=git; $g {STASH}", "G=git ; $G reset --hard HEAD", f"g=git && ${{g}} {STASH}"):
            with self.subTest(command=command):
                self.assertIsNotNone(blocked_reason(command), command)

    def test_list_argument_form_is_read_as_a_command(self) -> None:
        """인터프리터가 리스트로 넘기면 토큰 사이에 공백이 없고 `','` 가 있다.

        패턴마다 구분자를 넓히면 다음 패턴에서 같은 구멍이 다시 난다 — 세 턴 연속 그렇게 났다.
        입구에서 한 번 펴는 것이 이 시험이 지키는 계약이고, 그래서 **플래그 자리까지** 잰다."""
        for argv in (
            f"['git','{STASH}']",
            "['git','push','--force']",
            "['git','reset','--hard']",
            "['git','clean','-fd']",
            "['git','branch','-D','x']",
            "['git','checkout','--','.']",
            "['git','rebase','-i']",
        ):
            command = f'python3 -c "import subprocess;subprocess.run({argv})"'
            with self.subTest(command=command):
                self.assertIsNotNone(blocked_reason(command), command)

    def test_no_wrapper_unblocks_repository_destruction(self) -> None:
        """감싼 형태와 안 감싼 형태의 답이 갈리면 감싸는 것이 곧 우회다."""
        for command in (
            'sh -c "rm -rf .git"',
            "bash -c 'rm -rf .git'",
            'eval "rm -rf .git"',
            "`rm -rf .git`",  # 역따옴표는 `.git` 뒤에 공백도 끝도 안 남긴다
            "echo `rm -rf .git`",
            "rm -rf .git",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(blocked_reason(command), command)

    def test_destroying_the_repository_without_naming_git_or_rm(self) -> None:
        """`shutil.rmtree('.git')` 에는 git 토큰도 `rm` 도 없어 두 갈래가 모두 비껴갔다."""
        for command in (
            "python3 -c \"import shutil;shutil.rmtree('.git')\"",
            "python3 -c \"import os;os.rename('.git','/tmp/x')\"",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(blocked_reason(command), command)

    def test_talking_about_the_repository_is_not_destroying_it(self) -> None:
        """확장이 커진 만큼 오탐도 같이 재 둔다 — 설명하는 문장은 명령이 아니다."""
        for command in (
            'echo "the .git directory holds history"',
            "wc -c src/asgard/hooks/git_guard.py",
            'for f in a b; do wc -c "$f"; done',
            "ls .github/workflows",
        ):
            with self.subTest(command=command):
                self.assertIsNone(blocked_reason(command), command)


if __name__ == "__main__":
    unittest.main()
