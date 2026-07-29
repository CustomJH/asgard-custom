"""문서 로컬 레인 — 그래프가 감당하지 못하는 큰 문서를 정본과 파생 인덱스로 나눠 나른다.

왜 이 레인이 생겼는가 (26-07-28 3차 실서버 계측, tests/load/README.md).

원인은 오래 "링크 밀도"로 읽혔지만 **틀렸다**. 버려도 되는 뱅크를 새로 파서 변수를 갈라
재 보니 그래프 단계는 0.003s 이고, 회수 시간의 99%는 CPU 크로스 인코더 리랭크였다.
비용은 **후보 수 × 후보 길이**이고, 한국어는 같은 글자 수에서 토큰이 많아 그만큼 비싸다
(같은 3노드·9링크에서 영어 5~7s 대 한국어 20~21s). 링크를 7,260개까지 늘린 구성이 오히려
가장 건강했다 — 밀도는 변수가 아니었다.

바꿀 수 있는 것은 다 바꿔 봤다. 청크를 줄여 단위가 회수 예산에 들어오게 하니 적중이
0→10 으로 살아났지만, 지연은 문서 96,000자에서 41~67s 로 평평했다 — 후보가 늘어난 만큼
하나가 싸져 총합이 그대로다. 즉 **큰 한국어 문서는 어떤 청크 크기로도 이 배포에서
회수되지 않는다.** 회수 시간은 units 에 선형(≈0.38s/unit)이고, 턴 시작 주입은 5초에서
잘리므로 그래프 레인이 감당하는 것은 12 units(≈12,000자)까지다.

그 위는 그래프에 넣지 않는다:

  정본 = `.asgard/memory/documents/` 의 텍스트 파일 — 팀에는 **뱅크가 아니라 저장소가**
         나른다 (Git). 승인 게이트가 지키려던 것("공유 스코프의 쓰기는 사람을 지난다")은
         여기서도 지켜진다: 파일은 커밋 전까지 공유되지 않고, git status 에 그대로 보인다.
  검색 = 그 정본에서 만든 로컬 FTS5 인덱스 — 파생물이라 지워도·손상돼도 재생성된다.

"통합 관리, 분리 저장"이 깨지지 않는 이유: 정본은 여전히 하나이고 팀이 공유한다. 갈리는
것은 **회수 경로**뿐이고, 이 경로는 서버가 죽어 있어도 오프라인에서도 돈다.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import sqlite3

import yaml

DOCUMENT_SCHEMA = "asgard-project-document-v1"
DOCUMENTS_RELATIVE_DIR = os.path.join(".asgard", "memory", "documents")
INDEX_RELATIVE_PATH = os.path.join(".asgard", "memory", "documents.db")

RRF_K = 60  # memory.recall·episodes 와 동일 — 순위 융합 표준 상수
DOCUMENT_BUDGET = 900  # chars — 주입 블록 상한 (프로젝트 recall 1600 보다 작게)
_EXCERPT_WIDTH = 220
CHUNK_CHARS = 1200  # 회수 단위. 절 제목을 앞에 달아 두므로 조각만 읽어도 어디인지 안다
CHUNK_MIN = 120  # 이보다 짧은 꼬리는 앞 조각에 붙인다 — 한 줄짜리 조각은 검색 잡음이다
MAX_INDEX_BYTES = 8 * 1024 * 1024  # 한 문서에서 인덱스로 받는 상한 (읽기 폭주 방지)
# 어휘 스캔 스트림 상한. 이 경로는 **매 턴** 도는데 문서는 대화 턴과 달리 수천 조각이 될 수
# 있다 — 전 조각을 파이썬에서 훑는 비용이 사용자에게 지연으로 간다. 넘으면 FTS 만으로 간다:
# 후보가 줄어드는 것은 사실이고, 그걸 조용히 하지 않으려고 상수를 여기 둔다.
MAX_SCAN_CHUNKS = 4000

_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$|^\s*(\d+(?:\.\d+){0,3})\s+(\S.{0,80})$", re.MULTILINE)


def _unsafe_path(path: str) -> bool:
    return os.path.islink(path) or bool(getattr(os.path, "isjunction", lambda _path: False)(path))


def documents_dir(root: str, *, create: bool = False) -> str:
    """프로젝트 루트 아래 정본 디렉터리만 허용한다 (canonical.records_dir 과 같은 계약)."""
    root = os.path.realpath(root)
    path = os.path.join(root, DOCUMENTS_RELATIVE_DIR)
    for component in (os.path.join(root, ".asgard"), os.path.join(root, ".asgard", "memory"), path):
        if os.path.lexists(component) and _unsafe_path(component):
            raise ValueError(f"unsafe project memory path: {component}")
    if create:
        os.makedirs(path, exist_ok=True)
    if os.path.exists(path) and not os.path.isdir(path):
        raise ValueError("project document path must be a directory")
    return path


def document_filename(name: str, content_hash: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", os.path.splitext(name)[0].lower()).strip("-")[:64] or "document"
    return f"{slug}--{content_hash[:16]}.md"


# ── 정본 (Git) ────────────────────────────────────────────────────────────────


def render_document(meta: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=True) + "---\n\n" + body.strip() + "\n"


def parse_document(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("project document is missing its frontmatter")
    _, raw, body = text.split("---\n", 2)
    meta = yaml.safe_load(raw) or {}
    if not isinstance(meta, dict) or meta.get("schema") != DOCUMENT_SCHEMA:
        raise ValueError("unsupported project document schema")
    return meta, body.lstrip("\n")


def save_document(root: str, document) -> str:
    """준비된 문서를 정본으로 적는다. 반환 = 파일 경로.

    같은 파일을 다시 던지면 내용 해시가 파일명에 들어 있어 **다른 파일**이 된다 — 이전
    개정판이 남는 것은 의도다. 요구사항서의 이전 판은 지워야 할 쓰레기가 아니라 무엇이
    언제 바뀌었는지의 증거이고, 지우는 결정은 사람이 git 에서 한다."""
    directory = documents_dir(root, create=True)
    meta = {
        "schema": DOCUMENT_SCHEMA,
        "document_id": document.document_id,
        "name": document.name,
        "kind": document.kind,
        "strategy": document.strategy,
        "content_hash": document.content_hash,
        "chars": len(document.text),
        "entities": [name for name, _kind in document.entities],
        "lane": "local",
    }
    path = os.path.join(directory, document_filename(document.name, document.content_hash))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_document(meta, document.text))
    os.replace(tmp, path)
    return path


def load_documents(root: str) -> list[tuple[dict, str, str]]:
    """정본 전체 — (meta, body, path). 읽지 못한 파일은 건너뛴다 (한 장의 손상이 전부를 막지 않는다)."""
    try:
        directory = documents_dir(root)
    except ValueError:
        return []
    out: list[tuple[dict, str, str]] = []
    for entry in sorted(os.listdir(directory) if os.path.isdir(directory) else []):
        if not entry.endswith(".md"):
            continue
        path = os.path.join(directory, entry)
        if _unsafe_path(path):
            continue
        try:
            if os.path.getsize(path) > MAX_INDEX_BYTES:
                continue
            with open(path, encoding="utf-8", errors="replace") as handle:
                meta, body = parse_document(handle.read())
        except OSError, ValueError:
            continue
        out.append((meta, body, path))
    return out


# ── 조각내기 ──────────────────────────────────────────────────────────────────


def chunk(text: str) -> list[tuple[str, str]]:
    """(절 제목, 본문) 조각 목록.

    제목 경계에서 먼저 자르고 남은 긴 덩어리만 길이로 자른다. 순서가 반대면 한 절이 두
    조각으로 갈릴 때 뒤쪽 조각이 자기가 어느 절인지 잃는다 — 요구사항서에서 그것은
    "3.2.1 이 무엇을 요구하는가"를 못 찾는다는 뜻이다."""
    marks = [(m.start(), (m.group(2) or m.group(4) or "").strip()) for m in _HEADING.finditer(text)]
    sections: list[tuple[str, str]] = []
    if not marks or marks[0][0] > 0:
        sections.append(("", text[: marks[0][0]] if marks else text))
    for index, (start, title) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(text)
        sections.append((title, text[start:end]))
    out: list[tuple[str, str]] = []
    for title, body in sections:
        body = body.strip()
        if not body:
            continue
        while len(body) > CHUNK_CHARS:
            cut = body.rfind("\n", CHUNK_CHARS // 2, CHUNK_CHARS)
            if cut <= 0:
                cut = CHUNK_CHARS
            piece, body = body[:cut].strip(), body[cut:].strip()
            if piece:
                out.append((title, piece))
        if body:
            if len(body) < CHUNK_MIN and out and out[-1][0] == title:
                out[-1] = (title, out[-1][1] + "\n" + body)
            else:
                out.append((title, body))
    return out


# ── 파생 인덱스 ───────────────────────────────────────────────────────────────


def _index_path(root: str) -> str:
    return os.path.join(os.path.realpath(root), INDEX_RELATIVE_PATH)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS doc USING fts5"
            "(seq UNINDEXED, name UNINDEXED, document_id UNINDEXED, path UNINDEXED,"
            " heading, body, tokenize='trigram')"
        )
        conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        return conn
    except Exception:
        conn.close()
        raise


def _db(root: str) -> sqlite3.Connection:
    """파생 인덱스 연결 — 손상 파일은 격리 후 재생성 (memory.index·episodes 와 동일 계약)."""
    path = _index_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        return _connect(path)
    except sqlite3.DatabaseError as e:
        if getattr(e, "sqlite_errorcode", None) not in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
            raise
        with contextlib.suppress(OSError):
            os.remove(path)
        return _connect(path)


def _manifest(root: str) -> str:
    """정본 디렉터리의 형상 지문 — 파일이 늘고 줄고 바뀐 것을 한 문자열로 본다."""
    try:
        directory = documents_dir(root)
    except ValueError:
        return ""
    rows = []
    for entry in sorted(os.listdir(directory) if os.path.isdir(directory) else []):
        with contextlib.suppress(OSError):
            stat = os.stat(os.path.join(directory, entry))
            rows.append(f"{entry}:{stat.st_size}:{stat.st_mtime_ns}")
    return hashlib.sha256("|".join(rows).encode()).hexdigest()


def lane_present(root: str) -> bool:
    """이 저장소가 로컬 레인을 쓰는가 — 정본이 있거나, 있었던 흔적(인덱스)이 있는가.

    회수는 프로젝트마다 매 턴 돈다. 레인을 안 쓰는 저장소에 빈 인덱스 파일을 만들어 두면
    쓰지도 않는 `.asgard/memory/` 를 온 저장소에 심는 셈이다 — 파생물은 필요할 때 생긴다."""
    try:
        directory = documents_dir(root)
    except ValueError:
        return False
    if os.path.isdir(directory) and any(e.endswith(".md") for e in os.listdir(directory)):
        return True
    return os.path.exists(_index_path(root))  # 정본이 지워졌으면 인덱스도 비워야 한다


def sync(root: str) -> int:
    """정본 → 인덱스. 지문이 같으면 아무것도 하지 않고, 다르면 통째로 다시 만든다.

    증분을 안 하는 이유는 정본이 append-only 가 아니기 때문이다 (사람이 지우고 되돌린다).
    문서 수는 수십 단위라 전체 재구축이 싸다 — 여기서 아낄 것은 시간이 아니라 정합성이다.
    반환 = 인덱스된 조각 수."""
    try:
        if not lane_present(root):
            return 0
        digest = _manifest(root)
        conn = _db(root)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'manifest'").fetchone()
            if row and row[0] == digest:
                return int(conn.execute("SELECT count(*) FROM doc").fetchone()[0])
            seq = 0
            with conn:
                conn.execute("DELETE FROM doc")
                for meta, body, path in load_documents(root):
                    name = str(meta.get("name") or os.path.basename(path))
                    for heading, piece in chunk(body):
                        seq += 1
                        conn.execute(
                            "INSERT INTO doc(seq, name, document_id, path, heading, body) VALUES(?,?,?,?,?,?)",
                            (seq, name, str(meta.get("document_id") or ""), path, heading, piece),
                        )
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('manifest', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (digest,),
                )
            return seq
        finally:
            conn.close()
    except Exception:
        return 0  # fail-open — 인덱스 불능은 검색이 빈 결과로 감내한다


def _words(text: str) -> list[str]:
    return list(dict.fromkeys(w.lower() for w in re.split(r"[^\w가-힣%-]+", text) if len(w) >= 2))


def _excerpt(text: str, phrase: str, words: list[str], width: int = _EXCERPT_WIDTH) -> str:
    low = text.lower()
    needle = phrase if phrase and phrase in low else next((w for w in words if w in low), "")
    i = low.find(needle) if needle else 0
    seg = text[max(i - width // 4, 0) :][:width].strip()
    return re.sub(r"\s+", " ", seg)


def search(root: str, text: str, k: int = 3) -> list[dict]:
    """문서 정본 전문 검색 (0-LLM) — FTS trigram + lexical 스캔 2-스트림 RRF.

    반환 hit = {seq, name, heading, excerpt, score}. 그래프가 하던 일을 대신하는 자리라
    회수 경로는 검증된 것(episodes·memory.recall 과 같은 융합)을 그대로 쓴다."""
    try:
        if not lane_present(root):
            return []  # 파생물은 필요할 때 생긴다 — 빈 인덱스조차 만들지 않는다
        sync(root)
        k = max(1, min(int(k), 50))
        conn = _db(root)
        try:
            rows = conn.execute("SELECT seq, name, heading, body FROM doc").fetchall()
            fts_order: list[tuple[int, float]] = []
            terms = [w for w in re.split(r"\s+", text.strip()) if len(w) >= 3]
            if terms:
                match = " OR ".join('"' + w.replace('"', '""') + '"' for w in terms)
                with contextlib.suppress(Exception):  # MATCH 문법 오류 — 스캔 스트림만으로 진행
                    fts_order = [
                        (int(s), float(b))
                        for s, b in conn.execute(
                            "SELECT seq, bm25(doc) FROM doc WHERE doc MATCH ? ORDER BY bm25(doc) LIMIT ?",
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

    def _scan_score(row: tuple) -> int:
        hay = (str(row[2]) + "\n" + str(row[3])).lower()
        return sum(1 for w in words if w in hay) + (3 if phrase and phrase in hay else 0)

    scan_order = (
        sorted(((seq, float(s)) for seq, row in by_seq.items() if (s := _scan_score(row)) > 0), key=lambda p: -p[1])
        if len(by_seq) <= MAX_SCAN_CHUNKS
        else []
    )
    rrf: dict[int, float] = {}

    def _add(ordered: list[tuple[int, float]]) -> None:
        rank, prev = 0, None
        for i, (seq, score) in enumerate(ordered):
            if score != prev:
                rank, prev = i + 1, score
            rrf[seq] = rrf.get(seq, 0.0) + 1.0 / (RRF_K + rank)

    _add([(seq, b) for seq, b in fts_order if seq in by_seq])
    _add(scan_order)
    hits: list[dict] = []
    for seq in sorted(rrf, key=lambda s: (-rrf[s], s))[:k]:
        row = by_seq[seq]
        hits.append(
            {
                "seq": seq,
                "name": str(row[1]),
                "heading": str(row[2] or ""),
                "excerpt": _excerpt(str(row[3]), phrase, words),
                "score": round(rrf[seq], 4),
            }
        )
    return hits


def _neutralize(s: str) -> str:
    return s.replace("<", "‹").replace(">", "›")


NOTE_PREFIX = (
    '\n\n<memory-recall scope="project-document">\n'
    "요청 관련 프로젝트 문서 구간 (힌트 — 원문 발췌이지 완료 증거가 아님):\n"
)
NOTE_SUFFIX = "\n</memory-recall>"


def rows(query: str, root: str, k: int = 2) -> list[str]:
    """관련 문서 구간 본문 목록 — 렌더도 예산도 없다 (조립기가 건다).

    오염 검사는 여기서 한다: 문서 원문은 사람이 승인해 정본이 됐지만 **본문 안의 문장까지**
    승인한 것은 아니다 (규격서에 남이 심어 둔 지시가 있을 수 있다)."""
    from ..memory.policy import inject_enabled, scan_threats

    if not inject_enabled():
        return []
    out: list[str] = []
    for hit in search(root, query, k=k):
        if scan_threats(hit["excerpt"], hit["heading"]):
            continue  # 원문 유래 오염 구간 — 주입 제외
        where = f" · {hit['heading']}" if hit["heading"] else ""
        out.append(f"{_neutralize(hit['name'])}{_neutralize(where)}: {_neutralize(hit['excerpt'])}")
    return out


def note(query: str, root: str, k: int = 2) -> str:
    """관련 문서 구간의 비권위 주입 블록. 무적중·킬스위치 off·실패 = 빈 문자열.

    문서 원문은 승인 게이트를 지나 정본이 됐지만 **완료 증거는 아니다** — 규격서에 적혀
    있다는 것과 그렇게 구현됐다는 것은 다른 말이고, 그 구분이 무너지면 게이트가 무의미해진다.

    이 레인 혼자 쓰는 표면용이다 — 여섯 레인을 같이 싣는 자리는 조립기로 간다."""
    try:
        from ..memory.assemble import Candidate, Lane, assemble

        found = rows(query, root, k=k)
        if not found:
            return ""
        lane = Lane("document", NOTE_PREFIX, NOTE_SUFFIX, DOCUMENT_BUDGET)
        return assemble(
            [Candidate("document", body, rank=index) for index, body in enumerate(found)],
            (lane,),
            budget=DOCUMENT_BUDGET,
        )
    except Exception:
        return ""  # fail-open — 문서 회수 불능이 대화를 막지 않는다


def stats(root: str) -> dict:
    """레인 현황 — 문서 수·조각 수·정본 바이트. 읽기 전용."""
    documents = load_documents(root)
    chunks = sync(root)
    return {
        "documents": len(documents),
        "chunks": chunks,
        "bytes": sum(len(body.encode()) for _meta, body, _path in documents),
    }


__all__ = [
    "CHUNK_CHARS",
    "DOCUMENTS_RELATIVE_DIR",
    "DOCUMENT_SCHEMA",
    "chunk",
    "documents_dir",
    "lane_present",
    "load_documents",
    "note",
    "parse_document",
    "render_document",
    "save_document",
    "search",
    "stats",
    "sync",
]
