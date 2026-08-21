"""RRF 회수 — FTS·스캔·시맨틱·그래프 네 스트림을 합치고 구절 리랭크와 융합한다. 적중은 사용 흔적을 남긴다."""

from __future__ import annotations

import datetime as _dt
import os
import re

from ..index import _db
from ..policy import _memory_settings, memory_dir
from ..store import PAGES, _kind, slot_query_aliases
from ..temporal import event_date
from .clean import clean_pages
from .ppr import _graph_order
from .rerank import RERANK_BASE_WEIGHT, RERANK_CANDIDATES, _rerank_order, rerank_enabled
from .rows import SNIPPET_MAX
from .stems import _KO_ENDINGS, _KO_PARTICLES

# ── 검색 (query) — LLM 0. trigram FTS, 실패 시 파일 스캔 fail-open ─────────────────


RRF_K = 60  # rank-fusion 표준 상수 — 상위 랭크 간 격차를 완만히 눌러 단일 경로 독주를 막는다
SEM_FLOOR = 0.20  # 시맨틱 후보 진입 문턱 — 이 미만 코사인은 후보로도 안 넣는다(약연관 잡음 차단).
TEMPORAL_KINDS = frozenset({"reference"})
TEMPORAL_DAYS = 365
TEMPORAL_ALPHA = 0.20  # 최신성은 관련도를 대체하지 않고 최대 약 ±10%만 보정한다.


# 0.20은 경량 정적 임베더(model2vec) 기준 실측 튜닝(26-07-18): 교차언어 정답이 랭크1이어도
# 절대 코사인이 0.18–0.29로 낮아 0.30은 이득을 죽였다. 강한 torch 모델(all-MiniLM 등)은
# 0.5–0.7로 분리가 뚜렷해 이 문턱이 넉넉하다. config [memory].semantic_floor로 조정 가능.


def _sem_floor() -> float:
    """시맨틱 후보 진입 문턱 — 설정 오버라이드 > SEM_FLOOR 기본. 모델 tier에 맞춰 조정."""
    try:
        v = _memory_settings().get("semantic_floor")
        return float(v) if v is not None else SEM_FLOOR
    except Exception:
        return SEM_FLOOR


# 어휘가 안 잡은 단독 시맨틱 후보에 더 높은 문턱(0.35)을 걸어 봤고 **되돌렸다** (26-08-04).
# 개인 위키 9장에서는 잡음이 걷혔지만(오답 42%→2.5%), 이득이 측정된 코퍼스는 그쪽이 아니었다:
# benchmarks/hybrid-search 의 100장 대조에서 crosslingual hit@5 가 0.80 → 0.20 으로 떨어졌다
# (문턱 0.20 에서 0.80, 0.30·0.35·0.40 에서 모두 0.20 — 문턱 하나가 원인). 어휘가 못 찾는 것이
# 곧 교차언어의 정의라 그 후보가 정확히 이 갈래로 들어온다. 작은 저장소의 잡음은 실재하지만,
# 두 코퍼스를 같이 만족하는 값은 아직 없다 — 고칠 때는 절대 문턱이 아니라 질의별 분산
# (`_dispersion`, 리랭크 QPP 게이트와 같은 자)으로 접근할 것.


def _word_matcher(word: str):
    """스캔 토큰 하나의 매칭 규칙 — 라틴 토큰은 낱말 경계, 그 밖은 부분문자열.

    한국어는 어절이 낱말 경계와 어긋나고 조사·어미가 붙으므로 부분문자열 매칭이 회수의
    전제다(`query` 의 `_KO_PARTICLES` 갈래). 라틴 문자에는 그 전제가 없는데 같은 규칙을 받아
    영어 토큰이 더 긴 영어 낱말 **안쪽**에 걸렸다. 실측 26-08-20, 질의 `approval round trip
    for saving memories` 를 개인 위키 56장에 건 결과: `round` 가 `grounding` 안쪽에서 36장,
    `for` 가 `platform`·`before` 안쪽에서 3장, 합쳐 39장이 스캔 점수 1 로 동점이 됐다. 그
    동점이 문턱을 넘은 유일한 시맨틱 증거를 52건 중 41위까지 밀었다. 경계를 걸면 `round` 는
    0장, `for` 는 1장이 되고 같은 정답이 2위로 올라온다. 오딘의 LLM 행 기본 프롬프트가
    영어라 이 경로는 드물지 않다 — 질의는 영어인데 이 위키의 본문은 한국어다.

    경계 문자를 `[a-z0-9]` 로 좁히고 `-`·`_` 는 뺐다. 이 위키의 정본 어휘가 `asgard-verifier`
    ·`memory_bridge` 처럼 이어져 있어서, 그 둘까지 경계에 넣으면 같은 코퍼스에서 `memory` 가
    3장 → 0장, `asgard` 가 21장 → 13장으로 줄어든다. 부분문자열이 정말 필요한 라틴 질의는
    FTS trigram 스트림이 그대로 회수한다."""
    if word.isascii():
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])")
        return lambda hay: pat.search(hay) is not None
    return lambda hay: word in hay


