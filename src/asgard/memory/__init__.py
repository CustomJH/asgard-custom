"""위그드라실 (Yggdrasil) — Asgard 메모리 시스템의 세계관 이름. 개인 메모리 = LLM Wiki 패턴
(Karpathy gist 442a6bf5) 의 파일 정본 계층.

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

패키지 구성 (파사드 — 공개 표면은 이 모듈에서 전부 재수출):
  policy(설정·게이트·인젝션 스캔) · store(파일시스템 원시·페이지 직렬화) ·
  index(index.md·state.db 파생) · recall(query·스냅샷·회수·증류 넛지) ·
  pages(add/ingest/remove/merge·lint) · okf(단방향 export)
"""

from __future__ import annotations

from .index import (
    _connect,
    _db,
    _fts_upsert,
    _index_row,
    _is_corrupt_db_error,
    _vec_prune,
    _vec_text,
    _vec_upsert,
    build_index,
    reindex,
    usage_stats,
    write_index,
)
from .okf import export_okf
from .pages import (
    _IMPERATIVE_PATTERNS,
    _PREFERENCE_PATTERNS,
    DUP_JACCARD,
    MERGE_CONTAINMENT,
    STALE_DAYS,
    _add_unlocked,
    _fact_present,
    _fresh_slug,
    _imperative_phrase,
    _preference_parts,
    _rev,
    _update_user_preference,
    add,
    ingest,
    lint,
    merge,
    plan_ingest,
    remove,
)
from .policy import (
    _THREATS,
    INDEX_BUDGET,
    MEMORY_ENV,
    _memory_settings,
    index_budget,
    inject_allowed,
    inject_enabled,
    memory_dir,
    scan_threats,
)
from .recall import (
    _SNAPSHOT_WARN,
    DISTILL_MAX_PATHS,
    RECALL_BUDGET,
    RRF_K,
    SEM_FLOOR,
    _containment,
    _grams,
    _jaccard,
    _neutralize,
    _sem_floor,
    _snapshot_rows,
    _track,
    distill_nudge,
    query,
    recall_note,
    snapshot_note,
)
from .store import (
    _SCHEMA_MD,
    DB,
    DEFAULT_KIND,
    INDEX,
    KINDS,
    LOG,
    PAGES,
    SCHEMA,
    _atomic_write,
    _chmod,
    _desc,
    _fm_value,
    _kind,
    _lock,
    _page_path,
    _pages,
    _read,
    _today,
    ensure_home,
    log_op,
    parse_page,
    poisoned,
    render_page,
    slugify,
    valid_slug,
)

__all__ = [
    "DB",
    "DEFAULT_KIND",
    "DISTILL_MAX_PATHS",
    "DUP_JACCARD",
    "INDEX",
    "INDEX_BUDGET",
    "KINDS",
    "LOG",
    "MEMORY_ENV",
    "MERGE_CONTAINMENT",
    "PAGES",
    "RECALL_BUDGET",
    "RRF_K",
    "SCHEMA",
    "SEM_FLOOR",
    "STALE_DAYS",
    "_IMPERATIVE_PATTERNS",
    "_PREFERENCE_PATTERNS",
    "_SCHEMA_MD",
    "_SNAPSHOT_WARN",
    "_THREATS",
    "_add_unlocked",
    "_atomic_write",
    "_chmod",
    "_connect",
    "_containment",
    "_db",
    "_desc",
    "_fact_present",
    "_fm_value",
    "_fresh_slug",
    "_fts_upsert",
    "_grams",
    "_imperative_phrase",
    "_index_row",
    "_is_corrupt_db_error",
    "_jaccard",
    "_kind",
    "_lock",
    "_memory_settings",
    "_neutralize",
    "_page_path",
    "_pages",
    "_preference_parts",
    "_read",
    "_rev",
    "_sem_floor",
    "_snapshot_rows",
    "_today",
    "_track",
    "_update_user_preference",
    "_vec_prune",
    "_vec_text",
    "_vec_upsert",
    "add",
    "build_index",
    "distill_nudge",
    "ensure_home",
    "export_okf",
    "index_budget",
    "ingest",
    "inject_allowed",
    "inject_enabled",
    "lint",
    "log_op",
    "memory_dir",
    "merge",
    "parse_page",
    "plan_ingest",
    "poisoned",
    "query",
    "recall_note",
    "reindex",
    "remove",
    "render_page",
    "scan_threats",
    "slugify",
    "snapshot_note",
    "usage_stats",
    "valid_slug",
    "write_index",
]
