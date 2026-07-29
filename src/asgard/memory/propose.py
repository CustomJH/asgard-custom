"""개인 기억 쓰기 제안 — 에이전트가 **제안**하고 사람이 **승인**한다.

## 왜 이 층이 생겼는가 (26-07-29 감사)

에이전트가 개인 기억을 못 쓰고 있었다. 어느 모드에서도:

  · 네이티브 `tool_kernel` — 메모리 쓰기 툴이 없다 (`ingest_document` 는 프로젝트 문서용)
  · MCP 서버 — `memory_retain`/`memory_retain_commit` 은 **프로젝트 전용**
  · 개인 경로 — 넛지 문자열을 뿌리고 **사람이 `asgard memory ingest "…"` 를 타이핑**

결과가 숫자로 나왔다: 몇 달을 쓴 기계의 1차 메모리가 **페이지 2장**이었다. 사실이 없어서가
아니라 통로에 마찰이 있어서다. 대조군(hermes)은 같은 자리에서 모델이 직접 쓰는 툴을 주고
스키마 설명에 "언제 저장할지"를 박아 뒀는데, 그쪽 뱅크는 1,708 fact 다.

## 무엇을 바꾸고 무엇을 안 바꾸는가

**ask-before-save 는 그대로다.** 바뀌는 것은 "사람이 승인한다"와 "사람이 타이핑한다"를
같은 것으로 묶어 두던 구현이다. 프로젝트 레인은 이미 정답을 갖고 있었다 — 스테이징 +
미리보기 + 승인 id (`memory_bridge.config.stage_retain`). 여기는 그 모양을 개인 레인에
옮긴 것이고, **신뢰 경계는 한 치도 안 넓어진다**:

  · 제안은 디스크의 대기열에만 들어간다. 승인 전에는 `pages/` 에 한 글자도 안 쓴다.
  · 주입면에도 안 실린다 — 회수는 `pages/` 만 본다.
  · 인젝션·credential 스캔을 **제안 시점과 승인 시점 두 번** 한다 (사이에 파일이 바뀔 수 있다).

## 에이전트 격리 (프로파일)

대기열은 `memory_dir()` 안에 산다. 그 경로가 이미 프로파일별로 갈리므로(`profiles.home()`)
에이전트 A 의 제안은 B 의 대기열에 아예 나타나지 않는다 — 격리는 이 파일이 새로 만드는
것이 아니라 물려받는 것이다. 그 위에 제안마다 `agent` 를 적어 두는 이유는 **관측**이다:
`ASGARD_HOME` 을 안 물려받은 자식이 기본 에이전트에 제안을 쌓는 사고(hermes 이슈 18594 와
같은 모양)가 나면, 승인 화면에 남의 이름이 찍혀 사람이 그 자리에서 알아챈다.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time

from .pages import ingest, plan_ingest
from .policy import scan_secrets, scan_threats
from .store import DEFAULT_KIND, KINDS, _atomic_write, ensure_home, log_op

QUEUE_FILE = "proposals.json"
SCHEMA = "asgard-memory-proposal-v1"
# 대기열 상한 — 승인이 안 되고 쌓이기만 하면 그건 대기열이 아니라 쓰레기통이다. 넘치면
# **가장 오래된 것부터** 버린다 (새 제안이 거절당하면 에이전트가 같은 것을 계속 재시도한다).
MAX_PENDING = 50
# 만료 — 프로젝트 레인(1시간)보다 길다. 개인 기억의 승인은 대화 흐름 밖에서 일어날 수 있고
# (자리를 비웠다가 돌아와 훑는다), 저장 전에는 아무 효력이 없어 오래 두는 위험이 작다.
TTL_SECONDS = 24 * 60 * 60
MAX_TEXT = 2000


def _queue_path(d: str) -> str:
    return os.path.join(d, QUEUE_FILE)


def _load(d: str) -> list[dict]:
    try:
        with open(_queue_path(d), encoding="utf-8") as handle:
            payload = json.load(handle)
    except OSError, ValueError:
        return []
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return []
    rows = payload.get("proposals")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _save(d: str, rows: list[dict]) -> None:
    _atomic_write(_queue_path(d), json.dumps({"schema": SCHEMA, "proposals": rows}, ensure_ascii=False, indent=1))
    with contextlib.suppress(OSError):
        os.chmod(_queue_path(d), 0o600)  # 대기열도 개인 기억이다 — 소유자 전용


def _live(rows: list[dict], now: float) -> list[dict]:
    return [row for row in rows if float(row.get("expires") or 0) > now]


def _agent() -> str:
    """이 제안을 만든 에이전트 이름 — 못 알아내면 빈 문자열 (fail-open)."""
    try:
        from ..profiles import active

        return active()
    except Exception:
        return ""


def stage(text: str, *, kind: str = DEFAULT_KIND, d: str | None = None) -> dict:
    """제안 하나를 대기열에 올린다 — **저장은 안 한다**. 반환 = 제안 레코드.

    거절은 예외가 아니라 ValueError 다: 에이전트가 이유를 읽고 고쳐 다시 낼 수 있어야 한다."""
    d = ensure_home(d)
    body = " ".join(str(text or "").split())
    if not body:
        raise ValueError("빈 제안 — 저장할 사실을 한 문장으로 적어라")
    if len(body) > MAX_TEXT:
        raise ValueError(f"제안이 너무 길다 ({len(body)}자 > {MAX_TEXT}) — 사실 한 건으로 줄여라")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind!r} — one of {', '.join(KINDS)}")
    if threat := scan_threats(body):
        raise ValueError(f"injection scan: {threat} — 저장 거부")
    if secret := scan_secrets(body):
        raise ValueError(f"{secret} — 자격증명으로 보이는 내용은 기억에 안 넣는다")

    now = time.time()
    rows = _live(_load(d), now)
    # 같은 사실을 두 번 제안하면 대기열이 아니라 잡음이 된다. 이미 대기 중인 같은 본문은
    # 새 id 를 만들지 않고 기존 것을 돌려준다 (에이전트의 재시도가 대기열을 안 부풀린다).
    for row in rows:
        if row.get("text") == body and row.get("kind") == kind:
            return dict(row)
    record = {
        "id": secrets.token_hex(8),
        "text": body,
        "kind": kind,
        "agent": _agent(),
        "created": now,
        "expires": now + TTL_SECONDS,
        # 승인 화면이 "무엇이 일어날지"를 보여줄 수 있어야 한다 — 새 페이지인가 기존 병합인가.
        "plan_action": str((plan_ingest(body, d) or {}).get("action") or "create"),
    }
    rows.append(record)
    _save(d, rows[-MAX_PENDING:])
    log_op(d, "propose", record["id"], f"kind={kind} agent={record['agent'] or '?'}")
    return dict(record)


def pending(d: str | None = None) -> list[dict]:
    """살아 있는 제안 목록 (오래된 것 먼저). 만료분은 조회 시점에 청소한다."""
    d = ensure_home(d)
    now = time.time()
    rows = _load(d)
    live = _live(rows, now)
    if len(live) != len(rows):
        _save(d, live)
    return [dict(row) for row in sorted(live, key=lambda row: float(row.get("created") or 0))]


def get(proposal_id: str, d: str | None = None) -> dict | None:
    return next((row for row in pending(d) if row.get("id") == proposal_id), None)


def discard(proposal_id: str, d: str | None = None) -> bool:
    """제안 하나를 버린다 — 거절도 결정이라 흔적을 남긴다."""
    d = ensure_home(d)
    rows = pending(d)
    keep = [row for row in rows if row.get("id") != proposal_id]
    if len(keep) == len(rows):
        return False
    _save(d, keep)
    log_op(d, "propose-discard", proposal_id)
    return True


def commit(proposal_id: str, d: str | None = None) -> tuple[str, str]:
    """승인된 제안을 정본에 쓴다. 반환 = (action, slug). 1회 소비.

    스캔을 **여기서 다시** 한다. 제안 시점에 이미 통과했지만 그건 다른 시점이고, 그 사이에
    대기열 파일이 바뀔 수 있다 (사람이 편집기로 열 수도, 다른 프로세스가 쓸 수도 있다).
    주입면으로 들어가는 관문은 마지막 순간에 한 번 더 보는 것이 싸다."""
    d = ensure_home(d)
    record = get(proposal_id, d)
    if record is None:
        raise ValueError("없거나 만료된 제안 id")
    agent = _agent()
    staged_by = str(record.get("agent") or "")
    if staged_by and agent and staged_by != agent:
        # 대기열이 프로파일별로 갈려 있어 정상 경로에서는 일어날 수 없다. 일어났다면 환경
        # 전파가 깨진 것이므로(부모가 ASGARD_HOME 을 안 넘겼다) 조용히 쓰지 않고 말한다.
        raise ValueError(f"제안을 올린 에이전트({staged_by})와 지금 에이전트({agent})가 다르다 — 승인 거부")
    body = str(record.get("text") or "")
    if threat := scan_threats(body):
        discard(proposal_id, d)
        raise ValueError(f"injection scan: {threat} — 승인 취소, 제안 폐기")
    if secret := scan_secrets(body):
        discard(proposal_id, d)
        raise ValueError(f"{secret} — 승인 취소, 제안 폐기")
    kind = str(record.get("kind") or DEFAULT_KIND)
    # 계획을 지금 다시 세운다: 제안 시점의 계획은 표시용이었고, 그 사이 정본이 바뀌었으면
    # 병합 대상도 바뀐다 (승인한 것과 실제가 갈라지지 않게 — pages.ingest 의 TOCTOU 규율).
    action, slug = ingest(body, kind=kind, d=d, plan=plan_ingest(body, d))
    discard(proposal_id, d)
    log_op(d, "propose-commit", slug, f"{proposal_id} -> {action}")
    return action, slug


__all__ = [
    "MAX_PENDING",
    "MAX_TEXT",
    "QUEUE_FILE",
    "SCHEMA",
    "TTL_SECONDS",
    "commit",
    "discard",
    "get",
    "pending",
    "stage",
]
