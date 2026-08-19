"""공용 토큰 키트(`assets/ui/tokens.css` · `components.css`)의 불변식.

이 저장소에는 프런트엔드 시험 하네스가 없다. 그래서 CSS 를 읽어 선언을 뽑고, 색은
coloraide 로 실제 WCAG 2.1 대비를 재서 검사한다 — 이름 대조가 아니라 값 대조다.

세 화면이 같은 한 묶음을 읽게 만든 뒤로, 여기서 막는 회귀는 넷이다.
1. 라이트가 기본이 아니게 되는 것 (색이 `[data-theme]` 이나 미디어 질의 안에서만 태어남).
2. 한쪽 테마에만 있는 토큰이 생기는 것 (덮지 못한 테마는 반대 테마 값을 그대로 쓴다).
3. 글자 대비가 기준 밑으로 내려가는 것.
4. 브랜드 금 `#C6A45E` 가 라이트에서 본문 글자로 돌아오는 것 — 흰 바탕 2.37 이다.
"""

from __future__ import annotations

import re
import unittest
from importlib.resources import files
from pathlib import Path

from coloraide import Color

_UI = Path(str(files("asgard") / "assets" / "ui"))
_TOKENS = (_UI / "tokens.css").read_text(encoding="utf-8")
_COMPONENTS = (_UI / "components.css").read_text(encoding="utf-8")

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
_VAR = re.compile(r"var\(\s*(--[\w-]+)\s*\)")

# studio.html 이 배송하던 값. 다크는 새로 고른 게 아니라 옮겨 온 것이라 이 값들이 그대로
# 남아 있어야 한다. studio.html 자체를 읽지 않는 이유는 그 파일이 다른 단위의 소유라서,
# 거기서 `:root` 가 사라져도 이 시험이 잘못 실패하면 안 되기 때문이다.
_SHIPPED_DARK_HEXES = {
    "#0c0a07",  # --canvas
    "#14110c",  # --surface-1
    "#1b160e",  # --surface-2
    "#241c11",  # --surface-3
    "#100d09",  # --sidebar
    "#c6a45e",  # --gold
    "#e8c87e",  # --gold-lit
    "#e9e0ca",  # --ink
    "#9c9179",  # --muted
    "#1c1710",  # --gold-fill
}

# 본문 크기 글자로 쓰는 토큰 — 캔버스 위에서 4.5:1 (WCAG 2.1 AA).
_BODY_INK = ("--ink", "--muted", "--gold", "--gold-lit", "--ok", "--warn", "--danger", "--info")

# 경계와 큰 글자 — 3.0:1. `--focus` 는 WCAG 2.4.11 이 초점 표시에 요구하는 값이기도 하다.
_BOUNDARY = ("--faint", "--gold-line", "--focus")


def _blocks(css: str) -> dict[str, str]:
    """선택자 → 본문(주석 포함). at-rule 안쪽 규칙은 `바깥 :: 안쪽` 키로 담는다."""
    out: dict[str, str] = {}
    stack: list[tuple[str, int]] = []
    start = 0
    for i, ch in enumerate(css):
        if ch == "{":
            stack.append((_COMMENT.sub("", css[start:i]).strip(), i + 1))
            start = i + 1
        elif ch == "}":
            selector, body_start = stack.pop()
            body = css[body_start:i]
            if "{" not in body:  # at-rule 껍데기가 아니라 선언을 가진 규칙일 때만
                out[" :: ".join([s for s, _ in stack] + [selector])] = body
            start = i + 1
        elif ch == ";" and not stack:
            start = i + 1
    return out


def _decls(body: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in _DECL.finditer(_COMMENT.sub("", body))}


def _root_regions() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """`:root` 를 원시 · 테마별 · 테마 불변 셋으로 가른다. 경계는 파일 안의 구역 주석이다."""
    body = _blocks(_TOKENS)[":root"]
    themed_at = body.index("테마별 의미 토큰")
    constant_at = body.index("테마 불변 토큰")
    return _decls(body[:themed_at]), _decls(body[themed_at:constant_at]), _decls(body[constant_at:])


_PRIMITIVE, _THEMED, _CONSTANT = _root_regions()
_DARK = _decls(_blocks(_TOKENS)[':root[data-theme="dark"]'])
_MIRROR = _decls(_blocks(_TOKENS)['@media (prefers-color-scheme: dark) :: :root:not([data-theme="light"])'])


def _resolve(name: str, theme: dict[str, str]) -> str:
    """의미 토큰을 원시 층까지 따라가 리터럴로 편다."""
    value = theme.get(name) or _THEMED.get(name) or _CONSTANT.get(name) or _PRIMITIVE[name]
    for _ in range(8):
        match = _VAR.search(value)
        if match is None:
            return value.strip()
        inner = match.group(1)
        value = theme.get(inner) or _THEMED.get(inner) or _PRIMITIVE[inner]
    raise AssertionError(f"{name} 의 var() 사슬이 8단을 넘었다")


def _flatten(color: str, backdrop: str) -> Color:
    """알파가 있는 색을 바탕에 겹쳐 실제 픽셀 색으로 만든다 (source-over, sRGB)."""
    src = Color(color).convert("srgb")
    dst = Color(backdrop).convert("srgb")
    alpha = src.alpha()
    return Color("srgb", [src[i] * alpha + dst[i] * (1 - alpha) for i in range(3)])


