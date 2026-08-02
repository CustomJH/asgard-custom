"""회수 계기 — 노출과 사용을 가르고, 사용 기록을 정본으로 남긴다.

망각 계기가 양쪽으로 고장나 있던 자리다. 둘은 반대 방향이지만 원인이 하나다: 사용 기록이
무엇인지가 정해져 있지 않았다.

**① 판정이 영영 안 열린다.** 부패 후보는 "오래 안 고쳤고 한 번도 안 불렸다"인데, 매 턴
자동으로 프롬프트에 실리는 것까지 '불렸다'로 셌다 (`recall.recall_rows`). 한 번이라도 실린
페이지는 uses>0 이 되어 **영원히** 후보에서 빠진다. 자동 주입은 사람이 그 기억을 찾은 사건이
아니라 회수기가 그 기억을 골라 준 사건이다 — 그걸 사용으로 세면 계기가 자기 출력을 자기
입력으로 먹는다. 그래서 두 사건을 가른다:

    노출(exposure) — 자동 주입으로 프롬프트에 실렸다. 사람은 이걸 부른 적이 없다.
    사용(use)      — 사람이 부른 검색(`asgard memory query`·MCP 회수 도구)에 걸렸다.

부패 판정은 **사용만** 본다. 노출은 세되 판정에도 랭킹에도 안 쓴다 (왜 랭킹에도 안 쓰는지는
`recall.query`의 타이브레이크 주석에 있다). 노출을 버리지 않는 이유는 그 값이 대답하는
물음이 따로 있어서다 — "회수기는 이 페이지를 자꾸 고르는데 사람은 한 번도 안 찾는다"는
lint 가 사람에게 보여줄 만한 사실이다.

**② 반대로, 세어 둔 사용이 통째로 사라진다.** `state.db` 는 파생 계층이라 손상되면 지우고
pages/ 에서 다시 만든다 (`index._db`). 그런데 재생되는 것은 색인이고 사용 기록은 pages/ 에
없다 — **재생 원본이 없는 원본 데이터가 파생 저장소에 살고 있었다.** 이 시스템의 원칙
("정본=파일, 파생=state.db, 파생은 버려도 된다")을 사용 기록만 어기고 있었고, 그 대가는
DB 를 한 번 잃으면 90일 넘은 전 페이지가 **일제히** 부패 후보로 뜨는 것이다.

**고른 길 — (c) 절충.** 세 길이 있었다:
  (a) 페이지 frontmatter 로 내린다 — 정본과 같이 살고 git 으로 따라온다. 대신 회수마다
      정본 파일을 N 장 다시 쓴다. 값이 비싼 것만이 문제가 아니라 **정본을 더럽힌다**:
      mtime 이 바뀌면 `index._pages_fingerprint`의 메모가 매 턴 깨지고(coverage 판정이
      매번 전 페이지 sha 를 다시 만든다), git diff 는 지식이 바뀌지 않은 커밋으로 찬다.
  (b) `backup.py` 대상에만 넣는다 — 싸지만 백업을 안 돌린 사람은 그대로 잃는다. 원본
      데이터의 내구성을 사용자의 습관에 맡기는 것은 내구성이 아니다.
  (c) 둘의 절충 — 빈도가 다른 두 사건을 다른 자리에 적는다. 그래서 이걸 골랐다:

    사용 — DB 에 적고 **곧바로** `usage.json` 에 접는다. 사람이 부른 검색은 드물고(턴마다가
           아니라 사람이 칠 때만), 부패 판정이 읽는 값이 이것이다. 판정의 근거가 손상 하나로
           날아가지 않는 값이 한 번 쓰기보다 비싸다. 실측(26-08-01, 1,000 페이지): 회수 기록이
           몇 장뿐일 때 접기 한 번이 0.74ms, 전 페이지에 다 있는 최악 경우에도 2.46ms —
           같은 자리의 쓰기 한 번(`index.write_index` 73ms)의 3%다.
    노출 — DB 에만 적는다. 매 턴 일어나므로 여기에 파일 쓰기를 달면 (a)와 같은 비용이 든다.
           잃어도 판정은 안 흔들린다 — 노출은 판정에 안 쓰이니까. 접는 것은 사용이 접힐 때
           같이, 또는 reindex·백업 같은 큰 계기에.

`usage.json` 은 정본 옆에 있다 (`store.USAGE`, `backup.CANONICAL_FILES`). state.db 를
백업에 넣는 길은 안 골랐다 — 파생물을 백업에 담으면 복원본이 다른 시점의 색인을 들고
살아나고 그 불일치는 조용하다 (`backup` 모듈 독스트링). 사용 기록만 텍스트로 따로 내면
파생물은 여전히 버릴 수 있는 것으로 남는다.

**락 — 이 파일은 `_lock(d)` 을 안 잡는다 (의도).** `flush`·`forget` 은 읽고-고쳐-쓰기라
형제 장부(`propose`·`contradiction`)처럼 디렉터리 락을 지나는 것이 맞지만, 그럴 수 없다:
호출자 셋(`pages.remove`·`pages.merge`·`index.reindex`)이 **이미 그 락을 쥔 채로** 부른다.
같은 프로세스가 같은 락을 두 번 잡으면 flock 은 재진입이 아니라 교착이다. 대신 이 자리는
잃어도 회복된다 — `merged()` 가 파일과 DB 중 큰 쪽을 취하므로 겹친 쓰기의 결과는 계수가
안 오르는 것이지 사라지는 것이 아니다. 락을 여기 넣으려는 사람은 먼저 저 세 호출자를
`_lock` 밖으로 빼거나 unlocked 본체를 갈라야 한다.
"""

