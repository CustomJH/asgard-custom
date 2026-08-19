"""기억 화면의 배송 계약 — 창이 읽는 다섯 파일이 실제로 나가는가, 그리고 색이 새지 않는가.

이 화면은 자기 서버로 뜨던 창(`assets/memory_dashboard.html`, 3,094행)을 스튜디오의 한 판으로
옮긴 것이다. 옮기면서 두 가지가 깨지기 쉬워졌고, 이 파일이 그 둘을 잠근다.

**색.** 옛 창은 캔버스에 색을 직접 적었다 — `ctx.strokeStyle = "rgba(230,208,150,0.03)"` 류로
그리기 줄에만 열다섯, 종류·작업 팔레트와 인라인 SVG 까지 세면 스크립트 전체에 스물여덟이다.
캔버스는 CSS 를 못 읽으므로 라이트 테마가 생긴 뒤에도 그 값들만 밤 색으로 남아, 화면은 밝은데
성좌만 검게 남는 화면이 나왔다. 그래서 여기서는 세 스크립트에 16진수·`rgb()` 리터럴이
**하나도** 없어야 한다고 못 박는다(`--mem-*` 토큰을 `getComputedStyle` 로 읽는 길만 남긴다).
이것이 이 파일의 중심 회귀선이다.

**크기.** 옛 스크립트는 2,172행 한 덩이였고 `health.py` 의 크기 게이트는 1000행을 하드 블록으로
잡는다. 셋으로 나눈 뒤에도 각각이 그 밑인지 매번 본다 — 한 파일이 다시 자라면 게이트가 막기
전에 여기가 먼저 말한다.

실행: uv run pytest tests/test_studio_memory_ui.py
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import unittest
import urllib.request

from asgard.commands.studio import server

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "asgard", "assets")
_SCRIPTS = ("memory.js", "memory-search.js", "memory-log.js")

# 16진수 색과 `rgb()`/`rgba()` — 어느 쪽이든 값이 스크립트에 박혔다는 뜻이다.
# `oklch()`·`color-mix()`·`var()` 는 CSS 가 계산하므로 여기 걸리지 않는다.
_COLOR_LITERAL = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b|\brgba?\s*\(")

# 다섯 창구 — 옛 창의 `/api/snapshot` 류가 스튜디오에서 받는 이름.
_DOORS = ("snapshot", "injection", "search", "page", "log")


def _read(name: str) -> str:
    sub = "ui" if name.endswith(".css") else "js"
    with open(os.path.join(_ASSETS, sub, name), encoding="utf-8") as handle:
        return handle.read()


def _sources() -> dict[str, str]:
    return {name: _read(name) for name in _SCRIPTS}


class ServedSurfaceTest(unittest.TestCase):
    """실제 서버를 띄워 — 창이 `<script src>` 로 거는 주소가 정말 답하는가.

    판이 비어 보이는 사고의 절반은 파일이 404 인 것이다. 스크립트 태그는 조용히 실패한다."""

    def _serve(self):
        with tempfile.TemporaryDirectory() as root:
            httpd = server._bind("127.0.0.1", 0, root)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                yield httpd.server_address[1]
            finally:
                httpd.shutdown()

    def test_the_five_files_the_window_asks_for_are_delivered(self):
        cases = (
            ("/asset/js/memory.js", "text/javascript; charset=utf-8", "initMemoryView"),
            ("/asset/js/memory-search.js", "text/javascript; charset=utf-8", "MEM.panels.library"),
            ("/asset/js/memory-log.js", "text/javascript; charset=utf-8", "MEM.panels.chronicle"),
            ("/asset/ui/memory.css", "text/css; charset=utf-8", "--mem-kind-note"),
        )
        for port in self._serve():
            for path, ctype, needle in cases:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                    body = response.read().decode("utf-8")
                self.assertEqual(response.status, 200, path)
                self.assertEqual(response.headers["Content-Type"], ctype, path)
                self.assertIn(needle, body, path)


class EntryPointTest(unittest.TestCase):
    """스튜디오가 판에 들어올 때 부르는 이름 — `studio.html` 의 `PANE_INIT` 이 이것을 찾는다."""

    def test_memory_js_defines_the_global_the_shell_calls(self):
        self.assertIn("window.initMemoryView = initMemoryView;", _read("memory.js"))

    def test_the_other_two_register_their_panels_instead_of_a_second_entry_point(self):
        """문이 둘이면 어느 쪽이 판을 짓는지가 순서에 달린다 — 나머지 둘은 등록만 한다."""
        for name in ("memory-search.js", "memory-log.js"):
            source = _read(name)
            self.assertNotIn("window.initMemoryView", source, name)
            self.assertIn("MEM.panels", source, name)

    def test_every_tab_the_shell_lists_has_a_panel_behind_it(self):
        """탭은 있는데 그리는 코드가 없으면 빈 판이 열린다."""
        shell = _read("memory.js")
        registered = set()
        for name in ("memory-search.js", "memory-log.js"):
            registered |= set(re.findall(r"MEM\.panels\.(\w+)\s*=", _read(name)))
        for tab in re.findall(r'\["(\w+)", "[^"]+"\]', shell):
            if tab == "graph":
                continue  # 성좌는 memory.js 가 직접 그린다
            self.assertIn(tab, registered, f"{tab} 탭을 그리는 판이 등록되지 않았어요")

    def test_every_id_the_code_writes_to_exists_in_the_markup(self):
        """판을 짓는 글과 채우는 글이 갈라지면 `getElementById` 가 null 을 주고 그 칸만 조용히 빈다.

        브라우저가 없어도 잡히는 배선 오류다 — 이름 하나가 어긋난 것을 사람이 눈으로 찾을 일이 아니다."""
        joined = "\n".join(_sources().values())
        declared = set(re.findall(r'id="([a-z0-9-]+)"', joined))
        declared.add("memory-body")  # 스튜디오 껍데기가 소유한 자리 — 여기서는 되짚어 찾기만 한다
        touched = set(re.findall(r'[$q]\("([a-z0-9-]+)"\)', joined))
        touched |= set(re.findall(r'querySelector(?:All)?\("#([a-z0-9-]+)', joined))
        self.assertGreater(len(touched), 40, "검사가 헛돌고 있어요 — 만지는 id 를 거의 못 찾았어요")
        self.assertEqual(sorted(t for t in touched if t not in declared), [])


class FileSizeTest(unittest.TestCase):
    """`health.py` 의 크기 게이트는 1000행에서 하드 블록이다 — 옛 스크립트는 2,172행이었다."""

    def test_each_script_stays_under_the_size_gate(self):
        from asgard import health

        self.assertEqual(health.FILE_LINES_SEVERE, 1000, "게이트 값이 바뀌면 이 시험의 근거도 바뀐다")
        for name, source in _sources().items():
            lines = source.count("\n")
            self.assertLess(lines, health.FILE_LINES_SEVERE, f"{name} 이 {lines}행 — 크기 게이트가 막는다")


class ColorLiteralTest(unittest.TestCase):
    """이 단위의 중심 회귀선 — 캔버스가 자기 색을 갖고 있으면 테마가 그것만 못 바꾼다."""

    def test_no_script_writes_a_colour_value(self):
        for name, source in _sources().items():
            hits = [
                f"{i}: {line.strip()}" for i, line in enumerate(source.splitlines(), 1) if _COLOR_LITERAL.search(line)
            ]
            self.assertEqual(hits, [], f"{name} 에 색 값이 박혔어요:\n" + "\n".join(hits))

    def test_the_stylesheet_owns_the_values_instead(self):
        """색이 스크립트에 없다면 어딘가에는 있어야 한다 — 그 자리는 스타일시트 한 곳이다."""
        css = _read("memory.css")
        self.assertIn("--mem-kind-l", css)
        self.assertIn('[data-theme="dark"] .mem', css, "다크에서 종류 색을 올리는 자리가 없어요")
        self.assertIn("prefers-color-scheme: dark", css, "고른 적 없는 사용자의 다크가 빠졌어요")

    def test_every_token_the_canvas_reads_is_declared(self):
        """이름이 어긋나면 `getPropertyValue` 가 빈 문자열을 주고 캔버스가 조용히 검게 남는다."""
        css = _read("memory.css")
        read_names = set(re.findall(r'v\("(--mem-[a-z-]+)"\)', _read("memory.js")))
        # 종류 토큰은 `v("--mem-kind-" + k)` 로 이어 붙여 읽으므로 이름 목록에서 따로 모은다.
        kinds = re.findall(r"(\w+):\"(?:circle|tri|diamond|hexagon|rect|tridown)\"", _read("memory.js"))
        self.assertEqual(len(kinds), 6, f"종류가 여섯이 아니에요: {kinds}")
        read_names |= {"--mem-kind-" + k for k in kinds}
        self.assertGreater(len(read_names), 12, "캔버스가 읽는 토큰을 거의 못 찾았어요 — 검사가 헛돌고 있어요")
        for name in sorted(read_names):
            self.assertIn(f"{name}:", css, f"{name} 을 스타일시트가 선언하지 않았어요")


class ThemeRepaintTest(unittest.TestCase):
    """캔버스는 CSS 를 따라가지 않는다 — 테마가 바뀌면 누군가 다시 그려야 한다."""

    def test_a_theme_change_clears_the_cache_and_redraws(self):
        source = _read("memory.js")
        self.assertIn("MutationObserver", source)
        self.assertIn('attributeFilter: ["data-theme"]', source)
        self.assertIn("prefers-color-scheme: dark", source, "고른 적 없는 사용자의 테마 전환이 빠졌어요")
        repaint = re.search(r"const repaint = \(\) => \{([^}]*)\}", source)
        assert repaint is not None, "repaint 를 못 찾았어요"
        body = repaint.group(1)
        self.assertIn("PAINT = null", body, "물감 캐시를 안 버리면 옛 색으로 다시 그린다")
        self.assertIn("renderGraph()", body)

    def test_the_palette_is_read_from_the_scoped_element(self):
        """토큰은 `.mem` 에 걸려 있다 — 문서 뿌리에서 읽으면 빈 문자열이 온다."""
        self.assertIn("getComputedStyle(G.canvas", _read("memory.js"))


class ApiSurfaceTest(unittest.TestCase):
    """다섯 창구 — 옮기면서 하나라도 빠지면 그 탭만 조용히 빈다."""

    def test_all_five_doors_are_called(self):
        joined = "\n".join(_sources().values())
        for door in _DOORS:
            self.assertIn(f'api("{door}"', joined, f"{door} 창구를 아무도 부르지 않아요")

    def test_nothing_reaches_outside_the_memory_prefix(self):
        """이 판이 다른 화면의 창구를 부르기 시작하면 소유가 흐려진다."""
        for name, source in _sources().items():
            for path in re.findall(r'"(/api/[^"]*)"', source):
                self.assertTrue(path.startswith("/api/memory/"), f"{name} 이 {path} 를 부른다")

    def test_the_surface_stays_read_only(self):
        """읽기 전용 관측 창이다 — 쓰기 메서드가 생기면 계약이 바뀐 것이다."""
        joined = "\n".join(_sources().values())
        for verb in ('method: "POST"', 'method: "PUT"', 'method: "DELETE"', 'method: "PATCH"'):
            self.assertNotIn(verb, joined)


class StateCoverageTest(unittest.TestCase):
    """상태 넷 — 로딩 · 빈 서고 · 오류 · 결과 없음. 옛 창이 갖고 있던 수준을 지킨다."""

    def test_the_four_states_exist_in_the_shell(self):
        source = _read("memory.js")
        for name in ("const skeleton", "const empty", "const onboard", "const errorCard"):
            self.assertIn(name, source, f"{name} 이 없어요")

    def test_the_error_card_offers_a_way_back(self):
        """막다른 오류는 새로고침밖에 길이 없다 — 다시 시도가 화면 안에 있어야 한다."""
        source = _read("memory.js")
        self.assertIn('data-mem="retry"', source)
        self.assertIn('role="alert"', source)

    def test_the_canvas_has_a_text_alternative(self):
        """캔버스는 스크린리더에 안 읽힌다 — 같은 자료가 목록으로도 있어야 한다."""
        source = _read("memory.js")
        self.assertIn("renderAltList", source)
        self.assertIn('id="mem-galt"', source)
        self.assertIn('role="status"', source, "선택 결과를 읽어 주는 자리가 없어요")


if __name__ == "__main__":
    unittest.main()
