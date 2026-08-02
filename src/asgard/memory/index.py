"""파생 계층 — index.md 카탈로그 + state.db(FTS5·vec·usage). 지워도 pages/ 에서 재생성된다."""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3

from .. import io_sqlite
from .policy import memory_dir
from .store import (
    DB,
    INDEX,
    _atomic_write,
    _chmod,
    _desc,
    _kind,
    _lock,
    _pages,
    _pages_fingerprint,
    _read,
    _read_all,
    _read_all_cached,
    ensure_home,
    poison_ruleset,
)

# ── index.md — 카탈로그 (파생: pages/ 에서 전체 재생성) ──────────────────────────


def _index_row(slug: str, meta: dict, body: str) -> str:
    return f"- [{meta.get('title', slug)}](pages/{slug}.md) `{_kind(meta)}` — {_desc(meta, body)}"


def build_index(d: str, loaded: list[tuple[str, dict, str]] | None = None) -> str:
    """카탈로그 본문. loaded 를 주면 그 읽기를 재사용한다 (`store._read_all` 참조).

    안 주면 공유 읽기 캐시에서 가져온다 — `lint`가 낡음 대조로 이 함수를 부르는데, 그 호출이
    같은 점검 안에서 전량 읽기를 한 번 더 하던 자리다."""
    lines = ["# Memory Index", ""]
    for slug, meta, body in _read_all_cached(d) if loaded is None else loaded:
        lines.append(_index_row(slug, meta, body))
    return "\n".join(lines) + "\n"


def write_index(d: str) -> str:
    # 페이지는 여기서 **한 번** 읽는다. 아래 두 파생 목차가 같은 (meta, body)를 각자 다시
    # 열던 자리다 — 페이지를 저장할 때마다 도는 경로라 쓰기 한 번이 읽기 2N 번이었다.
    # 실측(26-08-01): 200 페이지 26.5ms → 14.8ms, 1,000 페이지 137.1ms → 72.6ms (−47%).
    # 읽기 절반과 함께 chmod 도 절반이 준다 (`vault.write_maps` 의 loaded 갈래).
    loaded = _read_all(d)
    text = build_index(d, loaded)
    _atomic_write(os.path.join(d, INDEX), text)
    # index.md는 주입면이라 예산에 묶여 있다. 예산 밖 전체 목차는 maps/ 가 진다 —
    # 같은 파생 시점에 같이 갱신돼야 vault를 열었을 때 목차가 거짓말하지 않는다.
    with contextlib.suppress(Exception):  # 파생 목차 실패가 지식 쓰기를 막지 않는다
        from .vault import write_maps

        write_maps(d, loaded=loaded)
    return text


# ── FTS5 파생 인덱스 (state.db) — 지워도·손상돼도 reindex로 복원 ─────────────────


