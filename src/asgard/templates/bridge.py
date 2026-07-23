"""asgard-provider 브릿지 스킬 — Trinity 역할을 배치 provider 로 위임하는 표면별 안내.

스킬은 항상 스캐폴드되고 게이트는 런타임(`asgard role list`)이다 — `.agents/skills/` 가
Cursor·Codex 공용 스코프라 파일 존재만으론 도구별 on/off 를 못 가르고, config 변경이
재스캐폴드 없이 즉시 반영돼야 하기 때문. 기본은 전부 꺼짐 (내부 모델로만 동작).
"""

BRIDGE_SKILL_MD = """\
---
name: asgard-provider
description: Bridge for projects where a Trinity role (THINKER/WORKER/VERIFIER) is placed on an external provider via [trinity.<role>] — run that role through the asgard CLI instead of a subagent. Use right after quest-log next assigns the role.
allowed-tools: Bash(asgard role *)
---

# asgard-provider — Trinity Role Bridge

This project's Trinity roles can be placed on other models/providers via `trinity.<role>` in
`.asgard/asgard-setting-project.json`. A placed role is executed by the asgard CLI instead of this tool's internal model.

## Gate (required first — if it does not pass, dispatch subagents as usual)

When quest-log `next` assigns THINKER/WORKER/VERIFIER, first run:

    asgard role list

- `bridge.<this tool>` is `false` → do not use the bridge. Tool keys: Claude Code = `claude-code`,
  Codex = `codex`, Cursor = `cursor`.
- The assigned role's `placed` is `false`, or `missing` is non-empty → do not use the bridge.
- Both pass → run the bridge below.

## Running the bridge

    asgard role run <thinker|worker|verifier> "<task + needed context (Thinker plan, etc.)>"

- The CLI runs the role session on the placed provider **and records the quest log entry itself** —
  do not run quest-log append yourself for a bridged role (double logging).
- The last line of the output is the result JSON (`writes` / `verdict` / `appended`).
- Then continue the normal protocol — next transition via quest-log `next`.

## Forbidden

- Never reinterpret or overturn a bridged Verifier's verdict — the verdict belongs to the Verifier + gate (Canon 10).
- Never bypass via the CLI while `bridge.<tool>` is off.
"""
