"""개인 메모리 — LLM Wiki 패턴 (Karpathy gist 442a6bf5) 의 파일 정본 계층.

원칙 (memory v3, 26-07-15 확정):
  정본 = ~/.asgard/memory/ 의 md 파일 (사람이 읽고 고칠 수 있는 텍스트 —
  바이너리-in-git 사고의 반성). state.db(FTS5)·index.md 는 pages/ 에서
  기계적으로 재생성되는 파생물 — 지워도(또는 손상돼도) 지식은 죽지 않는다.

구조:  SCHEMA.md(규약) · index.md(카탈로그) · log.md(append-only 운영 로그)
       · pages/<slug>.md(frontmatter+본문) · state.db(FTS5 파생 인덱스+usage)

보안 (P0, 감사 26-07-15 반영): 메모리는 시스템 프롬프트에 주입되므로 오염이 세션
전체·세션 간 지속된다. 방어 — ① 쓰기 시 본문+메타데이터(title/links) 전부 인젝션
스캔 ② frontmatter 값 개행 금지(가짜 필드 삽입 차단) ③ snapshot 주입 시 페이지
재검증(오염 제외) + 경계 문자 무력화(펜스 탈출 차단) ④ slug realpath 봉쇄(경로 순회).

무결성 (P1): 실제 렌더 기준 예산 하드게이트 · 원자 쓰기(고유 temp) · 프로세스 락 ·
승인된 plan 그대로 실행 · 손상 DB 자동 재생성. 전 경로 fail-open (읽기).

자가 관리: ingest 는 근사 중복을 기존 페이지 병합으로 흡수, query 가 사용 흔적을
남기고, lint 가 고아·죽은 링크·부패·중복·예산·오염을 기계 판정. 게이트는 메모리를
신뢰하지 않는다 — 여기 저장된 무엇도 완료 증거가 아니다.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import os
import re
import sqlite3
from typing import Any

fcntl: Any = None  # posix 파일 락 — 없으면 msvcrt(Windows) 폴백, 둘 다 없으면 best-effort
msvcrt: Any = None
with contextlib.suppress(ImportError):
    import fcntl
with contextlib.suppress(ImportError):  # pragma: no cover — Windows 전용
    import msvcrt as _msvcrt

    msvcrt = _msvcrt

MEMORY_ENV = "ASGARD_MEMORY_DIR"
PAGES, INDEX, LOG, SCHEMA, DB = "pages", "index.md", "log.md", "SCHEMA.md", "state.db"
KINDS = ("note", "user", "decision", "insight", "reference", "feedback")
DEFAULT_KIND = "note"
INDEX_BUDGET = 2200  # chars — 주입면 상한 검증값. config [memory].index_budget_chars 로 조정
STALE_DAYS = 90  # lint 부패 후보 기준 — 90일 무갱신 + 사용 0회
# ingest 병합 문턱 — containment(포함 계수)로 판정: Jaccard 는 길이 차에 취약해 "같은 사실의
# 패러프레이즈+추가 상세"를 놓친다 (실측 26-07-15: 병합쌍 cont 0.56/0.61 vs 생성쌍 0.00/0.02).
MERGE_CONTAINMENT = 0.45
DUP_JACCARD = 0.60  # lint 중복 의심 문턱 — 대칭 비교라 Jaccard 가 맞다
_SNAPSHOT_WARN = "- … (index over budget — asgard memory lint)"

# 주입 스캔 — 위협 문구 패턴 strict 축약판. 메모리는 프롬프트에 주입되므로
# 오염 엔트리는 세션 전체·세션 간 지속된다. 걸리면 저장 거부 (사람이 고쳐서 재시도).
_THREATS = (
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+(instructions|rules|prompts)",
    r"disregard\s+(the\s+)?(system|previous|above)",
    r"<\s*/?\s*(system|memory-context|assistant|user|tool)\b",  # 태그 경계 탈출·펜스 위조
    r"you\s+are\s+now\b",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"이전\s*지시(사항)?\s*(를|은|는)?\s*무시",
    r"시스템\s*프롬프트\s*(를|을)?\s*(공개|유출|출력)",
    r"\b(curl|wget)\s+https?://",
    r"[A-Za-z0-9+/]{120,}={0,2}",  # 장문 base64 블롭 — 은닉 페이로드 의심
)


def memory_dir() -> str:
    return os.environ.get(MEMORY_ENV) or os.path.join(os.path.expanduser("~"), ".asgard", "memory")


def _memory_settings() -> dict:
    """글로벌 [memory] 섹션 — asgard-setting-global.json 우선, 구 config.toml 폴백 (settings.py)."""
    try:
        from .settings import load_global

        return dict(load_global().get("memory") or {})
    except Exception:
        return {}


def index_budget() -> int:
    try:
        value = _memory_settings().get("index_budget_chars")
        return max(0, int(value)) if value is not None else INDEX_BUDGET
    except Exception:
        return INDEX_BUDGET


def inject_enabled() -> bool:
    """프롬프트 주입 킬스위치 (2차 리뷰 ⑦) — env ASGARD_MEMORY_INJECT > 설정 memory.inject.
    off 면 snapshot_note 가 빈 문자열 = 어떤 provider 로도 메모리가 전송되지 않는다."""
    v = (os.environ.get("ASGARD_MEMORY_INJECT") or "").strip().lower()
    if v:
        return v not in ("off", "0", "false")
    try:
        return str(_memory_settings().get("inject", "on")).strip().lower() not in ("off", "0", "false")
    except Exception:
        return True


def inject_allowed(provider: str | None = None, provider_source: str | None = None) -> bool:
    """provider별 전송 게이트 — 킬스위치 + `memory.providers` allowlist (배선 단계).
    allowlist 부재/빈 리스트 = 사용자 선택 provider 는 허용하되 프로젝트 선택 provider 는 거부.
    개인 메모리가 임의 원격 모델로 새는 표면을 사용자가 직접 통제한다 (독립 리뷰 지적)."""
    if not inject_enabled():
        return False
    if not provider:
        return True
    try:
        allow = _memory_settings().get("providers")
        if isinstance(allow, list) and allow:
            return provider in [str(a).strip() for a in allow]
    except Exception:
        pass
    return provider_source != ".asgard/asgard-setting-project.json"


def scan_threats(*texts: str | None) -> str | None:
    """인젝션/유출 패턴 검사 — 하나라도 걸리면 요약 반환, 전부 무해하면 None.
    본문만이 아니라 주입되는 모든 필드(title·links·meta)를 같이 넘긴다 (P0)."""
    for text in texts:
        if not text:
            continue
        for pat in _THREATS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return f"blocked pattern: {m.group(0)[:60]!r}"
    return None


_SCHEMA_MD = """# Memory Schema — 개인 위키 규약