def _connect(path: str) -> sqlite3.Connection:
    # 접속 계약(WAL·busy_timeout)은 `io_sqlite` 가 진다. 이 파일이 그 계약을 필요로 하는 이유:
    # 회수(`recall_rows`)가 매 턴 도는데 Dual Thinker 는 그 턴을 스레드 둘로 돌리고, 회수 경로가
    # 노출 계수를 쓰기 때문에 같은 state.db 에 읽기와 쓰기가 동시에 닿는다.
    conn = io_sqlite.connect(path)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5"
            "(slug UNINDEXED, title, kind UNINDEXED, body, tokenize='trigram')"
        )
        # 회수 계수 — 사람이 부른 검색(uses)과 자동 주입(exposures)을 **갈라서** 센다.
        # 둘을 한 칸에 세면 매 턴 주입되는 페이지가 영영 부패 후보가 못 된다 (memory.usage ①).
        # 이 칸은 파생이 아니다: 재생 원본이 pages/ 에 없어 정본 `usage.json` 이 짝으로 산다.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS usage(slug TEXT PRIMARY KEY, uses INT DEFAULT 0, last_used TEXT, "
            "exposures INT DEFAULT 0, last_exposed TEXT)"
        )
        # 옛 스키마(uses/last_used 둘뿐)를 만나면 조용히 늘린다 — 사람이 DB를 지우게 만들지 않는다.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(usage)")}
        if "exposures" not in columns:
            conn.execute("ALTER TABLE usage ADD COLUMN exposures INT DEFAULT 0")
        if "last_exposed" not in columns:
            conn.execute("ALTER TABLE usage ADD COLUMN last_exposed TEXT")
        # vec = 시맨틱 스트림 파생물 (옵트인). sha로 본문 변경만 재임베딩, data는 float32 BLOB.
        # 지워도·모델 바뀌어도 정본(pages/)에서 reindex로 복원 — 파일이 여전히 정본이다.
        conn.execute("CREATE TABLE IF NOT EXISTS vec(slug TEXT PRIMARY KEY, sha TEXT, dim INT, data BLOB)")
        # 구절 벡터 — 페이지 벡터와 같은 sha 규율의 파생물. 리랭크는 페이지 하나를 구절 수십으로
        # 쪼개 임베딩하는데, 그 결과가 어디에도 안 남아 **글자 그대로 같은 질의**가 같은 계산을
        # 매번 다시 했다 (실측 26-08-02: 1회차 636 호출 · 2회차 636 호출). 본문이 안 바뀌면
        # 구절도 안 바뀐다.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS vec_passage(slug TEXT, sha TEXT, idx INT, data BLOB, PRIMARY KEY(slug, idx))"
        )
        # 오염 판정 — 모델이 필요 없는 결정론 판정이라 vec 보다 싸고, 매 턴 도는 회수 경로가
        # 페이지마다 위협 정규식 전부를 다시 돌리던 자리다 (`store.poison_key`).
        conn.execute("CREATE TABLE IF NOT EXISTS clean(slug TEXT PRIMARY KEY, sha TEXT, verdict TEXT)")
        # 파생 계층의 운영 메타 — 어떤 임베더로 만든 벡터인가. 이게 없으면 모델을 갈아도
        # sha는 그대로라(본문이 안 바뀌었으므로) 낡은 차원의 벡터가 조용히 남는다.
        conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        return conn
    except Exception:
        conn.close()
        raise


def _is_corrupt_db_error(exc: sqlite3.DatabaseError) -> bool:
    """실제 파일 손상만 재생성 대상으로 판정 — locked/readonly/I/O 오류는 원본을 보존한다."""
    code = getattr(exc, "sqlite_errorcode", None)
    return code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}


def _db(d: str) -> sqlite3.Connection:
    """FTS 연결 — 손상 파일은 격리(삭제) 후 새로 만든다 (P1, "파생물은 복구 가능" 계약)."""
    path = os.path.join(d, DB)
    try:
        conn = _connect(path)
    except sqlite3.DatabaseError as e:
        if not _is_corrupt_db_error(e):
            raise
        io_sqlite.remove(path)
        conn = _connect(path)
    _chmod(path, 0o600)  # sqlite는 umask 기본(0644)으로 만든다 — 개인 메모리 파생물도 0600 (2차 리뷰 ④)
    return conn


def _fts_upsert(conn: sqlite3.Connection, d: str, slug: str) -> None:
    pg = _read(d, slug)
    if not pg:
        return
    meta, body = pg
    conn.execute("DELETE FROM fts WHERE slug = ?", (slug,))
    conn.execute(
        "INSERT INTO fts(slug, title, kind, body) VALUES(?,?,?,?)",
        (slug, meta.get("title", slug), _kind(meta), body),
    )
    _vec_upsert(conn, slug, meta, body)


def _vec_text(meta: dict, body: str) -> str:
    """임베딩 입력 — 제목에 가중(2회)해 짧은 페이지의 주제 신호를 살린다."""
    title = meta.get("title", "")
    return f"{title}\n{title}\n{body}".strip()


