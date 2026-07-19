"""풀스크린 TUI 뼈대 — textual.

readline REPL(repl.py)의 한계(단일라인, 박스 입력창 불가)를 넘는다. 레이아웃:
  배너(로고) · 메시지 영역(RichLog, 스크롤) · 입력박스(하단) · 상태바(provider·model).

Heimdall.handle 은 동기 블로킹(API 스트림)이므로 run_worker(thread=True)로 돌리고, on_text
콜백은 app.call_from_thread 로 RichLog 를 갱신한다 — UI 스레드를 막지 않는다.

--plain(readline REPL)은 repl.run 이 그대로 유지 (SSH·비-tty·최소 환경 폴백).
"""

from __future__ import annotations

import threading
from functools import partial

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Resize
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Input, OptionList, RichLog, Static

from .. import theme
from ..i18n import t
from . import repl as _repl

_O = theme.PRIMARY  # 브랜드 골드 (신성한 황금)


class CommandInput(Input):
    BINDINGS = [*Input.BINDINGS, Binding("tab", "cursor_right", show=False)]


def _brand_banner(compact: bool) -> str:
    if compact:
        return f"[b {_O}]{_repl._LOGO_SLIM}[/b {_O}]\n[dim]{t('tagline')}[/dim]"
    logo = "\n".join(
        f"  [{theme.LOGO_GRAD[i] if i < len(theme.LOGO_GRAD) else theme.LOGO_GRAD[-1]}]{line}[/]"
        for i, line in enumerate(_repl._LOGO.splitlines())
    )
    return f"{logo}\n  [dim]{t('tagline')}[/dim]"


class ChoiceModal(ModalScreen[str | None]):
    CSS = """
    ChoiceModal { align: center middle; background: $background 70%; }
    #choice-dialog { width: 80; max-width: 90%; height: 80%; padding: 1 2; border: round $primary; background: $surface; }
    #choice-title { height: 2; }
    #choice-options { height: 1fr; border: none; }
    #choice-manual { height: 3; margin-top: 1; }
    #choice-hint { height: 1; color: $text-muted; }
    """
    BINDINGS = [Binding("escape", "cancel", "cancel")]

    def __init__(
        self,
        title: str,
        choices: list[tuple[str, str]],
        *,
        current: str = "",
        manual_placeholder: str | None = None,
    ) -> None:
        super().__init__()
        self.picker_title = title
        self.choices = choices
        self.current = current
        self.manual_placeholder = manual_placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="choice-dialog"):
            yield Static(f"[b]{escape(self.picker_title)}[/b]", id="choice-title")
            yield OptionList(*[label for label, _ in self.choices], id="choice-options")
            if self.manual_placeholder:
                yield Input(placeholder=self.manual_placeholder, id="choice-manual")
            yield Static(
                t("tui_picker_manual_hint") if self.manual_placeholder else t("tui_picker_hint"),
                id="choice-hint",
            )

    def on_mount(self) -> None:
        options = self.query_one("#choice-options", OptionList)
        options.highlighted = next(
            (i for i, (_, value) in enumerate(self.choices) if value == self.current),
            0 if self.choices else None,
        )
        if self.choices:
            options.focus()
        elif self.manual_placeholder:
            self.query_one("#choice-manual", Input).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.choices[event.option_index][1])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ProviderFormModal(ModalScreen[dict[str, str] | None]):
    CSS = """
    ProviderFormModal { align: center middle; background: $background 70%; }
    #provider-form { width: 70; max-width: 90%; height: auto; padding: 1 2; border: round $primary; background: $surface; }
    #provider-title { height: 2; }
    #provider-error { height: 1; color: $error; }
    #provider-submit { margin-top: 1; }
    #provider-hint { height: 1; margin-top: 1; color: $text-muted; }
    """
    BINDINGS = [Binding("escape", "cancel", "cancel")]

    def __init__(self, profile) -> None:
        super().__init__()
        self.profile = profile

    def compose(self) -> ComposeResult:
        with Vertical(id="provider-form"):
            yield Static(f"[b]{escape(self.profile.display)}[/b]", id="provider-title")
            yield Input(placeholder=t("api_key_prompt", p=self.profile.display), password=True, id="provider-key")
            if self.profile.api_mode == "openai_compat" and not self.profile.base_url:
                yield Input(placeholder="base_url", id="provider-base-url")
            if not self.profile.default_model:
                yield Input(placeholder=t("model_id_prompt"), id="provider-model")
            yield Static("", id="provider-error")
            yield Button(t("tui_connect"), variant="primary", id="provider-submit")
            yield Static(t("tui_form_hint"), id="provider-hint")

    def on_mount(self) -> None:
        self.query_one("#provider-key", Input).focus()

    def _submit(self) -> None:
        fields = {field.id: field.value.strip() for field in self.query(Input)}
        required = ["provider-key"]
        if self.profile.api_mode == "openai_compat" and not self.profile.base_url:
            required.append("provider-base-url")
        if not self.profile.default_model:
            required.append("provider-model")
        missing = next((field_id for field_id in required if not fields.get(field_id)), None)
        if missing:
            self.query_one("#provider-error", Static).update(t("tui_required"))
            self.query_one(f"#{missing}", Input).focus()
            return
        self.dismiss(
            {
                "api_key": fields.get("provider-key", ""),
                "base_url": fields.get("provider-base-url", ""),
                "model": fields.get("provider-model", ""),
            }
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        inputs = list(self.query(Input))
        index = inputs.index(event.input)
        if index + 1 < len(inputs):
            inputs[index + 1].focus()
        else:
            self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "provider-submit":
            self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)


