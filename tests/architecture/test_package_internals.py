"""패키지 안쪽 방향 — 등급표가 디렉터리와 맞는지, 엣지가 등급을 내려가는지."""

from __future__ import annotations

import os
import unittest

from architecture.astscan import _iter_packages, _package_children, _package_edges
from architecture.layers import SRC
from architecture.packages import (
    _FACADE,
    _PACKAGE_TIER_RANK,
    _PACKAGE_TIER_TITLE,
    PACKAGE_TIERS,
    PACKAGES_GOVERNED_ELSEWHERE,
    PACKAGES_WITHOUT_TIERS,
)


class TestPackageInternals(unittest.TestCase):
    """최상위 이름 안쪽 — 패키지가 커져도 그 안의 방향이 규칙으로 남는지."""

    def test_every_package_with_internal_edges_has_a_tier_table(self):
        """안쪽 결합이 있는 패키지는 등급표를 갖는다 — 빠뜨리려면 이유를 적어야 한다.

        문턱을 엣지 1건으로 잡는다. 크기가 아니라 결합의 유무가 기준인 이유는, 지금 자식끼리
        아무것도 안 부르는 패키지는 잴 것이 없고 첫 결합이 생기는 순간 이 시험이 그 이름을
        대며 표를 요구하기 때문이다. 그래서 새 패키지가 규칙 없이 자라는 경로가 없다."""
        problems: list[str] = []
        packages = {".".join(pkg): pkg for pkg in _iter_packages()}
        for dotted, pkg in sorted(packages.items()):
            if dotted in PACKAGE_TIERS or dotted in PACKAGES_GOVERNED_ELSEWHERE:
                continue
            edges = list(_package_edges(pkg))
            if not edges:
                continue
            if dotted in PACKAGES_WITHOUT_TIERS:
                continue  # 이유가 비었는지는 아래에서 따로 본다
            sample = ", ".join(f"{src}→{dst}" for _rel, _lineno, src, dst in edges[:4])
            problems.append(f"{dotted} — 안쪽 엣지 {len(edges)}건({sample}) 인데 등급표가 없다")
        for dotted in sorted(set(PACKAGE_TIERS) | set(PACKAGES_GOVERNED_ELSEWHERE) | set(PACKAGES_WITHOUT_TIERS)):
            if dotted not in packages:
                problems.append(f"{dotted} — 없는 패키지를 가리키는 표가 남아 있다")
        for dotted, reason in sorted(PACKAGES_WITHOUT_TIERS.items()):
            if not reason.strip():
                problems.append(f"{dotted} — 규칙 밖에 두는 이유가 비어 있다")
        self.assertFalse(
            problems,
            "패키지 안쪽이 규칙 밖에 있다 — PACKAGE_TIERS 에 등급을 세우거나 "
            "PACKAGES_WITHOUT_TIERS 에 이유를 적어라:\n" + "\n".join(problems),
        )

    def test_tier_tables_match_the_package_directory(self):
        """표와 디렉터리가 어긋나면 안 된다 — 새 모듈은 자리를 얻고 들어온다.

        미배치는 '이게 무엇 위에 서는가'를 아무도 안 정했다는 뜻이고, 남은 이름은 표가 옛
        디렉터리를 서술한다는 뜻이다. 둘 다 표를 기록으로 전락시킨다."""
        problems: list[str] = []
        for dotted, tiers in sorted(PACKAGE_TIERS.items()):
            pkg = tuple(dotted.split("."))
            if not os.path.isdir(os.path.join(SRC, *pkg)):
                continue  # 사라진 패키지를 가리키는 표는 위 시험이 이름을 대며 잡는다
            actual = _package_children(pkg)
            placed = [name for _title, names in tiers for name in names]
            missing = sorted(actual - set(placed))
            stray = sorted(set(placed) - actual)
            twice = sorted({name for name in placed if placed.count(name) > 1})
            if missing:
                problems.append(f"{dotted} — 등급 미지정: {missing}")
            if stray:
                problems.append(f"{dotted} — 패키지에 없는 이름이 등급표에: {stray}")
            if twice:
                problems.append(f"{dotted} — 등급이 둘: {twice}")
            if _PACKAGE_TIER_RANK[dotted].get(_FACADE) != len(tiers) - 1:
                problems.append(f"{dotted} — 파사드({_FACADE})는 맨 위 등급이어야 한다")
        self.assertFalse(problems, "등급표가 패키지 디렉터리와 어긋난다:\n" + "\n".join(problems))

    def test_package_internals_go_down_a_tier(self):
        """패키지 안에서도 아래 등급만 부른다 — 같은 등급끼리도 안 된다.

        계층·SUBTIERS 와 같은 부등호다. 같은 등급을 막는 이유도 같다: 새 결합이 표를 안 고치고
        생길 수 있으면 표는 계약이 아니라 기록이 된다. 필요한 결합이면 등급을 올리고 왜
        올렸는지를 그 줄에 적으면 된다."""
        violations: list[str] = []
        for dotted in sorted(PACKAGE_TIERS):
            pkg = tuple(dotted.split("."))
            if not os.path.isdir(os.path.join(SRC, *pkg)):
                continue  # 사라진 패키지는 test_every_package_with_internal_edges_has_a_tier_table 몫
            rank, title = _PACKAGE_TIER_RANK[dotted], _PACKAGE_TIER_TITLE[dotted]
            for rel, lineno, src, dst in _package_edges(pkg):
                src_tier, dst_tier = rank.get(src), rank.get(dst)
                if src_tier is None or dst_tier is None:
                    continue  # 등급 미지정은 test_tier_tables_match_the_package_directory 가 잡는다
                if dst_tier < src_tier:
                    continue
                why = "같은 등급" if dst_tier == src_tier else "등급을 거슬러 오른다"
                violations.append(f"{rel}:{lineno} — {src}[{title[src]}] → {dst}[{title[dst]}] ({why})")
        self.assertFalse(
            violations,
            "패키지 안쪽 등급 위반 — PACKAGE_TIERS 를 고치고 왜 올렸는지 그 줄에 적어라:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
