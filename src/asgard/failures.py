"""실패 카탈로그 — 실패 이유의 정본은 코드, 문장은 렌더링.

발화자는 코드+파라미터만 넘기고 문장은 카탈로그가 만든다. 소비자(classify·trinity·doctor)는
문장을 파싱하지 않고 코드를 직독한다. 전송 표면 계약은 메시지 서두의 `[gate:<code>]` 태그 하나 —
프로토콜(claude/codex/cursor)이 페이로드 필드를 뭘 지원하든 태그는 살아남는다.

hooks 는 자기완결 단일 파일로 배포되어 이 모듈을 임포트하지 못한다 — verifier_gate.GATE_MESSAGES
가 같은 표의 사본을 품고, tests/test_failures.py 패리티 테스트가 두 표를 동일하게 봉인한다.

코드 표기는 kebab-case 단일 정본 (구 no_verdict/stale_pass 언더스코어 표기 폐지). failure_sig
(퀘스트 로그 동종 실패 키)도 같은 어휘를 쓴다 — 모델 자유 기술은 normalize_sig 로 슬러그화해
3-strike 동종 판정이 표기 흔들림에 무뎌지지 않게 한다.
"""

from __future__ import annotations

import re

# ── 게이트 차단 메시지 — verifier_gate.py 의 사본과 패리티 테스트로 봉인 ──
GATE_MESSAGES: dict[str, str] = {
    "orphan-write": (
        "이 세션이 파일을 썼는데({files}) 퀘스트 로그가 없습니다. write 과업은 Trinity "
        "순환이 필수입니다: python3 <hooks>/quest-log.py open <quest-id> --criteria "
        '"..." 로 로그를 열고 Verifier 검증을 기록하세요.'
    ),
    "unsafe-map": "unsafe code map symlink/junction: {targets}",
    "snapshot-fail": "현재 워킹트리 snapshot 생성 실패 — 변경 증거를 계산할 수 없어 종료를 거부합니다.",
    "no-verdict": "write 과업인데 Verifier 판정(PASS/ESCALATE) 레코드가 없습니다.",
    "escalate-nudge": (
        "무인 세션에서 작업 시도 없이 ESCALATE 로 종료하려 합니다 (Canon 8 무인 진행). "
        "오딘의 답은 오지 않습니다 — 방어 가능한 기본안을 골라 가정을 plan criteria "
        "`가정: ...` 으로 기록하고 Worker 를 디스패치하세요. 어떤 기본안도 방어 불가한 "
        "진짜 블로커면 사유를 기록하고 다시 ESCALATE 하면 통과됩니다."
    ),
    "stale-pass": "stale PASS — PASS 기록 이후 워킹트리가 변경되었습니다 (물리 대조 불일치). 재검증 필요.",
    "no-criteria": "성공 기준(criteria)이 로그에 없습니다. 검증은 기준 없이는 성립하지 않습니다.",
    "tickets-incomplete": "미완료 ticket 존재({units}) — 모든 단위를 done으로 만든 뒤 검증하세요.",
    "criteria-unverified": (
        "criteria verify 계약 미충족 ({unmet}) — 계약이 선언된 기준은 그 명령·산출물만 증거입니다. "
        "quest-log append --verdict PASS 가 계약 명령을 하네스로 재실행합니다."
    ),
    "no-evidence": (
        "PASS 에 성공한 검증 명령 증거(commands[{{cmd,exit_code==0}}])가 없습니다. "
        "Verifier 는 검증 명령을 직접 실행해야 합니다 (true/echo 류 무조건-성공 명령은 증거가 아닙니다)."
    ),
    "baseline-red": "하네스 베이스라인 체크 red ({failing}) — 실패한 체크를 수정한 뒤 재검증하세요.",
    "micro-pass": (
        "full-verify 필요(민감 경로 {sensitive}{deleted} / diff {files} files·{lines} lines)한데 "
        "micro PASS 입니다. --level full 로 재검증하세요."
    ),
}

# 하네스가 직접 찍는 failure_sig — 게이트 코드와 같은 어휘 공간 (퀘스트 로그에 영속)
HARNESS_SIGS: frozenset[str] = frozenset(
    {
        "snapshot-unavailable",
        "map-refresh-failed",
        "unsafe-map-link",
        "criteria-contract",
        "baseline-red",
        "lagom-style",
        "no-verdict-submitted",
        "invalid-verdict-submitted",
        "no-verification-evidence",
        "unresolved-verification-failure",
    }
)

KNOWN_CODES: frozenset[str] = frozenset(GATE_MESSAGES) | HARNESS_SIGS

_GATE_TAG = re.compile(r"\[gate:([a-z0-9][a-z0-9-]*)\]")

# 코드별 수리 전이 — 게이트 차단의 응답은 무수리 재시도가 아니라 사유에 맞는 턴이다.
# criteria 부재만 계획 보강, baseline red·미완료 ticket 은 코드/단위 수리(Worker),
# 무인 ESCALATE 넛지는 기본안 재계획, 나머지는 전부 신선 증거 재검증.
_REPAIRS: dict[str, tuple[str, str]] = {
    "no-criteria": ("THINKER_REPLAN", "게이트: criteria 부재 — 계획 보강 필요"),
    "baseline-red": ("WORKER_RETRY", "게이트: 하네스 베이스라인 red — 실패한 체크를 수정"),
    "tickets-incomplete": ("WORKER_RETRY", "게이트: 미완료 ticket — 미완료 단위만 재배정"),
    "escalate-nudge": ("THINKER_REPLAN", "게이트: 무인 ESCALATE — 방어 가능한 기본안으로 재계획 (Canon 8)"),
}


def gate_message(code: str, **params: object) -> str:
    """코드 → `[gate:<code>] <문장>` — 게이트 차단 사유의 유일한 조립 경로."""
    return "[gate:%s] " % code + GATE_MESSAGES[code].format(**params)


def parse_gate_code(text: str) -> str | None:
    """메시지에서 게이트 코드 직독 — 문장 파싱(부분 문자열 매칭)의 대체."""
    m = _GATE_TAG.search(str(text or ""))
    return m.group(1) if m else None


def repair_for(code: str) -> tuple[str, str]:
    """차단 코드 → (수리 전이, 사유 노트)."""
    return _REPAIRS.get(code) or ("VERIFIER", "게이트 차단(%s) — 신선한 증거로 재검증" % code)


_SLUG_JUNK = re.compile(r"[\s_/:,;.!?()\[\]{}<>|\"'`~*+=@#$%^&\\]+")
_SLUG_KEEP = re.compile(r"[^\w-]")


def normalize_sig(text: str) -> str:
    """자유 기술 failure_sig → kebab-case 슬러그. 같은 원인의 표기 흔들림(공백·언더스코어·
    구두점·대소문자)을 하나로 접어 3-strike 동종 판정 키를 안정화한다. 한글 등 비ASCII
    단어문자는 보존 — 전부 지우면 서로 다른 원인이 한 슬러그로 뭉개져 오탈출한다."""
    s = _SLUG_JUNK.sub("-", str(text or "").strip().lower())
    s = _SLUG_KEEP.sub("", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:48].rstrip("-") or "unspecified"
