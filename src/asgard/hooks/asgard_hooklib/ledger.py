"""퀘스트 로그 자체 — 스키마, 정규화, 한 줄 원자 append, 재생.

파일은 JSONL 이고 각 줄이 이전 줄 해시에 묶인다(integrity). 쓰기는 잠금 + `O_APPEND` 로
직렬화하고, 읽기는 깨진 줄을 버리지 않고 `_corrupt` 로 표시해 넘긴다 — 조용히 건너뛰면
무결성 검사가 볼 것이 사라진다.
"""

from __future__ import annotations

import contextlib
import json
import os
import time

from .integrity import EMPTY, canonical_hash, event_identity, ledger_integrity
from .paths import BAD_NUMBER, quest_dir

SCHEMA = 2


EVENTS = {
    "plan",
    "work",
    "verify",
    "fail",
    "escalate",
    "delegate",
    "amend",
    "ticket",
    "ticket_lease",
    "quest_closed",
}  # delegate: 중첩 디스패치 배정 기록 — Phase 2 통계가 배정 정책 학습


# ticket_lease: lease 갱신 전용 — 상태 전이가 아니다. 갱신이 `ticket`으로 적히면 티켓 이벤트
# 열이 "todo→in_progress→done"이 아니라 "얼마나 오래 돌았는가"를 적게 되고(lease의 1/3마다
# 한 줄), 그 열을 읽는 쪽은 벽시계에 따라 다른 역사를 본다. finish가 실패한 뒤의 lease 단축도
# 같은 이유로 티켓을 in_progress로 되돌려 놓았다.
# 갱신은 claim token을 검증하는 ticket-heartbeat만 적을 수 있다 — raw append로 열어 두면
# 토큰 없이 남의 lease를 미는 문이 된다.
# amend: 기준 수정 전용 — 상태 전이가 아니라 **채점 기준**을 옮기는 이벤트다. raw append 로
# 열어 두면 수정 동사가 지키는 것 둘이 그대로 우회된다: 서 있는 PASS 아래에서의 거부와, 사유를
# 반드시 남기게 하는 요건. 그러면 워커가 채점 기준을 이벤트 한 줄로 조용히 갈아 끼울 수 있다.
# 수정은 `quest-log.py amend-criteria` 만 적는다.
APPEND_EVENTS = EVENTS - {"ticket_lease", "amend"}


VERDICTS = {"PASS", "FAIL", "ESCALATE", "NA"}


TICKET_STATUSES = {"todo", "in_progress", "done", "failed", "blocked"}


# v1의 16필드 + v2 실행/승인/체인 identity. tier/effort/model 등은 부가 관측 필드.
FIELDS = [
    "schema",
    "quest_id",
    "execution_id",
    "acceptance_hash",
    "session_id",
    "turn",
    "ts",
    "role",
    "event",
    "base_ref",
    "risk",
    "criteria",
    "changed_files",
    "diff_hash",
    "commands",
    "verdict",
    "failure_sig",
    "failure_count",
    "prev_event_hash",
    "event_hash",
]


def load_events(root: str, qid: str) -> list[dict]:
    path = os.path.join(root, ".asgard", "quest", qid + ".jsonl")
    events = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    # Do not silently replay around a torn/corrupt event. The caller can report the
                    # exact line, while older valid unhashed logs remain readable.
                    events.append({"_corrupt": True, "_line": line_number})
    except Exception:
        pass
    return events