이 디렉토리는 asgard 개인 메모리의 **정본**이다 (LLM Wiki 패턴).
`pages/*.md` 가 지식이고, `index.md`·`state.db` 는 재생성 가능한 파생물이다.

## 페이지 규약
- 파일 = 사실/개체/개념 1개. frontmatter: `title` / `kind` / `created` / `updated` / `links`
- kind: note | user | decision | insight | reference | feedback
- 본문은 자립적으로 — 다른 페이지는 [[slug]] 로 연결
- 코드/저장소에서 1분 내 파악 가능한 사실은 저장하지 않는다

## 운영 (asgard memory <op>)
- ingest: 새 지식 흡수 — 근사 중복은 기존 페이지에 병합 (승인 게이트 경유)
- query: FTS 검색 — 가치 있는 종합 결과는 add 로 새 페이지 승격 (복리)
- lint: 건강 점검 — 고아·죽은 링크·부패 후보·중복 쌍·예산 초과·오염
- merge/remove: 통합·삭제 (예산 초과 해소) · reindex: pages/ 에서 파생 전체 재생성

## 불변식
- index.md 는 예산(기본 2200자) 안에서만 자란다 — 초과 시 add 가 거부된다: 병합·삭제로 통합하라
- 여기 저장된 무엇도 게이트의 완료 증거가 될 수 없다 (메모리는 힌트다)
- **개인 스코프 전용** — 이 위키의 내용·용어(개인 약어, 세계관 용어, 사적 축약)는
  프로젝트 공유 메모리로 그대로 내보내지 않는다. 공유 스코프에 쓸 때는 프로젝트
  공용 어휘(온톨로지)로 다시 서술한다 (용어 방화벽, 26-07-15)
