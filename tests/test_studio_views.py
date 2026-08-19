"""스튜디오 셸 계약 — 창이 공용 키트를 입었는가, 그리고 합쳐 들어온 세 판이 실재하는가.

이 저장소에는 브라우저를 띄우는 시험이 없다. 그래서 여기서 재는 것은 렌더된 문서의 **형상**이다:
어떤 파일을 어떤 순서로 걸었는가, 레일 단추와 판이 짝이 맞는가, 색이 studio.css 밖으로 나갔는가.
셋 다 눈으로는 한참 뒤에야 드러나고(라이트에서 검정 위 검정, 단추만 있고 안 열리는 판) 문서에서는
한 줄로 드러난다.

실행: uv run pytest tests/test_studio_views.py
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import unittest
import urllib.request

from asgard.commands.studio import routes, server

_HTML = routes.render_html()
_HEAD = _HTML.split("</head>", 1)[0]
_CSS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src",
    "asgard",
    "assets",
    "ui",
    "studio.css",
)
with open(_CSS_PATH, encoding="utf-8") as _handle:
    _CSS = _handle.read()

# 세 판이 이 단위에서 선언되고 다음 단위들이 채운다.
NEW_VIEWS = ("map", "memory", "terminal")


def _stripped_css() -> str:
    """주석을 뺀 studio.css — 색 리터럴을 셀 때 옛 값을 적어 둔 설명이 걸리면 안 된다."""
    return re.sub(r"/\*.*?\*/", "", _CSS, flags=re.S)


class StylesheetOrderTest(unittest.TestCase):
    """토큰 → 컴포넌트 → 이 창. 순서가 뒤집히면 부품이 자기 값보다 먼저 선다."""

    def test_three_sheets_are_linked_in_order(self):
        order = [
            _HEAD.index('href="/asset/ui/tokens.css"'),
            _HEAD.index('href="/asset/ui/components.css"'),
            _HEAD.index('href="/asset/ui/studio.css"'),
        ]
        self.assertEqual(order, sorted(order))

    def test_the_style_block_is_gone_from_the_page(self):
        """옮겼다는 증거 — 같은 규칙이 두 자리에 있으면 뒤에 오는 쪽이 앞의 것을 덮는다."""
        self.assertNotIn("<style>", _HTML)
        self.assertNotIn("</style>", _HTML)

    def test_the_page_declares_the_sheets_the_next_units_deliver(self):
        for name in NEW_VIEWS:
            self.assertIn(f'href="/asset/ui/{name}.css"', _HEAD)
        self.assertIn('href="/asset/vendor/xterm/xterm.css"', _HEAD)

    def test_the_page_declares_the_scripts_the_next_units_deliver(self):
        for src in (
            "/asset/vendor/xterm/xterm.js",
            "/asset/vendor/xterm/addon-fit.js",
            "/asset/js/map.js",
            "/asset/js/map-draw.js",
            "/asset/js/memory.js",
            "/asset/js/memory-search.js",
            "/asset/js/memory-log.js",
            "/asset/js/terminal.js",
        ):
            self.assertIn(f'src="{src}"', _HEAD, src)


class ThemeTest(unittest.TestCase):
    """라이트가 기본이고, 고른 값이 첫 페인트 전에 선다."""

    def test_the_document_declares_both_schemes(self):
        self.assertIn('<meta name="color-scheme" content="light dark">', _HTML)

    def test_the_saved_theme_is_applied_before_the_first_paint(self):
        """<body> 뒤에서 세우면 라이트로 한 번 칠하고 다크로 덮어서 창이 번쩍인다."""
        self.assertIn("asgard.studio.theme", _HEAD)
        self.assertIn("documentElement.dataset.theme", _HEAD)

    def test_the_settings_screen_offers_the_three_choices(self):
        panel = _HTML.split('id="general-panel"', 1)[1].split("</section>", 1)[0]
        self.assertIn('<select id="theme">', panel)
        for value in ("system", "light", "dark"):
            self.assertIn(f'value="{value}"', panel)

    def test_the_swap_frame_has_its_transitions_cut(self):
        """한 프레임 동안 면마다 제 시간으로 색을 건너가면 두 테마가 겹쳐 보인다."""
        self.assertIn(".theme-swap", _CSS)
        self.assertIn("theme-swap", _HTML)


class ViewRegistryTest(unittest.TestCase):
    """레일 단추와 판은 짝이다 — 한쪽만 있으면 눌러도 안 열리거나, 열 길이 없다."""

    def _views(self) -> list[str]:
        found = re.search(r"const VIEWS=\[(.*?)\]", _HTML, re.S)
        assert found is not None, "VIEWS 배열을 못 찾았어요 — 이름이 바뀌었으면 이 시험도 같이 옮겨야 해요"
        return re.findall(r"'([a-z-]+)'", found.group(1))

    def _panes(self) -> set[str]:
        return set(re.findall(r'<section class="[^"]*" id="([a-z-]+)-view"', _HTML))

    def _rail(self) -> set[str]:
        return set(re.findall(r'data-view="([a-z-]+)"', _HTML))

    def test_the_three_new_views_are_registered(self):
        self.assertLessEqual(set(NEW_VIEWS), set(self._views()))

    def test_every_registered_view_has_a_pane(self):
        self.assertEqual(set(self._views()) - self._panes(), set())

    def test_every_pane_is_registered(self):
        self.assertEqual(self._panes() - set(self._views()), set())

    def test_every_rail_button_has_a_pane(self):
        self.assertEqual(self._rail() - self._panes(), set())

    def test_every_pane_has_a_rail_button(self):
        self.assertEqual(self._panes() - self._rail(), set())

    def test_each_new_pane_carries_a_place_to_say_its_state(self):
        """비어 있어도 자기 상태를 말해야 한다 — 기다리는 중 · 아직 없음 · 못 읽음."""
        for name in NEW_VIEWS:
            pane = _HTML.split(f'id="{name}-view"', 1)[1].split("</section>", 1)[0]
            self.assertIn(f'id="{name}-state"', pane, name)
            self.assertIn('aria-live="polite"', pane, name)
            self.assertIn("ak-skeleton", pane, name)

    def test_a_missing_pane_script_draws_a_notice_instead_of_throwing(self):
        """다음 단위의 파일은 아직 없다 — 없다고 창이 죽으면 이 단위가 아무것도 배송 못 한다."""
        self.assertIn("typeof init!=='function'", _HTML)
        self.assertIn("아직 준비되지 않았어요", _HTML)
        for fn in ("initMapView", "initMemoryView", "initTerminalView"):
            self.assertIn(fn, _HTML, fn)


class StudioCssTest(unittest.TestCase):
    """studio.css 에 남을 것은 이 창의 배치지 색 정의가 아니다."""

    def test_no_hex_colour_is_hardcoded(self):
        found = re.findall(r"#[0-9A-Fa-f]{3,8}\b", _stripped_css())
        self.assertEqual(found, [], f"토큰으로 안 바꾼 색: {found}")

    def test_no_rgb_literal_is_hardcoded(self):
        found = re.findall(r"\brgba?\([^)]*\)", _stripped_css())
        self.assertEqual(found, [], f"토큰으로 안 바꾼 색: {found}")

    def test_it_reads_only_the_semantic_layer(self):
        """`--ak-c-*` 는 원시 층이다. 컴포넌트가 그 층을 읽으면 테마 전환을 안 따라온다."""
        self.assertEqual(re.findall(r"var\(--ak-[a-z]-", _stripped_css()), [])


class ServedSurfaceTest(unittest.TestCase):
    """서버를 띄워 — 걸어 둔 주소로 파일이 실제로 나가는가."""

    def _serve_forever(self, root: str):
        httpd = server._bind("127.0.0.1", 0, root)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd, httpd.server_address[1]

    def test_studio_css_is_delivered(self):
        with tempfile.TemporaryDirectory() as root:
            httpd, port = self._serve_forever(root)
            try:
                url = f"http://127.0.0.1:{port}/asset/ui/studio.css"
                with urllib.request.urlopen(url, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers["Content-Type"], "text/css; charset=utf-8")
                    self.assertIn(b".view-state", response.read())
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
