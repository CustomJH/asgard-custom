"""휠에 자산이 실리는가 — 소스 트리에서는 절대 안 보이는 실패를 잡는다.

`[tool.hatch.build.targets.wheel].artifacts` 는 **명시 목록**이다. 기본 포함은 `.py` 뿐이라,
새 자산 디렉터리를 만들고 목록에 안 적으면 이런 일이 벌어진다: 저장소에서 돌리는 시험은
파일이 디스크에 있으니 전부 통과하고, `pip install asgard` 로 깔린 것만 404 를 낸다. 아무도
못 보는 종류의 고장이라 여기서 못박는다.

실행: uv run pytest tests/test_packaging_assets.py
"""

from __future__ import annotations

import fnmatch
import os
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "src", "asgard", "assets")

# 창이 HTTP 로 내주는 갈래. `commands/studio/assets.py:_PREFIXES` 와 같은 목록이어야 한다 —
# 내줄 수 있는데 안 실리면 설치본에서만 깨지고, 실리는데 못 내주면 죽은 무게다.
SERVED = ("ui", "js", "vendor")


def _artifacts() -> list[str]:
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
        data = tomllib.load(handle)
    return list(data["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"])


def _covered(rel: str, patterns: list[str]) -> bool:
    """hatch 의 glob 은 `**` 를 경로 구분자 너머로 넓힌다 — fnmatch 는 안 그래서 풀어 준다."""
    for pattern in patterns:
        if fnmatch.fnmatch(rel, pattern):
            return True
        if pattern.endswith("/**") and rel.startswith(pattern[:-2]):
            return True
    return False


class ArtifactCoverageTest(unittest.TestCase):
    def test_every_served_directory_is_declared(self):
        """`/asset/...` 로 나갈 수 있는 갈래는 전부 휠 목록에 있어야 한다."""
        patterns = _artifacts()
        for name in SERVED:
            probe = f"src/asgard/assets/{name}/probe.css"
            self.assertTrue(
                _covered(probe, patterns),
                f"assets/{name}/ 가 휠 artifacts 에 없어요 — 설치본에서만 404 가 납니다",
            )

    def test_the_served_prefixes_match_the_route(self):
        """경로가 내주는 갈래와 휠이 싣는 갈래가 갈라지면, 갈라진 쪽이 조용히 죽는다."""
        from asgard.commands.studio import assets

        self.assertEqual(tuple(p.rstrip("/") for p in assets._PREFIXES), SERVED)

    def test_every_file_on_disk_under_those_directories_is_covered(self):
        """실제로 놓인 파일 하나하나가 실리는가 — 목록이 맞아도 확장자가 빠질 수 있다."""
        patterns = _artifacts()
        missed = []
        for name in SERVED:
            base = os.path.join(ASSETS, name)
            if not os.path.isdir(base):
                continue
            for dirpath, _, filenames in os.walk(base):
                for filename in filenames:
                    full = os.path.join(dirpath, filename)
                    rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                    if not _covered(rel, patterns):
                        missed.append(rel)
        self.assertEqual(missed, [], "휠에 안 실리는 자산이 있어요")

    def test_source_maps_are_not_shipped(self):
        """벤더링 `.map` 은 1.1MB 인데 사용자에게 쓸모가 없다 — 배송 무게만 는다."""
        shipped = []
        for name in SERVED:
            base = os.path.join(ASSETS, name)
            if not os.path.isdir(base):
                continue
            for dirpath, _, filenames in os.walk(base):
                shipped += [f for f in filenames if f.endswith(".map")]
        self.assertEqual(shipped, [])


if __name__ == "__main__":
    unittest.main()
