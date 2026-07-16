"""Trinity policy template — 통합 설정(asgard-setting-project.json)의 trinity_policy 섹션.

역할 서브에이전트 3종은 `asgard.templates.roles` 의 실제 .md 파일로 관리한다 (훅과 같은 패턴 — 문자열 임베딩
금지). 결정 테이블 로직은 quest_log.py(전이 함수)가 유일한 출처고, 이 정책 파일은 임계값·경로 패턴
같은 선언 데이터만 담는다 — 코드/데이터 이중 관리를 피한다."""

import json

# quest_log.py / verifier_gate.py 의 DEFAULT_POLICY 와 값 동일 — 파일은 사용자가 조정하는 표면이고,
# 스크립트 내장값은 파일이 없거나 깨졌을 때의 fail-open 바닥이다.
_POLICY = {
    "schema": 1,
    "roles": {
        "thinker": {"tier": "high", "effort": "high"},
        "worker": {"tier": "standard", "effort": "medium"},
        "verifier": {"tier": "high", "effort": "high"},
    },
    # 딜리버리 전문가 티어 — 하니스 tier→모델: fast=haiku, standard=sonnet, high=opus, max=fable.
    # full-verify·재계획 2회+ 는 한 칸 승급 (high→max). 명시 [trinity.<role>] placement 가 항상 우선.
    "delivery": {"freyja": "standard", "thor": "standard", "eitri": "standard", "loki": "fast", "mimir": "standard"},
    "budget_priors": {"trivial": {"turns": 1}, "standard": {"turns": 6}, "deep": {"turns": 12}},
    "small_write": {"max_files": 2, "max_lines": 80},
    "sensitive_paths": [
        "hooks",
        "policy",
        "templates",
        "install",
        "security",
        "auth",
        "secret",
        "db",
        "migration",
        "ci",
        ".github",
        ".claude",
        ".cursor",
        ".codex",
    ],
    "readonly_commands": [
        "git status",
        "git diff",
        "git log",
        "git show",
        "git ls-files",
        "git rev-parse",
        "rg",
        "grep",
        "ls",
        "cat",
        "head",
        "tail",
        "find",
        "wc",
        "pwd",
        "which",
    ],
    "failure_threshold": 3,
    # 하네스 소유 베이스라인 체크 — 비면 보수적 자동 감지 (pytest 만). 프로젝트 체크를
    # 명시하면 red 판정이 엄격해진다 (예: ["uv run pytest -x -q", "uv run ruff check"]).
    "baseline_checks": [],
    "baseline_timeout": 120,
    # 게이트-우선 적격 non-test 라인 상한 — 초과 시 LLM Verifier 승격
    "gate_first_max_lines": 25,
}


def trinity_policy() -> str:
    return json.dumps(_POLICY, ensure_ascii=False, indent=2) + "\n"


def project_settings() -> str:
    """asgard-setting-project.json 초기 스캐폴드 — lagom.mode + 빈 memory + trinity_policy 시드.

    lagom.mode 는 default full 이라 resolve 기본값과 동일하지만, 이 파일이 사용자가 모드를
    조정하는 표면이므로 명시적으로 적어 둔다 — 없으면 "라곰이 꺼졌나" 오해한다. memory 는
    빈 객체로 둔다 — 프로젝트 메모리는 opt-in 연결이라 기본 미연결(공란)이 정상 상태고,
    `asgard memory connect` 가 engine·endpoint·project_id 를 채운다. 빈 {} 는 find_config
    에서 미연결로 해석돼 도구가 노출되지 않는다. 나머지 섹션(provider …)은 명령이 필요할
    때 병합 기록한다 (사다리 1단)."""
    from ..lagom import DEFAULT_MODE

    return (
        json.dumps(
            {"lagom": {"mode": DEFAULT_MODE}, "memory": {}, "trinity_policy": _POLICY},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
