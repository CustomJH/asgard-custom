#!/usr/bin/env python3
"""맵 화면 — 배송 계약과 색의 단일 출처.

프런트엔드 하네스가 없으므로 여기서 재는 것은 브라우저 동작이 아니라 **파일이 지켜야 하는
약속** 넷이다.

  (a) 창이 선언한 세 자산(`js/map.js`·`js/map-draw.js`·`ui/map.css`)이 실제로 서버에서 나온다
  (b) `studio.html` 이 부르는 이름 `initMapView` 가 전역에 실제로 선다
  (c) 두 `.js` 가 각각 1000줄 미만이다 — `health.py` 의 `severe_files` 가 1000줄에서 하드 블록이다
  (d) 색 리터럴이 한 개도 없다

(d)가 이 화면의 회귀선이다. 옛 창(`assets/map_view.html`)은 팔레트 일부만 토큰에서 읽고 종류
색 열셋은 16진수로 박아 뒀다. 다크 전용 창일 때는 그래도 맞았지만 라이트 테마가 생긴 지금
그 열셋은 흰 바탕에 다크용 색으로 남아 **DOM 만 라이트가 되고 그래프는 어두운 채** 뜬다.
그래서 색은 `ui/map.css` 에서만 태어나고, 캔버스는 그것을 읽는다.

실행: uv run pytest tests/test_studio_map_view.py
"""

from __future__ import annotations

import re
import tempfile
import threading
import unittest
import urllib.request
from importlib.resources import files

from asgard.commands.studio import server

_ASSETS = files("asgard") / "assets"

# 16진수 색 — `#abc`·`#abcd`·`#aabbcc`·`#aabbccdd`. 앞뒤 경계를 막아 `#map-view` 같은
# 선택자나 id 문자열을 잡지 않는다(`#abc-def` 도 색이 아니라 이름이다).
_HEX = re.compile(r"(?<![\w-])#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![\w-])")
_RGB = re.compile(r"\brgba?\(")

_SURFACE = ("js/map.js", "js/map-draw.js", "ui/map.css")


def _read(rel: str) -> str:
    return (_ASSETS / rel).read_text(encoding="utf-8")


class DeliveryTest(unittest.TestCase):
    """창이 `<script src>`·`<link href>` 로 적은 주소가 실제로 답하는가."""

    def test_the_three_files_exist_on_disk(self):
        for rel in _SURFACE:
            self.assertTrue((_ASSETS / rel).is_file(), f"자산이 없어요: {rel}")

    def test_the_window_can_fetch_them_over_http(self):
        want = {
            "/asset/js/map.js": "text/javascript; charset=utf-8",
            "/asset/js/map-draw.js": "text/javascript; charset=utf-8",
            "/asset/ui/map.css": "text/css; charset=utf-8",
        }
        with tempfile.TemporaryDirectory() as root:
            httpd = server._bind("127.0.0.1", 0, root)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            port = httpd.server_address[1]
            try:
                for path, ctype in want.items():
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                        self.assertEqual(response.status, 200, path)
                        self.assertEqual(response.headers["Content-Type"], ctype, path)
                        self.assertTrue(response.read(), f"빈 몸통: {path}")
            finally:
                httpd.shutdown()


class EntryPointTest(unittest.TestCase):
    """`studio.html` 은 화면에 들어갈 때 `initMapView()` 를 부른다 — 그 이름이 전역에 서는가."""

    def test_init_map_view_is_assigned_on_the_global_object(self):
        source = _read("js/map.js")
        self.assertRegex(source, r"\b(?:global|window|globalThis)\.initMapView\s*=")

    def test_the_view_is_built_into_the_section_the_shell_owns(self):
        """판은 `studio.html` 소유다 — 화면은 그 안에 짓고, 밖으로 나가지 않는다."""
        self.assertIn('getElementById("map-view")', _read("js/map.js"))

    def test_the_drawing_half_is_reachable_from_the_data_half(self):
        self.assertIn("AsgardMapDraw", _read("js/map-draw.js"))
        self.assertIn("AsgardMapDraw", _read("js/map.js"))


class SizeGateTest(unittest.TestCase):
    """`health.py` 의 `severe_files` 는 1000줄에서 하드 블록이다 — 옮겨 온 스크립트가 1,040줄이었다."""

    def test_each_script_stays_under_a_thousand_lines(self):
        for rel in ("js/map.js", "js/map-draw.js"):
            lines = len(_read(rel).splitlines())
            self.assertLess(lines, 1000, f"{rel} 이 {lines}줄이에요 — 크기 게이트가 막아요")


