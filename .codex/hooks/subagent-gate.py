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

# 공용 라이브러리는 이 훅 옆에 깔린다 (setup 의 `library_files`). 이 훅이 여기서 집는 것은 증거
# 판정 술어다 — 26-08-06 까지 `trivial_evidence` 는 여기서 `true`·`echo` 만 아는 두 줄짜리
# 사본이었다. 같은 `ls` 한 줄이 Stop 게이트에서는 증거가 아니고 여기서는 증거였다는 뜻이다.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.append(_HOOK_DIR)

from asgard_hooklib.evidence import pass_evidence, trivial_evidence  # noqa: E402,F401
from asgard_hooklib.firing import run  # noqa: E402
from asgard_hooklib.ledger import fold_tickets, norm_path, verifiable_units  # noqa: E402
from asgard_hooklib.paths import read_text  # noqa: E402
from asgard_hooklib.policy import READ_ONLY_ROLES  # noqa: E402
from asgard_hooklib.siege import ledger_call  # noqa: E402

MAX_BLOCKS = 2  # 역할당 — 3번째는 통과 (최후 방벽은 verifier-gate)
ROLE_EVENT = {"asgard-thinker": "plan", "asgard-worker": "work", "asgard-verifier": "verify"}
# 누가 누구를 띄울 수 있는가 — AGENTS.md 트리니티 절의 위임 그래프가 정본이다.
#
# **표는 전수여야 한다.** 판정이 `agent in AGENT_TARGETS` 라, 표에 없는 역할은 검사 자체를
# 안 받고 무엇이든 띄운다. 종전에는 thinker·worker·eitri·planner·mimir·loki·ullr 이 전부
# 빠져 있어서, 읽기 전용인 Thinker 가 Worker 를 띄워 트리를 고칠 수 있었고 Worker 가 자기
# 판정자를 띄울 수 있었다 — 검증 독립성이 프런트매터 산문에만 얹혀 있었다 (26-08-05 감사).
#
# 표를 손으로 넓혀 온 이력이 있어(26-08-05 세 턴 연속 오탐↔구멍) 이제 표 자체는 판정 근거가
# 아니다. 근거는 아래 두 불변식이고, 표는 그것을 만족하는 하나의 해다 —
# `closure_violations()` 가 그 대조를 하고, 시험이 배포본 사본에서도 그것을 부른다.
#
#   층위 단조   rank[target] > rank[caller] 여야 한다. 이것 하나가 재귀와 순환을 동시에 막고
#               위임이 이어지는 횟수를 층위 수로 못박는다 — 깊이 카운터가 필요 없다.
#   읽기 봉인   부르는 쪽이 읽기 전용이면 불리는 쪽도 읽기 전용이어야 한다. 판정자·계획자가
#               쓰기 가능한 손을 부르면 자기가 고친 diff 를 자기가 심판하게 된다.
#
# 층위. 같은 층끼리는 서로 못 부른다 (thor → thor 가 여기서 끊긴다).
AGENT_RANK = {
    "asgard-thinker": 1,  # Trinity — 전이 함수가 배정하는 자리
    "asgard-worker": 1,
    "asgard-verifier": 1,
    "asgard-thor-lead": 2,  # 편대장
    "asgard-thor": 3,  # 쓰기 가능한 딜리버리
    "asgard-freyja": 3,
    "asgard-eitri": 3,
    "asgard-planner": 3,
    "asgard-mimir": 4,  # 읽기 전용 분석
    "asgard-loki": 4,
    "asgard-ullr": 5,  # 정찰 — 종점
}
# 트리를 만지지 않는 역할 — 정본은 공용 라이브러리 하나다 (`policy.READ_ONLY_ROLES`).
# 훅마다 사본을 들면 한 자리만 낡아도 같은 역할이 게이트마다 다르게 판정된다.
READ_ONLY_AGENTS = READ_ONLY_ROLES
# 전이 함수가 배정하는 자리 — 아무도 손으로 못 부른다. 자기 일을 심판·계획할 손을 자기가
# 고르는 순간 판정도 계획도 자기 확인이 된다.
UNDISPATCHABLE = frozenset({"asgard-thinker", "asgard-verifier"})

