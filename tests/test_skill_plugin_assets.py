"""벤더링 스킬 팩 자산 무결성 — 두 번 겪은 자산 소실 사고의 회귀 가드.

사고 계보: ① vanadis `web/**/lib`·`.claude` 가 블랭킷 gitignore(`lib/`, `.claude`)에
먹혀 sdist 빌드가 깨졌다. ② freyja2 `engine/scripts/lib` 15모듈이 같은 `lib/` 규칙에
걸려 봉인(285a181)에서 통째 소실됐고, context.mjs 등 lib 의존 스크립트가 실행 즉사였다.

가드 2종:
- ESM 상대 import 해석 — 벤더링 스크립트가 가리키는 이웃 모듈은 디스크에 실재해야
  한다(부분 벤더링을 즉시 적발; CI 는 커밋 트리에서 돌므로 git 소실도 여기서 걸린다).
- git 가시성 — assets 아래 파일은 아티팩트(캐시류) 예외를 빼고 git-ignore 되면
  안 된다(워킹트리엔 있는데 커밋에서 빠질 상태를 seal 전에 적발).
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_ASSETS = _REPO / "src" / "asgard" / "assets"
_PLUGINS = _ASSETS / "skill_plugins"

# 확장자 있는 상대 지정자만 강제한다 — 확장자 생략(번들러 문법)은 정적 판정 불가.
_REL = r"['\"](\.\.?/[^'\"]+?\.(?:mjs|js|json))['\"]"
_IMPORT_PATTERNS = [
    re.compile(r"\bfrom\s*" + _REL),  # import/export … from './x'
    re.compile(r"\bimport\s*\(\s*" + _REL),  # dynamic import('./x')
    re.compile(r"\bimport\s+" + _REL),  # side-effect import './x'
    re.compile(r"\bnew\s+URL\s*\(\s*" + _REL),  # new URL('./x', import.meta.url)
]

# git 가시성 검사에서 눈감아 주는 아티팩트 — .gitignore 자산 스코프 재제외와 동일 목록.
_IGNORABLE = ("__pycache__", "node_modules")


class TestVendoredAssetIntegrity(unittest.TestCase):
    def test_relative_imports_resolve(self):
        """벤더링 스크립트의 상대 import 대상은 전부 디스크에 실재한다."""
        missing: list[str] = []
        scanned = 0
        for src in sorted(_PLUGINS.rglob("*")):
            if src.suffix not in (".mjs", ".js") or not src.is_file():
                continue
            if "node_modules" in src.parts:
                continue
            scanned += 1
            text = src.read_text(encoding="utf-8", errors="replace")
            for pat in _IMPORT_PATTERNS:
                for spec in pat.findall(text):
                    target = (src.parent / spec).resolve()
                    if not target.is_file():
                        rel = src.relative_to(_REPO)
                        missing.append(f"{rel} → {spec}")
        self.assertGreater(scanned, 0, "스캔된 벤더링 스크립트가 없다 — 경로 확인")
        self.assertEqual(
            missing,
            [],
            "벤더링 스크립트가 존재하지 않는 이웃 모듈을 import 한다(부분 벤더링):\n" + "\n".join(missing),
        )

    def test_assets_are_git_visible(self):
        """assets 아래 파일은 캐시류를 빼고 git-ignore 되면 안 된다(소실 예방)."""
        candidates = [
            p.relative_to(_REPO).as_posix()
            for p in _ASSETS.rglob("*")
            if p.is_file()
            and not any(part in _IGNORABLE for part in p.parts)
            and p.suffix not in (".pyc", ".pyo")
            and p.name != ".DS_Store"
        ]
        self.assertGreater(len(candidates), 0)
        try:
            proc = subprocess.run(
                ["git", "check-ignore", "--stdin", "-z"],
                cwd=_REPO,
                input="\0".join(candidates).encode(),
                capture_output=True,
                timeout=60,
            )
        except OSError, subprocess.TimeoutExpired:  # git 부재 환경(설치본 등)
            self.skipTest("git 사용 불가 — 가시성 검사 생략")
        if proc.returncode == 1:  # 아무것도 ignore 되지 않음 — 통과
            return
        if proc.returncode != 0:
            self.skipTest(f"git check-ignore 실패(rc={proc.returncode}) — 저장소 아님")
        ignored = [p for p in proc.stdout.decode().split("\0") if p]
        self.fail(
            "패키지 자산이 gitignore 에 먹혀 커밋에서 소실될 상태다 — .gitignore 의 "
            "자산 재포함 블록(파일 말미)이 블랭킷 규칙보다 뒤에 있는지 확인하라:\n"
            + "\n".join(ignored[:40])
            + ("" if len(ignored) <= 40 else f"\n… 외 {len(ignored) - 40}건")
        )


if __name__ == "__main__":
    unittest.main()
