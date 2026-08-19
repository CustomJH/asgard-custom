"""위그드라실 (Yggdrasil) — Asgard 메모리 시스템의 세계관 이름. 개인 메모리 = LLM Wiki 패턴
(Karpathy gist 442a6bf5)의 파일 정본 계층.

귀속 (26-07-23 확정 · 26-07-28 경계 명시): 메모리는 **소유자 스코프**다. 지금 개인 메모리의
소유자는 오딘(사용자) — 오딘의 기억이면서, 오딘을 섬기는 에이전트가 자신의 기억처럼 빌려 쓴다
(소유=오딘, 사용=에이전트). 사용자 표면 설명도 현재는 오딘 귀속으로 말한다
(templates/agents.py asgard:memory · templates/memory.py 계약).

**소유자는 고정값이 아니라 변수다.** 지금 오딘인 것은 프로파일 시스템이 아직 없기 때문이고,
프로파일이 생기면 같은 메커니즘에 소유자만 바뀌어 **이 메모리는 에이전트의 것이 된다**
(오딘 정정 26-07-28). 그러니 새 표면을 지을 때 귀속을 "오딘"이라는 낱말로 굳히지 말 것 —
소유자를 참조하는 형태로 써 두면 프로파일이 붙는 순간 문구가 아니라 값만 갈린다.

원칙 (memory v3, 26-07-15 확정):
  정본 = ~/.asgard/memory/ 의 md 파일 (사람이 읽고 고칠 수 있는 텍스트 —
  바이너리-in-git 사고의 반성). state.db(FTS5)·index.md는 pages/ 에서
  기계적으로 재생성되는 파생물 — 지워도(또는 손상돼도) 지식은 죽지 않는다.

구조:  SCHEMA.md(규약) · index.md(카탈로그) · log.md(append-only 운영 로그)
       · pages/<slug>.md(frontmatter+본문) · state.db(FTS5·vec 파생 인덱스+회수 계수)
       · usage.json(회수 기록) · contradictions.json(미해결 모순 장부)

정본과 파생을 가르는 자는 "pages/ 에서 다시 만들 수 있는가" 하나다. 뒤의 두 JSON 이 정본
쪽에 있는 이유가 여기 있다 — 사람이 무엇을 찾았는지와 무엇을 보고 넘겼는지는 페이지에서
재생되지 않는다. 예전에 회수 기록이 state.db 에만 있었고, 그래서 파생물을 지우는 정상
경로가 원본 데이터를 같이 지웠다 (memory.usage · memory.contradiction).

보안 (P0, 감사 26-07-15 반영): 메모리는 시스템 프롬프트에 주입되므로 오염이 세션
전체·세션 간 지속된다. 방어 — ① 쓰기 시 본문+메타데이터(title/links) 전부 인젝션
스캔 ② frontmatter 값 개행 금지(가짜 필드 삽입 차단) ③ snapshot 주입 시 페이지
재검증(오염 제외) + 경계 문자 무력화(펜스 탈출 차단) ④ slug realpath 봉쇄(경로 순회).

무결성 (P1): 실제 렌더 기준 예산 하드게이트 · 원자 쓰기(고유 temp) · 프로세스 락 ·
승인된 plan 그대로 실행 · 손상 DB 자동 재생성. 전 경로 fail-open (읽기).

자가 관리: ingest는 근사 중복을 기존 페이지 병합으로 흡수, query가 사용 흔적을
남기고, lint가 고아·죽은 링크·부패·중복·예산·오염을 기계 판정. 게이트는 메모리를
신뢰하지 않는다 — 여기 저장된 무엇도 완료 증거가 아니다.

패키지 구성 (파사드 — 공개 표면은 이 모듈에서 전부 재수출):
  policy(설정·게이트·인젝션 스캔) · store(파일시스템 원시·페이지 직렬화) ·
  index(index.md·state.db 파생) · recall(hybrid RRF+명시-link PPR·스냅샷·회수·증류 넛지) ·
  pages(add/ingest/remove/merge·lint) · usage(노출/사용 구분·회수 기록 정본) ·
  contradiction(미해결 모순 장부) · okf(단방향 export)
"""

