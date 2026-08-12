"""링크 그래프 위의 personalized PageRank — 회수의 네 번째 스트림과 그 간선 등급."""

from __future__ import annotations

import os

from ..policy import _memory_settings
from ..store import _pages_token

PPR_DAMPING = 0.85
PPR_STEPS = 20


# 네 번째 RRF 스트림이 어떤 간선 위를 도는가. `explicit` 은 사람이 손으로 쓴 `[[링크]]` 만,
# `all` 은 거기에 본문에서 결정론으로 나오는 두 등급을 겹친다.
#
# 기본을 `all` 로 둔 이유는 `explicit` 이 실제 위키에서 빈 그래프이기 때문이다 — 이 저장소의
# 개인 기억은 14페이지에 명시 링크 0개였고(26-08-06 실측), 그 상태에서는 네 번째 스트림이
# 있으나 마나다. 겹친 뒤의 수치는 `benchmarks/memory-graph/REPORT.md` 에 있다.
_GRAPH_EDGES_ENV = "ASGARD_MEMORY_GRAPH_EDGES"
_GRAPH_EDGES_DEFAULT = "all"
_GRAPH_EDGE_MODES = ("explicit", "all")


def graph_edges() -> str:
    """회수의 그래프 스트림이 쓰는 간선 등급 — env 우선, 설정 폴백, 기본 `all`."""
    env = (os.environ.get(_GRAPH_EDGES_ENV) or "").strip().lower()
    if env in _GRAPH_EDGE_MODES:
        return env
    try:
        value = str(_memory_settings().get("graph_edges", _GRAPH_EDGES_DEFAULT)).strip().lower()
    except Exception:
        return _GRAPH_EDGES_DEFAULT
    return value if value in _GRAPH_EDGE_MODES else _GRAPH_EDGES_DEFAULT


# 파생 간선을 편 결과 — 위키 형상이 그대로면 지난 것을 다시 쓴다. `page_verdicts` 와 같은
# 열쇠(`_pages_token`)를 쓰는 이유는 같은 사실을 재기 때문이다: 페이지가 안 바뀌었으면 링크도
# 안 바뀐다. 캐시가 없던 동안 1,000페이지에서 질의당 +31.5ms 였다 (26-08-06 실측: p50
# 10.6 → 42.1ms). 회수는 매 턴 도는 자리라 그 값을 매번 다시 치를 이유가 없다.
_LINKS_MEMO: dict[str, tuple[str, str, dict[str, set[str]]]] = {}


def _links_for(pages: dict[str, tuple[dict, str]], d: str | None) -> dict[str, set[str]]:
    """이 위키의 인접 리스트 — 등급은 `graph_edges()`, 형상이 그대로면 지난 것 그대로."""
    from ..graph import mention_links, merge, page_links, term_links

    mode = graph_edges()
    key = os.path.realpath(d) if d else ""
    token = _pages_token(d) if d else ""
    memo = _LINKS_MEMO.get(key)
    if key and token and memo is not None and memo[0] == token and memo[1] == mode:
        return memo[2]
    links = page_links(pages)
    if mode == "all":
        documents = {slug: (str(meta.get("title") or slug), body) for slug, (meta, body) in pages.items()}
        links = merge(links, mention_links(documents), term_links(documents))
    if key and token:
        _LINKS_MEMO[key] = (token, mode, links)
    return links


def _graph_order(
    pages: dict[str, tuple[dict, str]], seeds: dict[str, float], d: str | None = None
) -> list[tuple[str, float]]:
    """링크 그래프 위의 personalized PageRank. LLM 추론 엣지는 여전히 만들지 않는다.

    인접 리스트는 `graph` 모듈이 편다 — 파서가 여기 따로 하나 더 있으면 회수가 보는 그래프와
    `asgard memory graph` 가 보는 그래프가 갈린다.

    간선 등급은 `graph_edges()` 가 정한다. `explicit` 은 사람이 쓴 `[[링크]]` 뿐이고,
    `all` 은 거기에 본문에서 결정론으로 나오는 두 등급을 겹친다 (제목 언급·드문 낱말 공유).
    후자를 기본으로 둔 근거는 벤치다 — `benchmarks/memory-graph/REPORT.md`."""
    links = _links_for(pages, d)
    if not any(links.values()):
        return []
    personal = {slug: max(0.0, seeds.get(slug, 0.0)) if links[slug] else 0.0 for slug in pages}
    total = sum(personal.values())
    if not total:
        return []
    personal = {slug: score / total for slug, score in personal.items()}
    scores = personal.copy()
    for _ in range(PPR_STEPS):
        nxt = {slug: (1.0 - PPR_DAMPING) * personal[slug] for slug in pages}
        dangling = sum(scores[slug] for slug, neighbors in links.items() if not neighbors)
        for slug in pages:
            nxt[slug] += PPR_DAMPING * dangling * personal[slug]
        for source, neighbors in links.items():
            if not neighbors:
                continue
            share = PPR_DAMPING * scores[source] / len(neighbors)
            for target in neighbors:
                nxt[target] += share
        scores = nxt
    return sorted(((slug, score) for slug, score in scores.items() if score > 0), key=lambda p: (-p[1], p[0]))