def _add_ranks(scores: dict[str, float], ordered: list[tuple[str, float]], weight: float = 1.0) -> None:
    """동점 구간은 그 구간의 **마지막** 순위를 함께 받는다 (수정 경쟁 순위).

    구간의 첫 순위를 주면 동점 구간의 크기가 기여에서 사라진다. 실측 26-08-20:
    `approval round trip for saving memories` 에서 스캔 점수 1 로 묶인 39장이 전부
    rank 1 = 1/(60+1) = 0.016393 을 받아, 문턱을 넘은 유일한 시맨틱 증거(코사인 0.429,
    2위 0.166)와 소수점까지 같은 점수가 됐다. 마지막 순위를 주면 그 39장은 구간 끝
    순위를 함께 받고, 단독 1위인 증거는 rank 1 을 그대로 지킨다 — 39장 중 아무거나
    하나만 맞은 것과 57장 중 하나만 맞은 것을 같은 값으로 세지 않는다.

    구간 안에서 i+1 을 쓰지 않는 이유: scan_order 는 점수가 같은 원소들의 상대 순서가
    임의(dict 삽입 순)라 그 값을 순위로 쓰면 같은 질의가 실행마다 다른 랭킹을 낸다."""
    n = len(ordered)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        rank = j + 1
        for slug, _s in ordered[i : j + 1]:
            scores[slug] += weight / (RRF_K + rank)
        i = j + 1


def _temporal_multiplier(meta: dict, today: _dt.date | None = None) -> float:
    """빠르게 낡는 reference만 보수적으로 보정한다. 날짜 불명·다른 kind는 중립."""
    if _kind(meta) not in TEMPORAL_KINDS:
        return 1.0
    try:
        # 사건 시각 우선 — "작년에 정한 규칙"을 오늘 적었다고 최신 사실이 되진 않는다
        updated = _dt.date.fromisoformat(event_date(meta))
    except ValueError:
        return 1.0
    days = max(0, ((today or _dt.date.today()) - updated).days)
    recency = max(0.1, min(1.0, 1.0 - days / TEMPORAL_DAYS))
    return 1.0 + TEMPORAL_ALPHA * (recency - 0.5)


def _snippet(body: str, i: int) -> str:
    """적중 위치 둘레 발췌 — 단, 렌더 상한 안에 들어가는 본문은 자르지 않는다.

    창(window)만 쓰던 시절, 한 문장짜리 페이지가 창 경계에서 잘려 나갔다. 실측 26-08-04:
    본문 89자 `helios-application의 로컬 경로는 /Users/yun/.../helios-application 이다.`가
    `.../helios-applicati` 로 실렸다 — 경로 끝 두 글자가 없어진 채로. 저장된 사실은 온전한데
    주입된 사실만 틀렸고, 그 값을 그대로 쓰면 열리지 않는 경로가 된다. 상한 안에 다 들어가는
    본문은 자를 이유가 애초에 없다."""
    whole = body.strip()
    if len(whole) <= SNIPPET_MAX:
        return whole
    start, end = max(i - 40, 0), i + 80
    window = body[start:end]
    # 창 경계는 글자 수로 잡히므로 낱말 한가운데를 지난다. 어절 경계까지 물러서고 잘렸다는
    # 표시를 남긴다 — 표시가 없으면 읽는 쪽이 `배포된 asg` 를 온전한 값으로 읽는다.
    if end < len(body) and (cut := window.rfind(" ")) > len(window) // 2:
        window = window[:cut] + "…"
    if start > 0 and 0 < (cut := window.find(" ")) < len(window) // 3:
        window = "…" + window[cut:]
    return window.strip()


