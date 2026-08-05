"""Trinity 정책 — 기본값과 그 위에서 갈리는 검증 강도.

정책 파일이 없어도 동작해야 하므로(fail-open) 기본값을 내장하고 프로젝트 설정이 덮는다.
26-08-06 까지 이 표는 quest-log 와 verifier-gate 에 두 벌 있었고 verifier-gate 쪽은 9키가 빠진
부분 사본이었다 — 값은 같았지만 "동일 유지"가 주석으로만 서 있었다.
"""

from __future__ import annotations

import copy
import json
import os
import re

# 정책 파일이 없어도 동작해야 하므로(fail-open) 기본값을 내장 — .asgard/trinity-policy.json이 덮는다.
# dict 주석: 이질형 중첩 리터럴이라 좁은 추론이 소비처 서브스크립트를 오탐한다 (ty).
DEFAULT_POLICY: dict = {
    "schema": 1,
    "roles": {
        "thinker": {"tier": "high", "effort": "high"},
        "worker": {"tier": "standard", "effort": "medium"},
        "verifier": {"tier": "high", "effort": "high"},
    },
    # 소비자는 Heimdall(_delivery_model/_model_for) — 여기 두는 이유는 템플릿과 기본값 거울 유지.
    "delivery": {"freyja": "standard", "thor": "standard", "eitri": "standard", "loki": "fast", "mimir": "standard"},
    "budget_priors": {"trivial": {"turns": 1}, "standard": {"turns": 6}, "deep": {"turns": 12}},
    "small_write": {"max_files": 2, "max_lines": 80},
    # 매칭은 세그먼트/토큰 정확 일치 (sensitive_path) — substring 파생형은 여기 명시한다.
    "sensitive_paths": [
        "hooks",
        "policy",
        "policies",
        "templates",
        "install",
        "security",
        "auth",
        "authn",
        "authz",
        "authentication",
        "authorization",
        "secret",
        "secrets",
        "credentials",
        "db",
        "migration",
        "migrations",
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
    # 검증 강도 — low: 항상 micro / high: 위험 축(민감 경로·테스트 삭제·큰 non-test diff·shared)이
    # 걸릴 때만 full / full: 항상 full. 기본 low 는 속도 선택이다: full 판정은 상위 티어 모델을
    # 쓰고(_assign_turn 의 bump), micro PASS 가 나오면 completion_decision 이 되돌려 같은 diff 를
    # 두 번 판정한다. 민감 경로가 넓은 저장소는 사실상 모든 쓰기가 그 두 번을 부담한다.
    "verify_level": "low",
    # 하네스 소유 베이스라인 체크 — 비면 보수적 자동 감지 (pytest만)
    "baseline_checks": [],
    "baseline_timeout": 120,
    # 하네스가 도는 pytest 를 xdist 로 돌린다 (`_run_check`). 판정은 안 바뀐다 — 초록만 병렬이
    # 결정하고 비초록은 직렬이 다시 낸다. false 는 그 재실행 값이 아까운 저장소를 위한 것이다:
    # 병렬에서 자주 깨지는 스위트는 빨간 판정마다 병렬 한 번을 더 쓰고 버린다.
    "baseline_parallel": True,
    # 게이트-우선 적격 상한 — small_write(full-verify 기준)보다 훨씬 좁다:
    # 63라인 리라이트가 소형 판정돼 caller 미방어로 close 된 벤치 결함. 소형 diff 전용.
    "gate_first_max_lines": 25,
    # 닫힌 퀘스트 로그 keep-last-N — 세션 상한 정책. 0 = 정리 없음(무한 누적).
    "quest_retention": 30,
    # 병렬 Worker는 기본적으로 독립 clone에서 실행하고 검증된 patch만 canonical root에 병합.
    "ticket_runtime": {"isolation": True, "lease_seconds": 300, "max_attempts": 3},
}


VERIFY_LEVELS = ("low", "high", "full")


def verify_strength(policy) -> str:
    """trinity_policy.verify_level — 모르는 값·빈 값은 기본값으로 (fail-open, 설정 오타가 게이트를 못 끈다).
    verifier_gate.py의 같은 함수와 동일 유지 (단일 출처 원칙 — 어긋나면 게이트↔전이 판정 분열)."""
    level = str((policy or {}).get("verify_level") or "").strip().lower()
    return level if level in VERIFY_LEVELS else "low"


def full_verify_required(policy, risky: bool) -> bool:
    """위험 축 판정에 설정 강도를 얹는다 — 전이·요약·게이트가 모두 이 한 식만 쓴다."""
    level = verify_strength(policy)
    return level == "full" or (level == "high" and bool(risky))


def sensitive_path(path: str, needles) -> bool:
    """경로 세그먼트/토큰 기준 민감 매칭 — 나이브 substring은 'ci'가 circle.py를,
    4자+ substring은 'auth'가 oauth.py·author.py를, 'install'이 installer_utils를 오탐해
    작은 수정 하나가 full-verify+티어 승격으로 흘렀다 (26-07-23 감사). 규칙: 세그먼트 정확
    일치, 또는 세그먼트를 [._-]로 쪼갠 토큰 정확 일치 (auth.py→auth, db_pool→db). 파생형은
    needle 목록에 명시한다 (authentication 등 — DEFAULT_POLICY).
    verifier_gate.py의 sensitive_path와 동일 유지 (단일 출처 원칙 — 어긋나면 게이트↔전이 판정 분열)."""
    segs = path.lower().split("/")
    for n in needles:
        n = str(n).lower()
        if any(seg == n or n in re.split(r"[._\-]", seg) for seg in segs):
            return True
    return False


def load_policy(root: str) -> dict:
    # 얕은 복사면 중첩 기본값(`ticket_runtime` 등)이 프로세스 전역으로 공유된다 — 한 호출자가
    # `policy["ticket_runtime"]["lease_seconds"]` 를 만지면 그 프로세스의 다음 로드가 그 값을
    # 물려받는다. 정책은 호출자마다 자기 사본이어야 한다.
    p = copy.deepcopy(DEFAULT_POLICY)
    # 신규 통합 설정(asgard-setting-project.json의 trinity_policy) 우선, 구 파일 폴백 (fail-open)
    try:
        with open(os.path.join(root, ".asgard", "asgard-setting-project.json"), encoding="utf-8") as handle:
            cfg = json.load(handle)
        pol = cfg.get("trinity_policy") if isinstance(cfg, dict) else None
        if isinstance(pol, dict):
            p.update(pol)
            return p
    except Exception:
        pass
    try:
        with open(os.path.join(root, ".asgard", "trinity-policy.json"), encoding="utf-8") as handle:
            p.update(json.load(handle))
    except Exception:
        pass  # 정책 파일 없음/깨짐 → 내장 기본값 (fail-open)
    return p