def _meta_get(conn: sqlite3.Connection, key: str) -> str:
    with contextlib.suppress(Exception):
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else ""
    return ""


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    with contextlib.suppress(Exception):
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def _vec_upsert(conn: sqlite3.Connection, slug: str, meta: dict, body: str) -> None:
    """시맨틱 활성 시에만 벡터 저장 (파생물). 본문 sha 불변이면 재임베딩 생략.
    비활성/실패는 무해 — 벡터 없이 query가 2경로로 fail-open 한다."""
    from .. import memory_semantic as sem

    if not sem.active():
        return
    text = _vec_text(meta, body)
    sha = hashlib.sha1(text.encode()).hexdigest()
    row = conn.execute("SELECT sha FROM vec WHERE slug = ?", (slug,)).fetchone()
    model = sem.loaded_model()
    if row and row[0] == sha and _meta_get(conn, "vec_model") == model:
        return  # 본문·임베더 무변경 — 재임베딩 비용 회피
    vector = sem.embed(text)
    if vector is None:
        return
    conn.execute(
        "INSERT INTO vec(slug, sha, dim, data) VALUES(?,?,?,?) "
        "ON CONFLICT(slug) DO UPDATE SET sha=excluded.sha, dim=excluded.dim, data=excluded.data",
        (slug, sha, len(vector), sem.pack(vector)),
    )
    if model:
        _meta_set(conn, "vec_model", model)


# ── 오염 판정 파생 칸 (clean) — 본문 sha 가 같으면 지난 판정 그대로 ────────────────────


