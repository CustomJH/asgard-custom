"""검색·주입면 — RRF 3-스트림 query, usage 추적, 동결 스냅샷·회수 블록·증류 넛지."""

from __future__ import annotations

import datetime as _dt
import os
import re

from .index import _db
from .policy import _memory_settings, index_budget, inject_enabled, memory_dir, scan_threats
from .store import PAGES, _desc, _kind, _pages, _read, _today, poisoned

_SNAPSHOT_WARN = "- … (index over budget — asgard memory lint)"

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
SEM_FLOOR = 0.20  # 시맨틱 후보 진입 문턱 — 이 미만 코사인은 후보로도 안 넣는다(약연관 잡음 차단).
TEMPORAL_KINDS = frozenset({"reference"})
TEMPORAL_DAYS = 365
TEMPORAL_ALPHA = 0.20  # 최신성은 관련도를 대체하지 않고 최대 약 ±10%만 보정한다.
# 0.20 은 경량 정적 임베더(model2vec) 기준 실측 튜닝(26-07-18): 교차언어 정답이 랭크1이어도
# 절대 코사인이 0.18–0.29 로 낮아 0.30 은 이득을 죽였다. 강한 torch 모델(all-MiniLM 등)은
# 0.5–0.7 로 분리가 뚜렷해 이 문턱이 넉넉하다. config [memory].semantic_floor 로 조정 가능.


def _sem_floor() -> float:
    """시맨틱 후보 진입 문턱 — 설정 오버라이드 > SEM_FLOOR 기본. 모델 tier 에 맞춰 조정."""
    try:
        v = _memory_settings().get("semantic_floor")
        return float(v) if v is not None else SEM_FLOOR
    except Exception:
        return SEM_FLOOR


def _temporal_multiplier(meta: dict, today: _dt.date | None = None) -> float:
    """빠르게 낡는 reference만 보수적으로 보정한다. 날짜 불명·다른 kind는 중립."""
    if _kind(meta) not in TEMPORAL_KINDS:
        return 1.0
    try:
        updated = _dt.date.fromisoformat(str(meta.get("updated") or meta.get("created") or ""))
    except ValueError:
        return 1.0
    days = max(0, ((today or _dt.date.today()) - updated).days)
    recency = max(0.1, min(1.0, 1.0 - days / TEMPORAL_DAYS))
    return 1.0 + TEMPORAL_ALPHA * (recency - 0.5)


def query(text: str, k: int = 5, d: str | None = None, track: bool = True, explain: bool = False) -> list[dict]:
    """FTS5 trigram 검색 (한국어 substring 대응). hit 는 usage 를 남긴다 — lint 부패 판정 원료.

    랭킹 = RRF(rank fusion). BM25 값과 스캔 매칭 카운트는 척도가 달라 점수 혼합이 무의미하므로
    각 경로의 '순위'만 합산한다 (동점 = 동순위). RRF 동률은 reference 최신성 → usage 회수
    빈도 → slug 순으로 가른다 — 보조 신호는 관련도 순위를 넘지 못한다.
    오염 페이지는 결과에서 제외한다 (2차 리뷰 ② — query 출력은 에이전트 컨텍스트로 흘러간다).
    제외 수는 결과에 실리지 않고 lint 가 threat 로 보고한다.

    explain=True 면 각 hit 에 `streams`(fts/scan/semantic 경로별 적중 여부)를 덧붙인다 —
    랭킹·반환 순서는 불변, 대시보드의 스트림 출처 표시(읽기 전용)용 파생 정보일 뿐이다."""
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

    # 시맨틱 스트림 (옵트인 3번째 경로) — 활성 시에만. lexical 이 놓친 패러프레이즈/동의어를
    # 회수한다. 벡터는 state.db 파생물이고, 비활성이면 이 블록 전체가 건너뛰어져 기존 2경로와
    # 완전히 동일하게 동작한다 (무회귀 계약). 문턱 미만 코사인은 후보로도 넣지 않는다.
    sem_order: list[tuple[str, float]] = []
    from .. import memory_semantic as sem

    if sem.active():
        qv = sem.embed(text)
        if qv:
            floor = _sem_floor()
            scored: list[tuple[str, float]] = []
            try:
                conn = _db(d)
                rows = conn.execute("SELECT slug, data FROM vec").fetchall()
                conn.close()
            except Exception:
                rows = []
            for slug, data in rows:
                try:
                    cos = sem.cosine(qv, sem.unpack(data))
                except Exception:
                    continue
                if cos >= floor:
                    scored.append((slug, cos))
            scored.sort(key=lambda p: -p[1])
            for slug, cos in scored[: max(k, 10)]:
                if slug not in cand:
                    pg = _clean(slug)  # 시맨틱 전용 후보도 오염 제외
                    if not pg:
                        continue
                    meta, body = pg
                    matched, _s = _scan_score(meta, body)
                    cand[slug] = (meta, body, matched, _s)  # _s 0 가능 — 순수 시맨틱 진입
                sem_order.append((slug, cos))

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
    # 스캔 스트림엔 실제 lexical 매칭(s>0)만 — 순수 시맨틱 후보(s=0)가 스캔 순위를 훔치지 않게
    _add_ranks(sorted(((slug, float(c[3])) for slug, c in cand.items() if c[3] > 0), key=lambda p: -p[1]))
    _add_ranks(sem_order)  # 비활성이면 빈 리스트 → 무영향

    # 빠르게 낡는 reference만 시간 multiplier를 계산하되 RRF 동률 안에서만 쓴다.
    # k=60 RRF의 인접 순위 차가 작아 전역 곱셈은 약한 최신성만으로 강한 관련도를 뒤집는다.
    # user/decision/insight는 강등하지 않고, last_used도 자기강화 편향 때문에 쓰지 않는다.
    temporal_scores = {slug: rrf[slug] * _temporal_multiplier(cand[slug][0]) for slug in cand}

    # usage 는 RRF·시간 보정 동률 타이브레이크 전용 prior (힌트, 증거 아님)
    uses: dict[str, int] = {}
    try:
        conn = _db(d)
        uses = dict(conn.execute("SELECT slug, uses FROM usage").fetchall())
        conn.close()
    except Exception:
        pass

    # 경로별 적중 집합 (explain 전용 파생 — 랭킹엔 미개입). fts=BM25 경로, scan=lexical(s>0),
    # semantic=벡터 코사인 경로. RRF 합산에 쓴 그 순서 리스트와 동일 출처라 표시가 실사와 일치한다.
    fts_slugs = {s for s, _ in fts_order}
    scan_slugs = {s for s, c in cand.items() if c[3] > 0}
    sem_slugs = {s for s, _ in sem_order}

    hits: list[dict] = []
    for slug in sorted(cand, key=lambda s: (-rrf[s], -temporal_scores[s], -uses.get(s, 0), s))[:k]:
        meta, body, matched, _s = cand[slug]
        lb = body.lower()
        needle = phrase if phrase in lb else next((w for w in matched if w in lb), "")
        i = lb.find(needle) if needle else 0
        hit = {
            "slug": slug,
            "title": meta.get("title", slug),
            "kind": _kind(meta),
            "snippet": body[max(i - 40, 0) : i + 80].strip(),
            "score": round(rrf[slug], 4),
        }
        if explain:
            hit["streams"] = {
                "fts": slug in fts_slugs,
                "scan": slug in scan_slugs,
                "semantic": slug in sem_slugs,
            }
        hits.append(hit)
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
