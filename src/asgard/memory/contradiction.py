"""미해결 모순 장부 — 노른이 찾은 어긋남을 사람이 볼 수 있는 자리에 쌓는다.

이 분야는 모순을 셋 중 하나로 다룬다: 옛 사실을 무효로 돌리거나(Graphiti), 새 값으로
덮어쓰거나(Memobase), 둘 다 남겨 두거나(Mem0). Asgard 는 넷째를 골랐다 — **사람에게
넘긴다**. 고른 이유는 분명하다: 단일값 정체성 슬롯 다섯(name·birthday·timezone·email·
language) **밖에서는** 두 기록이 어긋나 보여도 대개 둘 다 참이다 (다른 시기, 다른 맥락,
다른 대상). 그 자리에서 자동 해소는 사용자가 적은 사실을 정본에서 제거한다 — 흡수는 페이지를
아카이브로 옮긴다 (`pages._absorb_slot_dups`, 되돌리려면 `norn.restore_page`).

문제는 넘긴다고 해 놓고 **넘기는 통로를 안 만든 것**이었다. `norn.contradiction` op 은
아무것도 안 고치고 보고만 하는데, 그 보고가 닿는 곳은 그 런의 리포트 파일 하나뿐이었다.
리포트는 런마다 새로 생기므로 같은 모순이 열 번 감지되면 열 개의 파일에 흩어지고, 사람이
한 번 보고 "이건 둘 다 맞다"고 판단한 것도 다음 런에서 똑같이 다시 뜬다. 아무도 안 읽는
경고는 없는 경고와 같다.

그래서 장부를 둔다. 규율 셋:

**① 자동으로 해소하지 않는다.** 이 모듈에는 페이지를 고치거나 지우는 길이 없다. 사람이
   할 수 있는 것은 "봤다"고 표시하는 것뿐이고(`acknowledge_contradiction`), 그것도 어느
   쪽이 참인지는 안 적는다 — 해소는 사람이 정본을 고쳐서 한다.

**② 같은 모순은 한 줄이다.** 동일성은 **페이지 쌍**으로 잡는다 (순서 무관). 같은 쌍이 다시
   보고되면 새 줄이 생기는 대신 감지 횟수와 마지막 시각만 오른다. LLM 이 대는 사유(`why`)는
   런마다 표현이 달라지므로 동일성 판정에 넣지 않는다 — 넣으면 같은 어긋남이 문장만 바뀌어
   영원히 새 모순으로 쌓인다.

**③ 넘긴 것이 되살아나는 조건은 하나 — 땅이 바뀌었을 때.** 사람이 넘긴(acknowledged) 모순은
   다시 안 뜬다. 단, 두 페이지 중 하나라도 그 뒤 내용이 바뀌었으면 다시 연다: 넘긴 판단은
   그때의 두 문장에 대한 것이지 그 자리에 앞으로 올 모든 문장에 대한 것이 아니다.

장부는 정본이다 (`store.CONTRADICTIONS`, `backup.CANONICAL_FILES`). 감지 자체는 다음 노른
런이 다시 할 수 있지만 **사람이 넘겼다는 사실은 재생 원본이 없다** — 회수 기록과 같은 이유로
파생 저장소에 두지 않는다 (`memory.usage`).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os

from .pages import _rev
from .policy import memory_dir
from .store import CONTRADICTIONS, _atomic_write, _page_path, _read, valid_slug

LEDGER_SCHEMA = 1
OPEN, ACKNOWLEDGED = "open", "acknowledged"


def ledger_path(d: str) -> str:
    return os.path.join(d, CONTRADICTIONS)


def contradiction_key(a: str, b: str) -> str:
    """모순 하나의 신원 — 순서 없는 페이지 쌍. `[[a]]↔[[b]]` 와 `[[b]]↔[[a]]` 는 같은 모순이다."""
    return "|".join(sorted((str(a), str(b))))


def _stamp() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%MZ")


def _load(d: str) -> dict[str, dict]:
    try:
        with open(ledger_path(d), encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, dict):
        return {}
    return {key: row for key, row in items.items() if isinstance(key, str) and isinstance(row, dict)}


def _save(d: str, items: dict[str, dict]) -> None:
    payload = {
        "schema": LEDGER_SCHEMA,
        "note": "미해결 모순 장부 — 정본이다 (사람이 넘겼다는 사실은 재생되지 않는다).",
        "items": {key: items[key] for key in sorted(items)},
    }
    with contextlib.suppress(Exception):  # 장부 쓰기 실패가 손질을 막지 않는다
        _atomic_write(ledger_path(d), json.dumps(payload, ensure_ascii=False, indent=1) + "\n")


def _alive(d: str, slug: str) -> bool:
    return bool(slug) and valid_slug(slug) and os.path.exists(_page_path(d, slug))


def _title(d: str, slug: str) -> str:
    page = _read(d, slug)
    return str(page[0].get("title", slug)) if page else slug


def record(rows: list[dict], d: str | None = None) -> list[dict]:
    """감지된 모순을 장부에 접수한다. 반환 = 접수된 기록들 (입력 순서, `new` 표식 포함).

    rows 는 `{"a": slug, "b": slug, "why": str}` 목록 — `norn.validate_ops` 가 통과시킨 op 형상
    그대로다. 이미 있는 쌍은 새 줄을 만들지 않고 `count`·`last_seen` 만 올린다. 사람이 넘긴
    쌍은 넘긴 채로 두되, 두 페이지 중 하나라도 그 뒤 바뀌었으면 다시 연다 (모듈 독스트링 ③).

    반환 dict 의 `new` 는 이번 호출에서 처음 생긴 줄인가이고, 장부 파일에는 안 들어간다 —
    보고문이 "처음 보는 것"과 "또 보는 것"을 가려 쓰기 위한 값이다."""
    d = d or memory_dir()
    items = _load(d)
    stamp = _stamp()
    out: list[dict] = []
    for row in rows:
        a, b = str(row.get("a") or ""), str(row.get("b") or "")
        if not (_alive(d, a) and _alive(d, b)) or a == b:
            continue  # 사라진 페이지의 모순은 접수하지 않는다 — 어긋날 상대가 없다
        key = contradiction_key(a, b)
        # 신원이 순서를 지운 뒤에는 판본도 그 순서로 적어야 한다 — 입력 순서로 적으면
        # `rev_a` 가 저장된 `a` 가 아닌 페이지의 판본이 되어 "땅이 바뀌었다"가 늘 참이 된다.
        first, second = sorted((a, b))
        rev_a, rev_b = _rev(d, first), _rev(d, second)
        existing = items.get(key)
        if existing is None:
            items[key] = {
                "a": first,
                "b": second,
                "why": str(row.get("why", ""))[:200],
                "detected": stamp,
                "last_seen": stamp,
                "count": 1,
                "status": OPEN,
                "acknowledged": "",
                "note": "",
                "rev_a": rev_a,
                "rev_b": rev_b,
            }
            out.append({**items[key], "key": key, "new": True})
            continue
        existing["last_seen"] = stamp
        existing["count"] = int(existing.get("count") or 0) + 1
        if str(row.get("why", "")).strip():
            existing["why"] = str(row.get("why", ""))[:200]  # 최신 사유로 갱신 — 신원은 쌍이 진다
        if existing.get("status") == ACKNOWLEDGED and (
            existing.get("rev_a") != rev_a or existing.get("rev_b") != rev_b
        ):
            existing.update({"status": OPEN, "acknowledged": "", "rev_a": rev_a, "rev_b": rev_b})
        out.append({**existing, "key": key, "new": False})
    _save(d, items)
    return out


def open_contradictions(d: str | None = None, *, include_acknowledged: bool = False) -> list[dict]:
    """미해결 모순 목록 — 무엇과 무엇이, 왜, 언제부터. 최근 감지 순. 쓰기 없음.

    두 페이지가 다 살아 있는 줄만 준다. 한쪽이 사라졌으면 그 모순은 물음 자체가 없어진
    것이지 해소된 것이 아니다 — 장부에는 남겨 두고 목록에서만 뺀다 (사라진 페이지를 복원하면
    다시 보인다). include_acknowledged=True 면 사람이 이미 넘긴 것까지 같이 준다."""
    d = d or memory_dir()
    rows: list[dict] = []
    for key, row in _load(d).items():
        a, b = str(row.get("a") or ""), str(row.get("b") or "")
        if not (_alive(d, a) and _alive(d, b)):
            continue
        status = str(row.get("status") or OPEN)
        if status != OPEN and not include_acknowledged:
            continue
        rows.append(
            {
                "key": key,
                "a": a,
                "b": b,
                "a_title": _title(d, a),
                "b_title": _title(d, b),
                "why": str(row.get("why") or ""),
                "detected": str(row.get("detected") or ""),
                "last_seen": str(row.get("last_seen") or ""),
                "count": int(row.get("count") or 0),
                "status": status,
                "acknowledged": str(row.get("acknowledged") or ""),
                "note": str(row.get("note") or ""),
                "changed_since": _changed_since(d, row),
            }
        )
    return sorted(rows, key=lambda r: (r["last_seen"], r["key"]), reverse=True)


def _changed_since(d: str, row: dict) -> bool:
    """장부가 본 그 판본 이후로 두 페이지 중 하나가 바뀌었는가 — 목록이 낡았는지 사람이 알게."""
    return bool(
        row.get("rev_a") != _rev(d, str(row.get("a") or "")) or row.get("rev_b") != _rev(d, str(row.get("b") or ""))
    )


def acknowledge_contradiction(key: str, *, note: str = "", d: str | None = None) -> dict | None:
    """사람이 "봤다"고 표시한다. 반환 = 갱신된 기록, 그런 모순이 없으면 None.

    **해소가 아니다.** 페이지는 한 글자도 안 바뀌고, 어느 쪽이 참인지도 안 적힌다. 뜻은
    "이 어긋남은 내가 알고 있으니 다음 손질 때 또 보여 주지 마라"뿐이다. 두 페이지 중 하나가
    나중에 바뀌면 표시는 자동으로 풀린다 (`record` — 넘긴 판단은 그때의 두 문장에 대한 것이다)."""
    d = d or memory_dir()
    items = _load(d)
    row = items.get(key)
    if row is None:
        return None
    row.update(
        {
            "status": ACKNOWLEDGED,
            "acknowledged": _stamp(),
            "note": str(note)[:200],
            "rev_a": _rev(d, str(row.get("a") or "")),
            "rev_b": _rev(d, str(row.get("b") or "")),
        }
    )
    _save(d, items)
    return {**row, "key": key}


__all__ = [
    "ACKNOWLEDGED",
    "LEDGER_SCHEMA",
    "OPEN",
    "acknowledge_contradiction",
    "contradiction_key",
    "ledger_path",
    "open_contradictions",
    "record",
]
