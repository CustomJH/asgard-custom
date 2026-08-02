"""파일시스템 원시 계층 — 스캐폴드·권한·락·원자 쓰기·페이지 직렬화·읽기 헬퍼."""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import os
import re
from typing import Any

from .policy import memory_dir, scan_secrets, scan_threats

fcntl: Any = None  # posix 파일 락 — 없으면 msvcrt(Windows) 폴백, 둘 다 없으면 best-effort
msvcrt: Any = None
with contextlib.suppress(ImportError):
    import fcntl
with contextlib.suppress(ImportError):  # pragma: no cover — Windows 전용
    import msvcrt as _msvcrt

    msvcrt = _msvcrt

PAGES, INDEX, LOG, SCHEMA, DB = "pages", "index.md", "log.md", "SCHEMA.md", "state.db"
# 사람의 손이 남긴 것은 파생이 아니다 — 회수 기록(누가 실제로 이 페이지를 찾았는가)과
# 모순 처리 상태(사람이 이미 보고 넘긴 것인가)는 pages/ 에서 다시 만들 원본이 없다.
# 그래서 state.db 가 아니라 정본 옆에 텍스트로 산다 (memory.usage·memory.contradiction).
USAGE, CONTRADICTIONS = "usage.json", "contradictions.json"
KINDS = ("note", "user", "decision", "insight", "reference", "feedback")
DEFAULT_KIND = "note"
DEFAULT_SKILL_PREFERENCE_SLUG = "freyja-전체-스킬-조합-선호"

_DEFAULT_SKILL_PREFERENCE = """사용자는 프론트엔드·UI·모션·영상·3D 등 시각 작업에서 일부 익숙한 스킬에 편중하지 않고 Asgard의 현재 전체 스킬·플러그인 카탈로그를 확인해 적재적소에 조합하는 방식을 선호한다.

- `uv run asgard skills list --json`과 `uv run asgard plugins list --json`으로 현재 후보를 확인한다.
- 프로젝트 기존 컴포넌트와 Freyja 부모 계약을 우선하고, UI/UX 근거·컴포넌트 소싱·모션 레퍼런스·구현·성능·접근성·브라우저 검증 등 필요한 specialist만 지연 로드한다.
- 모든 스킬을 한꺼번에 주입하지 않는다. Vanadis 워크플로·레퍼런스·모션·접근성·카피·절제 게이트와 Playwright 검증 등 현재 카탈로그에서 과업에 맞는 조합을 선택하고 채택·기각 이유를 남긴다.
- 명시 호출 전용 스킬과 프로젝트의 기존 디자인 시스템·의존성 경계를 존중한다.
"""

