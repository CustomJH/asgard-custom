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
    # 역할을 서브에이전트로 세울지 — auto: 전이 함수의 임계값이 정한다 (작은 변경은 하네스
    # 베이스라인이 닫고 LLM Verifier 는 안 뜬다) / always: 쓰기가 있는 퀘스트는 언제나 LLM
    # Verifier 턴으로 닫는다. 저장소마다 민감 경로와 변경 크기가 달라서 auto 에서는 같은
    # 작업이 한 저장소에서는 판정자를 부르고 다른 저장소에서는 안 부른다 — 역할이 실제로
    # 도는 모습을 매번 보려는 저장소가 always 를 켠다. 속도를 판정 턴 한 번과 맞바꾼다.
    "role_dispatch": "auto",
    # LLM 판정을 판정자 자리에서만 받을지 — true 면 워커가 자기 diff 에 적은 PASS 를 Stop 게이트가
    # 되돌린다 (디스패치 영수증이 판정 축, `evidence.verifier_dispatched`). 하네스 베이스라인
    # 판정(`role: harness`)은 판정자 자리가 없는 경로라 언제나 면제다. 서브에이전트를 띄우지
    # 못하는 호스트에서만 false 로 내린다 — 그 모드에서는 같은 세션이 역할을 순서대로 도는 것이
    # 규정된 폴백이라(mode A), 참인 채로 두면 닫을 수 있는 퀘스트가 없다.
    "verifier_independence": True,
    # 닫힌 퀘스트 로그 keep-last-N — 세션 상한 정책. 0 = 정리 없음(무한 누적).
    "quest_retention": 30,
    # 병렬 Worker는 기본적으로 독립 clone에서 실행하고 검증된 patch만 canonical root에 병합.
    # lease_seconds 는 워커 한 턴보다 길어야 한다 — 근거는 tickets.DEFAULT_LEASE_SECONDS 주석에.
    "ticket_runtime": {"isolation": True, "lease_seconds": 1800, "max_attempts": 3},
}


# 트리를 만지지 않는 역할. 세 훅이 각자 이 목록을 들고 있었고, 그런 표는 한 자리만 낡아도
# 판정이 갈린다 — 26-08-05 에 subagent-gate 의 부분 표가 검증 독립성을 프런트매터 산문으로
# 만들어 놓은 적이 있다. `tools:` 에 Write·Edit 이 없는 역할 집합과 같아야 한다.
READ_ONLY_ROLES = frozenset({"asgard-thinker", "asgard-verifier", "asgard-mimir", "asgard-loki", "asgard-ullr"})

VERIFY_LEVELS = ("low", "high", "full")

ROLE_DISPATCH_MODES = ("auto", "always")


def role_dispatch(policy) -> str:
    """trinity_policy.role_dispatch — 모르는 값은 auto 로 (fail-open, 설정 오타가 전이를 못 바꾼다)."""
    mode = str((policy or {}).get("role_dispatch") or "").strip().lower()
    return mode if mode in ROLE_DISPATCH_MODES else "auto"


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


def merge_policy(base: dict, override: dict) -> dict:
    """선언한 키만 덮는다 — 양쪽이 dict 인 자리는 끝까지 따라 들어간다.

    최상위 `update` 는 dict 값을 통째로 갈아 끼운다. 그래서 프로젝트가 하위 키 하나만 적어도
    나머지 하위 키는 코드 기본값을 잃고, 나중에 기본값이 움직여도 그 프로젝트에는 안 닿는다.
    26-08-21 에 그 자리가 드러났다: `lease_seconds` 기본값을 300 에서 1800 으로 올렸는데,
    옛 기본값 셋을 그대로 베껴 둔 설정 파일이 그것을 통째로 가려 유효값이 300 으로 남았다 —
    병렬 단위가 매번 헛되이 만료되던 동작이 고친 뒤에도 재현됐다.

    깊이를 한 겹에서 멈춘 판은 같은 사고를 한 층 아래에서 냈다. `roles` 와 `budget_priors` 는
    두 겹이고(`roles.worker.tier`, `budget_priors.standard.turns`), 소비처가 둘 다 조용한
    폴백이라 값이 사라져도 화면에서는 정상과 구분이 안 된다 —
    `agent/heimdall/core/sessions.py` 의 `.get("tier", "standard")` 는 판정자 티어를 한 단계
    내리고, `agent/heimdall/trinity/__init__.py` 의 `.get("turns", …)` 는 턴 상한을 늘린다.

    리스트는 통째로 바뀐다. 리스트 원소를 짝지을 기준이 없으므로(순서인지 id 인지 값인지),
    합치는 규칙을 정하는 순간 그것이 새로운 암묵 계약이 된다. 값 하나로 두는 편이 읽기 쉽다."""
    for key, value in override.items():
        current = base.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            base[key] = merge_policy(dict(current), value)
        else:
            base[key] = value
    return base


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
            merge_policy(p, pol)
            return p
    except Exception:
        pass
    try:
        with open(os.path.join(root, ".asgard", "trinity-policy.json"), encoding="utf-8") as handle:
            merge_policy(p, json.load(handle))
    except Exception:
        pass  # 정책 파일 없음/깨짐 → 내장 기본값 (fail-open)
    return p
