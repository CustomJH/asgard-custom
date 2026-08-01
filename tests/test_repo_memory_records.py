"""이 저장소의 2차 메모리 정본이 Git 에 있는가 — 커밋 경계 불변식 (26-08-01 결정).

2차 메모리는 "정본은 Git" 위에 서 있다. 그런데 이 저장소는 `**/.asgard/` 한 줄로 자기
`.asgard` 를 통째로 무시하고 있었고, 그래서 승인된 record 4건이 추적 밖에 있었다
(`git ls-files .asgard` 가 빈 출력) — 자기 제품의 서사가 자기 저장소에서만 성립하지 않는
상태였다. 답은 무시를 걷는 것이 아니라 **records 한 갈래만 뚫는 것**이다: map/·state/·
개인 작업 공간은 이 기계의 런타임 상태지 팀 공유 자산이 아니다.

이 테스트가 지키는 것은 그 경계 자체다. 규칙이 두 파일에 걸쳐 있어서(루트 `.gitignore` 와
`.asgard/.gitignore`) 한쪽만 봐선 결과를 알 수 없고, `asgard setup` 재실행은 안쪽 파일을
스캐폴드 내용으로 덮어써 넓은 예외를 통째로 되살릴 수 있다. 그러니 규칙 문자열이 아니라
**git 의 판정**을 묻는다 — 어느 파일의 몇 번째 줄이 이겼는지는 git 에게 물으면 된다.
"""

from __future__ import annotations

import os
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RECORDS = ".asgard/memory/records"

# 이 저장소에서 .asgard 밖으로 나가면 안 되는 것들 — 런타임 상태와 중요정보.
# asgard-setting-project.json 은 tests/test_repo_hygiene.py 가 따로 못 박는다 (겹쳐도 좋다).
IGNORED = (
    ".asgard/map",
    ".asgard/state",
    ".asgard/quest",
    ".asgard/memory/binding.json",
    ".asgard/memory/synthesis.json",
    ".asgard/asgard-setting-project.json",
)


class TestProjectMemoryRecordsAreTrackable(unittest.TestCase):
    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, timeout=30)

    def setUp(self):
        if self._git("rev-parse", "--git-dir").returncode != 0:
            self.skipTest("git 저장소 밖 (sdist 등) — 커밋 경계 검사는 저장소 문맥 전용")

    def test_approved_records_are_not_git_ignored(self):
        """record 가 무시되면 2차 메모리의 정본이 이 저장소에 존재하지 않는 것과 같다."""
        self.assertEqual(
            self._git("check-ignore", "-q", f"{RECORDS}/").returncode,
            1,
            f"{RECORDS}/ 가 무시되고 있다 — 승인된 record 가 Git 정본이 될 수 없다",
        )
        directory = os.path.join(ROOT, RECORDS)
        for name in sorted(os.listdir(directory)) if os.path.isdir(directory) else []:
            if not name.endswith(".md"):
                continue
            with self.subTest(record=name):
                self.assertEqual(
                    self._git("check-ignore", "-q", f"{RECORDS}/{name}").returncode,
                    1,
                    f"{name} 이 무시되고 있다 — 디렉터리는 뚫렸는데 파일이 막힌 상태다",
                )

    def test_the_rest_of_asgard_stays_out_of_git(self):
        """뚫은 것은 records 한 갈래뿐이다 — 넓히면 이 기계의 상태가 팀 저장소로 샌다."""
        for path in IGNORED:
            with self.subTest(path=path):
                self.assertEqual(
                    self._git("check-ignore", "-q", path).returncode,
                    0,
                    f"{path} 이 추적 가능해졌다 — `asgard setup` 이 .asgard/.gitignore 를 덮어썼는지 확인하라",
                )

    def test_nothing_but_records_shows_up_as_untracked_under_asgard(self):
        """사람이 `git add .asgard` 를 쳤을 때 무엇이 딸려 가는가 — 실제 목록으로 묻는다."""
        listed = self._git("status", "--short", "-uall", "--", ".asgard")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        paths = [line[3:].strip().strip('"') for line in listed.stdout.splitlines() if line.strip()]
        strays = [path for path in paths if not path.startswith(f"{RECORDS}/")]
        self.assertEqual(strays, [], f".asgard 에서 record 아닌 것이 Git 에 보인다: {strays}")


if __name__ == "__main__":
    unittest.main()
