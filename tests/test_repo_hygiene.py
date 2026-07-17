"""리포 위생 불변식 — 이 저장소 한정 커밋 경계.

`.asgard/asgard-setting-project.json` 은 업스트림 기본에선 팀 공유(비밀 없음 전제)지만,
이 저장소에선 중요정보라 커밋 금지다 (오딘 결정 26-07-18). 방어는 `.asgard/.gitignore` 에서
업스트림 예외(`!asgard-setting-project.json`)를 제거하는 것인데, `asgard setup` 재실행이
그 파일을 무조건 덮어써(setup.py `_ASGARD_GITIGNORE`) 예외를 부활시킬 수 있다 —
이 테스트가 재노출을 CI 에서 잡는다.
"""

from __future__ import annotations

import os
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SENSITIVE = ".asgard/asgard-setting-project.json"


class TestRepoHygiene(unittest.TestCase):
    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, timeout=30)

    def setUp(self):
        if self._git("rev-parse", "--git-dir").returncode != 0:
            self.skipTest("git 저장소 밖 (sdist 등) — 위생 검사는 저장소 문맥 전용")

    def test_project_settings_json_is_git_ignored(self):
        """중요정보 파일이 unignore 로 재노출되면 실패 — `git add .` 한 번에 유출되는 상태다."""
        p = self._git("check-ignore", "-q", SENSITIVE)
        self.assertEqual(
            p.returncode,
            0,
            f"{SENSITIVE} 가 git 에 노출됨 — .asgard/.gitignore 의 업스트림 예외가 부활했는지 확인하라",
        )

    def test_project_settings_json_is_not_tracked(self):
        """이미 인덱스에 들어간 경우도 잡는다 — ignore 규칙은 tracked 파일에 무력하다."""
        p = self._git("ls-files", "--", SENSITIVE)
        self.assertEqual(p.stdout.strip(), "", f"{SENSITIVE} 가 git 인덱스에 추적되고 있음 — git rm --cached 필요")


if __name__ == "__main__":
    unittest.main()