_SCHEMA_MD = """# Memory Schema — 개인 위키 규약

이 디렉토리는 asgard 개인 메모리의 **정본**이다 (LLM Wiki 패턴).
`pages/*.md`가 지식이고, `index.md`·`state.db`·`maps/`는 재생성 가능한 파생물이다.

정본이 하나 더 있다 — **사람의 손이 남긴 것**. `usage.json`(무엇을 실제로 찾았는가)과
`contradictions.json`(어떤 어긋남을 보고 넘겼는가)은 `pages/`에서 다시 만들 수 없어서
파생물이 아니다. 지우면 부패 판정과 모순 알림이 처음 상태로 돌아간다.

## 페이지 규약
- 파일 = 사실/개체/개념 1개. frontmatter: `title` / `kind` / `created` / `updated` / `links`
- kind: note | user | decision | insight | reference | feedback
- 본문은 자립적으로 — 다른 페이지는 [[slug]]로 연결
- 코드/저장소에서 1분 내 파악 가능한 사실은 저장하지 않는다

## 운영 (asgard memory <op>)
- ingest: 새 지식 흡수 — 근사 중복은 기존 페이지에 병합 (승인 게이트 경유)
- query: FTS 검색 — 가치 있는 종합 결과는 add로 새 페이지 승격 (복리)
- lint: 건강 점검 — 고아·죽은 링크·부패 후보·중복 쌍·칸 예산 초과·오염
- merge/remove: 통합·삭제 (넘친 칸 해소) · reindex: pages/ 에서 파생 전체 재생성

## 불변식
- 저장에는 상한이 없다 — 예산은 **주입면**에만 걸린다 (지식은 언제나 pages/ 에 남는다)
- 주입 카탈로그는 kind 별로 칸이 나뉘고 칸마다 상한이 있다 — 넘친 칸은 머리글에 100% 초과로
  표시되고 lint가 그 칸을 지목한다: 그 칸만 병합·삭제로 통합하라
- 여기 저장된 무엇도 게이트의 완료 증거가 될 수 없다 (메모리는 힌트다)
- **개인 스코프 전용** — 이 위키의 내용·용어(개인 약어, 세계관 용어, 사적 축약)는
  프로젝트 공유 메모리로 그대로 내보내지 않는다. 공유 스코프에 쓸 때는 프로젝트
  공용 어휘(온톨로지)로 다시 서술한다 (용어 방화벽, 26-07-15).
  **이 하나는 기계가 안 막는다** — 모델의 순응에 기댄다 (`project_memory.records.validate_record`
  는 scope·kind·provenance·인젝션·credential 은 보지만 어휘는 안 본다). 위 다른 불변식들과
  달리 어긋나도 아무 데서도 걸리지 않으니, 읽는 사람이 집행이 있다고 믿으면 안 된다.
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
    for name in (DB, f"{DB}-wal", f"{DB}-shm", ".lock", USAGE, CONTRADICTIONS):
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
    fh = open(os.path.join(d, ".lock"), "a+", encoding="utf-8")
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
    global _WRITES
    d = os.path.dirname(path)
    tmp = os.path.join(d, f".{os.path.basename(path)}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    _chmod(tmp, 0o600)
    os.replace(tmp, path)
    _WRITES += 1  # 이 프로세스의 쓰기는 아래 읽기 캐시를 즉시 무효화한다


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


# ── 단일값 정체성 슬롯 ────────────────────────────────────────────────────────
# 사용자당 답이 하나뿐인 사실. 새 값은 옛 값 옆에 쌓이는 게 아니라
# 옛 값을 대체한다. 26-07-26 실측: "이름=썬더오브갓"(07-21 13:27)과 "이름=번개썬더왕"(07-21
# 14:05)이 containment 0.214로 갈려 각자 페이지가 됐고, 회상이 둘을 0.016/0.016으로 나란히
# 돌려주는 바람에 에이전트가 "어느 쪽입니까"밖에 답할 수 없게 됐다. 슬롯이 없으면 저장소는
# 사용자가 마음을 바꿀 때마다 모순을 하나씩 늘린다.
_SLOT_SUBJECT = r"(?:사용자|유저|오딘|나|내|저|제|the\s+user|user|my)"
_IDENTITY_SLOTS = (
    ("name", r"이름|성함|닉네임|별명|호칭|name|nickname"),
    ("birthday", r"생일|생년월일|birth\s*day|date\s+of\s+birth"),
    ("timezone", r"타임존|시간대|time\s*zone"),
    ("email", r"이메일|메일\s*주소|e-?mail"),
    ("language", r"모국어|주\s*사용\s*언어|native\s+language"),
)
# 주어부에 붙은 슬롯어만 인정한다 — 본문 아무 데나 "이름"이 나온다고 정체성 사실은 아니다
# ("helios-fe의 번역 키 이름 규칙은…"). 주어와 슬롯어 사이는 수식어 한 뭉치까지만 허용.
_SLOT_PATTERNS = tuple(
    (
        slot,
        re.compile(
            # "사용자의 canonical 이름/호칭은" — 수식어 한 뭉치와 슬래시로 이어붙인 슬롯어를 함께 허용
            rf"^{_SLOT_SUBJECT}\s*(?:의)?\s*(?:[^\s,.]{{1,12}}\s+)?"
            rf"(?:{words})(?:\s*[/·,]\s*(?:{words}))*\s*(?:은|는|이|가|:|\s+is\b)",
            re.IGNORECASE,
        ),
    )
    for slot, words in _IDENTITY_SLOTS
)
# "…라고 불러" 계열 — 주어(나를…)·지속 부사(이제부터…)·맨 명령형(…라고 불러줘) 셋 다 호칭 선언이다
_CALL_ME_PAT = re.compile(
    rf"^{_SLOT_SUBJECT}\s*(?:를|을|는|은)?\s*.{{0,30}}?(?:이?라고?\s*(?:불러|부르)|call\s+me)"
    r"|(?:이제부터|앞으로|앞으론|지금부터)\s+[^?]{1,30}?(?:이?라고?|이?라)\s*(?:불러|부르)"
    r"|[^\s?]{1,20}\s*(?:이?라고?|이?라)\s*(?:불러|부르)(?:줘|라|주세요|세요|주라)"
    # "call me back/when done"은 호칭 선언이 아니다 — 시간·조건 꼬리를 배제한다
    r"|\bcall\s+me\b(?!\s+(?:when|if|back|after|before|at|on|in|later|tomorrow|asap|once))",
    re.IGNORECASE,
)


def _identity_slot(text: str) -> str | None:
    """단일값 정체성 슬롯 이름 — 해당 없으면 None. 날짜 prefix 병합분도 같은 문장으로 본다."""
    statement = re.sub(r"^\d{4}-\d{2}-\d{2}(?:\s*\([^)]*\))?:\s*", "", text.strip())
    for slot, pattern in _SLOT_PATTERNS:
        if pattern.search(statement):
            return slot
    return "name" if _CALL_ME_PAT.search(statement) else None


# 질의어 판정용 슬롯 낱말 — 슬롯 표는 정규식이라 메타문자 없는 순수 낱말만 골라 쓴다.
# 낱말 하나를 찾는 규칙: 앞은 낱말 경계로 닫고, 뒤는 한글 꼬리 세 글자까지만 연다.
#   · 앞을 안 닫으면 "filename"이 name 슬롯을 깨워 정체성 동의어 일곱 개가 질의에 붙는다.
#     그 낱말들은 파일 이름과 아무 상관이 없고, 회수 어휘만 오염시킨다 (실측 26-08-01).
#   · 뒤를 딱 닫으면 정작 한국어 질의가 죽는다 — 조사·어미가 낱말 **뒤**에 붙어서 "이름은",
#     "이름이"가 서로 남남이 된다. 꼬리 상한 3은 `recall._stopword`가 쓰는 것과 같은 값이다.
_SLOT_QUERY_WORDS = tuple(
    (
        [w for w in words.split("|") if re.fullmatch(r"\w+", w)],
        [
            re.compile(rf"(?<!\w){re.escape(w)}[가-힣]{{0,3}}(?!\w)", re.IGNORECASE)
            for w in words.split("|")
            if re.fullmatch(r"\w+", w)
        ],
    )
    for _slot, words in _IDENTITY_SLOTS
)


def slot_query_aliases(text: str) -> list[str]:
    """질의어에 슬롯 낱말이 **낱말로** 있으면 그 슬롯의 동의어 전부 — 없으면 빈 리스트.

    승계는 정본의 어휘를 바꾼다("이름은 X" → "호칭은 X"). lexical 경로는 동의어를 모르므로
    그 순간 "내 이름이 뭐야"가 회수에 실패한다. 색인이 아니라 질의를 넓히는 이유: FTS 행은
    파생물이라 회수 경로가 정본으로 재검증하고(recall.query), 정본에 없는 낱말은 거기서 탈락한다."""
    for plain, patterns in _SLOT_QUERY_WORDS:
        if any(pattern.search(text) for pattern in patterns):
            return list(plain)
    return []


def slugify(title: str) -> str:
    """유니코드(한국어) 보존 슬러그 — 공백→하이픈, 경로 위험 문자 제거. 빈 결과는 해시."""
    s = re.sub(r"[\s]+", "-", title.strip().lower())
    s = re.sub(r"[^\w\-가-힣]", "", s, flags=re.UNICODE).strip("-")[:64]
    return s or hashlib.sha1(title.encode()).hexdigest()[:12]


def valid_slug(slug: str) -> bool:
    """슬러그 형식 검증 (P0) — slugify 산출 문자셋과 동일. 경로 구분자·점·과길이 배제."""
    return bool(slug) and len(slug) <= 80 and re.fullmatch(r"[\w\-가-힣]+", slug, re.UNICODE) is not None


def _page_path(d: str, slug: str) -> str:
    """pages/<slug>.md — realpath가 pages/ 하위임을 강제 (경로 순회 차단, P0)."""
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


def seed_defaults(d: str | None = None) -> list[str]:
    """첫 setup의 빈 개인 위키에만 패키지 기본 선호를 심는다. 기존 페이지는 건드리지 않는다."""
    d = ensure_home(d)
    with _lock(d):
        if _pages(d):
            return []
        meta = {
            "title": "Freyja 전체 스킬 조합 선호",
            "kind": "user",
            "created": _today(),
            "updated": _today(),
        }
        _atomic_write(
            _page_path(d, DEFAULT_SKILL_PREFERENCE_SLUG),
            render_page(meta, _DEFAULT_SKILL_PREFERENCE),
        )
    from .index import reindex

    reindex(d)
    log_op(d, "seed:user", DEFAULT_SKILL_PREFERENCE_SLUG)
    return [DEFAULT_SKILL_PREFERENCE_SLUG]


def _read(d: str, slug: str) -> tuple[dict, str] | None:
    try:
        with open(_page_path(d, slug), encoding="utf-8") as handle:
            return parse_page(handle.read())
    except Exception:  # 없음·파싱 실패·경로 순회 시도 전부 None (fail-safe)
        return None


def _read_all(d: str) -> list[tuple[str, dict, str]]:
    """살아 있는 페이지를 한 번에 읽는다 — (slug, meta, body) 목록.

    파생 목차 둘(`index.md` 카탈로그와 `maps/`)이 같은 파일을 각자 다시 열고 있었다. 둘 다
    페이지를 저장할 때마다 도는 경로라, 쓰기 한 번이 읽기 2N 번이었다. 읽는 자리를 여기 하나로
    모으고 결과를 나눠 쓴다 — 두 목차의 내용은 글자 그대로 같고 여는 횟수만 절반이 된다.
    못 읽는 페이지는 빠진다 (호출자 둘 다 원래 그렇게 다뤘다)."""
    rows: list[tuple[str, dict, str]] = []
    for slug in _pages(d):
        page = _read(d, slug)
        if page:
            rows.append((slug, *page))
    return rows


# ── 읽은 결과를 소비자들이 나눠 쓴다 (프로세스 수명 캐시) ─────────────────────────────
#
# `_read_all`은 **한 호출 안의** 중복 읽기를 없앴는데, 한 턴 안에서 그 호출 자체가 여러 번
# 일어난다: 회수(`recall.query`)·주입 카탈로그(`recall._snapshot_rows`)·건강 점검
# (`pages.lint`)이 각자 전량을 연다. 1,000페이지에서 회수 하나가 읽기 1,000번이고, 그 뒤
# 카탈로그가 같은 파일을 다시 1,000번 연다 (실측 26-08-02).
#
# 캐시가 언제 죽는가 — 두 축으로 본다.
#   ① 이 프로세스의 쓰기: `_atomic_write`가 `_WRITES`를 올린다. 쓰기 뒤 읽기는 무조건 새로 연다.
#   ② 남의 프로세스·외부 편집: 페이지 디렉터리의 stat 지문(이름·크기·mtime_ns)이 다르면 새로
#      연다. `index._pages_fingerprint`가 vec 커버리지 메모에 쓰는 것과 같은 자다.
# 지문을 못 재면(권한·경쟁) 빠른 길이 없다 — 못 믿을 때 캐시를 쓰는 일은 없다 (fail-safe).
#
# 반환 리스트는 **공유물**이라 호출자가 고치면 안 된다 (지금 소비자 전부 읽기만 한다).
_WRITES = 0
_READ_CACHE: dict[str, tuple[str, list[tuple[str, dict, str]]]] = {}
# 디렉터리당 하나만 들고 있는다. 이 상한을 넘는 위키는 캐시를 아예 안 만든다 — 회수 한 번
# 아끼자고 프로세스가 본문 전량을 상주시키면 그건 다른 종류의 비용이다.
_READ_CACHE_MAX_CHARS = 8_000_000


def _pages_fingerprint(d: str) -> str:
    """페이지 디렉터리의 stat 지문 — 이름·크기·mtime만 본다 (파일을 열지 않는다).

    `documents.py`의 `_manifest`와 같은 규율이다. 읽기가 0 인 이유는 `os.scandir`이 항목마다
    stat을 사실상 공짜로 주기 때문이고, 그래서 이 지문은 "확인해 둔 결론을 재사용해도 되는가"의
    싸고 보수적인 답이 된다. 실패하면 빈 문자열 — 지문이 없으면 빠른 길도 없고, 정확한 경로가
    돈다 (fail-safe: 캐시를 못 믿을 때 캐시를 쓰는 일은 없다)."""
    try:
        rows = []
        with os.scandir(os.path.join(d, PAGES)) as entries:
            for entry in sorted(entries, key=lambda row: row.name):
                if not entry.name.endswith(".md"):
                    continue
                info = entry.stat()
                rows.append(f"{entry.name}:{info.st_size}:{info.st_mtime_ns}")
        return hashlib.sha256("|".join(rows).encode()).hexdigest()
    except OSError:
        return ""


def _pages_token(d: str) -> str:
    """이 시점의 페이지 형상 표 — 같으면 지난 읽기를 그대로 쓴다. 못 재면 빈 문자열."""
    fingerprint = _pages_fingerprint(d)
    return f"{_WRITES}:{fingerprint}" if fingerprint else ""


def _read_all_cached(d: str) -> list[tuple[str, dict, str]]:
    """`_read_all`과 같은 값 — 형상이 그대로면 지난 읽기를 돌려준다 (위 절의 두 축 참조)."""
    token = _pages_token(d)
    if not token:
        return _read_all(d)
    key = os.path.realpath(d)
    hit = _READ_CACHE.get(key)
    if hit is not None and hit[0] == token:
        return hit[1]
    rows = _read_all(d)
    if sum(len(body) for _slug, _meta, body in rows) <= _READ_CACHE_MAX_CHARS:
        _READ_CACHE[key] = (token, rows)
    else:
        _READ_CACHE.pop(key, None)
    return rows


def _read_cache_clear() -> None:
    """읽기 캐시 폐기 — 테스트와 장기 프로세스의 명시적 손잡이."""
    _READ_CACHE.clear()


def _desc(meta: dict, body: str) -> str:
    line = meta.get("description") or next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    return line[:90]


def _kind(meta: dict) -> str:
    """kind 화이트리스트 강제 (2차 리뷰 ①) — 외부 편집으로 심은 임의 문자열이 표시/주입면에
    도달하지 못한다. 미등재 kind는 note로 강등."""
    k = meta.get("kind", DEFAULT_KIND)
    return k if k in KINDS else DEFAULT_KIND


def _poison_fields(meta: dict, body: str) -> tuple[str, ...]:
    """오염 판정이 보는 필드 — 판정과 캐시 키가 **같은 자리**에서 나와야 한다.

    키가 판정보다 좁으면 안 보는 필드를 고쳐도 캐시가 안 깨진다: title 에 심은 위협이 조용히
    통과한다. 그래서 두 함수가 이 하나를 부른다."""
    return (
        body,
        str(meta.get("title", "")),
        str(meta.get("links", "")),
        str(meta.get("description", "")),
        str(meta.get("kind", "")),
    )


def poisoned(meta: dict, body: str) -> str | None:
    """페이지 오염 판정 — 주입 가능한 모든 필드(본문·title·links·description·kind)."""
    fields = _poison_fields(meta, body)
    return scan_threats(*fields) or scan_secrets(*fields)


def poison_key(meta: dict, body: str) -> str:
    """오염 판정의 캐시 키 — 판정이 보는 필드 전부의 sha1.

    판정은 모델이 필요 없는 결정론이라 같은 입력이면 같은 답이다. 그런데 회수는 매 턴 돌고
    페이지마다 위협 정규식 스물 몇 개 × 필드 다섯을 다시 돌린다 — 1,000페이지에서 회수 한 번의
    71%가 이 재계산이었다 (실측 26-08-02). 본문 sha 로 접어 두면 `index._vec_upsert`가 벡터에
    쓰는 것과 같은 규율이 되고, 파생이므로 지워도 다시 나온다."""
    digest = hashlib.sha1()
    for field in _poison_fields(meta, body):
        digest.update(field.encode())
        digest.update(b"\x00")  # 필드 경계 — 이어 붙인 두 필드가 다른 조합과 같아지지 않게
    return digest.hexdigest()


_RULESET: str = ""


def poison_ruleset() -> str:
    """위협·credential 표의 지문 — 표가 바뀌면 접어 둔 판정을 전부 버려야 한다.

    `_vec_upsert`가 임베더 이름(`vec_model`)으로 하는 일과 같다: 캐시된 값이 **어느 자로 잰
    것인가**를 같이 적어 두지 않으면, 자를 갈아도 낡은 답이 조용히 살아남는다. 표를 넓히는
    개정(26-07-31 처럼)이 실제로 일어나므로 계약으로 둔다."""
    global _RULESET
    if not _RULESET:
        from .policy import _INVISIBLE, _SECRET_PATTERNS, _SECRET_PLACEHOLDERS, _TAG_RANGE, _THREATS

        parts = [
            *_THREATS,
            *(pattern.pattern for pattern in _SECRET_PATTERNS),
            *_SECRET_PLACEHOLDERS,
            *sorted(_INVISIBLE),
            str(_TAG_RANGE),
        ]
        _RULESET = hashlib.sha1("\x00".join(parts).encode()).hexdigest()[:16]
    return _RULESET


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
