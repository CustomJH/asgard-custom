#!/usr/bin/env python3
"""종류 어휘 대조 — 그리는 표면 넷이 `evidence.node_kinds()` 와 같은 집합을 아는지.

`assertIn("service", html)` 로는 이 회귀를 못 잡는다. 어긋남은 낱말이 문서에 있고 없고가
아니라 목록에 자리가 있고 없고라서, 목록을 실제로 읽어 비교해야 보인다. 그래서 이 시험은
자산 파일에서 리터럴을 뽑아 파이썬 정본과 집합으로 맞춘다.

실행: uv run pytest tests/map_graph/test_kind_vocabulary.py
"""

import re
import unittest
from importlib.resources import files

from map_graph.map_base import Base


def _asset(*parts: str) -> str:
    target = files("asgard") / "assets"
    for part in parts:
        target = target / part
    return target.read_text(encoding="utf-8")


def _block(source: str, opener: str, closer: str) -> str:
    """`opener` 부터 그 뒤 첫 `closer` 까지 — 리터럴 하나를 통째로 떼어 낸다."""
    start = source.index(opener)
    end = source.index(closer, start)
    return source[start : end + len(closer)]


def _quoted(text: str) -> set[str]:
    return set(re.findall(r'"([^"]+)"', text))


def _lane_kinds(block: str) -> set[str]:
    kinds: set[str] = set()
    for group in re.findall(r"kinds\s*:\s*\[([^\]]*)\]", block):
        kinds |= _quoted(group)
    return kinds


def _lane_filter(source: str) -> str:
    """`laneLayout` 이 무엇을 배치 대상으로 고르는지 — 함수 첫 줄."""
    match = re.search(r"function laneLayout\(\)\s*\{\s*\n([^\n]*)", source)
    assert match, "laneLayout 이 사라졌다"
    return match.group(1)


class TestKindVocabulary(Base):
    def setUp(self) -> None:
        super().setUp()
        from asgard.map_graph.evidence import EVIDENCE_KINDS, FILE_KIND, node_kinds

        self.evidence_kinds = set(EVIDENCE_KINDS)
        self.kinds = node_kinds()
        self.file_kind = FILE_KIND

    def test_node_kinds_is_every_evidence_kind_plus_file(self):
        """정본의 정의 — 표시 순서 표에 이름이 빠져도 종류가 사라지지 않는다."""
        self.assertEqual(set(self.kinds), self.evidence_kinds | {self.file_kind})
        self.assertEqual(len(self.kinds), len(set(self.kinds)))
        self.assertEqual(self.kinds[0], "route")
        self.assertEqual(self.kinds[-1], self.file_kind)

    def test_display_order_table_does_not_decide_the_set(self):
        """순서 표에 없는 종류는 사라지지 않고 뒤에 붙는다."""
        from asgard.map_graph import evidence

        original = evidence.EVIDENCE_KINDS
        try:
            evidence.EVIDENCE_KINDS = (*original, "zzz_unlisted")
            widened = evidence.node_kinds()
        finally:
            evidence.EVIDENCE_KINDS = original
        self.assertIn("zzz_unlisted", widened)
        self.assertEqual(widened[-1], "zzz_unlisted")

    def test_payload_carries_the_vocabulary(self):
        """자료에 `kinds` 가 실려야 그리는 쪽이 목록을 소유하지 않는다."""
        from asgard.map_graph import graph_payload, graph_state, scan_graph

        self.seed()
        scan_graph(self.root)
        state = graph_state(self.root)
        self.assertIsNotNone(state, "스캔 직후인데 그래프 상태가 없다")
        payload = graph_payload(self.root, state or {})
        self.assertEqual(payload["kinds"], list(self.kinds))

    def test_standalone_view_knows_every_kind(self):
        """`asgard open map` 이 여는 단일 HTML — 색·폴백 목록·레인 셋 다."""
        html = _asset("map_view.html")
        colors = set(re.findall(r"(\w+)\s*:\s*\"#", _block(html, "const KIND_COLORS = {", "};")))
        self.assertEqual(set(self.kinds) - colors, set(), "팔레트에 자리가 없는 종류")
        fallback = _quoted(_block(html, "const KIND_ORDER = ", ";"))
        self.assertEqual(set(self.kinds) - fallback, set(), "폴백 목록에 없는 종류")
        lanes = _lane_kinds(_block(html, "const LANES=[", "];"))
        self.assertEqual(set(self.kinds) - lanes, set(), "레인 표에 자리가 없는 종류")

    def test_studio_renderer_knows_every_kind(self):
        """스튜디오 창의 지도 화면 — 같은 어휘를 그리는 쪽과 색 쪽이 나눠 안다."""
        script = _asset("js", "map-draw.js")
        fallback = _quoted(_block(script, "const KIND_ORDER = [", "];"))
        self.assertEqual(set(self.kinds) - fallback, set(), "폴백 목록에 없는 종류")
        lanes = _lane_kinds(_block(script, "const LANES = [", "];"))
        self.assertEqual(set(self.kinds) - lanes, set(), "레인 표에 자리가 없는 종류")
        tokens = set(re.findall(r"--map-kind-([a-z-]+)\s*:", _asset("ui", "map.css")))
        missing = {kind for kind in self.kinds if kind.replace("_", "-") not in tokens}
        self.assertEqual(missing, set(), "색 토큰이 없는 종류 — 무채색으로 떨어진다")

    def test_lane_mode_draws_the_same_nodes_as_the_constellation(self):
        """레인이 성좌와 다른 집합을 그리지 않는다.

        전에는 모드 전환이 `active.delete("file")` 로 파일 종류를 강제로 껐고, 레인 배치가
        `n.kind !== "file"` 로 한 번 더 걸렀다. 두 자리가 다 없어져야 보이는 집합이 두 모드에서
        같은 필터(`state()`) 하나로만 정해진다."""
        for source in (_asset("map_view.html"), _asset("js", "map-draw.js")):
            self.assertNotIn('active.delete("file")', "".join(source.split()))
            self.assertNotIn('kind!=="file"', "".join(_lane_filter(source).split()))

    def test_no_surface_treats_one_kind_differently_in_lane_mode(self):
        """종류를 이름으로 집어 레인에서만 다르게 다루는 자리가 없다.

        같은 동작이 배치·필터·범례에 흩어져 있어서, 배치에서 지워도 범례에 남으면 칩이 켜진
        채로 비활성이 된다(스튜디오 창이 그랬다). 그래서 자리를 하나씩 세지 않고 불변식으로
        검사한다 — `laneMode` 를 판단하는 문장에 종류 이름이 같이 오면 안 된다."""
        surfaces = {
            "map_view.html": _asset("map_view.html"),
            "map-draw.js": _asset("js", "map-draw.js"),
            "map.js": _asset("js", "map.js"),
        }
        for name, source in surfaces.items():
            for number, line in enumerate(source.splitlines(), 1):
                if "laneMode" not in line:
                    continue
                named = [kind for kind in self.kinds if f'"{kind}"' in line]
                self.assertEqual(named, [], f"{name}:{number} — 레인 모드가 {named} 를 따로 다룬다")

    def test_a_kind_with_no_lane_is_collected_instead_of_dropped(self):
        """레인 표에 자리가 없는 종류가 생겨도 조용히 빠지지 않고 마지막 칸에 모인다."""
        for source in (_asset("map_view.html"), _asset("js", "map-draw.js")):
            self.assertIn("laneless", source)


if __name__ == "__main__":
    unittest.main()
