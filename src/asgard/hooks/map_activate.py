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


def wrote_since(state_dir, newest):
    """이 세션이 도구 계층으로 판 파일이 지도보다 새로운가.

    write-sentinel(PostToolUse)이 남기는 `writes-<sid>.json`의 mtime이 유일한 신호다. Bash
    리다이렉션 write는 그쪽도 못 보므로(write_sentinel 모듈 주석의 lagom 항목) 그 경로는
    주기 새로고침이 받는다 — 지도가 조금 늦는 것이 턴마다 2초를 태우는 것보다 싸다.
    """
    try:
        names = os.listdir(state_dir)
    except OSError:
        return False
    for name in names:
        if name.startswith("writes-") and name.endswith(".json"):
            try:
                if os.path.getmtime(os.path.join(state_dir, name)) > newest:
                    return True
            except OSError:
                pass
    return False


def maintain(exe, root, stop=False):
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
    # 지도는 Verifier 해시의 일부라(AGENTS.md map 절) **쓴 턴**은 반드시 최신화한다. 읽기만 한
    # 턴까지 재생성하면 턴마다 통째로 헛돈다 — 이 저장소 실측 4.7s, 지도 정리 뒤에도 2.2s.
    if not (stop and wrote_since(state_dir, newest)) and time.time() - newest < REFRESH_SECONDS:
        return
    for command in ([exe, "map", "update", "--quiet"], [exe, "map", "scan", "--quiet"]):
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=30, cwd=root, encoding="utf-8", errors="replace"
        )
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
        maintain(exe, root, stop=current_event == "Stop")
        if current_event == "Stop":
            return 0
        cmd = [exe, "map", "context", "--query", query(data)]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, cwd=root, encoding="utf-8", errors="replace"
        )
        note = (result.stdout or "").strip()
        if result.returncode == 0 and note:
            emit(current_mode, current_event, note)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
