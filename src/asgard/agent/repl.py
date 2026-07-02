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

from .. import ui
from .session import ql

# install.sh _logo_art 의 Yggdrasil 마크 + ASGARD wordmark (braille lockup) — 축약본.
_LOGO = r"""  ⠀⠀⢀⡤⣶⣶⣲⠤⣀⠀⠀   ⢰⡄⠀⠀⠀⢀⣤⣦⣄⡀⠀⠀⣠⣦⣀⠀⠀⠀⠀⣦⠀⠀⠰⣶⣶⣶⣦⡀⠐⣶⣦⣄
  ⠀⢀⣼⣽⣻⡟⣿⣷⢫⣟⣧⡀   ⢀⣿⣷⠀⢰⣿⠋⠈⠙⠁⠀⣠⡾⠋⠈⠛⠀⠀⣸⣿⡆⠀⠀⣿⡇⠀⠙⣷⡄⣿⡏⠻⣷⡄
  ⠀⣸⢽⣦⡷⣻⡟⣟⢾⣴⣧⠀   ⣼⡏⢻⣇⠈⠛⢷⣤⡀⢸⣿⠁⣀⣀⠀⢠⣿⠙⣿⡀⠀⣿⡇⣀⣴⠟⠀⣿⡇⠀⠈⢻⡆
  ⠀⢻⠽⠇⣸⢸⡇⣷⠈⠯⡟⠀   ⢰⡿⢀⡈⣿⡄⠀⠙⢿⣦⠘⢿⣄⢹⡏⣾⠇⣀⢹⣧⠀⣿⡿⢻⣧⠀⠀⣿⣧⡾⠋⠀
  ⠀⠈⢳⣲⡿⣾⣷⢿⣶⡞⠁⠀   ⢀⣿⠁⠻⠃⢸⣷⡀⣶⣤⣴⠿⠃⠙⢷⣼⡇⣸⡟⢻⣆⣿⡇⠀⠹⣷⡀⣿⣧⡾⠋⠀"""


def banner(rp) -> None:
    if ui._COLOR:
        sys.stdout.write("\n" + ui.paint("38;5;208", _LOGO) + "\n")
    sys.stdout.write(
        f"  {ui.dim('─' * 20)} {ui._mark()} {ui.dim('─' * 20)}\n"
        f"  {ui.bold('Heimdall')} {ui.dim('· 비프로스트의 수호자')}    "
        f"{ui.paint('38;5;208', rp.profile.display)} {ui.dim('·')} {rp.model}\n"
        f"  {ui.dim('/help 도움말 · /exit 종료 · Ctrl-C 턴 중단')}\n\n")


def prompt() -> str:
    mark = ui.paint("38;5;208", "◇") if ui._COLOR else "◇"
    return input(f"{mark} {ui.bold('odin')} ▸ ")


_HELP = {
    "/help": "이 도움말",
    "/quest": "진행 중 퀘스트 원장 상태",
    "/provider": "provider·model 표시 · '/provider set' 으로 재설정",
    "/model": "현재 모델 ID",
    "/clear": "화면 지우기",
    "/exit": "세션 종료 (Ctrl-D 동일)",
}


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
        for k, v in _HELP.items():
            sys.stdout.write(f"  {ui.paint('38;5;208', k.ljust(10))} {ui.dim(v)}\n")
        sys.stdout.write("\n")
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
        sys.stdout.write(f"  {ui.paint('38;5;208', rp.profile.display)} {ui.dim('·')} "
                         f"{rp.model} {ui.dim('(' + src + ')')}\n")
    elif c == "/quest":
        try:
            out = ql(root, "state").stdout.strip()
            sys.stdout.write(f"  {ui.dim(out or '진행 중 퀘스트 없음')}\n")
        except Exception:
            sys.stdout.write(f"  {ui.dim('진행 중 퀘스트 없음')}\n")
    else:
        sys.stdout.write(f"  {ui.paint('33', '⚠')} 미지의 커맨드 {c} — /help\n")
    return True


def _new_heimdall(root: str, rp, emit):
    from .heimdall import Heimdall
    return Heimdall(rp, root, on_text=emit)


def _bye() -> int:
    sys.stdout.write(f"\n  {ui.dim('비프로스트 봉인. 안녕히, 오딘.')}\n")
    return 0


def run(root: str, rp) -> int:
    """터미널을 바로 켠다 — 키 없어도 진입. 첫 요청 시 provider 미설정이면 온보딩(opencode 흐름)."""
    def emit(s: str) -> None:
        sys.stdout.write(s)
        sys.stdout.flush()

    banner(rp)
    heimdall = None if rp.missing else _new_heimdall(root, rp, emit)
    if heimdall is None:
        sys.stdout.write(f"  {ui.dim('provider 미설정 — 메시지를 보내면 연결을 안내합니다 (또는 /provider set)')}\n")

    while True:
        try:
            req = prompt().strip()
        except (EOFError, KeyboardInterrupt):
            return _bye()
        if not req:
            continue
        if req.startswith("/"):
            try:
                slash(req, root, rp)
            except EOFError:
                return _bye()
            except _Reconfigure as r:  # /provider set — 세션 재생성
                rp = r.rp
                heimdall = _new_heimdall(root, rp, emit)
                sys.stdout.write(f"  {ui.paint('32', '✔')} {rp.profile.display} · {rp.model} 로 전환\n")
            continue

        # 키 미설정이면 첫 요청에서 온보딩 (터미널은 이미 켜진 상태 — hermes/opencode 흐름)
        if heimdall is None:
            from .onboard import can_prompt, onboard
            if not can_prompt():
                sys.stdout.write(f"  {ui.paint('33', '⚠')} provider 미설정 — 대화형 터미널에서 연결하세요\n")
                continue
            new = onboard(root, preselect=rp.profile.name if not rp.missing else None)
            if new is None or new.missing:
                sys.stdout.write(f"  {ui.dim('연결 취소 — /provider set 으로 다시 시도')}\n")
                continue
            rp = new
            heimdall = _new_heimdall(root, rp, emit)

        try:
            out = heimdall.handle(req)
            if out:
                sys.stdout.write(f"\n{out}\n")
        except KeyboardInterrupt:
            sys.stdout.write(f"\n  {ui.dim('(턴 중단 — 세션 유지)')}\n")
        except Exception as e:
            sys.stdout.write(f"\n  {ui.paint('31', '⚠')} 세션 오류: {e}\n")
