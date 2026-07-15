"""asgard-provider 브릿지 스킬 — Trinity 역할을 배치 provider 로 위임하는 표면별 안내.

스킬은 항상 스캐폴드되고 게이트는 런타임(`asgard role list`)이다 — `.agents/skills/` 가
Cursor·Codex 공용 스코프라 파일 존재만으론 도구별 on/off 를 못 가르고, config 변경이
재스캐폴드 없이 즉시 반영돼야 하기 때문. 기본은 전부 꺼짐 (내부 모델로만 동작).
"""

BRIDGE_SKILL_MD = """\
---
name: asgard-provider
description: Trinity 역할(THINKER/WORKER/VERIFIER)이 [trinity.<role>] 로 외부 provider 에 배치된 프로젝트에서, 그 역할을 서브에이전트 대신 asgard CLI 로 실행하는 브릿지. quest-log next 가 역할을 배정한 직후 사용.
---

# asgard-provider — Trinity 역할 브릿지

이 프로젝트의 Trinity 역할은 `.asgard/asgard-setting-project.json` 의 `trinity.<role>` 로 다른 모델·provider 에
배치될 수 있다. 배치된 역할은 이 도구의 내부 모델 대신 asgard CLI 가 실행한다.

## 게이트 (필수 선행 — 통과 못 하면 평소대로 서브에이전트 디스패치)

quest-log `next` 가 THINKER/WORKER/VERIFIER 를 배정하면 먼저:

    asgard role list

- `bridge.<이 도구>` 가 `false` → 브릿지 안 쓴다. 도구 키: Claude Code = `claude-code`,
  Codex = `codex`, Cursor = `cursor`.
- 배정된 역할의 `placed` 가 `false` 또는 `missing` 이 비어있지 않음 → 브릿지 안 쓴다.
- 둘 다 통과 → 아래 실행.

## 브릿지 실행

    asgard role run <thinker|worker|verifier> "<과업 + 필요한 컨텍스트(Thinker 계획 등)>"

- CLI 가 배치된 provider 로 역할 세션을 돌리고 **퀘스트 로그(quest-log) 기록까지 수행**한다 —
  브릿지된 역할에 대해 quest-log append 를 직접 하지 마라 (이중 기록).
- 출력 마지막 줄 JSON 이 결과 (`writes` / `verdict` / `appended`).
- 이후는 평소 프로토콜 — quest-log `next` 로 다음 전이.

## 금지

- 브릿지된 Verifier 의 verdict 를 재해석·번복하지 마라 — 판정은 Verifier + 게이트 몫 (Canon 10).
- `bridge.<도구>` 가 꺼져 있는데 CLI 로 우회 실행하지 마라.
"""
