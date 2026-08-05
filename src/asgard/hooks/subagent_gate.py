#!/usr/bin/env python3
# Asgard subagent-gate — Trinity 역할 서브에이전트의 로그 규율 강제 (Claude Code SubagentStop).
#
# 모드 B의 유일한 프롬프트-의존 축은 "역할이 자기 이벤트를 quest 로그에 기록한다"는 계약이다
# (프롬프트 준수는 가정이 아니라 측정 대상). 이 훅은 그 계약을 코드로 바꾼다 —
# asgard-thinker/worker/verifier 서브에이전트가 활성 quest에 자기 역할 이벤트를 기록하지 않고
# 종료하면 1회 차단하고 정확한 append 명령을 지시한다 (증거-영수증 게이트).
#
# 차단 알고리즘 (deterministic만 block, 그 외 전부 allow — fail-open 유지):
#   활성 quest 없음 / 파싱 실패 / 미지의 agent_type → allow (DIRECT·비-Trinity 디스패치 존중)
#   thinker  종료: 마지막 verify 이후 plan 이벤트 없음   → block (재계획 포함)
#   worker   종료: 마지막 verify 이후 work 이벤트 없음   → block
#   verifier 종료: 마지막 work 이후 verify 이벤트 없음   → block
#   verifier PASS 인데 성공 명령 증거 없음               → block (조기 피드백 — Stop 게이트 전에)
#
# 왜 역할당 2회 상한인가: SubagentStop block 루프는 서브에이전트를 인질로 잡는다. 같은 세션에서
# 같은 역할을 2회 차단하면 3번째는 경고와 함께 통과 — 최종 담보는 어차피 Stop의 verifier-gate
# (diff-hash 물리 대조)다. 이 훅은 조기 교정 장치지 최후 방벽이 아니다.
from __future__ import annotations

import json
import os
import re
import sys
import time

# Windows 콘솔/파이프 기본 인코딩(cp1252 등)은 한국어 출력을 넣지 못한다 — 인코딩 오류가
# fail-open에 삼켜지면 훅 판정이 통째로 증발한다 (게이트 block → 조용한 allow). UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute] — TextIOWrapper 전용, 대체 스트림은 except로
    except Exception:
        pass


MAX_BLOCKS = 2  # 역할당 — 3번째는 통과 (최후 방벽은 verifier-gate)
ROLE_EVENT = {"asgard-thinker": "plan", "asgard-worker": "work", "asgard-verifier": "verify"}
# 누가 누구를 띄울 수 있는가 — AGENTS.md 트리니티 절의 위임 그래프가 정본이다.
#
# **표는 전수여야 한다.** 판정이 `agent in AGENT_TARGETS` 라, 표에 없는 역할은 검사 자체를
# 안 받고 무엇이든 띄운다. 종전에는 thinker·worker·eitri·planner·mimir·loki·ullr 이 전부
# 빠져 있어서, 읽기 전용인 Thinker 가 Worker 를 띄워 트리를 고칠 수 있었고 Worker 가 자기
# 판정자를 띄울 수 있었다 — 검증 독립성이 프런트매터 산문에만 얹혀 있었다 (26-08-05 감사).
# 빈 frozenset 은 "재위임 없음"이라는 **선언**이고, 항목이 없는 것과 뜻이 다르다.
AGENT_TARGETS = {
    # Verifier 는 적대적 읽기 전용 하나만 — 쓰기 가능한 손을 부르면 자기가 고친 diff 를 자기가 심판한다.
    "asgard-verifier": frozenset({"asgard-loki"}),
    # Thinker 는 탐사 정찰 하나만. 계획하는 손은 트리를 만지지 않는다.
    "asgard-thinker": frozenset({"asgard-ullr"}),
    # Worker 는 변경 표면별 딜리버리와 코드 안내자, 그리고 반례 사냥까지.
    # **판정자와 계획자는 자기가 부르지 않는다** — 자기 일을 심판할 손을 자기가 고르는 자리다.
    # loki 는 다르다: 읽기 전용이고 판정을 내지 않아, 쓰기 가능한 역할이 자기 작업의 반례를
    # 찾는 데 써도 독립성이 상하지 않는다. 깨지는 것은 **판정자가 쓰기 가능한 손을 부를 때**뿐이다.
    "asgard-worker": frozenset(
        {"asgard-freyja", "asgard-thor", "asgard-thor-lead", "asgard-eitri", "asgard-mimir", "asgard-loki"}
    ),
    # thor-lead 의 임무는 sub-Thor 편성이다 (깊이 1). 반례 사냥은 위와 같은 이유로 함께 연다.
    "asgard-thor-lead": frozenset({"asgard-thor", "asgard-loki"}),
    # 전문가는 재위임하지 않는다.
    "asgard-freyja": frozenset(),
    "asgard-thor": frozenset(),
    "asgard-eitri": frozenset(),
    "asgard-planner": frozenset(),
    "asgard-mimir": frozenset(),
    "asgard-loki": frozenset(),
    "asgard-ullr": frozenset(),
}
# 역할 이벤트의 "신선도" 기준점 — 이 이벤트 뒤에 자기 이벤트가 있어야 이번 턴 기록으로 인정.
ANCHOR = {"plan": "verify", "work": "verify", "verify": "work"}
# 이벤트 이름은 역할 이름이 아니다 — 기장 명령이 시키는 `role` 값은 여기서 온다.
EVENT_ROLE = {"plan": "thinker", "work": "worker", "verify": "verifier"}


