#!/usr/bin/env python3
# Asgard git-guard — Canon Law 3/6 (증거 보존). Blocks irreversible git ops. One script for every tool:
# it auto-detects the hook protocol from the payload shape, so the BLOCK list has a single source.
#   • Claude Code / Codex (PreToolUse): {"tool_input": {"command": ...}} → block = exit 2 + stderr.
#   • Cursor (beforeShellExecution):    {"command": ...}                 → block = stdout {"permission":"deny"}, exit 0.
# Fail-open: any error -> allow.
import json
import re
import sys

BLOCK = [
    (r"\bgit\s+push\b[^|;&]*\s-(-force\b|f\b)", "force-push"),
    (r"\bgit\s+push\b[^|;&]*--force-with-lease\b", "force-push"),
    (r"\bgit\s+reset\s+--hard\b", "reset --hard"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "clean -f"),
    (r"\bgit\s+branch\s+-D\b", "branch -D"),
    (r"\bgit\s+(rebase|filter-branch|filter-repo)\b", "history rewrite"),
    (r"\bgit\s+update-ref\s+-d\b", "update-ref -d"),
    (r"\bgit\s+(stash\s+(drop|clear)|reflog\s+(delete|expire))\b", "drop history"),
]


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    # Cursor sends the command at top level (no tool_input); Claude Code / Codex nest it in tool_input.
    cursor = "tool_input" not in data
    cmd = str((data.get("command") if cursor else (data.get("tool_input") or {}).get("command")) or "")

    for pat, label in BLOCK:
        if re.search(pat, cmd):
            if cursor:
                sys.stdout.write(json.dumps({
                    "permission": "deny",
                    "userMessage": "Asgard Canon Law 3/6 — irreversible git op (" + label + "). Blocked.",
                    "agentMessage": "This " + label + " was blocked by the Asgard Canon (Law 3/6). "
                                    "Get Odin's explicit per-action consent; do not retry.",
                }, separators=(",", ":")))
                sys.exit(0)
            print(
                "Asgard Canon Law 3/6 — irreversible git op (" + label + "). "
                "Odin의 명시적 동의를 먼저 받으세요 (매 건, 대상 단위).",
                file=sys.stderr,
            )
            sys.exit(2)

    if cursor:  # Cursor expects an explicit allow response
        sys.stdout.write(json.dumps({"permission": "allow"}, separators=(",", ":")))
    sys.exit(0)


if __name__ == "__main__":
    main()
