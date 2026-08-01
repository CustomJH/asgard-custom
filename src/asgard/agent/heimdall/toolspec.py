"""네이티브 세션 툴 스키마 — 순수 데이터 선언.

Verifier verdict, 딜리버리 dispatch, thor 편대 fan-out.
핸들러 구현은 dispatch/trinity 모듈 몫 — 여기는 계약 표면만.
"""

from __future__ import annotations

from typing import Any

from .roles import _DELIVERY

# JSON 스키마다 — 값이 str·dict·list로 섞인다. 선언을 안 달면 추론이 첫 값으로 좁혀져
# 중첩 키를 파고드는 호출부가 전부 타입 오류가 된다.
VERDICT_TOOL: dict[str, Any] = {
    "name": "verdict",
    "description": "Verifier only — submit a structured verdict. Call only after running the "
    "verification commands yourself.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["PASS", "FAIL", "ESCALATE"]},
            "criteria": {"type": "array", "items": {"type": "string"}},
            "commands": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}, "exit_code": {"type": "integer"}},
                    "required": ["cmd", "exit_code"],
                },
            },
            "failure_sig": {
                "type": "string",
                "description": "On FAIL, the same-kind failure signature — a kebab-case slug (e.g. "
                "missing-null-check). Reuse the same slug for repeated failures with the same cause "
                "(3-strike same-kind verdict key — the harness normalizes it as a slug)",
            },
            "structural": {
                "type": "boolean",
                "description": "true when the FAIL is a defect of the approach itself (structural) — "
                "triggers Thinker replanning (false for minor fixable defects)",
            },
            "findings": {
                "type": "array",
                "description": "Every defect this verdict rests on, each classified by who owns the "
                "decision. Mechanical, low-risk defects are auto-fix (the retry turn resolves them). "
                "A finding that contradicts what Odin explicitly asked for, or that changes "
                "user-visible product behaviour, is ask-user — it belongs to Odin, not to a retry, "
                "and it stops the loop. Observations that need nothing are no-op. A finding you "
                "cannot classify is ask-user (fail closed).",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Short stable id, e.g. f1."},
                        "severity": {"type": "string", "enum": ["error", "warning", "info"]},
                        "file": {"type": "string", "description": "file:line the finding is anchored to."},
                        "action": {"type": "string", "enum": ["auto-fix", "ask-user", "no-op"]},
                        "description": {"type": "string"},
                    },
                    "required": ["id", "action", "description"],
                },
            },
            "why": {"type": "string"},
        },
        "required": ["verdict", "criteria", "commands"],
    },
}

ASK_TOOL: dict = {
    "name": "ask_coordinator",
    "description": "Ask the coordinator a blocking question when you cannot proceed without a decision that "
    "is not yours to make: a scope boundary, a conflict with another unit's files, or an ambiguity in the "
    "assignment that the repository cannot settle. Do not use it for anything you can answer by reading the "
    "code — read first. You always get a reply: either an answer or an explicit instruction to proceed under "
    "a stated assumption.",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The decision you need, in one sentence."},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The candidate answers you see, when the choice is closed.",
            },
            "tried": {
                "type": "string",
                "description": "What you already read or ran, and why it did not settle the question.",
            },
        },
        "required": ["question", "tried"],
    },
}

# dict 주석: 이질형 중첩 스키마 리터럴 — 좁은 추론이 소비처 서브스크립트를 오탐한다 (ty).
DISPATCH_TOOL: dict = {
    "name": "dispatch",
    "description": "Delegate a subtask to a delivery specialist (freyja=design/frontend/motion/3D/video, "
    "thor=backend/data/API/runtime, eitri=build/CI/packaging/release, loki=adversarial, "
    "mimir=code explanation/walkthrough/onboarding). Before delegating, think about who and why, "
    "and leave the rationale in why — it is recorded in the quest log.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "enum": list(_DELIVERY)},
            "task": {"type": "string"},
            "why": {"type": "string"},
        },
        "required": ["agent", "task", "why"],
    },
}


# 네이티브 thor-lead 전용 물리 fan-out — 에인헤랴르 편대 유형 2종을 계약으로 강제한다:
# split(분할) = scope 파일 범위 비중첩 검증 + 병합, tournament = 패치 회수만(본류 미적용, 승자만 대장이 적용).
THOR_SQUAD_TOOL: dict = {
    "name": "dispatch_thor_squad",
    "description": "Thor squad lead only — invoke 2-4 Thor members in parallel as one batch. "
    "mode=split: parallel split units with non-overlapping file scopes + automatic merge. "
    "mode=tournament: N isolated attempts at the same hard problem — not applied to the mainline, "
    "collected as deliverables/thor-tournament/<id>.patch.",
    "x-asgard-capability": "coordinate",
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["split", "tournament"]},
            "tasks": {
                "type": "array",
                "minItems": 2,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "task": {"type": "string"},
                        "scope": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "why": {"type": "string"},
                    },
                    "required": ["id", "task", "scope", "why"],
                },
            },
        },
        "required": ["mode", "tasks"],
    },
}
