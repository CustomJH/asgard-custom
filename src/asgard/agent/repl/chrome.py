"""터미널 치장 — 배너, 로고, 상태줄, 그리고 상자 글자. 밝은 배경 판정도 여기서 한다."""

from __future__ import annotations

import sys

from ... import theme, ui
from ...i18n import t

# install.sh _logo_art 원본 그대로 — Yggdrasil 마크 + ASGARD braille wordmark. install에서
# 나오는 그 로고. 축약하면 정렬이 깨지므로 원본 유지. 이미지 터미널은 _image_logo() PNG(동일 lockup).
_LOGO = (
    "⠀⠀⠀⠀⢀⡤⣶⣶⣶⣲⠤⣀⠀⠀⠀⠀  ⠀⠀⠀⢰⡄⠀⠀⠀⠀⠀⢀⣤⣦⣄⡀⠀⠀⠀⠀⣠⣦⣀⠀⠀⠀⠀⠀⠀⣦⠀⠀⠀⠀⠰⣶⣶⣶⣦⡀⠀⠀⠐⣶⣦⣄⠀⠀⠀\n"
    "⠀⠀⢀⣼⣽⣻⡟⣿⣷⢫⣟⣯⣧⡀⠀⠀  ⠀⠀⢀⣿⣷⠀⠀⠀⠀⢰⣿⠋⠈⠙⠁⠀⠀⣠⡾⠋⠈⠛⠀⠀⠀⠀⠀⣸⣿⡆⠀⠀⠀⠀⣿⡇⠀⠙⣷⡄⠀⠀⣿⡏⠻⣷⡄⠀\n"
    "⠀⠀⣸⢽⣦⡷⣻⣻⡟⣟⢾⣴⣯⣧⠀⠀  ⠀⠀⣼⡏⢻⣇⠀⠀⠀⠈⠛⢷⣤⡀⠀⠀⢸⣿⠁⠀⠀⣀⣀⠀⠀⠀⢠⣿⠙⣿⡀⠀⠀⠀⣿⡇⣀⣴⠟⠀⠀⠀⣿⡇⠀⠈⢻⡆\n"
    "⠀⠀⢻⠽⠇⠁⣸⢸⡇⣷⠈⠸⠯⡟⠀⠀  ⠀⢰⡿⢀⡈⣿⡄⠀⠀⠀⠀⠀⠙⢿⣦⠀⠘⢿⣄⠀⠀⢹⡏⠀⠀⠀⣾⠇⣀⢹⣧⠀⠀⠀⣿⡿⢻⣧⠀⠀⠀⠀⣿⡇⠀⣠⡿⠃\n"
    "⠀⠀⠈⢳⣲⣶⡿⣾⣷⢿⣶⣖⡞⠁⠀⠀  ⢀⣿⠁⠻⠃⢸⣷⡀⠀⠰⣶⣤⣴⠿⠃⠀⠀⠀⠙⢷⣤⣼⡇⠀⠀⣸⡟⠘⠟⠁⢻⣆⠀⠀⣿⡇⠀⠹⣷⡀⠀⠀⣿⣧⡾⠋⠀⠀\n"
    "⠀⠀⠀⠀⠈⠓⠻⠯⠵⠟⠚⠉⠀⠀⠀⠀  ⠉⠉⠁⠀⠀⠈⠉⠁⠀⠀⠀⠉⠁⠀⠀⠀⠀⠀⠀⠀⠉⠹⠃⠀⠈⠉⠉⠀⠀⠀⠉⠉⠁⠈⠉⠉⠀⠀⠈⠉⠀⠈⠉⠉⠀⠀⠀⠀"
)
_LOGO_SLIM = "◇ ASGARD"  # 폭 좁은 터미널용 축약


def is_light_bg() -> bool:
    """터미널 배경이 밝은지 — COLORFGBG='fg;bg'의 bg가 7~15 면 라이트. 모르면 다크 가정.
    라이트 배경엔 흰 로고가 안 보이고 골드 asset은 검정 박스가 보이므로, 이미지를 스킵하고
    진한 텍스트 로고로 폴백한다."""
    import os

    parts = os.environ.get("COLORFGBG", "").split(";")
    if len(parts) >= 2:
        try:
            return int(parts[-1]) >= 7
        except ValueError:
            pass
    return False


