"""Terminal UX — branded + colored on a tty, plain otherwise (mirrors install.sh / the TS ui helpers).
`--quiet` suppresses decorative head/step lines (results still print). NO_COLOR / non-tty → no ANSI."""

import os
import sys

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
_QUIET = False


def set_quiet(q: bool) -> None:
    global _QUIET
    _QUIET = q


def paint(code: str, s: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m" if _COLOR else s


def bold(s: str) -> str:
    return paint("1", s)


def dim(s: str) -> str:
    return paint("2", s)


def head(action: str) -> None:
    if not _QUIET:
        sys.stdout.write(f"\n  {paint('1;35', 'ᛞ')} {bold('asgard')} {dim(action)}\n\n")


def step(msg: str) -> None:
    if not _QUIET:
        sys.stdout.write(f"  {paint('36', '→')} {msg}\n")


def ok(msg: str) -> None:
    sys.stdout.write(f"  {paint('32', '✔')} {msg}\n")


def warn(msg: str) -> None:
    sys.stdout.write(f"  {paint('33', '!')} {msg}\n")


def fail(msg: str) -> None:
    sys.stderr.write(f"  {paint('31', '✗')} {msg}\n")
