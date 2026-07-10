#!/usr/bin/env python3
# Asgard route-hint — UserPromptSubmit 시 결정론 라우트 힌트 주입 (CUS-189).
#
# 모드 B 에는 하네스 classify 가 없다 — AGENTS.md 정적 계약만으로는 게이트-우선(--standard) 채택이
# 불안정하다 (CUS-189 벤치 스모크 2회 실측: 모델이 계약 대신 자체 Thinker 진행). CUS-169 패턴 재사용:
# 정적 문서가 아니라 프롬프트 시점 컨텍스트 주입 (stdout + exit 0 = 주입, 공식 스키마).
# 힌트지 강제가 아니다 — 최종 판정은 전이 함수의 물리 가드(sensitive/big/sig_risk/테스트 삭제)가
# 내린다. 여기서는 heimdall classify_heuristic 의 보수 원칙만 복제: 명백한 비파괴 write 만 힌트,
# 모호하면 침묵 (오판 비용: 힌트 과잉 = 세금 소폭, 힌트 누락 = 현상 유지 — 둘 다 안전).
# heimdall.py 의 _DESTRUCTIVE_PAT/_WRITE_VERBS/_READ_VERBS 와 동일 유지 (단일 출처-by-copy,
# 훅은 사용자 repo 에서 stdlib 단독 실행이라 asgard import 불가).
import json
import re
import sys

_DESTRUCTIVE_PAT = re.compile(
    r"rm\s+-rf|git\s+push\s+--force|git\s+reset\s+--hard|git\s+clean\s+-[a-z]*f"
    r"|drop\s+(table|database)|truncate\s+table|mkfs|dd\s+if=|전부\s*(삭제|지워)|다\s*지워|싹\s*지워",
    re.IGNORECASE,
)
_WRITE_VERBS = (
    "만들", "생성해", "수정해", "고쳐", "추가해", "구현해", "작성해", "바꿔", "변경해", "리팩터", "빼줘",
    "삭제해", "지워", "적용해", "옮겨", "설치해", "fix ", "implement", "refactor", "rename ", "install ",
)  # fmt: skip
_READ_VERBS = (
    "설명해", "알려", "뭐야", "무엇", "어떻게 동작", "왜 ", "읽어줘", "분석해줘", "보여줘", "요약해", "조회",
    "explain", "what is", "what does", "how does", "why does", "describe", "summarize", "몇 개", "몇개", "?",
)  # fmt: skip

HINT = (
    "[asgard] 라우트 힌트(결정론 분류): 이 과업은 비파괴 write 로 분류됨 — 트리니티 프로토콜을 그대로 "
    "따르라: quest-log open 후 매 턴 `next --write-expected` 를 호출하고 산출된 next_role 을 **그대로** "
    "수행한다 (역할 자청 금지 — Thinker/Verifier 를 스스로 시작하지 마라). next_role 이 BASELINE_VERIFY "
    "면 반드시 `quest-log.py verify-baseline` 을 실행하라 — 하네스가 프로젝트 체크로 판정하는 정규 턴이다. "
    "LLM Verifier 승격(민감 경로·큰 diff·시그니처 변경·테스트 삭제)은 전이 함수가 자동으로 한다."
)


def hint(prompt: str) -> str | None:
    low = " ".join(str(prompt).split()).lower()
    if not low or _DESTRUCTIVE_PAT.search(low):
        return None  # 파괴 신호는 Canon 3 경로 — 힌트 없음
    has_w = any(v in low for v in _WRITE_VERBS)
    has_r = any(v in low for v in _READ_VERBS)
    if has_w and not has_r:
        return HINT
    return None  # read-only 또는 모호 — 침묵 (모델/전이 함수 판단에 위임)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    h = hint(data.get("prompt") or "")
    if h:
        sys.stdout.write(h)
    sys.exit(0)  # 항상 allow — 주입 실패는 현상 유지 (fail-open)


if __name__ == "__main__":
    main()
