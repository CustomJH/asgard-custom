"""파생 계층 — index.md 카탈로그 + state.db(FTS5·vec·usage). 지워도 pages/ 에서 재생성된다."""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3

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
    _read,
    ensure_home,
)

# ── index.md — 카탈로그 (파생: pages/ 에서 전체 재생성) ──────────────────────────


def _index_row(slug: str, meta: dict, body: str) -> str:
    return f"- [{meta.get('title', slug)}](pages/{slug}.md) `{_kind(meta)}` — {_desc(meta, body)}"


def build_index(d: str) -> str:
    lines = ["# Memory Index", ""]
    for slug in _pages(d):
        pg = _read(d, slug)
        if pg:
            lines.append(_index_row(slug, *pg))
    return "\n".join(lines) + "\n"


def write_index(d: str) -> str:
    text = build_index(d)
    _atomic_write(os.path.join(d, INDEX), text)
    # index.md 는 주입면이라 예산에 묶여 있다. 예산 밖 전체 목차는 maps/ 가 진다 —
    # 같은 파생 시점에 같이 갱신돼야 vault 를 열었을 때 목차가 거짓말하지 않는다.
    with contextlib.suppress(Exception):  # 파생 목차 실패가 지식 쓰기를 막지 않는다
        from .vault import write_maps

        write_maps(d)
    return text


