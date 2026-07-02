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

# Cursor failure-tracker (Python). Wired to postToolUseFailure (fires on tool failure only). Shares
# the tool-neutral .asgard/ state with Claude/Codex so the 3-strike stays continuous across tools.
_CURSOR_FAILURE_TRACKER = """\
#!/usr/bin/env python3
# Asgard failure-tracker (Cursor) — Canon Law 9. postToolUseFailure: count per tool + normalized error
# signature in the shared .asgard/ dir; at 3+ of the same kind emit a soft agentMessage. Fail-open.
import sys, json, re, os

def _sig(text):
    s = text.lower()
    s = re.sub(r"0x[0-9a-f]+|\\b[0-9a-f]{6,}\\b", "", s)
    s = re.sub(r"[\\\\/]\\S+", "", s)
    s = re.sub(r"\\d+", "#", s)
    return re.sub(r"\\s+", " ", s).strip()[:80]

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
try:
    tool = str(data.get("tool_name") or "").strip() or "unknown"
    err = str(data.get("error_message") or data.get("failure_type") or "error")
    if tool == "unknown":
        sys.exit(0)
    proj = data.get("cwd") or os.getcwd()
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("session_id") or "default"))[:64]
    d = os.path.join(proj, ".asgard")
    os.makedirs(d, exist_ok=True)
    gi = os.path.join(d, ".gitignore")
    if not os.path.exists(gi):
        try:
            open(gi, "w").write("*\\n")
        except Exception:
            pass
    path = os.path.join(d, "failures-" + sid + ".json")
    counts = {}
    if os.path.exists(path):
        try:
            counts = json.load(open(path))
        except Exception:
            counts = {}
    key = tool + "|" + _sig(err)
    counts[key] = int(counts.get(key, 0)) + 1
    n = counts[key]
    try:
        json.dump(counts, open(path, "w"))
    except Exception:
        pass
    if n >= 3:
        msg = ("Asgard Canon Law 9 (\\ubb34\\ud55c \\ub8e8\\ud504 \\ubc29\\uc9c0): `" + tool + "` failed " + str(n) +
               "\\u00d7 with the same error kind. 3\\ud68c+ \\uac19\\uc740 \\uc811\\uadfc \\uc2e4\\ud328 \\uc2dc STOP \\u2014 "
               "\\uac00\\uc124 \\uc7ac\\uc124\\uacc4/\\ub2e4\\ub978 \\uc804\\ub7b5, \\ub9c9\\ud790 \\ub54c Odin\\uc5d0\\uac8c \\ubb38\\uc758.")
        sys.stdout.write(json.dumps({"agentMessage": msg}, separators=(",", ":")))
except Exception:
    sys.exit(0)
sys.exit(0)
"""

CURSOR_FOLDERS = [
    ("skills", "Skills — each in `<name>/SKILL.md`; frontmatter: name, description, paths.\nDocs: https://cursor.com/docs/context/commands"),
    ("hooks", "Hook scripts, wired from `.cursor/hooks.json` (events: beforeShellExecution, postToolUseFailure, …).\nDocs: https://cursor.com/docs/hooks"),
]


def cursor_rule() -> str:
    return _CURSOR_RULE


def cursor_git_guard() -> str:
    return _CURSOR_GIT_GUARD


def cursor_failure_tracker() -> str:
    return _CURSOR_FAILURE_TRACKER


def cursor_hooks_json() -> str:
    # Wires the beforeShellExecution guard (Law 3/6) + postToolUseFailure tracker (Law 9). Project
    # hooks run from repo root, need python3, load only in a trusted workspace (cursor.com/docs/hooks).
    return json.dumps(
        {
            "version": 1,
            "hooks": {
                "beforeShellExecution": [{"command": "python3 .cursor/hooks/git-guard.py"}],
                "postToolUseFailure": [{"command": "python3 .cursor/hooks/failure-tracker.py"}],
            },
        },
        indent=2,
    ) + "\n"