def _image_logo() -> bool:
    """지원 터미널(kitty/iterm/ghostty/wezterm) + 다크 배경이면 PNG lockup을 인라인 표시.
    라이트 배경은 흰 로고가 안 보여 스킵(→ 텍스트 폴백). install.sh _logo의 파이썬 포팅."""
    import base64
    import os

    if is_light_bg():  # 흰 lockup은 라이트 배경서 안 보인다 — 텍스트 폴백에 맡긴다
        return False
    proto = ""
    tp = os.environ.get("TERM_PROGRAM", "")
    term = os.environ.get("TERM", "")
    if tp in ("iTerm.app", "WezTerm") or os.environ.get("LC_TERMINAL") == "iTerm2":
        proto = "iterm"
    if (
        "kitty" in term
        or "ghostty" in term
        or os.environ.get("KITTY_WINDOW_ID")
        or os.environ.get("GHOSTTY_RESOURCES_DIR")
        or tp in ("ghostty", "Ghostty")
    ):
        proto = "kitty"
    if not proto:
        return False
    try:
        from importlib.resources import files

        data = (files("asgard") / "assets" / "logo-lockup.png").read_bytes()
    except Exception:
        return False
    b64 = base64.b64encode(data).decode()
    sys.stdout.write("\n  ")
    if proto == "iterm":
        sys.stdout.write(f"\033]1337;File=inline=1;width=30;preserveAspectRatio=1:{b64}\a\n")
    else:  # kitty graphics — 4096자 청크
        off, first = 0, True
        while off < len(b64):
            piece, off = b64[off : off + 4096], off + 4096
            more = 1 if off < len(b64) else 0
            if first:
                sys.stdout.write(f"\033_Gf=100,a=T,c=30,m={more};{piece}\033\\")
                first = False
            else:
                sys.stdout.write(f"\033_m={more};{piece}\033\\")
        sys.stdout.write("\n")
    sys.stdout.flush()
    return True


_O = theme.ansi(theme.PRIMARY)  # 브랜드 골드 (신성한 황금)
# 로고 세로 그라디언트 — theme.py 단일 소스 (다크=밝은 금→깊은 금, 라이트=진한 금)
_LOGO_GRAD = [theme.ansi(h) for h in theme.LOGO_GRAD]
_LOGO_GRAD_LIGHT = [theme.ansi(h) for h in theme.LOGO_GRAD_LIGHT]


def banner(rp) -> None:
    import shutil

    size = shutil.get_terminal_size((80, 20))
    width = size.columns
    roomy = width >= 100 and size.lines >= 36

    # 큰 lockup은 세로 공간이 충분할 때만. 120×30 같은 일반 터미널은 대화 공간을 우선한다.
    if not (roomy and ui._COLOR and _image_logo()):
        grad = _LOGO_GRAD_LIGHT if is_light_bg() else _LOGO_GRAD
        if roomy:
            sys.stdout.write("\n")
            for i, line in enumerate(_LOGO.split("\n")):
                col = grad[i] if i < len(grad) else grad[-1]
                sys.stdout.write("  " + ui.paint(col, line) + "\n")
        else:
            sys.stdout.write("\n  " + ui.paint(_O, _LOGO_SLIM) + "\n")

    # welcome + tip + 구분선 rule (모델·경로·git은 하단 status line으로)
    # rule은 HAIRLINE — 금은 로고·✦·입력 캐럿(좌측 스파인)에만, 프레임 선은 전부 한 하드라인 색
    rule = ui.paint(theme.ansi(theme.HAIRLINE), "─" * min(width - 4, 60))
    sys.stdout.write(
        f"\n  {ui.bold(t('welcome'))} {ui.dim(t('welcome_hint'))}\n  {ui.paint(_O, '✦')} {ui.dim(t('tip'))}\n  {rule}\n"
    )


def _git_status(root: str) -> str:
    """현재 브랜치(+dirty '*'). git repo 아니면 빈 문자열."""
    import subprocess

    try:
        b = subprocess.run(
            ["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            encoding="utf-8",
            errors="replace",
        )
        if b.returncode != 0:
            return ""
        branch = b.stdout.strip()
        d = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=3,
            encoding="utf-8",
            errors="replace",
        )
        return branch + ("*" if d.stdout.strip() else "")
    except Exception:
        return ""


# 상태줄 — 세그먼트 모델. 오딘 선택(26-07-16): 좌측 골드 브랜드칩 + 세그먼트별
# 아이콘·고유색(모델◆금·경로⌂청·git 녹/호박·lagom❄시안·메트릭 흐림). 색이 분절을 담당하므로
# 구분자는 여백만. 폭 주의: statusline은 단일 좌측 플로우라 폭 변동이 정렬을 깨지 않으며, 이모지
# 프리젠테이션 가능 글리프(❄)만 VS15(U+FE0E)로 텍스트 렌더 강제(색 ANSI 유지·너비 안정).
_BRAND_CHIP = "⠶ ASGARD"  # 좌측 골드 브랜드칩 — readline 폴백 statusline의 Asgard 시그니처
_STATUS_SEP = "   "  # 세그먼트 간 여백 — 색이 분절을 담당 (구분자 글리프 없음)
_ICON_LAGOM = "❄︎"  # ❄ + VS15 = 텍스트 프리젠테이션 강제 (색 이모지 렌더 방지)

# 입력 박스 프레임 (프레이야 명세 26-07-16) — 라운드 코너 U+2500(폭 안정). 라운드=라이브 입력,
# 향후 출력 블록은 샤프 ┌┐└┘ 로 시각 문법 분리. 상·하단 코너는 정적 라인이라 완전 폐합 안전,
# 입력 줄 좌측 │ 스파인만 두고 우측은 개방(라이브 편집·wrap로 깨지는 유일한 면 — rprompt 힌트가 채움).
_BOX = {"tl": "╭", "tr": "╮", "bl": "╰", "br": "╯", "h": "─", "v": "│"}
_BOX_CAP = "⠶ asgard"  # 상단 프레임 골드 브랜드 캡 — pt 경로 시그니처 (top-border 라벨)