def _read_text(path: str) -> str:
    """파일을 통째로 읽는다. 오류는 그대로 올린다 — 호출부마다 삼킬 범위가 다르다. quest_log.py와 동일 유지.

    핸들 수명을 여기서 끝내는 것이 요점이다. `open(p).read()`는 CPython의 참조 계수에 기대
    곧장 닫히는 것이고, 그 기댐은 코드에 안 적혀 있어서 다른 런타임에서 조용히 깨진다."""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _load_json(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def trivial_evidence(cmd):
    """quest_log.py의 trivial_evidence와 동일 유지 (단일 출처 원칙)."""
    c = " ".join(str(cmd).split())
    return c in ("true", ":", "exit 0", "echo") or c.startswith("echo ")


def pass_evidence(rec):
    """verifier_gate.py의 pass_evidence와 동일 유지 (단일 출처 원칙)."""
    if (rec.get("baseline") or {}).get("state") == "green":
        return True
    return any(
        isinstance(c, dict) and c.get("exit_code") == 0 and not trivial_evidence(c.get("cmd", ""))
        for c in (rec.get("commands") or [])
    )


def block(root, sid, agent, reason, *, protocol="claude"):
    """차단 — 단 세션·역할당 MAX_BLOCKS 회. 초과 시 warn+allow (인질극 방지)."""
    path = os.path.join(root, ".asgard", "subgate-" + sid + ".json")
    counts = {}
    try:
        with open(path, encoding="utf-8") as handle:
            counts = json.load(handle)
        counts = counts if isinstance(counts, dict) else {}
    except Exception:
        pass
    n = int(counts.get(agent, 0)) + 1
    counts[agent] = n
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())  # temp+rename — 크래시 절단이 카운터를 리셋하지 않게
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(counts, handle)
        os.replace(tmp, path)
    except Exception:
        pass
    if n > MAX_BLOCKS:
        sys.stderr.write(
            "asgard subagent-gate: %s exceeded %d block(s) — allowing (verifier-gate is the final backstop)\n"
            % (agent, MAX_BLOCKS)
        )
        sys.exit(0)
    message = "Asgard subagent-gate: " + reason
    if protocol == "cursor":
        payload = {"followup_message": message}
    elif protocol == "codex":
        payload = {"continue": False, "stopReason": message}
    else:
        payload = {"decision": "block", "reason": message}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.exit(0)