"""


def _chmod(path: str, mode: int) -> None:
    with contextlib.suppress(OSError):
        os.chmod(path, mode)  # 개인 메모리 — 파일 0600 / 디렉토리 0700 (P2)


def ensure_home(d: str | None = None) -> str:
    """스캐폴드와 개인 파일 권한 교정. 내용은 기존 파일을 덮어쓰지 않는다."""
    d = d or memory_dir()
    pages = os.path.join(d, PAGES)
    if os.path.islink(d):
        raise ValueError("memory home must not be a symlink")
    if os.path.islink(pages):
        raise ValueError("memory pages directory must not be a symlink")
    os.makedirs(pages, exist_ok=True)
    _chmod(d, 0o700)
    _chmod(pages, 0o700)
    for name, content in ((SCHEMA, _SCHEMA_MD), (INDEX, "# Memory Index\n"), (LOG, "# Memory Log\n")):
        p = os.path.join(d, name)
        if not os.path.exists(p):
            _atomic_write(p, content)
        elif not os.path.islink(p):
            _chmod(p, 0o600)
    for name in (DB, f"{DB}-wal", f"{DB}-shm", ".lock"):
        p = os.path.join(d, name)
        if os.path.exists(p) and not os.path.islink(p):
            _chmod(p, 0o600)
    with contextlib.suppress(OSError):
        for name in os.listdir(pages):
            p = os.path.join(pages, name)
            if name.endswith(".md") and os.path.isfile(p) and not os.path.islink(p):
                _chmod(p, 0o600)
    return d


@contextlib.contextmanager
def _lock(d: str):
    """디렉토리 단위 배타 락 — 동시 add/ingest/remove 직렬화 (P1).
    posix=fcntl, Windows=msvcrt(2차 리뷰 ⑥), 둘 다 없으면 best-effort no-op."""
    os.makedirs(d, exist_ok=True)
    fh = open(os.path.join(d, ".lock"), "a+")
    _chmod(os.path.join(d, ".lock"), 0o600)
    try:
        if fcntl is not None:
            fcntl.flock(fh, fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover — Windows 전용
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        yield
    finally:
        with contextlib.suppress(OSError):
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        fh.close()


def _atomic_write(path: str, content: str) -> None:
    """고유 temp + rename 원자 쓰기 (P1) — 부분 파일 노출·동시 temp 충돌 없음. 0600."""
    d = os.path.dirname(path)
    tmp = os.path.join(d, f".{os.path.basename(path)}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    _chmod(tmp, 0o600)
    os.replace(tmp, path)


# ── 페이지 직렬화 ──────────────────────────────────────────────────────────────


def _today() -> str:
    return _dt.date.today().isoformat()


def _fm_value(v: object) -> str:
    """frontmatter 값 정규화 — 개행 제거(가짜 필드 삽입 차단, P0) + 트림."""
    return re.sub(r"[\r\n]+", " ", str(v)).strip()


def parse_page(text: str) -> tuple[dict, str]:
    """frontmatter(`--- k: v ---`) + 본문. yaml 미사용 — k: v 평문만 (외부 편집 관용)."""
    meta: dict = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end > 0:
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            return meta, text[end + 4 :].lstrip("\n")
    return meta, text


def render_page(meta: dict, body: str) -> str:
    fm = "\n".join(f"{k}: {_fm_value(v)}" for k, v in meta.items() if v not in ("", None))
    return f"---\n{fm}\n---\n\n{body.rstrip()}\n"


def slugify(title: str) -> str:
    """유니코드(한국어) 보존 슬러그 — 공백→하이픈, 경로 위험 문자 제거. 빈 결과는 해시."""
    s = re.sub(r"[\s]+", "-", title.strip().lower())
    s = re.sub(r"[^\w\-가-힣]", "", s, flags=re.UNICODE).strip("-")[:64]
    return s or hashlib.sha1(title.encode()).hexdigest()[:12]


def valid_slug(slug: str) -> bool:
    """슬러그 형식 검증 (P0) — slugify 산출 문자셋과 동일. 경로 구분자·점·과길이 배제."""
    return bool(slug) and len(slug) <= 80 and re.fullmatch(r"[\w\-가-힣]+", slug, re.UNICODE) is not None


def _page_path(d: str, slug: str) -> str:
    """pages/<slug>.md — realpath 가 pages/ 하위임을 강제 (경로 순회 차단, P0)."""
    pages = os.path.join(d, PAGES)
    if os.path.islink(d) or os.path.islink(pages):
        raise ValueError("memory canonical directories must not be symlinks")
    p = os.path.join(pages, f"{slug}.md")
    root = os.path.realpath(pages)
    if os.path.commonpath([root, os.path.realpath(p)]) != root:
        raise ValueError(f"slug escapes pages dir: {slug!r}")
    return p


def _pages(d: str) -> list[str]:
    p = os.path.join(d, PAGES)
    try:
        return sorted(f[:-3] for f in os.listdir(p) if f.endswith(".md"))
    except Exception:
        return []


def _read(d: str, slug: str) -> tuple[dict, str] | None:
    try:
        return parse_page(open(_page_path(d, slug), encoding="utf-8").read())
    except Exception:  # 없음·파싱 실패·경로 순회 시도 전부 None (fail-safe)
        return None


def _desc(meta: dict, body: str) -> str:
    line = meta.get("description") or next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    return line[:90]


def _kind(meta: dict) -> str:
    """kind 화이트리스트 강제 (2차 리뷰 ①) — 외부 편집으로 심은 임의 문자열이 표시/주입면에
    도달하지 못한다. 미등재 kind 는 note 로 강등."""
    k = meta.get("kind", DEFAULT_KIND)
    return k if k in KINDS else DEFAULT_KIND


def poisoned(meta: dict, body: str) -> str | None:
    """페이지 오염 판정 — 주입 가능한 모든 필드(본문·title·links·description·kind)."""
    return scan_threats(
        body, meta.get("title", ""), meta.get("links", ""), meta.get("description", ""), meta.get("kind", "")
    )


def log_op(d: str, op: str, slug: str, detail: str = "") -> None:
    """append-only 운영 로그 — 파싱 가능한 접두사 `[op]` (Karpathy log.md)."""
    try:
        ts = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%MZ")
        p = os.path.join(d, LOG)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"- {ts} [{op}] {slug}{' — ' + detail if detail else ''}\n")
        _chmod(p, 0o600)
    except Exception:
        pass  # 로그 실패가 지식 쓰기를 막지 않는다


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


def reindex(d: str | None = None) -> int:
    """pages/ → state.db + index.md 전체 재생성. usage 보존, 손상 시 nuke-rebuild. 반환 = 페이지 수."""
    d = ensure_home(d)
    with _lock(d):
        conn = None
        try:
            conn = _db(d)
            with conn:
                conn.execute("DELETE FROM fts")
                for slug in _pages(d):
                    _fts_upsert(conn, d, slug)
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
                for slug in _pages(d):
                    _fts_upsert(conn, d, slug)
            conn.close()
        write_index(d)
        return len(_pages(d))


# ── 검색 (query) — LLM 0. trigram FTS, 실패 시 파일 스캔 fail-open ─────────────────


def _grams(text: str, n: int = 3) -> set[str]:
    t = re.sub(r"\s+", " ", text.lower())
    return {t[i : i + n] for i in range(max(len(t) - n + 1, 1))}


def _jaccard(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / (len(ga | gb) or 1)


def _containment(a: str, b: str) -> float:
    """포함 계수 |A∩B|/min(|A|,|B|) — 한쪽이 다른 쪽을 품는 패러프레이즈에 강건."""
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / (min(len(ga), len(gb)) or 1)


RRF_K = 60  # rank-fusion 표준 상수 — 상위 랭크 간 격차를 완만히 눌러 단일 경로 독주를 막는다


def query(text: str, k: int = 5, d: str | None = None, track: bool = True) -> list[dict]:
    """FTS5 trigram 검색 (한국어 substring 대응). hit 는 usage 를 남긴다 — lint 부패 판정 원료.

    랭킹 = RRF(rank fusion). BM25 값과 스캔 매칭 카운트는 척도가 달라 점수 혼합이 무의미하므로
    각 경로의 '순위'만 합산한다 (동점 = 동순위). RRF 동률은 usage 회수 빈도 → slug 순으로
    가른다 — 빈도는 어디를 먼저 볼지 정하는 prior 일 뿐, 관련도 순위를 넘지 못한다.
    오염 페이지는 결과에서 제외한다 (2차 리뷰 ② — query 출력은 에이전트 컨텍스트로 흘러간다).
    제외 수는 결과에 실리지 않고 lint 가 threat 로 보고한다."""
    d = d or memory_dir()
    k = max(1, min(int(k), 1000))  # 음수·0·과대 방지 (P2)
    if not os.path.isdir(os.path.join(d, PAGES)):
        return []

    def _clean(slug: str) -> tuple[dict, str] | None:
        pg = _read(d, slug)
        if not pg or poisoned(*pg):
            return None
        return pg

    phrase = text.strip().lower()
    raw_words = [w.lower() for w in re.split(r"[^\w가-힣%-]+", text) if len(w) >= 2]
    scan_words: list[str] = []
    particles = (
        "으로",
        "에서",
        "에게",
        "한테",
        "처럼",
        "까지",
        "부터",
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "에",
        "의",
        "로",
        "과",
        "와",
        "도",
        "만",
    )
    for word in raw_words:
        scan_words.append(word)
        suffix = next((p for p in particles if word.endswith(p) and len(word) > len(p) + 1), None)
        if suffix:
            scan_words.append(word[: -len(suffix)])
    scan_words = list(dict.fromkeys(scan_words))

    def _scan_score(meta: dict, body: str) -> tuple[list[str], int]:
        hay = (meta.get("title", "") + "\n" + body).lower()
        matched = [w for w in scan_words if w in hay]
        return matched, len(matched) + (3 if phrase and phrase in hay else 0)

    # 후보 수집: slug → (meta, body, matched, scan_score). FTS 순위는 별도 리스트로 보존.
    cand: dict[str, tuple[dict, str, list[str], int]] = {}
    fts_order: list[tuple[str, float]] = []  # (slug, bm25) — bm25 는 작을수록 좋음
    try:
        conn = _db(d)
        words = [w for w in re.split(r"\s+", text.strip()) if len(w) >= 3]
        if words:
            match = " OR ".join('"' + w.replace('"', '""') + '"' for w in words)
            rows = conn.execute(
                "SELECT slug, bm25(fts) FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?",
                (match, k),
            ).fetchall()
            for slug, bm in rows:
                pg = _clean(slug)
                if pg is None:  # 오염·소실 — FTS 행이 낡았어도 정본 기준으로 거른다
                    continue
                meta, body = pg
                matched, s = _scan_score(meta, body)
                if not s:
                    continue  # stale FTS 행 — 현재 정본이 더는 질의와 맞지 않음
                cand[slug] = (meta, body, matched, s)
                fts_order.append((slug, bm))
        conn.close()
    except Exception:
        pass  # FTS 불능 → 아래 파일 스캔만으로 fail-open

    # 정본 스캔으로 FTS 일부 누락·stale 행을 보완한다. 메모리는 예산상 작아 완전성 우선.
    for slug in _pages(d):
        if slug in cand:
            continue
        pg = _clean(slug)
        if not pg:
            continue
        meta, body = pg
        matched, s = _scan_score(meta, body)
        if s:
            cand[slug] = (meta, body, matched, s)
    if not cand:
        return []

    # RRF: 경로별 순위 기여 1/(RRF_K+rank) 합산. 동점은 동순위 — 진짜 동등만 동률로 남는다.
    rrf = dict.fromkeys(cand, 0.0)

    def _add_ranks(ordered: list[tuple[str, float]]) -> None:
        rank, prev = 0, None
        for i, (slug, s) in enumerate(ordered):
            if s != prev:
                rank, prev = i + 1, s
            rrf[slug] += 1.0 / (RRF_K + rank)

    _add_ranks(fts_order)
    _add_ranks(sorted(((slug, float(c[3])) for slug, c in cand.items()), key=lambda p: -p[1]))

    # usage 는 RRF 동률 타이브레이크 전용 prior — 관련도 순위를 넘지 못한다 (힌트, 증거 아님)
    uses: dict[str, int] = {}
    try:
        conn = _db(d)
        uses = dict(conn.execute("SELECT slug, uses FROM usage").fetchall())
        conn.close()
    except Exception:
        pass

    hits: list[dict] = []
    for slug in sorted(cand, key=lambda s: (-rrf[s], -uses.get(s, 0), s))[:k]:
        meta, body, matched, _s = cand[slug]
        lb = body.lower()
        needle = phrase if phrase in lb else next((w for w in matched if w in lb), "")
        i = lb.find(needle) if needle else 0
        hits.append(
            {
                "slug": slug,
                "title": meta.get("title", slug),
                "kind": _kind(meta),
                "snippet": body[max(i - 40, 0) : i + 80].strip(),
                "score": round(rrf[slug], 4),
            }
        )
    return _track(d, hits) if track else hits


def _track(d: str, hits: list[dict]) -> list[dict]:
    """hit 의 사용 흔적 기록 — lint 부패 판정 원료. 경로(FTS/스캔) 무관 공통, 실패는 무해."""
    try:
        conn = _db(d)
        ts = _today()
        with conn:
            for h in hits:
                conn.execute(
                    "INSERT INTO usage(slug, uses, last_used) VALUES(?,1,?) "
                    "ON CONFLICT(slug) DO UPDATE SET uses = uses + 1, last_used = ?",
                    (h["slug"], ts, ts),
                )
        conn.close()
    except Exception:
        pass
    return hits


# ── 쓰기 (add / ingest) — 승인은 CLI 계층, 여기는 기계 검증 + 락 ───────────────────


def _fresh_slug(d: str, base: str, seed: str) -> str:
    """충돌 없는 slug — 이미 있으면 seed 로 접미사를 붙이며 빈 자리까지 반복 (P2, 3번째 충돌 방지)."""
    slug, i = base, 0
    while os.path.exists(_page_path(d, slug)):
        i += 1
        slug = f"{base}-{hashlib.sha1(f'{seed}{i}'.encode()).hexdigest()[:6]}"
    return slug


def add(
    text: str,
    title: str | None = None,
    kind: str = DEFAULT_KIND,
    links: str = "",
    d: str | None = None,
    force: bool = False,
) -> tuple[str, str]:
    """페이지 생성. 반환 = (slug, path). 스캔 위반·예산 초과·잘못된 kind 는 ValueError."""
    d = ensure_home(d)
    if not text.strip():
        raise ValueError("empty memory text")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind!r} — one of {', '.join(KINDS)}")
    title = _fm_value(title or next((ln.strip().lstrip("# ") for ln in text.splitlines() if ln.strip()), "untitled"))[
        :80
    ]
    links = _fm_value(links)
    threat = scan_threats(text, title, links)  # 본문 + 주입 메타 전부 (P0)
    if threat:
        raise ValueError(f"injection scan: {threat}")
    with _lock(d):
        slug, path = _add_unlocked(d, text, title, kind, links, force)
    return slug, path


def _add_unlocked(d: str, text: str, title: str, kind: str, links: str, force: bool) -> tuple[str, str]:
    """호출자가 _lock(d)을 보유한 add 본체 — ingest create의 락 공백 방지."""
    slug = _fresh_slug(d, slugify(title), text)
    meta = {"title": title, "kind": kind, "created": _today(), "updated": _today()}
    if links:
        meta["links"] = links
    projected = len(build_index(d)) + len(_index_row(slug, meta, text)) + 1
    if not force and projected > index_budget():
        raise ValueError(
            f"index budget exceeded ({projected}/{index_budget()} chars) — "
            "consolidate first (asgard memory merge/remove), or --force"
        )
    path = _page_path(d, slug)
    _atomic_write(path, render_page(meta, text))
    write_index(d)
    with contextlib.suppress(Exception):
        conn = _db(d)
        with conn:
            _fts_upsert(conn, d, slug)
        conn.close()
    log_op(d, f"add:{kind}", slug)
    return slug, path


def plan_ingest(text: str, d: str | None = None) -> dict:
    """ingest 계획 — 실행 없이 판정만 (CLI 승인 게이트가 이 계획을 사람에게 보여준다).
    후보 top-3 중 최대 containment ≥ MERGE_CONTAINMENT 면 merge, 아니면 create."""
    d = d or memory_dir()
    best, best_sim = None, 0.0
    for hit in query(text, k=3, d=d, track=False):
        pg = _read(d, hit["slug"])
        if not pg:
            continue
        sim = _containment(text, pg[0].get("title", "") + " " + pg[1])
        if sim > best_sim:
            best, best_sim = hit, sim
    if best and best_sim >= MERGE_CONTAINMENT:
        return {
            "action": "merge",
            "slug": best["slug"],
            "title": best["title"],
            "sim": round(best_sim, 2),
            "rev": _rev(d, best["slug"]),  # 승인 시점 페이지 리비전 — 실행 시 대조 (2차 리뷰 ⑤)
        }
    return {"action": "create", "slug": None, "title": None, "sim": round(best_sim, 2)}


def _rev(d: str, slug: str) -> str:
    """페이지 리비전 = 원문 sha1 — plan 승인과 실행 사이의 변경 감지용."""
    try:
        return hashlib.sha1(open(_page_path(d, slug), "rb").read()).hexdigest()[:12]
    except Exception:
        return ""


def _fact_present(body: str, text: str) -> bool:
    """동일 ingest 재실행 탐지. 과거 날짜-prefix 병합분도 같은 사실로 본다."""
    fact = text.strip()
    if not fact:
        return False
    for paragraph in re.split(r"\n\s*\n", body.strip()):
        existing = re.sub(r"^\d{4}-\d{2}-\d{2}:\s*", "", paragraph.strip())
        if existing == fact:
            return True
    return False


_PREFERENCE_PATTERNS = (
    re.compile(r"^(?P<subject>.+?)\s+(?P<key>.+?)(?:로|으로)\s+(?P<value>.+?)(?:을|를)\s+선호"),
    re.compile(r"^(?P<subject>.+?)\s+(?P<value>.+?)(?:을|를)\s+(?P<key>.+?)(?:로|으로)\s+선호"),
)


def _preference_parts(text: str) -> tuple[str, frozenset[str]] | None:
    statement = re.sub(r"^\d{4}-\d{2}-\d{2}:\s*", "", text.strip())
    for pattern in _PREFERENCE_PATTERNS:
        match = pattern.search(statement)
        if not match:
            continue
        key = re.sub(r"\s+", " ", f"{match.group('subject')} {match.group('key')}").strip().casefold()
        values = frozenset(
            value.strip().casefold()
            for value in re.split(r"\s*(?:과|와|및|,)\s*", match.group("value"))
            if value.strip()
        )
        if key and values:
            return key, values
    return None


def _update_user_preference(body: str, text: str) -> tuple[str, str]:
    """동일 preference key만 갱신한다. 복합값 축소·다른 key는 보존한다."""
    incoming = _preference_parts(text)
    if incoming is None:
        return body.rstrip() + f"\n\n{_today()}: {text.strip()}", "merged"
    paragraphs = re.split(r"\n\s*\n", body.strip())
    matches = [
        (i, parts[1])
        for i, paragraph in enumerate(paragraphs)
        if (parts := _preference_parts(paragraph)) and parts[0] == incoming[0]
    ]
    if not matches:
        return body.rstrip() + f"\n\n{_today()}: {text.strip()}", "merged"
    old_values = frozenset().union(*(values for _, values in matches))
    new_values = incoming[1]
    if new_values <= old_values:
        return body, "unchanged"
    if old_values.isdisjoint(new_values) or old_values <= new_values:
        first = matches[0][0]
        remove = {i for i, _ in matches[1:]}
        paragraphs[first] = text.strip()
        return "\n\n".join(p for i, p in enumerate(paragraphs) if i not in remove), "updated"
    return body.rstrip() + f"\n\n{_today()}: {text.strip()}", "merged"


def ingest(text: str, kind: str = DEFAULT_KIND, d: str | None = None, plan: dict | None = None) -> tuple[str, str]:
    """자가 학습 쓰기 — plan 대로 생성·병합·선호 갱신·동일 사실 no-op. 반환 = (action, slug).

    plan 을 넘기면(CLI 승인 게이트가 이미 계산·표시한 계획) 재계산하지 않는다 (TOCTOU 차단, P1):
    "승인한 merge 대상"과 "실제 merge 대상"이 갈라지지 않는다."""
    d = ensure_home(d)
    if not text.strip():
        raise ValueError("empty memory text")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind!r} — one of {', '.join(KINDS)}")
    threat = scan_threats(text)
    if threat:
        raise ValueError(f"injection scan: {threat}")
    with _lock(d):
        approved = plan is not None
        plan = plan or plan_ingest(text, d)
        if approved and plan.get("action") not in ("create", "merge"):
            raise ValueError("invalid approved plan: action must be create or merge")
        if approved and plan.get("action") == "merge":
            if not plan.get("rev"):
                raise ValueError("invalid approved plan: missing revision for merge")
            target = plan.get("slug")
            if not target or not os.path.exists(_page_path(d, target)):
                raise ValueError("stale plan: merge target disappeared — re-run ingest")
        if plan["action"] == "merge" and plan.get("slug") and os.path.exists(_page_path(d, plan["slug"])):
            slug = plan["slug"]
            meta, body = _read(d, slug) or ({}, "")
            # crash가 정본 쓰기 후 approval finish 전에 발생했다면 stale rev보다 idempotence가 우선이다.
            if _fact_present(body, text):
                log_op(d, "ingest:unchanged", slug)
                return "unchanged", slug
            # 승인된 plan 은 리비전까지 대조 (2차 리뷰 ⑤) — 승인과 실행 사이 대상이 바뀌었으면 중단
            if approved and plan.get("rev") and plan["rev"] != _rev(d, slug):
                raise ValueError(f"stale plan: page '{slug}' changed since approval — re-run ingest")
            meta["updated"] = _today()
            if kind == "user" and _kind(meta) == "user":
                merged, action = _update_user_preference(body, text)
                if action == "unchanged":
                    log_op(d, "ingest:unchanged", slug)
                    return action, slug
                if action == "updated":
                    meta["title"] = _fm_value(next(ln.strip().lstrip("# ") for ln in text.splitlines() if ln.strip()))[
                        :80
                    ]
            else:
                merged = body.rstrip() + f"\n\n{_today()}: {text.strip()}"
                action = "merged"
            _atomic_write(_page_path(d, slug), render_page(meta, merged))
            write_index(d)
            with contextlib.suppress(Exception):
                conn = _db(d)
                with conn:
                    _fts_upsert(conn, d, slug)
                conn.close()
            log_op(d, f"ingest:{action}", slug, f"sim={plan.get('sim')}")
            return action, slug
        existing = next((slug for slug in _pages(d) if (pg := _read(d, slug)) and _fact_present(pg[1], text)), None)
        if existing:
            log_op(d, "ingest:unchanged", existing)
            return "unchanged", existing
        title = _fm_value(next(ln.strip().lstrip("# ") for ln in text.splitlines() if ln.strip()))[:80]
        slug, _ = _add_unlocked(d, text, title, kind, "", False)
        log_op(d, "ingest:created", slug)
        return "created", slug


def remove(slug: str, d: str | None = None) -> bool:
    """페이지 삭제 + 파생 재생성 (P2). 반환 = 삭제 성공 여부."""
    d = d or memory_dir()
    if not valid_slug(slug):
        raise ValueError(f"invalid slug: {slug!r}")
    with _lock(d):
        path = _page_path(d, slug)
        if not os.path.exists(path):
            return False
        os.remove(path)
        with contextlib.suppress(Exception):
            conn = _db(d)
            with conn:
                conn.execute("DELETE FROM fts WHERE slug = ?", (slug,))
                conn.execute("DELETE FROM usage WHERE slug = ?", (slug,))
            conn.close()
        write_index(d)
        log_op(d, "remove", slug)
    return True


def merge(src: str, dst: str, d: str | None = None) -> str:
    """src 를 dst 에 흡수하고 src 삭제 (P2, 예산 초과 수동 통합). 반환 = dst slug."""
    d = d or memory_dir()
    if not (valid_slug(src) and valid_slug(dst)):
        raise ValueError("invalid slug")
    if src == dst:  # 자기 병합 = 원본 삭제 사고 (2차 리뷰 ③)
        raise ValueError("src and dst are the same page")
    with _lock(d):
        ps, pd = _read(d, src), _read(d, dst)
        if ps is None or pd is None:
            raise ValueError("src or dst not found")
        dmeta, dbody = pd
        dmeta["updated"] = _today()
        merged = dbody.rstrip() + f"\n\n{_today()} (merged from {src}): {ps[1].strip()}"
        _atomic_write(_page_path(d, dst), render_page(dmeta, merged))
        os.remove(_page_path(d, src))
        with contextlib.suppress(Exception):
            conn = _db(d)
            with conn:
                conn.execute("DELETE FROM fts WHERE slug = ?", (src,))
                conn.execute("DELETE FROM usage WHERE slug = ?", (src,))
                _fts_upsert(conn, d, dst)
            conn.close()
        write_index(d)
        log_op(d, "merge", dst, f"← {src}")
    return dst


# ── lint — 위키 건강 점검 (Karpathy lint = 부패 방지의 기계화) ───────────────────────

# user 메모리 명령문 탐지 — 명확한 지시 어휘 결합에만 앵커 (false positive 회피).
_IMPERATIVE_PATTERNS = (
    re.compile(r"(항상|반드시|무조건|절대)\s+\S[^\n]*?(하라|해라|할 것|하세요|하지 ?마|해야 한다|금지)"),
    re.compile(r"^\s*(always|never|must|do not|don't)\b", re.IGNORECASE | re.MULTILINE),
)


def _imperative_phrase(body: str) -> str:
    """user 페이지의 명령문 탐지 — 매치 구절(절단)을 반환, 없으면 빈 문자열."""
    for pattern in _IMPERATIVE_PATTERNS:
        m = pattern.search(body)
        if m:
            return m.group(0)[:40]
    return ""


def lint(d: str | None = None) -> list[dict]:
    """기계 판정만 — 모순 탐지 같은 의미 판단은 LLM 몫(후속). 반환 = findings."""
    d = d or memory_dir()
    findings: list[dict] = []
    slugs = set(_pages(d))
    if not slugs:
        index_path = os.path.join(d, INDEX)
        if os.path.exists(index_path):
            try:
                if open(index_path, encoding="utf-8").read() != build_index(d):
                    findings.append(
                        {"level": "info", "code": "index-stale", "slug": INDEX, "msg": "run: asgard memory reindex"}
                    )
            except Exception:
                findings.append(
                    {"level": "info", "code": "index-stale", "slug": INDEX, "msg": "run: asgard memory reindex"}
                )
        return findings
    usage: dict[str, tuple[int, str]] = {}
    try:
        conn = _db(d)
        usage = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT slug, uses, last_used FROM usage")}
        conn.close()
    except Exception:
        pass
    today = _dt.date.today()
    docs: dict[str, str] = {}
    for slug in sorted(slugs):
        pg = _read(d, slug)
        if not pg:
            findings.append({"level": "error", "code": "unreadable", "slug": slug, "msg": "parse failed"})
            continue
        meta, body = pg
        docs[slug] = meta.get("title", "") + " " + body
        for ref in re.findall(r"\[\[([^\]]+)\]\]", body) + [
            s.strip() for s in meta.get("links", "").split(",") if s.strip()
        ]:
            if slugify(ref) not in slugs and ref not in slugs:
                findings.append({"level": "warn", "code": "dead-link", "slug": slug, "msg": f"[[{ref}]]"})
        # 외부 편집으로 스캔을 우회한 오염 소급 탐지 — 본문 + 주입 메타 전부, kind 포함 (P0)
        threat = poisoned(meta, body)
        if threat:
            findings.append({"level": "error", "code": "threat", "slug": slug, "msg": threat})
        # user 메모리는 선언문이어야 한다 — 명령문은 미래 세션에서 지시로 재해석되어
        # 사용자의 현재 요청을 덮어쓸 수 있다 ("사용자는 X를 선호한다" ✓ / "항상 X하라" ✗)
        if _kind(meta) == "user":
            imperative = _imperative_phrase(body)
            if imperative:
                findings.append(
                    {
                        "level": "warn",
                        "code": "imperative-user-memory",
                        "slug": slug,
                        "msg": f"명령문 감지({imperative}) — 선언문으로 바꾸세요 ('사용자는 …를 선호한다')",
                    }
                )
        try:
            updated = _dt.date.fromisoformat(meta.get("updated", meta.get("created", "")))
            uses = usage.get(slug, (0, None))[0]
            if (today - updated).days >= STALE_DAYS and uses == 0:
                findings.append(
                    {
                        "level": "info",
                        "code": "decay-candidate",
                        "slug": slug,
                        "msg": f"{(today - updated).days}d untouched, never recalled",
                    }
                )
        except Exception:
            findings.append({"level": "warn", "code": "no-date", "slug": slug, "msg": "missing/invalid updated:"})
    items = sorted(docs.items())
    for i, (s1, t1) in enumerate(items):
        for s2, t2 in items[i + 1 :]:
            if _jaccard(t1, t2) >= DUP_JACCARD:
                findings.append({"level": "warn", "code": "near-duplicate", "slug": s1, "msg": f"≈ {s2}"})
    size = len(build_index(d))
    if size > index_budget():
        findings.append(
            {"level": "warn", "code": "index-over-budget", "slug": INDEX, "msg": f"{size}/{index_budget()} chars"}
        )
    try:
        if open(os.path.join(d, INDEX), encoding="utf-8").read() != build_index(d):
            findings.append(
                {"level": "info", "code": "index-stale", "slug": INDEX, "msg": "run: asgard memory reindex"}
            )
    except Exception:
        findings.append({"level": "info", "code": "index-stale", "slug": INDEX, "msg": "run: asgard memory reindex"})
    return findings


# ── 동결 스냅샷 주입 — Heimdall 세션 생성 시 1회 ─────────────


def _neutralize(s: str) -> str:
    """주입면 경계 무력화 (P0) — 각괄호를 유사문자로 치환해 태그/펜스 탈출 차단."""
    return s.replace("<", "‹").replace(">", "›")


def _snapshot_rows(d: str) -> list[str]:
    """주입용 카탈로그 행 — 페이지 재검증(오염 제외) + 경계 무력화 + kind 화이트리스트.
    index.md 와 별도(주입 안전용)."""
    rows: list[str] = []
    for slug in _pages(d):
        pg = _read(d, slug)
        if not pg:
            continue
        meta, body = pg
        if poisoned(meta, body):
            continue  # 오염 페이지는 주입 제외 (lint 전이라도)
        title = _neutralize(meta.get("title", slug))
        rows.append(f"- {title} `{_kind(meta)}` — {_neutralize(_desc(meta, body))}")
    return rows


def snapshot_note(d: str | None = None) -> str:
    """세션 프롬프트 주입분 — 카탈로그를 예산 내로 동결. 페이지 없으면 빈 문자열 (무변화).

    "동결" 계약 = Heimdall 인스턴스 수명. self.identity 에 1회 결합 후 세션 중 불변
    (KV 캐시 보존). /lagom 등 Heimdall 재생성 경로에서만 재렌더된다."""
    try:
        if not inject_enabled():  # 킬스위치 (2차 리뷰 ⑦) — off 면 어느 provider 로도 전송 없음
            return ""
        d = d or memory_dir()
        rows = _snapshot_rows(d)
        if not rows:
            return ""
        budget = index_budget()
        prefix = (
            '\n\n<memory-context scope="personal">\n'
            "개인 메모리 카탈로그 (힌트 — 완료 증거 아님). 상세는 asgard memory query.\n"
        )
        suffix = "\n</memory-context>"
        lines, truncated = ["# Memory Index", ""], False
        if len(prefix + "\n".join(lines) + suffix) > budget:
            return ""
        for r in rows:
            if len(prefix + "\n".join([*lines, r]) + suffix) > budget:
                truncated = True
                break
            lines.append(r)
        if truncated:
            while len(lines) > 2 and len(prefix + "\n".join([*lines, _SNAPSHOT_WARN]) + suffix) > budget:
                lines.pop()
            if len(prefix + "\n".join([*lines, _SNAPSHOT_WARN]) + suffix) <= budget:
                lines.append(_SNAPSHOT_WARN)
        catalog = "\n".join(lines)
        return prefix + catalog + suffix
    except Exception:
        return ""  # fail-open — 메모리 불능이 세션을 막지 않는다


RECALL_BUDGET = 900  # chars — 회수 블록 상한 (턴마다 붙으므로 카탈로그보다 훨씬 작게)


def recall_note(text: str, k: int = 3, d: str | None = None) -> str:
    """요청 기반 zero-LLM 회수 블록 — DIRECT/Thinker 턴 시작 시 결정론 주입 (감사 권고:
    "모델이 자발적으로 CLI 를 부르는" 순응 의존을 없앤다). query 가 오염 페이지를 이미
    제외하므로 여기선 경계 무력화 + 예산만. 무적중·킬스위치 off = 빈 문자열 (무변화)."""
    try:
        if not inject_enabled():
            return ""
        hits = query(text, k=k, d=d)  # track=True — 회수 흔적이 lint 부패 판정 원료
        if not hits:
            return ""
        prefix = '\n\n<memory-recall scope="personal">\n요청 관련 개인 메모리 (힌트 — 완료 증거 아님):\n'
        suffix = "\n</memory-recall>"
        if len(prefix + suffix) > RECALL_BUDGET:
            return ""
        rows: list[str] = []
        for h in hits:
            title = _neutralize(str(h["title"]))[:120]
            row = f"- {title} `{h['kind']}` — {_neutralize(str(h['snippet']))[:160]}"
            if len(prefix + "\n".join([*rows, row]) + suffix) > RECALL_BUDGET:
                break
            rows.append(row)
        if not rows:
            return ""
        return prefix + "\n".join(rows) + suffix
    except Exception:
        return ""  # fail-open


DISTILL_MAX_PATHS = 3  # 넛지당 경로 상한 — 위치 지식의 최소 형태만, 목록 폭주 방지


def distill_nudge(request: str, response: str, root: str) -> str:
    """탐색 발견 저장 넛지 (0-LLM) — 응답에 인용된 '실존 파일 경로'만 증류해 기존 ingest
    승인 게이트로 안내한다. 저장은 ask-before-save 그대로 — 여기는 안내문뿐이다.

    응답 유래 자유 텍스트는 명령에 싣지 않는다: 디스크 실존 + root 격리 검증을 통과한
    경로 토큰만 후보가 된다 (모델 응답을 명령 제안으로 렌더링하는 표면의 인젝션 차단).
    숏컷 벤치(26-07-16) 근거 — 위치 지식이 recall 이득(토큰 -67%)의 최대 원천."""
    try:
        # 킬스위치는 여기서 라이브로 본다 — 호출측 플래그는 세션 생성 시점 캐시라
        # 세션 도중 ASGARD_MEMORY_INJECT=off 를 반영하지 못한다.
        if not inject_enabled():
            return ""
        req = re.sub(r"\s+", " ", (request or "")).strip().replace('"', "'")
        if not req or not response or scan_threats(req):
            return ""
        real_root = os.path.realpath(root)
        paths: list[str] = []
        for tok in re.findall(r"[\w][\w./\-]*\.[A-Za-z0-9_]+", response):
            p = tok.strip(".")
            if "/" not in p or os.path.isabs(p) or p.startswith((".asgard/", ".git/")):
                continue
            full = os.path.realpath(os.path.join(real_root, p))
            if os.path.commonpath([real_root, full]) != real_root:
                continue  # 경로 순회 시도 — 후보 자격 없음
            if p not in paths and os.path.isfile(full):
                paths.append(p)
            if len(paths) >= DISTILL_MAX_PATHS:
                break
        if not paths:
            return ""
        fact = f"{req[:80]} → {', '.join(paths)}"
        return f'🧠 탐색 발견 저장 후보 (승인 전엔 저장되지 않음):\n  asgard memory ingest "{fact}" --kind reference'
    except Exception:
        return ""  # fail-open — 넛지는 실행을 인질로 잡지 않는다
