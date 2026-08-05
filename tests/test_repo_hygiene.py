"""리포 위생 불변식 — 이 저장소 한정 커밋 경계.

`.asgard/asgard-setting-project.json` 은 팀 공유 설정이다 (오딘 결정 26-08-05: "어차피 다
나중에 넣어야 하니까 .asgard gitignore 풀어"). 26-07-18 에는 반대로 커밋 금지였고, 그때의
방어는 `.asgard/.gitignore` 에서 업스트림 예외를 지우는 것이었다 — 그 결정이 뒤집혔으므로
이 파일이 지키는 것도 바뀐다.

**공유가 되면 지킬 것도 바뀐다.** 예전 질문은 "이 파일이 새어 나가는가"였고, 지금 질문은
"새어 나가도 되는 것만 들어 있는가"다. 커밋되는 파일에 백엔드 자격증명이 하나 들어오는
순간 그것은 곧바로 팀 저장소의 비밀이 된다 — 그래서 키 이름을 본다.

값은 안 본다 (Canon 4). 이름만으로 판정하는 것이 요점이다: 값을 읽어 판정하는 검사는
그 자체가 비밀을 로그로 옮긴다.
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SETTINGS = ".asgard/asgard-setting-project.json"

# 자격증명을 담는 이름들. 부분일치로 본다 — `api_key`·`authToken`·`db_password` 를 다 잡는다.
SECRET_NAMES = ("secret", "token", "password", "passwd", "credential", "api_key", "apikey", "private_key")


class TestSharedSettingsStayShareable(unittest.TestCase):
    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, timeout=30)

    def setUp(self):
        if self._git("rev-parse", "--git-dir").returncode != 0:
            self.skipTest("git 저장소 밖 (sdist 등) — 위생 검사는 저장소 문맥 전용")

    def test_project_settings_json_is_trackable(self):
        """팀 공유 설정이 무시되면 팀이 같은 정책으로 못 돈다 — 26-08-05 결정의 반대 방향 감시."""
        self.assertEqual(
            self._git("check-ignore", "-q", SETTINGS).returncode,
            1,
            f"{SETTINGS} 가 무시되고 있다 — `.asgard/.gitignore` 에서 예외가 다시 지워졌는지 확인하라",
        )

    def test_shared_settings_carry_no_credential_shaped_keys(self):
        """커밋되는 설정에 자격증명 이름이 들어오면 그 순간 팀 저장소의 비밀이 된다."""
        path = os.path.join(ROOT, SETTINGS)
        if not os.path.exists(path):
            self.skipTest("설정 파일 없음 — 스캐폴드 전 저장소")
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)

        found: list[str] = []

        def walk(node: object, path: str = "") -> None:
            if isinstance(node, dict):
                for raw_key, value in node.items():
                    key = str(raw_key)
                    here = f"{path}.{key}" if path else key
                    if any(name in key.lower() for name in SECRET_NAMES):
                        found.append(here)
                    walk(value, here)
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")

        walk(payload)
        self.assertEqual(
            found,
            [],
            f"공유 설정에 자격증명 이름이 있다: {found} — 그 값은 이 파일이 아니라 환경변수나 "
            "`~/.asgard` 의 기계 로컬 설정에 둔다",
        )


class TestSetupLeavesANarrowedIgnoreAlone(unittest.TestCase):
    """셋업이 기존 `.asgard/.gitignore` 를 덮지 않는가.

    26-08-04 실측: `asgard init --cc` 한 번에 map/·binding.json·asgard-setting-project.json
    셋이 추적 가능해졌다. 지금은 그 넓은 쪽이 이 저장소가 원하는 상태지만, 셋업이 **사용자가
    손으로 좁혀 둔 파일을 덮어쓰는가**는 방향과 무관한 별개의 계약이다 — 좁히기로 한 저장소에서
    재실행 한 번에 도로 넓어지면 그것은 스캐폴드가 결정을 뒤집은 것이다."""

    def test_preserved_ignore_is_not_rewritten(self):
        import tempfile
        from pathlib import Path

        from asgard.commands import setup

        narrowed = "*\n!memory/\nmemory/*\n!memory/records/\n!.gitignore\n"
        scaffold = narrowed + "!map/\n!memory/binding.json\n!asgard-setting-project.json\n"
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            target = Path(td, ".asgard", ".gitignore")
            target.parent.mkdir(parents=True)
            target.write_text(narrowed, encoding="utf-8")
            os.chdir(td)
            try:
                setup._scaffold([(str(target), scaffold)], "test", force=False, dry_run=False)
            finally:
                os.chdir(cwd)
            self.assertEqual(target.read_text(encoding="utf-8"), narrowed)


if __name__ == "__main__":
    unittest.main()
