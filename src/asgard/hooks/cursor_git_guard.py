#!/usr/bin/env python3
# Asgard git-guard (Cursor) — Canon Law 3/6. Cursor's contract differs: command is top-level `.command`,
# block = compact stdout JSON {"permission":"deny"} with exit 0 (NOT exit 2). beforeShellExecution.
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


def out(o: dict) -> None:
    sys.stdout.write(json.dumps(o, separators=(",", ":")))
    sys.exit(0)


def main() -> None:
    try:
        cmd = str(json.load(sys.stdin).get("command") or "")
    except Exception:
        out({"permission": "allow"})
    for pat, label in BLOCK:
        if re.search(pat, cmd):
            out({
                "permission": "deny",
                "userMessage": "Asgard Canon Law 3/6 — irreversible git op (" + label + "). Blocked.",
                "agentMessage": "This " + label + " was blocked by the Asgard Canon (Law 3/6). "
                                "Get Odin's explicit per-action consent; do not retry.",
            })
    out({"permission": "allow"})


if __name__ == "__main__":
    main()
