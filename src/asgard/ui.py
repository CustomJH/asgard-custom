"""Terminal UX — branded + colored on a tty, plain otherwise (mirrors install.sh's phased look).
Every command routes through head()/phase()/spin()/ok()/done() so the CLI reads like the installer:
a brand mark, numbered phases, a braille spinner for slow steps, ✔/!/✗ results.
`--quiet` suppresses decorative lines (results still print). NO_COLOR / non-tty → no ANSI, no spinner."""

import itertools
import os
import sys
import threading
import time

# TERM=dumb 또는 미설정이면 ANSI 미지원 — 색을 끈다 (docker exec 등에서 raw 코드가 뜨는 것 방지).
_TERM = os.environ.get("TERM", "")
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR") and _TERM not in ("", "dumb")
_QUIET = False
_MARK = "⠶"  # ⠶ — small brand dot-mark (Yggdrasil), painted orange
_FRAMES = "⣾⣽⣻⢿⡿⣟⣯⣷"
_STEP = 0
_STEPS = 0


def set_quiet(q: bool) -> None:
    global _QUIET
    _QUIET = q


def paint(code: str, s: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m" if _COLOR else s


def bold(s: str) -> str:
    return paint("1", s)


def dim(s: str) -> str:
    return paint("2", s)


def _mark() -> str:
    return paint("38;5;208", _MARK)


def head(action: str, steps: int = 0) -> None:
    """Branded header — mark + `asgard <action>`. `steps` sets the phase denominator ([n/steps])."""
    global _STEP, _STEPS
    _STEP, _STEPS = 0, steps
    if not _QUIET:
        sys.stdout.write(f"\n  {_mark()} {bold('asgard')} {dim(action)}\n\n")


def phase(title: str) -> None:
    """Numbered section header, install.sh-style: [n/N] (or [n] when the total is unknown)."""
    global _STEP
    _STEP += 1
    if not _QUIET:
        tag = f"[{_STEP}/{_STEPS}]" if _STEPS else f"[{_STEP}]"
        sys.stdout.write(f"  {bold(paint('36', tag))} {bold(title)}\n")


def step(msg: str) -> None:
    if not _QUIET:
        sys.stdout.write(f"  {paint('36', '→')} {msg}\n")


def ok(msg: str) -> None:
    sys.stdout.write(f"  {paint('32', '✔')} {msg}\n")


def warn(msg: str) -> None:
    sys.stdout.write(f"  {paint('33', '!')} {msg}\n")


def fail(msg: str) -> None:
    sys.stderr.write(f"  {paint('31', '✘')} {msg}\n")


def done(msg: str = "") -> None:
    """Closing ✔ line for a command."""
    tail = f"  {dim('— ' + msg)}" if msg else ""
    sys.stdout.write(f"\n  {paint('32', '✔')} {bold('done')}{tail}\n\n")


class spin:
    """Braille spinner for a slow step. `with ui.spin('installing…'): subprocess.run(..., capture)`.
    No-op (just runs the body) on non-tty / --quiet. Clears its line on exit so the ✔ prints clean."""

    def __init__(self, label: str) -> None:
        self.label = label
        self._t: threading.Thread | None = None
        self._stop: threading.Event | None = None

    def __enter__(self) -> "spin":
        if _COLOR and not _QUIET:
            self._stop = threading.Event()
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()
        return self

    def _run(self) -> None:
        import shutil
        for fr in itertools.cycle(_FRAMES):
            if self._stop.is_set():
                break
            # 라벨을 터미널 폭에 맞춰 절단 — 넘치면 줄바꿈이 나서 \r 리라이트가 깨진다(스피너가
            # 줄줄이 찍힘). 프리픽스 "  X " = 4칸. 라벨은 순수 텍스트 전제(ANSI 넣지 말 것 — 폭 오산).
            width = shutil.get_terminal_size((80, 20)).columns
            budget = max(10, width - 5)
            label = self.label if len(self.label) <= budget else self.label[:budget - 1] + "…"
            sys.stdout.write(f"\r\x1b[K  {paint('36', fr)} {label}")
            sys.stdout.flush()
            time.sleep(0.08)

    def __exit__(self, *exc: object) -> bool:
        if self._t:
            self._stop.set()
            self._t.join(timeout=1)
            sys.stdout.write("\r\x1b[K")
            sys.stdout.flush()
        return False