AGENT_TARGETS = {
    # Verifier 는 읽기 전용·판정 없는 손만. loki 는 반례 사냥, ullr 은 사실 확인용 정찰이다.
    "asgard-verifier": frozenset({"asgard-loki", "asgard-ullr"}),
    # Thinker 는 계획에 필요한 읽기 전용 셋. 계획하는 손은 트리를 만지지 않는다.
    "asgard-thinker": frozenset({"asgard-ullr", "asgard-mimir", "asgard-loki"}),
    # Worker 는 변경 표면별 딜리버리와 코드 안내자, 정찰, 그리고 반례 사냥까지.
    # loki·ullr·mimir 는 읽기 전용이고 판정을 내지 않아, 쓰기 가능한 역할이 자기 작업의
    # 반례를 찾는 데 써도 독립성이 상하지 않는다.
    "asgard-worker": frozenset(
        {
            "asgard-freyja",
            "asgard-thor",
            "asgard-thor-lead",
            "asgard-eitri",
            "asgard-mimir",
            "asgard-loki",
            "asgard-ullr",
        }
    ),
    # thor-lead 의 임무는 sub-Thor 편성이다. 층위가 갈라 놓아 sub-Thor 는 다시 편성하지 못한다.
    "asgard-thor-lead": frozenset({"asgard-thor", "asgard-mimir", "asgard-loki", "asgard-ullr"}),
    # 딜리버리 전문가도 자기 배차를 연다 — 읽기 전용 아래층만. 자기가 고친 표면의 반례를
    # 스스로 찾고(loki), 남의 코드를 읽어야 할 때 정찰을 보낸다(ullr·mimir).
    "asgard-freyja": frozenset({"asgard-mimir", "asgard-loki", "asgard-ullr"}),
    "asgard-thor": frozenset({"asgard-mimir", "asgard-loki", "asgard-ullr"}),
    "asgard-eitri": frozenset({"asgard-mimir", "asgard-loki", "asgard-ullr"}),
    # 기획자는 근거를 모으는 손만 — 반례 사냥은 구현이 있어야 뜻이 있다.
    "asgard-planner": frozenset({"asgard-mimir", "asgard-ullr"}),
    # 읽기 전용 분석층은 정찰만 더 보낸다.
    "asgard-mimir": frozenset({"asgard-ullr"}),
    "asgard-loki": frozenset({"asgard-ullr"}),
    # 종점. 빈 frozenset 은 "재위임 없음"이라는 **선언**이고, 항목이 없는 것과 뜻이 다르다.
    "asgard-ullr": frozenset(),
}


# 배정 단위 하나를 끝까지 수행할 수 있는 에이전트 — 모드 B 영수증이 "이 단위를 누가 실제로
# 돌렸는가"를 셀 때 보는 집합이다. 손으로 든 목록이 아니라 위임 표에서 뽑는다: 워커 자신과,
# 워커가 변경 표면에 따라 내려보내는 쓰기 가능한 딜리버리(freyja=화면, thor·thor-lead=백엔드,
# eitri=빌드·CI). 읽기 전용은 트리를 안 고치니 단위를 끝낼 수 없고, 판정자·사고자는 전이 함수가
# 배정하는 자리라 배차 대상 자체가 아니다 (UNDISPATCHABLE).
#
# 26-08-12 까지 이 집합이 `asgard-worker` 하나였다. 그런데 `[ASGARD_UNIT:<id>]` 를 달고
# asgard-thor 에게 보낸 단위는 영수증이 안 잡혀, 전 단위가 done 인데도 판정자 배차가
# "physical worker dispatch receipts missing" 으로 막혔다.
UNIT_EXECUTORS = frozenset({"asgard-worker"}) | (AGENT_TARGETS["asgard-worker"] - READ_ONLY_AGENTS)


