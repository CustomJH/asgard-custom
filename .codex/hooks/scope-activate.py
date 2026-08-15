#!/usr/bin/env python3
# Asgard scope-activate — 이 요청이 어떤 형상이고 어느 전문가의 표면인가를 턴 머리에 주입한다.
#
# 왜 훅인가. 이 판정은 `skill_scope.scope_note` 가 이미 결정론으로 내고 있었고, 부르는 자리가
# 둘뿐이었다: 네이티브 루프(`agent/heimdall/roles.py`)와 사람이 치는 CLI. 세 호스트 모드에는
# 통로가 없어서, AGENTS.md 가 "계획 전에 `asgard skills resolve` 를 한 번 돌려라"라고 적어 둔
# 것이 모델의 자발성에만 걸려 있었다. 26-08-13 helios-asgard 실측: Bash 258회 중 그 명령은 0회.
# 그 세션의 지시 18건은 대시보드 위젯·차트·폰트·해상도였고, Freyja 는 한 번도 안 불렸다.
#
# 판정은 CLI 가 쥔다 (map-activate 와 같은 계약) — 훅 사본이 엔진과 갈라지지 않게. 여기서
# 정하는 것은 어느 이벤트에 어느 역할로 물을지뿐이다.
#
# future import 는 3.9 바닥 때문이다: `role_for` 의 `str | None` 은 3.9 에서 파싱은 되고 함수를
# 정의하는 순간 TypeError 로 죽으며, 훅의 fail-open 은 그보다 뒤에 있어 그 죽음을 못 받는다.
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.firing import run  # noqa: E402
from asgard_hooklib.inject import client, emit_context  # noqa: E402

# 판정 표면에는 붙이지 않는다 — 게이트에 advisory 지식 무주입 (AGENTS.md 스킬 절). CLI 도 같은
# 두 이름을 거부하므로 여기 목록은 프로세스 하나를 아끼는 것이지 판정을 바꾸지 않는다.
NEVER_INJECT = {"asgard-verifier", "asgard-loki", "verifier", "loki"}
# 서브에이전트 이름 → resolve 가 아는 역할. 여기 없는 이름은 묻지 않는다: 형상 규율은 배정을
# 받은 역할에만 뜻이 있고, 표에 없는 이름에 worker 를 넘기면 남의 역할 규율을 읽히게 된다.
ROLES = {
    "asgard-worker": "worker",
    "asgard-freyja": "freyja",
    "asgard-thor": "thor",
    "asgard-thor-lead": "thor-lead",
    "asgard-eitri": "eitri",
    "asgard-mimir": "mimir",
}
TIMEOUT = 15


def event(data):
    raw = str(data.get("hook_event_name") or "")
    return {
        "beforeSubmitPrompt": "UserPromptSubmit",
        "subagentStart": "SubagentStart",
        "preToolUse": "SubagentStart",
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


def role_for(current_event: str, current_agent: str) -> str | None:
    """이 턴을 어느 역할로 물을 것인가. 답이 없으면 묻지 않는다 (None)."""
    if current_agent in NEVER_INJECT:
        return None
    if current_event == "UserPromptSubmit":
        # 메인 코디네이터는 배정을 받기 전이다. 워커 자리로 묻는 이유는 그 자리가 실제로 다음에
        # 서는 자리라서고(전이 함수의 기본 배정), 워커에게 보이는 것이 "이 표면은 넘겨라"다.
        return "worker" if not current_agent else ROLES.get(current_agent)
    return ROLES.get(current_agent)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        current_event = event(data)
        if current_event not in ("UserPromptSubmit", "SubagentStart"):
            return 0
        role = role_for(current_event, agent(data))
        if not role:
            return 0
        task = query(data)
        if len(task) < 8:  # 인사·확인 한 마디에 계획 규율을 붙이지 않는다
            return 0
        exe = shutil.which("asgard")
        if not exe:
            return 0
        root = (
            os.environ.get("CLAUDE_PROJECT_DIR")
            or os.environ.get("CURSOR_PROJECT_DIR")
            or str(data.get("cwd") or os.getcwd())
        )
        result = subprocess.run(
            [exe, "skills", "resolve", "--agent", role, "--scope-only", task],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=root,
            encoding="utf-8",
            errors="replace",
        )
        note = (result.stdout or "").strip()
        if result.returncode == 0 and note:
            emit_context(client(), note, current_event)
    except Exception:
        pass  # 형상 힌트가 없다고 잘못되는 것은 없다 — 훅이 죽어도 턴은 돈다
    return 0


if __name__ == "__main__":
    run("scope-activate", main)
