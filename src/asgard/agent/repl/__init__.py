"""Heimdall 터미널 — 한 번의 세션이 도는 자리.

화면·입력·명령·출력은 면별 모듈이 지고, 여기 남은 것은 그것들을 엮는 루프 하나다."""

from __future__ import annotations

import sys

from ... import ui, winterm
from ...i18n import t

# 아래는 다시 내보내기다. 이 모듈은 파일 하나였고 바깥은 그 평평한 이름 표면을 쥔다 —
# `repl._Dock`·`repl._decode_keys` 처럼. 면별로 갈랐다고 닿던 이름이 사라지면 안 된다.
from .catalog import (
    _COMMAND_HELP,
    _completer,
    _completion_matches,
    _help_items,
)
from .chrome import (
    _BOX,
    _BOX_CAP,
    _BRAND_CHIP,
    _ICON_LAGOM,
    _LOGO,
    _LOGO_GRAD,
    _LOGO_GRAD_LIGHT,
    _LOGO_SLIM,
    _O,
    _STATUS_SEP,
    _abbrev_path,
    _git_status,
    _image_logo,
    _paint_seg,
    _status_segments,
    banner,
    is_light_bg,
    statusline,
)
from .commands import (
    _apply_role_model,
    _cmd_bridge,
    _cmd_lagom,
    _cmd_manual,
    _cmd_trinity,
    _prompt_role_model,
    _Reconfigure,
    _trinity_model,
    _trinity_models,
    slash,
)
from .dock import (
    _cancel_on_sigint,
    _cursor_row,
    _Dock,
    _echo_off,
    _term_rows,
)
from .editline import (
    _PT,
    _PT_CTX,
    _box_bottom_str,
    _box_fill,
    _box_top,
    _box_top_str,
    _decode_keys,
    _disp_w,
    _echo_submitted,
    _history_path,
    _input_continued,
    _kb_enter,
    _kb_newline,
    _pt_continuation,
    _pt_message,
    _pt_session,
    _pt_toolbar,
    _save_history,
    _setup_readline,
    _term_width,
    _usage_of,
    ensure_pt,
    prompt,
)
from .render import (
    _MD_BOLD,
    _bye,
    _memory_badge,
    _new_heimdall,
    _recap_sentence,
    _Render,
    _run_bang,
    _Spinner,
    _turn_recap_str,
)


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
    # 한쪽만 배선한다 (readline atexit가 pt 포맷 히스토리를 덮어쓰는 것 방지).
    pt = ensure_pt()
    if not pt:
        _setup_readline()  # Tab 자동완성 + 화살표 히스토리
    if pt and ui._COLOR and sys.stdout.isatty():
        dock = _Dock()  # 하단 상주 입력 독 — pt 경로 전용 (폴백·비 tty는 기존 스피너 흐름)
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
        if pt:  # 상태줄은 bottom_toolbar(입력창 아래)가 표시 — cursor-agent 식
            # 하단 고정은 _pt_session의 바닥 정렬 필러가 담당 (커서 점프 불필요 — CPR 기반)
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
        if pt:  # 지워진 입력 프레임을 대신하는 사용자 메시지 표기 (폴백 경로는 input 에코가 남는다)
            if dock is not None:
                # 제출 블록(에코+여백)을 독 바로 위로 앵커 — 질문·응답·독이 하단에 응집한다.
                # 흐름이 얕을 때(첫 턴 등)만 하향 점프 (상향 점프는 본문 덮어쓰기라 금지),
                # 이후 스트리밍 스크롤에도 질문이 응답 직상에 남는다. CPR 미응답이면 현 위치 유지.
                cur = _cursor_row()
                anchor = max(1, _term_rows() - _Dock.HEIGHT - 1)
                if cur is not None and cur < anchor:
                    sys.stdout.write(f"\x1b[{anchor};1H\x1b[0J")
            sys.stdout.write(_echo_submitted(req) + "\n")
        if req == "/new":  # 컨텍스트·화면 리셋 (rp/heimdall 재생성 필요 — slash는 rp만 받음)
            sys.stdout.write("\033[2J\033[H")
            heimdall = None if rp.missing else _new_heimdall(root, rp, emit, status)
            banner(rp)
            continue
        if req.startswith("!"):  # bash 직접 실행
            _run_bang(root, req[1:].strip())
            continue
        if req.startswith("/"):
            from ...skill_registry import invoked_skill_prompt

            invoked = None if req.split()[0] in _COMMAND_HELP else invoked_skill_prompt(root, req)
            if invoked is None:
                try:
                    slash(req, root, rp)
                except EOFError:
                    return _bye()
                except _Reconfigure as r:  # /provider set · /trinity set — 세션 재생성
                    rp = r.rp
                    heimdall = None if rp.missing else _new_heimdall(root, rp, emit, status)
                    msg = r.msg or f"{rp.profile.display} · {rp.model}로 전환"
                    sys.stdout.write(f"  {ui.paint(ui._OK, '✔')} {msg}\n")
                continue
            req = invoked

        # 키 미설정 — 온보딩을 강제로 열지 않고 안내만 (연결은 /provider set으로 명시적으로)
        if heimdall is None:
            sys.stdout.write(f"  {ui.paint(ui._WARN, '⚠')} {t('connect_needed')}\n")
            continue

        try:
            import time as _time
            from contextlib import ExitStack

            ev = getattr(heimdall, "cancel_event", None)  # 제출측 clear — handle()은 clear 하지 않는다
            if ev is not None:
                ev.clear()
            sys.stdout.write("\n")  # 제출 에코 ↔ 응답 블록 시각 분리 — 스트리밍 첫 줄이 에코에 접착되지 않게
            t0 = _time.monotonic()
            tok0 = getattr(heimdall, "total_tokens", 0)  # 턴 지출 = 누적 델타 (recap 용)
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
            # 턴 recap — '✓ done' 요약줄 + 활동 집계(agents/tools/files/cmds, hermes 식 로컬 계산)
            spent = max(0, getattr(heimdall, "total_tokens", 0) - tok0)
            sys.stdout.write("\n" + _turn_recap_str(heimdall, rp, _time.monotonic() - t0, spent) + "\n")
        except KeyboardInterrupt:
            sys.stdout.write(f"\n  {ui.dim(t('turn_kept'))}\n")
        except Exception as e:
            sys.stdout.write(f"\n  {ui.paint(ui._FAIL, '⚠')} 세션 오류: {e}\n")
        finally:
            status(None)  # 스피너 누수 방지 (인터럽트·예외 경로)
            render.finish()