def deny_pretool(protocol: str, message: str) -> None:
    if protocol == "cursor":
        sys.stdout.write(
            json.dumps(
                {"permission": "deny", "user_message": message, "agent_message": message},
                ensure_ascii=False,
            )
        )
        sys.exit(0)
    print(message, file=sys.stderr)
    sys.exit(2)


def quest_pointer(root: str, sid: str) -> str | None:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(sid or "default"))[:64] or "default"
    sessions = os.path.join(root, ".asgard", "quest", "sessions")
    session_path = os.path.join(sessions, name + ".active")
    try:
        qid = _read_text(session_path).strip()
        if qid:
            return qid
    except Exception:
        pass
    if os.path.exists(os.path.join(sessions, name + ".known")):
        return None
    try:
        active = {
            _read_text(os.path.join(sessions, entry)).strip()
            for entry in os.listdir(sessions)
            if entry.endswith(".active")
        }
        active.discard("")
        if len(active) == 1:
            return next(iter(active))
    except Exception:
        pass
    if os.path.isdir(sessions):
        return None
    for path in (os.path.join(root, ".asgard", "quest", "ACTIVE"),):
        try:
            qid = _read_text(path).strip()
            if qid:
                return qid
        except Exception:
            continue
    return None


def receipt_path(root: str, qid: str, agent_id: str) -> str:
    safe_agent = re.sub(r"[^A-Za-z0-9_.-]", "_", agent_id)[:96]
    return os.path.join(root, ".asgard", "quest", "receipts", qid, "agent-" + safe_agent + ".json")


def record_agent_start(root: str, qid: str, sid: str, agent: str, agent_id: str, task: str = "") -> None:
    if not agent_id:
        return
    path = receipt_path(root, qid, agent_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    record = {
        "schema": 1,
        "quest_id": qid,
        "session_id": sid,
        "agent_type": agent,
        "agent_id": agent_id,
        "task": task,
        "started_at": time.time_ns(),
        "stopped_at": None,
    }
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def record_agent_stop(root: str, qid: str, agent_id: str, agent: str = "", task: str = "") -> None:
    if not agent_id:
        directory = os.path.join(root, ".asgard", "quest", "receipts", qid)
        candidates = []
        try:
            for name in os.listdir(directory):
                if not name.startswith("agent-"):
                    continue
                record = _load_json(os.path.join(directory, name))
                if (
                    record.get("agent_type") == agent
                    and record.get("stopped_at") is None
                    and (not task or record.get("task") == task)
                ):
                    candidates.append(record)
        except Exception:
            return
        if not candidates:
            return
        agent_id = str(max(candidates, key=lambda record: int(record.get("started_at") or 0)).get("agent_id") or "")
    if not agent_id:
        return
    path = receipt_path(root, qid, agent_id)
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        if record.get("quest_id") != qid or record.get("stopped_at") is not None:
            return
        record["stopped_at"] = max(time.time_ns(), int(record.get("started_at") or 0) + 1)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        return


def record_worker_dispatch(root: str, qid: str, sid: str, tool_use_id: str, tool_input: dict) -> bool:
    prompt = str(
        tool_input.get("prompt")
        or tool_input.get("task")
        or tool_input.get("message")
        or tool_input.get("description")
        or ""
    )
    match = re.search(r"\[ASGARD_UNIT:([^\]]+)\]", prompt)
    if not match:
        return False
    raw_unit = match.group(1).strip()
    unit = int(raw_unit) if raw_unit.isdigit() else raw_unit[:80]
    safe_call = re.sub(r"[^A-Za-z0-9_.-]", "_", tool_use_id or ("call-%d" % time.time_ns()))[:96]
    directory = os.path.join(root, ".asgard", "quest", "receipts", qid)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "dispatch-" + safe_call + ".json")
    record = {
        "schema": 1,
        "quest_id": qid,
        "session_id": sid,
        "tool_use_id": tool_use_id,
        "agent_type": "asgard-worker",
        "unit": unit,
        "requested_at": time.time_ns(),
        "quest_turn": max((int(event.get("turn") or 0) for event in load_quest_events(root, qid)), default=0),
    }
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return True