from __future__ import annotations

import contextlib
import json
import os

from .store import PAGES, USAGE, _atomic_write, _pages, _today

USAGE_SCHEMA = 1
_EMPTY = {"uses": 0, "last_used": "", "exposures": 0, "last_exposed": ""}


def usage_path(d: str) -> str:
    return os.path.join(d, USAGE)


def read_file(d: str) -> dict[str, dict]:
    """`usage.json` 의 사용 기록. 없거나 못 읽으면 빈 dict (fail-open — 계기가 지식을 막지 않는다)."""
    try:
        with open(usage_path(d), encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    rows = payload.get("pages") if isinstance(payload, dict) else None
    if not isinstance(rows, dict):
        return {}
    clean: dict[str, dict] = {}
    for slug, row in rows.items():
        if isinstance(slug, str) and isinstance(row, dict):
            clean[slug] = _row(row)
    return clean


def _row(row: dict) -> dict:
    """외부 편집 관용 — 숫자가 아니면 0, 날짜가 아니면 빈 문자열."""

    def count(key: str) -> int:
        try:
            return max(0, int(row.get(key) or 0))
        except TypeError, ValueError:
            return 0

    def stamp(key: str) -> str:
        value = row.get(key)
        return str(value)[:10] if isinstance(value, str) else ""

    return {
        "uses": count("uses"),
        "last_used": stamp("last_used"),
        "exposures": count("exposures"),
        "last_exposed": stamp("last_exposed"),
    }


def _write_file(d: str, rows: dict[str, dict]) -> None:
    payload = {
        "schema": USAGE_SCHEMA,
        "note": "회수 기록 — 정본이다 (state.db 에서 재생되지 않는다). memory/usage.py 참조.",
        "pages": {slug: rows[slug] for slug in sorted(rows)},
    }
    with contextlib.suppress(Exception):  # 계기 쓰기 실패가 회수를 막지 않는다
        _atomic_write(usage_path(d), json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False) + "\n")


def counters(d: str) -> dict[str, dict]:
    """state.db 의 현재 회수 계수 — {slug: {uses, last_used, exposures, last_exposed}}."""
    from .index import _db

    rows: dict[str, dict] = {}
    with contextlib.suppress(Exception):
        conn = _db(d)
        for slug, uses, last_used, exposures, last_exposed in conn.execute(
            "SELECT slug, uses, last_used, exposures, last_exposed FROM usage"
        ):
            rows[str(slug)] = {
                "uses": int(uses or 0),
                "last_used": str(last_used or ""),
                "exposures": int(exposures or 0),
                "last_exposed": str(last_exposed or ""),
            }
        conn.close()
    return rows


def merged(d: str) -> dict[str, dict]:
    """판정과 표면이 읽어야 할 회수 사실 — 파일과 DB 중 **큰 쪽**. 어느 한쪽만 보면 틀린다.

    DB 만 보면 파생 소실 직후(reindex 전)에 전 페이지가 회수 0으로 보인다 — 부패 판정이
    일제히 열리는 바로 그 그림이다. 파일만 보면 마지막으로 접힌 뒤의 노출이 안 보인다.
    큰 쪽을 쓰면 둘 중 어느 것이 최신이든 세어 둔 것을 잃지 않는다 (`hydrate` 와 같은 규칙)."""
    rows = dict(read_file(d))
    for slug, live in counters(d).items():
        prev = rows.get(slug)
        rows[slug] = (
            live
            if prev is None
            else {key: max(prev[key], live[key]) for key in ("uses", "last_used", "exposures", "last_exposed")}
        )
    return rows


