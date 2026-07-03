"""네이티브 REPL 렌더 (CUS-138) — 브랜드 로고 + 간결 UX.

4개 레퍼런스의 장점만 섞는다:
  Claude Code — 세션 헤더(provider·model), 슬래시 커맨드, tool-use 축약 한 줄
  Codex       — 미니멀·조용한 기본, 저소음
  hermes      — provider·model 상태 라인
  opencode    — 정렬된 컬러, 역할/툴 심볼

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
    if "kitty" in term or "ghostty" in term or os.environ.get("KITTY_WINDOW_ID") \
            or os.environ.get("GHOSTTY_RESOURCES_DIR") or tp in ("ghostty", "Ghostty"):
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
            piece, off = b64[off:off + 4096], off + 4096
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
    width = shutil.get_terminal_size((80, 20)).columns
    bar = ui.paint(_O, "▌")

    # 로고: 다크+이미지 터미널 → PNG, 아니면 braille lockup(배경 밝기별 그라디언트) / 축약
    if not (ui._COLOR and _image_logo()):
        grad = _LOGO_GRAD_LIGHT if is_light_bg() else _LOGO_GRAD
        if width >= 70:
            sys.stdout.write("\n")
            for i, line in enumerate(_LOGO.split("\n")):
                col = grad[i] if i < len(grad) else grad[-1]
                sys.stdout.write("  " + ui.paint(col, line) + "\n")
        else:
            sys.stdout.write("\n  " + ui.paint(_O, _LOGO_SLIM) + "\n")

    # hermes 스타일 — welcome + tip + 구분선 rule (모델·경로·git 은 하단 status line 으로)
    rule = ui.paint(_O, "─" * min(width - 4, 60))
    sys.stdout.write(
        f"\n  {ui.bold(t('welcome'))} {ui.dim(t('welcome_hint'))}\n"
        f"  {ui.paint(_O, '✦')} {ui.dim(t('tip'))}\n"
        f"  {rule}\n")


def _git_status(root: str) -> str:
    """현재 브랜치(+dirty '*'). git repo 아니면 빈 문자열."""
    import subprocess
    try:
        b = subprocess.run(["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True, timeout=3)
        if b.returncode != 0:
            return ""
        branch = b.stdout.strip()
        d = subprocess.run(["git", "-C", root, "status", "--porcelain"],
                          capture_output=True, text=True, timeout=3)
        return branch + ("*" if d.stdout.strip() else "")
    except Exception:
        return ""


def statusline(root: str, rp, usage: dict | None = None) -> str:
    """claude-code 식 상태줄 — 모델 · 디렉토리 · git · 사용량. 미연결이면 명확히 안내."""
    import os
    home = os.path.expanduser("~")
    cwd = root.replace(home, "~", 1) if root.startswith(home) else root
    if rp.missing:  # 키/설정 미충족 = 미연결 — 모델명 대신 명확한 안내
        return "  " + ui.paint(theme.ansi(theme.WARNING), f"⚠ {t('not_connected')}") + "   " + ui.dim(f"⌂ {cwd}")
    parts = [f"◆ {rp.model}", f"⌂ {cwd}"]
    br = _git_status(root)
    if br:
        parts.append(f"⎇ {br}")
    if usage and usage.get("tokens"):
        parts.append(f"↯ {usage['tokens'] / 1000:.1f}k")
    return "  " + ui.dim("  ".join(parts))


_HELP_KEYS = {
    "/help": "h_help", "/new": "h_new", "/quest": "h_quest", "/provider": "h_provider",
    "/model": "h_model", "/lang": "h_lang", "/clear": "h_clear", "/exit": "h_exit",
}
_COMMANDS = ["/help", "/new", "/quest", "/provider", "/provider set", "/model",
             "/lang en", "/lang ko", "/clear", "/exit"]


def _help_items():
    return [(k, t(v)) for k, v in _HELP_KEYS.items()]


def _completer(text: str, state: int):
    """Tab 자동완성 — 슬래시 커맨드 (opencode / 트리거). readline 콜백."""
    if not text.startswith("/"):
        return None
    matches = [c + " " for c in _COMMANDS if c.startswith(text)]
    return matches[state] if state < len(matches) else None


def _setup_readline() -> None:
    """readline 배선 — Tab 자동완성 + 화살표 히스토리(파일 영속). 없는 플랫폼은 조용히 스킵."""
    try:
        import atexit
        import os
        import readline
    except Exception:
        return
    readline.set_completer(_completer)
    readline.set_completer_delims("")   # 전체 라인을 completion 대상으로 (/ 포함)
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


def prompt() -> str:
    # status line 바로 아래, 2칸 들여 정렬. 시안 › 프롬프트.
    if not ui._COLOR:
        return input("  › ")
    # readline 은 프롬프트의 비출력(ANSI) 문자를 \x01..\x02 로 감싸야 커서 폭을 정확히 계산한다.
    arrow = f"\x01\x1b[{_O}m\x02›\x01\x1b[0m\x02"
    return input(f"  {arrow} ")


class _Reconfigure(Exception):
    """provider set — 새 ResolvedProvider 로 세션 재생성 신호."""
    def __init__(self, rp):
        self.rp = rp


def slash(cmd: str, root: str, rp) -> bool:
    """슬래시 커맨드 처리. True = 처리됨(루프 계속), 종료/재설정은 예외로 신호."""
    c = cmd.split()[0]
    if c in ("/exit", "/quit"):
        raise EOFError
    if c == "/help":
        sys.stdout.write("\n")
        for k, v in _help_items():
            sys.stdout.write(f"  {ui.paint(_O, k.ljust(14))} {ui.dim(v)}\n")
        sys.stdout.write(f"  {ui.paint(_O, '!<cmd>'.ljust(14))} {ui.dim(t('h_bash'))}\n")
        sys.stdout.write(f"  {ui.dim(t('help_footer'))}\n\n")
    elif c == "/lang":
        from ..i18n import save_lang, t as _t
        arg = cmd.split()[1:2]
        if arg and save_lang(arg[0], root):
            sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {ui.dim(_t('lang_set', lang=arg[0]))}\n")
        else:
            sys.stdout.write(f"  {ui.dim(_t('lang_usage'))}\n")
    elif c == "/clear":
        sys.stdout.write("\033[2J\033[H")
        banner(rp)
    elif c in ("/provider", "/model"):
        if c == "/provider" and cmd.split()[1:2] == ["set"]:
            from .onboard import can_prompt, onboard
            if can_prompt():
                new = onboard(root)
                if new is not None:
                    raise _Reconfigure(new)  # repl.run 이 세션 재생성
            return True
        src = rp.key_source or rp.source
        sys.stdout.write(f"  {ui.paint(_O, rp.profile.display)} {ui.dim('·')} "
                         f"{rp.model} {ui.dim('(' + src + ')')}\n")
    elif c == "/quest":
        try:
            out = ql(root, "state").stdout.strip()
            sys.stdout.write(f"  {ui.dim(out or t('no_quest'))}\n")
        except Exception:
            sys.stdout.write(f"  {ui.dim(t('no_quest'))}\n")
    else:
        sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('unknown_cmd', c=c)}\n")
    return True


def _new_heimdall(root: str, rp, emit):
    from .heimdall import Heimdall
    return Heimdall(rp, root, on_text=emit)


def _bye() -> int:
    sys.stdout.write(f"\n  {ui.dim(t('bye'))}\n")
    return 0


def _run_bang(root: str, cmd: str) -> None:
    """!cmd — bash 직접 실행 (opencode 흐름). git-guard 통과 후 실행, 출력 표시."""
    from . import tools as T
    try:
        out, code = T.run_bash(root, {"command": cmd})
        sys.stdout.write(f"  {ui.dim('$ ' + cmd)}\n{out}\n")
        if code:
            sys.stdout.write(f"  {ui.dim('exit ' + str(code))}\n")
    except T.ToolError as e:
        sys.stdout.write(f"  {ui.paint(ui._FAIL, '⚠')} {e}\n")


def run(root: str, rp) -> int:
    """터미널을 바로 켠다 — 키 없어도 진입. 첫 요청 시 provider 미설정이면 온보딩(opencode 흐름)."""
    def emit(s: str) -> None:
        sys.stdout.write(s)
        sys.stdout.flush()

    _setup_readline()  # Tab 자동완성 + 화살표 히스토리
    banner(rp)
    heimdall = None if rp.missing else _new_heimdall(root, rp, emit)
    # provider 미설정 안내는 status line(⚠ not connected)이 대신 표현 — 별도 줄 없음

    while True:
        usage = {"tokens": heimdall.total_tokens} if heimdall else None
        sys.stdout.write("\n" + statusline(root, rp, usage) + "\n")  # claude-code 식 상태줄 (프롬프트 위)
        try:
            req = prompt().strip()
        except (EOFError, KeyboardInterrupt):
            return _bye()
        if not req:
            continue
        if req == "/new":  # 컨텍스트·화면 리셋 (rp/heimdall 재생성 필요 — slash 는 rp 만 받음)
            sys.stdout.write("\033[2J\033[H")
            heimdall = None if rp.missing else _new_heimdall(root, rp, emit)
            banner(rp)
            continue
        if req.startswith("!"):  # bash 직접 실행
            _run_bang(root, req[1:].strip())
            continue
        if req.startswith("/"):
            try:
                slash(req, root, rp)
            except EOFError:
                return _bye()
            except _Reconfigure as r:  # /provider set — 세션 재생성
                rp = r.rp
                heimdall = _new_heimdall(root, rp, emit)
                sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {rp.profile.display} · {rp.model} 로 전환\n")
            continue

        # 키 미설정이면 첫 요청에서 온보딩 (터미널은 이미 켜진 상태 — hermes/opencode 흐름)
        if heimdall is None:
            from .onboard import can_prompt, onboard
            if not can_prompt():
                sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('provider_unset_short')}\n")
                continue
            new = onboard(root, preselect=rp.profile.name if not rp.missing else None)
            if new is None or new.missing:
                sys.stdout.write(f"  {ui.dim(t('connect_cancel'))}\n")
                continue
            rp = new
            heimdall = _new_heimdall(root, rp, emit)

        try:
            out = heimdall.handle(req)
            if out:
                sys.stdout.write(f"\n{out}\n")
        except KeyboardInterrupt:
            sys.stdout.write(f"\n  {ui.dim(t('turn_kept'))}\n")
        except Exception as e:
            sys.stdout.write(f"\n  {ui.paint(ui._FAIL, '⚠')} 세션 오류: {e}\n")