class ColorSourceTest(unittest.TestCase):
    """색이 태어나는 자리는 하나뿐이어야 한다."""

    def test_no_colour_literal_survives_anywhere_on_this_surface(self):
        for rel in _SURFACE:
            source = _read(rel)
            self.assertEqual(_HEX.findall(source), [], f"{rel} 에 16진수 색이 남아 있어요")
            self.assertEqual(_RGB.findall(source), [], f"{rel} 에 rgb 색이 남아 있어요")

    def test_every_node_kind_the_canvas_draws_has_a_token(self):
        """종류를 하나 늘리고 색을 안 만들면 그 노드만 색 없이 뜬다 — 조용한 결함이다."""
        draw = _read("js/map-draw.js")
        block = re.search(r"const KIND_ORDER = \[(.*?)\];", draw, re.S)
        assert block is not None, "KIND_ORDER 를 못 찾았어요"
        kinds = re.findall(r'"([a-z_]+)"', block.group(1))
        self.assertIn("route", kinds)
        css = _read("ui/map.css")
        for kind in kinds + ["unknown"]:
            name = "--map-kind-" + kind.replace("_", "-")
            self.assertIn(name + ":", css, f"{kind} 의 색 토큰이 없어요")

    def test_the_canvas_reads_those_tokens_instead_of_carrying_a_copy(self):
        draw = _read("js/map-draw.js")
        self.assertIn("getComputedStyle", draw)
        self.assertIn('"--map-kind-"', draw)

    def test_the_kind_palette_is_retuned_per_theme(self):
        """라이트와 다크가 같은 명도로 그리면 한쪽에서 점이 바탕에 잠긴다."""
        css = _read("ui/map.css")
        self.assertGreaterEqual(css.count("--map-kind-l:"), 2)
        self.assertIn('[data-theme="dark"]', css)


class StateTest(unittest.TestCase):
    """네트워크를 타면서 생긴 상태들 — 옛 창은 로컬 스냅샷이라 하나도 없었다."""

    def test_the_unscanned_root_is_handled_as_a_state_not_a_failure(self):
        source = _read("js/map.js")
        self.assertIn("map_unscanned", source)
        # 처방(`asgard map scan`)은 창구가 내려 준다 — 화면은 그것을 지어내지 않고 옮긴다.
        self.assertIn("remedy", source)

    def test_all_four_states_are_drawn(self):
        source = _read("js/map.js")
        for kind in ("loading", "empty", "unscanned", "error"):
            self.assertIn(f'"{kind}"', source, f"{kind} 상태가 없어요")
        self.assertIn(".map-state", _read("ui/map.css"))

    def test_the_root_picker_says_why_each_row_is_there(self):
        """`source` 를 안 보여 주면 목록이 그냥 경로 뭉치가 된다."""
        source = _read("js/map.js")
        for origin in ("session", "workspace", "declared"):
            self.assertIn(f"{origin}:", source)
        self.assertIn("/api/map/roots", source)
        self.assertIn("/api/map/graph", source)


class ThemeAndMotionTest(unittest.TestCase):
    """토큰만 바꾸고 재그리기를 안 붙이면 DOM 만 라이트가 되고 그림은 그대로 남는다."""

    def test_a_theme_change_repaints_the_canvas(self):
        source = _read("js/map.js")
        self.assertIn("MutationObserver", source)
        self.assertIn('"data-theme"', source)
        self.assertIn("refreshPalette", source)

    def test_the_canvas_follows_the_device_pixel_ratio(self):
        self.assertIn("devicePixelRatio", _read("js/map-draw.js"))

    def test_reduced_motion_turns_the_simulation_off(self):
        draw = _read("js/map-draw.js")
        self.assertIn("prefers-reduced-motion", draw)
        # 애니메이션 프레임을 도는 조건 자체에 걸려 있어야 한다 — 전환만 끄면 물리는 계속 돈다.
        self.assertRegex(draw, r"ambient = \(\) =>.*reduced\(\)")

    def test_the_canvas_keeps_a_readable_alternative(self):
        """캔버스는 스크린리더에 아무것도 아니다 — 같은 노드를 목록으로도 둔다."""
        source = _read("js/map.js")
        self.assertIn('data-map="node"', source)
        self.assertIn("노드 선택", source)


if __name__ == "__main__":
    unittest.main()
