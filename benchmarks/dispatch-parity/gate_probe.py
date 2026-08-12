#!/usr/bin/env python3
"""배포본 subagent-gate 의 위임 판정을 caller×target 전수로 확인한다.

표(`AGENT_TARGETS`)를 읽어 기대값을 만들고, 그 기대값을 **훅을 실제로 실행해서** 대조한다.
표를 표로 검산하면 아무것도 안 재므로, 판정은 합성 PreToolUse JSON 을 stdin 으로 먹인
서브프로세스의 종료 코드로만 읽는다 (allow=0, deny=2).

세션 id 는 퀘스트 포인터가 없는 이름을 쓴다. 훅은 경계 검사를 퀘스트 조회보다 **먼저** 하므로
판정은 그대로 나오고, 뒤따르는 배차 장부 기록(`siege_open`)은 도달하지 않는다 — 이 시험이
`.asgard/orchestration.db` 에 유령 배차를 남기지 않는 이유다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEPLOYED = os.path.join(ROOT, ".claude", "hooks", "subagent-gate.py")
PACKAGE = os.path.join(ROOT, "src", "asgard", "hooks", "subagent_gate.py")
# 퀘스트 포인터가 없어야 하는 세션 이름 — 있으면 이 시험은 장부를 건드린다.
PROBE_SID = "gate-probe-no-quest"


def load_module(path: str, name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fire(caller: str, target: str) -> tuple[int, str]:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "session_id": PROBE_SID,
        "cwd": ROOT,
        "agent_type": caller,
        "tool_input": {"subagent_type": target, "prompt": "probe"},
    }
    proc = subprocess.run(
        [sys.executable, DEPLOYED],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "CLAUDE_PROJECT_DIR": ROOT},
    )
    return proc.returncode, (proc.stderr or "").strip()


def main() -> int:
    if os.path.exists(os.path.join(ROOT, ".asgard", "quest", "sessions", PROBE_SID + ".active")):
        print("FAIL: probe session has an active quest pointer — the probe would write the ledger")
        return 1

    gate = load_module(DEPLOYED, "deployed_subagent_gate")
    package = load_module(PACKAGE, "package_subagent_gate")

    failures: list[str] = []

    # ① 표 자체가 두 불변식(층위 단조·읽기 봉인)을 지키는가 — 사본 둘 다.
    for label, module in (("deployed", gate), ("package", package)):
        for problem in module.closure_violations():
            failures.append(f"{label} table: {problem}")
    if gate.AGENT_TARGETS != package.AGENT_TARGETS or gate.AGENT_RANK != package.AGENT_RANK:
        failures.append("deployed copy and package copy declare different delegation tables")

    # ② 훅의 실제 판정이 표와 일치하는가 — 표 안 caller 전원 + 표 밖 caller 둘.
    callers = sorted(gate.AGENT_TARGETS) + ["", "Explore"]
    targets = sorted(gate.AGENT_RANK)
    checked = 0
    for caller in callers:
        for target in targets:
            expected_deny = caller in gate.AGENT_TARGETS and target not in gate.AGENT_TARGETS[caller]
            code, err = fire(caller, target)
            checked += 1
            if expected_deny and code != 2:
                failures.append(f"{caller or '<main>'} -> {target}: expected deny, got exit {code}")
            if not expected_deny and code != 0:
                failures.append(f"{caller or '<main>'} -> {target}: expected allow, got exit {code} ({err[:120]})")

    # ③ 전이 함수가 배정하는 두 자리는 어떤 역할도 손으로 못 부른다.
    for caller in sorted(gate.AGENT_TARGETS):
        for target in sorted(gate.UNDISPATCHABLE):
            code, _ = fire(caller, target)
            checked += 1
            if code != 2:
                failures.append(f"{caller} -> {target}: undispatchable seat was allowed (exit {code})")

    print(f"checked {checked} caller x target verdicts against the deployed hook")
    for line in failures:
        print("FAIL:", line)
    if failures:
        return 1
    print("PASS: every verdict matches the declared table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
