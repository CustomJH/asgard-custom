"""네이티브 세션 툴 스키마 — 순수 데이터 선언.

Verifier verdict, 딜리버리 dispatch, thor 편대 fan-out.
핸들러 구현은 dispatch/trinity 모듈 몫 — 여기는 계약 표면만.
"""

from __future__ import annotations

from .roles import _DELIVERY

VERDICT_TOOL = {
    "name": "verdict",
    "description": "Verifier 전용 — 구조화 판정 제출. 검증 명령을 직접 실행한 뒤에만 호출한다.",
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
                "description": "FAIL 시 동종 실패 시그니처 — kebab-case 슬러그 (예: missing-null-check). "
                "같은 원인의 재실패에는 같은 슬러그를 쓴다 (3-strike 동종 판정 키 — 하네스가 슬러그로 정규화)",
            },
            "structural": {
                "type": "boolean",
                "description": "FAIL 이 접근 자체의 결함(구조적)이면 true — Thinker 재계획 트리거 (경미한 수정 가능 결함은 false)",
            },
            "why": {"type": "string"},
        },
        "required": ["verdict", "criteria", "commands"],
    },
}

# dict 주석: 이질형 중첩 스키마 리터럴 — 좁은 추론이 소비처 서브스크립트를 오탐한다 (ty).
DISPATCH_TOOL: dict = {
    "name": "dispatch",
    "description": "딜리버리 전문가에게 하위 작업 위임 (freyja=디자인/프론트엔드/모션/3D/영상, thor=백엔드/데이터/API/런타임, "
    "eitri=빌드/CI/패키징/릴리스, loki=adversarial, mimir=코드 설명/워크스루/온보딩). "
    "위임 전 누구에게·왜를 고민하고 why 에 근거를 남겨라 — 퀘스트 로그에 기록된다.",
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
    "description": "토르 편대장 전용 — 토르 2~4기를 한 배치로 병렬 호출한다. "
    "mode=split: 파일 범위(scope)가 겹치지 않는 분할 단위 병렬 + 자동 병합. "
    "mode=tournament: 같은 난제의 N-버전 격리 시도 — 본류 미적용, deliverables/thor-tournament/<id>.patch 로 회수.",
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
