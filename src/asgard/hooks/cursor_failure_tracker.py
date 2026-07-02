#!/usr/bin/env python3
# Asgard failure-tracker (Cursor) — Canon Law 9. Wired to postToolUseFailure (fires on tool failure
# only), schema {tool_name, error_message, failure_type, ...}. Shares the tool-neutral .asgard/ state
# with Claude/Codex so the 3-strike stays continuous across tools; at 3+ of the same kind emits a soft
# agentMessage. Fail-open: any error -> exit 0.
import json
import os
import re
import sys

WARN = (
    "Asgard Canon Law 9 (무한 루프 방지): `{tool}` failed {n}× with the same error kind. "
    "3회+ 같은 접근 실패 시 STOP — 가설 재설계/다른 전략, 막힐 때 Odin에게 문의."
)


def sig(text: str) -> str:
    s = text.lower()
    s = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{6,}\b", "", s)
    s = re.sub(r"[\\/]\S+", "", s)
    s = re.sub(r"\d+", "#", s)
    return re.sub(r"\s+", " ", s).strip()[:80]


def state_dir(proj: str) -> str:
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
        err = str(data.get("error_message") or data.get("failure_type") or "error")
        if tool == "unknown":
            sys.exit(0)
        proj = data.get("cwd") or os.getcwd()
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
            sys.stdout.write(json.dumps({"agentMessage": WARN.format(tool=tool, n=n)}, separators=(",", ":")))
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
