"""입력 한 줄을 받는 자리 — prompt_toolkit 세션과 readline 폴백, 그리고 그 둘의 상자 테두리."""

from __future__ import annotations

from ... import theme, ui
from ...i18n import t
from .catalog import _COMMAND_HELP, _completer, _completion_matches
from .chrome import _BOX, _BOX_CAP, _O, _STATUS_SEP, _status_segments

_PT = None  # prompt_toolkit 세션 캐시 — False 면 생성 실패(readline 폴백)


def ensure_pt() -> bool:
    """prompt_toolkit 세션을 한 번만 세우고, 세워졌는지 돌려준다.

    세션을 만드는 쪽(루프)과 쓰는 쪽(`prompt`)이 다른 파일에 있어서 함수가 됐다. 실패는
    False 로 굳혀 다시 시도하지 않는다 — 못 세우는 터미널에서 매 턴 예외를 다시 무는 대신
    readline 폴백으로 내려간다."""
    global _PT
    if _PT is None and ui._COLOR:
        try:
            _PT = _pt_session()
        except Exception:
            _PT = False
    return bool(_PT)


_PT_CTX: dict = {}  # bottom_toolbar 용 세션 상태 — run()이 매 루프 갱신 {root, rp, heimdall}


def _term_width() -> int:
    import shutil

    return max(20, shutil.get_terminal_size((80, 20)).columns)


def _disp_w(s: str) -> int:
    """표시 폭 — CJK 전각(W/F) 2칸. 독 입력행 절단·캐럿 열 계산 공용 (정본은 ui.disp_width)."""
    return ui.disp_width(s)


def _decode_keys(raw: bytes) -> tuple[str, bytes]:
    """원시 stdin 바이트 → 독 초안에 반영할 텍스트. 미완성 UTF-8/이스케이프 꼬리는 carry로
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
        return "", b""  # UTF-8로 못 푸는 잡음 — 폐기
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
    """_box_top의 ANSI 문자열판 — 독(비활성 프레임)용. pt 프래그와 같은 기하·색."""
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
    # 브랜드칩은 상단 캡(⠶ asgard)이 담당 — pt 경로 시그니처 1개. 상태줄은 model부터 (상태 전용)
    for i, (txt, hx, bold) in enumerate(_status_segments(ctx["root"], ctx["rp"], usage)):
        if i:
            frags.append(("", _STATUS_SEP))  # 여백 구분자 (색이 분절)
        frags.append((f"fg:{hx} bold" if bold else f"fg:{hx}", txt))
    return frags


def _history_path() -> str:
    import os

    from ...profiles import home

    hp = os.path.join(home(), "history")  # 입력 이력도 에이전트의 것 (turn_store와 같은 규율)
    os.makedirs(os.path.dirname(hp), exist_ok=True)
    return hp


def _kb_enter(event) -> None:
    """Enter = 제출. 단 커서 앞이 '\\'로 끝나면 백슬래시를 지우고 줄 내림 (연속 입력)."""
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

    # Shift+Enter를 Ctrl+J로 별칭 — CSI-u(\x1b[13;2u)는 미매핑, modifyOtherKeys(\x1b[27;2;13~)는
    # pt 기본이 일반 Enter라 줄내림으로 재매핑한다. 미지원 터미널은 \r 그대로 → '\'+Enter가 대안.
    for seq in ("\x1b[13;2u", "\x1b[27;2;13~"):
        _esc.ANSI_SEQUENCES[seq] = Keys.ControlJ

    kb = KeyBindings()
    kb.add("enter")(_kb_enter)
    kb.add("c-j")(_kb_newline)

    class _BottomAnchored(PromptSession):
        """하단 고정용 세션 — 메뉴 예약을 동적으로: '/' 커맨드 입력 중일 때만 8행.
        pt는 이 값을 렌더마다 읽으므로(_get_default_buffer_control_height) 프로퍼티가 통한다.
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
            pass  # __init__의 정적 대입 무시 — 동적 계산이 단일 소스

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
            "rule": theme.HAIRLINE,  # 입력·박스 프레임 룰 — 배너 rule과 한 하드라인 색
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
        multiline=True,  # 줄 내림 허용 — Enter 제출은 _kb_enter가 유지 (기본 멀티라인 Enter를 대체)
        key_bindings=kb,
        prompt_continuation=_pt_continuation,
        # 제출 시 입력 프레임 전체 소거 — 라이브 에디터는 편집 중에만 존재하고, 스크롤백엔
        # run()의 _echo_submitted 한 줄이 사용자 메시지를 대표한다 (pi·hermes·opencode 공통:
        # 에디터는 transient, 내역엔 별도 표현. 열린 박스·rprompt 힌트 잔존 문제의 근본 해소).
        erase_when_done=True,
    )

    # 바닥 정렬 필러 — pt 인라인 프롬프트는 커서 원점에 위에서부터 그린다. 박스 위를
    # `화면 잔여 행(rows − rows_above_layout, CPR 기반) − 본체 필요 행` 만큼 정확히 채우면
    # 박스가 바닥에 붙고, 성장(줄 추가·메뉴 오픈)은 필러를 소모할 뿐 화면을 스크롤하지 않으며
    # 축소는 필러가 되살아나 위 내용(배너·직전 출력)이 전혀 움직이지 않는다. 잔여 공간을
    # 넘는 성장만 pt가 자연 스크롤. accept(is_done) 시 필러가 접혀 제출 박스는 본문 흐름
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
    # uv 파이썬(macOS)은 GNU readline이 아니라 libedit — 바인딩 문법이 다르다.
    # GNU 문법("tab: complete")을 libedit에 주면 조용히 무시돼 Tab이 탭 문자로 들어간다.
    if getattr(readline, "backend", "") == "editline":
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")
    hp = _history_path()
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
    """제출된 입력의 스크롤백 표기 — pt가 accept 시 입력 프레임을 통째로 지우므로
    (erase_when_done) 내역엔 이 표기가 사용자 메시지를 대표한다. 일반 요청은 골드 캐럿 `›`
    + 본문(hermes의 ❯ 거터 상응), 커맨드(`/`·`!`)는 전체 흐림(hermes의 muted slash 라인
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
    # readline 폴백 — 비출력(ANSI) 문자는 \x01..\x02로 감싸야 커서 폭을 정확히 계산한다.
    arrow = f"\x01\x1b[{_O}m\x02›\x01\x1b[0m\x02"
    cont = "  \x01\x1b[2m\x02…\x01\x1b[0m\x02 "  # readline 프롬프트 ANSI는 \x01..\x02 가드 필수
    return _input_continued(f"  {arrow} ", cont)