# ── FTS5 파생 인덱스 (state.db) — 지워도·손상돼도 reindex 로 복원 ─────────────────


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5"
            "(slug UNINDEXED, title, kind UNINDEXED, body, tokenize='trigram')"
        )
        # usage 는 운영 메타 (지식 아님) — 페이지 파일을 더럽히지 않고 여기서만 추적
        conn.execute("CREATE TABLE IF NOT EXISTS usage(slug TEXT PRIMARY KEY, uses INT DEFAULT 0, last_used TEXT)")
        # vec = 시맨틱 스트림 파생물 (옵트인). sha 로 본문 변경만 재임베딩, data 는 float32 BLOB.
        # 지워도·모델 바뀌어도 정본(pages/)에서 reindex 로 복원 — 파일이 여전히 정본이다.
        conn.execute("CREATE TABLE IF NOT EXISTS vec(slug TEXT PRIMARY KEY, sha TEXT, dim INT, data BLOB)")
        # 파생 계층의 운영 메타 — 어떤 임베더로 만든 벡터인가. 이게 없으면 모델을 갈아도
        # sha 는 그대로라(본문이 안 바뀌었으므로) 낡은 차원의 벡터가 조용히 남는다.
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
        with contextlib.suppress(OSError):
            os.remove(path)
        conn = _connect(path)
    _chmod(path, 0o600)  # sqlite 는 umask 기본(0644)으로 만든다 — 개인 메모리 파생물도 0600 (2차 리뷰 ④)
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
    비활성/실패는 무해 — 벡터 없이 query 가 2경로로 fail-open 한다."""
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


def vec_coverage(d: str | None = None) -> dict:
    """시맨틱 파생 인덱스가 정본을 실제로 덮는가 — **임베더를 로드하지 않는** 순수 판정.

    왜 이 함수가 필요한가 (26-07-29 실측): 이 기계의 개인 메모리는 페이지 2장에 vec 0행이었고,
    그런데도 `semantic status` 는 "동작 중"이라고 말했다. 두 문장이 다 참이다 — 임베더는
    로드되고, 벡터는 없다. `active()` 는 **임베더가 서는가**를 묻지 **회수에 기여하는가**를
    묻지 않기 때문이다. 그 간극에서 사용자는 매 질의마다 모델 로드 비용(~1초)을 내고 기여는
    0을 받는다.

    이건 남에게 지적한 것과 같은 형태의 결함이다: `memory_semantic` 독스트링이 "agentmemory 는
    로컬 임베딩 기본이라 광고하고 실제론 OFF 였다 — 우리는 그대로 노출한다"고 적어 뒀는데,
    정직함이 한 층 얕은 데서 멈춰 있었다. 이 함수가 그 한 층이다.

    반환 = {pages, vectors, fresh, stale, orphan, coverage, model, ok}
      fresh  = 현재 본문 sha 와 일치하는 벡터 (실제로 회수에 쓰이는 것)
      stale  = 벡터는 있는데 본문이 그 뒤 바뀐 것
      orphan = 정본에 없는 slug 의 벡터 (prune 대상)
      coverage = fresh / pages  (페이지가 0이면 1.0 — 덮을 것이 없으면 결함도 없다)

    임베더를 안 부르는 것이 계약이다: 상태를 재느라 35초를 쓰면 그건 상태 계기가 아니다."""
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
    try:
        rows = dict(conn.execute("SELECT slug, sha FROM vec").fetchall())
        result["model"] = _meta_get(conn, "vec_model")
    except Exception:
        rows = {}
    finally:
        with contextlib.suppress(Exception):
            conn.close()
    fresh = 0
    stale = 0
    for slug in pages:
        stored = rows.get(slug)
        if stored is None:
            continue
        pg = _read(d, slug)
        if pg and hashlib.sha1(_vec_text(*pg).encode()).hexdigest() == stored:
            fresh += 1
        else:
            stale += 1
    # 임베더가 바뀌면 본문 sha 는 그대로여도 벡터는 **다른 공간의 것**이다. 차원이 우연히
    # 같으면 코사인이 조용히 엉뚱한 값을 내므로(길이가 다를 때만 0 을 돌려준다) sha 만으로는
    # 이 드리프트를 못 본다. 지금 로드된 모델이 있을 때만 대조한다 — 판정 때문에 모델을
    # 불러오지는 않는다 (`loaded_model()` 은 로드를 유발하지 않는다).
    from .. import memory_semantic as sem

    current = sem.loaded_model()
    stored = str(result["model"])
    mismatch = bool(rows) and bool(current) and bool(stored) and current != stored
    if mismatch:
        stale += fresh
        fresh = 0
    result["vectors"] = len(rows)
    result["fresh"] = fresh
    result["stale"] = stale
    result["orphan"] = sum(1 for slug in rows if slug not in set(pages))
    result["coverage"] = 1.0 if not pages else round(fresh / len(pages), 4)
    result["model_mismatch"] = mismatch
    result["ok"] = fresh == len(pages) and not result["orphan"] and not mismatch
    return result


def reindex(d: str | None = None) -> int:
    """pages/ → state.db + index.md 전체 재생성. usage 보존, 손상 시 nuke-rebuild. 반환 = 페이지 수."""
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
        except sqlite3.DatabaseError as e:  # connect 는 됐지만 쓰기 중 손상 — 파일 폐기 후 재구축
            if conn is not None:
                with contextlib.suppress(Exception):
                    conn.close()
            if not _is_corrupt_db_error(e):
                raise
            with contextlib.suppress(OSError):
                os.remove(os.path.join(d, DB))
            conn = _db(d)
            with conn:
                pages = _pages(d)
                for slug in pages:
                    _fts_upsert(conn, d, slug)
                _vec_prune(conn, pages)
            conn.close()
        write_index(d)
        return len(_pages(d))


def _vec_prune(conn: sqlite3.Connection, pages: list[str]) -> None:
    """정본에 없는 slug 의 벡터 행 제거 — 파생물 고아 청소 (fail-open)."""
    with contextlib.suppress(Exception):
        keep = set(pages)
        stale = [r[0] for r in conn.execute("SELECT slug FROM vec").fetchall() if r[0] not in keep]
        for slug in stale:
            conn.execute("DELETE FROM vec WHERE slug = ?", (slug,))


def usage_stats(d: str | None = None) -> list[dict]:
    """usage 테이블 읽기 전용 스냅샷 — slug·uses·last_used, 회수 빈도 내림차순.
    파생물(state.db)이라 없으면 빈 리스트 (fail-open). 대시보드·분석용 순수 읽기."""
    d = d or memory_dir()
    try:
        conn = _db(d)
        rows = conn.execute("SELECT slug, uses, last_used FROM usage ORDER BY uses DESC, slug").fetchall()
        conn.close()
    except Exception:
        return []
    return [{"slug": r[0], "uses": int(r[1] or 0), "last_used": r[2]} for r in rows]
