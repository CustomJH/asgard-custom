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
from textual.suggester import SuggestFromList
from textual.widgets import Input, RichLog, Static

from . import repl as _repl
from ..i18n import t

_O = "#5fd7d7"  # 브랜드 시안 (서리/얼음)
# 세로 그라디언트 — 다크 배경은 밝은 얼음, 라이트 배경은 진한 청록 (밝은색은 라이트서 안 보임)
_GRAD = ["#afffff", "#87ffff", "#5fd7d7", "#00d7d7", "#00afaf", "#008787"]
_GRAD_LIGHT = ["#008787", "#008787", "#005f5f", "#005f5f", "#005f5f", "#005f5f"]


def _banner(light: bool = False) -> str:
    g = _GRAD_LIGHT if light else _GRAD
    return "\n".join(
        f"  [{g[i] if i < len(g) else g[-1]}]{ln}[/]"
        for i, ln in enumerate(_repl._LOGO.split("\n")))


class AsgardTUI(App):
    CSS = """
    Screen { background: $surface; }
    #logo { height: auto; padding: 1 0 0 0; }  /* 색은 _BANNER markup 그라디언트 */
    #log  { height: 1fr; padding: 0 1; border: none; background: $surface; }
    #status { dock: bottom; height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    #prompt { dock: bottom; height: 3; }
    /* opencode 스타일 — 왼쪽 오렌지 accent bar */
    Input { border: none; border-left: thick #5fd7d7; background: $surface; padding-left: 1; }
    Input:focus { border-left: thick #87ffff; }
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
        yield Static(_banner(_repl.is_light_bg()), id="logo")
        yield RichLog(id="log", wrap=True, markup=True, highlight=False)
        with Vertical(id="prompt"):
            # 슬래시 자동완성 — / 입력 시 인라인 제안(→ 로 수락). CLI readline 의 Tab 대응.
            yield Input(placeholder=t("input_placeholder"), id="input",
                        suggester=SuggestFromList(_repl._COMMANDS, case_sensitive=False))
        yield Static(self._status_line(), id="status")

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()
        log = self.query_one("#log", RichLog)
        log.write(f"[b]{t('welcome')}[/b] [dim]{t('welcome_hint')}[/dim]")
        log.write(f"[#5fd7d7]✦[/#5fd7d7] [dim]{t('tip')}[/dim]")
        if self.heimdall is None:
            log.write(f"[dim]{t('provider_unset')}[/dim]")

    def _status_line(self, busy: bool = False) -> str:
        if busy:
            return f" [#5fd7d7]●[/#5fd7d7] {t('busy')}   [dim]{t('interrupt_hint')}[/dim]"
        # claude-code 식 — 모델 · 디렉토리 · git 브랜치
        import os
        from .repl import _git_status
        home = os.path.expanduser("~")
        cwd = self.root.replace(home, "~", 1) if self.root.startswith(home) else self.root
        parts = [f"◆ {self.rp.model}", f"⌂ {cwd}"]
        br = _git_status(self.root)
        if br:
            parts.append(f"⎇ {br}")
        tok = getattr(self.heimdall, "total_tokens", 0) if self.heimdall else 0
        if tok:
            parts.append(f"↯ {tok / 1000:.1f}k")
        return " [#5fd7d7]▌[/#5fd7d7] [dim]" + "  ".join(parts) + "[/dim]"

    def _set_status(self, busy: bool) -> None:
        self.query_one("#status", Static).update(self._status_line(busy))

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
        self.call_from_thread(self._set_status, True)
        try:
            out = self.heimdall.handle(req)
            if out:
                self.call_from_thread(self._append, "\n" + out)
        except Exception as e:
            self.call_from_thread(self._append, f"[red]⚠ {t('session_error', e=e)}[/red]")
        finally:
            self.call_from_thread(self._set_status, False)

    # ── 입력 처리 ────────────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        req = event.value.strip()
        self.query_one("#input", Input).value = ""
        if not req:
            return
        log = self.query_one("#log", RichLog)
        log.write(f"[#5fd7d7]▌[/#5fd7d7] {req}")

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

        if self.heimdall is None:  # 키 없음 → 온보딩 후 이 요청 이어서 처리
            if self._onboard():
                self._dispatch(req)
            return
        self._dispatch(req)

    def _onboard(self) -> bool:
        """TUI 를 잠깐 suspend → readline onboard 재사용 → resume. 성공 시 True."""
        from .onboard import onboard
        log = self.query_one("#log", RichLog)
        with self.suspend():
            new = onboard(self.root, preselect=self.rp.profile.name if not self.rp.missing else None)
        if new is None or new.missing:
            log.write(f"[dim]{t('connect_cancel')}[/dim]")
            return False
        self.rp = new
        self.heimdall = _repl._new_heimdall(self.root, self.rp, self._emit)
        self._set_status(False)
        log.write(f"[#5fd7d7]✔[/#5fd7d7] {new.profile.display} · {new.model} {t('connected')}")
        return True

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
            for k, v in _repl._help_items():
                log.write(f"[#5fd7d7]{k}[/#5fd7d7]  [dim]{v}[/dim]")
        elif c == "/provider" and req.split()[1:2] == ["set"]:
            self._onboard()
        elif c in ("/provider", "/model"):
            log.write(f"[#5fd7d7]{self.rp.profile.display}[/#5fd7d7] · {self.rp.model} [dim]({self.rp.key_source or self.rp.source})[/dim]")
        elif c == "/lang":
            from ..i18n import save_lang
            arg = req.split()[1:2]
            if arg and save_lang(arg[0], self.root):
                self._set_status(False)
                log.write(f"[#5fd7d7]✔[/#5fd7d7] {t('lang_set', lang=arg[0])} [dim](/new 로 배너 갱신)[/dim]")
            else:
                log.write(f"[dim]{t('lang_usage')}[/dim]")
        elif c == "/quest":
            try:
                out = _repl.ql(self.root, "state").stdout.strip()
                log.write(f"[dim]{out or t('no_quest')}[/dim]")
            except Exception:
                log.write(f"[dim]{t('no_quest')}[/dim]")
        else:
            log.write(f"[yellow]⚠ {t('unknown_cmd', c=c)}[/yellow]")

    def action_interrupt(self) -> None:
        self.workers.cancel_all()
        self._set_status(False)
        self.query_one("#log", RichLog).write(f"[dim]{t('turn_interrupted')}[/dim]")


def run(root: str, rp) -> int:
    AsgardTUI(root, rp).run()
    return 0
