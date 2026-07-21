"""인터랙티브 선택 패널 (foundation) — 온보딩·REPL·CLI 공용 선택 프리미티브.

opencode식 연계 창: 한 패널 안에서 ↑↓ 이동·타이핑 즉시 필터·Enter 확정·Esc 취소가
이루어진다. 시각 언어는 REPL 입력 프레임과 동일(라운드 프레임·골드 캡·hairline rule).
패널은 transient — 닫히면 스스로 지워지고 선택 결과 한 줄만 스크롤백에 남는다.

TTY 가 아니거나 색이 꺼져 있으면 available() 이 False — 호출부는 기존 번호 입력
폴백을 그대로 쓴다 (파이프·CI·테스트 무회귀). ASGARD_PLAIN_SELECT=1 로 강제 폴백.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from . import theme, ui
from .i18n import t

_MAX_ROWS = 10  # 목록 가시 행 상한 — 넘치면 커서 주변 창으로 스크롤


@dataclass(frozen=True)
class Option:
    value: str  # pick() 반환값
    label: str  # 본문 표기
    detail: str = ""  # 딤 부가 설명 (· model 등)
    current: bool = False  # 현재 값 표식 *


def available() -> bool:
    """인터랙티브 패널 구동 가능 여부 — 폴백 분기의 단일 소스."""
    if os.environ.get("ASGARD_PLAIN_SELECT"):
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty() and ui._COLOR):
        return False
    try:
        import prompt_toolkit  # noqa: F401
    except Exception:
        return False
    return True


def _match(option: Option, terms: list[str]) -> bool:
    hay = f"{option.label} {option.detail} {option.value}".lower()
    return all(term in hay for term in terms)


def pick(title: str, options: list[Option], *, default: int = 0, manual_hint: str = "") -> str | None:
    """선택 패널을 띄우고 확정된 Option.value 를 돌려준다 (취소 None).

    manual_hint 가 주어지면 필터 텍스트를 그대로 쓰는 수동 행이 열린다 — 이때 반환값은
    옵션 목록 밖의 원시 입력일 수 있다 (호출부가 정규화). available() 이 참일 때만 부를 것.
    """
    if not options:
        return None
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    class _State:
        query = ""
        cursor = max(0, min(default, len(options) - 1))

    state = _State()
    _rule = f"fg:{theme.HAIRLINE}"
    _cap = f"fg:{theme.PRIMARY} bold"
    _dim = f"fg:{theme.SUBTEXT}"

    def rows() -> list[tuple[str, str]]:
        """필터 적용된 (kind, payload) 행 — kind: opt 인덱스 str | 'manual'."""
        terms = state.query.lower().split()
        out: list[tuple[str, str]] = [("opt", str(i)) for i, o in enumerate(options) if _match(o, terms)]
        if manual_hint and state.query.strip():
            out.append(("manual", state.query.strip()))
        return out

    def fragments():
        width = ui.stream_width()
        frags: list[tuple[str, str]] = []
        # 상단 보더 — ╭─ {title} ───╮ (REPL 입력 프레임과 같은 기하)
        fill = width - 9 - len(title)
        if fill < 4:
            frags.append((_rule, "  ╭" + "─" * max(0, width - 6) + "╮\n"))
        else:
            frags.append((_rule, "  ╭─ "))
            frags.append((_cap, title))
            frags.append((_rule, " " + "─" * fill + "╮\n"))
        # 필터 입력 행 — › 쿼리 (비면 placeholder)
        frags.append((_rule, "  │ "))
        frags.append((f"fg:{theme.PRIMARY} bold", "› "))
        if state.query:
            frags.append((f"fg:{theme.TEXT}", state.query))
        else:
            frags.append((_dim, t("picker_filter_ph")))
        frags.append(("", "\n"))
        visible = rows()
        cursor = min(state.cursor, len(visible) - 1) if visible else 0
        state.cursor = cursor
        # 가시 창 — 커서 주변 _MAX_ROWS 행, 넘침은 … n more 로 표기
        start = max(0, min(cursor - _MAX_ROWS // 2, len(visible) - _MAX_ROWS))
        end = min(len(visible), start + _MAX_ROWS)
        if start > 0:
            frags += [(_rule, "  │ "), (_dim, "  " + t("picker_more", n=start) + " ↑\n")]
        for i in range(start, end):
            kind, payload = visible[i]
            on = i == cursor
            frags.append((_rule, "  │ "))
            frags.append((f"fg:{theme.PRIMARY} bold" if on else "", "▸ " if on else "  "))
            if kind == "manual":
                frags.append((f"fg:{theme.TEXT} bold" if on else _dim, "↳ " + manual_hint.format(q=payload)))
            else:
                o = options[int(payload)]
                frags.append((f"fg:{theme.TEXT} bold" if on else f"fg:{theme.TEXT}", o.label))
                if o.detail:
                    frags.append((_dim, " · " + o.detail))
                if o.current:
                    frags.append((_cap, " *"))
            frags.append(("", "\n"))
        if end < len(visible):
            frags += [(_rule, "  │ "), (_dim, "  " + t("picker_more", n=len(visible) - end) + " ↓\n")]
        if not visible:
            frags += [(_rule, "  │ "), (_dim, "  " + t("picker_no_match") + "\n")]
        # 하단 보더 + 힌트
        frags.append((_rule, "  ╰" + "─" * max(0, width - 6) + "╯\n"))
        frags.append((_dim, "    " + t("picker_hint")))
        return frags

    kb = KeyBindings()

    def move(delta: int) -> None:
        n = len(rows())
        if n:
            state.cursor = (state.cursor + delta) % n

    kb.add("up")(lambda e: move(-1))
    kb.add("c-p")(lambda e: move(-1))
    kb.add("down")(lambda e: move(1))
    kb.add("c-n")(lambda e: move(1))
    kb.add("pageup")(lambda e: move(-_MAX_ROWS))
    kb.add("pagedown")(lambda e: move(_MAX_ROWS))

    @kb.add("enter")
    def _accept(event) -> None:
        visible = rows()
        if not visible:
            return
        kind, payload = visible[state.cursor]
        event.app.exit(result=payload if kind == "manual" else options[int(payload)].value)

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("c-g")
    def _cancel(event) -> None:
        event.app.exit(result=None)

    @kb.add("backspace")
    def _erase(event) -> None:
        if state.query:
            state.query = state.query[:-1]
            state.cursor = 0

    @kb.add("c-u")
    def _clear(event) -> None:
        state.query, state.cursor = "", 0

    @kb.add("<any>")
    def _type(event) -> None:
        data = event.data or ""
        if data.isprintable():
            state.query += data
            state.cursor = 0

    app: Application = Application(
        layout=Layout(HSplit([Window(FormattedTextControl(fragments, show_cursor=False), wrap_lines=False)])),
        key_bindings=kb,
        erase_when_done=True,
        mouse_support=False,
    )
    try:
        result = app.run()
    except EOFError, KeyboardInterrupt:
        return None
    if result is not None:
        chosen = next((o.label for o in options if o.value == result), result)
        sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {ui.dim(title + ' ·')} {chosen}\n")
    return result
