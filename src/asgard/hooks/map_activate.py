#!/usr/bin/env python3
# Asgard map-activate — refresh the managed project map and inject bounded task context.
#
# Standalone stdlib hook. All map generation, validation, ranking, and budgets stay in the Asgard
# CLI so generated hook copies cannot drift from the engine.
import json
import os
import shutil
import subprocess
import sys
import time

MODES = {"claude-code", "codex", "cursor"}
NEVER_INJECT = {"asgard-verifier", "asgard-loki"}
REFRESH_SECONDS = 6 * 60 * 60


def mode():
    raw = str(sys.argv[1] if len(sys.argv) > 1 else "claude-code")
    return raw if raw in MODES else "claude-code"


def event(data):
    raw = str(data.get("hook_event_name") or "")
    return {
        "sessionStart": "SessionStart",
        "beforeSubmitPrompt": "UserPromptSubmit",
        "subagentStart": "SubagentStart",
        "preToolUse": "SubagentStart",
        "stop": "Stop",
    }.get(raw, raw)


def agent(data):
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    return str(
        data.get("agent_type")
        or data.get("agent_name")
        or data.get("subagent_type")
        or tool_input.get("agent_type")
        or tool_input.get("subagent_type")
        or ""
    )


def query(data):
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    return str(
        data.get("prompt") or tool_input.get("prompt") or tool_input.get("description") or tool_input.get("task") or ""
    ).strip()


def emit(current_mode, current_event, text):
    if current_mode == "cursor":
        sys.stdout.write(json.dumps({"additional_context": text}, ensure_ascii=False) + "\n")
    elif current_event in {"UserPromptSubmit", "SubagentStart"}:
        sys.stdout.write(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": current_event,
                        "additionalContext": text,
                    }
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    else:
        sys.stdout.write(text + "\n")


def maintain(exe, root, force=False):
    """Refresh both map tiers at most once per interval; failures stay fail-open."""
    # ponytail: concurrent hooks may duplicate one scan; add a lock only if scans become costly.
    state_dir = os.path.join(root, ".asgard", "state")
    marker = os.path.join(state_dir, "map-maintained")
    graph = os.path.join(state_dir, "map-graph.json")
    newest = 0.0
    for path in (marker, graph):
        try:
            newest = max(newest, os.path.getmtime(path))
        except OSError:
            pass
    if not force and time.time() - newest < REFRESH_SECONDS:
        return
    for command in ([exe, "map", "update", "--quiet"], [exe, "map", "scan", "--quiet"]):
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, cwd=root)
        if result.returncode != 0:
            return
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(marker, "w", encoding="utf-8") as stream:
            stream.write(str(int(time.time())) + "\n")
    except OSError:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        current_mode = mode()
        current_event = event(data)
        current_agent = agent(data)
        if current_agent in NEVER_INJECT:
            return 0
        exe = shutil.which("asgard")
        if not exe:
            return 0
        root = (
            os.environ.get("CLAUDE_PROJECT_DIR")
            or os.environ.get("CURSOR_PROJECT_DIR")
            or str(data.get("cwd") or os.getcwd())
        )
        maintain(exe, root, force=current_event == "Stop")
        if current_event == "Stop":
            return 0
        cmd = [exe, "map", "context", "--query", query(data)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=root)
        note = (result.stdout or "").strip()
        if result.returncode == 0 and note:
            emit(current_mode, current_event, note)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
