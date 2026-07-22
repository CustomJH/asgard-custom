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
    fields = (body, meta.get("title", ""), meta.get("links", ""), meta.get("description", ""), meta.get("kind", ""))
    return scan_threats(*fields) or scan_secrets(*fields)


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
