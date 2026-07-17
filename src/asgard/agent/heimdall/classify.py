"""요청 분류 + 오류·게이트 시그니처 — 순수 판정 계층 (LLM·IO 없음).

pre-LLM 휴리스틱 분류, API 오류 재시도 판정, 게이트 차단 사유 시그니처/수리 매핑.
전부 순수 함수 — 부작용 있는 텔레메트리는 journal 모듈이 진다.
"""

from __future__ import annotations

import re

# ── 게이트 차단 사유 → (시그니처, 수리 역할) — 동일 시그니처 2회 = 수리 불가 → ESCALATE ──
_GATE_SIGS = (
    ("판정(PASS/ESCALATE) 레코드가 없", "no-verdict"),
    ("stale PASS", "stale-pass"),
    ("성공 기준(criteria)", "no-criteria"),
    ("검증 명령 증거", "no-evidence"),
    ("베이스라인 체크 red", "baseline-red"),
    ("full-verify 필요", "micro-pass"),
    ("퀘스트 로그가 없", "orphan-write"),
)


def _gate_sig(reason: str) -> str:
    return next((sig for needle, sig in _GATE_SIGS if needle in reason), "other")


def _gate_repair(sig: str) -> tuple[str, str]:
    """차단 사유별 수리 턴 — criteria 부재만 계획 보강, baseline red 는 코드 수리(Worker),
    나머지는 전부 신선 증거 재검증."""
    if sig == "no-criteria":
        return "THINKER_REPLAN", "게이트: criteria 부재 — 계획 보강 필요"
    if sig == "baseline-red":
        return "WORKER_RETRY", "게이트: 하네스 베이스라인 red — 실패한 체크를 수정"
    return "VERIFIER", f"게이트 차단({sig}) — 신선한 증거로 재검증"


# ── 결정론 pre-LLM 분류 — 명백 케이스만, 모호하면 None → LLM 폴백 ──
_DESTRUCTIVE_PAT = re.compile(
    r"rm\s+-rf|git\s+push\s+--force|git\s+reset\s+--hard|git\s+clean\s+-[a-z]*f"
    r"|drop\s+(table|database)|truncate\s+table|mkfs|dd\s+if=|전부\s*(삭제|지워)|다\s*지워|싹\s*지워",
    re.IGNORECASE,
)
_WRITE_VERBS = (
    "만들", "생성해", "제작해", "수정해", "고쳐", "추가해", "구현해", "작성해", "바꿔", "변경해", "리팩터", "빼줘",
    "삭제해", "지워", "적용해", "옮겨", "설치해", "완성해", "fix ", "implement", "refactor", "rename ", "install ",
    "create ", "write ", "modify ", "change ", "edit ", "add ", "update ", "delete ", "remove ", "move ", "copy ",
)  # fmt: skip
_READ_VERBS = (
    "설명해", "알려", "뭐야", "무엇", "어떻게 동작", "왜 ", "읽", "답해", "분석해줘", "보여줘", "요약해", "조회",
    "explain", "what is", "what does", "how does", "why does", "describe", "summarize", "read ", "show ", "몇 개", "몇개", "?",
)  # fmt: skip
_NEGATED_WRITE_PAT = re.compile(
    r"(?:수정|변경|편집|고치)\s*(?:하지\s*(?:마(?:라|세요)?|말|않)|금지)"
    r"|(?:do\s+not|don't|without)\s+(?:modify|modifying|change|changing|edit|editing|write|writing)\b",
    re.IGNORECASE,
)
_PARALLEL_WORK_PAT = re.compile(
    r"병렬|동시에|독립\s*(?:worker|작업|단위)|서브\s*에이전트|sub[ -]?agents?|fan[ -]?out|"
    r"todo\s*(?:list)?|작업\s*목록|티켓|task\s*graph",
    re.IGNORECASE,
)


def classify_heuristic(request: str) -> dict | None:
    """순수 함수 1차 분류 — LLM 토큰 0. 확실할 때만 판정하고 나머지는 None (안전 우선).

    read-only 판정은 write 동사가 전혀 없을 때만 — 오판 시 write 가 게이트를 우회하므로
    (DIRECT), write 쪽 오판(불필요한 trinity 세금)보다 훨씬 보수적으로 잡는다."""
    low = " ".join(request.split()).lower()
    base = {
        "write_expected": False,
        "ambiguous": False,
        "destructive": False,
        "external_research": False,
        "shared": False,
        "parallel_requested": False,
        "criteria": [],
        "task_class": "standard",
    }
    if _DESTRUCTIVE_PAT.search(low):
        return {**base, "write_expected": True, "destructive": True, "task_class": "deep"}
    # "파일을 수정하지 마"의 부정된 동사를 write 의도로 세면 read-only 질의가 Trinity로
    # 오분류된다. 부정구만 제거한 사본에서 write 동사를 찾되, 같은 문장에 실제 write 동사가
    # 따로 있으면 그대로 잡는다 (예: "기존 파일은 수정하지 말고 새 파일 만들어").
    write_scan = _NEGATED_WRITE_PAT.sub("", low)
    has_w = any(v in write_scan for v in _WRITE_VERBS)
    has_r = any(v in low for v in _READ_VERBS)
    if has_w and _PARALLEL_WORK_PAT.search(low):
        # 명시적 분해·병렬 요청은 Thinker가 dependency/file-overlap을 구조화해야 한다.
        # LLM 분류가 standard를 반환하면 gate-first가 Thinker를 생략해 단일 Worker로 축소된다.
        return {**base, "write_expected": True, "parallel_requested": True, "task_class": "deep"}
    if has_r and not has_w:
        return base  # 명백 read-only — DIRECT 무세금
    if has_w and not has_r:
        # 명백 write — criteria 는 못 뽑는다 (기본 criterion 사용). task_class 는 LLM 없이 보수적 standard.
        return {**base, "write_expected": True}
    return None  # 모호 — LLM 폴백


def _pred_fields(d: dict) -> dict:
    return {k: d.get(k) for k in ("write_expected", "ambiguous", "destructive", "task_class")}


# ── API 오류 회복 (recovery-hint 최소판) ──
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
_FATAL_STATUS = {400, 401, 403, 404, 422}


def classify_api_error(e: Exception) -> str:
    """ "retryable" | "fatal" — 분류는 1회, 재시도 루프는 멍청하게."""
    status = getattr(e, "status_code", None)
    if status in _RETRY_STATUS:
        return "retryable"
    if status in _FATAL_STATUS:
        return "fatal"
    name = e.__class__.__name__.lower()
    if "usagecap" in name:  # 구독 한도 도달 (claude_cli) — 재시도로 뚫지 않는다
        return "fatal"
    if any(k in name for k in ("timeout", "connection", "overloaded", "ratelimit", "internalserver")):
        return "retryable"
    return "retryable" if status is None else "fatal"  # 미상 = 일시 오류로 간주 (1회 재시도 가치)
