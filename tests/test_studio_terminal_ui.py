"""터미널 화면의 **배송 계약** — 브라우저에 도착하는 파일과 그 안의 배선을 검사한다.

프런트엔드 하네스가 없으므로 여기서 못박는 것은 "화면이 예쁜가"가 아니라 넷이다.

  1. **닿는가** — 벤더링한 xterm 셋과 `terminal.js` 가 실제로 `/asset/...` 로 나가고,
     내용 종류가 맞는가. 이름만 맞고 안 나가면 창은 빈 판을 그린다.
  2. **테마를 따라오는가** — xterm 은 CSS 변수를 못 읽어 자기 색을 JS 객체로 받는다.
     그래서 `terminal.js` 안에 색을 박아 두면 화면만 라이트가 되고 터미널만 다크로 남는다.
     이 시험이 그 자리를 막는다: 색 리터럴 금지 + `data-theme` 을 보는가.
  3. **이어 받는가** — 스트림이 끊겼다 붙을 때 `after=` 가 없으면 매번 처음부터 다시 그린다.
  4. **게이트를 안 건드리는가** — 최소화된 283KB 를 `vendor/` 밖에 두면 크기·중복 게이트가
     남의 코드를 이 변경의 책임으로 잡는다. 라이선스와 `.map` 도 여기서 같이 본다.

실행: uv run pytest tests/test_studio_terminal_ui.py
"""

from __future__ import annotations

import re
import tempfile
import threading
import unittest
import urllib.request
from importlib.resources import files
from pathlib import Path

from asgard.commands.studio import server

_ASSETS = Path(str(files("asgard") / "assets"))
_VENDOR = _ASSETS / "vendor" / "xterm"
_SCRIPT = _ASSETS / "js" / "terminal.js"
_SHEET = _ASSETS / "ui" / "terminal.css"

# `#abc` · `#aabbcc` · `#aabbccdd` — 셋 다 잡는다. 테마를 따라오지 못하는 색은 전부 이 꼴이다.
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


class VendoredTest(unittest.TestCase):
    """남의 코드를 들여올 때 같이 와야 하는 것들."""

    def test_the_three_files_are_here(self):
        for name in ("xterm.js", "xterm.css", "addon-fit.js"):
            path = _VENDOR / name
            self.assertTrue(path.is_file(), f"없어요: {path}")
            self.assertGreater(path.stat().st_size, 1000, name)

    def test_the_bundle_is_the_real_one(self):
        """토막이 아니라 UMD 번들 통째인가 — 잘려 오면 창에서 `Terminal` 이 없다."""
        head = (_VENDOR / "xterm.js").read_bytes()[:200]
        self.assertIn(b"typeof define", head)
        self.assertIn(b"amd", head)

    def test_the_licences_came_along(self):
        licence = _VENDOR / "LICENSE"
        self.assertTrue(licence.is_file(), "벤더링에는 라이선스 원문이 따라와야 해요")
        text = licence.read_text(encoding="utf-8")
        self.assertIn("xterm.js authors", text)
        # 두 패키지(xterm · addon-fit)를 들여왔으므로 둘 다의 원문이 있어야 한다.
        self.assertGreaterEqual(text.count("Permission is hereby granted"), 2)

    def test_the_source_and_version_are_written_down(self):
        """어디서 몇 판을 받았는지 없으면 다음 사람은 판을 못 올린다."""
        readme = (_VENDOR / "README.md").read_text(encoding="utf-8")
        for mark in ("@xterm/xterm", "@xterm/addon-fit", "5.5.0", "0.10.0"):
            self.assertIn(mark, readme)

    def test_no_source_maps_shipped(self):
        """`.map` 둘이 1.1MB 다 — 배송에 필요 없고 창은 최소화본만 읽는다."""
        self.assertEqual(sorted(p.name for p in _VENDOR.glob("*.map")), [])

    def test_it_sits_where_the_gate_skips(self):
        """디렉터리 이름이 `vendor` 인 것이 크기·중복 게이트 면제의 유일한 근거다."""
        from asgard import health

        self.assertIn("vendor", health.GATE_SKIP_DIRS)
        self.assertIsNotNone(health.borrowed("src/asgard/assets/vendor/xterm/xterm.js"))


