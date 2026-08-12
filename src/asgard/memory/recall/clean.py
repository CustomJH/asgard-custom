"""페이지 전량의 오염 판정 — 읽기와 판정을 각각 캐시로 접는다."""

from __future__ import annotations

import contextlib
import os

from ..index import _db, clean_remember, clean_verdicts
from ..store import _pages_token, _read_all_cached, poison_key, poisoned

# ── 오염되지 않은 페이지 — 회수·카탈로그·점검이 같은 읽기와 같은 판정을 나눠 쓴다 ──────────


_VERDICT_MEMO: dict[str, tuple[str, dict[str, str]]] = {}


def page_verdicts(d: str) -> dict[str, str]:
    """페이지 전량의 오염 판정 — slug → 사유(빈 문자열이 "깨끗함"). 못 읽는 페이지는 빠진다.

    소비자가 셋이다: 회수(`query`)·주입 카탈로그(`_snapshot_rows`)·건강 점검(`pages.lint`).
    셋 다 매 턴 또는 매 계획마다 돌면서 각자 전량을 열고 페이지마다 판정을 처음부터 다시
    했다 — 1,000페이지에서 회수 213ms 중 152ms 가 그 재계산이었고, 카탈로그가 곧바로 같은
    일을 한 번 더 했다 (실측 26-08-02). 여기서 두 가지를 접는다:

      · 읽기 — `store._read_all_cached` (형상이 그대로면 지난 읽기 그대로)
      · 판정 — `state.db` 의 `clean` 칸 (본문 sha 가 그대로면 지난 판정 그대로)

    판정 결과 자체도 형상 표로 메모한다. 둘 다 파생이라 지워도 답이 안 바뀐다 — 다시 잴 뿐이다.

    DB 를 못 열거나 못 쓰면 그냥 전부 다시 잰다 (fail-open). 이 경로는 회수라 사람을 기다리게
    하지 않는 것이 캐시를 남기는 것보다 중요하다 — 그래서 `_lock(d)` 도 잡지 않는다."""
    token = _pages_token(d)
    key = os.path.realpath(d)
    memo = _VERDICT_MEMO.get(key)
    if token and memo is not None and memo[0] == token:
        return memo[1]

    conn = None
    cached: dict[str, tuple[str, str]] = {}
    with contextlib.suppress(Exception):
        conn = _db(d)
        cached = clean_verdicts(conn)
    fresh: list[tuple[str, str, str]] = []
    verdicts: dict[str, str] = {}
    for slug, meta, body in _read_all_cached(d):
        sha = poison_key(meta, body)
        row = cached.get(slug)
        if row is not None and row[0] == sha:
            verdicts[slug] = row[1]
            continue
        verdicts[slug] = verdict = poisoned(meta, body) or ""
        fresh.append((slug, sha, verdict))
    if conn is not None:
        if fresh:
            clean_remember(conn, fresh)
        with contextlib.suppress(Exception):
            conn.close()
    if token:
        _VERDICT_MEMO[key] = (token, verdicts)
    else:
        _VERDICT_MEMO.pop(key, None)
    return verdicts


def clean_pages(d: str) -> dict[str, tuple[dict, str]]:
    """주입 자격이 있는 페이지 전량 — slug → (meta, body). 오염·파싱 실패는 빠진다."""
    verdicts = page_verdicts(d)
    return {slug: (meta, body) for slug, meta, body in _read_all_cached(d) if not verdicts.get(slug, "")}
