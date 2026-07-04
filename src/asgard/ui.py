"""Terminal UX — branded + colored on a tty, plain otherwise (mirrors install.sh's phased look).
Every command routes through head()/phase()/spin()/ok()/done() so the CLI reads like the installer:
a brand mark, numbered phases, a braille spinner for slow steps, ✔/!/✗ results.
`--quiet` suppresses decorative lines (results still print). NO_COLOR / non-tty → no ANSI, no spinner."""

import itertools
import os
import sys
import threading
import time

from . import theme

# TERM=dumb 또는 미설정이면 ANSI 미지원 — 색을 끈다 (docker exec 등에서 raw 코드가 뜨는 것 방지).
_TERM = os.environ.get("TERM", "")
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR") and _TERM not in ("", "dumb")
_QUIET = False
_MARK = "⠶"  # ⠶ — small brand dot-mark (Yggdrasil), painted gold (theme.PRIMARY)
# 시맨틱 색 — 토큰(theme.py)에서 유도. 여기 외 raw 코드 직접 쓰지 말 것.
_GOLD = theme.ansi(theme.PRIMARY)
_INFO = theme.ansi(theme.ACCENT_BLUE)
_OK = theme.ansi(theme.SUCCESS)
_WARN = theme.ansi(theme.WARNING)
_FAIL = theme.ansi(theme.DANGER)
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
    return paint(_GOLD, _MARK)


def head(action: str, steps: int = 0) -> None:
    """Branded header — mark + `asgard <action>`. `steps` sets the phase denominator ([n/steps])."""
    global _STEP, _STEPS
    _STEP, _STEPS = 0, steps
    if not _QUIET:
        sys.stdout.write(f"\n  {_mark()} {bold('asgard')} {dim(action)}\n\n")


def steps(n: int) -> None:
    """phase 분모를 늦게 확정 — head 시점에 총 단계 수를 모를 때 (update 의 check 분기 등)."""
    global _STEPS
    _STEPS = n


def phase(title: str) -> None:
    """Numbered section header, install.sh-style: [n/N] (or [n] when the total is unknown)."""
    global _STEP
    _STEP += 1
    if not _QUIET:
        tag = f"[{_STEP}/{_STEPS}]" if _STEPS else f"[{_STEP}]"
        sys.stdout.write(f"  {bold(paint(_INFO, tag))} {bold(title)}\n")


def step(msg: str) -> None:
    if not _QUIET:
        sys.stdout.write(f"  {paint(_INFO, '→')} {msg}\n")


def ok(msg: str) -> None:
    sys.stdout.write(f"  {paint(_OK, '✔')} {msg}\n")


def warn(msg: str) -> None:
    sys.stdout.write(f"  {paint(_WARN, '!')} {msg}\n")


def fail(msg: str) -> None:
    sys.stderr.write(f"  {paint(_FAIL, '✘')} {msg}\n")


def done(msg: str = "") -> None:
    """Closing ✔ line for a command."""
    tail = f"  {dim('— ' + msg)}" if msg else ""
    sys.stdout.write(f"\n  {paint(_OK, '✔')} {bold('done')}{tail}\n\n")


class bar:
    """Determinate 진행률 바 — `with ui.bar('label', total_bytes) as b: b.advance(n)`.
    골드 채움 + 흐린 잔여 + % + MB. non-tty/--quiet 은 no-op. total 불명(0)은 누적 MB 만."""

    _CELLS = 24

    def __init__(self, label: str, total: int) -> None:
        self.label, self.total, self.done = label, max(0, int(total or 0)), 0

    def __enter__(self) -> "bar":
        self._draw()
        return self

    def advance(self, n: int) -> None:
        self.done += n
        self._draw()

    def _draw(self) -> None:
        if not _COLOR or _QUIET:
            return
        import shutil

        if self.total:
            frac = min(1.0, self.done / self.total)
            fill = int(self._CELLS * frac)
            cells = paint(_GOLD, "━" * fill) + dim("─" * (self._CELLS - fill))
            info = f"{frac * 100:3.0f}%  {self.done / 1e6:.1f}/{self.total / 1e6:.1f} MB"
        else:
            cells = paint(_GOLD, "━" * self._CELLS)
            info = f"{self.done / 1e6:.1f} MB"
        width = shutil.get_terminal_size((80, 20)).columns
        label = self.label[: max(8, width - self._CELLS - 24)]
        sys.stdout.write(f"\r\x1b[K  {cells} {info}  {dim(label)}")
        sys.stdout.flush()

    def __exit__(self, *exc: object) -> bool:
        if _COLOR and not _QUIET:
            sys.stdout.write("\r\x1b[K")
            sys.stdout.flush()
        return False


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

        t0 = time.monotonic()
        for fr in itertools.cycle(_FRAMES):
            if self._stop.is_set():
                break
            # 라벨을 터미널 폭에 맞춰 절단 — 넘치면 줄바꿈이 나서 \r 리라이트가 깨진다(스피너가
            # 줄줄이 찍힘). 프리픽스 "  X " = 4칸. 라벨은 순수 텍스트 전제(ANSI 넣지 말 것 — 폭 오산).
            secs = time.monotonic() - t0
            tail = f" · {secs:.0f}s" if secs >= 1 else ""
            width = shutil.get_terminal_size((80, 20)).columns
            budget = max(10, width - 5 - len(tail))
            label = self.label if len(self.label) <= budget else self.label[: budget - 1] + "…"
            sys.stdout.write(f"\r\x1b[K  {paint(_INFO, fr)} {label}{dim(tail)}")
            sys.stdout.flush()
            time.sleep(0.08)

    def __exit__(self, *exc: object) -> bool:
        if self._t:
            self._stop.set()
            self._t.join(timeout=1)
            sys.stdout.write("\r\x1b[K")
            sys.stdout.flush()
        return False
