#!/usr/bin/env python3
# Asgard failure-tracker — Canon Law 9 (무한 루프 방지). Counts failures per tool + normalized error
# signature in a per-session file under the shared, tool-neutral .asgard/ dir; at 3+ of the same kind,
# injects a SOFT warning (never blocks). Signature normalization defeats "reword the same retry" gaming.
# One script for every tool — it auto-detects the hook protocol from the payload:
#   • Claude Code / Codex (PostToolUse):     {tool_name, tool_response:{error|is_error}} → additionalContext.
#   • Cursor (postToolUseFailure, on fail):  {tool_name, error_message, failure_type}     → agentMessage.
# Fail-open: any error -> exit 0 with no output. Stdlib-only.
import json
import os
import re
import sys

WARN = (
    "Repeated failure: `{tool}` failed {n}× with the same error kind this session. "
    "Canon Law 9 (무한 루프 방지): 같은 접근으로 3회+ 실패 시 STOP — 가설을 재설계하거나 다른 "
    "전략/도구로 바꾸고, 막히면 Odin에게 물어보세요."
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


def read_failure(data: dict) -> tuple[str, bool]:
    """Return (error_text, is_cursor). Empty error_text = not a recognized failure (skip)."""
    if "error_message" in data or "failure_type" in data:  # Cursor postToolUseFailure (always a failure)
        return str(data.get("error_message") or data.get("failure_type") or "error"), True
    resp = data.get("tool_response")  # Claude Code / Codex PostToolUse
    if isinstance(resp, dict) and (resp.get("is_error") or resp.get("error")):
        return str(resp.get("error") or resp.get("stderr") or "error"), False
    if data.get("error"):
        return str(data.get("error")), False
    return "", False


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        tool = str(data.get("tool_name") or "").strip() or "unknown"
        err, cursor = read_failure(data)
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
            msg = WARN.format(tool=tool, n=n)
            if cursor:
                out = {"agentMessage": msg}
            else:
                out = {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                              "additionalContext": "<asgard-failure-warning>\n" + msg + "\n</asgard-failure-warning>"}}
            sys.stdout.write(json.dumps(out, separators=(",", ":")))
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
