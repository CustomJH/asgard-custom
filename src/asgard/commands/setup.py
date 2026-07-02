"""setup / init — scaffold a project. AGENTS.md is always canonical; a tool flag scopes the setup to
that tool (nothing for the others); no flag wires every agent (universal). Flags combine. Generated
content is byte-identical to the TS version; hooks are Python (.py) wired via python3."""

import os
import sys
from pathlib import Path

from .. import ui
from ..templates import (
    CC_FOLDERS,
    CURSOR_FOLDERS,
    agents_md,
    cc_settings,
    codex_config,
    codex_rules,
    cursor_failure_tracker,
    cursor_git_guard,
    cursor_hooks_json,
    cursor_rule,
    failure_tracker,
    git_guard,
    secret_guard,
)


def _scaffold(files: list[tuple[str, str]], label: str, force: bool, dry_run: bool) -> int:
    cwd = os.getcwd()

    def rel(p: str) -> str:
        return p[len(cwd) + 1:] if p.startswith(cwd + os.sep) else p

    existing = [p for p, _ in files if os.path.lexists(p)]
    if existing and not force and not dry_run:
        ui.head(label)
        ui.phase("check · existing files")
        for p in existing:
            ui.fail(f"exists {ui.dim(rel(p))}")
        sys.stderr.write(f"  {ui.dim('--force to overwrite · --dry-run to preview')}\n")
        return 2

    ui.head(label)
    if dry_run:
        ui.phase(f"preview · {len(files)} file(s)")
        for p, _ in files:
            ui.step(f"would create {ui.dim(rel(p))}")
        return 0

    ui.phase(f"scaffold · {len(files)} file(s)")
    for p, content in files:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(content)
        ui.ok(ui.dim(rel(p)))
    ui.done(f"{len(files)} file(s) · make anything, your way")
    return 0


def plan_files(cc: bool, cursor: bool, codex: bool, root: str | None = None) -> tuple[list[tuple[str, str]], str]:
    """Compute (files, label) a setup would write — pure, no IO. Shared by run_setup and the TUI
    preview so what the onboarding screen shows is exactly what gets scaffolded."""
    universal = not cc and not cursor and not codex
    if universal:  # universal = the full cross-tool Canon setup — every agent wired AND enforced.
        cc = cursor = codex = True
    root = root or os.getcwd()
    name = os.path.basename(root)
    j = os.path.join
    files: list[tuple[str, str]] = [(j(root, "AGENTS.md"), agents_md(name))]

    # Claude Code — bridge import + settings (permission floor + hook wiring) + Canon guards.
    if cc:
        files += [
            (j(root, ".claude", "CLAUDE.md"), "@../AGENTS.md\n"),
            (j(root, ".claude", "settings.json"), cc_settings()),
            (j(root, ".claude", ".gitignore"), "settings.local.json\n"),  # shared hook state lives in root .asgard/ (self-ignored)
        ]
        for d, desc in CC_FOLDERS:
            files.append((j(root, ".claude", d, "README.md"), f"# .claude/{d}/\n\n{desc}\n"))
        files += [
            (j(root, ".claude", "hooks", "git-guard.py"), git_guard()),
            (j(root, ".claude", "hooks", "secret-guard.py"), secret_guard()),
            (j(root, ".claude", "hooks", "failure-tracker.py"), failure_tracker()),
        ]

    # Cursor — rule bridge + skeleton + beforeShellExecution guard + postToolUseFailure tracker.
    if cursor:
        files.append((j(root, ".cursor", "rules", "000-agents.mdc"), cursor_rule()))
        for d, desc in CURSOR_FOLDERS:
            files.append((j(root, ".cursor", d, "README.md"), f"# .cursor/{d}/\n\n{desc}\n"))
        files += [
            (j(root, ".cursor", "hooks.json"), cursor_hooks_json()),
            (j(root, ".cursor", "hooks", "git-guard.py"), cursor_git_guard()),
            (j(root, ".cursor", "hooks", "failure-tracker.py"), cursor_failure_tracker()),
        ]

    # Codex reads root AGENTS.md natively — add config + Pre/PostToolUse hooks + native rules.
    if codex:
        files += [
            (j(root, ".codex", "config.toml"), codex_config()),
            (j(root, ".codex", "hooks", "git-guard.py"), git_guard()),
            (j(root, ".codex", "hooks", "failure-tracker.py"), failure_tracker()),
            (j(root, ".codex", "rules", "canon.rules"), codex_rules()),
        ]

    tools = [t for t, on in (("claude-code", cc), ("cursor", cursor), ("codex", codex)) if on]
    label = "init · universal (all agents, enforced)" if universal else f"init · AGENTS.md + {', '.join(tools)}"
    return files, label


