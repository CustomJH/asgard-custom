"""Cursor templates: the always-apply rule bridge + the hooks manifest + skeleton folder READMEs.
The hook SCRIPTS live in `asgard.hooks` (cursor_git_guard / cursor_failure_tracker); this file only
emits config that points at them."""

import json

from ..platform import hook_python

_CURSOR_RULE = """\
---
description: Canonical project instructions (Asgard)
alwaysApply: true
---

Follow the canonical project instructions in `AGENTS.md` at the repo root.
"""

CURSOR_FOLDERS = [
    (
        "skills",
        "Skills — each in `<name>/SKILL.md`; frontmatter: name, description, paths.\nDocs: https://cursor.com/docs/context/commands",
    ),
    (
        "hooks",
        "Hook scripts, wired from `.cursor/hooks.json` (events: beforeShellExecution, postToolUseFailure, …).\nDocs: https://cursor.com/docs/hooks",
    ),
]


def cursor_rule() -> str:
    return _CURSOR_RULE


def cursor_hooks_json() -> str:
    # Wires the beforeShellExecution guard (Law 3/6) + postToolUseFailure tracker (Law 9). Project
    # hooks run from repo root, need a python on PATH (python3 — Windows: python/py),
    # load only in a trusted workspace (cursor.com/docs/hooks).
    py = hook_python()
    return (
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "beforeShellExecution": [
                        {"command": f"{py} .cursor/hooks/git-guard.py"},
                        {"command": f"{py} .cursor/hooks/release-guard.py"},
                    ],
                    "postToolUseFailure": [{"command": f"{py} .cursor/hooks/failure-tracker.py"}],
                },
            },
            indent=2,
        )
        + "\n"
    )
