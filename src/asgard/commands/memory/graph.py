"""memory graph 커맨드 — 두 기억의 링크를 그래프로 읽는 표면.

두 계층을 한 모듈이 지는 이유는 **연산이 같기 때문**이다. 중심·경로·둘레·덩어리는 인접
리스트 하나만 있으면 답이 나오고, 개인 위키의 `[[wiki-link]]` 와 프로젝트 record 의
`relations` 는 둘 다 그 인접 리스트로 편다 (`memory.graph`). 계층별로 갈라 두면 같은 BFS 가
두 벌이 되고, 두 벌은 곧 다르게 답한다.

갈리는 것은 자료를 어디서 읽는가와 노드를 무엇으로 부르는가뿐이라, 그 둘만 `_source` 가
정한다."""

import os

from ... import errors, ui
from ...memory import graph as G
from ._core import _emit, _guard

VERBS = ("hubs", "path", "expand", "communities", "stats")
SCOPES = ("personal", "project")


EDGE_SOURCES = ("all", "explicit", "mention", "term")


def _source(scope: str, edges: str) -> tuple[dict[str, set[str]], dict[str, str]]:
    """(인접 리스트, 노드 → 제목). 제목은 표시 전용이고 없는 노드는 자기 id 로 보인다.

    `edges` 가 기본 `all` 인 이유는 실측이다: 이 저장소의 개인 기억은 명시 링크가 0개라
    `explicit` 만 보면 그래프가 통째로 비어 있다. 두 등급을 갈라 볼 수 있게는 남긴다 —
    손으로 쓴 링크와 본문에서 나온 언급은 근거의 종류가 다르다.
    """
    if scope == "personal":
        from ...memory import memory_dir
        from ...memory.recall import clean_pages

        pages = clean_pages(memory_dir())
        titles = {slug: str(meta.get("title") or slug) for slug, (meta, _body) in pages.items()}
        documents = {slug: (titles[slug], body) for slug, (_meta, body) in pages.items()}
        explicit = G.page_links(pages)
    else:
        from ...project_memory import load_canonical_records

        rows = load_canonical_records(os.getcwd())
        titles = {record.record_id: record.title for record, _path, _digest in rows}
        documents = {record.record_id: (record.title, record.content) for record, _path, _digest in rows}
        explicit = G.record_links(rows)
    if edges == "explicit":
        return explicit, titles
    if edges == "mention":
        return G.mention_links(documents), titles
    if edges == "term":
        return G.term_links(documents), titles
    return G.merge(explicit, G.mention_links(documents), G.term_links(documents)), titles


def _label(titles: dict[str, str], node: str) -> str:
    title = titles.get(node, "")
    return f"{node}  {ui.dim(title)}" if title and title != node else node


def run_graph(
    verb: str,
    source: str = "",
    target: str = "",
    *,
    scope: str = "personal",
    edges: str = "all",
    top: int = 10,
    depth: int = 2,
    json_out: bool = False,
) -> int:
    """기억 그래프를 읽는다. 아무것도 쓰지 않는다 — 조회 전용 표면이다.

    Returns:
        0 이면 읽었고, 1 이면 부른 쪽이 틀렸다(모르는 동사·범위, 없는 노드, 빠진 인자).
    """
    errors.set_json_surface(json_out)

    def _do() -> int:
        if verb not in VERBS:
            raise ValueError(f"verb must be one of {'|'.join(VERBS)}")
        if scope not in SCOPES:
            raise ValueError(f"scope must be one of {'|'.join(SCOPES)}")
        if edges not in EDGE_SOURCES:
            raise ValueError(f"edges must be one of {'|'.join(EDGE_SOURCES)}")
        links, titles = _source(scope, edges)
        if not links:
            ui.step(
                ui.dim("이 기억엔 아직 아무 페이지도 없어요." if scope == "personal" else "승인된 기록이 아직 없어요.")
            )
            return 0
        return _run(verb, links, titles)

    def _run(verb: str, links: dict[str, set[str]], titles: dict[str, str]) -> int:
        if verb == "stats":
            found = G.stats(links)
            if json_out:
                _emit(found)
                return 0
            ui.step(
                f"  노드 {found['nodes']} · 간선 {found['edges']} · 덩어리 {found['communities']}"
                f" · 외톨이 {found['isolated']}"
            )
            return 0
        if verb == "hubs":
            found = G.hubs(links, top)
            if json_out:
                _emit([{"node": node, "degree": degree, "title": titles.get(node, "")} for node, degree in found])
                return 0
            if not found:
                ui.step(ui.dim("아직 이어진 페이지가 없어요 — 링크를 하나도 안 쓰면 중심도 없어요."))
                return 0
            for node, degree in found:
                ui.step(f"  {degree:>3}  {_label(titles, node)}")
            return 0
        if verb == "communities":
            groups = G.communities(links)
            members: dict[int, list[str]] = {}
            for node, cid in sorted(groups.items()):
                members.setdefault(cid, []).append(node)
            if json_out:
                _emit([{"community": cid, "members": nodes} for cid, nodes in sorted(members.items())])
                return 0
            for cid, nodes in sorted(members.items()):
                ui.step(f"  {cid}차 ({len(nodes)})  {ui.dim(' · '.join(nodes[:6]))}")
            return 0
        if verb == "path":
            if not (source and target):
                raise ValueError("path needs two nodes: asgard memory graph path <a> <b>")
            for node in (source, target):
                if node not in links:
                    raise ValueError(f"unknown node: {node}")
            found = G.shortest_path(links, source, target)
            if json_out:
                _emit({"source": source, "target": target, "path": found, "hops": max(0, len(found) - 1)})
                return 0
            if not found:
                ui.step(ui.dim(f"이어져 있지 않아요 — {source} 와 {target} 사이에 링크 길이 없어요."))
                return 0
            ui.step("  " + " → ".join(found))
            return 0
        # expand
        if not source:
            raise ValueError("expand needs a node: asgard memory graph expand <node>")
        if source not in links:
            raise ValueError(f"unknown node: {source}")
        nodes, edges = G.expand(links, [source], depth)
        if json_out:
            _emit({"seed": source, "depth": depth, "nodes": nodes, "edges": [list(edge) for edge in edges]})
            return 0
        ui.step(f"  {source} 둘레 {depth}홉 — 노드 {len(nodes)} · 간선 {len(edges)}")
        for node in nodes:
            ui.step(f"    {_label(titles, node)}")
        return 0

    return _guard(_do)
