"""이벤트 해시 연결과 정체성 — 로그가 재개 전에 손대졌는지를 본다.

비밀키 서명이 아니라 crash/replay 무결성 장치다: 한 줄 원자 append 는 동시 writer 의 절단만
막고, 수동 편집·부분 복사·중간 줄 유실은 못 잡는다. 각 줄을 이전 줄 해시에 묶어 그 자리를
드러낸다. 완료 위조 방어는 여기 몫이 아니다 — verifier-gate 가 Stop 시점에 워킹트리 diff 를
다시 해시해 물리 대조한다.
"""

from __future__ import annotations

import hashlib
import json

EMPTY = hashlib.sha256(b"").hexdigest()  # 변경 전무(diff 없음 + untracked 없음)의 정준 해시


def canonical_hash(value) -> str:
    """Stable local integrity digest. This is tamper-evident, not an authenticity signature."""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def acceptance_identity(
    *,
    request: str,
    criteria,
    base_ref: str,
    ignored_snapshot: dict,
    risk: dict,
) -> str:
    """Bind the exact requested outcome to the quest-start physical tree."""
    return canonical_hash(
        {
            "request": request,
            "criteria": list(criteria or []),
            "base_ref": base_ref,
            "ignored_snapshot": ignored_snapshot,
            "risk": risk,
        }
    )


def event_identity(event: dict) -> str:
    """Hash one event without its self-referential digest."""
    return canonical_hash({key: value for key, value in event.items() if key != "event_hash"})


def verification_identity(event: dict) -> str:
    """Bind a PASS to one execution, acceptance contract, physical diff and evidence set."""
    return canonical_hash(
        {
            "execution_id": event.get("execution_id"),
            "acceptance_hash": event.get("acceptance_hash"),
            "diff_hash": event.get("diff_hash"),
            "tree_ref": event.get("tree_ref"),
            "level": event.get("level"),
            "verdict": event.get("verdict"),
            "commands": event.get("commands") or [],
            "baseline": event.get("baseline") or {},
            "criteria_checks": event.get("criteria_checks") or [],
        }
    )


def ledger_integrity(events: list[dict]) -> tuple[bool, str]:
    """Validate the v2 hash chain and immutable execution/acceptance identity.

    A legacy unhashed prefix remains readable. Once a hashed event appears, every later event must
    stay protected; this lets active v1 quests migrate on their next append without rewriting history.
    """
    previous = EMPTY
    protected = False
    execution_id = None
    acceptance_hash = None
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("_corrupt"):
            return False, f"turn {index}: malformed JSON event"
        hashed = bool(event.get("event_hash"))
        if not hashed:
            if protected:
                return False, f"turn {index}: unhashed event after protected chain"
            previous = event_identity(event)
            continue
        protected = True
        if event.get("prev_event_hash") != previous:
            return False, f"turn {index}: previous event hash mismatch"
        if event.get("event_hash") != event_identity(event):
            return False, f"turn {index}: event hash mismatch"
        previous = str(event["event_hash"])
        current_execution = event.get("execution_id")
        current_acceptance = event.get("acceptance_hash")
        if not current_execution or not current_acceptance:
            return False, f"turn {index}: protected event lacks execution identity"
        execution_id = execution_id or current_execution
        acceptance_hash = acceptance_hash or current_acceptance
        if current_execution != execution_id or current_acceptance != acceptance_hash:
            return False, f"turn {index}: execution or acceptance identity changed"
    return True, "protected" if protected else "legacy"
