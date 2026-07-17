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


def _vec_upsert(conn: sqlite3.Connection, slug: str, meta: dict, body: str) -> None:
    """시맨틱 활성 시에만 벡터 저장 (파생물). 본문 sha 불변이면 재임베딩 생략.
    비활성/실패는 무해 — 벡터 없이 query 가 2경로로 fail-open 한다."""
    from .. import memory_semantic as sem

    if not sem.active():
        return
    text = _vec_text(meta, body)
    sha = hashlib.sha1(text.encode()).hexdigest()
    row = conn.execute("SELECT sha FROM vec WHERE slug = ?", (slug,)).fetchone()
    if row and row[0] == sha:
        return  # 본문 무변경 — 재임베딩 비용 회피
    vector = sem.embed(text)
    if vector is None:
        return
    conn.execute(
        "INSERT INTO vec(slug, sha, dim, data) VALUES(?,?,?,?) "
        "ON CONFLICT(slug) DO UPDATE SET sha=excluded.sha, dim=excluded.dim, data=excluded.data",
        (slug, sha, len(vector), sem.pack(vector)),
    )


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
