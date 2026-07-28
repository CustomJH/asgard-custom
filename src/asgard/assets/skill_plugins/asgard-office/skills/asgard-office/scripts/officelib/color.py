"""WCAG relative luminance and contrast, in one place.

The naive version — weighting the raw 0-255 channels — is off by enough to
change verdicts: #7B8794 on white reads 1.8:1 without gamma linearisation and
4.3:1 with it. One of those says "unreadable" about a perfectly ordinary
caption grey. sRGB is not linear light; the transfer function is not optional.
"""

from __future__ import annotations

_WEIGHTS = (0.2126, 0.7152, 0.0722)


def _channel(value: int) -> float:
    scaled = value / 255.0
    return scaled / 12.92 if scaled <= 0.04045 else ((scaled + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    """WCAG relative luminance of an RRGGBB string, 0.0 (black) to 1.0 (white)."""
    text = color.lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    channels = (int(text[index : index + 2], 16) for index in (0, 2, 4))
    return sum(weight * _channel(value) for weight, value in zip(_WEIGHTS, channels))


def contrast(front: str, back: str) -> float:
    light, dark = sorted((luminance(front), luminance(back)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def is_dark(color: str) -> bool:
    """Whether white text belongs on this background rather than dark text."""
    return contrast("FFFFFF", color) >= contrast("1F2933", color)


def readable_ink(background: str, light: str = "FFFFFF", dark: str = "1F2933") -> str:
    return light if contrast(light, background) >= contrast(dark, background) else dark


def _rgb(color: str) -> tuple[int, int, int]:
    text = color.lstrip("#")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def mix(color: str, toward: str, amount: float) -> str:
    """Blend two colours in sRGB. Good enough for nudging a hue into legibility."""
    source, target = _rgb(color), _rgb(toward)
    blended = tuple(round(a + (b - a) * max(0.0, min(1.0, amount))) for a, b in zip(source, target))
    return "".join(f"{channel:02X}" for channel in blended)


def readable_accent(color: str, background: str, *, floor: float = 3.0, steps: int = 24) -> str:
    """Keep an accent's hue but push its lightness until it clears the contrast floor.

    A brand coral at 3.0:1 on white is a real defect, and the fix a designer
    would make is a darker coral — not a different colour, and not black.
    """
    if contrast(color, background) >= floor:
        return color
    toward = "FFFFFF" if is_dark(background) else "000000"
    for step in range(1, steps + 1):
        candidate = mix(color, toward, step / steps)
        if contrast(candidate, background) >= floor:
            return candidate
    return toward
