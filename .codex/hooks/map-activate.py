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

# 주입 스키마는 훅과 함께 깔리는 공용 라이브러리가 쥔다 — 이 훅이 정하는 것은 어느 이벤트에
# 무엇을 실을지(정책)뿐이다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import run  # noqa: E402
from asgard_hooklib.inject import client, emit_context  # noqa: E402

NEVER_INJECT = {"asgard-verifier", "asgard-loki"}
REFRESH_SECONDS = 6 * 60 * 60


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


def maintain(exe, root, stop=False):
    """Refresh both map tiers at most once per interval; failures stay fail-open.

    Stop 에서는 절대 안 쓴다. 지도는 Verifier 해시의 일부인데(AGENTS.md map 절) 판정을 기록하는
    자리도 Stop 이라, 여기서 `map update` 를 돌리면 같은 이벤트의 verifier-gate 가 방금 적힌
    PASS 를 stale 로 읽는다 — 같은 이벤트의 훅은 병렬이라 순서를 정할 수도 없다 (26-08-05 실측:
    PASS 10d56dcc 직후 현재 해시 68992095, 차이는 지도의 파일 수 두 줄뿐이었다).

    쓴 턴의 최신화는 사라지지 않는다. 판정 대상 diff 안에서는 `quest_log.refresh_managed_map`
    이 **해시를 뜨기 전에** 갱신하고(그 함수 독스트링이 같은 규칙을 적어 뒀다), 그 밖의 턴은
    다음 요청의 UserPromptSubmit 이 주기 새로고침으로 받는다 — 판정보다 앞이라 안전하다."""
    if stop:
        return
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
    # 읽기만 한 턴까지 재생성하면 턴마다 통째로 헛돈다 — 이 저장소 실측 4.7s, 지도 정리 뒤에도 2.2s.
    if time.time() - newest < REFRESH_SECONDS:
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
        current_mode = client()
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
            emit_context(current_mode, note, current_event)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    run("map-activate", main)
