"""하단 상주 입력 독 — 턴이 도는 동안에도 다음 줄을 칠 수 있는 자리.

`_term_rows` 가 여기 있는 이유는 독의 높이가 그 계산에 들어가기 때문이다. 입력면에 두면
독이 그것을 부르고 그것이 독을 불러 순환이 된다."""

from __future__ import annotations

import sys

from ... import theme, ui, winterm
from ...i18n import t
from .chrome import _BOX, _O, _STATUS_SEP, _paint_seg, _status_segments
from .editline import _PT_CTX, _box_bottom_str, _box_top_str, _decode_keys, _disp_w, _usage_of


def _term_rows() -> int:
    import shutil

    return max(_Dock.HEIGHT, shutil.get_terminal_size((80, 24)).lines)


class _Dock:
    """클로드코드식 하단 상주 입력 독 (프레이야 명세 26-07-20).

    턴 진행 중에도 입력 프레임이 화면 하단에 상주하고 스트리밍 출력은 그 위로 삽입된다.
    pt 프롬프트와 같은 프레임(골드 캡·라운드 박스·상태줄)을 그려 턴 사이 시각 연속성을 만들고,
    실제 편집은 턴 종료 후 pt가 같은 자리에서 이어받는다.

    하단 고정: mount가 CPR로 커서 행을 얻어 프레임을 처음부터 화면 마지막 HEIGHT 행에 놓는다
    (흐름이 위면 무스크롤 절대 배치, 겹치면 부족분만 스크롤, CPR 미응답이면 최하단 점프 폴백) —
    제출 직후 프레임이 본문 흐름 위치로 붙었다가 밀려 내려오는 점프를 없앤다.

    라이브 입력: 턴 중 리더 스레드가 stdin(cbreak)을 소유해 타이핑을 독 입력행에 즉시 표시한다
    (이스케이프·CPR 잔여는 스크럽 — 커널 버퍼 방치로 다음 프롬프트가 오염되는 것을 차단).
    턴 종료 시 run()이 take_pending()으로 초안을 회수해 pt 프롬프트에 프리필하고,
    트레일링 ⏎ 는 제출 의사로 보고 자동 제출한다.

    커서 계약: 유휴 시 입력행 캐럿 뒤 파킹 — 사용자가 보는 깜빡임이 곧 타이핑 지점이다.
    내부 소거 원점은 여전히 스페이서 행(_IN 행 위): write()는 스페이서로 올라가 아래를 지우고
    출력을 삽입한 뒤 독을 다시 그린다 — 자연 스크롤이라 스크롤백이 보존된다 (DECSTBM 기각).
    리사이즈·CJK 랩으로 파킹이 틀어져도 다음 redraw의 전체 소거가 복원한다.
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
        self._pending = ""  # 턴 중 타이핑 초안 — take_pending()으로 회수
        self.mounted = False

    def mount(self) -> None:
        import threading

        with self._lock:
            # 제출된 입력 박스는 pt가 통째로 지운다(erase_when_done) — 여기선 독 프레임만 그린다.
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
        if sys.stdin.isatty():  # 라이브 입력 리더 — mount의 CPR 소비가 끝난 뒤에만 stdin 소유
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
            # 소거→삽입→재드로우를 단일 write로 원자화 — 라인버퍼 중간 flush로 소거 상태가
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
        if winterm.IS_WINDOWS:  # select는 Windows에서 소켓 전용 — fd를 주면 첫 턴에 스레드가 죽는다
            return self._read_keys_win()
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

    def _read_keys_win(self) -> None:
        """Windows 키 리더 — 콘솔을 한 글자씩 폴링해 POSIX와 같은 _decode_keys에 얹는다.
        VT 입력이 켜져 있으면 화살표가 ESC 시퀀스로 쪼개져 오는데, carry가 미완성 접두를
        들고 있다가 완성되는 순간 폐기하므로 초안에 쓰레기가 섞이지 않는다."""
        carry = b""
        while not self._stop_reader.is_set():
            chunk = winterm.poll_key()
            if not chunk:
                continue
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
        secs = time.monotonic() - self._t0
        tail = f" · {secs:.0f}s" if secs >= 1 else ""
        budget = max(10, ui.term_cols() - 8 - len(tail))  # 랩 방지 절단 (ui.spin과 동일 규칙)
        # 단일 물리 행 불변식 — 상태 행 페인트는 고정 커서 산술(_paint_status)이라 개행이
        # 살아 나가면 박스 보더를 덮어쓴다. 호출측 클램프와 별개로 여기서 최종 방어.
        label = ui.oneline(self._label, budget)
        return f"  {ui.lantern(self._frame)} {label}{ui.dim(tail)}"

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
    termios 없는 플랫폼은 None (호출부가 폴백). ECHO·ICANON을 잠깐 내려 응답만 소비한다 —
    Enter 직후 ~100ms 창이라 선타이핑 유실 위험은 실질 0."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    if winterm.IS_WINDOWS:  # 콘솔에 직접 물어본다 — 왕복도 타임아웃도 없다
        return winterm.cursor_row()
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
    ISIG는 유지 — Ctrl-C 턴 중단 계약 불변. termios 없는 플랫폼·non-tty는 no-op."""
    from contextlib import contextmanager

    if winterm.IS_WINDOWS:  # 같은 계약을 콘솔 모드로 (ENABLE_PROCESSED_INPUT 유지 = ISIG 유지)
        return winterm.cbreak()

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
