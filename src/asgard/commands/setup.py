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
    cursor_git_guard,
    cursor_hooks_json,
    cursor_rule,
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
        for p in existing:
            ui.fail(f"exists {ui.dim(rel(p))}")
        sys.stderr.write(f"  {ui.dim('--force to overwrite · --dry-run to preview')}\n")
        return 2

    ui.head(label)
    if dry_run:
        for p, _ in files:
            ui.step(f"would create {ui.dim(rel(p))}")
        return 0

    for p, content in files:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(content)
        ui.ok(ui.dim(rel(p)))
    sys.stdout.write(
        f"\n  {ui.paint('32', '✔')} {ui.bold('done')} {ui.dim(f'— {len(files)} file(s) · make anything, your way')}\n"
    )
    return 0


def run_setup(cc: bool = False, cursor: bool = False, codex: bool = False,
              profile: str | None = None, force: bool = False, dry_run: bool = False) -> int:
    cc = cc or profile == "claude-code"
    cursor = cursor or profile == "cursor"
    codex = codex or profile == "codex"
    universal = not cc and not cursor and not codex

    root = os.getcwd()
    name = os.path.basename(root)
    j = os.path.join
    files: list[tuple[str, str]] = [(j(root, "AGENTS.md"), agents_md(name))]

    # Claude Code — bridge when universal or targeted; full skeleton only when targeted (--cc).
    if universal or cc:
        files.append((j(root, ".claude", "CLAUDE.md"), "@../AGENTS.md\n"))
    if cc:
        files += [
            (j(root, ".claude", "settings.json"), cc_settings()),
            (j(root, ".claude", ".gitignore"), "settings.local.json\n"),
        ]
        for d, desc in CC_FOLDERS:
            files.append((j(root, ".claude", d, "README.md"), f"# .claude/{d}/\n\n{desc}\n"))
        files += [
            (j(root, ".claude", "hooks", "git-guard.py"), git_guard()),
            (j(root, ".claude", "hooks", "secret-guard.py"), secret_guard()),
        ]

    # Cursor — always-apply rule bridge when universal or targeted; skeleton + guard only when targeted.
    if universal or cursor:
        files.append((j(root, ".cursor", "rules", "000-agents.mdc"), cursor_rule()))
    if cursor:
        for d, desc in CURSOR_FOLDERS:
            files.append((j(root, ".cursor", d, "README.md"), f"# .cursor/{d}/\n\n{desc}\n"))
        files += [
            (j(root, ".cursor", "hooks.json"), cursor_hooks_json()),
            (j(root, ".cursor", "hooks", "git-guard.py"), cursor_git_guard()),
        ]

    # Codex reads root AGENTS.md natively — --codex adds config + a PreToolUse git-guard + native rules.
    if codex:
        files += [
            (j(root, ".codex", "config.toml"), codex_config()),
            (j(root, ".codex", "hooks", "git-guard.py"), git_guard()),
            (j(root, ".codex", "rules", "canon.rules"), codex_rules()),
        ]

    tools = [t for t, on in (("claude-code", cc), ("cursor", cursor), ("codex", codex)) if on]
    label = "universal setup (AGENTS.md — all agents)" if universal else f"setup — AGENTS.md + {', '.join(tools)}"
    return _scaffold(files, label, force, dry_run)


def run_init(force: bool = False, dry_run: bool = False) -> int:
    return run_setup(cc=True, force=force, dry_run=dry_run)