class AsgardTUI(App):
    TITLE = "ASGARD"
    SUB_TITLE = "Heimdall"
    CSS = """
    Screen { background: $surface; }
    #masthead {
        height: 8;
        padding: 0;
        background: $background;
        border-bottom: solid $hairline;
    }
    #log {
        height: 1fr;
        margin: 1 2 0 2;
        padding: 1 2;
        border: round $hairline;
        background: $background;
        scrollbar-color: $primary;
        scrollbar-color-hover: $accent;
        scrollbar-background: $surface;
    }
    #composer {
        height: 5;
        margin: 0 2 1 2;
        padding: 0 1;
        border: round $hairline;
        border-left: thick $primary;
        background: $background;
    }
    #prompt-label { height: 1; color: $subtext; }
    #input { height: 3; border: none; background: $background; padding: 0; }
    #input:focus { border: none; }
    #status { dock: bottom; height: 1; background: $panel; color: $text-muted; padding: 0 2; }
    """.replace("$hairline", theme.HAIRLINE).replace("$subtext", theme.SUBTEXT)
    BINDINGS = [
        Binding("ctrl+q", "quit", "quit"),
        Binding("ctrl+c", "interrupt", "interrupt", show=False),
    ]

    def __init__(self, root: str, rp, cont: bool = False):
        super().__init__()
        self.root = root
        self.rp = rp
        self._cont = cont
        self._turn_lock = threading.Lock()
        self._turn_running = False
        # 스트림 코얼레싱 — 청크당 RichLog 줄 생성 대신 개행 경계로 묶어 쓴다 (UI 스레드 부하·조각화 방지)
        self._stream_lock = threading.Lock()
        self._stream_buf = ""
        # 활동 스트립 — busy 중에도 텔레메트리를 유지하고 현재 활동(사고·툴)만 서픽스로 교체
        self._activity: str | None = None
        self._busy = False
        self._telemetry_cache: str | None = None
        # ! bash 취소 — Heimdall 밖에서 도는 명령도 ctrl+c 로 죽일 수 있어야 한다
        self._bang_cancel = threading.Event()
        # Heimdall 은 콜백 상태가 전부 준비된 뒤 마지막에 — 생성자가 즉시 on_text(경고)를 방출한다
        self.heimdall = None if rp.missing else _repl._new_heimdall(root, rp, self._emit, self._on_status)

    # ── 레이아웃 ─────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Static(_brand_banner(compact=False), id="masthead")
        yield RichLog(id="log", wrap=True, markup=True, highlight=False)
        with Vertical(id="composer"):
            yield Static(t("tui_input_label"), id="prompt-label")
            # 슬래시 자동완성 — / 입력 시 인라인 제안(오른쪽 화살표로 수락).
            yield CommandInput(
                placeholder=t("tui_input_placeholder"),
                id="input",
                suggester=SuggestFromList(_repl._COMMANDS, case_sensitive=False),
            )
        yield Static(self._status_line(), id="status")

    def on_mount(self) -> None:
        self.register_theme(theme.textual_theme())
        self.theme = "asgard"
        self._update_masthead(self.size.width)
        self.query_one("#input", Input).focus()
        self._show_welcome()
        # 미연결 안내는 하단 status bar(⚠ not connected)가 표현 — log 중복 없음
        if self._cont and self.heimdall is not None and hasattr(self.heimdall, "restore_history"):
            n = self.heimdall.restore_history()
            if n:
                self.query_one("#log", RichLog).write(f"[dim]{t('continue_restored', n=n)}[/dim]")

    def on_resize(self, event: Resize) -> None:
        self._update_masthead(event.size.width)

    def _update_masthead(self, width: int) -> None:
        masthead = self.query_one("#masthead", Static)
        compact = width < 100
        masthead.update(_brand_banner(compact))
        masthead.styles.height = 4 if compact else 8

    def _show_welcome(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write(f"[b {_O}]HEIMDALL[/b {_O}]  [{theme.SUCCESS}]● {t('tui_ready')}[/{theme.SUCCESS}]")
        log.write(f"[b]{t('tui_intro')}[/b]")
        log.write(f"[dim]{t('tui_tip')}[/dim]")

    def _telemetry(self) -> str:
        """안정 텔레메트리(모델·경로·git·lagom·토큰·캐시) — busy 중엔 캐시 재사용.
        _git_status 가 서브프로세스(≤3s)라 상태 이벤트마다 재계산하면 UI 가 언다."""
        if self._busy and self._telemetry_cache is not None:
            return self._telemetry_cache
        usage = None
        if self.heimdall is not None:
            usage = {
                "tokens": getattr(self.heimdall, "total_tokens", 0),
                "context": getattr(self.heimdall, "last_context_tokens", 0),
                "cache_read": getattr(self.heimdall, "cache_read_tokens", 0),
                "cache_prompt": getattr(self.heimdall, "cache_prompt_tokens", 0),
            }
        parts = []
        for txt, color, bold in _repl._status_segments(self.root, self.rp, usage):
            style = f"b {color}" if bold else color
            parts.append(f"[{style}]{escape(txt)}[/{style}]")
        self._telemetry_cache = "   ".join(parts)
        return self._telemetry_cache

    def _status_line(self, busy: bool = False) -> str:
        chip = f"[b {_O}]⠶ ASGARD[/b {_O}]"
        if busy:
            act = self._activity or t("busy")
            return f" {chip}   [b {_O}]● {escape(act)}[/b {_O}]   {self._telemetry()}   [dim]{t('tui_busy_hint')}[/dim]"
        return f" {chip}   {self._telemetry()}"

    def _set_status(self, busy: bool) -> None:
        self._busy = busy
        if not busy:
            self._activity = None
            self._telemetry_cache = None  # 턴 종료 — 다음 렌더에서 토큰·git 최신화
        self.query_one("#status", Static).update(self._status_line(busy))
        input_box = self.query_one("#input", Input)
        input_box.disabled = busy
        if not busy:
            input_box.focus()

    # ── 활동 신호 (session.on_status, thread → UI) ──────────────────────
    def _on_status(self, s: str | None) -> None:
        try:
            self.call_from_thread(self._set_activity, s)
        except Exception:
            pass

    def _set_activity(self, s: str | None) -> None:
        if s == self._activity:
            return
        self._activity = s
        if self._busy:
            self.query_one("#status", Static).update(self._status_line(True))

    # ── Heimdall 스트리밍 브리지 (thread → UI) ──────────────────────────
    def _emit(self, s: str) -> None:
        # on_text 콜백 — worker thread 에서 호출됨. 개행 경계까지 모았다가 한 번에 넘긴다.
        with self._stream_lock:
            self._stream_buf += s
            if "\n" not in self._stream_buf:
                return
            lines, _, rest = self._stream_buf.rpartition("\n")
            self._stream_buf = rest
        try:
            self.call_from_thread(self._append_stream, lines)
        except Exception:
            pass

    def _flush_stream(self) -> None:
        """턴 종료 시 잔여 버퍼 방출 — 개행 없이 끝난 마지막 조각 유실 방지."""
        with self._stream_lock:
            rest, self._stream_buf = self._stream_buf, ""
        if rest.strip():
            self._append_stream(rest)

    def _append_stream(self, s: str) -> None:
        # 모델·툴 출력은 불신 텍스트 — Rich 마크업 해석 금지, ANSI 색만 복원 (Text.from_ansi)
        self.query_one("#log", RichLog).write(Text.from_ansi(s), expand=True)

    def _append(self, s: str) -> None:
        self.query_one("#log", RichLog).write(s, expand=True)

    @work(thread=True, exclusive=True)
    def _dispatch(self, req: str) -> None:
        import time

        assert self.heimdall is not None  # 입력 핸들러가 None 가드 후에만 디스패치
        t0 = time.monotonic()
        try:
            out = self.heimdall.handle(req)
            self.call_from_thread(self._flush_stream)
            if out:
                self.call_from_thread(self._append_stream, "\n" + out)
            # 턴 요약 한 줄
            self.call_from_thread(self._append, f"[dim]✓ done · {self.rp.model} · {time.monotonic() - t0:.1f}s[/dim]")
        except Exception as e:
            self.call_from_thread(self._append, f"[red]⚠ {t('session_error', e=e)}[/red]")
        finally:
            self.call_from_thread(self._flush_stream)
            self.call_from_thread(self._set_status, False)
            with self._turn_lock:
                self._turn_running = False

    # ── 입력 처리 ────────────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        req = event.value.strip()
        self.query_one("#input", Input).value = ""
        if not req:
            return
        log = self.query_one("#log", RichLog)
        command = req.startswith(("/", "!"))
        label = t("tui_command") if command else t("tui_you")
        color = theme.ACCENT_BLUE if command else _O
        log.write(f"\n[b {color}]{label}[/b {color}]\n{escape(req)}")

        if req in ("/exit", "/quit"):
            self.exit()
            return
        with self._turn_lock:
            if self._turn_running:
                log.write("[yellow]⚠ 이전 턴이 아직 실행 중입니다. 완료 후 다시 요청하세요.[/yellow]")
                return
        if req == "/clear":
            log.clear()
            self._show_welcome()
            return
        if req == "/new":
            log.clear()
            self.heimdall = (
                None if self.rp.missing else _repl._new_heimdall(self.root, self.rp, self._emit, self._on_status)
            )
            self._show_welcome()
            return
        if req.startswith("!"):
            with self._turn_lock:
                self._turn_running = True
            self._bang_cancel.clear()
            self._set_status(True)
            self._dispatch_bang(req[1:].strip())
            return
        if req.startswith("/"):
            try:
                self._handle_slash(req)
            except Exception as exc:
                log.write(f"[red]⚠ {escape(str(exc))}[/red]")
            return

        if self.heimdall is None:  # 키 없음 — 온보딩 강제 진입 대신 안내 (/provider set 으로 명시적 연결)
            log.write(f"[yellow]⚠ {t('connect_needed')}[/yellow]")
            return
        ev = getattr(self.heimdall, "cancel_event", None)  # 제출측 clear — handle() 진입 전 ctrl+c 보존
        if ev is not None:
            ev.clear()
        with self._turn_lock:
            self._turn_running = True
        log.write(f"\n[b {theme.ACCENT_CYAN}]{t('tui_heimdall')}[/b {theme.ACCENT_CYAN}]")
        self._set_status(True)
        self._dispatch(req)

    def _replace_provider(self, new, message: str | None = None) -> None:
        self.rp = new
        self.heimdall = None if new.missing else _repl._new_heimdall(self.root, new, self._emit, self._on_status)
        self._set_status(False)
        log = self.query_one("#log", RichLog)
        if new.missing:
            log.write(f"[yellow]⚠ {escape('; '.join(new.missing))}[/yellow]")
        else:
            detail = message or f"{new.profile.display} · {new.model} {t('connected')}"
            log.write(f"[{_O}]✔[/{_O}] {escape(detail)}")

    def _open_provider_picker(self) -> None:
        from ..providers import PROVIDERS

        choices = [
            (f"{profile.display} · {profile.default_model or t('needs_base_url')}", name)
            for name, profile in PROVIDERS.items()
        ]
        self.push_screen(
            ChoiceModal(t("pick_provider"), choices, current=self.rp.profile.name), self._provider_selected
        )

    def _provider_selected(self, name: str | None) -> None:
        if not name:
            return
        from ..providers import PROVIDERS

        profile = PROVIDERS[name]
        if profile.api_mode == "codex_responses":
            self._set_status(True)
            self._connect_subscription(name)
        elif profile.key_optional:
            self._activate_provider(name, {})
        else:
            self.push_screen(ProviderFormModal(profile), partial(self._activate_provider, name))

    def _activate_provider(self, name: str, values: dict[str, str] | None) -> None:
        if values is None:
            return
        from ..providers import resolve, save_config_section, save_credential
        from .onboard import _provider_values

        try:
            key, base_url = values.get("api_key", ""), values.get("base_url", "")
            if key or base_url:
                save_credential(name, key, base_url=base_url)
            selected = resolve(self.root, provider=name, model=values.get("model") or None)
            save_config_section(self.root, "provider", _provider_values(self.root, selected))
            self._replace_provider(resolve(self.root, provider=name))
        except Exception as exc:
            self._set_status(False)
            self._append(f"[red]⚠ {escape(str(exc))}[/red]")

    @work(thread=True)
    def _connect_subscription(self, name: str) -> None:
        from .. import openai_codex

        try:
            tokens = openai_codex.device_login(
                lambda message: self.call_from_thread(self._append, f"[dim]{escape(message)}[/dim]")
            )
            openai_codex.save_tokens(tokens)
            self.call_from_thread(self._activate_provider, name, {})
        except openai_codex.OAuthError as exc:
            self.call_from_thread(self._append, f"[red]⚠ {escape(str(exc))}[/red]")
            self.call_from_thread(self._set_status, False)
        except Exception as exc:
            self.call_from_thread(self._append, f"[red]⚠ {escape(str(exc))}[/red]")
            self.call_from_thread(self._set_status, False)

    def _open_model_picker(self) -> None:
        self._set_status(True)
        self._load_models()

    @work(thread=True)
    def _load_models(self) -> None:
        from ..providers import provider_models

        fallback_reasons: list[str] = []
        try:
            models = provider_models(self.rp, on_fallback=fallback_reasons.append)
            self.call_from_thread(self._show_model_picker, models, fallback_reasons)
        except Exception as exc:
            self.call_from_thread(self._append, f"[red]⚠ {escape(str(exc))}[/red]")
            self.call_from_thread(self._set_status, False)

    def _show_model_picker(self, models: list[str], fallback_reasons: list[str]) -> None:
        self._set_status(False)
        if fallback_reasons:
            self._append(f"[yellow]⚠ {escape(t('model_catalog_fallback'))}[/yellow]")
        manual = None if self.rp.profile.api_mode == "codex_responses" else t("model_id_prompt")
        self.push_screen(
            ChoiceModal(
                t("pick_model"),
                [(model, model) for model in models],
                current=self.rp.model,
                manual_placeholder=manual,
            ),
            self._model_selected,
        )

    def _model_selected(self, model: str | None) -> None:
        if not model:
            return
        from .onboard import select_model_id

        try:
            selected = select_model_id(self.root, self.rp, model)
            if selected is None:
                self._append(f"[yellow]⚠ {t('invalid_model_id')}[/yellow]")
                return
            self._replace_provider(selected)
        except Exception as exc:
            self._append(f"[red]⚠ {escape(str(exc))}[/red]")

    def _open_role_picker(self) -> None:
        from ..providers import TRINITY_ROLES

        choices = [(role, role) for role in TRINITY_ROLES]
        self.push_screen(ChoiceModal(t("pick_role"), choices, current="worker"), self._trinity_role_selected)

    def _trinity_role_selected(self, role: str | None) -> None:
        if not role:
            return
        from ..providers import PROVIDERS

        choices = [(t("placement_clear"), "")] + [
            (f"{profile.display} · {profile.default_model or t('needs_base_url')}", name)
            for name, profile in PROVIDERS.items()
        ]
        self.push_screen(
            ChoiceModal(t("pick_provider"), choices),
            partial(self._trinity_provider_selected, role),
        )

    def _trinity_provider_selected(self, role: str, name: str | None) -> None:
        if name is None:
            return
        if not name:
            self._save_trinity(role, "", "")
            return
        self._set_status(True)
        self._load_trinity_models(role, name)

    @work(thread=True)
    def _load_trinity_models(self, role: str, name: str) -> None:
        from ..providers import provider_models, resolve

        try:
            placed = resolve(self.root, provider=name)
            models = provider_models(placed)
            self.call_from_thread(self._show_trinity_model_picker, role, name, placed.model, models)
        except Exception as exc:
            self.call_from_thread(self._append, f"[red]⚠ {escape(str(exc))}[/red]")
            self.call_from_thread(self._set_status, False)

    def _show_trinity_model_picker(self, role: str, name: str, current: str, models: list[str]) -> None:
        self._set_status(False)
        self.push_screen(
            ChoiceModal(
                t("pick_model"),
                [(model, model) for model in models],
                current=current,
                manual_placeholder=t("model_id_prompt"),
            ),
            partial(self._save_trinity, role, name),
        )

    def _save_trinity(self, role: str, name: str, model: str | None) -> None:
        if name and not model:
            return
        from ..providers import save_config_section

        try:
            if name:
                save_config_section(self.root, f"trinity.{role}", {"provider": name, "model": model})
                message = t("placement_saved")
            else:
                save_config_section(self.root, f"trinity.{role}", None)
                message = t("placement_cleared")
            self.heimdall = (
                None if self.rp.missing else _repl._new_heimdall(self.root, self.rp, self._emit, self._on_status)
            )
            self._set_status(False)
            self._append(f"[{_O}]✔[/{_O}] {escape(message)}")
        except Exception as exc:
            self._set_status(False)
            self._append(f"[red]⚠ {escape(str(exc))}[/red]")

    def _capture_repl_command(self, command) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        output = StringIO()
        with redirect_stdout(output):
            command()
        rendered = output.getvalue()
        if rendered:
            self.query_one("#log", RichLog).write(Text.from_ansi(rendered))

    def _start_update(self, args: list[str]) -> None:
        with self._turn_lock:
            self._turn_running = True
        self._set_status(True)
        self._dispatch_update(args)

    @work(thread=True)
    def _dispatch_update(self, args: list[str]) -> None:
        import os
        import subprocess
        import sys

        env = dict(os.environ, NO_COLOR="1")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "asgard", "update", *args],
                cwd=self.root,
                env=env,
                capture_output=True,
                text=True,
            )
            output = (result.stdout + result.stderr).strip()
            if output:
                self.call_from_thread(self._append, escape(output))
        except Exception as exc:
            self.call_from_thread(self._append, f"[red]⚠ {escape(str(exc))}[/red]")
        finally:
            self.call_from_thread(self._set_status, False)
            with self._turn_lock:
                self._turn_running = False

    @work(thread=True)
    def _dispatch_bang(self, cmd: str) -> None:
        from ..hooks.readonly_guard import is_readonly_bash_safe
        from . import tools as T

        try:
            if not is_readonly_bash_safe(cmd, self.root):
                self.call_from_thread(
                    self._append,
                    "[yellow]⚠ ! 명령은 읽기 전용만 허용됩니다. 변경 작업은 일반 요청으로 실행하세요.[/yellow]",
                )
                return
            out, code = T.run_bash(self.root, {"command": cmd}, cancel=self._bang_cancel)
            self.call_from_thread(self._append, f"[dim]$ {escape(cmd)}[/dim]")
            self.call_from_thread(self._append_stream, out)
        except T.ToolError as e:
            self.call_from_thread(self._append, f"[red]⚠ {e}[/red]")
        finally:
            self.call_from_thread(self._set_status, False)
            with self._turn_lock:
                self._turn_running = False

    def _handle_slash(self, req: str) -> None:
        log = self.query_one("#log", RichLog)
        c = req.split()[0]
        if c == "/help":
            log.write(f"\n[b]{t('tui_help_title')}[/b]")
            for k, v in _repl._help_items():
                log.write(f"[{_O}]{k}[/{_O}]  [dim]{v}[/dim]")
            log.write(f"\n[dim]{t('tui_completion_hint')}[/dim]")
        elif c == "/provider" and req.split()[1:2] == ["set"]:
            self._open_provider_picker()
        elif c == "/provider":
            log.write(
                f"[{_O}]{self.rp.profile.display}[/{_O}] · {self.rp.model} [dim]({self.rp.key_source or self.rp.source})[/dim]"
            )
        elif c == "/model":
            self._open_model_picker()
        elif c == "/trinity":
            if req.split()[1:2] == ["set"]:
                self._open_role_picker()
            else:
                from ..providers import resolve_trinity

                for role, placed in resolve_trinity(self.root, self.rp).items():
                    tag = f" [dim]{t('default_tag')}[/dim]" if placed is self.rp else ""
                    warning = f" [yellow]⚠ {'; '.join(placed.missing)}[/yellow]" if placed.missing else ""
                    log.write(f"[{_O}]{role.ljust(9)}[/{_O}] {placed.profile.name}:{placed.model}{tag}{warning}")
        elif c == "/update":
            self._start_update(req.split()[1:])
        elif c == "/bridge":
            self._capture_repl_command(lambda: _repl._cmd_bridge(req, self.root))
        elif c == "/lagom":
            try:
                self._capture_repl_command(lambda: _repl._cmd_lagom(req, self.root, self.rp))
            except _repl._Reconfigure as changed:
                self.rp = changed.rp
                self.heimdall = (
                    None
                    if changed.rp.missing
                    else _repl._new_heimdall(self.root, changed.rp, self._emit, self._on_status)
                )
                self._set_status(False)
                log.write(f"[{_O}]✔[/{_O}] {escape(changed.msg or '')}")
        elif c == "/lang":
            from ..i18n import save_lang

            arg = req.split()[1:2]
            if arg and save_lang(arg[0], self.root):
                self._set_status(False)
                log.write(f"[{_O}]✔[/{_O}] {t('lang_set', lang=arg[0])} [dim](/new 로 배너 갱신)[/dim]")
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
        with self._turn_lock:
            running = self._turn_running
        log = self.query_one("#log", RichLog)
        if running:
            self._bang_cancel.set()  # ! bash 경로 — Heimdall 밖에서 도는 명령도 함께 중단
            h = self.heimdall
            if h is not None and hasattr(h, "cancel"):
                h.cancel()
            log.write(f"[yellow]⚠ {t('tui_cancel_requested')}[/yellow]")
            return
        log.write(f"[dim]{t('turn_interrupted')}[/dim]")


def run(root: str, rp, cont: bool = False) -> int:
    AsgardTUI(root, rp, cont=cont).run()
    return 0
