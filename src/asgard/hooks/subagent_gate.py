#!/usr/bin/env python3
# Asgard subagent-gate — Trinity 역할 서브에이전트의 로그 규율 강제 (Claude Code SubagentStop).
#
# 모드 B 의 유일한 프롬프트-의존 축은 "역할이 자기 이벤트를 quest 로그에 기록한다"는 계약이다
# (프롬프트 준수는 가정이 아니라 측정 대상). 이 훅은 그 계약을 코드로 바꾼다 —
# asgard-thinker/worker/verifier 서브에이전트가 활성 quest 에 자기 역할 이벤트를 기록하지 않고
# 종료하면 1회 차단하고 정확한 append 명령을 지시한다 (증거-영수증 게이트).
#
# 차단 알고리즘 (deterministic 만 block, 그 외 전부 allow — fail-open 유지):
#   활성 quest 없음 / 파싱 실패 / 미지의 agent_type → allow (DIRECT·비-Trinity 디스패치 존중)
#   thinker  종료: 마지막 verify 이후 plan 이벤트 없음   → block (재계획 포함)
#   worker   종료: 마지막 verify 이후 work 이벤트 없음   → block
#   verifier 종료: 마지막 work 이후 verify 이벤트 없음   → block
#   verifier PASS 인데 성공 명령 증거 없음               → block (조기 피드백 — Stop 게이트 전에)
#
# 왜 역할당 2회 상한인가: SubagentStop block 루프는 서브에이전트를 인질로 잡는다. 같은 세션에서
# 같은 역할을 2회 차단하면 3번째는 경고와 함께 통과 — 최종 담보는 어차피 Stop 의 verifier-gate
# (diff-hash 물리 대조)다. 이 훅은 조기 교정 장치지 최후 방벽이 아니다.
from __future__ import annotations

import json
import os
import re
import sys
import time

MAX_BLOCKS = 2  # 역할당 — 3번째는 통과 (최후 방벽은 verifier-gate)
ROLE_EVENT = {"asgard-thinker": "plan", "asgard-worker": "work", "asgard-verifier": "verify"}
# 역할 이벤트의 "신선도" 기준점 — 이 이벤트 뒤에 자기 이벤트가 있어야 이번 턴 기록으로 인정.
ANCHOR = {"plan": "verify", "work": "verify", "verify": "work"}


def trivial_evidence(cmd):
    """quest_log.py 의 trivial_evidence 와 동일 유지 (단일 출처 원칙)."""
    c = " ".join(str(cmd).split())
    return c in ("true", ":", "exit 0", "echo") or c.startswith("echo ")


def pass_evidence(rec):
    """verifier_gate.py 의 pass_evidence 와 동일 유지 (단일 출처 원칙)."""
    if (rec.get("baseline") or {}).get("state") == "green":
        return True
    return any(
        isinstance(c, dict) and c.get("exit_code") == 0 and not trivial_evidence(c.get("cmd", ""))
        for c in (rec.get("commands") or [])
    )


def block(root, sid, agent, reason):
    """차단 — 단 세션·역할당 MAX_BLOCKS 회. 초과 시 warn+allow (인질극 방지)."""
    path = os.path.join(root, ".asgard", "subgate-" + sid + ".json")
    counts = {}
    try:
        counts = json.load(open(path))
        counts = counts if isinstance(counts, dict) else {}
    except Exception:
        pass
    n = int(counts.get(agent, 0)) + 1
    counts[agent] = n
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())  # temp+rename — 크래시 절단이 카운터를 리셋하지 않게
        json.dump(counts, open(tmp, "w"))
        os.replace(tmp, path)
    except Exception:
        pass
    if n > MAX_BLOCKS:
        sys.stderr.write(
            "asgard subagent-gate: %s %d회 차단 초과 — 통과 (최종 담보는 verifier-gate)\n" % (agent, MAX_BLOCKS)
        )
        sys.exit(0)
    sys.stdout.write(json.dumps({"decision": "block", "reason": "Asgard subagent-gate: " + reason}, ensure_ascii=False))
    sys.exit(0)


def quest_pointer(root: str, sid: str) -> str | None:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(sid or "default"))[:64] or "default"
    sessions = os.path.join(root, ".asgard", "quest", "sessions")
    session_path = os.path.join(sessions, name + ".active")
    try:
        qid = open(session_path, encoding="utf-8").read().strip()
        if qid:
            return qid
    except Exception:
        pass
    if os.path.exists(os.path.join(sessions, name + ".known")):
        return None
    try:
        active = {
            open(os.path.join(sessions, entry), encoding="utf-8").read().strip()
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
            qid = open(path, encoding="utf-8").read().strip()
            if qid:
                return qid
        except Exception:
            continue
    return None


def receipt_path(root: str, qid: str, agent_id: str) -> str:
    safe_agent = re.sub(r"[^A-Za-z0-9_.-]", "_", agent_id)[:96]
    return os.path.join(root, ".asgard", "quest", "receipts", qid, "agent-" + safe_agent + ".json")


def record_agent_start(root: str, qid: str, sid: str, agent: str, agent_id: str) -> None:
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
        "started_at": time.time_ns(),
        "stopped_at": None,
    }
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def record_agent_stop(root: str, qid: str, agent_id: str) -> None:
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
    prompt = str(tool_input.get("prompt") or tool_input.get("description") or "")
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