def query(
    text: str,
    k: int = 5,
    d: str | None = None,
    track: bool = True,
    explain: bool = False,
    expand_links: bool = True,
) -> list[dict]:
    """FTS5 trigram 검색 (한국어 substring 대응). hit는 **사용** 흔적을 남긴다 — lint 부패 판정 원료.

    track=True 가 "사람이 부른 검색"을 뜻한다. 자동 주입 레인은 track=False 로 부르고 프롬프트에
    실제로 실린 것만 따로 **노출**로 센다 (`recall_rows`·`memory.usage`) — 두 사건을 한 칸에
    세면 한 번 실린 페이지가 영영 부패 후보가 못 된다.

    랭킹 = RRF(rank fusion). BM25 값과 스캔 매칭 카운트는 척도가 달라 점수 혼합이 무의미하므로
    각 경로의 '순위'만 합산한다 (동점 구간은 구간의 마지막 순위 — `_add_ranks`). RRF 동률은
    reference 최신성 → usage 회수 빈도 → slug 순으로 가른다 — 보조 신호는 관련도 순위를 넘지 못한다.
    오염 페이지는 결과에서 제외한다 (2차 리뷰 ② — query 출력은 에이전트 컨텍스트로 흘러간다).
    제외 수는 결과에 실리지 않고 lint가 threat로 보고한다.

    명시적 links/[[wiki-link]]가 있으면 lexical·semantic seed에서 PPR로 연관 페이지를 확장해
    네 번째 RRF 스트림으로 합친다. expand_links=False는 A/B 평가용 기존 3-스트림 경로다.

    explain=True 면 각 hit에 `streams`(fts/scan/semantic/graph 경로별 적중 여부)를 덧붙인다 —
    랭킹·반환 순서는 불변, 대시보드의 스트림 출처 표시(읽기 전용)용 파생 정보일 뿐이다."""
    d = d or memory_dir()
    k = max(1, min(int(k), 1000))  # 음수·0·과대 방지 (P2)
    if not os.path.isdir(os.path.join(d, PAGES)):
        return []

    # 읽은 결과와 오염 판정을 카탈로그·점검과 나눠 쓴다 (`clean_pages` 참조).
    clean_pages_map = clean_pages(d)

    phrase = text.strip().lower()
    raw_words = [w.lower() for w in re.split(r"[^\w가-힣%-]+", text) if len(w) >= 2]
    scan_words: list[str] = []
    # 조사는 물론 흔한 용언 활용도 어간 후보를 하나만 더 만든다. 한국어 FTS trigram은
    # `선호하는` 질의와 정본의 `선호한다`처럼 의미가 같아도 표면형이 달라지면 놓치므로,
    # 형태소 분석기 의존성 없이 길고 명확한 어미만 보수적으로 제거한다.
    #
    # 목록은 근거 대조(`_stem_floor`)와 **같은 표**를 쓴다. 여기 따로 적어 두었더니 회수는
    # 한국어를 형태로 보고 근거 대조는 길이로 보는 갈라짐이 생겼고, 그 비대칭이 근거 정밀도를
    # 반토막 냈다 (`benchmarks/grounding/REPORT.md`). 조사와 어미를 따로 한 번씩 떼는 것은
    # 여기만의 거동이라 그대로 둔다 — 회수는 후보를 넓게 잡아도 랭킹이 거르지만, 판정에는
    # 그 여유가 없다.
    for word in raw_words:
        scan_words.append(word)
        suffix = next((p for p in _KO_PARTICLES if word.endswith(p) and len(word) > len(p) + 1), None)
        if suffix:
            scan_words.append(word[: -len(suffix)])
        ending = next((e for e in _KO_ENDINGS if word.endswith(e) and len(word) > len(e) + 1), None)
        if ending:
            scan_words.append(word[: -len(ending)])
    # 정체성 슬롯 동의어 — "내 이름이 뭐야"가 "사용자의 호칭은 …" 페이지를 찾게 한다.
    # 승계(ingest)가 정본 어휘를 슬롯 안에서 갈아끼우므로 질의도 슬롯 단위로 넓힌다.
    scan_words.extend(slot_query_aliases(text))
    scan_words = list(dict.fromkeys(scan_words))
    scan_matchers = [(w, _word_matcher(w)) for w in scan_words]
    # 구절 가산점도 낱말과 같은 규칙을 지난다. 한 낱말짜리 영어 질의는 구절이 곧 그 낱말이라,
    # 여기만 원시 부분문자열로 두면 `round` 가 `grounding` 페이지에 3점을 주고 낱말 쪽에서
    # 막은 잡음이 그대로 돌아온다 (실측 26-08-20 — 이 경로 하나 때문에 pin 시험이 빨갛게 났다).
    phrase_hit = _word_matcher(phrase)

    def _scan_score(meta: dict, body: str) -> tuple[list[str], int]:
        hay = (meta.get("title", "") + "\n" + body).lower()
        matched = [w for w, hit in scan_matchers if hit(hay)]
        # 빈 질의는 `phrase` 에서 먼저 끊는다 — 빈 문자열로 만든 경계 패턴은 어디서나 맞는다.
        return matched, len(matched) + (3 if phrase and phrase_hit(hay) else 0)

    # 후보 수집: slug → (meta, body, matched, scan_score). FTS 순위는 별도 리스트로 보존.
    cand: dict[str, tuple[dict, str, list[str], int]] = {}
    fts_order: list[tuple[str, float]] = []  # (slug, bm25) — bm25는 작을수록 좋음
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
                pg = clean_pages_map.get(slug)
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
    for slug, pg in clean_pages_map.items():
        if slug in cand:
            continue
        meta, body = pg
        matched, s = _scan_score(meta, body)
        if s:
            cand[slug] = (meta, body, matched, s)

    # 시맨틱 스트림 (3번째 경로) — `memory_semantic.DEFAULT_MODE` 가 `local` 이라 기본 설치에서
    # 돈다. "옵트인" 이라 적던 주석은 그 기본값이 바뀐 뒤로 코드와 어긋나 있었다. lexical이 놓친 패러프레이즈/동의어를
    # 회수한다. 벡터는 state.db 파생물이고, 비활성이면 이 블록 전체가 건너뛰어져 기존 2경로와
    # 완전히 동일하게 동작한다 (무회귀 계약). 문턱 미만 코사인은 후보로도 넣지 않는다.
    sem_order: list[tuple[str, float]] = []
    qv: list[float] | None = None
    from ... import memory_semantic as sem

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
                    pg = clean_pages_map.get(slug)  # 시맨틱 전용 후보도 오염 제외
                    if not pg:
                        continue
                    meta, body = pg
                    matched, _s = _scan_score(meta, body)
                    cand[slug] = (meta, body, matched, _s)  # _s 0 가능 — 순수 시맨틱 진입
                sem_order.append((slug, cos))

    if not cand:
        return []

    scan_order = sorted(((slug, float(c[3])) for slug, c in cand.items() if c[3] > 0), key=lambda p: -p[1])

    # 기존 검색 결과를 personalization seed로 삼고, 정본의 명시 링크만 PPR로 전파한다.
    # LLM 추출 그래프/별도 DB 없이 기존 Zettelkasten 링크를 실제 검색 신호로 재사용한다.
    seed_scores = dict.fromkeys(cand, 0.0)

    for ordered in (fts_order, scan_order, sem_order):
        _add_ranks(seed_scores, ordered)
    graph_order = _graph_order(clean_pages_map, seed_scores, d) if expand_links else []
    graph_order = graph_order[: max(k, 10)]
    for slug, _score in graph_order:
        if slug not in cand:
            meta, body = clean_pages_map[slug]
            matched, s = _scan_score(meta, body)
            cand[slug] = (meta, body, matched, s)

    # RRF: 경로별 순위 기여 1/(RRF_K+rank) 합산. 동점 구간은 그 구간의 마지막 순위를 함께 받는다.
    rrf = dict.fromkeys(cand, 0.0)

    _add_ranks(rrf, fts_order)
    # 스캔 스트림엔 실제 lexical 매칭(s>0)만 — 순수 시맨틱 후보(s=0)가 스캔 순위를 훔치지 않게
    _add_ranks(rrf, scan_order)
    _add_ranks(rrf, sem_order)  # 비활성이면 빈 리스트 → 무영향
    _add_ranks(rrf, graph_order)  # 링크가 없거나 A/B off면 빈 리스트 → 무영향

    # 2단계 — 4스트림이 정한 상위권만 구절 단위로 다시 보고, 그 순위와 **1:1로** 융합한다.
    # 회수 범위는 안 넓히고 순위만 고친다. 왜 다섯 번째 스트림이 아니라 2단계인가:
    # 스트림 하나로 넣으면 가중이 1/5로 희석돼 실측 이득이 +2.4pp → +0.4pp로 죽었다
    # (LongMemEval-S 500문항). 이 신호는 그만큼 강하다 — 대등하게 세워야 값을 한다.
    base_order = sorted(cand, key=lambda slug: (-rrf[slug], slug))
    if rerank_enabled():
        rerank_order, rerank_weight = _rerank_order(text, cand, base_order[:RERANK_CANDIDATES], d, qv)
        if rerank_order and rerank_weight > 0.0:
            fused = dict.fromkeys(cand, 0.0)
            _add_ranks(fused, [(slug, rrf[slug]) for slug in base_order], RERANK_BASE_WEIGHT)
            # 가중은 QPP 게이트가 정한다: 후보가 갈리면 1.0(대등), 안 갈리면 그만큼 작게.
            _add_ranks(fused, rerank_order, rerank_weight)
            rrf = fused

    # 빠르게 낡는 reference만 시간 multiplier를 계산하되 RRF 동률 안에서만 쓴다.
    # k=60 RRF의 인접 순위 차가 작아 전역 곱셈은 약한 최신성만으로 강한 관련도를 뒤집는다.
    # user/decision/insight는 강등하지 않고, last_used도 자기강화 편향 때문에 쓰지 않는다.
    temporal_scores = {slug: rrf[slug] * _temporal_multiplier(cand[slug][0]) for slug in cand}

    # usage는 RRF·시간 보정 동률 타이브레이크 전용 prior (힌트, 증거 아님).
    #
    # 노출과 사용이 갈린 뒤 **사용 쪽을 쓴다**. 노출은 회수기가 스스로 고른 기록이라 prior 로
    # 쓰는 순간 자기 순위를 자기 근거로 삼는다 — 한 번 상위에 든 페이지가 매 턴 실리고, 실렸다는
    # 이유로 다음 동률에서 또 우선한다 (바로 위 last_used 를 안 쓰는 것과 같은 이유). 사용은
    # 회수기 밖에서 온 신호다: 사람이 검색을 쳤고 이 페이지가 걸렸다. 갈라 놓은 덕에 이 칸이
    # 전보다 깨끗해졌다 — 예전엔 자동 주입이 같은 칸에 섞여 들어와 prior 를 균질하게 부풀렸다.
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
    graph_slugs = {s for s, _ in graph_order}

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
            "snippet": _snippet(body, i),
            "score": round(rrf[slug], 4),
        }
        if explain:
            hit["streams"] = {
                "fts": slug in fts_slugs,
                "scan": slug in scan_slugs,
                "semantic": slug in sem_slugs,
                "graph": slug in graph_slugs,
            }
        hits.append(hit)
    return _track(d, hits) if track else hits


def _track(d: str, hits: list[dict], *, exposure: bool = False) -> list[dict]:
    """hit의 회수 흔적 기록. 경로(FTS/스캔) 무관 공통, 실패는 무해.

    exposure=False 가 **사용**이다 — 사람이 부른 검색에 걸렸다는 뜻이고, 부패 판정이 읽는
    값이 이것이다. exposure=True 는 자동 주입으로 프롬프트에 실린 **노출**이라 판정에 안 쓴다:
    회수기가 고른 것을 사람이 찾은 것으로 세면 한 번 실린 페이지가 영영 안 늙는다
    (`memory.usage` 참조 — 기본값이 사용인 이유는 자동 주입 경로가 이 저장소 안에 하나뿐이고,
    밖에서 부르는 표면은 전부 사람이 시킨 검색이기 때문이다)."""
    from ..usage import bump

    bump(d, [str(h["slug"]) for h in hits], exposure=exposure)
    return hits
