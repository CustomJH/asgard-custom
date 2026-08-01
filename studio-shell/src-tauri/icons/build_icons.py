#!/usr/bin/env python3
"""앱 아이콘 굽기 — 브랜드 마크 한 장에서 Tauri 가 요구하는 전 규격을 만든다.

    uv run --no-project --with pillow studio-shell/src-tauri/icons/build_icons.py

원본은 배경이 없는 금빛 선각(assets/asgard-yggdrasil-production-mark.png)이다. 그대로 쓰면
독의 어두운 배경에서 선이 사라지므로, 브랜드의 밤(#0C0A07) 위에 얹어 macOS 아이콘 격자
(1024 캔버스 · 824 본체)로 굽는다. 모서리는 원호가 아니라 초타원 — 원호는 macOS 이웃
아이콘들 사이에서 혼자 각져 보인다.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "assets" / "asgard-yggdrasil-production-mark.png"
OUT = Path(__file__).resolve().parent

CANVAS = 1024
BODY = 824  # macOS 아이콘 격자 — 캔버스 대비 본체
SS = 4  # 초타원과 마크 축소를 위한 초과표본
NIGHT_TOP = (27, 22, 14)  # --raised #1B160E
NIGHT_BOTTOM = (12, 10, 7)  # --vault  #0C0A07
GOLD_EDGE = (198, 164, 94)  # --gold   #C6A45E

# Tauri 가 참조하는 이름들 — square 계열은 Windows 타일이다
SQUARE_SIZES = {
    "32x32.png": 32,
    "64x64.png": 64,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "icon.png": 512,
    "Square30x30Logo.png": 30,
    "Square44x44Logo.png": 44,
    "Square71x71Logo.png": 71,
    "Square89x89Logo.png": 89,
    "Square107x107Logo.png": 107,
    "Square142x142Logo.png": 142,
    "Square150x150Logo.png": 150,
    "Square284x284Logo.png": 284,
    "Square310x310Logo.png": 310,
    "StoreLogo.png": 50,
}
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def superellipse(box: float, n: float = 5.0, steps: int = 720) -> list[tuple[float, float]]:
    """|x|^n + |y|^n = 1 — macOS 의 연속 곡률 모서리에 가까운 닫힌 윤곽."""
    r = box / 2
    points = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        cos_t, sin_t = math.cos(t), math.sin(t)
        x = math.copysign(abs(cos_t) ** (2 / n), cos_t)
        y = math.copysign(abs(sin_t) ** (2 / n), sin_t)
        points.append((r + x * r, r + y * r))
    return points


def body_mask(size: int) -> Image.Image:
    big = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(big).polygon(superellipse(size * SS), fill=255)
    return big.resize((size, size), Image.Resampling.LANCZOS)


def night(size: int) -> Image.Image:
    """위에서 아래로 옅어지는 밤 — 평면 검정은 독에서 구멍처럼 보인다."""
    gradient = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        gradient.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(NIGHT_TOP, NIGHT_BOTTOM)))
    return gradient.resize((size, size), Image.Resampling.BICUBIC)


def master() -> Image.Image:
    mark = Image.open(SOURCE).convert("RGBA")
    mark = mark.crop(mark.getbbox())  # 원본 여백은 우리 격자가 아니다

    body = night(BODY).convert("RGBA")
    body.putalpha(body_mask(BODY))
    # 어두운 바탕 위에서 아이콘의 경계가 서게 — 금빛 실선 한 겹
    edge = Image.new("RGBA", (BODY * SS, BODY * SS), (0, 0, 0, 0))
    ImageDraw.Draw(edge).polygon(superellipse(BODY * SS), outline=(*GOLD_EDGE, 70), width=3 * SS)
    body.alpha_composite(edge.resize((BODY, BODY), Image.Resampling.LANCZOS))

    inner = round(BODY * 0.78)  # 선각은 굵지 않다 — 본체에 꽉 채우지 않는다
    scale = inner / max(mark.size)
    box = (max(round(mark.width * scale), 1), max(round(mark.height * scale), 1))
    mark = mark.resize(box, Image.Resampling.LANCZOS)
    body.alpha_composite(mark, ((BODY - mark.width) // 2, (BODY - mark.height) // 2))

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.alpha_composite(body, ((CANVAS - BODY) // 2, (CANVAS - BODY) // 2))
    return canvas


def main() -> int:
    if not SOURCE.is_file():
        print(f"missing source mark: {SOURCE}", file=sys.stderr)
        return 1
    art = master()
    art.save(OUT.parents[1] / "app-icon.png")  # 1024 마스터 — `tauri icon` 이 보는 자리
    for name, size in SQUARE_SIZES.items():
        art.resize((size, size), Image.Resampling.LANCZOS).save(OUT / name)

    iconset = OUT / "icon.iconset"
    for stale in iconset.glob("*.png") if iconset.is_dir() else []:
        stale.unlink()
    iconset.mkdir(exist_ok=True)
    for size in ICNS_SIZES:
        art.resize((size, size), Image.Resampling.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
        if size > 16:
            art.resize((size, size), Image.Resampling.LANCZOS).save(iconset / f"icon_{size // 2}x{size // 2}@2x.png")
    if subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "icon.icns")]).returncode == 0:
        for stale in iconset.glob("*.png"):
            stale.unlink()
        iconset.rmdir()
    art.save(OUT / "icon.ico", sizes=[(s, s) for s in ICO_SIZES])
    print(f"icons written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
