"""Worker 배정 단위 계획 — Thinker 계획 파싱, wave 위상 정렬, 재개 스냅샷.

Worker wave 병렬 (Fugu Conductor analog) — 배정 단위 {id, subtask, files, criteria, access}.
실행은 waves.WaveRunner 몫 — 여기는 계획의 파싱·검증·정렬만 (순수 계층 + 퀘스트 로그 읽기).
"""

from __future__ import annotations

import json
import os
import re

_UNITS_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def _parse_units(plan: str) -> list[dict] | None:
    """Thinker 계획 말미의 ```json {"units":[...]}``` 블록 파싱 — 실패/단일 단위는 None (기존 단일 경로)."""
    m = None
    for m_ in _UNITS_RE.finditer(plan or ""):
        m = m_  # 마지막 블록이 배정 단위
    if not m:
        return None
    try:
        units = json.loads(m.group(1)).get("units")
        if not isinstance(units, list) or not (2 <= len(units) <= 6):
            return None
        out, seen = [], set()
        for i, u in enumerate(units):
            if not isinstance(u, dict):
                return None
            subtask = u.get("subtask")
            if not subtask:
                return None
            uid_text = str(u.get("id", i + 1))
            if not re.fullmatch(r"[1-9]\d*", uid_text):
                return None
            uid = int(uid_text)
            if uid in seen:
                return None
            seen.add(uid)
            files, crit, acc = u.get("files"), u.get("criteria"), u.get("access")
            if isinstance(acc, list) and any(not re.fullmatch(r"[1-9]\d*", str(dep)) for dep in acc):
                return None
            normalized_access = [int(str(dep)) for dep in acc] if isinstance(acc, list) else []
            out.append(
                {
                    "id": uid,
                    "subtask": str(subtask),
                    "files": [str(f) for f in files] if isinstance(files, list) else [],
                    "criteria": [str(c) for c in crit] if isinstance(crit, list) else [],
                    "access": normalized_access,
                }
            )
        ids = {u["id"] for u in out}
        if any(u["id"] in u["access"] or not set(u["access"]) <= ids for u in out):
            return None  # self/unknown dependency — 의존성을 무시하고 실행하지 않는다
        resolved: set = set()
        pending = list(out)
        while pending:
            ready = [u for u in pending if set(u["access"]) <= resolved]
            if not ready:
                return None  # cycle — 잘못된 순서로 직렬 실행하는 대신 단일 안전 경로로 강등
            ready_ids = {u["id"] for u in ready}
            resolved |= ready_ids
            pending = [u for u in pending if u["id"] not in ready_ids]
        return out
    except Exception:
        return None


def _plan_waves(units: list[dict], root: str | None = None) -> list[list[dict]]:
    """access 의존 위상 정렬 + 파일 겹침 직렬화 — 같은 wave 안은 병렬 안전 (경로 겹침 게이트)."""

    def path_key(path: object) -> str:
        raw = os.path.abspath(os.path.join(root or os.getcwd(), str(path)))
        return os.path.realpath(raw).replace(os.sep, "/").casefold().rstrip("/")

    def overlaps(left: set[str], right: set[str]) -> bool:
        return any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in left for b in right)

    done: set = set()
    waves: list[list[dict]] = []
    remaining = list(units)
    while remaining:
        ready = [u for u in remaining if set(u.get("access") or []) <= done]
        if not ready:
            raise ValueError("invalid unit dependency graph")  # _parse_units 검증의 방어적 백스톱
        wave: list[dict] = []
        files_used: set[str] = set()
        for u in ready:
            fs = {path_key(path) for path in (u.get("files") or [])}
            if overlaps(fs, files_used):
                continue  # 파일 겹침 — 다음 wave 로 직렬화
            wave.append(u)
            files_used |= fs
        if not wave:
            wave = [ready[0]]
        waves.append(wave)
        ids = {u["id"] for u in wave}
        done |= ids
        remaining = [u for u in remaining if u["id"] not in ids]
    return waves


def _resume_snapshot(root: str, qid: str) -> dict:
    """Materialize a resumable unit graph without replaying completed tickets."""
    from ...hooks.quest_log import fold_tickets, load_events

    events = load_events(root, qid)
    tickets = fold_tickets(events)
    completed = {str(ticket["id"]) for ticket in tickets.values() if ticket["status"] == "done"}
    retryable = []
    for ticket in tickets.values():
        if ticket["status"] not in {"todo", "failed"}:
            continue
        retryable.append(
            {
                "id": ticket["id"],
                "subtask": ticket.get("subtask") or f"resume unit {ticket['id']}",
                "files": list(ticket.get("files") or []),
                "criteria": list(ticket.get("criteria") or []),
                "access": [
                    dependency for dependency in (ticket.get("access") or []) if str(dependency) not in completed
                ],
            }
        )
    criteria = next((list(event.get("criteria") or []) for event in events if event.get("criteria")), [])
    request = next((str(event.get("request")) for event in events if event.get("request")), "")
    return {
        "quest_id": qid,
        "request": request,
        "criteria": criteria,
        "units": retryable,
        "completed": [ticket["id"] for ticket in tickets.values() if ticket["status"] == "done"],
        "blocked": [ticket["id"] for ticket in tickets.values() if ticket["status"] == "blocked"],
        "active": [ticket["id"] for ticket in tickets.values() if ticket["status"] == "in_progress"],
    }


# Thinker 에게 요구하는 배정 단위 출력 계약 (네이티브) — 독립 단위는 wave 병렬로 실행된다
_UNITS_NOTE = (
    "\n\n계획 마지막에 Worker 배정 단위를 JSON 블록으로 산출하라 (독립 단위는 병렬 실행):\n"
    '```json\n{"units":[{"id":1,"subtask":"...","files":["경로"],"criteria":["..."],"access":[]}]}\n```\n'
    "access = 이 단위가 결과를 참조해야 하는 선행 단위 id 목록 (독립이면 빈 배열 — 격리 실행됨). "
    "파일이 겹치는 단위는 같은 파일을 access 없이 나누지 마라. 단일 작업이면 units 1개."
)