def clean_verdicts(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    """접어 둔 오염 판정 — slug → (sha, verdict). verdict 빈 문자열이 "깨끗함"이다.

    위협 표가 개정되면 전부 버린다. 낡은 자로 잰 답을 새 자의 답이라고 말하지 않기 위해서다
    (`store.poison_ruleset`). 못 읽으면 빈 dict — 캐시가 없으면 정확한 경로가 돈다."""
    try:
        if _meta_get(conn, "clean_rules") != poison_ruleset():
            with conn:
                conn.execute("DELETE FROM clean")
                _meta_set(conn, "clean_rules", poison_ruleset())
            return {}
        return {
            row[0]: (str(row[1] or ""), str(row[2] or ""))
            for row in conn.execute("SELECT slug, sha, verdict FROM clean")
        }
    except Exception:
        return {}


def clean_remember(conn: sqlite3.Connection, rows: list[tuple[str, str, str]]) -> None:
    """새로 낸 판정을 접어 둔다 — (slug, sha, verdict). 실패는 무해(다음 턴에 다시 잰다)."""
    with contextlib.suppress(Exception):
        with conn:
            conn.executemany(
                "INSERT INTO clean(slug, sha, verdict) VALUES(?,?,?) "
                "ON CONFLICT(slug) DO UPDATE SET sha=excluded.sha, verdict=excluded.verdict",
                rows,
            )
            _meta_set(conn, "clean_rules", poison_ruleset())


# ── 구절 벡터 파생 칸 (vec_passage) — 본문 sha 가 같으면 재임베딩 없음 ──────────────────

PASSAGE_MODEL_KEY = "vec_passage_model"


def passage_vectors(conn: sqlite3.Connection, slug: str, sha: str) -> list[bytes]:
    """접어 둔 구절 벡터 BLOB — 본문 sha 가 다르면 빈 리스트. idx 순서 그대로."""
    try:
        rows = conn.execute(
            "SELECT data FROM vec_passage WHERE slug = ? AND sha = ? ORDER BY idx", (slug, sha)
        ).fetchall()
        return [row[0] for row in rows]
    except Exception:
        return []


def passage_remember(conn: sqlite3.Connection, entries: list[tuple[str, str, list[bytes]]]) -> None:
    """구절 벡터를 접어 둔다 — (slug, sha, 벡터들) 목록을 커밋 한 번에. 실패는 무해.

    같은 slug 의 옛 sha 행은 함께 사라진다 (칸이 페이지 개정마다 자라지 않는다)."""
    with contextlib.suppress(Exception):
        with conn:
            for slug, sha, blobs in entries:
                conn.execute("DELETE FROM vec_passage WHERE slug = ?", (slug,))
                conn.executemany(
                    "INSERT INTO vec_passage(slug, sha, idx, data) VALUES(?,?,?,?)",
                    [(slug, sha, idx, blob) for idx, blob in enumerate(blobs)],
                )


def passage_model(conn: sqlite3.Connection) -> str:
    """구절 벡터를 만든 임베더 이름. `vec_model`과 **따로** 적는다 — 여기서 같은 칸을 쓰면
    페이지 벡터의 재임베딩 게이트가 구절 캐시 때문에 통과해 낡은 벡터가 살아남는다."""
    return _meta_get(conn, PASSAGE_MODEL_KEY)


def passage_reset(conn: sqlite3.Connection, model: str) -> None:
    """임베더가 바뀌었다 — 다른 공간의 구절 벡터를 통째로 버리고 새 이름을 적는다."""
    with contextlib.suppress(Exception):
        with conn:
            conn.execute("DELETE FROM vec_passage")
            _meta_set(conn, PASSAGE_MODEL_KEY, model)


def _coverage_token(fingerprint: str, model: str, pages: int, vectors: int) -> str:
    """메모 키 — 형상·임베더·개수가 모두 같아야 지난 결론을 재사용한다."""
    return f"{fingerprint}:{model}:{pages}:{vectors}"


def vec_coverage(d: str | None = None) -> dict:
    """시맨틱 파생 인덱스가 정본을 실제로 덮는가 — **임베더를 로드하지 않는** 순수 판정.

    왜 이 함수가 필요한가 (26-07-29 실측): 이 기계의 개인 메모리는 페이지 2장에 vec 0행이었고,
    그런데도 `semantic status`는 "동작 중"이라고 말했다. 두 문장이 다 참이다 — 임베더는
    로드되고, 벡터는 없다. `active()`는 **임베더가 서는가**를 묻지 **회수에 기여하는가**를
    묻지 않기 때문이다. 그 간극에서 사용자는 매 질의마다 모델 로드 비용(~1초)을 내고 기여는
    0을 받는다.

    이건 남에게 지적한 것과 같은 형태의 결함이다: `memory_semantic` 독스트링이 "agentmemory는
    로컬 임베딩 기본이라 광고하고 실제론 OFF 였다 — 우리는 그대로 노출한다"고 적어 뒀는데,
    정직함이 한 층 얕은 데서 멈춰 있었다. 이 함수가 그 한 층이다.

    반환 = {pages, vectors, fresh, stale, orphan, coverage, model, ok}
      fresh  = 현재 본문 sha와 일치하는 벡터 (실제로 회수에 쓰이는 것)
      stale  = 벡터는 있는데 본문이 그 뒤 바뀐 것
      orphan = 정본에 없는 slug의 벡터 (prune 대상)
      coverage = fresh / pages  (페이지가 0이면 1.0 — 덮을 것이 없으면 결함도 없다)

    임베더를 안 부르는 것이 계약이다: 상태를 재느라 35초를 쓰면 그건 상태 계기가 아니다.

    **비용.** 정확한 판정은 페이지마다 본문을 읽어 sha를 다시 만든다 — 1,000 페이지에서 42ms
    다 (실측 26-07-29). 이 함수는 SessionStart 훅(`memory semantic
    nudge`)·lint·doctor·status가 부르므로 그 값을 매번 내면 계기가 자기가 지키는 것보다 비싸진다. 그래서 **정상 상태를
    메모**한다: 페이지 디렉터리의 stat 지문(이름·크기·mtime)이 그대로이고 임베더도 그대로면
    이미 확인한 결론을 그대로 돌려준다. 지문은 `os.scandir`이 이미 주는 값이라 읽기가 0 이다.

    메모하는 것은 **ok 상태뿐**이다. 고장 상태를 캐시하면 고친 뒤에도 고장이라고 말하게 되고,
    그건 이 함수가 고치려던 바로 그 병(계기가 실사와 어긋남)이다. 지문이 조금이라도 다르면
    정확한 경로로 떨어진다 — 캐시는 빠른 길이지 판정의 근거가 아니다."""
    d = d or memory_dir()
    pages = _pages(d)
    result = {
        "pages": len(pages),
        "vectors": 0,
        "fresh": 0,
        "stale": 0,
        "orphan": 0,
        "coverage": 1.0,
        "model": "",
        "model_mismatch": False,
        "ok": True,
    }
    try:
        conn = _db(d)
    except Exception:
        return result
    fingerprint = _pages_fingerprint(d)
    try:
        rows = dict(conn.execute("SELECT slug, sha FROM vec").fetchall())
        result["model"] = _meta_get(conn, "vec_model")
        memo = _meta_get(conn, "coverage_ok")
    except Exception:
        rows, memo = {}, ""
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    from .. import memory_semantic as sem

    current = sem.loaded_model()
    stored = str(result["model"])
    # 빠른 길 — 지난번에 "전부 덮였다"고 확인한 그 형상 그대로인가. 페이지를 한 장도 안 읽는다.
    if memo and fingerprint and memo == _coverage_token(fingerprint, stored, len(pages), len(rows)):
        result["vectors"] = len(rows)
        result["fresh"] = len(pages)
        result["coverage"] = 1.0
        result["ok"] = not (current and stored and current != stored)
        result["model_mismatch"] = not result["ok"]
        if result["model_mismatch"]:
            result["fresh"], result["stale"], result["coverage"] = 0, len(pages), 0.0
        return result

    fresh = stale = 0
    loaded = {slug: (meta, body) for slug, meta, body in _read_all_cached(d)}  # 읽기는 공유분에서
    for slug in pages:
        # 이름을 `stored`로 두지 않는다: 위에서 그건 **임베더 모델명**이고, 같은 이름을 쓰면
        # 루프가 그걸 sha로 덮어써서 아래 모델 대조가 항상 불일치가 된다 (26-07-29 실측 결함).
        stored_sha = rows.get(slug)
        if stored_sha is None:
            continue
        pg = loaded.get(slug)
        if pg and hashlib.sha1(_vec_text(*pg).encode()).hexdigest() == stored_sha:
            fresh += 1
        else:
            stale += 1
    # 임베더가 바뀌면 본문 sha는 그대로여도 벡터는 **다른 공간의 것**이다. 차원이 우연히
    # 같으면 코사인이 조용히 엉뚱한 값을 내므로(길이가 다를 때만 0을 돌려준다) sha 만으로는
    # 이 드리프트를 못 본다. 지금 로드된 모델이 있을 때만 대조한다 — 판정 때문에 모델을
    # 불러오지는 않는다 (`loaded_model()`은 로드를 유발하지 않는다).
    mismatch = bool(rows) and bool(current) and bool(stored) and current != stored
    if mismatch:
        stale += fresh
        fresh = 0
    result["vectors"] = len(rows)
    result["fresh"] = fresh
    result["stale"] = stale
    result["orphan"] = len(rows.keys() - set(pages))  # 집합 하나로 — 행마다 pages를 다시 해싱하지 않게
    result["coverage"] = 1.0 if not pages else round(fresh / len(pages), 4)
    result["model_mismatch"] = mismatch
    result["ok"] = fresh == len(pages) and not result["orphan"] and not mismatch
    # 정상 상태만 메모한다 (위 독스트링 참조 — 고장을 캐시하면 고친 뒤에도 고장이라 말한다).
    # 모델 불일치는 메모에 안 넣는다: 그건 형상이 아니라 **이 프로세스가 무엇을 로드했는가**라
    # 매 호출 다시 봐야 한다. 그래서 빠른 길도 이 판정만은 다시 한다.
    if result["ok"] and fingerprint:
        with contextlib.suppress(Exception):
            conn = _db(d)
            with conn:
                _meta_set(conn, "coverage_ok", _coverage_token(fingerprint, stored, len(pages), len(rows)))
            conn.close()
    return result


def reindex(d: str | None = None) -> int:
    """pages/ → state.db + index.md 전체 재생성. 손상 시 nuke-rebuild. 반환 = 페이지 수.

    회수 기록은 재생 대상이 아니라 **복원** 대상이다: DB 를 지우고 다시 만드는 길에서 색인은
    pages/ 에서 나오지만 사용 기록은 나올 데가 없다. 그래서 정본 `usage.json` 에서 되살린다
    (`memory.usage.hydrate`) — 그러지 않으면 손상 한 번에 90일 넘은 전 페이지가 일제히
    부패 후보로 뜬다."""
    d = ensure_home(d)
    with _lock(d):
        conn = None
        try:
            conn = _db(d)
            with conn:
                conn.execute("DELETE FROM fts")
                pages = _pages(d)
                for slug in pages:
                    _fts_upsert(conn, d, slug)
                _vec_prune(conn, pages)  # 소실 페이지의 벡터 파생물 정리
            conn.close()
        except sqlite3.DatabaseError as e:  # connect는 됐지만 쓰기 중 손상 — 파일 폐기 후 재구축
            if conn is not None:
                with contextlib.suppress(Exception):
                    conn.close()
            if not _is_corrupt_db_error(e):
                raise
            io_sqlite.remove(os.path.join(d, DB))
            conn = _db(d)
            with conn:
                pages = _pages(d)
                for slug in pages:
                    _fts_upsert(conn, d, slug)
                _vec_prune(conn, pages)
            conn.close()
        from .usage import flush as _usage_flush
        from .usage import hydrate as _usage_hydrate

        _usage_hydrate(d)  # 정본에 접어 둔 회수 기록을 되살린다 (파생 소실 복구)
        _usage_flush(d)  # 그 뒤 정본을 현재 계수로 맞춘다 — 지워진 페이지의 행이 여기서 빠진다
        write_index(d)
        return len(_pages(d))


def _vec_prune(conn: sqlite3.Connection, pages: list[str]) -> None:
    """정본에 없는 slug의 파생 행 제거 — 벡터·구절 벡터·오염 판정 고아 청소 (fail-open).

    셋 다 slug 로 정본에 매달린 파생물이라 청소 시점이 같다. 남겨 둬도 판정을 바꾸지는
    않지만(전부 sha 로 다시 대조한다) 지운 페이지의 흔적이 파생 칸에 영영 남는다."""
    keep = set(pages)
    for select, delete in (
        ("SELECT slug FROM vec", "DELETE FROM vec WHERE slug = ?"),
        ("SELECT slug FROM vec_passage", "DELETE FROM vec_passage WHERE slug = ?"),
        ("SELECT slug FROM clean", "DELETE FROM clean WHERE slug = ?"),
    ):
        with contextlib.suppress(Exception):
            stale = {row[0] for row in conn.execute(select).fetchall() if row[0] not in keep}
            for slug in stale:
                conn.execute(delete, (slug,))


def usage_stats(d: str | None = None) -> list[dict]:
    """usage 테이블 읽기 전용 스냅샷 — 회수 빈도 내림차순. 대시보드·분석용 순수 읽기.

    행마다 네 값을 준다: `uses`/`last_used` 는 사람이 부른 검색, `exposures`/`last_exposed` 는
    자동 주입이다 (`memory.usage`). 옛 표면이 보던 `uses`는 이름도 자리도 그대로고, 뜻만
    좁아졌다 — 자동 주입이 더는 섞이지 않는다."""
    from .usage import merged

    d = d or memory_dir()
    rows = merged(d)  # 파일과 DB 중 큰 쪽 — 표면이 판정과 다른 수를 말하지 않게
    return [{"slug": slug, **rows[slug]} for slug in sorted(rows, key=lambda s: (-int(rows[s]["uses"] or 0), s))]
