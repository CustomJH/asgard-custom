"""네이티브 REPL 렌더 — 브랜드 로고 + 간결 UX.

설계 지향: 세션 헤더(provider·model) + 슬래시 커맨드 + tool-use 축약 한 줄,
미니멀·조용한 기본(저소음), 정렬된 컬러와 역할/툴 심볼, provider·model 상태 라인.
입력 프레임은 턴 진행 중에도 하단에 상주한다(_Dock) — 출력이 독 위로 흘러들고,
턴이 끝나면 pt 프롬프트가 같은 자리를 이어받는다 (프레이야 명세 26-07-20).

ANSI 직접 (ui.py 스타일 일관 — rich Markdown 은 스트리밍과 안 맞아 버퍼가 필요). 로고는
install.sh 의 Yggdrasil braille lockup 재사용 — 어느 터미널·배경에서나 렌더된다.
"""

from __future__ import annotations

import sys

from .. import theme, ui
from ..i18n import t
from .session import ql

# install.sh _logo_art 원본 그대로 — Yggdrasil 마크 + ASGARD braille wordmark. install 에서
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
    """터미널 배경이 밝은지 — COLORFGBG='fg;bg' 의 bg 가 7~15 면 라이트. 모르면 다크 가정.
    라이트 배경엔 흰 로고가 안 보이고 골드 asset 은 검정 박스가 보이므로, 이미지를 스킵하고
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
    """지원 터미널(kitty/iterm/ghostty/wezterm) + 다크 배경이면 PNG lockup 을 인라인 표시.
    라이트 배경은 흰 로고가 안 보여 스킵(→ 텍스트 폴백). install.sh _logo 의 파이썬 포팅."""
    import base64
    import os

    if is_light_bg():  # 흰 lockup 은 라이트 배경서 안 보인다 — 텍스트 폴백에 맡긴다
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

    # 큰 lockup 은 세로 공간이 충분할 때만. 120×30 같은 일반 터미널은 대화 공간을 우선한다.
    if not (roomy and ui._COLOR and _image_logo()):
        grad = _LOGO_GRAD_LIGHT if is_light_bg() else _LOGO_GRAD
        if roomy:
            sys.stdout.write("\n")
            for i, line in enumerate(_LOGO.split("\n")):
                col = grad[i] if i < len(grad) else grad[-1]
                sys.stdout.write("  " + ui.paint(col, line) + "\n")
        else:
            sys.stdout.write("\n  " + ui.paint(_O, _LOGO_SLIM) + "\n")

    # welcome + tip + 구분선 rule (모델·경로·git 은 하단 status line 으로)
    # rule 은 HAIRLINE — 금은 로고·✦·입력 캐럿(좌측 스파인)에만, 프레임 선은 전부 한 하드라인 색
    rule = ui.paint(theme.ansi(theme.HAIRLINE), "─" * min(width - 4, 60))
    sys.stdout.write(
        f"\n  {ui.bold(t('welcome'))} {ui.dim(t('welcome_hint'))}\n  {ui.paint(_O, '✦')} {ui.dim(t('tip'))}\n  {rule}\n"
    )


def _git_status(root: str) -> str:
    """현재 브랜치(+dirty '*'). git repo 아니면 빈 문자열."""
    import subprocess

    try:
        b = subprocess.run(
            ["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=3
        )
        if b.returncode != 0:
            return ""
        branch = b.stdout.strip()
        d = subprocess.run(["git", "-C", root, "status", "--porcelain"], capture_output=True, text=True, timeout=3)
        return branch + ("*" if d.stdout.strip() else "")
    except Exception:
        return ""


# 상태줄 — 세그먼트 모델. 오딘 선택(26-07-16): 좌측 골드 브랜드칩 + 세그먼트별
# 아이콘·고유색(모델◆금·경로⌂청·git 녹/호박·lagom❄시안·메트릭 흐림). 색이 분절을 담당하므로
# 구분자는 여백만. 폭 주의: statusline 은 단일 좌측 플로우라 폭 변동이 정렬을 깨지 않으며, 이모지
# 프리젠테이션 가능 글리프(❄)만 VS15(U+FE0E)로 텍스트 렌더 강제(색 ANSI 유지·너비 안정).
_BRAND_CHIP = "⠶ ASGARD"  # 좌측 골드 브랜드칩 — readline 폴백 statusline 의 Asgard 시그니처
_STATUS_SEP = "   "  # 세그먼트 간 여백 — 색이 분절을 담당 (구분자 글리프 없음)
_ICON_LAGOM = "❄︎"  # ❄ + VS15 = 텍스트 프리젠테이션 강제 (색 이모지 렌더 방지)

# 입력 박스 프레임 (프레이야 명세 26-07-16) — 라운드 코너 U+2500(폭 안정). 라운드=라이브 입력,
# 향후 출력 블록은 샤프 ┌┐└┘ 로 시각 문법 분리. 상·하단 코너는 정적 라인이라 완전 폐합 안전,
# 입력 줄 좌측 │ 스파인만 두고 우측은 개방(라이브 편집·wrap 로 깨지는 유일한 면 — rprompt 힌트가 채움).
_BOX = {"tl": "╭", "tr": "╮", "bl": "╰", "br": "╯", "h": "─", "v": "│"}
_BOX_CAP = "⠶ asgard"  # 상단 프레임 골드 브랜드 캡 — pt 경로 시그니처 (top-border 라벨)


def _abbrev_path(cwd: str, limit: int = 28) -> str:
    """긴 경로는 leaf 디렉토리만 남기고 축약 — ⠶·모델·git 을 밀어내지 않게 (프레이야 절단 우선순위).
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
    if br:  # git 라이브 색 — clean 룬 녹색, dirty 호박(접미 `*` 로 색맹에도 구분)
        segs.append((br, theme.SUCCESS if not br.endswith("*") else theme.WARNING, False))
    try:  # Lagom 모드 — off 는 흔적 없음 (bifrost 시안 ❄)
        from ..lagom import current_mode

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
    """상태줄 (readline 폴백 경로 — pt 는 bottom_toolbar 로 표시). 골드 브랜드칩 + 컬러 아이콘 세그먼트."""
    segs = _status_segments(root, rp, usage)
    if not ui._COLOR:  # 무색 터미널 — 텍스트만
        return "  " + _STATUS_SEP.join([_BRAND_CHIP, *[txt for txt, _, _ in segs]])
    chip = ui.bold(ui.paint(theme.ansi(theme.PRIMARY), _BRAND_CHIP))
    body = _STATUS_SEP.join(_paint_seg(txt, hx, b) for txt, hx, b in segs)
    return f"  {chip}{_STATUS_SEP}{body}"


_COMMAND_HELP = {
    "/help": "h_help",
    "/skills": "h_skills",
    "/new": "h_new",
    "/quest": "h_quest",
    "/sessions": "h_sessions",
    "/sessions stop": "h_sessions",
    "/provider": "h_provider",
    "/provider set": "h_provider_set",
    "/trinity": "h_trinity",
    "/trinity set": "h_trinity",
    "/trinity models": "h_trinity",
    "/trinity model": "h_trinity",
    "/trinity model reset": "h_trinity",
    "/trinity dual": "h_trinity",
    "/trinity dual on": "h_trinity",
    "/trinity dual off": "h_trinity",
    "/trinity dual default": "h_trinity",
    "/trinity dual default on": "h_trinity",
    "/trinity dual default off": "h_trinity",
    "/bridge": "h_bridge",
    "/lagom": "h_lagom",
    "/lagom off": "h_lagom",
    "/lagom lite": "h_lagom",
    "/lagom full": "h_lagom",
    "/lagom default": "h_lagom",
    "/lagom stats": "h_lagom",
    "/model": "h_model",
    "/lang": "h_lang",
    "/lang en": "h_lang",
    "/lang ko": "h_lang",
    "/update": "h_update",
    "/clear": "h_clear",
    "/exit": "h_exit",
}


def _help_items():
    return [(command, t(key)) for command, key in _COMMAND_HELP.items() if " " not in command]


def _completion_matches(text: str) -> list[str]:
    """최상위 명령을 먼저 보여주고, 인자 후보는 사용자가 공백을 입력한 뒤 펼친다."""
    return [c for c in _COMMAND_HELP if c.startswith(text) and (" " in text or " " not in c)]


def _completer(text: str, state: int):
    """Tab 자동완성 — 슬래시 커맨드 (/ 트리거). readline 콜백."""
    if not text.startswith("/"):
        return None
    matches = [c + " " for c in _completion_matches(text)]
    return matches[state] if state < len(matches) else None


_PT = None  # prompt_toolkit 세션 캐시 — False 면 생성 실패(readline 폴백)
_PT_CTX: dict = {}  # bottom_toolbar 용 세션 상태 — run() 이 매 루프 갱신 {root, rp, heimdall}


def _term_width() -> int:
    import shutil

    return max(20, shutil.get_terminal_size((80, 20)).columns)