def closure_violations() -> list[str]:
    """표가 두 불변식을 어긴 자리 — 없으면 빈 목록. 시험이 부르는 자리다.

    **임포트 시점에 raise 하지 않는다.** 이 훅은 fail-open 이 계약이고, PreToolUse 가 예외로
    죽으면 호스트는 그것을 거절로 읽어 모든 디스패치가 막힌다 — 표의 오타 하나가 세션을
    통째로 세우는 교환은 성립하지 않는다. 대신 시험이 **배포본까지** 이 함수를 돌린다:
    이 파일은 `.claude/hooks/` 로 복사돼 사는 사본이라 패키지만 태우면 사본의 표는 안 본다.
    """
    problems: list[str] = []
    if set(AGENT_TARGETS) != set(AGENT_RANK):
        problems.append("every agent needs both a rank and a target set")
    for caller, targets in AGENT_TARGETS.items():
        rank = AGENT_RANK.get(caller)
        for target in sorted(targets):
            if rank is None or AGENT_RANK.get(target, rank) <= rank:
                problems.append(f"delegation rank must strictly increase: {caller} -> {target}")
            if target in UNDISPATCHABLE:
                problems.append(f"{target} is assigned by the transition function, not dispatched: {caller}")
            if caller in READ_ONLY_AGENTS and target not in READ_ONLY_AGENTS:
                problems.append(f"read-only {caller} cannot dispatch write-capable {target}")
    return problems


# 역할 이벤트의 "신선도" 기준점 — 이 이벤트 뒤에 자기 이벤트가 있어야 이번 턴 기록으로 인정.
ANCHOR = {"plan": "verify", "work": "verify", "verify": "work"}
# 이벤트 이름은 역할 이름이 아니다 — 기장 명령이 시키는 `role` 값은 여기서 온다.
EVENT_ROLE = {"plan": "thinker", "work": "worker", "verify": "verifier"}


