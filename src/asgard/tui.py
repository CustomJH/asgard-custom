"""Full-screen onboarding TUI for `asgard init` (CUS-49). Textual app: arrow-key profile pick with a
live preview of exactly what will be scaffolded (same plan_files() the writer uses, so preview == result).

Kept thin: the caller (commands.setup.run_init) decides when to launch this vs the Rich-prompt fallback
(non-TTY, or Textual import/run failure). run_init_tui() returns the chosen profile, or None if cancelled."""

from __future__ import annotations

import os

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from .commands.setup import _DEFAULT_PROFILE, _PROFILES, plan_files, profile_flags


def _preview(profile: str) -> str:
    f = profile_flags(profile)
    files, label = plan_files(f["cc"], f["cursor"], f["codex"])
    cwd = os.getcwd()
    lines = [f"[b]{label}[/b]", ""]
    lines += [f"  [green]+[/green] {os.path.relpath(p, cwd)}" for p, _ in files]
    lines += ["", f"[dim]{len(files)} file(s) · enter to create · q to cancel[/dim]"]
    return "\n".join(lines)


class InitApp(App):
    CSS = """
    Horizontal { height: 1fr; }
    #profiles { width: 34; border: round $accent; padding: 0 1; }
    #preview  { width: 1fr; border: round $panel-darken-1; padding: 0 1; }
    """
    BINDINGS = [Binding("q,escape", "cancel", "cancel")]
    TITLE = "asgard init"
    SUB_TITLE = "make anything, your way"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            yield OptionList(
                *[Option(f"{k}", id=k) for k, _ in _PROFILES], id="profiles"
            )
            yield Static(id="preview")
        yield Footer()

    def on_mount(self) -> None:
        ol = self.query_one("#profiles", OptionList)
        default_idx = next((i for i, (k, _) in enumerate(_PROFILES) if k == _DEFAULT_PROFILE), 0)
        ol.highlighted = default_idx
        ol.focus()
        self._refresh_preview(default_idx)

    def _refresh_preview(self, idx: int | None) -> None:
        profile = _PROFILES[idx or 0][0]
        self.query_one("#preview", Static).update(_preview(profile))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._refresh_preview(event.option_index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.exit(event.option.id)  # enter on a row = confirm that profile

    def action_cancel(self) -> None:
        self.exit(None)


def run_init_tui() -> str | None:
    """Run the onboarding app; return chosen profile or None (cancelled). Raises if Textual can't run
    (no tty / import error) — the caller falls back to the Rich prompt."""
    return InitApp().run()


if __name__ == "__main__":  # pilot self-check (needs textual): uv run python -m asgard.tui
    import asyncio

    async def _check() -> None:
        app = InitApp()
        async with app.run_test() as pilot:  # default highlight = claude-code; ↓ = cursor
            await pilot.press("down")
            await pilot.press("enter")
        assert app.return_value == "cursor", app.return_value
        cancel = InitApp()
        async with cancel.run_test() as pilot:
            await pilot.press("q")
        assert cancel.return_value is None, cancel.return_value

    asyncio.run(_check())
    print("tui self-check ok")