def _term_rows() -> int:
    import shutil

    return max(_Dock.HEIGHT, shutil.get_terminal_size((80, 24)).lines)


def _disp_w(s: str) -> int:
    """표시 폭 — CJK 전각(W/F) 2칸. 독 입력행 절단·캐럿 열 계산 공용."""
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _decode_keys(raw: bytes) -> tuple[str, bytes]:
    """원시 stdin 바이트 → 독 초안에 반영할 텍스트. 미완성 UTF-8/이스케이프 꼬리는 carry 로
    보류하고, 완성된 이스케이프 시퀀스(CPR 응답·화살표 등)는 폐기한다 — 커널 버퍼의 원시
    바이트가 다음 pt 프롬프트를 오염시키는 경로를 여기서 끊는다."""
    import re

    text, keep = "", b""
    for cut in (0, 1, 2, 3):
        try:
            text, keep = raw[: len(raw) - cut].decode("utf-8"), raw[len(raw) - cut :]
            break
        except UnicodeDecodeError:
            continue
    else:
        return "", b""  # UTF-8 로 못 푸는 잡음 — 폐기
    text = re.sub(r"\x1b(?:\[[0-9;?]*[A-Za-z~]|O.)", "", text)  # 완성 시퀀스 폐기
    m = re.search(r"\x1b(?:\[[0-9;?]*|O)?\Z", text)  # 끝의 미완성 시퀀스 접두 — 다음 청크와 합류
    if m and m.group(0):
        text, held = text[: m.start()], m.group(0)
        keep = held.encode() + keep
    return text.replace("\x1b", ""), keep


def _box_fill(width: int) -> int:
    """상단 보더 캡 우측 채움 길이 — pt 프래그(_box_top)와 독 문자열(_box_top_str) 공용 기하.
    프레임폭(╭→╮) = width-4. 캡 포함: ╭(1)+'─ '(2)+캡(len)+' '(1)+채움+╮(1)."""
    return width - 4 - (1 + 2 + len(_BOX_CAP) + 1 + 1)  # = width - 9 - len(cap)


def _box_top(width: int) -> list[tuple[str, str]]:
    """상단 보더 프래그 — ╭─ ⠶ asgard ───╮ (좁으면 캡 드롭). 좌 들여쓰기 2·우 여백 2로 하단과 정렬."""
    fill = _box_fill(width)
    if fill < 4:  # 좁은 터미널 — 캡 드롭, 코너만
        dashes = max(0, width - 6)
        return [("class:rule", "  " + _BOX["tl"] + _BOX["h"] * dashes + _BOX["tr"] + "\n")]
    return [
        ("class:rule", "  " + _BOX["tl"] + _BOX["h"] + " "),  # "  ╭─ "
        ("class:cap", _BOX_CAP),  # 골드 브랜드 캡
        ("class:rule", " " + _BOX["h"] * fill + _BOX["tr"] + "\n"),  # " ───╮"
    ]


def _box_top_str(width: int) -> str:
    """_box_top 의 ANSI 문자열판 — 독(비활성 프레임)용. pt 프래그와 같은 기하·색."""
    rule = theme.ansi(theme.HAIRLINE)
    fill = _box_fill(width)
    if fill < 4:
        return "  " + ui.paint(rule, _BOX["tl"] + _BOX["h"] * max(0, width - 6) + _BOX["tr"])
    return (
        "  "
        + ui.paint(rule, _BOX["tl"] + _BOX["h"] + " ")
        + ui.bold(ui.paint(_O, _BOX_CAP))
        + ui.paint(rule, " " + _BOX["h"] * fill + _BOX["tr"])
    )


def _box_bottom_str(width: int) -> str:
    """하단 보더 ╰───╯ — pt toolbar 첫 줄과 같은 기하·색 (독 프레임용)."""
    return "  " + ui.paint(theme.ansi(theme.HAIRLINE), _BOX["bl"] + _BOX["h"] * max(0, width - 6) + _BOX["br"])


def _usage_of(hd) -> dict | None:
    """Heimdall 누적 사용량 → 상태줄 usage dict (독·pt toolbar·readline 폴백 공용)."""
    if hd is None:
        return None
    active = hd.session_snapshot(active_only=True) if hasattr(hd, "session_snapshot") else []
    return {
        "tokens": hd.total_tokens,
        "context": hd.last_context_tokens,
        "cache_read": hd.cache_read_tokens,
        "cache_prompt": hd.cache_prompt_tokens,
        "active_sessions": len(active),
        "active_role": active[-1]["role"] if active else "",
    }


def _pt_message():
    """입력 영역 — 상단 박스 보더(브랜드 캡) + 좌측 │ 스파인 + 골드 캐럿."""
    return [
        *_box_top(ui.stream_width()),  # 터미널 가로 칸 수 그대로 — 반응형 박스 폭
        ("class:rule", "  " + _BOX["v"] + " "),  # 입력 줄 좌측 스파인 "  │ "
        ("class:arrow", "› "),
    ]


def _pt_toolbar():
    """입력창 아래 — 하단 rule + 상태줄 (모델 · 디렉토리 · git · 사용량)."""
    ctx = _PT_CTX
    if not ctx:
        return ""
    usage = _usage_of(ctx.get("heimdall"))
    w = ui.stream_width()  # 상단 보더와 같은 폭 캡 — 코너 정렬
    bottom = "  " + _BOX["bl"] + _BOX["h"] * max(0, w - 6) + _BOX["br"] + "\n"  # 하단 보더 ╰───╯
    frags: list[tuple[str, str]] = [("class:rule", bottom), ("", "  ")]  # 상태줄은 박스 밖(아래), 들여쓰기 2
    # 브랜드칩은 상단 캡(⠶ asgard)이 담당 — pt 경로 시그니처 1개. 상태줄은 model 부터 (상태 전용)
    for i, (txt, hx, bold) in enumerate(_status_segments(ctx["root"], ctx["rp"], usage)):
        if i:
            frags.append(("", _STATUS_SEP))  # 여백 구분자 (색이 분절)
        frags.append((f"fg:{hx} bold" if bold else f"fg:{hx}", txt))
    return frags


def _history_path() -> str:
    import os

    hp = os.path.join(os.path.expanduser("~"), ".asgard", "history")
    os.makedirs(os.path.dirname(hp), exist_ok=True)
    return hp


def _kb_enter(event) -> None:
    """Enter = 제출. 단 커서 앞이 '\\' 로 끝나면 백슬래시를 지우고 줄 내림 (연속 입력)."""
    buf = event.current_buffer
    if buf.document.current_line_before_cursor.endswith("\\"):
        buf.delete_before_cursor(1)
        buf.insert_text("\n")
    else:
        buf.validate_and_handle()


def _kb_newline(event) -> None:
    """Shift+Enter(CSI-u·modifyOtherKeys 터미널)·Ctrl+J — 줄 내림."""
    event.current_buffer.insert_text("\n")


def _pt_continuation(width, line_number, is_soft_wrap):
    """멀티라인 연속 행 프리픽스 — 좌측 │ 스파인 유지 + 첫 행('  │ › ' 6칸)과 동일 폭 정렬."""
    return [("class:rule", "  " + _BOX["v"] + " "), ("", "  ")]