def read_quest_events(root: str, qid: str) -> tuple[list[dict], bool]:
    """(이벤트, 읽기 성공 여부). 둘째 값을 버리면 안 된다 — **읽기 실패와 빈 로그는 다른 사실**이고,
    섞는 순간 fail-open 게이트가 fail-closed로 뒤집힌다(로그를 못 읽었을 뿐인데 차단)."""
    events: list[dict] = []
    try:
        with open(os.path.join(root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8") as handle:
            for line in handle:
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue  # 찢어진 줄 하나 — 로그 전체를 못 읽은 것과는 다르다(그쪽은 아래 False)
    except Exception:
        return events, False
    return events, True


def load_quest_events(root: str, qid: str) -> list[dict]:
    """읽기 실패를 빈 목록으로 삼키는 쪽 — 실패해도 막지 않는 호출부 전용."""
    return read_quest_events(root, qid)[0]


def ticket_view(events: list[dict]) -> dict[str, dict]:
    tickets = {}
    for event in events:
        if event.get("event") != "ticket" or event.get("unit") is None:
            continue
        key = str(event["unit"])
        current = tickets.get(key, {})
        tickets[key] = {
            "unit": event["unit"],
            "status": event.get("ticket_status") or current.get("status") or "todo",
            "access": event.get("access") if isinstance(event.get("access"), list) else current.get("access") or [],
            "files": event.get("changed_files") or current.get("files") or [],
        }
    return tickets


def _norm_path(path) -> str:
    return os.path.normpath(str(path)).replace("\\", "/")


def verifiable_units(tickets: list[dict]) -> list[str]:
    """quest_log.py의 verifiable_units와 동일 유지 (단일 출처 원칙, TestPolicyMirror로 정합 확인)."""
    open_files: set[str] = set()
    for ticket in tickets:
        if ticket.get("status") in ("todo", "in_progress"):
            files = [_norm_path(f) for f in (ticket.get("files") or [])]
            if not files:
                return []
            open_files.update(files)
    return [
        str(ticket["unit"])
        for ticket in tickets
        if ticket.get("status") == "done" and open_files.isdisjoint(_norm_path(f) for f in (ticket.get("files") or []))
    ]


def unit_marker(tool_input: dict) -> str | None:
    """Verifier 조기(파이프라인) 디스패치의 [ASGARD_UNIT:<id>] 마커 — record_worker_dispatch와
    동일한 파싱 규칙(같은 unit이 같은 문자열 키로 귀결)을 독립적으로 미러링한다."""
    prompt = str(
        tool_input.get("prompt")
        or tool_input.get("task")
        or tool_input.get("message")
        or tool_input.get("description")
        or ""
    )
    match = re.search(r"\[ASGARD_UNIT:([^\]]+)\]", prompt)
    if not match:
        return None
    raw_unit = match.group(1).strip()
    return str(int(raw_unit)) if raw_unit.isdigit() else raw_unit[:80]


def call_spec(tool_input: dict) -> str:
    """이 호출로 무엇을 시켰는가 — 장부의 Task 한 줄. 없으면 빈 문자열."""
    text = str(tool_input.get("description") or tool_input.get("prompt") or tool_input.get("task") or "")
    for line in text.splitlines():
        stripped = re.sub(r"\[ASGARD_UNIT:[^\]]*\]", "", line).strip()
        if stripped:
            return stripped[:500]
    return ""


def siege_open(root: str, qid: str, caller: str, target: str, tool_input: dict) -> None:
    """호출된 에이전트를 배차 장부에 세운다 — 호스트 모드에서 이것이 적히는 유일한 자리.

    네이티브 루프는 `agent/heimdall/bifrost.py` 가 같은 것을 프로세스 안에서 적는다. 세 호스트
    모드에는 그 루프가 없고 디스패치를 아는 자리가 이 훅뿐이라, 여기가 없으면 `asgard siege` 는
    어떤 에이전트가 불렸는지 영영 말하지 못한다 — 오늘 잡히는 것은 배정 단위 티켓뿐이다.

    실패는 삼킨다. 장부는 퀘스트 로그에서 파생된 기록이고, 파생을 얻으려다 디스패치를 막는
    교환은 성립하지 않는다.
    """
    try:
        from asgard import orchestration as orc

        # 목표는 Run 을 처음 열 때만 쓴다. 이미 열려 있으면 퀘스트 로그를 통째로 읽을 까닭이
        # 없다 — 이 훅은 서브에이전트를 띄우는 길목이라 매 호출의 지연이 그대로 얹힌다.
        objective = qid
        if orc.run_for_quest(root, qid) is None:
            objective = next((e.get("request") for e in load_quest_events(root, qid) if e.get("request")), "") or qid
        orc.note_agent(
            root,
            qid,
            target,
            spec=call_spec(tool_input),
            objective=str(objective),
            caller=caller,
        )
    except Exception:
        return


def siege_close(root: str, qid: str, agent: str, summary: str = "") -> None:
    """그 에이전트의 살아 있는 시도를 접는다. `siege_open` 이 연 것만 — 배정 단위 티켓의
    수명은 ticket-finish 가 쥔다.

    결과는 언제나 `succeeded` 다. 이 자리가 아는 것은 호출이 답을 들고 돌아왔다는 사실뿐이고,
    판정의 옳고 그름은 다른 축이다 — 네이티브의 `bifrost.settle_turn` 도 턴이 예외로 죽었을
    때만 failed 를 적는다. Verifier 의 FAIL 은 `summary` 로 간다.
    """
    try:
        from asgard import orchestration as orc

        orc.close_agent(root, qid, agent, "succeeded", summary=summary)
    except Exception:
        return


def _role_summary(event: dict, want: str) -> str:
    """역할 턴이 장부에 남길 한 줄 — 퀘스트 로그가 실제로 든 값만 옮긴다.

    이벤트에 자유 서술 칸은 없다. 판정은 `verdict`(+`level`), 나머지는 단위 설명이나 바꾼 파일
    수가 전부다 — 없는 것을 지어내면 장부가 근거를 잃는다.
    """
    if want == "verify":
        level = event.get("level")
        return "판정 %s%s" % (event.get("verdict") or "NA", " (%s)" % level if level else "")
    subtask = str(event.get("subtask") or "").strip()
    if subtask:
        return subtask[:200]
    changed = event.get("changed_files") or []
    return "파일 %d건 변경" % len(changed) if changed else ""


def pipeline_denial_reason(tickets: dict[str, dict], unit: str) -> str:
    """왜 이 유닛이 아직 조기 검증 대상이 아닌지 — done 아님 / 파일 미선언 / 파일 충돌 순으로 구체화."""
    ticket = tickets.get(unit)
    if not ticket:
        return "unknown unit %s" % unit
    if ticket["status"] != "done":
        return "unit %s is not done yet (status: %s)" % (unit, ticket["status"])
    open_tickets = [t for t in tickets.values() if t["status"] in ("todo", "in_progress")]
    undeclared = sorted(str(t["unit"]) for t in open_tickets if not t.get("files"))
    if undeclared:
        return "open unit(s) declared no files (disjointness unprovable): " + ", ".join(undeclared)
    mine = {_norm_path(f) for f in ticket.get("files") or []}
    overlapping = sorted(str(t["unit"]) for t in open_tickets if mine & {_norm_path(f) for f in t.get("files") or []})
    if overlapping:
        return "unit %s files overlap with still-open unit(s): %s" % (unit, ", ".join(overlapping))
    return "unit %s is not yet early-verifiable" % unit


def mode_b_receipts(root: str, qid: str, sid: str) -> tuple[list[dict], list[dict]]:
    directory = os.path.join(root, ".asgard", "quest", "receipts", qid)
    agents, dispatches = [], []
    try:
        names = os.listdir(directory)
    except Exception:
        return agents, dispatches
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            record = _load_json(os.path.join(directory, name))
        except Exception:
            continue
        if record.get("quest_id") != qid or record.get("session_id") != sid:
            continue
        if name.startswith("agent-"):
            agents.append(record)
        elif name.startswith("dispatch-"):
            dispatches.append(record)
    return agents, dispatches


def physical_worker_problem(root: str, qid: str, sid: str, tickets: dict[str, dict]) -> str:
    if not tickets:
        return ""
    agents, dispatches = mode_b_receipts(root, qid, sid)
    workers = [
        record
        for record in agents
        if record.get("agent_type") == "asgard-worker" and record.get("started_at") and record.get("stopped_at")
    ]
    distinct = {str(record.get("agent_id")) for record in workers if record.get("agent_id")}
    if len(distinct) < len(tickets):
        return "physical worker receipts missing: expected %d distinct completed agents, got %d" % (
            len(tickets),
            len(distinct),
        )
    dispatched = {str(record.get("unit")) for record in dispatches if record.get("agent_type") == "asgard-worker"}
    missing = sorted(set(tickets) - dispatched)
    if missing:
        return "physical worker dispatch receipts missing for unit(s): " + ", ".join(missing)
    dispatch_turn = {}
    for record in dispatches:
        key = str(record.get("unit"))
        dispatch_turn[key] = max(dispatch_turn.get(key, 0), int(record.get("quest_turn") or 0))
    done_turn = {}
    for event in load_quest_events(root, qid):
        if event.get("event") == "ticket" and event.get("ticket_status") == "done" and event.get("unit") is not None:
            key = str(event["unit"])
            done_turn[key] = max(done_turn.get(key, 0), int(event.get("turn") or 0))
    for key, ticket in tickets.items():
        for dependency in ticket["access"]:
            dep = str(dependency)
            if dispatch_turn.get(key, 0) <= done_turn.get(dep, 0):
                return "dependency fan-in violation: unit %s dispatched before unit %s completed" % (key, dep)
    done, remaining, max_wave = set(), dict(tickets), 0
    while remaining:
        ready = [key for key, ticket in remaining.items() if {str(dep) for dep in ticket["access"]} <= done]
        if not ready:
            return "ticket dependency graph is cyclic or incomplete"
        max_wave = max(max_wave, len(ready))
        done.update(ready)
        for key in ready:
            remaining.pop(key)
    points = []
    for record in workers:
        points.append((int(record["started_at"]), 1))
        points.append((int(record["stopped_at"]), -1))
    active = observed = 0
    for _, delta in sorted(points, key=lambda point: (point[0], -point[1])):
        active += delta
        observed = max(observed, active)
    if observed < max_wave:
        return "parallel worker overlap missing: expected concurrency %d, observed %d" % (max_wave, observed)
    return ""


def record_hint(hooks_dir: str, want: str) -> str:
    """미기록 종료를 막을 때 같이 건네는 기장 명령.

    `uv run --no-project python` 은 platform.hook_python_token() 의 정본을 리터럴로 옮긴 것이다 —
    이 파일은 자기완결 배포라 asgard 를 임포트할 수 없고, uv 는 설치 경로가 보장하는 런타임이라
    여기서 다시 탐지할 것이 없다.

    형태가 **명령 하나 + 상대 경로**인 이유는 허용목록이다. 호스트의 Bash 규칙은
    `Bash(uv run --no-project python .claude/hooks/quest-log.py *)` 처럼 원문 프리픽스로 맞추므로,
    `$CLAUDE_PROJECT_DIR` 절대 형태는 한 글자도 안 겹치고 파이프라인은 앞 세그먼트(`echo`)까지
    허용목록을 요구한다. 둘 다 헤드리스에서 자동 거부 → 이벤트 미기록 → 재차단의 교착이다."""
    return 'uv run --no-project python %s/quest-log.py append --json \'{"role":"%s","event":"%s",...}\'%s' % (
        hooks_dir,
        EVENT_ROLE[want],
        want,
        " --verdict PASS|FAIL --level micro|full (must run the verification commands directly and record them)"
        if want == "verify"
        else "",
    )


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        protocol_arg = sys.argv[1] if len(sys.argv) > 1 else ""
        protocol = "cursor" if protocol_arg in {"pre", "start", "stop"} else protocol_arg or "claude"
        event = str(data.get("hook_event_name") or protocol_arg)
        agent = str(data.get("agent_type") or data.get("subagent_type") or "")
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        raw_sid = "cursor" if protocol == "cursor" else data.get("session_id") or "default"
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw_sid))[:64]
        qid = quest_pointer(root, sid)
        if event in {"PreToolUse", "preToolUse", "pre"} and data.get("tool_name") in {"Agent", "Task"}:
            tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
            target = str(tool_input.get("subagent_type") or tool_input.get("agent_type") or "")
            # **위임 경계는 퀘스트와 무관하다.** 종전에는 활성 퀘스트 조회가 이 검사보다 먼저
            # 빠져나가서, 퀘스트를 열지 않은 세션에서는 판정자가 워커를 띄우는 것도 통과했다 —
            # 로그를 안 여는 것만으로 역할 경계가 사라지는 셈이었다 (26-08-05 감사).
            if agent in AGENT_TARGETS and target not in AGENT_TARGETS[agent]:
                allowed = ", ".join(sorted(AGENT_TARGETS[agent])) or "none"
                deny_pretool(
                    protocol,
                    "Asgard role boundary: %s cannot dispatch %s (allowed: %s)"
                    % (agent, target or "<missing>", allowed),
                )
            if not qid:
                # 남은 검사(티켓 배리어·배차 장부)는 퀘스트가 있어야 뜻이 있다 — 없으면
                # DIRECT·탐사 디스패치를 존중한다 (fail-open).
                if protocol == "cursor":
                    sys.stdout.write(json.dumps({"permission": "allow"}))
                sys.exit(0)
            if target == "asgard-worker":
                if not record_worker_dispatch(root, qid, sid, str(data.get("tool_use_id") or ""), tool_input):
                    deny_pretool(protocol, "Asgard Mode B: Worker Agent prompt requires [ASGARD_UNIT:<id>] marker")
            elif target == "asgard-verifier":
                tickets = ticket_view(load_quest_events(root, qid))
                unit = unit_marker(tool_input)
                if unit is not None:
                    # 유닛 단위 조기(파이프라인) 검증 — 전 티켓 done 배리어와 동시성 감사
                    # (physical_worker_problem)는 웨이브 전체용이라 여기선 전제가 아니다.
                    if unit not in verifiable_units(list(tickets.values())):
                        deny_pretool(protocol, "Asgard Mode B: " + pipeline_denial_reason(tickets, unit))
                else:
                    unfinished = sorted(
                        str(ticket["unit"]) for ticket in tickets.values() if ticket["status"] != "done"
                    )
                    if unfinished:
                        deny_pretool(protocol, "Asgard Mode B: unfinished ticket(s): " + ", ".join(unfinished))
                    problem = physical_worker_problem(root, qid, sid, tickets)
                    if problem:
                        deny_pretool(protocol, "Asgard Mode B: " + problem)
            # 통과한 디스패치만 장부에 세운다 — 거절된 호출은 돌지 않으므로 시도가 아니다.
            # 단위 마커가 붙은 호출은 건너뛴다: 그 수명은 ticket-claim/finish 가 이미 쥐고 있고
            # (quest_log._siege_mirror), 여기서 또 열면 한 Task 를 둘이 연다.
            if target and unit_marker(tool_input) is None:
                siege_open(root, qid, agent, target, tool_input)
            if protocol == "cursor":
                sys.stdout.write(json.dumps({"permission": "allow"}))
            sys.exit(0)
        if not qid:
            sys.exit(0)  # 활성 quest 없음 → 로그 규율의 대상이 아니다 (fail-open)
        stopping = event in {"SubagentStop", "subagentStop", "stop"}
        want = ROLE_EVENT.get(agent)
        if not want:
            # Trinity 역할 아님 (딜리버리 전문가 포함) → 로그 규율의 대상은 아니다. 그래도 장부는
            # 접는다: 안 접으면 `siege show` 가 이미 끝난 에이전트를 영영 "도는 중" 으로 보인다.
            if stopping:
                siege_close(root, qid, agent)
            sys.exit(0)
        task = str(data.get("task") or data.get("description") or "")
        agent_id = str(data.get("agent_id") or data.get("subagent_id") or "")
        if event in {"SubagentStart", "subagentStart", "start"}:
            record_agent_start(root, qid, sid, agent, agent_id, task)
            sys.exit(0)
        events, readable = read_quest_events(root, qid)
        if not readable:
            sys.exit(0)  # 로그 읽기 실패 → allow (fail-open)

        anchor = ANCHOR[want]
        last_anchor = max((i for i, e in enumerate(events) if e.get("event") == anchor), default=-1)
        fresh = [e for i, e in enumerate(events) if i > last_anchor and e.get("event") == want]
        script = os.path.realpath(__file__).replace("\\", "/")
        hooks_dir = next(
            (f".{client}/hooks" for client in ("claude", "cursor", "codex") if f"/.{client}/hooks/" in script),
            ".claude/hooks",
        )
        if not fresh:
            block(
                root,
                sid,
                agent,
                "%s is trying to end quest %s without recording a %s event. A role is only fulfilled by "
                "logging it — record it, then end: %s" % (agent, qid, want, record_hint(hooks_dir, want)),
                protocol=protocol,
            )
        if want == "verify":
            last = fresh[-1]
            if last.get("verdict") == "PASS" and not pass_evidence(last):
                block(
                    root,
                    sid,
                    agent,
                    "PASS has no successful verification-command evidence (commands[{cmd,exit_code==0}]). "
                    "Run the verification command directly and re-record the result via append "
                    "(unconditionally-successful commands like true/echo do not count as evidence).",
                    protocol=protocol,
                )
        record_agent_stop(root, qid, agent_id, agent, task)
        # 규율을 통과한 뒤에 접는다 — 차단된 역할은 아직 안 끝났고, 접어 두면 이어지는 두 번째
        # 종료가 접을 것을 못 찾아 그 역할이 장부에서 한 번 돈 것으로 남는다.
        siege_close(root, qid, agent, summary=_role_summary(fresh[-1], want))
        # 통과 → 이 역할의 차단 카운터 리셋 (다음 위반은 새로 계수)
        try:
            path = os.path.join(root, ".asgard", "subgate-" + sid + ".json")
            with open(path, encoding="utf-8") as handle:
                counts = json.load(handle)
            if isinstance(counts, dict) and agent in counts:
                counts.pop(agent)
                tmp = "%s.%d.tmp" % (path, os.getpid())
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(counts, handle)
                os.replace(tmp, path)
        except Exception:
            pass
    except Exception:
        sys.exit(0)  # 훅 자체 오류 = allow — 게이트가 죽어도 서브에이전트를 인질로 잡지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
