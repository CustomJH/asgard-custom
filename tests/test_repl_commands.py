from __future__ import annotations

import os
from types import SimpleNamespace

from asgard import ui
from asgard.agent import repl


def test_command_catalog_drives_help_and_completion() -> None:
    help_commands = {command for command, _ in repl._help_items()}

    assert help_commands == {command for command in repl._COMMAND_HELP if " " not in command}
    assert repl._completer("/lang", 0) == "/lang "
    assert repl._completion_matches("/") == [c for c in repl._COMMAND_HELP if " " not in c]
    assert repl._completer("/lang ", 0) == "/lang en "
    assert repl._completer("/lagom default", 0) == "/lagom default "


def test_unknown_command_suggests_nearest_command(monkeypatch, capsys) -> None:
    monkeypatch.setattr(ui, "_COLOR", False)

    repl.slash("/modle", ".", None)

    assert "/model" in capsys.readouterr().out


def test_skills_command_lists_only_explicit_workflows(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(ui, "_COLOR", False)

    repl.slash("/skills", str(tmp_path), None)

    out = capsys.readouterr().out
    assert "User skills" in out
    assert "╭─" in out and "╰" in out
    assert "/grill-me" in out
    assert "/to-spec" in out
    assert "/domain-modeling" not in out


def test_exact_skill_slash_reaches_heimdall_as_explicit_prompt(monkeypatch, tmp_path) -> None:
    seen = []

    class Heimdall:
        total_tokens = last_context_tokens = cache_read_tokens = cache_prompt_tokens = 0
        cancel_event = None

        def handle(self, prompt):
            seen.append(prompt)
            return ""

    requests = iter(["/grill-me checkout flow"])

    def ask():
        try:
            return next(requests)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr(repl, "_PT", True)
    monkeypatch.setattr(repl, "banner", lambda _rp: None)
    monkeypatch.setattr(repl, "prompt", ask)
    monkeypatch.setattr(repl, "_new_heimdall", lambda *_args, **_kwargs: Heimdall())
    rp = SimpleNamespace(missing=False, model="test-model")

    assert repl.run(str(tmp_path), rp) == 0
    assert len(seen) == 1
    assert '<user_invoked_skill name="grill-me">' in seen[0]
    assert "Arguments: checkout flow" in seen[0]


def test_banner_uses_compact_mark_on_standard_terminal(monkeypatch, capsys) -> None:
    monkeypatch.setattr(os, "get_terminal_size", lambda _fd=0: os.terminal_size((120, 30)))
    monkeypatch.setattr(ui, "_COLOR", False)

    repl.banner(None)

    out = capsys.readouterr().out
    assert repl._LOGO_SLIM in out
    assert repl._LOGO not in out


def test_completion_menu_reserves_only_visible_rows(monkeypatch, tmp_path) -> None:
    import prompt_toolkit

    seen = {}

    class Session:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(prompt_toolkit, "PromptSession", Session)
    monkeypatch.setattr(repl, "_history_path", lambda: str(tmp_path / "history"))

    repl._pt_session()

    assert seen["reserve_space_for_menu"] == 8
