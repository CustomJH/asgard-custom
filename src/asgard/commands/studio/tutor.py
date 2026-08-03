"""되짚기 패널의 재료 — 창이 그릴 것을 JSON 으로 만든다. 화면 문장은 여기서 안 만든다.

네 갈래를 한 왕복에 담는다: 열린 물음 · 성장 요약 · 부채 계량 · recap 서사. 앞의 둘은 늘
있는 엔진(`tutor_growth`)이고, 뒤의 둘은 아직 없을 수 있는 엔진이라 못 읽으면 None 으로
적고 `missing` 에 이름을 남긴다 — 조용히 빼면 "잴 것이 없다"와 "못 쟀다"가 같은 화면이
되고, 그건 튜터 계약 ④("못 본 것은 못 봤다고 적는다")를 창에서 깨는 일이다.

답의 왕복도 여기가 진다. 물음만 보여주고 답을 못 받으면 이 층은 아무것도 못 배운다 —
채점은 안 하고(성장 기록 계약 ①) 엔진(`tutor_growth.answer`·`dismiss`)의 판정을 그대로
통과시킨다. 이 모듈이 스스로 내리는 판정은 없다: 좌표·수·이름을 엔진에서 꺼내 담을 뿐이다.
"""

from __future__ import annotations

import time

from ... import tutor as engine
from ... import tutor_growth
from .. import loopback

_json_body = loopback.json_body

_SPANS = ("session", "day", "week")  # recap 이 아는 폭 — 밖에서 온 다른 값은 기본값으로 접는다


def panel_state(root: str, span: str = "day", now: float | None = None) -> dict:
    """패널 한 판의 재료. 문장이 아니라 좌표·수·이름만 담는다 — 문장은 화면이 만든다."""
    stamp = time.time() if now is None else now
    debt = _debt_state(root, stamp)
    recap = _recap_state(root, span if span in _SPANS else "day", stamp)
    return {
        "open": _open_state(root, stamp),
        "growth": tutor_growth.summary(root, stamp),
        "debt": debt,
        "recap": recap,
        # None 은 "못 봤다"다 — 이름까지 적어야 화면이 그 갈래를 "없음"이 아니라 "미계측"으로 그린다.
        "missing": [name for name, value in (("debt", debt), ("recap", recap)) if value is None],
        # 종류의 사람 이름은 엔진이 갖는다 — 화면이 다시 쓰면 같은 판정이 표면마다 다르게 불린다.
        "labels": dict(engine.KIND_LABEL),
    }


def _open_state(root: str, now: float) -> list[dict]:
    """열린 물음 전부 — 무거운 종류부터, 같은 무게면 오래 기다린 것부터(확인 순위는 엔진의 것)."""
    rows = tutor_growth.open_points(root)
    rows.sort(key=lambda row: (-engine.WEIGHT.get(row.kind, 0), row.opened))
    return [
        {
            "cid": row.cid,
            "kind": row.kind,
            "path": row.path,
            "unit": row.unit,
            "where": row.where,
            "ask": row.ask,
            "asks": row.asks,
            "days": row.days(now),
        }
        for row in rows
    ]


def _debt_state(root: str, now: float) -> dict | None:
    """부채 계량 — 엔진이 아직 없거나 죽으면 None. 나머지 세 갈래는 그대로 나간다.

    넓게 삼키는 이유: 이 갈래는 관문이 아니라 계기다. 계기 하나가 죽었다고 창이 통째로
    비면 사용자는 계기가 아니라 창을 의심한다. 못 잰 사실은 None 으로 남아 `missing` 에
    적히므로 실패가 화면에서 사라지지는 않는다 — 삼키되 숨기지는 않는다.
    """
    try:
        from ... import tutor_debt

        led = tutor_debt.ledger(root, now=now)
        worst = led.worst
        return {
            "level": int(led.level),
            "open_debt": int(led.open_debt),
            "oldest_days": int(led.oldest_days),
            "turns": int(led.turns),
            "added": int(led.added),
            "worst": worst.name if worst else "",
            "signals": [
                {"name": s.name, "level": int(s.level), "fact": s.fact, "why": s.why, "source": s.source}
                for s in led.signals
            ],
        }
    except Exception:
        return None


def _recap_state(root: str, span: str, now: float) -> str | None:
    """recap 서사 — 엔진에 아직 없으면 None. 빈 문자열은 "적을 만큼의 일이 없다"라 None 과 가른다."""
    write = getattr(engine, "recap", None)
    if write is None:
        return None
    try:
        return str(write(root, span=span, now=now))
    except Exception:
        return None  # 부채 계량과 같은 계약 — 계기 하나의 실패가 창을 막지 않고, missing 에 적힌다


def answer_point(payload: dict, root: str) -> tuple[int, str, bytes]:
    """물음 하나를 답으로 닫는다. 닫힌 뒤의 패널 재료까지 한 왕복에 돌려준다 — 창이 GET 을
    한 번 더 돌면 그 사이에 낀 남의 변경이 이 답의 결과처럼 보인다."""
    key = str(payload.get("cid") or "").strip()
    text = str(payload.get("text") or "").strip()
    if not key or not text:
        return _json_body(400, {"error": "물음 표식(cid)과 답 본문이 함께 필요해요"})
    closed, note = tutor_growth.answer(root, key, text)
    if not closed:
        return _json_body(404, {"error": note})
    return _json_body(200, {"closed": key, "note": note, "state": panel_state(root)})


def dismiss_point(payload: dict, root: str) -> tuple[int, str, bytes]:
    """오탐으로 닫는다 — 이 통로가 사용자가 튜터를 고치는 길이다(반복 오탐은 탐침을 낮춘다)."""
    key = str(payload.get("cid") or "").strip()
    if not key:
        return _json_body(400, {"error": "물음 표식(cid)이 필요해요"})
    closed, note = tutor_growth.dismiss(root, key, str(payload.get("reason") or ""))
    if not closed:
        return _json_body(404, {"error": note})
    return _json_body(200, {"closed": key, "note": note, "state": panel_state(root)})