from __future__ import annotations

from .contradiction import (
    acknowledge_contradiction,
    contradiction_key,
    open_contradictions,
)
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
    vec_coverage,
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
    retitle,
)
from .policy import (
    _THREATS,
    AUTOSAVE_ENV,
    INDEX_BUDGET,
    KIND_BUDGETS,
    MEMORY_ENV,
    _memory_settings,
    autosave_enabled,
    index_budget,
    inject_allowed,
    inject_enabled,
    kind_budgets,
    memory_dir,
    scan_invisible,
    scan_secrets,
    scan_threats,
)
from .recall import (
    _SNAPSHOT_WARN,
    DISTILL_MAX_PATHS,
    RECALL_BUDGET,
    RECALL_PREFIX,
    RECALL_SUFFIX,
    RERANK_DISPERSION_FLOOR,
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
    recall_rows,
    section_usage,
    snapshot_note,
)
from .store import (
    _SCHEMA_MD,
    CONTRADICTIONS,
    DB,
    DEFAULT_KIND,
    DEFAULT_SKILL_PREFERENCE_SLUG,
    INDEX,
    KINDS,
    LOG,
    PAGES,
    SCHEMA,
    TITLE_MAX,
    USAGE,
    _atomic_write,
    _chmod,
    _desc,
    _fm_value,
    _kind,
    _lock,
    _page_path,
    _pages,
    _read,
    _read_all,
    _today,
    derive_title,
    ensure_home,
    log_op,
    parse_page,
    poisoned,
    render_page,
    seed_defaults,
    slugify,
    strip_speaker,
    valid_slug,
)
from .temporal import event_date, ground_event_date
from .usage import counters as usage_counters
from .usage import flush as usage_flush
from .usage import forget as usage_forget
from .usage import hydrate as usage_hydrate
from .usage import usage_of

__all__ = [
    "AUTOSAVE_ENV",
    "CONTRADICTIONS",
    "DB",
    "DEFAULT_KIND",
    "DEFAULT_SKILL_PREFERENCE_SLUG",
    "DISTILL_MAX_PATHS",
    "DUP_JACCARD",
    "INDEX",
    "INDEX_BUDGET",
    "KIND_BUDGETS",
    "KINDS",
    "LOG",
    "MEMORY_ENV",
    "MERGE_CONTAINMENT",
    "PAGES",
    "RECALL_BUDGET",
    "RECALL_PREFIX",
    "RECALL_SUFFIX",
    "RERANK_DISPERSION_FLOOR",
    "RRF_K",
    "SCHEMA",
    "SEM_FLOOR",
    "STALE_DAYS",
    "USAGE",
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
    "_read_all",
    "_rev",
    "_sem_floor",
    "_snapshot_rows",
    "_today",
    "_track",
    "_update_user_preference",
    "_vec_prune",
    "_vec_text",
    "_vec_upsert",
    "acknowledge_contradiction",
    "add",
    "autosave_enabled",
    "build_index",
    "contradiction_key",
    "distill_nudge",
    "ensure_home",
    "export_okf",
    "index_budget",
    "kind_budgets",
    "ingest",
    "inject_allowed",
    "inject_enabled",
    "TITLE_MAX",
    "derive_title",
    "strip_speaker",
    "lint",
    "retitle",
    "log_op",
    "memory_dir",
    "merge",
    "open_contradictions",
    "parse_page",
    "plan_ingest",
    "poisoned",
    "query",
    "recall_note",
    "recall_rows",
    "reindex",
    "remove",
    "render_page",
    "scan_threats",
    "scan_invisible",
    "scan_secrets",
    "seed_defaults",
    "slugify",
    "event_date",
    "ground_event_date",
    "section_usage",
    "snapshot_note",
    "usage_counters",
    "usage_flush",
    "usage_forget",
    "usage_hydrate",
    "usage_of",
    "usage_stats",
    "valid_slug",
    "vec_coverage",
    "write_index",
]
