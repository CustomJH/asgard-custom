#!/usr/bin/env python3
# Asgard failure-tracker — Canon Law 9 (무한 루프 방지). PostToolUse: counts failures per tool +
# normalized error signature in a per-session file under the shared, tool-neutral .asgard/ dir; at 3+
# of the same kind, injects a SOFT warning (additionalContext) to reframe — never blocks. Signature
# normalization defeats "reword the same retry" gaming. Shared by Claude Code + Codex (same schema:
# tool_name + tool_response). Fail-open: any error -> exit 0 with no output. Stdlib-only.
import json
import os
import re
import sys

WARN = (
    "<asgard-failure-warning>\n"
    "⚠️ Repeated failure: `{tool}` failed {n}× with the same error kind this session.\n"
    "Canon Law 9 (무한 루프 방지): 같은 접근으로 3회+ 실패 시 STOP — 가설을 재설계하거나 다른 "
    "전략/도구로 바꾸고, 막히면 Odin에게 물어보세요.\n"
    "</asgard-failure-warning>"
)


def sig(text: str) -> str:
    """Normalize an error into a stable signature so paraphrased retries collapse to one key."""
    s = text.lower()
    s = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{6,}\b", "", s)  # hex / hashes
    s = re.sub(r"[\\/]\S+", "", s)                       # bare paths (drop the variable part)
    s = re.sub(r"\d+", "#", s)                           # numbers -> #
    return re.sub(r"\s+", " ", s).strip()[:80]


def state_dir(proj: str) -> str:
    """Shared, tool-neutral state dir at repo root; self-ignores via a '*' .gitignore on first use."""
    d = os.path.join(proj, ".asgard")
    os.makedirs(d, exist_ok=True)
    gi = os.path.join(d, ".gitignore")
    if not os.path.exists(gi):
        try:
            open(gi, "w").write("*\n")
        except Exception:
            pass
    return d


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        tool = str(data.get("tool_name") or "").strip() or "unknown"
        resp = data.get("tool_response")
        err = ""
        if isinstance(resp, dict) and (resp.get("is_error") or resp.get("error")):
            err = str(resp.get("error") or resp.get("stderr") or "error")
        if not err and data.get("error"):
            err = str(data.get("error"))
        if not err or tool == "unknown":
            sys.exit(0)  # not a recognized failure -> no-op

        proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("session_id") or "default"))[:64]
        path = os.path.join(state_dir(proj), "failures-" + sid + ".json")
        counts = {}
        if os.path.exists(path):
            try:
                counts = json.load(open(path))
            except Exception:
                counts = {}
        key = tool + "|" + sig(err)
        counts[key] = int(counts.get(key, 0)) + 1
        n = counts[key]
        try:
            json.dump(counts, open(path, "w"))
        except Exception:
            pass
        if n >= 3:
            out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": WARN.format(tool=tool, n=n)}}
            print(json.dumps(out))
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