def bump(d: str, slugs: list[str], *, exposure: bool) -> None:
    """회수 흔적 기록 — exposure=True 면 노출, False 면 사용. 실패는 무해 (fail-open).

    사용은 그 자리에서 정본에 접는다 (모듈 독스트링의 (c) 참조). 노출은 DB 까지만 — 매 턴
    일어나는 사건에 파일 쓰기를 달면 정본이 회수 로그가 된다."""
    if not slugs:
        return
    from .index import _db

    stamp = _today()
    column = "exposures" if exposure else "uses"
    last = "last_exposed" if exposure else "last_used"
    with contextlib.suppress(Exception):
        conn = _db(d)
        with conn:
            for slug in slugs:
                # 칸 이름은 위 두 리터럴 중 하나다 — 질의는 f-string 이어도 값은 코드가 정한다.
                conn.execute(  # noqa: S608
                    f"INSERT INTO usage(slug, {column}, {last}) VALUES(?,1,?) "
                    f"ON CONFLICT(slug) DO UPDATE SET {column} = {column} + 1, {last} = ?",
                    (slug, stamp, stamp),
                )
        conn.close()
    if not exposure:
        flush(d)


def flush(d: str, *, force: bool = False) -> bool:
    """회수 계수를 `usage.json` 에 접는다. 반환 = 실제로 썼는가.

    **접기는 덮어쓰기가 아니라 합치기다.** DB 계수만 그대로 쓰면 접는 순간 DB 가 비어 있을 때
    (손상 직후, reindex 전) 정본이 같이 비워진다 — 파생 소실을 견디려고 만든 파일이 파생
    소실로 지워지는 셈이다. 그래서 `merged` 로 큰 쪽을 남긴다: 이 함수는 계수를 올리거나
    그대로 두기만 하고, 줄이지 않는다.

    줄어드는 경우는 하나뿐이다 — 페이지가 사라졌을 때. 지워진 페이지의 계수를 남겨 두면 같은
    이름의 새 페이지가 남의 회수 기록을 물려받는다. 그 정리도 pages/ 를 **실제로 읽을 수
    있을 때만** 한다: 목록을 못 읽은 것을 "다 지워졌다"로 읽으면 그게 또 한 번의 소실이다.
    force 는 내용이 같아도 쓴다 (실측용)."""
    rows = merged(d)
    if os.path.isdir(os.path.join(d, PAGES)):
        live = set(_pages(d))
        rows = {slug: row for slug, row in rows.items() if slug in live}
    if not rows and not os.path.exists(usage_path(d)):
        return False  # 셀 것도 지울 것도 없다 — 빈 파일을 만들지 않는다
    if not force and rows == read_file(d):
        return False
    _write_file(d, rows)
    return True


def forget(d: str, slug: str) -> None:
    """한 페이지의 회수 기록을 DB 와 파일 양쪽에서 지운다 — 삭제·병합·흡수가 부른다."""
    rows = read_file(d)
    if rows.pop(slug, None) is not None:
        _write_file(d, rows)
    from .index import _db

    with contextlib.suppress(Exception):
        conn = _db(d)
        with conn:
            conn.execute("DELETE FROM usage WHERE slug = ?", (slug,))
        conn.close()


def hydrate(d: str) -> int:
    """`usage.json` → state.db. 반환 = 되살린 행 수. DB 를 잃은 뒤 회수 기록이 돌아오는 길.

    계수는 **큰 쪽을 남긴다**. 파일이 뒤처져 있을 수도(노출은 늦게 접힌다), DB 가 갓 만들어진
    빈 것일 수도 있어서다 — 어느 쪽이 최신인지 모르는 채 덮으면 세어 둔 것을 잃는다.
    정본에 없는 slug 는 되살리지 않는다 (지워진 페이지가 계수를 물려받지 않게)."""
    rows = read_file(d)
    if not rows:
        return 0
    live = set(_pages(d))
    from .index import _db

    restored = 0
    with contextlib.suppress(Exception):
        conn = _db(d)
        with conn:
            for slug, row in rows.items():
                if slug not in live:
                    continue
                conn.execute(
                    "INSERT INTO usage(slug, uses, last_used, exposures, last_exposed) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(slug) DO UPDATE SET "
                    "uses = max(uses, excluded.uses), "
                    "last_used = max(coalesce(last_used,''), coalesce(excluded.last_used,'')), "
                    "exposures = max(exposures, excluded.exposures), "
                    "last_exposed = max(coalesce(last_exposed,''), coalesce(excluded.last_exposed,''))",
                    (slug, row["uses"], row["last_used"], row["exposures"], row["last_exposed"]),
                )
                restored += 1
        conn.close()
    return restored


def usage_of(d: str, slug: str) -> dict:
    """한 페이지의 회수 사실 — 표면·판정이 같은 값을 보게 하는 단일 창구 (`merged` 기준)."""
    return dict(merged(d).get(slug) or _EMPTY)


__all__ = [
    "USAGE_SCHEMA",
    "bump",
    "counters",
    "flush",
    "forget",
    "hydrate",
    "merged",
    "read_file",
    "usage_of",
    "usage_path",
]
