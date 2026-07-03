"""Asgard 디자인 토큰 — 브랜드 색 단일 소스 (신성한 황금 · 왕실 네이비).

hex 는 rich/Textual markup·CSS 용. 터미널 raw ANSI 는 ansi() 로 변환해 ui.paint 에
넣는다 (truecolor 터미널은 24bit, 아니면 xterm-256 근사). Textual 앱은
textual_theme() 를 register_theme 하고 theme="asgard" 로 쓴다 — CSS 에서
$primary/$accent/$surface 참조.
"""

import os

PRIMARY = "#D4AF37"      # 신성한 황금 — 브랜드 마크·로고·액센트 바
SECONDARY = "#1E2A44"    # 왕실 네이비 — 패널·보조 배경
BACKGROUND = "#090B12"   # 우주
SURFACE = "#151D38"      # 궁전 석재
TEXT = "#F7F5EF"
SUBTEXT = "#C8C5BD"

ACCENT_BLUE = "#5FA8D3"  # 정보·진행 (phase 태그·스피너·화살표)
ACCENT_CYAN = "#5DE7FF"  # 포커스·하이라이트 (bifrost)
ACCENT_PURPLE = "#8B5CF6"
SUCCESS = "#4ADE80"
WARNING = "#FBBF24"
DANGER = "#DC2626"

# 로고 세로 그라디언트 — 다크 배경은 밝은 금→깊은 금, 라이트 배경은 진한 금(밝은 금은 흰 배경서 안 보임)
LOGO_GRAD = ["#F5E6B0", "#E9CE79", "#D4AF37", "#BD9A2F", "#A28327", "#856B1F"]
LOGO_GRAD_LIGHT = ["#8A6D1E", "#8A6D1E", "#6F5716", "#6F5716", "#6F5716", "#6F5716"]

_TRUECOLOR = ("truecolor" in os.environ.get("COLORTERM", "")
              or "24bit" in os.environ.get("COLORTERM", ""))


def _x256(r: int, g: int, b: int) -> int:
    """xterm-256 근사 — 6×6×6 색 큐브와 그레이 램프 중 오차 작은 쪽."""
    def q(v: int) -> int:  # 큐브 레벨 0,95,135,175,215,255 로 양자화
        return 0 if v < 48 else 1 if v < 115 else min(5, (v - 35) // 40)

    def lvl(i: int) -> int:
        return 0 if i == 0 else 40 * i + 55

    ci, cj, ck = q(r), q(g), q(b)
    cube_err = (lvl(ci) - r) ** 2 + (lvl(cj) - g) ** 2 + (lvl(ck) - b) ** 2
    gi = max(0, min(23, (((r + g + b) // 3) - 3) // 10))  # 램프 8,18,…,238
    gv = 8 + 10 * gi
    gray_err = (gv - r) ** 2 + (gv - g) ** 2 + (gv - b) ** 2
    return (232 + gi) if gray_err < cube_err else (16 + 36 * ci + 6 * cj + ck)


def ansi(hex_color: str) -> str:
    """ui.paint 용 SGR 전경색 파라미터 — '38;2;r;g;b' 또는 '38;5;N'."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"38;2;{r};{g};{b}" if _TRUECOLOR else f"38;5;{_x256(r, g, b)}"


def textual_theme():
    """asgard Textual 테마. TUI 경로에서만 호출 — CLI 는 textual 미로드."""
    from textual.theme import Theme
    return Theme(
        name="asgard",
        primary=PRIMARY,
        secondary=SECONDARY,
        background=BACKGROUND,
        surface=SURFACE,
        panel=SECONDARY,
        foreground=TEXT,
        accent=ACCENT_CYAN,
        success=SUCCESS,
        warning=WARNING,
        error=DANGER,
        dark=True,
    )
