"""에피소드 계층 — 대화 원문(turns.jsonl)과 승격 메모리 '사이'의 파생 검색·회수면.

대화 원문 ── 에피소드 인덱스(FTS5, 파생) ── 관련 구간만 비권위 주입
   └ 퀘스트 귀속(quest 필드)              └ 승격은 기존 ingest 승인 게이트로만

권위는 여기 없다 — Git·퀘스트 로그·게이트 증거가 소유하고, 주입 블록은 힌트로만 표기된다.
인덱스는 파생물: 지워도·손상돼도 turns.jsonl 에서 재생성된다. 원문이 줄었으면(보존 정리)
증분 오프셋을 신뢰하지 않고 전체 재구축한다. 모든 실패는 fail-open — 검색·주입 불능이
세션을 막지 않는다.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3

from .turn_store import _dir, store_path

_DB = "episodes.db"
RRF_K = 60  # memory.recall 과 동일 — 순위 융합 표준 상수
EPISODE_BUDGET = 700  # chars — 턴마다 붙을 수 있는 주입 블록 상한 (개인 recall 900 보다 작게)
_EXCERPT_WIDTH = 160
_EXCLUDE_TAIL = 3  # 최근 턴은 라이브 history 가 이미 나른다 — 재주입 중복 차단


def _db_path(root: str) -> str:
    return os.path.join(_dir(root), _DB)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS ep USING fts5"
            "(seq UNINDEXED, ts UNINDEXED, quest UNINDEXED, sid UNINDEXED,"
            " request, response, tokenize='trigram')"
        )
        conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        return conn
    except Exception:
        conn.close()
        raise


def _db(root: str) -> sqlite3.Connection:
    """파생 인덱스 연결 — 손상 파일은 격리 후 재생성 (memory.index 와 동일 계약)."""
    path = _db_path(root)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    try:
        conn = _connect(path)
    except sqlite3.DatabaseError as e:
        if getattr(e, "sqlite_errorcode", None) not in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
            raise
        with contextlib.suppress(OSError):
            os.remove(path)
        conn = _connect(path)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)  # sqlite umask 기본은 0644 — 세션 파생물도 소유자 전용
    return conn


def _meta_get(conn: sqlite3.Connection, key: str, default: int = 0) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    try:
        return int(row[0]) if row else default
    except TypeError, ValueError:
        return default


def _meta_set(conn: sqlite3.Connection, key: str, value: int) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def sync(root: str) -> int:
    """turns.jsonl → episodes.db 증분 동기화. 반환 = 신규 인덱스 턴 수.

    오프셋은 '완결 라인'까지만 전진한다 — 꼬리의 절단 라인은 다음 sync 가 다시 본다.
    원문이 오프셋보다 작아졌으면(prune·수동 삭제) 전체 재구축한다."""
    try:
        src = store_path(root)
        try:
            size = os.path.getsize(src)
        except OSError:
            size = 0
        conn = _db(root)
        try:
            offset = _meta_get(conn, "offset")
            seq = _meta_get(conn, "seq")
            if size < offset:  # 원문 축소 — 증분 신뢰 불가, 파생물 전체 재구축
                with conn:
                    conn.execute("DELETE FROM ep")
                    _meta_set(conn, "offset", 0)
                    _meta_set(conn, "seq", 0)
                offset, seq = 0, 0
            if size == offset:
                return 0
            with open(src, "rb") as f:
                f.seek(offset)
                raw = f.read()
            consumed = len(raw)
            if not raw.endswith(b"\n"):  # 절단 꼬리 — 완결 라인까지만 소비
                cut = raw.rfind(b"\n") + 1
                raw, consumed = raw[:cut], cut
            added = 0
            with conn:
                for line in raw.decode("utf-8", errors="replace").splitlines():
                    seq += 1
                    try:
                        d = json.loads(line)
                        q, a = str(d["request"]), str(d["response"])
                    except ValueError, KeyError, TypeError:
                        continue  # 손상 라인 — seq 는 전진 (라인 위치 = 안정 좌표)
                    conn.execute(
                        "INSERT INTO ep(seq, ts, quest, sid, request, response) VALUES(?,?,?,?,?,?)",
                        (seq, float(d.get("ts") or 0.0), str(d.get("quest") or ""), str(d.get("sid") or ""), q, a),
                    )
                    added += 1
                _meta_set(conn, "offset", offset + consumed)
                _meta_set(conn, "seq", seq)
            return added
        finally:
            conn.close()
    except Exception:
        return 0  # fail-open — 인덱스 불능은 검색이 빈 결과로 감내


def _words(text: str) -> list[str]:
    return list(dict.fromkeys(w.lower() for w in re.split(r"[^\w가-힣%-]+", text) if len(w) >= 2))


def _excerpt(text: str, phrase: str, words: list[str], width: int = _EXCERPT_WIDTH) -> str:
    """관련 '구간'만 골라낸다 — 전문 주입 금지 계약의 핵심. 매칭 지점 중심 윈도우."""
    low = text.lower()
    needle = phrase if phrase and phrase in low else next((w for w in words if w in low), "")
    i = low.find(needle) if needle else 0
    start = max(i - width // 4, 0)
    seg = text[start : start + width].strip()
    return re.sub(r"\s+", " ", seg)


def search(root: str, text: str, k: int = 5, quest: str | None = None) -> list[dict]:
    """세션 원문 전문 검색 (0-LLM) — FTS trigram + lexical 스캔 2-스트림 RRF.

    반환 hit = {seq, ts, quest, sid, request, excerpt, score}. excerpt 는 응답(우선)
    또는 요청에서 고른 관련 구간이다. quest 를 주면 해당 퀘스트 귀속 턴만 남긴다."""
    try:
        sync(root)
        k = max(1, min(int(k), 200))
        conn = _db(root)
        try:
            where, args = ("WHERE quest = ?", [quest]) if quest else ("", [])
            rows = conn.execute(
                f"SELECT seq, ts, quest, sid, request, response FROM ep {where}",  # noqa: S608 — where 는 상수 2형
                args,
            ).fetchall()
            fts_order: list[tuple[int, float]] = []
            terms = [w for w in re.split(r"\s+", text.strip()) if len(w) >= 3]
            if terms:
                match = " OR ".join('"' + w.replace('"', '""') + '"' for w in terms)
                with contextlib.suppress(Exception):  # MATCH 문법 오류 등 — 스캔 스트림만으로 진행
                    fts_order = [
                        (int(s), float(b))
                        for s, b in conn.execute(
                            "SELECT seq, bm25(ep) FROM ep WHERE ep MATCH ? ORDER BY bm25(ep) LIMIT ?",
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
    phrase = text.strip().lower()
    words = _words(text)

    def _scan_score(r: tuple) -> int:
        hay = (str(r[4]) + "\n" + str(r[5])).lower()
        return sum(1 for w in words if w in hay) + (3 if phrase and phrase in hay else 0)

    scan_order = sorted(
        ((seq, float(s)) for seq, r in by_seq.items() if (s := _scan_score(r)) > 0),
        key=lambda p: -p[1],
    )
    fts_order = [(seq, b) for seq, b in fts_order if seq in by_seq]  # quest 필터 존중

    rrf: dict[int, float] = {}

    def _add(ordered: list[tuple[int, float]]) -> None:
        rank, prev = 0, None
        for i, (seq, s) in enumerate(ordered):
            if s != prev:
                rank, prev = i + 1, s
            rrf[seq] = rrf.get(seq, 0.0) + 1.0 / (RRF_K + rank)

    _add(fts_order)
    _add(scan_order)
    if not rrf:
        return []

    hits: list[dict] = []
    for seq in sorted(rrf, key=lambda s: (-rrf[s], -s))[:k]:  # 동률 = 최신 턴 우선
        r = by_seq[seq]
        req, resp = str(r[4]), str(r[5])
        # 발췌는 항상 응답에서 — 질의가 요청문과 겹치는 건 당연하고, 주입 가치는 그때의 답이다.
        # 응답 내 매칭이 없으면 응답 머리 구간 (_excerpt 가 i=0 폴백).
        src = resp
        hits.append(
            {
                "seq": seq,
                "ts": float(r[1] or 0.0),
                "quest": str(r[2] or ""),
                "sid": str(r[3] or ""),
                "request": re.sub(r"\s+", " ", req)[:120],
                "excerpt": _excerpt(src, phrase, words),
                "score": round(rrf[seq], 4),
            }
        )
    return hits


def turns_for_quest(root: str, quest: str) -> list[dict]:
    """퀘스트 귀속 턴 전부 — 퀘스트 로그(권위)에서 대화 맥락(비권위)으로 건너가는 다리."""
    try:
        sync(root)
        conn = _db(root)
        try:
            rows = conn.execute(
                "SELECT seq, ts, request, response FROM ep WHERE quest = ? ORDER BY seq", (quest,)
            ).fetchall()
        finally:
            conn.close()
        return [{"seq": int(s), "ts": float(t or 0.0), "request": q, "response": a} for s, t, q, a in rows]
    except Exception:
        return []


def stats(root: str) -> dict:
    """인덱스 현황 — 턴 수·퀘스트 귀속 수·원문 크기. 대시보드/CLI 읽기 전용."""
    try:
        sync(root)
        conn = _db(root)
        try:
            total = conn.execute("SELECT count(*) FROM ep").fetchone()[0]
            quests = conn.execute("SELECT count(DISTINCT quest) FROM ep WHERE quest != ''").fetchone()[0]
        finally:
            conn.close()
        size = 0
        with contextlib.suppress(OSError):
            size = os.path.getsize(store_path(root))
        return {"turns": int(total), "quests": int(quests), "raw_bytes": int(size)}
    except Exception:
        return {"turns": 0, "quests": 0, "raw_bytes": 0}


def _neutralize(s: str) -> str:
    return s.replace("<", "‹").replace(">", "›")


def episode_note(request: str, root: str, k: int = 3) -> str:
    """요청 관련 과거 세션 구간의 비권위 주입 블록 (0-LLM 결정론).

    개인 recall(승격 메모리)과 달리 저장 게이트가 없는 원문이므로 주입 시점에
    scan_threats 로 오염 구간을 걸러낸다. 최근 _EXCLUDE_TAIL 턴은 라이브 history 가
    이미 싣고 있어 제외. 무적중·킬스위치 off·실패 = 빈 문자열 (무변화)."""
    try:
        from ..memory.policy import inject_enabled, scan_threats

        if not inject_enabled():
            return ""
        hits = search(root, request, k=k + _EXCLUDE_TAIL)
        if not hits:
            return ""
        top = max(h["seq"] for h in hits)
        try:
            conn = _db(root)
            try:
                latest = _meta_get(conn, "seq")
            finally:
                conn.close()
        except Exception:
            latest = top
        hits = [h for h in hits if h["seq"] <= latest - _EXCLUDE_TAIL][:k]
        prefix = (
            '\n\n<episode-recall scope="session">\n'
            "과거 세션 관련 구간 (비권위 참고 — 완료 증거 아님. 보존 가치가 있으면 asgard memory ingest):\n"
        )
        suffix = "\n</episode-recall>"
        rows: list[str] = []
        for h in hits:
            if scan_threats(h["request"], h["excerpt"]):
                continue  # 원문 유래 오염 구간 — 주입 제외
            head = _neutralize(h["request"])[:60]
            body = _neutralize(h["excerpt"])[:200]
            tag = f" quest:{h['quest'][:24]}" if h["quest"] else ""
            row = f"- [t{h['seq']}{tag}] {head} → {body}"
            if len(prefix + "\n".join([*rows, row]) + suffix) > EPISODE_BUDGET:
                break
            rows.append(row)
        if not rows:
            return ""
        return prefix + "\n".join(rows) + suffix
    except Exception:
        return ""  # fail-open


# ── 의미 보존 컴팩션 (0-LLM 발췌) — 긴 응답을 예산 내로 줄이되 신호 문장을 우선 보존 ──

_SIGNAL = re.compile(
    r"[\w.\-]+/[\w./\-]+"  # 파일 경로
    r"|`[^`]+`"  # 코드 스팬
    r"|\b\d[\d.,:%]*\b"  # 수치
    r"|PASS|FAIL|ESCALATE|커밋|오류|실패|완료|검증|경고|⚠",
)


def compact_text(text: str, budget: int = 500) -> str:
    """예산 초과 텍스트의 의미 보존 발췌 — 경로·수치·판정어를 품은 줄을 우선 남긴다.

    맹목 접두 절단(text[:budget])의 대체: 결론·증거가 응답 꼬리에 몰리는 형태에서
    신호 유실을 줄인다. 예산 이내면 원문 그대로 — 압축은 초과분에만 개입한다."""
    if len(text) <= budget:
        return text
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text[:budget]
    last = len(lines) - 1
    scored = sorted(
        range(len(lines)),
        key=lambda i: -(len(_SIGNAL.findall(lines[i])) * 2 + (3 if i == 0 else 0) + (1 if i == last else 0)),
    )
    keep: set[int] = set()
    used = 0
    for i in scored:
        cost = min(len(lines[i]), 200) + 2  # 초장문 줄도 200자 발췌로만 청구
        if used + cost > budget:
            continue
        keep.add(i)
        used += cost
    if not keep:
        return text[:budget]
    out: list[str] = []
    prev = -1
    for i in sorted(keep):
        if prev >= 0 and i != prev + 1:
            out.append("…")
        out.append(lines[i][:200])
        prev = i
    return "\n".join(out)[:budget]