def _load_json(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


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
        qid = read_text(session_path).strip()
        if qid:
            return qid
    except Exception:
        pass
    if os.path.exists(os.path.join(sessions, name + ".known")):
        return None
    try:
        active = {
            read_text(os.path.join(sessions, entry)).strip()
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
            qid = read_text(path).strip()
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


def record_executor_lifecycle(root: str, qid: str, sid: str, agent: str, agent_id: str, task: str, *, starting: bool):
    """딜리버리 전문가의 시작·종료도 물리 영수증으로 남긴다.

    단위를 받아 실제로 도는 손인데 시작·종료가 안 적히면, 그 단위는 아무도 안 돈 것으로 읽혀
    판정자 배차가 막힌다. 역할 로그 규율(work·verify 이벤트)은 여전히 트리니티 역할만 진다 —
    이 함수는 영수증만 남기고 아무것도 거절하지 않는다."""
    if starting:
        record_agent_start(root, qid, sid, agent, agent_id, task)
    else:
        record_agent_stop(root, qid, agent_id, agent, task)


def record_worker_dispatch(
    root: str, qid: str, sid: str, tool_use_id: str, tool_input: dict, agent: str = "asgard-worker"
) -> bool:
    """`[ASGARD_UNIT:<id>]` 가 붙은 배차를 영수증으로 남긴다 — 수행자 종류를 받은 그대로 적는다.

    종전에는 종류를 `asgard-worker` 로 못박아, 같은 단위를 딜리버리 전문가가 받아도 영수증은
    워커가 받은 것처럼 적혔다. 마커가 없으면 아무것도 안 쓰고 False 를 돌려준다."""
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
        "agent_type": agent,
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


def quest_request(root: str, qid: str) -> str:
    """이 퀘스트를 연 요청 한 줄 — Run 의 목표가 된다. 못 읽으면 퀘스트 id.

    로그를 통째로 읽지 않고 `request` 를 든 첫 줄에서 멈춘다. 이 훅은 서브에이전트를 띄우는
    길목이라 매 호출의 지연이 그대로 얹히고, 그 값은 언제나 `open` 이벤트에 있다.
    """
    try:
        with open(os.path.join(root, ".asgard", "quest", qid + ".jsonl"), encoding="utf-8") as handle:
            for line in handle:
                try:
                    request = json.loads(line).get("request")
                except Exception:
                    continue
                if request:
                    return str(request)[:500]
    except Exception:
        pass
    return qid


def siege_open(root: str, qid: str, caller: str, target: str, tool_input: dict) -> None:
    """호출된 에이전트를 배차 장부에 세운다 — 호스트 모드에서 이것이 적히는 유일한 자리.

    네이티브 루프는 `agent/heimdall/bifrost.py` 가 같은 것을 프로세스 안에서 적는다. 세 호스트
    모드에는 그 루프가 없고 디스패치를 아는 자리가 이 훅뿐이라, 여기가 없으면 `asgard siege` 는
    어떤 에이전트가 불렸는지 영영 말하지 못한다 — 오늘 잡히는 것은 배정 단위 티켓뿐이다.

    실패는 삼킨다. 장부는 퀘스트 로그에서 파생된 기록이고, 파생을 얻으려다 디스패치를 막는
    교환은 성립하지 않는다.
    """
    ledger_call(
        root,
        ["note", target, "--quest", qid, "--spec", call_spec(tool_input), "--objective", quest_request(root, qid)]
        + (["--caller", caller] if caller else []),
    )


def heal_ledger(root: str, qid: str, agent: str) -> bool:
    """종료에서 여는 기록을 메워도 되는가 — 단위 티켓이 그 수명을 쥐고 있으면 안 된다.

    티켓이 쥐는 것은 워커의 수명뿐이다 (`quest_log._siege_mirror` 가 claim/finish 로 연다).
    같은 퀘스트에서 도는 thinker·verifier·딜리버리 전문가는 여전히 `siege_open` 이 여는
    자리라, 그쪽 유실은 티켓이 있든 없든 메워야 한다.
    """
    if agent != "asgard-worker":
        return True
    return not fold_tickets(load_quest_events(root, qid))


def siege_close(
    root: str, qid: str, agent: str, summary: str = "", *, heal: bool = False, outcome: str = "succeeded"
) -> None:
    """그 에이전트의 살아 있는 시도를 접는다. `siege_open` 이 연 것만 — 배정 단위 티켓의
    수명은 ticket-finish 가 쥔다.

    기본 결과는 `succeeded` 다. 이 자리가 스스로 아는 것은 호출이 답을 들고 돌아왔다는 사실뿐이고,
    판정의 옳고 그름은 다른 축이다 — 네이티브의 `bifrost.settle_turn` 도 턴이 예외로 죽었을
    때만 failed 를 적는다. Verifier 의 FAIL 은 `summary` 로 간다. `failed` 로 접는 경우는 하나뿐:
    돌아온 역할이 자기 이벤트에 그렇게 적었을 때다 (`_role_outcome`).

    `heal` 은 여는 기록이 유실된 자리를 여기서 메운다 (`siege_act.run_unnote`). 여는 쪽은 답을
    안 기다리는 자식 프로세스라 실패가 조용하고, 그러면 실제로 돈 역할이 장부에서 통째로
    사라진다 — 26-08-12 에 Thinker 가 그렇게 빠졌다. 단위 티켓이 있는 퀘스트에서는 끄는데,
    그쪽 수명은 ticket-claim/finish 가 쥐고 있어 여기서 세우면 한 Task 를 둘이 연다.
    """
    argv = ["unnote", agent, "--quest", qid]
    if summary:
        argv += ["--summary", summary[:500]]
    if heal:
        argv.append("--heal")
    if outcome != "succeeded":
        argv += ["--outcome", outcome]
    ledger_call(root, argv)


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


def _role_outcome(event: dict) -> str:
    """돌아온 역할이 이 시도를 실패로 적었는가 — 장부에 넣을 결과 한 낱말.

    배차가 답을 들고 돌아왔다는 것과 그 답이 목표에 닿았다는 것은 서로 다른 사실인데, 종료 훅이
    보는 것은 앞의 하나뿐이다. 그래서 뒤의 하나는 역할이 자기 이벤트에 적어야 한다 —
    `dispatch-context` 가 배차받은 쪽에 그 자리를 알려 준다.

    `failed` 라고 정확히 적힌 것만 실패로 읽는다. 모르는 값을 실패로 접으면 성공한 배차가 회로
    차단 횟수를 먹는다. 판정자의 FAIL 은 여기 오지 않는다 — 그것은 워커 일에 대한 결론이지
    판정 배차 자체의 실패가 아니고, `verdict` 는 이 칸이 아니다.
    """
    return "failed" if str(event.get("outcome") or "").strip().lower() == "failed" else "succeeded"


def pipeline_denial_reason(tickets: dict[str, dict], unit: str) -> str:
    """왜 이 유닛이 아직 조기 검증 대상이 아닌지 — done 아님 / 파일 미선언 / 파일 충돌 순으로 구체화."""
    ticket = tickets.get(unit)
    if not ticket:
        return "unknown unit %s" % unit
    if ticket["status"] != "done":
        return "unit %s is not done yet (status: %s)" % (unit, ticket["status"])
    open_tickets = [t for t in tickets.values() if t["status"] in ("todo", "in_progress")]
    undeclared = sorted(str(t["id"]) for t in open_tickets if not t.get("files"))
    if undeclared:
        return "open unit(s) declared no files (disjointness unprovable): " + ", ".join(undeclared)
    mine = {norm_path(f) for f in ticket.get("files") or []}
    overlapping = sorted(str(t["id"]) for t in open_tickets if mine & {norm_path(f) for f in t.get("files") or []})
    if overlapping:
        return "unit %s files overlap with still-open unit(s): %s" % (unit, ", ".join(overlapping))
    return "unit %s is not yet early-verifiable" % unit


def _sanitize_sid(raw: object) -> str:
    """영수증에 적히는 철자로 세션 id 를 맞춘다 — main() 이 라이브 세션에 거는 것과 같은 규칙."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw))[:64]


def quest_sessions(root: str, qid: str, sid: str) -> set[str]:
    """이 퀘스트를 쥐었던 세션 전부 — 지금 세션과 로그가 이름을 적은 세션들.

    영수증은 세션에 묶인다(424b5619: agent_id 를 세션에 결속해 동시 세션 경합을 막는다). 그런데
    `quest-log attach` 는 퀘스트를 다른 세션이 이어받게 하므로, 지금 세션 하나로만 거르면
    인수인계된 퀘스트는 앞 세션이 남긴 영수증을 영영 못 읽는다 — 워커가 물리적으로 다 돌았는데도
    판정자 배차가 막히고, 그 퀘스트는 어느 세션에서도 판정을 못 받는다 (실측
    se-baseline-research-260819: 완료 영수증 4건·단위 배차 3건이 디스크에 있는데 got 0).

    로그에 이벤트를 적으려면 그 퀘스트에 attach 되어 있어야 하므로, 로그가 이름을 적은 세션은
    이 퀘스트를 실제로 쥐었던 세션이다. 결속을 푸는 것이 아니라 결속의 열쇠를 터미널 세션에서
    퀘스트 계보로 옮기는 것이라, 이 퀘스트를 한 번도 안 쥔 세션의 영수증은 그대로 걸린다.
    """
    owners = {sid}
    for event in load_quest_events(root, qid):
        owner = event.get("session_id")
        if owner:
            owners.add(_sanitize_sid(owner))
    return owners


def mode_b_receipts(root: str, qid: str, sid: str) -> tuple[list[dict], list[dict]]:
    directory = os.path.join(root, ".asgard", "quest", "receipts", qid)
    agents, dispatches = [], []
    try:
        names = os.listdir(directory)
    except Exception:
        return agents, dispatches
    owners = quest_sessions(root, qid, sid)
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            record = _load_json(os.path.join(directory, name))
        except Exception:
            continue
        if record.get("quest_id") != qid or str(record.get("session_id") or "") not in owners:
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
    # 이 수가 말하는 것은 "물리적으로 끝까지 돈 수행자가 몇인가"이지 단위와의 결속이 아니다
    # (워커가 자기 단위 안에서 부른 thor 도 같은 종류라 여기서는 섞인다). 단위 결속은 아래
    # 배차 영수증의 `unit` 이 진다.
    workers = [
        record
        for record in agents
        if record.get("agent_type") in UNIT_EXECUTORS and record.get("started_at") and record.get("stopped_at")
    ]
    distinct = {str(record.get("agent_id")) for record in workers if record.get("agent_id")}
    if len(distinct) < len(tickets):
        return "physical worker receipts missing: expected %d distinct completed agents, got %d" % (
            len(tickets),
            len(distinct),
        )
    dispatched = {str(record.get("unit")) for record in dispatches if record.get("agent_type") in UNIT_EXECUTORS}
    missing = sorted(set(tickets) - dispatched)
    if missing:
        return "physical worker dispatch receipts missing for unit(s): " + ", ".join(missing)
    # **첫** 배차 턴이다. 이 검사가 묻는 것은 "후행 단위가 선행 완료 전에 시작됐는가"라 재는 것은
    # 시작 시점이고, 최대를 쓰면 나중 재배차 한 번이 이른 첫 배차를 덮어 위반을 가린다.
    dispatch_turn = {}
    for record in dispatches:
        key = str(record.get("unit"))
        turn = int(record.get("quest_turn") or 0)
        dispatch_turn[key] = min(dispatch_turn[key], turn) if key in dispatch_turn else turn
    done_turn = {}
    for event in load_quest_events(root, qid):
        if event.get("event") == "ticket" and event.get("ticket_status") == "done" and event.get("unit") is not None:
            key = str(event["unit"])
            done_turn[key] = max(done_turn.get(key, 0), int(event.get("turn") or 0))
    for key, ticket in tickets.items():
        for dependency in ticket["access"]:
            dep = str(dependency)
            # 경계는 `<` 다. 영수증의 `quest_turn` 은 배차 시점에 **이미 적혀 있던** 마지막 턴이라,
            # 선행의 done 이벤트 직후에 배차하면 두 값이 같아진다 — 정상 순서인데 `<=` 는 그것을
            # 위반으로 읽었다 (실측 asgard-coherence-refactor-260812: tier-table 배차 21 ·
            # recall-split done 21 로 판정자 배차가 막혔다). 선행 완료 전 배차는 최소한 한 턴
            # 작으므로 `<` 로도 그대로 잡힌다.
            if dispatch_turn.get(key, 0) < done_turn.get(dep, 0):
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


def worker_dispatch_barrier(protocol: str, root: str, qid: str, sid: str, tool_use_id: str, tool_input: dict) -> None:
    """모드 B 워커 디스패치 배리어 — 단위 티켓이 선언된 퀘스트에서만 `[ASGARD_UNIT:<id>]` 마커를 요구한다.

    마커는 **배정 단위가 있을 때만** 요구한다. 단위 티켓이 하나도 없는 퀘스트는 병렬 모드 B 가
    아니라 단일 위임이고, 거기서 마커를 요구하면 조율자가 워커 서브에이전트를 아예 못 띄운다 —
    26-08-12 까지 그랬다: 퀘스트를 연 세션에서 `asgard-worker` 호출이 전부 exit 2 로 끊겼고,
    남은 길은 조율자가 직접 편집하는 MAIN_WORKER 뿐이라 워커 역할이 화면에 한 번도 안 떴다.
    티켓이 선언된 순간부터는 종전대로 마커가 있어야 한다 (영수증↔티켓 결속).

    면제는 **단일** 위임에만 준다. 마커 강제가 종전에 병렬 팬아웃까지 통째로 막고 있었으므로,
    그것을 열면서 겹침 검사를 안 붙이면 티켓 없이 워커 여럿이 같은 파일을 동시에 고칠 수 있다 —
    단위를 안 적었으니 파일 분리를 증명할 방법도, `physical_worker_problem` 이 볼 것도 없다.
    그래서 앞선 마커 없는 워커가 아직 안 끝났으면 두 번째 호출을 거절하고 단위 선언을 요구한다."""
    if record_worker_dispatch(root, qid, sid, tool_use_id, tool_input):
        return
    if fold_tickets(load_quest_events(root, qid)):
        deny_pretool(protocol, "Asgard Mode B: Worker Agent prompt requires [ASGARD_UNIT:<id>] marker")
    if live_unmarked_workers(root, qid, sid):
        deny_pretool(
            protocol,
            "Asgard Mode B: another Worker without a unit marker is still running. Fanning out needs "
            "declared units — record a ticket event per unit with non-overlapping `files`, then dispatch "
            "each with [ASGARD_UNIT:<id>] as the prompt's first line. One Worker at a time needs no marker.",
        )


def live_unmarked_workers(root: str, qid: str, sid: str) -> int:
    """이 세션에서 아직 안 끝난 asgard-worker 서브에이전트 수 — 티켓 없는 팬아웃을 가르는 축.

    영수증은 SubagentStart 가 쓰고 SubagentStop 이 닫는다 (`record_agent_start`/`_stop`). 그래서
    `stopped_at` 이 빈 것은 지금 도는 워커다. 티켓이 있는 퀘스트는 이 함수에 오지 않는다 —
    거기서는 마커가 이미 강제되고 겹침은 티켓의 `files` 가 판정한다.
    """
    agents, _ = mode_b_receipts(root, qid, sid)
    return sum(
        1
        for record in agents
        if record.get("agent_type") == "asgard-worker" and record.get("started_at") and not record.get("stopped_at")
    )


def verifier_dispatch_barrier(protocol: str, root: str, qid: str, sid: str, tool_input: dict) -> None:
    """모드 B 판정자 디스패치 배리어 — 유닛 조기 검증이면 그 티켓만, 웨이브 전체면 전 티켓 done 을 요구한다."""
    tickets = fold_tickets(load_quest_events(root, qid))
    unit = unit_marker(tool_input)
    if unit is not None:
        # 유닛 단위 조기(파이프라인) 검증 — 전 티켓 done 배리어와 동시성 감사
        # (physical_worker_problem)는 웨이브 전체용이라 여기선 전제가 아니다.
        if unit not in verifiable_units(list(tickets.values())):
            deny_pretool(protocol, "Asgard Mode B: " + pipeline_denial_reason(tickets, unit))
        return
    unfinished = sorted(str(ticket["id"]) for ticket in tickets.values() if ticket["status"] != "done")
    if unfinished:
        deny_pretool(protocol, "Asgard Mode B: unfinished ticket(s): " + ", ".join(unfinished))
    problem = physical_worker_problem(root, qid, sid, tickets)
    if problem:
        deny_pretool(protocol, "Asgard Mode B: " + problem)


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
        sid = _sanitize_sid(raw_sid)
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
                worker_dispatch_barrier(protocol, root, qid, sid, str(data.get("tool_use_id") or ""), tool_input)
            elif target == "asgard-verifier":
                verifier_dispatch_barrier(protocol, root, qid, sid, tool_input)
            elif target in UNIT_EXECUTORS:
                # 단위를 딜리버리 전문가가 받는 길 — 마커가 있을 때만 영수증을 남기고 거절은 없다.
                # 마커 없는 호출은 워커가 자기 단위 안에서 여는 하위 배차라, 여기서 막으면 표면별 위임이 끊긴다.
                record_worker_dispatch(root, qid, sid, str(data.get("tool_use_id") or ""), tool_input, target)
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
        starting = event in {"SubagentStart", "subagentStart", "start"}
        want = ROLE_EVENT.get(agent)
        task = str(data.get("task") or data.get("description") or "")
        agent_id = str(data.get("agent_id") or data.get("subagent_id") or "")
        if not want:
            # Trinity 역할 아님 → 로그 규율의 대상은 아니다. 단위를 수행할 수 있는 손이면 영수증만 남긴다.
            if agent in UNIT_EXECUTORS and (starting or stopping):
                record_executor_lifecycle(root, qid, sid, agent, agent_id, task, starting=starting)
            # 장부도 접는다: 안 접으면 `siege show` 가 이미 끝난 에이전트를 영영 "도는 중" 으로 보인다.
            if stopping:
                siege_close(root, qid, agent, heal=heal_ledger(root, qid, agent))
            sys.exit(0)
        if starting:
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
        last = fresh[-1]
        if want == "verify":
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
        heal = heal_ledger(root, qid, agent)
        siege_close(root, qid, agent, summary=_role_summary(last, want), heal=heal, outcome=_role_outcome(last))
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
    run("subagent-gate", main)
