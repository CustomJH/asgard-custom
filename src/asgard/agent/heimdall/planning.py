"""Worker 배정 단위 계획 — Thinker 계획 파싱, wave 위상 정렬, 재개 스냅샷.

Worker wave 병렬 (Fugu Conductor analog) — 배정 단위 {id, subtask, files, criteria, access}.
실행은 waves.WaveRunner 몫 — 여기는 계획의 파싱·검증·정렬만 (순수 계층 + 퀘스트 로그 읽기).
"""

from __future__ import annotations

import json
import os
import re

from ...orchestration import OrchestrationError, topo_waves

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
    """access 의존 위상 정렬 + 파일 겹침 직렬화 — 같은 wave 안은 병렬 안전 (경로 겹침 게이트).

    일정은 orchestration.topo_waves 하나가 짠다. 여기서 하는 일은 경로 정규화뿐이다 — 겹치는
    단위 쌍을 conflicts 로 넘긴다. 배차 장부(bifrost.register_units)도 같은 함수를 부르므로
    장부에 적힌 wave 와 실제로 실행한 wave 가 갈라지지 않는다. realpath 를 부르는 절반이 이
    파일에 남는 이유는 orchestration.model 이 파일을 보지 않기 때문이다.

    Raises:
        ValueError: access 가 순환하거나 목록에 없는 단위를 가리킬 때. WaveRunner 와 trinity 가
            이 예외를 그대로 받으므로 topo_waves 의 OrchestrationError 를 여기서 바꿔 던진다.
    """

    def path_key(path: object) -> str:
        raw = os.path.abspath(os.path.join(root or os.getcwd(), str(path)))
        return os.path.realpath(raw).replace(os.sep, "/").casefold().rstrip("/")

    def overlaps(left: set[str], right: set[str]) -> bool:
        return any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in left for b in right)

    ids = {unit["id"] for unit in units}
    if any(not set(unit.get("access") or []) <= ids for unit in units):
        # topo_waves 는 목록 밖 의존을 무시하지만 배정 단위에서는 그것이 실행 순서 유실이다.
        raise ValueError("invalid unit dependency graph")  # _parse_units 검증의 방어적 백스톱

    # 자리 번호를 topo_waves 의 id 로 쓴다. 준비 집합을 정렬 순으로 훑으므로 자릿수를 맞춰야
    # 그 순서가 units 목록 순서와 같아지고, 겹침으로 미루는 단위가 달라지지 않는다.
    width = len(str(len(units)))
    keys = [f"{index:0{width}d}" for index in range(len(units))]
    key_by_id = {unit["id"]: keys[index] for index, unit in enumerate(units)}
    files = [{path_key(path) for path in (unit.get("files") or [])} for unit in units]
    deps = {keys[index]: [key_by_id[dep] for dep in (unit.get("access") or [])] for index, unit in enumerate(units)}
    conflicts = {
        keys[left]: {
            keys[right] for right in range(len(units)) if right != left and overlaps(files[left], files[right])
        }
        for left in range(len(units))
    }
    try:
        waves = topo_waves(keys, deps, conflicts)
    except OrchestrationError as cycle:
        raise ValueError("invalid unit dependency graph") from cycle
    unit_by_key = {keys[index]: unit for index, unit in enumerate(units)}
    return [[unit_by_key[key] for key in wave] for wave in waves]


def _resume_snapshot(root: str, qid: str) -> dict:
    """Materialize a resumable unit graph without replaying completed tickets."""
    from ...hooks.quest_log import fold_tickets, load_events, replay_ledger

    events = load_events(root, qid)
    replayed = replay_ledger(events)
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
    return {
        "quest_id": qid,
        "execution_id": replayed.get("execution_id"),
        "request": replayed.get("request") or "",
        "criteria": list(replayed.get("criteria") or []),
        "units": retryable,
        "completed": [ticket["id"] for ticket in tickets.values() if ticket["status"] == "done"],
        "blocked": [ticket["id"] for ticket in tickets.values() if ticket["status"] == "blocked"],
        "active": [ticket["id"] for ticket in tickets.values() if ticket["status"] == "in_progress"],
    }


# Thinker에게 요구하는 배정 단위 출력 계약 (네이티브) — 독립 단위는 wave 병렬로 실행된다
_UNITS_NOTE = (
    "\n\nAt the end of the plan, emit the Worker assignment units as a JSON block "
    "(independent units run in parallel):\n"
    '```json\n{"units":[{"id":1,"subtask":"...","files":["path"],"criteria":["..."],"access":[]}]}\n```\n'
    "access = list of prior unit ids whose results this unit must reference (empty array if "
    "independent — runs isolated). Do not split units sharing the same file without access "
    "between them. For a single task, emit 1 unit."
)
