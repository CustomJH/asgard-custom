"""방출 보관소 — 압축이 잘라낸 구간의 검색 가능한 사본 (후긴 T4).

요약 압축의 구조적 결함은 손실이 예측 불가라는 점이다. 무엇이 남고 무엇이 사라졌는지
아무도 모르고, 사라진 걸 되찾을 방법도 없다. 그래서 후긴은 중간 구간을 '태우지 않고
옮긴다' — 요약은 컨텍스트에 남기고, 원문은 여기로 내려보낸 뒤 필요할 때 `context_recall`
툴로 되짚는다. 압축이 파괴가 아니라 이동이 되는 지점이다.

에피소드 계층(episodes.py)과 층이 다르다:
  episodes  완결 턴(turns.jsonl) 파생 — 세션들 '사이', Heimdall 층 문답
  evicted   압축이 잘라낸 전송 히스토리 — 세션 '안', 툴 루프 내부의 읽기·명령·오류
같은 발췌·RRF 기계를 쓰지만(중복 구현 금지) 원본과 수명이 다르므로 저장소를 나눈다.

권위는 여기 없다 — Git·퀘스트 로그·게이트 증거가 소유한다. 이 인덱스는 편의 사본이고,
지워도 세션은 계속 돈다. 모든 실패는 fail-open.

저장소: ~/.asgard/sessions/<root-sha16>/evicted.db (0600, FTS5 trigram)
"""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
import time

from .. import io_sqlite
from .episodes import RRF_K, _excerpt, _words
from .turn_store import _dir

_DB = "evicted.db"
_MAX_ROWS = 20_000  # 보존 상한 — 초과분은 오래된 순으로 버린다 (편의 사본은 무한 성장 금지)
_TEXT_CAP = 6_000  # 행 1건 본문 상한 — 통짜 보관이 목적이 아니라 되짚기가 목적
_RECALL_BUDGET = 4_000  # 툴 1회 응답 상한 (chars) — 회수가 새 압축 압력이 되면 안 된다


def db_path(root: str) -> str:
    return os.path.join(_dir(root), _DB)


def _connect(path: str) -> sqlite3.Connection:
    # 접속 계약(WAL·busy_timeout)은 `io_sqlite` 가 진다. 이 파일이 그 계약을 필요로 하는 이유:
    # 보관은 세션마다 도는 압축이 부르는데(`huginn._archive`), 웨이브 워커와 편대 자식은 세션을
    # 스레드로 여럿 띄우면서 root 가 같다 — 같은 evicted.db 에 쓰기 여럿이 동시에 들어온다.
    conn = io_sqlite.connect(path)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS ev USING fts5"
            "(seq UNINDEXED, ts UNINDEXED, sid UNINDEXED, role UNINDEXED, body, tokenize='trigram')"
        )
        return conn
    except Exception:
        conn.close()
        raise


def _db(root: str) -> sqlite3.Connection:
    """손상 파일은 격리 후 재생성 — episodes/memory 인덱스와 동일 계약."""
    path = db_path(root)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    try:
        conn = _connect(path)
    except sqlite3.DatabaseError as e:
        if getattr(e, "sqlite_errorcode", None) not in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
            raise
        io_sqlite.remove(path)
        conn = _connect(path)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return conn


def archive(root: str, rows: list[tuple[str, str]], *, session_id: str = "") -> int:
    """방출된 (role, text) 행들을 보관한다. 반환 = 실제 기록 건수.

    text는 호출자가 이미 편집(redact)한 상태로 넘긴다 — 이 층은 저장만 한다."""
    if not rows:
        return 0
    try:
        conn = _db(root)
        try:
            # 읽고 나서 쓰는 블록이라 `io_sqlite.writing` 이다 — `with conn:` 은 이 자리에서
            # 세션 절반을 조용히 잃었다 (그 이유는 그 함수의 독스트링에). `max(seq)` 를 락 안에서
            # 읽는 것도 같은 몫이다: 밖에서 읽으면 두 세션이 같은 top 을 보고 같은 seq 를 쓴다
            # (ev 는 fts5 라 그 중복을 막아 줄 제약이 없다).
            written = 0
            with io_sqlite.writing(conn):
                top = conn.execute("SELECT max(seq) FROM ev").fetchone()[0] or 0
                now = time.time()
                for role, text in rows:
                    body = (text or "").strip()
                    if not body:
                        continue
                    top += 1
                    written += 1
                    conn.execute(
                        "INSERT INTO ev(seq, ts, sid, role, body) VALUES(?,?,?,?,?)",
                        (top, now, str(session_id or ""), str(role or ""), body[:_TEXT_CAP]),
                    )
                total = conn.execute("SELECT count(*) FROM ev").fetchone()[0]
                if total > _MAX_ROWS:  # 오래된 순으로 버린다 — 되짚기 가치는 최신에 몰려 있다
                    conn.execute("DELETE FROM ev WHERE seq <= ?", (top - _MAX_ROWS,))
            return written
        finally:
            conn.close()
    except Exception:
        return 0  # fail-open — 보관 실패가 압축을 막지 않는다