def run_setup(cc: bool = False, cursor: bool = False, codex: bool = False,
              profile: str | None = None, force: bool = False, dry_run: bool = False) -> int:
    cc = cc or profile == "claude-code"
    cursor = cursor or profile == "cursor"
    codex = codex or profile == "codex"
    files, label = plan_files(cc, cursor, codex)
    return _scaffold(files, label, force, dry_run)


# ── init — interactive onboarding (CUS-49, minimal slice). TTY: pick a profile; non-TTY / --yes:
# default to claude-code (back-compat with the old `init` = `setup --cc`). Uses Rich (already a dep);
# no heavy TUI framework yet — the full OpenCode/Hermes-style editor stays scoped to CUS-49.
_PROFILES: list[tuple[str, str]] = [
    ("universal", "every agent — AGENTS.md + full .claude/.cursor/.codex, Canon enforced"),
    ("claude-code", ".claude/ full skeleton + hooks"),
    ("cursor", ".cursor/ rules + hooks"),
    ("codex", ".codex/ config + rules + guard"),
]
_DEFAULT_PROFILE = "claude-code"
_FLAG_OF = {"claude-code": "cc", "cursor": "cursor", "codex": "codex"}


def profile_flags(profile: str) -> dict[str, bool]:
    """Profile name → setup flags. 'universal' = all False (bridges every agent)."""
    return {"cc": profile == "claude-code", "cursor": profile == "cursor", "codex": profile == "codex"}


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _choose_profile() -> str:
    from rich.console import Console
    from rich.prompt import Prompt

    c = Console()
    c.print("\n  [bold]asgard init[/bold] [dim]— choose a setup profile[/dim]")
    for i, (key, desc) in enumerate(_PROFILES, 1):
        c.print(f"    [bold cyan]{i}[/bold cyan]  {key:<12} [dim]{desc}[/dim]")
    default_idx = str(next(i for i, (k, _) in enumerate(_PROFILES, 1) if k == _DEFAULT_PROFILE))
    choice = Prompt.ask("  select", choices=[str(i) for i in range(1, len(_PROFILES) + 1)], default=default_idx)
    return _PROFILES[int(choice) - 1][0]


def _run_profile(profile: str, force: bool, dry_run: bool) -> int:
    if profile == "universal":
        return run_setup(force=force, dry_run=dry_run)
    return run_setup(**{_FLAG_OF[profile]: True}, force=force, dry_run=dry_run)


def run_init(cc: bool = False, cursor: bool = False, codex: bool = False, profile: str | None = None,
             force: bool = False, dry_run: bool = False, yes: bool = False) -> int:
    # Explicit target (flags/--profile) → scaffold it directly, no picker.
    if cc or cursor or codex or profile:
        return run_setup(cc=cc, cursor=cursor, codex=codex, profile=profile, force=force, dry_run=dry_run)
    # No target given: default on non-TTY/--yes; else the full-screen picker.
    if yes or not _interactive():
        return _run_profile(_DEFAULT_PROFILE, force, dry_run)
    # TTY: full-screen Textual onboarding. Textual missing/broken → Rich prompt. None = user cancelled.
    try:
        from ..tui import run_init_tui
        chosen = run_init_tui()
    except Exception:
        chosen = _choose_profile()
    if chosen is None:
        ui.warn("cancelled — nothing written.")
        return 0
    return _run_profile(chosen, force, dry_run)


if __name__ == "__main__":  # ponytail: profile→setup mapping self-check (no framework)
    assert _FLAG_OF["cursor"] == "cursor" and set(_FLAG_OF) == {"claude-code", "cursor", "codex"}
    assert _DEFAULT_PROFILE in dict(_PROFILES)
    print("setup self-check ok")
