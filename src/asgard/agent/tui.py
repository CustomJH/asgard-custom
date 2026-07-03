"""풀스크린 TUI 뼈대 (CUS-148) — textual. opencode/hermes 급 레이아웃.

readline REPL(repl.py)의 한계(단일라인, 박스 입력창 불가)를 넘는다. 레이아웃:
  배너(로고) · 메시지 영역(RichLog, 스크롤) · 입력박스(하단) · 상태바(provider·model).

Heimdall.handle 은 동기 블로킹(API 스트림)이므로 run_worker(thread=True)로 돌리고, on_text
콜백은 app.call_from_thread 로 RichLog 를 갱신한다 — UI 스레드를 막지 않는다.

--plain(readline REPL)은 repl.run 이 그대로 유지 (SSH·비-tty·최소 환경 폴백).
"""

from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, RichLog, Static

from . import repl as _repl

_O = "#ff8700"  # 브랜드 오렌지 (208)

_BANNER = "\n".join("  " + ln for ln in _repl._LOGO.split("\n"))


class AsgardTUI(App):
    CSS = """
    Screen { background: $surface; }
    #logo { color: #ff8700; height: auto; padding: 1 0 0 0; }
    #meta { color: $text-muted; height: auto; padding: 0 0 1 2; }
    #log  { height: 1fr; padding: 0 1; border: none; background: $surface; }
    #status { dock: bottom; height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    #prompt { dock: bottom; height: 3; border-top: solid #ff8700; }
    Input { border: none; background: $surface; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "quit"),
        Binding("ctrl+c", "interrupt", "interrupt", show=False),
    ]

    def __init__(self, root: str, rp):
        super().__init__()
        self.root = root
        self.rp = rp
        self.heimdall = None if rp.missing else _repl._new_heimdall(root, rp, self._emit)

    # ── 레이아웃 ─────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Static(_BANNER, id="logo")
        yield Static(self._meta_line(), id="meta")
        yield RichLog(id="log", wrap=True, markup=True, highlight=False)
        with Vertical(id="prompt"):
            yield Input(placeholder="메시지를 입력하세요…  ( /help · !bash · Ctrl-Q 종료 )", id="input")
        yield Static(self._status_line(), id="status")

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()
        log = self.query_one("#log", RichLog)
        if self.heimdall is None:
            log.write("[dim]provider 미설정 — 메시지를 보내면 연결을 안내합니다 (/provider set)[/dim]")
        else:
            log.write("[dim]Heimdall 대기 중. 무엇이든 물으세요.[/dim]")

    def _meta_line(self) -> str:
        return f"[b]Heimdall[/b]  [dim]비프로스트의 수호자 · Trinity 오케스트레이터[/dim]"

    def _status_line(self) -> str:
        p = self.rp.profile.display
        return f" [#ff8700]▌[/#ff8700] {p} · {self.rp.model}   [dim]/help · /new · !bash[/dim]"

    # ── Heimdall 스트리밍 브리지 (thread → UI) ──────────────────────────
    def _emit(self, s: str) -> None:
        # on_text 콜백 — worker thread 에서 호출됨. UI 갱신은 메인 스레드로.
        try:
            self.call_from_thread(self._append, s)
        except Exception:
            pass

    def _append(self, s: str) -> None:
        self.query_one("#log", RichLog).write(s, expand=True)

    @work(thread=True, exclusive=True)
    def _dispatch(self, req: str) -> None:
        try:
            out = self.heimdall.handle(req)
            if out:
                self.call_from_thread(self._append, "\n" + out)
        except Exception as e:
            self.call_from_thread(self._append, f"[red]⚠ 세션 오류: {e}[/red]")

    # ── 입력 처리 ────────────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        req = event.value.strip()
        self.query_one("#input", Input).value = ""
        if not req:
            return
        log = self.query_one("#log", RichLog)
        log.write(f"[#ff8700]▌[/#ff8700] {req}")

        if req in ("/exit", "/quit"):
            self.exit()
            return
        if req == "/clear":
            log.clear()
            return
        if req == "/new":
            log.clear()
            self.heimdall = None if self.rp.missing else _repl._new_heimdall(self.root, self.rp, self._emit)
            return
        if req.startswith("!"):
            self._dispatch_bang(req[1:].strip())
            return
        if req.startswith("/"):
            self._handle_slash(req)
            return

        if self.heimdall is None:
            log.write("[yellow]⚠ provider 미설정 — /provider set 으로 연결하세요[/yellow]")
            return
        self._dispatch(req)

    @work(thread=True)
    def _dispatch_bang(self, cmd: str) -> None:
        from . import tools as T
        try:
            out, code = T.run_bash(self.root, {"command": cmd})
            self.call_from_thread(self._append, f"[dim]$ {cmd}[/dim]\n{out}")
        except T.ToolError as e:
            self.call_from_thread(self._append, f"[red]⚠ {e}[/red]")

    def _handle_slash(self, req: str) -> None:
        log = self.query_one("#log", RichLog)
        c = req.split()[0]
        if c == "/help":
            for k, v in _repl._HELP.items():
                log.write(f"[#ff8700]{k}[/#ff8700]  [dim]{v}[/dim]")
        elif c in ("/provider", "/model"):
            log.write(f"[#ff8700]{self.rp.profile.display}[/#ff8700] · {self.rp.model} [dim]({self.rp.key_source or self.rp.source})[/dim]")
        elif c == "/quest":
            try:
                out = _repl.ql(self.root, "state").stdout.strip()
                log.write(f"[dim]{out or '진행 중 퀘스트 없음'}[/dim]")
            except Exception:
                log.write("[dim]진행 중 퀘스트 없음[/dim]")
        else:
            log.write(f"[yellow]⚠ 미지의 커맨드 {c} — /help[/yellow]")

    def action_interrupt(self) -> None:
        self.workers.cancel_all()
        self.query_one("#log", RichLog).write("[dim](턴 중단)[/dim]")


def run(root: str, rp) -> int:
    AsgardTUI(root, rp).run()
    return 0