def recall(root: str, query: str, k: int = 5) -> list[dict]:
    """방출 구간 검색 — FTS trigram + lexical 스캔 2-스트림 RRF (episodes와 동일 기계).

    반환 hit = {seq, ts, role, excerpt, score}."""
    try:
        k = max(1, min(int(k), 50))
        conn = _db(root)
        try:
            rows = conn.execute("SELECT seq, ts, role, body FROM ev").fetchall()
            fts_order: list[tuple[int, float]] = []
            terms = [w for w in re.split(r"\s+", query.strip()) if len(w) >= 3]
            if terms:
                match = " OR ".join('"' + w.replace('"', '""') + '"' for w in terms)
                with contextlib.suppress(Exception):
                    fts_order = [
                        (int(s), float(b))
                        for s, b in conn.execute(
                            "SELECT seq, bm25(ev) FROM ev WHERE ev MATCH ? ORDER BY bm25(ev) LIMIT ?",
                            (match, k * 3),
                        ).fetchall()
                    ]
        finally:
            conn.close()
    except Exception:
        return []

    if not rows:
        return []
    by_seq = {int(r[0]): r for r in rows}
    phrase = query.strip().lower()
    words = _words(query)
    fts_order = [(seq, b) for seq, b in fts_order if seq in by_seq]

    scan_order = sorted(
        (
            (seq, float(score))
            for seq, r in by_seq.items()
            if (score := sum(1 for w in words if w in str(r[3]).lower()) + (3 if phrase in str(r[3]).lower() else 0))
            > 0
        ),
        key=lambda p: -p[1],
    )

    rrf: dict[int, float] = {}

    def _add(ordered: list[tuple[int, float]]) -> None:
        rank, prev = 0, None
        for i, (seq, score) in enumerate(ordered):
            if score != prev:
                rank, prev = i + 1, score
            rrf[seq] = rrf.get(seq, 0.0) + 1.0 / (RRF_K + rank)

    _add(fts_order)
    _add(scan_order)
    if not rrf:
        return []
    hits = []
    for seq in sorted(rrf, key=lambda s: (-rrf[s], -s))[:k]:  # 동률 = 최신 우선
        r = by_seq[seq]
        hits.append(
            {
                "seq": seq,
                "ts": float(r[1] or 0.0),
                "role": str(r[2] or ""),
                "excerpt": _excerpt(str(r[3]), phrase, words, width=320),
                "score": round(rrf[seq], 4),
            }
        )
    return hits


def stats(root: str) -> dict:
    try:
        conn = _db(root)
        try:
            total = conn.execute("SELECT count(*) FROM ev").fetchone()[0]
        finally:
            conn.close()
        size = 0
        with contextlib.suppress(OSError):
            size = os.path.getsize(db_path(root))
        return {"rows": int(total), "bytes": int(size)}
    except Exception:
        return {"rows": 0, "bytes": 0}


def clear(root: str) -> None:
    """세션 경계·수동 초기화용. 파생물이므로 삭제는 언제나 안전하다.

    WAL 곁 파일까지 같이 지우는 것은 `io_sqlite.remove` 가 진다 — 본체만 지우면 아직
    체크포인트되지 않은 방출 구간이 `-wal` 에 남는다."""
    io_sqlite.remove(db_path(root))


# ── 툴 표면 ─────────────────────────────────────────────────────────────────

RECALL_TOOL = {
    "name": "context_recall",
    "description": (
        "Search the spans of THIS session that context compaction removed from the transcript, "
        "and get the original text back. Use it when the handoff summary mentions something "
        "without the detail you need — an exact error string, a command you already ran, a file "
        "you already read, a value you already computed — instead of re-running the work. "
        "Returns nothing when no compaction has happened yet."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for: an error fragment, file path, command, or topic.",
            },
            "limit": {"type": "integer", "description": "Max spans to return (default 5, max 20)."},
        },
        "required": ["query"],
    },
}


def run_recall(root: str, tool_input: dict) -> str:
    """context_recall 핸들러 — 방출 구간 발췌를 예산 내로 돌려준다."""
    query = str(tool_input.get("query") or "").strip()
    if not query:
        return "query is required."
    try:
        limit = int(tool_input.get("limit") or 5)
    except TypeError, ValueError:
        limit = 5
    hits = recall(root, query, k=max(1, min(limit, 20)))
    if not hits:
        total = stats(root)["rows"]
        if not total:
            return "No compacted spans yet — the full transcript is still in context."
        return f"No match for {query!r} among {total} compacted span(s)."
    lines = [f"Recovered {len(hits)} compacted span(s) — original text, not a summary:"]
    for hit in hits:
        row = f"- [{hit['role']} #{hit['seq']}] {hit['excerpt']}"
        if sum(len(line) for line in lines) + len(row) > _RECALL_BUDGET:
            lines.append("- ...[truncated — narrow the query for more]")
            break
        lines.append(row)
    return "\n".join(lines)