def _contrast(token: str, theme: dict[str, str]) -> float:
    canvas = _resolve("--canvas", theme)
    return _flatten(_resolve(token, theme), canvas).contrast(canvas, method="wcag21")


class TokenLayeringCase(unittest.TestCase):
    def test_light_is_the_default(self) -> None:
        """모든 테마별 토큰이 `:root` 에서 라이트 값을 갖는다 — 다크 블록 없이도 색이 정해진다."""
        self.assertTrue(_THEMED, "테마별 구역이 비었다")
        for name in _THEMED:
            self.assertTrue(_resolve(name, {}), f"{name} 이 라이트에서 빈 값이다")

    def test_dark_covers_the_same_token_set(self) -> None:
        """한쪽에만 있는 이름은 0 이어야 한다 — 덮지 못한 자리는 반대 테마 값을 써서 색이 어긋난다."""
        self.assertEqual(set(_THEMED) - set(_DARK), set(), "다크가 덮지 않은 토큰")
        self.assertEqual(set(_DARK) - set(_THEMED) - {"color-scheme"}, set(), "다크에만 있는 토큰")

    def test_constant_tokens_stay_out_of_the_dark_block(self) -> None:
        """간격·반지름·모션·글꼴은 테마를 타지 않는다. 다크에 다시 적으면 두 벌이 된다."""
        self.assertEqual(set(_CONSTANT) & set(_DARK), set())

    def test_system_preference_block_matches_the_dark_block(self) -> None:
        """다크 매핑은 두 자리에 적혀 있다. 순수 CSS 로 합칠 수 없어 여기서 대조한다."""
        self.assertEqual(_DARK, _MIRROR)

    def test_no_color_literal_outside_the_primitive_layer(self) -> None:
        """색값이 태어나는 자리는 원시 층 하나다 — `#0C0A07` 이 세 번 적히던 걸 되돌리지 않는다."""
        literal = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(")
        for region, label in ((_THEMED, "테마별"), (_DARK, "다크"), (_MIRROR, "시스템 다크")):
            for name, value in region.items():
                self.assertIsNone(literal.search(value), f"{label} {name} 에 색 리터럴: {value}")

    def test_every_primitive_name_is_prefixed(self) -> None:
        for name in _PRIMITIVE:
            self.assertTrue(name.startswith("--ak-"), f"원시 토큰 이름 규칙 위반: {name}")


class ContrastCase(unittest.TestCase):
    def test_body_ink_meets_aa_in_both_themes(self) -> None:
        for label, theme in (("light", {}), ("dark", _DARK)):
            for token in _BODY_INK:
                with self.subTest(theme=label, token=token):
                    self.assertGreaterEqual(round(_contrast(token, theme), 2), 4.5)

    def test_boundary_and_large_text_meet_three_to_one(self) -> None:
        for label, theme in (("light", {}), ("dark", _DARK)):
            for token in _BOUNDARY:
                with self.subTest(theme=label, token=token):
                    self.assertGreaterEqual(round(_contrast(token, theme), 2), 3.0)

    def test_brand_gold_is_never_body_ink_in_light(self) -> None:
        """`#C6A45E` 는 흰 바탕에서 2.37 이다. 채움과 마크로만 쓰고 글자로는 쓰지 않는다."""
        for token in _BODY_INK:
            self.assertNotEqual(_resolve(token, {}).lower(), "#c6a45e", f"{token} 이 라이트에서 브랜드 금이다")
        self.assertEqual(_resolve("--gold-mark", {}).lower(), "#c6a45e")
        self.assertLess(round(_contrast("--gold-mark", {}), 2), 3.0)

    def test_dark_keeps_the_shipped_values(self) -> None:
        shipped = {_resolve(name, _DARK).lower() for name in _THEMED}
        self.assertEqual(_SHIPPED_DARK_HEXES - shipped, set())


class ComponentKitCase(unittest.TestCase):
    def test_components_read_only_the_semantic_layer(self) -> None:
        """컴포넌트가 원시 토큰이나 색 리터럴을 읽으면 그 규칙은 테마를 따라오지 못한다."""
        body = _COMMENT.sub("", _COMPONENTS)
        self.assertNotIn("--ak-", body)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", body))

    def test_every_referenced_token_exists(self) -> None:
        known = set(_THEMED) | set(_CONSTANT) | set(_PRIMITIVE)
        used = {m.group(1) for m in _VAR.finditer(_COMMENT.sub("", _COMPONENTS))}
        self.assertEqual(used - known, set(), "정의되지 않은 토큰을 읽는다")

    def test_interactive_parts_ship_every_state(self) -> None:
        body = _COMMENT.sub("", _COMPONENTS)
        for base in (".ak-btn", ".ak-chip"):
            for state in (":hover", ":active", ":disabled"):
                with self.subTest(part=base, state=state):
                    self.assertIn(f"{base}{state}", body)
        self.assertIn(":focus-visible", body)

    def test_motion_has_a_reduced_motion_guard(self) -> None:
        body = _COMMENT.sub("", _COMPONENTS)
        self.assertIn("@keyframes", body)
        self.assertIn("@media (prefers-reduced-motion: reduce)", body)
        # 초점 표시는 대체 없이 지우면 안 되는 것이라 guard 안에서도 건드리지 않는다.
        guard = body[body.index("prefers-reduced-motion") :]
        self.assertNotIn("outline: none", guard)


if __name__ == "__main__":
    unittest.main()
