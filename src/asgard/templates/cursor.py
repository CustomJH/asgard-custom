"""Cursor templates: the always-apply rule bridge + the hooks manifest + skeleton folder READMEs.
The hook SCRIPTS live in `asgard.hooks` (cursor_git_guard / cursor_failure_tracker); this file only
emits config that points at them."""

import json

from ..platform import hook_python
from .roles import role_document

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
        "agents",
        "Project subagents — one `.md` each; frontmatter: name, description, model, readonly.\nDocs: https://cursor.com/docs/subagents",
    ),
    (
        "hooks",
        "Hook scripts, wired from `.cursor/hooks.json` (events: beforeShellExecution, postToolUseFailure, …).\nDocs: https://cursor.com/docs/hooks",
    ),
]


def cursor_rule() -> str:
    return _CURSOR_RULE


def cursor_agent(content: str) -> str:
    """Adapt the canonical Claude-compatible role file to Cursor's agent schema."""
    metadata, body = role_document(content)
    readonly = "Write" not in str(metadata.get("tools") or "")
    return (
        "---\n"
        f"name: {metadata['name']}\n"
        f"description: {json.dumps(str(metadata['description']), ensure_ascii=False)}\n"
        "model: inherit\n"
        f"readonly: {str(readonly).lower()}\n"
        "---\n\n" + body
    )


def cursor_hooks_json() -> str:
    # Project hooks run from repo root and load only in a trusted workspace (cursor.com/docs/hooks).
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
                    "preToolUse": [
                        {
                            "matcher": "Task",
                            "command": f"{py} .cursor/hooks/subagent-gate.py pre",
                        }
                    ],
                    "subagentStart": [
                        {
                            "matcher": "^asgard-(thinker|worker|verifier)$",
                            "command": f"{py} .cursor/hooks/subagent-gate.py start",
                        }
                    ],
                    "subagentStop": [
                        {
                            "matcher": "^asgard-(thinker|worker|verifier)$",
                            "command": f"{py} .cursor/hooks/subagent-gate.py stop",
                        }
                    ],
                    "postToolUse": [
                        {
                            "matcher": "Write|Edit|Delete",
                            "command": f"{py} .cursor/hooks/write-sentinel.py cursor",
                        }
                    ],
                    "stop": [{"command": f"{py} .cursor/hooks/verifier-gate.py cursor"}],
                    "postToolUseFailure": [{"command": f"{py} .cursor/hooks/failure-tracker.py"}],
                },
            },
            indent=2,
        )
        + "\n"
    )