def _pt_session():
    """prompt_toolkit 세션 — '/' 입력 즉시 후보 메뉴(설명 포함)가 아래에 뜨고 Tab·화살표로
    완성한다. 색은 theme 토큰. 멀티라인: Enter 제출 · '\\'+Enter / Shift+Enter / Ctrl+J 줄 내림."""
    from collections.abc import Callable

    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.input import ansi_escape_sequences as _esc
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.styles import Style

    # Shift+Enter 를 Ctrl+J 로 별칭 — CSI-u(\x1b[13;2u)는 미매핑, modifyOtherKeys(\x1b[27;2;13~)는
    # pt 기본이 일반 Enter 라 줄내림으로 재매핑한다. 미지원 터미널은 \r 그대로 → '\'+Enter 가 대안.
    for seq in ("\x1b[13;2u", "\x1b[27;2;13~"):
        _esc.ANSI_SEQUENCES[seq] = Keys.ControlJ

    kb = KeyBindings()
    kb.add("enter")(_kb_enter)
    kb.add("c-j")(_kb_newline)

    class _BottomAnchored(PromptSession):
        """하단 고정용 세션 — 메뉴 예약을 동적으로: '/' 커맨드 입력 중일 때만 8행.
        pt 는 이 값을 렌더마다 읽으므로(_get_default_buffer_control_height) 프로퍼티가 통한다.
        상시 예약은 입력행과 toolbar(하단 보더·상태줄)를 항상 8행 찢어 놓아 하단 고정과 상극 —
        필요한 순간에만 열어 평소엔 프레임이 밀착된다 (pyte 실측 검증)."""

        _asgard_bottom_pad: Callable[[], object]  # 바닥 정렬 필러 — _pt_session 말미 배선 (테스트 노출)

        @property
        def reserve_space_for_menu(self) -> int:
            try:
                return 8 if self.default_buffer.text.startswith("/") else 0
            except Exception:
                return 0

        @reserve_space_for_menu.setter
        def reserve_space_for_menu(self, value: int) -> None:
            pass  # __init__ 의 정적 대입 무시 — 동적 계산이 단일 소스

    class _Slash(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/"):
                return
            for c in _completion_matches(text):
                yield Completion(c + " ", start_position=-len(text), display=c, display_meta=t(_COMMAND_HELP[c]))

    style = Style.from_dict(
        {
            "arrow": f"{theme.PRIMARY} bold",
            "cap": f"{theme.PRIMARY} bold",  # 상단 박스 프레임 골드 브랜드 캡 (⠶ asgard)
            "rule": theme.HAIRLINE,  # 입력·박스 프레임 룰 — 배너 rule 과 한 하드라인 색
            "placeholder": theme.SUBTEXT,
            "hint": theme.SUBTEXT,
            "bottom-toolbar": "noreverse",
            "completion-menu": f"bg:{theme.SURFACE} {theme.TEXT}",
            "completion-menu.completion.current": f"bg:{theme.PRIMARY} {theme.BACKGROUND}",
            "completion-menu.meta.completion": f"bg:{theme.SURFACE} {theme.SUBTEXT}",
            "completion-menu.meta.completion.current": f"bg:{theme.PRIMARY} {theme.SECONDARY}",
            "auto-suggestion": theme.SUBTEXT,
        }
    )
    session = _BottomAnchored(
        completer=_Slash(),
        complete_while_typing=True,
        auto_suggest=AutoSuggestFromHistory(),
        history=FileHistory(_history_path()),
        style=style,
        multiline=True,  # 줄 내림 허용 — Enter 제출은 _kb_enter 가 유지 (기본 멀티라인 Enter 를 대체)
        key_bindings=kb,
        prompt_continuation=_pt_continuation,
        # 제출 시 입력 프레임 전체 소거 — 라이브 에디터는 편집 중에만 존재하고, 스크롤백엔
        # run() 의 _echo_submitted 한 줄이 사용자 메시지를 대표한다 (pi·hermes·opencode 공통:
        # 에디터는 transient, 내역엔 별도 표현. 열린 박스·rprompt 힌트 잔존 문제의 근본 해소).
        erase_when_done=True,
    )

    # 바닥 정렬 필러 — pt 인라인 프롬프트는 커서 원점에 위에서부터 그린다. 박스 위를
    # `화면 잔여 행(rows − rows_above_layout, CPR 기반) − 본체 필요 행` 만큼 정확히 채우면
    # 박스가 바닥에 붙고, 성장(줄 추가·메뉴 오픈)은 필러를 소모할 뿐 화면을 스크롤하지 않으며
    # 축소는 필러가 되살아나 위 내용(배너·직전 출력)이 전혀 움직이지 않는다. 잔여 공간을
    # 넘는 성장만 pt 가 자연 스크롤. accept(is_done) 시 필러가 접혀 제출 박스는 본문 흐름
    # 위치로 붙고 스크롤백에 빈 행이 남지 않는다. CPR 미지원/미도착이면 0 (원점 폴백).
    from prompt_toolkit.filters import is_done
    from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.layout.layout import Layout

    inner = session.layout.container

    def _bottom_pad() -> Dimension:
        from prompt_toolkit.application import get_app

        app = get_app()
        try:
            above = app.renderer.rows_above_layout
        except Exception:
            return Dimension.exact(0)
        size = app.output.get_size()
        body = inner.preferred_height(size.columns, size.rows).preferred
        return Dimension.exact(max(0, size.rows - above - body))

    session.app.layout = Layout(HSplit([ConditionalContainer(Window(height=_bottom_pad), filter=~is_done), inner]))
    session._asgard_bottom_pad = _bottom_pad  # 테스트 노출용
    return session


def _setup_readline() -> None:
    """readline 배선 — Tab 자동완성 + 화살표 히스토리(파일 영속). 없는 플랫폼은 조용히 스킵.
    prompt_toolkit 폴백 경로 전용 (기본은 _pt_session)."""
    try:
        import atexit
        import os
        import readline
    except Exception:
        return
    readline.set_completer(_completer)
    readline.set_completer_delims("")  # 전체 라인을 completion 대상으로 (/ 포함)
    # uv 파이썬(macOS)은 GNU readline 이 아니라 libedit — 바인딩 문법이 다르다.
    # GNU 문법("tab: complete")을 libedit 에 주면 조용히 무시돼 Tab 이 탭 문자로 들어간다.
    if getattr(readline, "backend", "") == "editline":
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")
    hp = os.path.join(os.path.expanduser("~"), ".asgard", "history")
    try:
        os.makedirs(os.path.dirname(hp), exist_ok=True)
        readline.read_history_file(hp)
    except Exception:
        pass
    readline.set_history_length(1000)
    atexit.register(lambda: _save_history(readline, hp))


def _save_history(readline, path: str) -> None:
    try:
        readline.write_history_file(path)
    except Exception:
        pass


def _input_continued(first: str, cont: str) -> str:
    """input() 경로의 '\\' 연속 입력 — 트레일링 백슬래시는 지우고 다음 줄을 이어 받는다."""
    parts = [input(first)]
    while parts[-1].endswith("\\"):
        parts[-1] = parts[-1][:-1]
        parts.append(input(cont))
    return "\n".join(parts)


def _echo_submitted(req: str) -> str:
    """제출된 입력의 스크롤백 표기 — pt 가 accept 시 입력 프레임을 통째로 지우므로
    (erase_when_done) 내역엔 이 표기가 사용자 메시지를 대표한다. 일반 요청은 골드 캐럿 `›`
    + 본문(hermes 의 ❯ 거터 상응), 커맨드(`/`·`!`)는 전체 흐림(hermes 의 muted slash 라인
    상응 — 대화가 아니라 조작이므로 조용히). 멀티라인은 본문 열('  › ' 4칸)에 정렬."""
    lines = req.split("\n")
    if req.startswith(("/", "!")):
        return "  " + ui.dim("› " + "\n    ".join(lines))
    head = "  " + ui.paint(_O, "›") + " " + lines[0]
    return head + "".join("\n    " + line for line in lines[1:])


def prompt(default_text: str = "", auto_submit: bool = False) -> str:
    # cursor-agent 식 입력 영역 — rule 프레임 + 골드 → + placeholder + 하단 상태줄.
    # default_text = 턴 중 독에 타이핑된 초안 프리필, auto_submit = 트레일링 ⏎(제출 의사) 즉시 제출.
    if not ui._COLOR:
        return _input_continued("  › ", "  … ")
    if _PT:
        return _PT.prompt(
            _pt_message,
            placeholder=[("class:placeholder", t("ph_input"))],
            rprompt=[("class:hint", t("interrupt_hint") + " ")],
            bottom_toolbar=_pt_toolbar,
            default=default_text,
            accept_default=auto_submit and bool(default_text),
        )
    # readline 폴백 — 비출력(ANSI) 문자는 \x01..\x02 로 감싸야 커서 폭을 정확히 계산한다.
    arrow = f"\x01\x1b[{_O}m\x02›\x01\x1b[0m\x02"
    cont = "  \x01\x1b[2m\x02…\x01\x1b[0m\x02 "  # readline 프롬프트 ANSI 는 \x01..\x02 가드 필수
    return _input_continued(f"  {arrow} ", cont)


class _Dock:
    """클로드코드식 하단 상주 입력 독 (프레이야 명세 26-07-20).

    턴 진행 중에도 입력 프레임이 화면 하단에 상주하고 스트리밍 출력은 그 위로 삽입된다.
    pt 프롬프트와 같은 프레임(골드 캡·라운드 박스·상태줄)을 그려 턴 사이 시각 연속성을 만들고,
    실제 편집은 턴 종료 후 pt 가 같은 자리에서 이어받는다.

    하단 고정: mount 가 CPR 로 커서 행을 얻어 프레임을 처음부터 화면 마지막 HEIGHT 행에 놓는다
    (흐름이 위면 무스크롤 절대 배치, 겹치면 부족분만 스크롤, CPR 미응답이면 최하단 점프 폴백) —
    제출 직후 프레임이 본문 흐름 위치로 붙었다가 밀려 내려오는 점프를 없앤다.

    라이브 입력: 턴 중 리더 스레드가 stdin(cbreak)을 소유해 타이핑을 독 입력행에 즉시 표시한다
    (이스케이프·CPR 잔여는 스크럽 — 커널 버퍼 방치로 다음 프롬프트가 오염되는 것을 차단).
    턴 종료 시 run() 이 take_pending() 으로 초안을 회수해 pt 프롬프트에 프리필하고,
    트레일링 ⏎ 는 제출 의사로 보고 자동 제출한다.

    커서 계약: 유휴 시 입력행 캐럿 뒤 파킹 — 사용자가 보는 깜빡임이 곧 타이핑 지점이다.
    내부 소거 원점은 여전히 스페이서 행(_IN 행 위): write() 는 스페이서로 올라가 아래를 지우고
    출력을 삽입한 뒤 독을 다시 그린다 — 자연 스크롤이라 스크롤백이 보존된다 (DECSTBM 기각).
    리사이즈·CJK 랩으로 파킹이 틀어져도 다음 redraw 의 전체 소거가 복원한다.
    화면 쓰기는 전부 _lock 직렬화 (틱 스레드 vs 리더 스레드 vs 메인)."""

    HEIGHT = 6  # 스페이서 · 스피너 상태 · 박스 상단 · 입력행 · 박스 하단 · 상태줄
    _IN = 3  # 스페이서(소거 원점) → 입력행 거리

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._stop_reader = threading.Event()
        self._t: threading.Thread | None = None
        self._rt: threading.Thread | None = None
        self._label: str | None = None
        self._t0 = 0.0
        self._frame = 0
        self._pending = ""  # 턴 중 타이핑 초안 — take_pending() 으로 회수
        self.mounted = False

    def mount(self) -> None:
        import threading

        with self._lock:
            # 제출된 입력 박스는 pt 가 통째로 지운다(erase_when_done) — 여기선 독 프레임만 그린다.
            self.mounted = True
            rows = _term_rows()
            top = max(1, rows - self.HEIGHT + 1)
            cur = _cursor_row()
            if cur is None:  # CPR 미응답 터미널 — 최하단 점프 후 프레임 개행이 필요분을 자연 스크롤
                sys.stdout.write(f"\x1b[{rows};1H" + self._frame_str() + self._park())
            else:
                push = "\x1b[%d;1H%s" % (rows, "\n" * (cur - top)) if cur > top else ""
                sys.stdout.write(push + self._frame_abs(top) + self._park())
            sys.stdout.flush()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._tick, daemon=True)
        self._t.start()
        self._stop_reader = threading.Event()
        if sys.stdin.isatty():  # 라이브 입력 리더 — mount 의 CPR 소비가 끝난 뒤에만 stdin 소유
            self._rt = threading.Thread(target=self._read_keys, daemon=True)
            self._rt.start()

    def unmount(self) -> None:
        if not self.mounted:
            return
        self._stop_reader.set()
        if self._rt:
            self._rt.join(timeout=1)
            self._rt = None
        self._stop.set()
        if self._t:
            self._t.join(timeout=1)
            self._t = None
        with self._lock:
            self.mounted = False
            self._label = None
            sys.stdout.write(self._unpark() + "\x1b[0J")  # 스페이서부터 독 소거 — 커서는 다음 출력 자리
            sys.stdout.flush()

    def write(self, s: str) -> None:
        """완성 라인(들)을 독 위로 삽입. 미마운트면 stdout 직행 (테어다운 경계 잔여분)."""
        if not s:
            return
        with self._lock:
            if not self.mounted:
                sys.stdout.write(s)
                sys.stdout.flush()
                return
            # 소거→삽입→재드로우를 단일 write 로 원자화 — 라인버퍼 중간 flush 로 소거 상태가
            # 노출되는 플리커 창을 없앤다
            body = s if s.endswith("\n") else s + "\n"
            sys.stdout.write(self._unpark() + "\x1b[0J" + body + self._frame_str() + self._park())
            sys.stdout.flush()

    def status(self, label: str | None) -> None:
        """on_status 핸들러 — 독 상태 행에 스피너 라벨 표시 (None=해제). 경과초는 틱이 갱신."""
        import time

        with self._lock:
            if label != self._label:
                self._label, self._t0 = label, time.monotonic()
            if self.mounted:
                self._paint_status()
                sys.stdout.flush()

    def take_pending(self) -> tuple[str, bool]:
        """턴 중 독에 입력된 초안 회수 — (본문, 자동 제출 여부). 트레일링 ⏎ = 제출 의사."""
        with self._lock:
            text, self._pending = self._pending, ""
        submit = text.endswith("\n") and bool(text.strip())
        return text.strip("\n"), submit

    # — 라이브 입력 리더 (자체 스레드) —

    def _read_keys(self) -> None:
        import os
        import select

        fd = sys.stdin.fileno()
        carry = b""
        while not self._stop_reader.is_set():
            try:
                r, _, _ = select.select([fd], [], [], 0.05)
                if not r:
                    continue
                chunk = os.read(fd, 1024)
            except Exception:
                return
            if not chunk:
                return
            text, carry = _decode_keys(carry + chunk)
            if text:
                self._apply_keys(text)

    def _apply_keys(self, text: str) -> None:
        with self._lock:
            for ch in text:
                if ch in "\r\n":
                    self._pending += "\n"
                elif ch in "\x7f\x08":  # backspace
                    self._pending = self._pending[:-1]
                elif ch == "\x15":  # C-u — 초안 클리어
                    self._pending = ""
                elif ch == "\t" or ch.isprintable():
                    self._pending += " " if ch == "\t" else ch
            if self.mounted:
                self._paint_input()
                sys.stdout.flush()

    # — 내부 렌더 (호출측이 _lock 보유) —

    def _park(self) -> str:
        """스페이서 → 입력행 캐럿 뒤 — 깜빡이는 커서가 타이핑 지점에 놓인다."""
        return f"\x1b[{self._IN}B\x1b[{self._input_render()[1]}G"

    def _unpark(self) -> str:
        """입력행 파킹 → 스페이서 1열 (소거·삽입 원점)."""
        return f"\r\x1b[{self._IN}A"

    def _paint_input(self) -> None:
        # 입력행 파킹 상태에서 제자리 갱신 — 독 전체 redraw 없이 저비용
        line, col = self._input_render()
        sys.stdout.write("\r\x1b[2K" + line + f"\x1b[{col}G")

    def _tick(self) -> None:
        while not self._stop.wait(0.1):
            with self._lock:
                if not self.mounted:
                    return
                self._frame += 1
                self._paint_status()
                sys.stdout.flush()

    def _paint_status(self) -> None:
        # 입력행 파킹에서 상태 행(스페이서+1)로 올라가 제자리 갱신 후 캐럿 복귀
        up, down = self._IN - 1, self._IN - 1
        col = self._input_render()[1]
        sys.stdout.write(f"\x1b[{up}A\r\x1b[2K" + self._status_str() + f"\x1b[{down}B\x1b[{col}G")

    def _status_str(self) -> str:
        import time

        if not self._label:
            return ""
        fr = ui._FRAMES[self._frame % len(ui._FRAMES)]
        secs = time.monotonic() - self._t0
        tail = f" · {secs:.0f}s" if secs >= 1 else ""
        budget = max(10, ui.term_cols() - 8 - len(tail))  # 랩 방지 절단 (ui.spin 과 동일 규칙)
        # 단일 물리 행 불변식 — 상태 행 페인트는 고정 커서 산술(_paint_status)이라 개행이
        # 살아 나가면 박스 보더를 덮어쓴다. 호출측 클램프와 별개로 여기서 최종 방어.
        label = ui.oneline(self._label, budget)
        return f"  {ui.paint(theme.ansi(theme.ACCENT_BLUE), fr)} {label}{ui.dim(tail)}"

    def _statusline_str(self) -> str:
        ctx = _PT_CTX
        if not ctx:
            return ""
        segs = _status_segments(ctx["root"], ctx["rp"], _usage_of(ctx.get("heimdall")))
        parts: list[str] = []
        used = 2
        for txt, hx, bold in segs:  # 폭 초과 세그먼트는 통째로 드롭 — 랩이 독 높이를 깨지 않게
            need = (len(_STATUS_SEP) if parts else 0) + len(txt)
            if used + need > ui.term_cols() - 2:
                break
            used += need
            parts.append(_paint_seg(txt, hx, bold))
        return "  " + _STATUS_SEP.join(parts)

    def _input_render(self) -> tuple[str, int]:
        """입력행 문자열과 캐럿 열 — 초안이 있으면 골드 캐럿+본문(뒤쪽 우선), 비면 딤 플레이스홀더."""
        spine = "  " + ui.paint(theme.ansi(theme.HAIRLINE), _BOX["v"]) + " "
        if not self._pending:
            # 독 캐럿·플레이스홀더는 딤 — pt 활성 캐럿(골드)과 활성/비활성 시각 구분
            return spine + ui.dim("› " + t("ph_input")), 7
        disp = self._pending.replace("\n", "⏎")
        budget = max(10, ui.stream_width() - 10)
        while _disp_w(disp) > budget:  # 랩 방지 — 캐럿이 있는 뒤쪽을 남기고 앞을 자른다
            disp = disp[1:]
        return spine + ui.paint(_O, "› ") + disp, 7 + _disp_w(disp)

    def _frame_lines(self) -> list[str]:
        w = ui.stream_width()
        lines = ["", self._status_str(), _box_top_str(w), self._input_render()[0], _box_bottom_str(w)]
        return lines + [self._statusline_str()]

    def _frame_str(self) -> str:
        return "\n".join(self._frame_lines()) + f"\r\x1b[{self.HEIGHT - 1}A"  # 스페이서 행 1열 파킹

    def _frame_abs(self, top: int) -> str:
        """절대 배치판 _frame_str — 화면 마지막 HEIGHT 행에 스크롤 없이 그린다 (mount 전용).
        개행 대신 행별 절대 이동+소거라 본문 흐름과의 사이 여백을 건드리지 않는다."""
        lines = self._frame_lines()
        return "".join(f"\x1b[{top + i};1H\x1b[2K{line}" for i, line in enumerate(lines)) + f"\x1b[{top};1H"