def _abbrev_path(cwd: str, limit: int = 28) -> str:
    """긴 경로는 leaf 디렉토리만 남기고 축약 — ⠶·모델·git을 밀어내지 않게 (프레이야 절단 우선순위).
    `~/a/b/c/repo` → `~/…/repo`. leaf 자체가 길면 뒤에서 자른다."""
    if len(cwd) <= limit:
        return cwd
    leaf = cwd.rstrip("/").split("/")[-1] or cwd
    prefix = "~/…/" if cwd.startswith("~") else "…/"
    if len(prefix) + len(leaf) <= limit:
        return prefix + leaf
    return prefix + leaf[-(limit - len(prefix)) :]


def _status_segments(root: str, rp, usage: dict | None = None) -> list[tuple[str, str, bool]]:
    """상태줄 세그먼트 목록 — (아이콘+텍스트, hex 색, bold). 색 렌더(readline vs pt)는 호출부 몫.
    브랜드칩(⠶ ASGARD)은 호출부가 앞에 붙인다 — 여기선 모델부터."""
    import os

    home = os.path.expanduser("~")
    cwd = _abbrev_path(root.replace(home, "~", 1) if root.startswith(home) else root)
    if rp.missing:  # 키/설정 미충족 = 미연결 — 색+`!`+단어 이중 인코딩
        return [("! " + t("not_connected"), theme.WARNING, False), (f"⌂ {cwd}", theme.ACCENT_BLUE, False)]
    segs = [(f"◆ {rp.model}", theme.PRIMARY, False), (f"⌂ {cwd}", theme.ACCENT_BLUE, False)]  # 모델=금·경로=청
    isolation = os.environ.get("ASGARD_ISOLATION")
    if isolation in {"docker-sandbox", "oci-container"}:
        segs.append(("▣ " + ("sandbox" if isolation == "docker-sandbox" else "container"), theme.SUCCESS, False))
    if usage and usage.get("active_sessions"):
        count = usage["active_sessions"]
        role = usage.get("active_role") or "agent"
        segs.append((f"◇ {role}" + (f" +{count - 1}" if count > 1 else ""), theme.ACCENT_CYAN, False))
    br = _git_status(root)
    if br:  # git 라이브 색 — clean 룬 녹색, dirty 호박(접미 `*`로 색맹에도 구분)
        segs.append((br, theme.SUCCESS if not br.endswith("*") else theme.WARNING, False))
    try:  # Lagom 모드 — off는 흔적 없음 (bifrost 시안 ❄)
        from ...lagom import current_mode

        lm = current_mode(root)
        if lm != "off":
            segs.append((f"{_ICON_LAGOM} lagom:{lm}", theme.ACCENT_CYAN, False))
    except Exception:
        pass
    if usage and usage.get("tokens"):
        tok = usage["tokens"]  # 누적 지출 (iteration 마다 전체 프롬프트 재합산 — 창 % 기준으론 부적합)
        win = rp.context_window or rp.profile.context_window  # config override 우선 (CUS-248)
        ctx = usage.get("context") or 0  # 마지막 호출 컨텍스트 크기 — 창 % 는 이걸로
        metric = f"{tok / 1000:.1f}k"
        metric_color = theme.SUBTEXT
        if win and ctx:  # 세그먼트 내부는 미들닷 하위결합 (세그먼트 간 여백과 2단 구두점)
            pct = ctx / win * 100
            metric += f"·{pct:.0f}%"
            # 창 압박 경고색 — 70% 호박, 90% 적색 (프룬 트리거 80% 를 사이에 두는 2단 신호)
            if pct >= 90:
                metric_color = theme.DANGER
            elif pct >= 70:
                metric_color = theme.WARNING
        segs.append((metric, metric_color, False))
        if usage.get("cache_prompt"):  # 프롬프트 캐시 적중률 — read / (read+write+정가 입력)
            segs.append(
                (f"cache {usage.get('cache_read', 0) / usage['cache_prompt'] * 100:.0f}%", theme.SUBTEXT, False)
            )
    return segs


def _paint_seg(txt: str, hx: str, bold: bool) -> str:
    s = ui.paint(theme.ansi(hx), txt)
    return ui.bold(s) if bold else s


def statusline(root: str, rp, usage: dict | None = None) -> str:
    """상태줄 (readline 폴백 경로 — pt는 bottom_toolbar로 표시). 골드 브랜드칩 + 컬러 아이콘 세그먼트."""
    segs = _status_segments(root, rp, usage)
    if not ui._COLOR:  # 무색 터미널 — 텍스트만
        return "  " + _STATUS_SEP.join([_BRAND_CHIP, *[txt for txt, _, _ in segs]])
    chip = ui.bold(ui.paint(theme.ansi(theme.PRIMARY), _BRAND_CHIP))
    body = _STATUS_SEP.join(_paint_seg(txt, hx, b) for txt, hx, b in segs)
    return f"  {chip}{_STATUS_SEP}{body}"
