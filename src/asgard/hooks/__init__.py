"""Asgard hook library — the single home for hook code (grows as we add hooks).

Each `*.py` here is a REAL, standalone, stdlib-only script: runnable directly (`python3 <file>`) and
testable in isolation, with no escaping and no `asgard` import (it runs inside the *user's* repo). setup
scaffolds a hook by reading its source verbatim via `script(name)` — this package is the abstraction
boundary, so command/template code never embeds hook bodies as escaped strings.

Registry maps a logical hook name → module filename. Add a hook = drop a file here + one REGISTRY entry."""

from importlib import resources

# logical name → filename (without .py). Grouped by tool contract.
REGISTRY: dict[str, str] = {
    # Claude Code + Codex share the same PreToolUse/PostToolUse stdin schema → same scripts.
    "git-guard": "git_guard",
    "secret-guard": "secret_guard",
    "failure-tracker": "failure_tracker",
    # Cursor's hook contract differs (top-level .command / postToolUseFailure) → its own scripts.
    "cursor-git-guard": "cursor_git_guard",
    "cursor-failure-tracker": "cursor_failure_tracker",
}


def script(name: str) -> str:
    """Return a hook's source text verbatim (to write into a user project). `name` is a REGISTRY key
    or a bare module name. Raises KeyError for an unknown logical name."""
    module = REGISTRY.get(name, name)
    return resources.files(__package__).joinpath(module + ".py").read_text(encoding="utf-8")
