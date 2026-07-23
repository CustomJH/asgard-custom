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
        "This session wrote files ({files}) but there is no quest log. Write quests require "
        "the Trinity loop: open a log with python3 <hooks>/quest-log.py open <quest-id> "
        '--criteria "..." and record Verifier verification.'
    ),
    "unsafe-map": "unsafe code map symlink/junction: {targets}",
    "snapshot-fail": "Failed to snapshot the current working tree — cannot compute change evidence, refusing to close.",
    "no-verdict": "Write quest without a Verifier verdict (PASS/ESCALATE) record.",
    "escalate-nudge": (
        "Ending with ESCALATE in an unattended session without attempting the work "
        "(Canon 8 unattended progress). Odin's answer will not arrive — pick a defensible "
        "default, record the assumption as a plan criteria `가정: ...` item, and dispatch "
        "a Worker. If it is a genuine blocker no default can defend, record the reason and "
        "ESCALATE again to pass."
    ),
    "stale-pass": "stale PASS — the working tree changed after PASS was recorded (physical diff mismatch). Re-verify.",
    "no-criteria": "No success criteria in the log. Verification cannot stand without criteria.",
    "tickets-incomplete": "Incomplete tickets remain ({units}) — bring every unit to done before verifying.",
    "criteria-unverified": (
        "criteria verify contract unmet ({unmet}) — for criteria with a declared contract, only that "
        "command/artifact counts as evidence. quest-log append --verdict PASS re-runs the contract "
        "command via the harness."
    ),
    "no-evidence": (
        "PASS lacks successful verification-command evidence (commands[{{cmd,exit_code==0}}]). "
        "The Verifier must run verification commands directly (always-succeeding commands like "
        "true/echo are not evidence)."
    ),
    "baseline-red": "Harness baseline checks red ({failing}) — fix the failing checks, then re-verify.",
    "micro-pass": (
        "full-verify required (sensitive paths {sensitive}{deleted} / diff {files} files·{lines} lines) "
        "but this is a micro PASS. Re-verify with --level full."
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
    "no-criteria": ("THINKER_REPLAN", "gate: missing criteria — plan needs reinforcement"),
    "baseline-red": ("WORKER_RETRY", "gate: harness baseline red — fix the failing checks"),
    "tickets-incomplete": ("WORKER_RETRY", "gate: incomplete tickets — reassign only the unfinished units"),
    "escalate-nudge": ("THINKER_REPLAN", "gate: unattended ESCALATE — replan with a defensible default (Canon 8)"),
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
    return _REPAIRS.get(code) or ("VERIFIER", "gate block (%s) — re-verify with fresh evidence" % code)


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
