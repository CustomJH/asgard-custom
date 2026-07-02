#!/usr/bin/env python3
# Asgard git-guard — Canon Law 3/6 (증거 보존). Blocks irreversible git ops in PreToolUse(Bash); they
# require Odin's explicit per-action consent. Shared by Claude Code + Codex (same stdin schema:
# {"tool_input": {"command": ...}}). Fail-open: any error -> exit 0 (allow). exit 2 = block w/ reason.
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
        cmd = str((json.load(sys.stdin).get("tool_input") or {}).get("command") or "")
    except Exception:
        sys.exit(0)
    for pat, label in BLOCK:
        if re.search(pat, cmd):
            print(
                "Asgard Canon Law 3/6 — irreversible git op (" + label + "). "
                "Odin의 명시적 동의를 먼저 받으세요 (매 건, 대상 단위).",
                file=sys.stderr,
            )
            sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
