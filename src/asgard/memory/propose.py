"""개인 기억 쓰기 제안 — 에이전트가 **제안**하고 사람이 **승인**한다.

## 왜 이 층이 생겼는가 (26-07-29 감사)

에이전트가 개인 기억을 못 쓰고 있었다. 어느 모드에서도:

  · 네이티브 `tool_kernel` — 메모리 쓰기 툴이 없다 (`ingest_document`는 프로젝트 문서용)
  · MCP 서버 — `memory_retain`/`memory_retain_commit`은 **프로젝트 전용**
  · 개인 경로 — 넛지 문자열을 뿌리고 **사람이 `asgard memory ingest "…"`를 타이핑**

결과가 숫자로 나왔다: 몇 달을 쓴 기계의 1차 메모리가 **페이지 2장**이었다. 사실이 없어서가
아니라 통로에 마찰이 있어서다. 대조군(hermes)은 같은 자리에서 모델이 직접 쓰는 툴을 주고
스키마 설명에 "언제 저장할지"를 박아 뒀는데, 그쪽 뱅크는 1,708 fact 다.

## 무엇을 바꾸고 무엇을 안 바꾸는가

**ask-before-save는 그대로다.** 바뀌는 것은 "사람이 승인한다"와 "사람이 타이핑한다"를
같은 것으로 묶어 두던 구현이다. 프로젝트 레인은 이미 정답을 갖고 있었다 — 스테이징 +
미리보기 + 승인 id (`memory_bridge.config.stage_retain`). 여기는 그 모양을 개인 레인에
옮긴 것이고, **신뢰 경계는 한 치도 안 넓어진다**:

  · 제안은 디스크의 대기열에만 들어간다. 승인 전에는 `pages/`에 한 글자도 안 쓴다.
  · 주입면에도 안 들어간다 — 회수는 `pages/`만 본다.
  · 인젝션·credential 스캔을 **제안 시점과 승인 시점 두 번** 한다 (사이에 파일이 바뀔 수 있다).

## 자동저장 (26-07-30 — 사용자 선택)

기본은 위 그대로다. 그런데 승인을 **매번** 요구하면, 사용자가 자기 이름을 말한 자리에서도
대화가 끊기고 터미널 명령 한 줄을 치라는 안내가 나간다. 안 치면 그 사실은 영영 안 남고,
다음 세션이 같은 것을 또 묻는다 — 게이트가 기억을 지키는 게 아니라 기억을 막는다.

그래서 게이트를 없애는 대신 **사용자 손에** 뒀다: `memory.autosave`가 켜져 있으면 제안이
아니라 저장이다 (`submit`). 켜져도 안 바뀌는 것 — 인젝션·credential 스캔, 근사 중복 병합,
프로파일 격리. 이 설정은 **글로벌에서만** 읽는다 (`policy.autosave_enabled`의 이유 참조).

## 에이전트 격리 (프로파일)

대기열은 `memory_dir()` 안에 있다. 그 경로가 이미 프로파일별로 갈리므로(`profiles.home()`)
에이전트 A의 제안은 B의 대기열에 아예 나타나지 않는다 — 격리는 이 파일이 새로 만드는
것이 아니라 물려받는 것이다. 그 위에 제안마다 `agent`를 적어 두는 이유는 **관측**이다:
`ASGARD_HOME`을 안 물려받은 자식이 기본 에이전트에 제안을 쌓는 사고(hermes 이슈 18594와
같은 모양)가 나면, 승인 화면에 남의 이름이 찍혀 사람이 그 자리에서 알아챈다.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time

from .pages import ingest, plan_ingest
from .policy import autosave_enabled, scan_secrets, scan_threats
from .store import DEFAULT_KIND, KINDS, _atomic_write, _lock, ensure_home, log_op

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


def _pending_unlocked(d: str) -> list[dict]:
    """만료분을 청소한 대기 목록 (오래된 것 먼저) — 호출자가 `_lock(d)` 을 쥐고 있다.

    대기열은 읽고-고쳐-쓰기라 페이지 쓰기와 같은 락을 지난다. 락이 없으면 두 프로세스가
    같은 목록을 읽고 각자 쓴 결과가 마지막 쓴 쪽만 남는다 — 잃는 것은 제안 한 건이고,
    제안은 아직 정본에 없으므로 어디서도 복구되지 않는다."""
    now = time.time()
    rows = _load(d)
    live = _live(rows, now)
    if len(live) != len(rows):
        _save(d, live)
    return sorted(live, key=lambda row: float(row.get("created") or 0))


def _agent() -> str:
    """이 제안을 만든 에이전트 이름 — 못 알아내면 빈 문자열 (fail-open)."""
    try:
        from ..profiles import active

        return active()
    except Exception:
        return ""


def _absorb_pairs(plan: dict) -> list[tuple[str, str]]:
    """계획의 `absorb` 를 (slug, rev) 쌍으로 정규화한다.

    계획은 JSON 대기열을 왕복하므로 tuple 이 list 로 돌아온다. slug 문자열만 든 옛 형식도
    읽는다 — 형식이 갈리는 자리에서 조용히 빈 목록을 돌려주면 "아무것도 안 접는 계획"으로
    보이고, `_plan_key` 대조가 그대로 통과해 버린다."""
    pairs: list[tuple[str, str]] = []
    for entry in plan.get("absorb") or []:
        if isinstance(entry, (list, tuple)):
            slug = entry[0] if entry else ""
            rev = entry[1] if len(entry) > 1 else ""
        else:
            slug, rev = entry, ""
        if isinstance(slug, str) and slug:
            pairs.append((slug, str(rev or "")))
    return pairs


def _absorb_slugs(plan: dict) -> list[str]:
    """계획이 **접을** 페이지 slug — 사람에게 보일 것은 slug 뿐이라 여기서 rev 를 벗긴다.

    접기는 pages/ 밖 archive/ 로의 이동이다 (`pages._absorb_slot_dups`). 검색·주입에서는
    사라지고 `norn.restore_page` 로 되돌아온다."""
    return [slug for slug, _rev in _absorb_pairs(plan)]


def _plan_key(plan: dict) -> tuple:
    """계획에서 **정본을 바꾸는 것**만 뽑는다 — 봉인본과 실행 직전 계획을 대조할 때 쓰는 값.

    비교하는 것은 넷이다: 무슨 동작인가(action), 어느 페이지에 쓰는가(slug), 그 페이지가 승인
    당시 그대로인가(rev), 어느 페이지를 접는가(absorb 의 slug+rev). `sim`·`title` 은 사람에게
    보여 줄 설명이라 뺀다 — 설명이 흔들렸다고 승인을 무르면 승인이 통과할 자리가 없어진다."""
    return (
        str(plan.get("action") or ""),
        str(plan.get("slug") or ""),
        str(plan.get("rev") or ""),
        tuple(sorted(_absorb_pairs(plan))),
    )


def _prepare(text: str, kind: str) -> str:
    """저장 후보 한 건을 정규화하고 문턱을 태운다 — 제안이든 자동저장이든 **같은 문턱**이다.

    거절은 예외가 아니라 ValueError 다: 에이전트가 이유를 읽고 고쳐 다시 낼 수 있어야 한다."""
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
    return body


def stage(text: str, *, kind: str = DEFAULT_KIND, d: str | None = None, title: str = "") -> dict:
    """제안 하나를 대기열에 올린다 — **저장은 안 한다**. 반환 = 제안 레코드."""
    d = ensure_home(d)
    body = _prepare(text, kind)
    title = " ".join(str(title or "").split())
    # 제목도 제안 시점·승인 시점 두 번 태운다 — 본문만 태우면 제목 칸이 스캔을 비껴간다.
    if threat := scan_threats(title):
        raise ValueError(f"injection scan: {threat} — 저장 거부")
    if secret := scan_secrets(title):
        raise ValueError(f"{secret} — 자격증명으로 보이는 내용은 기억에 안 넣는다")

    now = time.time()
    # 같은 사실을 두 번 제안하면 대기열이 아니라 잡음이 된다. 이미 대기 중인 같은 본문은
    # 새 id를 만들지 않고 기존 것을 돌려준다 (에이전트의 재시도가 대기열을 안 부풀린다).
    # 여기 판정은 빠른 길일 뿐이고, 정본 판정은 아래 락 안에서 한 번 더 한다.
    for row in _live(_load(d), now):
        if row.get("text") == body and row.get("kind") == kind:
            return dict(row)
    # 계획 세우기는 락 밖에서 한다 — 읽기뿐이지만 전 페이지 후보 검색이라 오래 걸린다.
    # 그동안 대기열을 잠가 두면 남의 쓰기가 그 시간만큼 멈춘다.
    plan = plan_ingest(body, d) or {}
    record = {
        "id": secrets.token_hex(8),
        "text": body,
        # 제목은 제안한 쪽이 지은 것이라 승인까지 실려 가야 한다 — 여기서 떨구면 승인 경로로
        # 저장된 페이지만 제목이 본문 앞부분으로 되돌아간다.
        "title": title,
        "kind": kind,
        "agent": _agent(),
        "created": now,
        "expires": now + TTL_SECONDS,
        # 승인 화면이 "무엇이 일어날지"를 보여줄 수 있어야 한다 — 새 페이지인가 기존 병합인가.
        "plan_action": str(plan.get("action") or "create"),
        # 병합에는 페이지 접기가 딸려 올 수 있다. 승인하는 사람이 그 사실을 모르면 그건 승인이 아니다.
        "plan_absorb": _absorb_slugs(plan),
        # 계획 **전체**(대상 slug·rev·접을 쌍)를 봉인한다. 표시용 두 칸만 남기고 실행할 때
        # 계획을 다시 세우면 사람이 본 계획과 실행되는 계획이 갈라지고, 갈라진 것을 아무도
        # 못 본다 — `commit` 이 이 봉인본을 실행 직전 계획과 대조한다.
        "plan": plan,
    }
    with _lock(d):
        rows = _live(_load(d), now)
        # 계획을 세우는 동안 같은 사실이 먼저 올라왔을 수 있다 — 그러면 그것을 쓴다.
        for row in rows:
            if row.get("text") == body and row.get("kind") == kind:
                return dict(row)
        rows.append(record)
        _save(d, rows[-MAX_PENDING:])
    log_op(d, "propose", record["id"], f"kind={kind} agent={record['agent'] or '?'}")
    return dict(record)


def submit(text: str, *, kind: str = DEFAULT_KIND, d: str | None = None, title: str = "") -> dict:
    """에이전트의 저장 요청 하나 — 자동저장이면 바로 쓰고, 아니면 대기열에 올린다.

    툴 표면(네이티브 `memory_propose`·MCP `memory_propose`)이 부르는 **단 하나의** 진입점이다.
    설정을 표면마다 읽으면 모드마다 답이 갈린다 — 갈리면 사용자가 "어디선 저장되고 어디선
    안 되는" 기억을 갖게 되고, 그건 기억이 아니라 복권이다.

    반환은 두 갈래가 같은 모양이고 `saved` 로만 갈린다:
      · 자동저장 on  → {"saved": True,  "action": created|merged|…, "slug": …}
      · 자동저장 off → {"saved": False, "id": 제안 id, "plan_action": …}  (기존 계약 그대로)
    """
    d = ensure_home(d)
    body = _prepare(text, kind)
    if not autosave_enabled():
        return {"saved": False, **stage(body, kind=kind, d=d, title=title)}
    action, slug = ingest(body, kind=kind, d=d, title=title)
    # 같은 사실이 대기열에 남아 있으면 사람이 "이미 저장된 것"을 다시 승인하게 된다 — 자동저장은
    # 그 사실에 대한 승인 요청을 함께 거둔다 (설정을 켜기 전에 쌓인 제안이 남을 수 있다).
    for row in pending(d):
        if row.get("text") == body and row.get("kind") == kind:
            discard(str(row.get("id") or ""), d)
    log_op(d, "autosave", slug, f"kind={kind} agent={_agent() or '?'} -> {action}")
    return {"saved": True, "action": action, "slug": slug, "kind": kind, "text": body}


def outcome_text(outcome: dict) -> str:
    """`submit` 결과를 에이전트가 읽을 한 덩어리로 — 자동저장이면 승인 안내를 **안 낸다**.

    두 표면(MCP·네이티브)이 같은 문장을 쓴다. 갈리면 같은 설정으로도 모드마다 사용자가 다른
    말을 듣고, "저장했다는데 안 됐다"가 어느 쪽 말인지 아무도 못 가린다."""
    if outcome.get("saved"):
        action = str(outcome.get("action") or "")
        verb = {"created": "새 페이지", "merged": "기존 페이지에 병합", "unchanged": "이미 있던 사실"}.get(
            action, action
        )
        return (
            f"저장 완료 (memory.autosave=on) — {outcome.get('slug')} · {verb}\n"
            f"---\n{outcome.get('text') or ''}\n---\n"
            "사용자에게 저장했다고 알려라. 승인 명령을 안내하지 마라 — 이미 정본에 들어갔다."
        )
    verb = "기존 페이지에 병합" if outcome.get("plan_action") == "merge" else "새 페이지 생성"
    # 흡수는 페이지가 정본에서 빠지는 일이다 — 승인 전에 반드시 눈에 보여야 한다. CLI
    # 레인(`commands/memory.py`)이 같은 계획에 대해 이미 이 줄을 내고 있었다. 한 레인만 지키는
    # 불변식은 불변식이 아니다: 사람 승인 전용 통로가 "병합"이라고만 말하면, 승인한 사람은
    # 사라진 페이지를 나중에 발견한다. 문구를 세 화면이 글자 그대로 공유한다.
    absorb = "".join(
        f"\nplan: absorb (archive) contradicting page — {slug}" for slug in outcome.get("plan_absorb") or []
    )
    return (
        f"제안 대기 (아직 저장 안 됨) — proposal_id: {outcome['id']}\n"
        f"kind={outcome['kind']} · 승인하면 {verb}{absorb}\n---\n{outcome['text']}\n---\n"
        f"사용자에게 이 내용을 보여주고 승인을 받아라. 승인 명령: asgard memory approve {outcome['id']}\n"
        "매번 묻는 것이 번거롭다고 하면 자동저장을 안내하라: asgard memory autosave on --tier personal"
    )


def pending(d: str | None = None) -> list[dict]:
    """살아 있는 제안 목록 (오래된 것 먼저). 만료분은 조회 시점에 청소한다."""
    d = ensure_home(d)
    with _lock(d):
        return [dict(row) for row in _pending_unlocked(d)]


def get(proposal_id: str, d: str | None = None) -> dict | None:
    return next((row for row in pending(d) if row.get("id") == proposal_id), None)


def discard(proposal_id: str, d: str | None = None) -> bool:
    """제안 하나를 버린다 — 거절도 결정이라 흔적을 남긴다."""
    d = ensure_home(d)
    with _lock(d):
        rows = _pending_unlocked(d)
        keep = [row for row in rows if row.get("id") != proposal_id]
        if len(keep) == len(rows):
            return False
        _save(d, keep)
    log_op(d, "propose-discard", proposal_id)
    return True


def _reseal(proposal_id: str, plan: dict, d: str) -> None:
    """제안 하나의 봉인 계획을 새 계획으로 갈아 끼운다 — 표시용 두 칸도 같이 맞춘다.

    거절만 하고 옛 계획을 남겨 두면 사람이 목록에서 보는 것은 이미 틀린 계획이고, 그것을
    보고 다시 승인해도 같은 자리에서 또 거절당한다."""
    with _lock(d):
        rows = _pending_unlocked(d)
        for row in rows:
            if row.get("id") == proposal_id:
                row["plan"] = plan
                row["plan_action"] = str(plan.get("action") or "create")
                row["plan_absorb"] = _absorb_slugs(plan)
        _save(d, rows)
    log_op(d, "propose-replan", proposal_id, f"action={plan.get('action')} absorb={len(_absorb_slugs(plan))}")


def _approved_plan(proposal_id: str, record: dict, body: str, d: str) -> dict:
    """승인받은 계획을 돌려준다 — 지금 다시 세운 계획과 다르면 아무것도 쓰지 않고 ValueError.

    `pages.ingest` 는 plan 을 받으면 그것을 "사람이 승인한 계획"으로 믿고 그 목록대로 페이지를
    접는다. 그러니 넘길 것은 승인 화면이 보여 준 그 계획이어야 한다. 실행 시점에 계획을 다시
    세워 넘기면 리비전 대조가 자기 자신과의 비교가 되어 언제나 통과하고, 승인 화면에 없던
    페이지가 접힌다 — 방어가 켜져 있는 것처럼 보이면서 꺼져 있다.

    그렇다고 봉인본을 그대로 실행할 수도 없다. 제안과 승인 사이에 정본이 바뀌었으면 그 계획은
    이미 다른 저장소의 계획이다. 그래서 대조만 한다: 같으면 봉인본으로 실행하고, 다르면 새
    계획을 제안에 다시 봉인한 뒤 거절한다. 제안 id 는 이때 소비되지 않으므로 사람은 바뀐
    계획을 보고 같은 id 로 다시 승인하면 된다. 프로젝트 레인의 approval_id 와 같은 규율이다 —
    승인은 **특정 계획 하나**에 대한 승인이고, 계획이 바뀌면 그 승인은 없던 것이 된다."""
    sealed = record.get("plan")
    fresh = plan_ingest(body, d) or {}
    if isinstance(sealed, dict) and _plan_key(sealed) == _plan_key(fresh):
        return dict(sealed)
    _reseal(proposal_id, fresh, d)
    verb = "기존 페이지에 병합" if fresh.get("action") == "merge" else "새 페이지 생성"
    absorb = "".join(f"\nplan: absorb (archive) contradicting page — {slug}" for slug in _absorb_slugs(fresh))
    raise ValueError(
        "stale plan: 승인 화면이 보여 준 계획과 지금 계획이 다르다 — 아무것도 안 썼다\n"
        f"바뀐 계획: {verb}{absorb}\n"
        f"확인하고 다시 승인하라: asgard memory approve {proposal_id}"
    )


def commit(proposal_id: str, d: str | None = None) -> tuple[str, str]:
    """승인된 제안을 정본에 쓴다. 반환 = (action, slug). 1회 소비.

    스캔을 **여기서 다시** 한다. 제안 시점에 이미 통과했지만 그건 다른 시점이고, 그 사이에
    대기열 파일이 바뀔 수 있다 (사람이 편집기로 열 수도, 다른 프로세스가 쓸 수도 있다).
    주입면으로 들어가는 관문은 마지막 순간에 한 번 더 보는 것이 싸다.

    계획도 같은 이유로 다시 본다. 다만 계획은 다시 **세워서 넘기는** 것이 아니라 봉인본과
    **대조**만 한다 (`_approved_plan`)."""
    d = ensure_home(d)
    record = get(proposal_id, d)
    if record is None:
        raise ValueError("없거나 만료된 제안 id")
    agent = _agent()
    staged_by = str(record.get("agent") or "")
    if staged_by and agent and staged_by != agent:
        # 대기열이 프로파일별로 갈려 있어 정상 경로에서는 일어날 수 없다. 일어났다면 환경
        # 전파가 깨진 것이므로(부모가 ASGARD_HOME을 안 넘겼다) 조용히 쓰지 않고 말한다.
        raise ValueError(f"제안을 올린 에이전트({staged_by})와 지금 에이전트({agent})가 다르다 — 승인 거부")
    body = str(record.get("text") or "")
    if threat := scan_threats(body):
        discard(proposal_id, d)
        raise ValueError(f"injection scan: {threat} — 승인 취소, 제안 폐기")
    if secret := scan_secrets(body):
        discard(proposal_id, d)
        raise ValueError(f"{secret} — 승인 취소, 제안 폐기")
    kind = str(record.get("kind") or DEFAULT_KIND)
    action, slug = ingest(
        body, kind=kind, d=d, plan=_approved_plan(proposal_id, record, body, d), title=str(record.get("title") or "")
    )
    discard(proposal_id, d)
    log_op(d, "propose-commit", slug, f"{proposal_id} -> {action}")
    return action, slug


__all__ = [
    "MAX_PENDING",
    "MAX_TEXT",
    "QUEUE_FILE",
    "SCHEMA",
    "TTL_SECONDS",
    "autosave_enabled",
    "commit",
    "discard",
    "get",
    "outcome_text",
    "pending",
    "stage",
    "submit",
]
