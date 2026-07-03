#!/usr/bin/env python3
"""디자인 토큰(theme.py) 자가 검증 — hex 형식, ansi() truecolor/256 분기, x256 근사 정확도.

실행: uv run python test/test_theme.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard import theme  # noqa: E402


class TestTokens(unittest.TestCase):
    def test_all_tokens_are_hex(self):
        for name in ("PRIMARY", "SECONDARY", "BACKGROUND", "SURFACE", "TEXT", "SUBTEXT",
                     "ACCENT_BLUE", "ACCENT_CYAN", "ACCENT_PURPLE",
                     "SUCCESS", "WARNING", "DANGER"):
            v = getattr(theme, name)
            self.assertRegex(v, r"^#[0-9A-Fa-f]{6}$", name)

    def test_gradients_length_match(self):
        self.assertEqual(len(theme.LOGO_GRAD), len(theme.LOGO_GRAD_LIGHT))
        for h in theme.LOGO_GRAD + theme.LOGO_GRAD_LIGHT:
            self.assertRegex(h, r"^#[0-9A-Fa-f]{6}$")


class TestAnsi(unittest.TestCase):
    def test_truecolor(self):
        old = theme._TRUECOLOR
        theme._TRUECOLOR = True
        try:
            self.assertEqual(theme.ansi("#D4AF37"), "38;2;212;175;55")
        finally:
            theme._TRUECOLOR = old

    def test_256_fallback(self):
        old = theme._TRUECOLOR
        theme._TRUECOLOR = False
        try:
            self.assertRegex(theme.ansi("#D4AF37"), r"^38;5;\d{1,3}$")
        finally:
            theme._TRUECOLOR = old

    def test_x256_exact_cube_corners(self):
        self.assertEqual(theme._x256(0, 0, 0), 16)        # 큐브 (0,0,0)
        self.assertEqual(theme._x256(255, 255, 255), 231)  # 큐브 (5,5,5)
        self.assertEqual(theme._x256(95, 135, 175), 16 + 36 * 1 + 6 * 2 + 3)

    def test_x256_gray_prefers_ramp(self):
        code = theme._x256(128, 128, 128)
        self.assertGreaterEqual(code, 232)  # 회색은 그레이 램프로

    def test_x256_gold_lands_on_gold(self):
        # #D4AF37 → 179 (#d7af5f) — 육안 골드 근사
        self.assertEqual(theme._x256(212, 175, 55), 179)


if __name__ == "__main__":
    unittest.main(verbosity=1)