# 평평한 이름 표면의 선언. 여기 있는 것은 밖에서 `repl.<이름>` 으로 닿는다.
__all__ = [
    "_BOX",
    "_BOX_CAP",
    "_BRAND_CHIP",
    "_COMMAND_HELP",
    "_Dock",
    "_ICON_LAGOM",
    "_LOGO",
    "_LOGO_GRAD",
    "_LOGO_GRAD_LIGHT",
    "_LOGO_SLIM",
    "_MD_BOLD",
    "_O",
    "_PT",
    "_PT_CTX",
    "_Reconfigure",
    "_Render",
    "_STATUS_SEP",
    "_Spinner",
    "_abbrev_path",
    "_apply_role_model",
    "_box_bottom_str",
    "_box_fill",
    "_box_top",
    "_box_top_str",
    "_bye",
    "_cancel_on_sigint",
    "_cmd_bridge",
    "_cmd_lagom",
    "_cmd_manual",
    "_cmd_trinity",
    "_completer",
    "_completion_matches",
    "_cursor_row",
    "_decode_keys",
    "_disp_w",
    "_echo_off",
    "_echo_submitted",
    "_git_status",
    "_help_items",
    "_history_path",
    "_image_logo",
    "_input_continued",
    "_kb_enter",
    "_kb_newline",
    "_memory_badge",
    "_new_heimdall",
    "_paint_seg",
    "_prompt_role_model",
    "_pt_continuation",
    "_pt_message",
    "_pt_session",
    "_pt_toolbar",
    "_recap_sentence",
    "_run_bang",
    "_save_history",
    "_setup_readline",
    "_status_segments",
    "_term_rows",
    "_term_width",
    "_trinity_model",
    "_trinity_models",
    "_turn_recap_str",
    "_usage_of",
    "ensure_pt",
    "banner",
    "is_light_bg",
    "prompt",
    "run",
    "slash",
    "statusline",
    "winterm",
]
