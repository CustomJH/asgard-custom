"""`.asgard` 의 커밋 경계 — 무엇이 팀의 것이고 무엇이 이 기계의 것인가.

26-08-01 에는 `memory/records/` **한 갈래만** 뚫려 있었다. 26-08-05 에 오딘이 뒤집었다:
"어차피 다 나중에 넣어야 하니까 .asgard gitignore 풀어". 그래서 경계가 옮겨졌다 —
팀이 함께 읽는 자산(지도·기억 정본·프로젝트 설정·결속)은 Git 에, 이 기계에서만 뜻이 있는
런타임(퀘스트 로그·상태 파일·배차 DB)은 밖에.

경계가 옮겨져도 **경계가 있다는 사실**은 그대로다. 런타임까지 들어오면 세션마다 수백 개
파일이 diff 에 뜨고, 그 소음 속에서 진짜 변경을 아무도 못 읽는다.

규칙이 두 파일에 걸쳐 있어서(루트 `.gitignore` 와 `.asgard/.gitignore`) 한쪽만 봐선 결과를
알 수 없다. 그러니 규칙 문자열이 아니라 **git 의 판정**을 묻는다 — 어느 파일의 몇 번째 줄이
이겼는지는 git 에게 물으면 된다.

검사는 양방향이다. 열려야 할 것이 닫히면 팀이 자산을 못 받고, 닫혀야 할 것이 열리면 이
기계의 런타임이 팀 저장소로 샌다.
"""

from __future__ import annotations

import os
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RECORDS = ".asgard/memory/records"

# 팀의 것 — 함께 읽고 함께 고친다. `.asgard/.gitignore` 가 실제로 여는 목록과 같아야 한다:
# 두 목록이 갈라지면 정본으로 저장된 파일이 여기서 낯선 것으로 잡힌다 (26-08-11: local 레인
# 문서가 이 저장소에 처음 생기자 `memory/documents/` 가 빠져 있던 것이 드러났다).
SHARED = (
    ".asgard/.gitignore",
    ".asgard/map",
    ".asgard/memory/records",
    ".asgard/memory/documents",
    ".asgard/memory/binding.json",
    ".asgard/asgard-setting-project.json",
)

# 이 기계의 것 — 런타임 상태. 열리면 diff 가 세션 소음으로 덮인다.
MACHINE_LOCAL = (
    ".asgard/state",
    ".asgard/quest",
    ".asgard/memory/synthesis.json",
    ".asgard/orchestration.db",
)


class TestAsgardCommitBoundary(unittest.TestCase):
    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, timeout=30)

    def setUp(self):
        if self._git("rev-parse", "--git-dir").returncode != 0:
            self.skipTest("git 저장소 밖 (sdist 등) — 커밋 경계 검사는 저장소 문맥 전용")

    def test_shared_assets_are_not_git_ignored(self):
        """팀 자산이 무시되면 그 정본이 이 저장소에 존재하지 않는 것과 같다.

        없는 자리는 안 묻는다. 디렉터리 전용 예외(`!memory/records/`)는 git 이 그 경로를
        디렉터리로 볼 수 있을 때만 적용된다 — 디스크에 없는 경로에 대고 물으면 규칙이 아니라
        부재가 답으로 나온다. 26-08-05 재초기화로 `memory/` 갈래가 통째로 없어졌고(4669fe7),
        그때 이 검사가 규칙이 아니라 그 부재를 쟀다."""
        for path in SHARED:
            with self.subTest(path=path):
                if not os.path.exists(os.path.join(ROOT, path)):
                    self.skipTest(f"{path} 이 이 저장소에 없다 — 무시 여부를 물을 자리가 아니다")
                self.assertEqual(
                    self._git("check-ignore", "-q", path).returncode,
                    1,
                    f"{path} 이 무시되고 있다 — `asgard setup` 이 .asgard/.gitignore 를 좁혔는지 확인하라",
                )

    def test_records_are_trackable_file_by_file(self):
        """디렉터리는 뚫렸는데 파일이 막힌 상태를 잡는다 — negation 순서가 어긋나면 그렇게 된다."""
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

    def test_machine_runtime_stays_out_of_git(self):
        """경계를 넓히는 것과 없애는 것은 다르다 — 런타임은 여전히 이 기계의 것이다."""
        for path in MACHINE_LOCAL:
            with self.subTest(path=path):
                self.assertEqual(
                    self._git("check-ignore", "-q", path).returncode,
                    0,
                    f"{path} 이 추적 가능해졌다 — 런타임이 팀 저장소로 샌다",
                )

    def test_nothing_outside_the_shared_set_shows_up_under_asgard(self):
        """사람이 `git add .asgard` 를 쳤을 때 무엇이 딸려 가는가 — 실제 목록으로 묻는다."""
        listed = self._git("status", "--short", "-uall", "--", ".asgard")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        paths = [line[3:].strip().strip('"') for line in listed.stdout.splitlines() if line.strip()]
        strays = [path for path in paths if not any(path.startswith(shared) for shared in SHARED)]
        self.assertEqual(strays, [], f".asgard 에서 공유 대상 밖의 것이 Git 에 보인다: {strays}")


if __name__ == "__main__":
    unittest.main()