class ScriptContractTest(unittest.TestCase):
    """`terminal.js` 원문 — 창이 기대하는 배선이 정말 그 안에 있는가."""

    def setUp(self):
        self.source = _SCRIPT.read_text(encoding="utf-8")

    def test_the_entrance_is_global(self):
        """창은 화면에 들어갈 때 이 이름을 부른다. 모듈 안에만 있으면 아무 일도 안 일어난다."""
        self.assertIn("window.initTerminalView", self.source)

    def test_no_colour_is_written_into_the_script(self):
        """xterm 팔레트는 토큰에서 읽어야 한다 — 박아 두면 테마 전환이 터미널만 비켜 간다."""
        self.assertEqual(_HEX.findall(self.source), [])

    def test_the_palette_reads_semantic_tokens(self):
        """색이 하나도 없다는 것만으로는 모자란다 — 읽어야 할 토큰을 실제로 읽는가."""
        for name in ("--ink", "--surface-1", "--gold", "--danger", "--ok", "--warn", "--info", "--mono"):
            self.assertIn(f'"{name}"', self.source, name)

    def test_it_answers_a_theme_change(self):
        """`data-theme` 이 바뀌는 것을 보고 팔레트를 다시 넣는가."""
        self.assertIn("data-theme", self.source)
        self.assertIn("MutationObserver", self.source)
        self.assertIn("prefers-color-scheme", self.source)

    def test_it_resumes_the_stream_where_it_stopped(self):
        self.assertIn("after=", self.source)
        self.assertIn("lastSeq", self.source)

    def test_the_token_never_rides_in_a_shared_place(self):
        """세션 토큰은 `open` 응답에서만 온다 — 목록 창구는 토큰을 안 낸다."""
        self.assertNotIn("/api/terminal/sessions", self.source)

    def test_size_changes_are_debounced_and_deduplicated(self):
        self.assertIn("ResizeObserver", self.source)
        self.assertIn("/api/terminal/resize", self.source)

    def test_it_stays_under_the_line_gate(self):
        """`.js` 는 health 게이트가 세고 1000줄이 하드 블록이다."""
        self.assertLess(len(self.source.splitlines()), 1000)


class SheetContractTest(unittest.TestCase):
    """`terminal.css` — 읽는 층은 의미 토큰 하나뿐이라는 규칙을 여기서도 지키는가."""

    def setUp(self):
        self.source = _SHEET.read_text(encoding="utf-8")

    def test_no_colour_literal(self):
        self.assertEqual(_HEX.findall(self.source), [])

    def test_no_raw_token(self):
        """`--ak-*` 는 원시 층이다. 컴포넌트가 그것을 읽으면 테마 매핑을 건너뛴다."""
        self.assertEqual(re.findall(r"var\(--ak-[\w-]+", self.source), [])


class ServedTest(unittest.TestCase):
    """실제로 서버를 띄워 — 창이 요청할 주소 그대로 나오는가.

    자산은 패키지 안에서 나가므로 서버 뿌리와 무관하다. 그래서 뿌리는 빈 임시 디렉터리다."""

    def _fetch(self, path: str) -> tuple[int, str, bytes]:
        with tempfile.TemporaryDirectory() as root:
            httpd = server._bind("127.0.0.1", 0, root)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                url = f"http://127.0.0.1:{httpd.server_address[1]}{path}"
                with urllib.request.urlopen(url, timeout=5) as response:
                    return response.status, response.headers["Content-Type"], response.read()
            finally:
                httpd.shutdown()

    def test_every_file_the_page_declares_is_delivered(self):
        cases = (
            ("/asset/vendor/xterm/xterm.js", "text/javascript; charset=utf-8"),
            ("/asset/vendor/xterm/addon-fit.js", "text/javascript; charset=utf-8"),
            ("/asset/vendor/xterm/xterm.css", "text/css; charset=utf-8"),
            ("/asset/js/terminal.js", "text/javascript; charset=utf-8"),
            ("/asset/ui/terminal.css", "text/css; charset=utf-8"),
        )
        for path, ctype in cases:
            status, seen, body = self._fetch(path)
            self.assertEqual(status, 200, path)
            self.assertEqual(seen, ctype, path)
            self.assertGreater(len(body), 0, path)

    def test_the_bundle_arrives_whole(self):
        """잘려 나가면 창에서는 문법 오류 한 줄로만 보인다 — 바이트로 대조한다."""
        _, _, body = self._fetch("/asset/vendor/xterm/xterm.js")
        self.assertEqual(body, (_VENDOR / "xterm.js").read_bytes())


if __name__ == "__main__":
    unittest.main()