def load_quest_events(root: str, qid: str) -> list[dict]:
    events = []
    try:
        for line in open(os.path.join(root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8"):
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        pass
    return events


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
        }
    return tickets


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
            record = json.load(open(os.path.join(directory, name), encoding="utf-8"))
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


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        agent = str(data.get("agent_type") or "")
        root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data.get("session_id") or "default"))[:64]
        qid = quest_pointer(root, sid)
        if not qid:
            sys.exit(0)  # 활성 quest 없음 → DIRECT·탐사 디스패치 존중 (fail-open)
        if data.get("hook_event_name") == "PreToolUse" and data.get("tool_name") == "Agent":
            tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
            target = str(tool_input.get("subagent_type") or tool_input.get("agent_type") or "")
            if target == "asgard-worker":
                if not record_worker_dispatch(root, qid, sid, str(data.get("tool_use_id") or ""), tool_input):
                    print("Asgard Mode B: Worker Agent prompt requires [ASGARD_UNIT:<id>] marker", file=sys.stderr)
                    sys.exit(2)
            elif target == "asgard-verifier":
                tickets = ticket_view(load_quest_events(root, qid))
                unfinished = sorted(str(ticket["unit"]) for ticket in tickets.values() if ticket["status"] != "done")
                if unfinished:
                    print("Asgard Mode B: unfinished ticket(s): " + ", ".join(unfinished), file=sys.stderr)
                    sys.exit(2)
                problem = physical_worker_problem(root, qid, sid, tickets)
                if problem:
                    print("Asgard Mode B: " + problem, file=sys.stderr)
                    sys.exit(2)
            sys.exit(0)
        want = ROLE_EVENT.get(agent)
        if not want:
            sys.exit(0)  # Trinity 역할 아님 (딜리버리 전문가 포함) → 대상 아님
        if data.get("hook_event_name") == "SubagentStart":
            record_agent_start(root, qid, sid, agent, str(data.get("agent_id") or ""))
            sys.exit(0)
        events = []
        try:
            for line in open(os.path.join(root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8"):
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            sys.exit(0)  # 로그 읽기 실패 → allow (fail-open)

        anchor = ANCHOR[want]
        last_anchor = max((i for i, e in enumerate(events) if e.get("event") == anchor), default=-1)
        fresh = [e for i, e in enumerate(events) if i > last_anchor and e.get("event") == want]
        hooks_dir = ".claude/hooks"  # SubagentStop 은 Claude Code 전용 이벤트
        if not fresh:
            block(
                root,
                sid,
                agent,
                "%s 가 활성 quest(%s)에 %s 이벤트를 기록하지 않고 종료하려 합니다. 역할 수행은 로그 기록으로만 "
                '성립합니다 — 기록 후 종료하세요: echo \'{"role":"%s","event":"%s",...}\' | '
                'python3 "$CLAUDE_PROJECT_DIR/%s/quest-log.py" append%s'
                % (
                    agent,
                    qid,
                    want,
                    want if want != "verify" else "verifier",
                    want,
                    hooks_dir,
                    " --verdict PASS|FAIL --level micro|full (검증 명령 직접 실행 + commands 기록 필수)"
                    if want == "verify"
                    else "",
                ),
            )
        if want == "verify":
            last = fresh[-1]
            if last.get("verdict") == "PASS" and not pass_evidence(last):
                block(
                    root,
                    sid,
                    agent,
                    "PASS 에 성공한 검증 명령 증거(commands[{cmd,exit_code==0}])가 없습니다. 검증 명령을 직접 "
                    "실행하고 결과를 append 로 재기록하세요 (true/echo 류 무조건-성공 명령은 증거가 아닙니다).",
                )
        record_agent_stop(root, qid, str(data.get("agent_id") or ""))
        # 통과 → 이 역할의 차단 카운터 리셋 (다음 위반은 새로 계수)
        try:
            path = os.path.join(root, ".asgard", "subgate-" + sid + ".json")
            counts = json.load(open(path))
            if isinstance(counts, dict) and agent in counts:
                counts.pop(agent)
                tmp = "%s.%d.tmp" % (path, os.getpid())
                json.dump(counts, open(tmp, "w"))
                os.replace(tmp, path)
        except Exception:
            pass
    except Exception:
        sys.exit(0)  # 훅 자체 오류 = allow — 게이트가 죽어도 서브에이전트를 인질로 잡지 않는다
    sys.exit(0)


if __name__ == "__main__":
    main()
