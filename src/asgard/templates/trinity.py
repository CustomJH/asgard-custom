"""Trinity policy template (CUS-119/120): trinity-policy.json.

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
    # 딜리버리 전문가 티어 (CUS-177) — 하니스 tier→모델: fast=haiku, standard=sonnet, high=opus, max=fable.
    # full-verify·재계획 2회+ 는 한 칸 승급 (high→max). 명시 [trinity.<role>] placement 가 항상 우선.
    "delivery": {"freyja": "standard", "thor": "standard", "loki": "fast"},
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
}


def trinity_policy() -> str:
    return json.dumps(_POLICY, ensure_ascii=False, indent=2) + "\n"