def _cursor_row() -> int | None:
    """CPR(ESC[6n)로 현재 커서 행 조회 — 독 하단 배치·제출 블록 앵커의 기준점. 미응답·비 tty·
    termios 없는 플랫폼은 None (호출부가 폴백). ECHO·ICANON 을 잠깐 내려 응답만 소비한다 —
    Enter 직후 ~100ms 창이라 선타이핑 유실 위험은 실질 0."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    try:
        import os
        import re
        import select
        import termios
        import time

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[3] &= ~(termios.ECHO | termios.ICANON)  # 응답이 화면에 에코되거나 개행 대기로 막히지 않게
        new[6][termios.VMIN] = 0
        new[6][termios.VTIME] = 0
        try:
            termios.tcsetattr(fd, termios.TCSANOW, new)
            sys.stdout.write("\x1b[6n")
            sys.stdout.flush()
            buf = ""
            deadline = time.monotonic() + 0.1
            while (left := deadline - time.monotonic()) > 0:
                r, _, _ = select.select([fd], [], [], left)
                if not r:
                    break
                buf += os.read(fd, 64).decode("ascii", "ignore")
                m = re.search(r"\x1b\[(\d+);\d+R", buf)
                if m:
                    return int(m.group(1))
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, old)
    except Exception:
        return None
    return None


def _echo_off():
    """턴 진행 중 stdin cbreak 컨텍스트 — 에코 차단 + 즉시 읽기(ICANON 해제). 눌린 키는 독의
    라이브 입력 리더가 소비해 입력행에 표시하고, 턴 종료 시 pt 프롬프트에 프리필된다.
    ISIG 는 유지 — Ctrl-C 턴 중단 계약 불변. termios 없는 플랫폼·non-tty 는 no-op."""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        try:
            import termios

            fd = sys.stdin.fileno()
            if not sys.stdin.isatty():
                raise OSError("not a tty")
            old = termios.tcgetattr(fd)
            new = termios.tcgetattr(fd)
            new[3] &= ~(termios.ECHO | termios.ICANON)
            new[6][termios.VMIN] = 1
            new[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, new)
        except Exception:
            yield
            return
        try:
            yield
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, old)

    return _cm()


def _cancel_on_sigint(heimdall):
    """Turn Ctrl-C into cooperative tree cancellation so child sessions cannot outlive the UI."""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        try:
            import signal

            previous = signal.getsignal(signal.SIGINT)

            def cancel(sig, frame):
                if getattr(heimdall, "cancel_event", None) is not None and heimdall.cancel_event.is_set():
                    signal.default_int_handler(sig, frame)  # second Ctrl-C = hard interrupt
                heimdall.cancel()

            signal.signal(signal.SIGINT, cancel)
        except Exception:
            yield
            return
        try:
            yield
        finally:
            signal.signal(signal.SIGINT, previous)

    return _cm()


class _Reconfigure(Exception):
    """provider set / trinity 배치 변경 — 세션(Heimdall) 재생성 신호."""

    def __init__(self, rp, msg: str | None = None):
        self.rp, self.msg = rp, msg


def _cmd_trinity(cmd: str, root: str, rp) -> None:
    """/trinity — 역할 배치와 Dual Thinker 세션·프로젝트 모드."""
    from ..providers import PROVIDERS, resolve_trinity, save_config_section

    args = cmd.split()[1:]
    if args[:1] == ["models"]:
        from ..commands.role import role_model_state

        for host, roles in role_model_state(root).items():
            sys.stdout.write(f"  {ui.bold(host)}\n")
            for role, selected in roles.items():
                if host == "native":
                    value = f"{selected['provider']}:{selected['model']}"
                else:
                    value = str(selected["model"])
                    if selected.get("effort"):
                        value += f" · effort={selected['effort']}"
                sys.stdout.write(f"    {ui.paint(_O, role.ljust(12))} {value}\n")
        return

    if args[:1] == ["model"]:
        from ..commands.role import MODEL_HOSTS, configure_role_model, role_model_state

        values = args[1:]
        if not values:
            from ..templates.agent_models import AGENT_MODEL_DEFAULTS
            from .onboard import can_prompt

            if not can_prompt():
                sys.stdout.write(f"  {ui.dim(t('trinity_model_usage'))}\n")
                return
            from ..picker import Option, available, pick

            try:
                if available():  # 인터랙티브 패널 — host→role→model 연계 창 (번호 입력은 폴백)
                    picked = pick(t("pick_host"), [Option(n, n) for n in MODEL_HOSTS])
                    if picked is None:
                        raise EOFError
                    host = picked
                    if host == "native":
                        _cmd_trinity("/trinity set", root, rp)
                        return
                    state = role_model_state(root)[host]
                    roles = tuple(AGENT_MODEL_DEFAULTS[host])
                    picked = pick(t("pick_role"), [Option(n, n, detail=str(state[n]["model"])) for n in roles])
                    if picked is None:
                        raise EOFError
                    role = picked
                    current = str(state[role]["model"])
                    recommended = AGENT_MODEL_DEFAULTS[host][role]["model"]
                    models = list(
                        dict.fromkeys(
                            [current, recommended, *(item["model"] for item in AGENT_MODEL_DEFAULTS[host].values())]
                        )
                    )
                    mopts = [Option("", t("model_override_clear"))]
                    for model_id in models:
                        tags = []
                        if model_id == current:
                            tags.append(t("current_tag"))
                        if model_id == recommended:
                            tags.append(t("recommended_tag"))
                        mopts.append(Option(model_id, model_id, detail=", ".join(tags), current=model_id == current))
                    sel = pick(
                        t("pick_model"), mopts, default=models.index(current) + 1, manual_hint=t("picker_manual_model")
                    )
                    if sel is None:
                        raise EOFError
                    values = ["reset", host, role] if sel == "" else [host, role, sel]
                else:
                    sys.stdout.write(f"\n  {ui.bold(t('pick_host'))}\n")
                    for i, name in enumerate(MODEL_HOSTS, 1):
                        sys.stdout.write(f"    {ui.paint(_O, str(i))} {name}\n")
                    choice = input("  " + t("number") + " [1]: ").strip() or "1"
                    if choice.lower() == "q":
                        raise EOFError
                    host = MODEL_HOSTS[int(choice) - 1]
                    if host == "native":
                        _cmd_trinity("/trinity set", root, rp)
                        return

                    state = role_model_state(root)[host]
                    roles = tuple(AGENT_MODEL_DEFAULTS[host])
                    sys.stdout.write(f"\n  {ui.bold(t('pick_role'))}\n")
                    for i, name in enumerate(roles, 1):
                        sys.stdout.write(f"    {ui.paint(_O, str(i))} {name} {ui.dim('· ' + state[name]['model'])}\n")
                    choice = input("  " + t("number") + " [1]: ").strip() or "1"
                    if choice.lower() == "q":
                        raise EOFError
                    role = roles[int(choice) - 1]

                    current = str(state[role]["model"])
                    recommended = AGENT_MODEL_DEFAULTS[host][role]["model"]
                    models = list(
                        dict.fromkeys(
                            [current, recommended, *(item["model"] for item in AGENT_MODEL_DEFAULTS[host].values())]
                        )
                    )
                    sys.stdout.write(f"\n  {ui.bold(t('pick_model'))}\n")
                    sys.stdout.write(f"    {ui.paint(_O, '0')} {t('model_override_clear')}\n")
                    for i, model_id in enumerate(models, 1):
                        tags = []
                        if model_id == current:
                            tags.append(t("current_tag"))
                        if model_id == recommended:
                            tags.append(t("recommended_tag"))
                        suffix = ui.dim(" · " + ", ".join(tags)) if tags else ""
                        sys.stdout.write(f"    {ui.paint(_O, str(i))} {model_id}{suffix}\n")
                    sys.stdout.write(f"    {ui.dim('m ' + t('model_id_prompt') + ' · q cancel')}\n")
                    default = str(models.index(current) + 1)
                    choice = input("  " + t("number") + f" [{default}]: ").strip() or default
                    if choice.lower() == "q":
                        raise EOFError
                    if choice == "0":
                        values = ["reset", host, role]
                    elif choice.lower() == "m":
                        values = [host, role, input("  " + t("model_id_prompt") + ": ").strip()]
                    else:
                        values = [host, role, models[int(choice) - 1]]
            except ValueError, IndexError, EOFError, KeyboardInterrupt:
                sys.stdout.write(f"  {t('cancelled')}\n")
                return

        reset = values[:1] == ["reset"]
        if reset:
            values = values[1:]
        if len(values) < 2 or (not reset and len(values) < 3) or len(values) > (2 if reset else 4):
            sys.stdout.write(f"  {ui.dim(t('trinity_model_usage'))}\n")
            return
        host, role = values[:2]
        model = None if reset else values[2]
        extra = None if reset or len(values) < 4 else values[3]
        try:
            result = configure_role_model(
                root,
                host,
                role,
                model=model,
                effort=extra if host != "native" else None,
                provider=extra if host == "native" else None,
                reset=reset,
            )
        except ValueError as exc:
            sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {exc}\n")
            return
        effective = result["effective"]
        value = f"{effective.get('provider')}:" if host == "native" else ""
        value += str(effective["model"])
        if effective.get("effort"):
            value += f" · effort={effective['effort']}"
        msg = t("trinity_model_reset" if reset else "trinity_model_saved", host=host, role=role, value=value)
        if host == "native":
            raise _Reconfigure(rp, msg)
        sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {msg}\n")
        return

    if args[:1] == ["dual"]:
        hd = _PT_CTX.get("heimdall")
        if hd is None:
            sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('connect_needed')}\n")
            return
        if len(args) == 1:
            state = "on" if hd.dual_mode else "off"
            a, b = hd.dual_thinker_labels()
            sys.stdout.write(f"  {ui.paint(_O, 'dual'.ljust(9))} {state} {ui.dim(f'· {a} ⊕ {b}')}\n")
            return
        persistent = args[1:2] == ["default"]
        mode_arg = args[2] if persistent and len(args) == 3 else (args[1] if len(args) == 2 else "")
        if mode_arg not in ("on", "off"):
            sys.stdout.write(f"  {ui.dim(t('trinity_dual_usage'))}\n")
            return
        if mode_arg == "on":
            a, b = hd.dual_thinker_labels()
            if a == b:
                sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('trinity_dual_same', model=a)}\n")
                return
        hd.dual_mode = mode_arg == "on"
        if persistent:
            save_config_section(root, "trinity.mode", {"dual": hd.dual_mode})
        key = "trinity_dual_persisted" if persistent else "trinity_dual_set"
        sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {t(key, mode=mode_arg)}\n")
        return

    if args[:1] == ["set"]:
        from ..picker import Option, available, pick
        from .onboard import can_prompt

        if not can_prompt():
            return
        roles = ("thinker", "thinker_alt", "worker", "verifier")
        names = list(PROVIDERS)
        try:
            if available():  # 인터랙티브 패널 — 역할→provider 연계 창 (번호 입력은 폴백)
                picked_role = pick(t("pick_role"), [Option(r, r) for r in roles], default=1)
                if picked_role is None:
                    sys.stdout.write(f"  {t('cancelled')}\n")
                    return
                role = picked_role
                popts = [Option("", t("placement_clear"))] + [
                    Option(n, PROVIDERS[n].display, detail=PROVIDERS[n].default_model or t("needs_base_url"))
                    for n in names
                ]
                sel = pick(t("pick_provider"), popts)
                if sel is None:
                    sys.stdout.write(f"  {t('cancelled')}\n")
                    return
                if not sel:
                    save_config_section(root, f"trinity.{role}", None)
                    raise _Reconfigure(rp, t("placement_cleared"))
                name = sel
            else:
                sys.stdout.write(f"\n  {ui.bold(t('pick_role'))}\n")
                for i, r in enumerate(roles, 1):
                    sys.stdout.write(f"    {ui.paint(_O, str(i))} {r}\n")
                role = roles[int(input("  " + t("number") + " [2]: ").strip() or "2") - 1]
                sys.stdout.write(f"\n  {ui.bold(t('pick_provider'))}\n")
                sys.stdout.write(f"    {ui.paint(_O, '0')} {t('placement_clear')}\n")
                for i, n in enumerate(names, 1):
                    p = PROVIDERS[n]
                    sys.stdout.write(
                        f"    {ui.paint(_O, str(i))} {p.display} {ui.dim('· ' + (p.default_model or t('needs_base_url')))}\n"
                    )
                idx = int(input("  " + t("number") + " [0]: ").strip() or "0")
                if idx == 0:
                    save_config_section(root, f"trinity.{role}", None)
                    raise _Reconfigure(rp, t("placement_cleared"))
                name = names[idx - 1]
            p = PROVIDERS[name]
            vals: dict = {"provider": name}
            if p.fallback_models or p.api_mode == "openai_compat":
                from ..providers import resolve
                from .onboard import _pick_model

                selected = _pick_model(resolve(root, provider=name))
                if not selected:
                    sys.stdout.write(f"  {t('cancelled')}\n")
                    return
                model = selected
            else:
                model = input(f"  model [{p.default_model or '?'}]: ").strip() or p.default_model
            if model:
                vals["model"] = model
            if p.api_mode == "openai_compat" and not p.base_url:
                bu = input("  base_url: ").strip()
                if bu:
                    vals["base_url"] = bu
        except ValueError, IndexError, EOFError, KeyboardInterrupt:
            sys.stdout.write(f"  {t('cancelled')}\n")
            return
        save_config_section(root, f"trinity.{role}", vals)
        raise _Reconfigure(rp, t("placement_saved"))

    roles = ("thinker", "thinker_alt", "worker", "verifier")
    for role, r in resolve_trinity(root, rp, roles).items():
        warn = f"  {ui.paint(ui._WARN, '⚠ ' + '; '.join(r.missing))}" if r.missing else ""
        tag = f" {ui.dim(t('default_tag'))}" if r is rp else ""
        sys.stdout.write(f"  {ui.paint(_O, role.ljust(9))} {r.profile.name}:{r.model}{tag}{warn}\n")
    sys.stdout.write(f"  {ui.dim(t('trinity_hint'))}\n")


def _cmd_bridge(cmd: str, root: str) -> None:
    """/bridge — 도구별 CLI 브릿지 플래그 표시/토글 ([bridge], 기본 전부 off)."""
    from ..providers import BRIDGE_TOOLS, bridge_flags, project_section, save_config_section

    args = cmd.split()[1:]
    if len(args) == 2 and args[0] in BRIDGE_TOOLS and args[1] in ("on", "off"):
        cur = project_section(root, "bridge")
        cur[args[0]] = args[1] == "on"
        save_config_section(root, "bridge", cur)
        sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {t('bridge_set', tool=args[0], v=args[1])}\n")
        return
    for tool, on in bridge_flags(root).items():
        mark = ui.paint(ui._OK, "on") if on else ui.dim("off")
        sys.stdout.write(f"  {ui.paint(_O, tool.ljust(12))} {mark}\n")
    sys.stdout.write(f"  {ui.dim(t('bridge_usage'))}\n")


def _cmd_lagom(cmd: str, root: str, rp) -> None:
    """/lagom — 모드 표시. '/lagom <mode>' 세션 전환, '/lagom default <mode>' 영속.
    전환은 _Reconfigure 로 Heimdall 을 재생성한다 — 역할 프롬프트의 lagom 렌더가 새 모드로 갱신."""
    from ..lagom import MODES, clear_state, current_mode, normalize, read_state, write_state

    args = cmd.split()[1:]
    if not args:
        cur, st = current_mode(root), read_state(root)
        tag = t("lagom_session") if st else t("lagom_default")
        sys.stdout.write(f"  {ui.paint(_O, 'lagom'.ljust(9))} {cur} {ui.dim('(' + tag + ')')}\n")
        for line in t("lagom_what").split("\n"):  # 라곰이 뭔지 — 한 번에 이해되게
            sys.stdout.write(f"  {' ' * 9} {ui.dim(line)}\n")
        for m in MODES:  # off·lite·full 각 모드가 뭘 하는지, 현재 모드는 표식
            mark = ui.paint(ui._OK, "▸") if m == cur else " "
            name = ui.paint(_O, m.ljust(6)) if m == cur else ui.dim(m.ljust(6))
            sys.stdout.write(f"  {mark} {name} {ui.dim(t('lagom_mode_' + m))}\n")
        sys.stdout.write(f"  {ui.dim(t('lagom_usage'))}\n")
        return
    if args[0] == "stats":  # 로컬 집계만, 무텔레메트리. honest numbers: 합산 지출이지 output 단독 아님
        hd = _PT_CTX.get("heimdall")
        cur = current_mode(root)
        tok = f"{hd.total_tokens / 1000:.1f}k" if hd and hd.total_tokens else "0"
        sys.stdout.write(
            f"  {ui.paint(_O, 'lagom'.ljust(9))} {cur} {ui.dim('· ' + t('lagom_stats_tokens', tok=tok))}\n"
        )
        sys.stdout.write(f"  {ui.dim(t('lagom_stats_note'))}\n")
        return
    is_default = args[0] == "default"
    mode = normalize(args[1] if is_default and len(args) > 1 else args[0])
    if mode is None:
        sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('lagom_usage')}\n")
        return
    if is_default:
        from ..providers import save_config_section

        save_config_section(root, "lagom", {"mode": mode})
        clear_state(root)  # 상태파일 제거 → 새 기본값이 즉시 유효 (세션 오버라이드 해소)
        raise _Reconfigure(rp, t("lagom_persisted", mode=mode))
    write_state(root, mode)
    raise _Reconfigure(rp, t("lagom_set", mode=mode))


def slash(cmd: str, root: str, rp) -> bool:
    """슬래시 커맨드 처리. True = 처리됨(루프 계속), 종료/재설정은 예외로 신호."""
    c = cmd.split()[0]
    if c in ("/exit", "/quit"):
        raise EOFError
    if c == "/skills":
        from ..commands.skills import render_skills
        from ..skill_registry import invocable_skills

        rows = [row for row in invocable_skills(root) if row["invocation"] == "user"]
        if rows:
            rows = [{**row, "name": "/" + row["name"]} for row in rows]
            render_skills(rows, "User skills")
        else:
            sys.stdout.write(f"  {ui.dim('no user-invoked skills')}\n")
    elif c == "/help":
        sys.stdout.write("\n")
        for k, v in _help_items():
            sys.stdout.write(f"  {ui.paint(_O, k.ljust(14))} {ui.dim(v)}\n")
        sys.stdout.write(f"  {ui.paint(_O, '!<cmd>'.ljust(14))} {ui.dim(t('h_bash'))}\n")
        sys.stdout.write(f"  {ui.dim(t('help_footer'))}\n\n")
    elif c == "/lang":
        from ..i18n import save_lang
        from ..i18n import t as _t

        arg = cmd.split()[1:2]
        if arg and save_lang(arg[0], root):
            sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {ui.dim(_t('lang_set', lang=arg[0]))}\n")
        else:
            sys.stdout.write(f"  {ui.dim(_t('lang_usage'))}\n")
    elif c == "/update":
        from ..commands.update import run_update

        run_update(cmd.split()[1:], restart_hint=True)
    elif c == "/clear":
        sys.stdout.write("\033[2J\033[H")
        banner(rp)
    elif c == "/provider":
        if cmd.split()[1:2] == ["set"]:
            from .onboard import can_prompt, onboard

            if can_prompt():
                new = onboard(root)
                if new is not None:
                    raise _Reconfigure(new)  # repl.run 이 세션 재생성
            return True
        if rp.missing:  # 미연결 — 기본 프로파일(Claude)을 연결된 것처럼 보여주지 않는다
            sys.stdout.write(
                f"  {ui.paint(ui._WARN, '⚠')} {t('not_connected')} {ui.dim('· ' + '; '.join(rp.missing))}\n"
            )
            return True
        src = rp.key_source or rp.source
        sys.stdout.write(f"  {ui.paint(_O, rp.profile.display)} {ui.dim('·')} {rp.model} {ui.dim('(' + src + ')')}\n")
    elif c == "/model":
        from .onboard import can_prompt, select_model

        if can_prompt():
            new = select_model(root, rp)
            if new is not None:
                raise _Reconfigure(new)
        else:
            sys.stdout.write(f"  {ui.paint(_O, rp.profile.display)} {ui.dim('·')} {rp.model}\n")
    elif c == "/trinity":
        _cmd_trinity(cmd, root, rp)
    elif c == "/bridge":
        _cmd_bridge(cmd, root)
    elif c == "/lagom":
        _cmd_lagom(cmd, root, rp)
    elif c == "/quest":
        try:
            out = ql(root, "state").stdout.strip()
            sys.stdout.write(f"  {ui.dim(out or t('no_quest'))}\n")
        except Exception:
            sys.stdout.write(f"  {ui.dim(t('no_quest'))}\n")
    elif c == "/sessions":
        hd = _PT_CTX.get("heimdall")
        if hd is None:
            sys.stdout.write(f"  {ui.dim(t('no_sessions'))}\n")
            return True
        if cmd.split()[1:2] == ["stop"]:
            hd.cancel()
            sys.stdout.write(f"  {ui.paint(ui._WARN, '■')} {t('sessions_stopping')}\n")
            return True
        rows = hd.session_snapshot()
        if not rows:
            sys.stdout.write(f"  {ui.dim(t('no_sessions'))}\n")
            return True
        for row in rows[-12:]:
            mark = "●" if row["state"] == "running" else "○"
            detail = row["status"] or row["state"]
            sys.stdout.write(
                f"  {ui.paint(_O, mark)} {row['id'].ljust(18)} {ui.dim(detail + ' · ' + str(row['elapsed_s']) + 's')}\n"
            )
    else:
        from difflib import get_close_matches

        match = get_close_matches(c, _COMMAND_HELP, n=1, cutoff=0.6)
        key = "unknown_cmd_suggest" if match else "unknown_cmd"
        sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t(key, c=c, suggestion=match[0] if match else '')}\n")
    return True


def _new_heimdall(root: str, rp, emit, status=None):
    from ..providers import project_section
    from .heimdall import Heimdall

    hd = Heimdall(rp, root, on_text=emit, on_status=status)
    hd.dual_mode = project_section(root, "trinity.mode").get("dual") is True
    return hd


class _Spinner:
    """on_status 핸들러 — 침묵 구간(thinking·툴 실행)에 라이브 스피너. 라벨 None 이면 해제."""

    def __init__(self) -> None:
        self._cur: ui.spin | None = None
        self._label: str | None = None

    def __call__(self, label: str | None) -> None:
        if label == self._label:  # 동일 상태 반복 신호(스트림 청크마다 None 등) — 무시
            return
        if self._cur:
            self._cur.__exit__(None, None, None)
            self._cur = None
        if label:
            self._cur = ui.spin(label)
            self._cur.__enter__()
        self._label = label


_MD_BOLD = None  # re 모듈 lazy — 아래 _Render 에서 컴파일


class _Render:
    """스트리밍 md-lite 렌더 — 응답 본문을 2칸 들여쓰고 라인 단위로 가볍게 스타일.

    완성 라인: **볼드**·`코드`(시안)·헤더(골드)·불릿(•) 적용. 오래 안 끝나는 라인(긴 문단)은
    스타일 포기하고 즉시 플러시 — 라이브함이 스타일보다 우선. 세션 메타 라인('  │ …' 활동 스레드 등,
    이미 들여쓰기됨)은 그대로 통과하고, 미종결 산문에 접착되지 않게 write() 가 먼저 닫는다."""

    FLUSH_AT = 160

    def __init__(self) -> None:
        import re

        self._re = re
        self.buf = ""
        self.dirty = False  # 현재 라인을 이미 raw 로 흘려보냄 — 완성 시 스타일 생략
        self._sink = None  # 독 모드 싱크(dock.write) — 완성 라인만 전달. None=stdout 직행

    def attach(self, sink) -> None:
        """독 모드 전환 — 잔여 버퍼를 현 싱크로 먼저 방출하고 교체. 독 모드는 완성 라인 단위로만
        흘려보낸다(부분 라인 raw 스트림은 독 redraw 와 충돌). 긴 문단은 폭 경계 소프트랩으로
        라인을 확정 — 터미널 자연 랩과 같은 자리라 시각 동일, 라이브함 유지."""
        self.finish()
        self._sink = sink

    def _sink_write(self, s: str) -> None:
        sink = self._sink
        if sink is None:
            return
        self.buf += s
        lines: list[str] = []
        budget = max(24, ui.stream_width() - 4)
        while True:
            if "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                lines.append(self._line(line))
                continue
            if len(self.buf) >= budget:  # 소프트랩 — 마지막 공백에서 자르고 라인 확정
                cut = self.buf.rfind(" ", 0, budget)
                cut = cut if cut > 0 else budget
                line, self.buf = self.buf[:cut], self.buf[cut:].lstrip(" ")
                lines.append(self._line(line))
                continue
            break
        if lines:
            sink("\n".join(lines) + "\n")

    def _line(self, line: str) -> str:
        """싱크 모드 라인 스타일 — _emit_line 과 같은 규칙, 문자열 반환."""
        if line.startswith("  ") or not line.strip():
            return line
        return "  " + self._style(line)

    def write(self, s: str) -> None:
        if self._sink is not None:
            self._sink_write(s)
            return
        # 활동 라인(완성된 메타 라인 — 앞 2칸 들여쓰기)이 미종결 산문에 접착되는 것을 막는다:
        # 두 생산자(모델 산문 · 툴/전이 라인)가 한 싱크를 공유하므로, 메타 라인이 오면 대기 산문을 먼저 닫는다.
        if "\n" in s and s.lstrip("\n").startswith("  "):
            if self.dirty:  # 산문이 이미 raw 로 흘러나간 상태 — 개행으로 닫는다
                sys.stdout.write("\n")
                sys.stdout.flush()
                self.dirty = False
            elif self.buf:  # 버퍼에 미종결 산문 — 자기 라인으로 방출
                self._emit_line(self.buf)
                self.buf = ""
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self._emit_line(line)
        if len(self.buf) >= self.FLUSH_AT:
            if not self.dirty:
                sys.stdout.write("  ")
                self.dirty = True
            sys.stdout.write(self.buf)
            sys.stdout.flush()
            self.buf = ""

    def finish(self) -> None:
        if self.buf:
            if self._sink is not None:
                self._sink(self._line(self.buf) + "\n")
            else:
                self._emit_line(self.buf)
            self.buf = ""

    def _emit_line(self, line: str) -> None:
        if self.dirty:  # 이미 raw 로 나간 라인의 잔여
            sys.stdout.write(line + "\n")
            self.dirty = False
        elif line.startswith("  ") or not line.strip():  # 메타 라인·공백 — 무가공
            sys.stdout.write(line + "\n")
        else:
            sys.stdout.write("  " + self._style(line) + "\n")
        sys.stdout.flush()

    def _style(self, line: str) -> str:
        re = self._re
        if not ui._COLOR:
            return line
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:  # 헤더 — 골드 볼드
            return ui.bold(ui.paint(_O, m.group(2)))
        line = re.sub(r"\*\*(.+?)\*\*", lambda x: ui.bold(x.group(1)), line)
        line = re.sub(r"`([^`]+)`", lambda x: ui.paint(theme.ansi(theme.ACCENT_CYAN), x.group(1)), line)
        line = re.sub(r"^(\s*)[-*]\s+", lambda x: x.group(1) + ui.paint(_O, "•") + " ", line)
        return line


def _bye() -> int:
    sys.stdout.write(f"\n  {ui.dim(t('bye'))}\n")
    return 0


def _run_bang(root: str, cmd: str) -> None:
    """!cmd — 관찰 명령만 직접 실행. 변경은 일반 요청의 Trinity 경로로 보낸다."""
    from ..hooks.readonly_guard import is_readonly_bash_safe
    from . import tools as T

    if not is_readonly_bash_safe(cmd, root):
        sys.stdout.write(
            f"  {ui.paint(ui._WARN, '⚠')} ! 명령은 읽기 전용만 허용됩니다. 변경 작업은 일반 요청으로 실행하세요.\n"
        )
        return

    try:
        out, code = T.run_bash(root, {"command": cmd})
        sys.stdout.write(f"  {ui.dim('$ ' + cmd)}\n{out}\n")
        if code:
            sys.stdout.write(f"  {ui.dim('exit ' + str(code))}\n")
    except T.ToolError as e:
        sys.stdout.write(f"  {ui.paint(ui._FAIL, '⚠')} {e}\n")


def run(root: str, rp, cont: bool = False) -> int:
    """터미널을 바로 켠다 — 키 없어도 진입. 첫 요청 시 provider 미설정이면 온보딩."""
    render = _Render()
    spinner = _Spinner()
    dock: _Dock | None = None

    def status(label: str | None) -> None:
        # 턴 중(독 상주)엔 독 상태 행, 그 외(readline 폴백·독 밖)엔 라인 스피너
        if dock is not None and dock.mounted:
            dock.status(label)
        else:
            spinner(label)

    def emit(s: str) -> None:
        render.write(s)

    # '/' 라이브 완성 메뉴 (prompt_toolkit). 실패 시 readline 폴백 — 히스토리 파일 충돌 방지 위해
    # 한쪽만 배선한다 (readline atexit 가 pt 포맷 히스토리를 덮어쓰는 것 방지).
    global _PT
    if _PT is None and ui._COLOR:
        try:
            _PT = _pt_session()
        except Exception:
            _PT = False
    if not _PT:
        _setup_readline()  # Tab 자동완성 + 화살표 히스토리
    if _PT and ui._COLOR and sys.stdout.isatty():
        dock = _Dock()  # 하단 상주 입력 독 — pt 경로 전용 (폴백·비 tty 는 기존 스피너 흐름)
        sys.stdout.write("\033[2J\033[H")  # 클린 스타트 — 이전 셸 화면 위가 아니라 아스가드만
    banner(rp)
    heimdall = None if rp.missing else _new_heimdall(root, rp, emit, status)
    # provider 미설정 안내는 status line(⚠ not connected)이 대신 표현 — 별도 줄 없음
    if cont and heimdall is not None:
        n = heimdall.restore_history()
        if n:
            sys.stdout.write(f"  {ui.dim(t('continue_restored', n=n))}\n")

    while True:
        _PT_CTX.update(root=root, rp=rp, heimdall=heimdall)  # toolbar + /lagom stats 공용 세션 상태
        if _PT:  # 상태줄은 bottom_toolbar(입력창 아래)가 표시 — cursor-agent 식
            # 하단 고정은 _pt_session 의 바닥 정렬 필러가 담당 (커서 점프 불요 — CPR 기반)
            sys.stdout.write("\n")
        else:
            sys.stdout.write("\n" + statusline(root, rp, _usage_of(heimdall)) + "\n")
        try:
            # 직전 턴 중 독에 타이핑된 초안 회수 — 프리필하고, 트레일링 ⏎ 는 즉시 제출
            pending, auto = dock.take_pending() if dock is not None else ("", False)
            req = (prompt(pending, auto) if pending else prompt()).strip()
        except EOFError, KeyboardInterrupt:
            return _bye()
        if not req:
            continue
        if _PT:  # 지워진 입력 프레임을 대신하는 사용자 메시지 표기 (폴백 경로는 input 에코가 남는다)
            if dock is not None:
                # 제출 블록(에코+여백)을 독 바로 위로 앵커 — 질문·응답·독이 하단에 응집한다.
                # 흐름이 얕을 때(첫 턴 등)만 하향 점프 (상향 점프는 본문 덮어쓰기라 금지),
                # 이후 스트리밍 스크롤에도 질문이 응답 직상에 남는다. CPR 미응답이면 현 위치 유지.
                cur = _cursor_row()
                anchor = max(1, _term_rows() - _Dock.HEIGHT - 1)
                if cur is not None and cur < anchor:
                    sys.stdout.write(f"\x1b[{anchor};1H\x1b[0J")
            sys.stdout.write(_echo_submitted(req) + "\n")
        if req == "/new":  # 컨텍스트·화면 리셋 (rp/heimdall 재생성 필요 — slash 는 rp 만 받음)
            sys.stdout.write("\033[2J\033[H")
            heimdall = None if rp.missing else _new_heimdall(root, rp, emit, status)
            banner(rp)
            continue
        if req.startswith("!"):  # bash 직접 실행
            _run_bang(root, req[1:].strip())
            continue
        if req.startswith("/"):
            from ..skill_registry import invoked_skill_prompt

            invoked = None if req.split()[0] in _COMMAND_HELP else invoked_skill_prompt(root, req)
            if invoked is None:
                try:
                    slash(req, root, rp)
                except EOFError:
                    return _bye()
                except _Reconfigure as r:  # /provider set · /trinity set — 세션 재생성
                    rp = r.rp
                    heimdall = None if rp.missing else _new_heimdall(root, rp, emit, status)
                    msg = r.msg or f"{rp.profile.display} · {rp.model} 로 전환"
                    sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {msg}\n")
                continue
            req = invoked

        # 키 미설정 — 온보딩을 강제로 열지 않고 안내만 (연결은 /provider set 으로 명시적으로)
        if heimdall is None:
            sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('connect_needed')}\n")
            continue

        try:
            import time as _time
            from contextlib import ExitStack

            ev = getattr(heimdall, "cancel_event", None)  # 제출측 clear — handle() 은 clear 하지 않는다
            if ev is not None:
                ev.clear()
            sys.stdout.write("\n")  # 제출 에코 ↔ 응답 블록 시각 분리 — 스트리밍 첫 줄이 에코에 접착되지 않게
            t0 = _time.monotonic()
            with ExitStack() as stack:  # 독 수명 = handle 구간 — 예외·중단에도 반드시 내려간다
                stack.enter_context(_cancel_on_sigint(heimdall))
                if dock is not None:
                    stack.enter_context(_echo_off())
                    stack.callback(dock.unmount)
                    stack.callback(render.attach, None)  # LIFO — 싱크 분리(잔여 방출) 후 독 해체
                    render.attach(dock.write)
                    dock.mount()
                out = heimdall.handle(req)
                render.finish()
            if out:
                sys.stdout.write(f"\n{out}\n")
            # 턴 요약 — '✓ done · model · 7.0s' 한 줄
            sys.stdout.write(f"\n  {ui.dim(f'✓ done · {rp.model} · {_time.monotonic() - t0:.1f}s')}\n")
        except KeyboardInterrupt:
            sys.stdout.write(f"\n  {ui.dim(t('turn_kept'))}\n")
        except Exception as e:
            sys.stdout.write(f"\n  {ui.paint(ui._FAIL, '⚠')} 세션 오류: {e}\n")
        finally:
            status(None)  # 스피너 누수 방지 (인터럽트·예외 경로)
            render.finish()