@contextlib.contextmanager
def quest_lock(root: str, qid: str):
    """Quest별 프로세스 lock — 상태 검사→turn 할당→append를 한 임계구역으로 묶는 기반."""
    path = os.path.join(quest_dir(root), qid + ".lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if os.name == "nt":  # pragma: no cover - Windows 전용
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":  # pragma: no cover - Windows 전용
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def write_event_unlocked(root: str, qid: str, ev: dict, events: list[dict]) -> None:
    """quest_lock 보유 호출자 전용 append primitive."""
    path = os.path.join(quest_dir(root), qid + ".jsonl")
    valid, detail = ledger_integrity(events)
    if not valid:
        raise ValueError(f"quest ledger integrity failure: {detail}")
    ev["turn"] = max((int(event.get("turn") or 0) for event in events), default=0) + 1
    ev["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ev["prev_event_hash"] = str(events[-1].get("event_hash") or event_identity(events[-1])) if events else EMPTY
    ev["event_hash"] = event_identity(ev)
    line = (json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(path, os.O_APPEND | os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        written = os.write(fd, line)
        if written != len(line):
            raise OSError("short quest-log write")
        os.fsync(fd)
    finally:
        os.close(fd)


def write_event(root: str, qid: str, ev: dict) -> None:
    """Quest lock 안에서 단조 turn을 할당하고 O_APPEND+fsync로 한 JSONL 레코드를 내구 기록."""
    with quest_lock(root, qid):
        write_event_unlocked(root, qid, ev, load_events(root, qid))


# `normalize` 가 읽는 이벤트 키 전부다. 여기 없는 키는 기록에 남지 않으므로, CLI 의 `append` 는
# 그런 키를 받으면 거절한다 (`quest_log._append_rejection`). 판정은 이 기록만 읽으므로, 조용히
# 버리면 워커는 근거를 적었다고 보고 판정자는 빈 칸을 읽는다. 자유 서술 칸은 `subtask` 하나다.
# `normalize` 에 키를 더할 때 여기도 함께 더한다 — 어긋나면
# `tests/test_quest_log_standalone.py` 의 소스 스캔이 실패한다.
# 하네스가 PASS 판정 시점에 직접 붙이는 칸 (`quest_log._verify_evidence`). `normalize` 는 이 셋을
# 안 읽으므로 stdin 이 값을 넣어도 기록에 안 남지만, 그 침묵은 위조 시도를 성공처럼 보이게 한다.
# `append` 는 이 이름들을 따로 거절해 호출자가 쓰는 칸이 아님을 알린다.
HARNESS_FIELDS = frozenset({"baseline", "criteria_checks", "peer_tree"})

EVENT_FIELDS = frozenset(
    {
        "acceptance_hash", "access", "attempt", "base_ref", "changed_files", "claim_token_hash",
        "commands", "criteria", "diff_hash", "event", "execution_id", "failure_count", "failure_sig",
        "findings", "heartbeat_at", "ignored_snapshot", "lease_expires_at", "level", "max_attempts",
        "model", "outcome", "peer_snapshot", "request", "research_findings", "research_only", "risk",
        "role", "subtask", "ticket_error", "ticket_status", "tree_ref", "unit", "verdict",
        "verification_id", "worker_id",
    }
)  # fmt: skip


# 자유 서술 칸의 상한. 1000자이던 판은 여러 단위를 합친 워커 보고를 문장 중간에서 잘랐고,
# 잘랐다는 표시가 없어 판정자가 "워커가 거기까지만 적었다"로 읽었다 (26-08-21 실측 — 수정본
# 다섯이 통째로 사라졌다). 상한 자체는 남긴다: 이 칸은 매 턴 로그 파일에 쌓인다.
SUBTASK_LIMIT = 8000
_CLIPPED = "…[잘림]"


def _clip(text: str, limit: int) -> str:
    """상한을 넘으면 자르되, 잘랐다는 사실을 글 안에 남긴다 — 조용한 절단은 거짓 완결이다."""
    if len(text) <= limit:
        return text
    return text[: limit - len(_CLIPPED)] + _CLIPPED


def normalize(ev: dict, events: list[dict], qid: str, session: str) -> dict:
    """고정 코어 스키마로 정규화 — 빠진 필드는 중립값, 모르는 stdin 필드는 버린다."""
    base_ref = next((e.get("base_ref") for e in events if e.get("base_ref")), None)
    execution_id = next((e.get("execution_id") for e in events if e.get("execution_id")), None)
    acceptance_hash = next((e.get("acceptance_hash") for e in events if e.get("acceptance_hash")), None)
    if events and (not execution_id or not acceptance_hash):
        # First v2 append upgrades a legacy quest without rewriting its historical prefix.
        execution_id = "legacy-" + canonical_hash({"quest_id": qid, "first": event_identity(events[0])})[:24]
        acceptance_hash = canonical_hash(
            {
                "execution_id": execution_id,
                "base_ref": base_ref,
                "request": next((e.get("request") for e in events if e.get("request")), ""),
                "criteria": next((e.get("criteria") for e in events if e.get("criteria")), []),
            }
        )
    full = {
        "schema": SCHEMA,
        "quest_id": qid,
        # Only `open` may seed these values. Subsequent stdin cannot replace the first event's identity.
        "execution_id": execution_id or ev.get("execution_id"),
        "acceptance_hash": acceptance_hash or ev.get("acceptance_hash"),
        "session_id": session,
        "turn": len(events) + 1,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "role": ev.get("role") or "worker",
        "event": ev.get("event") or "work",
        "base_ref": ev.get("base_ref") or base_ref,
        "risk": ev.get("risk") or {},
        "criteria": ev.get("criteria") or [],
        "changed_files": ev.get("changed_files") or [],
        "diff_hash": ev.get("diff_hash"),
        "commands": ev.get("commands") or [],
        "verdict": ev.get("verdict") or "NA",
        "failure_sig": ev.get("failure_sig"),
        "failure_count": int(ev.get("failure_count") or 0),
    }
    if isinstance(ev.get("ignored_snapshot"), dict):
        full["ignored_snapshot"] = ev["ignored_snapshot"]
    # 짝 저장소의 시작 트리 — `base_ref` 가 세션 뿌리 하나만 담아서, 이것이 없으면 선언된 추가
    # 뿌리의 작업이 판정 내내 무변경으로 읽힌다. 소비자(`peer_base_of`)는 **첫** 이벤트의 값만
    # 보므로 뒤따르는 stdin 이 기준선을 갈아치울 수 없다 (`ignored_snapshot` 과 같은 규약).
    if isinstance(ev.get("peer_snapshot"), dict):
        full["peer_snapshot"] = ev["peer_snapshot"]
    if ev.get("level"):  # verify 전용 부가 필드 — gate의 full-verify 판정 근거
        full["level"] = ev["level"]
    if ev.get("unit") is not None:  # work 전용 부가 필드 — wave 병렬 배정 단위 id
        full["unit"] = ev["unit"]
    if ev.get("ticket_status"):
        full["ticket_status"] = ev["ticket_status"]
    if ev.get("subtask"):
        full["subtask"] = _clip(str(ev["subtask"]), SUBTASK_LIMIT)
    # 돌아온 역할이 목표에 닿았는가 — `failed` 하나만 통과한다. 종료 훅이 이 칸을 읽어 배차를
    # 실패로 접고(`subagent_gate._role_outcome`), 이 칸이 없는 배차는 succeeded 로 접힌다. 모르는
    # 값을 그대로 넣으면 그 오타가 조용히 성공으로 읽히므로, 오타는 쓰는 쪽에 남긴다.
    if str(ev.get("outcome") or "").strip().lower() == "failed":
        full["outcome"] = "failed"
    if isinstance(ev.get("access"), list):
        full["access"] = ev["access"][:20]
    if ev.get("ticket_error"):
        full["ticket_error"] = str(ev["ticket_error"])[:500]
    if ev.get("claim_token_hash"):
        full["claim_token_hash"] = str(ev["claim_token_hash"])[:128]
    if ev.get("worker_id"):
        full["worker_id"] = str(ev["worker_id"])[:128]
    for key in ("lease_expires_at", "heartbeat_at"):
        if ev.get(key) is not None:
            full[key] = float(ev[key])
    for key in ("attempt", "max_attempts"):
        if ev.get(key) is not None:
            full[key] = int(ev[key])
    if ev.get("model"):
        full["model"] = str(ev["model"])[:80]
    if ev.get("request"):
        full["request"] = str(ev["request"])
    if ev.get("research_only") is True:
        full["research_only"] = True
    if ev.get("research_findings"):
        full["research_findings"] = str(ev["research_findings"])[:6000]
    for key in ("tree_ref", "verification_id"):
        if ev.get(key):
            full[key] = str(ev[key])[:128]
    if isinstance(ev.get("findings"), list):
        # verify 전용 부가 필드 — 결함의 소유자 분류 (기계 수리 auto-fix ↔ 사람 판단 ask-user).
        # 알 수 없는 action은 ask-user로 닫는다: 분류 불가를 기계 수리로 흘리면 판단이 필요한
        # 결함이 조용히 추측으로 해소된다. 필드 자체가 없는 판정은 종전 경로 그대로다.
        rows = []
        for index, item in enumerate(ev["findings"][:20], 1):
            if not isinstance(item, dict) or not str(item.get("description") or "").strip():
                continue
            action = str(item.get("action") or "").strip().lower()
            rows.append(
                {
                    "id": str(item.get("id") or f"f{index}")[:32],
                    "severity": str(item.get("severity") or "")[:16],
                    "file": str(item.get("file") or "")[:200],
                    "action": action if action in ("auto-fix", "ask-user", "no-op") else "ask-user",
                    "description": str(item["description"])[:600],
                }
            )
        if rows:
            full["findings"] = rows
    return full


def fold_tickets(events: list[dict]) -> dict[str, dict]:
    """Append-only ticket events를 최신 materialized view로 접는다 (구 이벤트는 기본값으로 호환)."""
    tickets: dict[str, dict] = {}
    for event in events:
        kind = event.get("event")
        if kind not in ("ticket", "ticket_lease") or event.get("unit") is None:
            continue
        key = str(event["unit"])
        current = tickets.get(key, {})
        if kind == "ticket_lease":
            # 갱신은 만료 시각만 민다. claim 이전의 갱신은 접을 상태가 없으니 버린다.
            for field in ("lease_expires_at", "heartbeat_at"):
                if current and event.get(field) is not None:
                    current[field] = event[field]
            continue
        attempt_value = event.get("attempt") if event.get("attempt") is not None else current.get("attempt")
        max_attempts_value = (
            event.get("max_attempts") if event.get("max_attempts") is not None else current.get("max_attempts")
        )
        try:
            attempt = int(str(attempt_value)) if attempt_value is not None else 0
        except BAD_NUMBER:
            attempt = 0
        try:
            max_attempts = int(str(max_attempts_value)) if max_attempts_value is not None else 3
        except BAD_NUMBER:
            max_attempts = 3
        tickets[key] = {
            "id": event["unit"],
            "status": event.get("ticket_status") or current.get("status") or "todo",
            "subtask": event.get("subtask") or current.get("subtask") or "",
            "files": event.get("changed_files") or current.get("files") or [],
            "criteria": event.get("criteria") or current.get("criteria") or [],
            "access": event.get("access") if isinstance(event.get("access"), list) else current.get("access") or [],
            "error": event.get("ticket_error") or current.get("error"),
            "claim_token_hash": event.get("claim_token_hash") or current.get("claim_token_hash"),
            "worker_id": event.get("worker_id") or current.get("worker_id"),
            "lease_expires_at": event.get("lease_expires_at")
            if event.get("lease_expires_at") is not None
            else current.get("lease_expires_at"),
            "heartbeat_at": event.get("heartbeat_at")
            if event.get("heartbeat_at") is not None
            else current.get("heartbeat_at"),
            "attempt": attempt,
            "max_attempts": max_attempts,
        }
    return tickets


def norm_path(path) -> str:
    return os.path.normpath(str(path)).replace("\\", "/")


def verifiable_units(tickets: list[dict]) -> list[str]:
    """Pipeline (not barrier) eligibility: a `done` unit may verify immediately once its `files`
    no longer overlap any still-open (`todo`/`in_progress`) unit's `files` — Workflow tool's
    `pipeline` semantics (no cross-item barrier) ported to Mode B ticket units. This is early
    *verification* eligibility only; the final close/PASS gate (completion_decision) still
    requires every ticket `done` — no change to that barrier.

    Fail-closed on undeclared files: an open unit with no declared `files` has not proven it is
    disjoint from anything, so no unit is early-verifiable until every open unit declares its
    files (absence of a declaration is not evidence of no overlap)."""
    open_files: set[str] = set()
    for ticket in tickets:
        if ticket.get("status") in ("todo", "in_progress"):
            files = [norm_path(f) for f in (ticket.get("files") or [])]
            if not files:
                return []
            open_files.update(files)
    return [
        str(ticket["id"])
        for ticket in tickets
        if ticket.get("status") == "done" and open_files.isdisjoint(norm_path(f) for f in (ticket.get("files") or []))
    ]


def replay_ledger(events: list[dict]) -> dict:
    """Materialize durable execution state from events only; no working-tree reads."""
    first = events[0] if events else {}
    tickets = list(fold_tickets(events).values())
    verifies = [event for event in events if event.get("event") == "verify"]
    closed = [event for event in events if event.get("event") == "quest_closed"]
    last_verify = verifies[-1] if verifies else {}
    return {
        "quest_id": first.get("quest_id"),
        "execution_id": next((event.get("execution_id") for event in events if event.get("execution_id")), None),
        "acceptance_hash": next(
            (event.get("acceptance_hash") for event in events if event.get("acceptance_hash")), None
        ),
        "base_ref": first.get("base_ref"),
        "request": first.get("request") or "",
        "criteria": first.get("criteria") or [],
        "turns": len(events),
        "last_event": events[-1].get("event") if events else None,
        "last_verdict": last_verify.get("verdict"),
        "last_diff_hash": last_verify.get("diff_hash"),
        "verification_id": last_verify.get("verification_id"),
        "tickets": tickets,
        "closed": bool(closed),
        "close_decision": ((closed[-1].get("risk") or {}).get("decision") if closed else None),
    }
