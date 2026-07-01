"""Cursor templates: the always-apply rule bridge + the beforeShellExecution guard (Cursor's hook
contract differs — command is top-level `.command`, block = stdout JSON {"permission":"deny"} with
exit 0, NOT exit 2) + the hooks manifest + skeleton folder READMEs."""

import json

_CURSOR_RULE = """\
---
description: Canonical project instructions (Asgard)
alwaysApply: true
---

Follow the canonical project instructions in `AGENTS.md` at the repo root.
"""

# Cursor guard (Python). beforeShellExecution: block via compact stdout JSON, exit 0. Fail-open.
_CURSOR_GIT_GUARD = """\
#!/usr/bin/env python3
# Asgard git-guard (Cursor) — Canon Law 3/6. beforeShellExecution: block via stdout JSON, exit 0.
import sys, json, re
def out(o):
    sys.stdout.write(json.dumps(o, separators=(",", ":")))
    sys.exit(0)
try:
    cmd = str(json.load(sys.stdin).get("command") or "")
except Exception:
    out({"permission": "allow"})
BLOCK = [
    (r"\\bgit\\s+push\\b[^|;&]*\\s-(-force\\b|f\\b)", "force-push"),
    (r"\\bgit\\s+push\\b[^|;&]*--force-with-lease\\b", "force-push"),
    (r"\\bgit\\s+reset\\s+--hard\\b", "reset --hard"),
    (r"\\bgit\\s+clean\\s+-[a-zA-Z]*f", "clean -f"),
    (r"\\bgit\\s+branch\\s+-D\\b", "branch -D"),
    (r"\\bgit\\s+(rebase|filter-branch|filter-repo)\\b", "history rewrite"),
    (r"\\bgit\\s+update-ref\\s+-d\\b", "update-ref -d"),
    (r"\\bgit\\s+(stash\\s+(drop|clear)|reflog\\s+(delete|expire))\\b", "drop history"),
]
for pat, label in BLOCK:
    if re.search(pat, cmd):
        out({"permission": "deny",
             "userMessage": "Asgard Canon Law 3/6 — irreversible git op (" + label + "). Blocked.",
             "agentMessage": "This " + label + " was blocked by the Asgard Canon (Law 3/6). Get Odin's explicit per-action consent; do not retry."})
out({"permission": "allow"})
"""

CURSOR_FOLDERS = [
    ("skills", "Skills — each in `<name>/SKILL.md`; frontmatter: name, description, paths.\nDocs: https://cursor.com/docs/context/commands"),
    ("hooks", "Hook scripts, wired from `.cursor/hooks.json` (events: beforeShellExecution, afterFileEdit, …).\nDocs: https://cursor.com/docs/hooks"),
]


def cursor_rule() -> str:
    return _CURSOR_RULE


def cursor_git_guard() -> str:
    return _CURSOR_GIT_GUARD


def cursor_hooks_json() -> str:
    # Wires the beforeShellExecution guard. Project hooks run from repo root, need python3, load only
    # in a trusted workspace (cursor.com/docs/hooks).
    return json.dumps(
        {"version": 1, "hooks": {"beforeShellExecution": [{"command": "python3 .cursor/hooks/git-guard.py"}]}},
        indent=2,
    ) + "\n"
