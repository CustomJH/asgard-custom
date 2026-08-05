"""기억 그래프 — 이미 있는 링크 위에서 답하는 네 가지 질문.

회수(`recall.query`)는 그래프를 **랭킹 신호 하나**로만 쓴다: 명시 링크 위의 personalized
PageRank 가 네 번째 RRF 스트림으로 들어가고, 나오는 것은 페이지 목록이다. 그 축으로는
답할 수 없는 질문이 넷 있다 — 무엇이 중심인가, 이 둘은 왜 이어져 있는가, 이 하나 둘레에는
무엇이 있는가, 이 기억은 몇 덩어리인가.

넷 다 같은 그래프에 이미 답이 있다. 없던 것은 **읽는 문**이지 자료가 아니다. 그래서 이
모듈은 새 저장소를 만들지 않는다 — tier-1 은 페이지의 `[[wiki-link]]` 와 frontmatter
`links:`, tier-2 는 승인 record 의 `relations` 를 그대로 인접 리스트로 편다.

층: domain. 위(commands·cli)에서 부르고, 아래(store·project_memory)만 본다.

**의존을 하나도 안 늘린다.** 커뮤니티는 Leiden 이 아니라 라벨 전파다 — 이웃 중 가장 흔한
라벨을 받되 동률은 라벨 문자열 순으로 끊어 결정론을 지킨다. Leiden 이 모듈러리티를 직접
최적화하는 것과 달리 라벨 전파는 국소 규칙이라 덩어리 경계가 더 거칠다. 그 대신 여기서
쓰는 것은 표준 라이브러리뿐이고, 개인 기억은 페이지 수천 규모라 그 차이가 답을 바꾸는
자리가 아직 없다.
lagom: 덩어리 품질이 회수에 실제로 걸리기 시작하면 (수만 노드, 또는 커뮤니티 요약을
회수 경로에 넣을 때) igraph 의 Leiden 으로 갈아탄다 — `communities()` 반환 형태는 같다.
"""

from __future__ import annotations

import re
from collections import deque

from .store import slugify

# `[[대상]]` · `[[대상|보이는 글자]]` · `[[대상#구절]]` 셋 다 대상만 집는다.
_WIKILINK = re.compile(r"\[\[([^\]\n]+)\]\]")


def page_links(pages: dict[str, tuple[dict, str]]) -> dict[str, set[str]]:
    """페이지 전량 → 무향 인접 리스트. 링크가 없는 페이지도 빈 이웃으로 남는다.

    파서가 여기 하나뿐인 것이 요점이다. `recall._graph_order` 가 자기 안에서 같은 정규식을
    따로 하나 더 들고 있으면, 한쪽이 `links:` frontmatter 를 읽기 시작한 날 회수와 그래프 조회가
    서로 다른 그래프를 보게 된다 — 같은 wiki 를 두고 "이어져 있다" 와 "안 이어져 있다" 가
    동시에 참이 된다.

    존재하지 않는 페이지를 가리키는 링크는 버린다. 아직 안 쓴 페이지를 가리키는 `[[이름]]`
    은 정상이고(개인 기억 계약), 그것을 노드로 세우면 본문이 없는 노드가 중심성 상위에
    올라온다.
    """
    links: dict[str, set[str]] = {slug: set() for slug in pages}
    for source, (meta, body) in pages.items():
        refs = _WIKILINK.findall(body)
        refs += [ref for ref in str(meta.get("links") or "").split(",") if ref.strip()]
        for ref in refs:
            raw = ref.split("|", 1)[0].split("#", 1)[0].strip()
            target = raw if raw in links else slugify(raw)
            if target in links and target != source:
                links[source].add(target)
                links[target].add(source)
    return links


def record_links(records: list) -> dict[str, set[str]]:
    """승인 record 전량 → 무향 인접 리스트. tier-2 의 `relations` 가 그대로 간선이다.

    Args:
        records: `project_memory.load_canonical_records()` 가 돌려주는 `(record, path, digest)`
            목록, 또는 `ProjectRecord` 목록. 앞의 형태는 튜플 첫 칸을 집는다.

    관계 종류(`supersedes`·`dependsOn` …)는 여기서 지운다. 이 모듈이 답하는 넷은 전부
    **연결의 모양**에 관한 질문이고, 방향과 종류는 record 본문이 이미 들고 있다 — 여기서
    또 들면 같은 사실이 두 자리에 저장된다.
    """
    rows = [row[0] if isinstance(row, tuple) else row for row in records]
    links: dict[str, set[str]] = {row.record_id: set() for row in rows}
    for row in rows:
        for relation in row.relations or ():
            target = str(relation.get("target") or "").strip()
            if target in links and target != row.record_id:
                links[row.record_id].add(target)
                links[target].add(row.record_id)
    return links


# 언급 간선의 바늘 하한. 이보다 짧은 제목은 안 쓴다 — "지도"·"게이트" 같은 두 글자 제목은
# 남의 본문에서 우연히 걸리고, 그렇게 생긴 간선 하나가 그 페이지를 중심성 1위로 만든다.
MENTION_FLOOR = 4


def mention_links(documents: dict[str, tuple[str, str]]) -> dict[str, set[str]]:
    """제목이 남의 본문에 **글자 그대로** 나오면 간선 — 모델 없이 생기는 그래프.

    Args:
        documents: id → (제목, 본문). tier-1 은 페이지, tier-2 는 승인 record 다.

    왜 이것이 필요한가: 명시 링크는 사람이 손으로 쓰는 것이고, 실제 위키에서는 거의 안
    쓰인다 — 이 저장소의 개인 기억은 14페이지에 링크 0개였다 (26-08-06 실측). 그러면 회수의
    네 번째 스트림도, 아래 네 질문도 전부 빈 그래프 위에서 돈다.

    간선의 근거는 추론이 아니라 본문의 글자다. graphify 가 `EXTRACTED` 로 부르는 등급이
    이것이고, 임베딩 유사도(`INFERRED`)와 달리 문턱도 모델도 필요 없다 — 제목이 거기 있거나
    없거나 둘 중 하나다. 그래서 이 함수는 config 손잡이를 하나도 안 받는다.

    바늘은 **제목 전체**다. 낱말 단위로 쪼개면 흔한 낱말 하나가 위키의 절반을 잇는다.
    """
    links: dict[str, set[str]] = {key: set() for key in documents}
    needles = {
        key: title.strip().lower() for key, (title, _body) in documents.items() if len(title.strip()) >= MENTION_FLOOR
    }
    for key, (_title, body) in documents.items():
        haystack = body.lower()
        for other, needle in needles.items():
            if other != key and needle in haystack:
                links[key].add(other)
                links[other].add(key)
    return links


# 공유어 간선의 세 손잡이. 셋 다 실측이 아니라 **형상**에서 나온 값이라 설정 손잡이로 안 낸다:
# 흔한 낱말은 아무것도 못 가르고(상한), 한 번만 나온 낱말은 이을 상대가 없으며(하한 2),
# 낱말 하나가 겹치는 것은 우연이지만 둘이 겹치면 같은 주제다.
_TERM_MAX_SHARE = 0.34  # 이 비율 넘게 나오는 낱말은 버린다 (사실상 불용어)
_TERM_MAX_POSTING = 40  # 이만큼 많은 페이지에 걸린 낱말도 버린다 — 작은 위키의 상한 보정
_TERM_MIN_SHARED = 2  # 두 페이지를 잇는 데 필요한 공유어 수


def term_links(documents: dict[str, tuple[str, str]]) -> dict[str, set[str]]:
    """드문 낱말을 함께 쓰는 페이지끼리 간선 — 임베딩 없이 나오는 유사도 그래프.

    `mention_links` 가 비는 자리를 메운다. 개인 기억의 제목은 한 문장인 경우가 많고
    (이 저장소 실측: 14페이지 전부), 문장 전체가 남의 본문에 그대로 박히는 일은 없어서
    언급 간선이 0개로 남는다. 그런데 같은 주제를 다룬 두 페이지는 **드문 낱말을 공유한다** —
    `subagent_gate`·`verify_level`·`hindsight` 같은 것들.

    graphify 가 "임베딩이 필요 없다, 그래프 구조가 곧 유사도 신호다" 라고 말하는 자리가
    이것이다. 다만 그쪽은 semantic 간선을 LLM 이 뽑고 여기서는 안 뽑는다 — 모델을 안 쓰므로
    같은 위키는 언제나 같은 그래프를 준다.

    한 낱말이 걸린 페이지 목록(posting) 안에서만 짝을 짓는다. 전체 페이지 쌍을 도는 것과
    답은 같고, 흔한 낱말을 미리 버리므로 posting 이 짧아 실제 비용은 페이지 수에 가깝다.
    """
    from .recall import _content_words, _stopword

    words = {key: _content_words(f"{title}\n{body}") for key, (title, body) in documents.items()}
    posting: dict[str, list[str]] = {}
    for key, terms in words.items():
        for term in terms:
            if len(term) < MENTION_FLOOR or _stopword(term):
                continue
            posting.setdefault(term, []).append(key)
    ceiling = min(_TERM_MAX_POSTING, max(2, int(len(documents) * _TERM_MAX_SHARE)))
    shared: dict[tuple[str, str], int] = {}
    for keys in posting.values():
        if not 2 <= len(keys) <= ceiling:
            continue
        ordered = sorted(keys)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                shared[(left, right)] = shared.get((left, right), 0) + 1
    links: dict[str, set[str]] = {key: set() for key in documents}
    for (left, right), count in shared.items():
        if count >= _TERM_MIN_SHARED:
            links[left].add(right)
            links[right].add(left)
    return links


def merge(*graphs: dict[str, set[str]]) -> dict[str, set[str]]:
    """여러 인접 리스트를 하나로 겹친다 — 노드 집합은 합집합, 간선도 합집합."""
    merged: dict[str, set[str]] = {}
    for links in graphs:
        for node, neighbors in links.items():
            merged.setdefault(node, set()).update(neighbors)
    return merged


def hubs(links: dict[str, set[str]], top: int = 10) -> list[tuple[str, int]]:
    """가장 많이 이어진 노드 — 이 기억이 무엇을 중심으로 자랐는가.

    이웃 수만 센다. 매개 중심성이 "어느 노드를 지우면 그래프가 끊기는가" 에 더 정확히
    답하지만 O(V·E) 라 매 조회에 얹기엔 비싸고, 여기서 묻는 것은 중심이지 절단점이 아니다.
    동률은 slug 순으로 끊어 같은 wiki 가 같은 답을 준다.
    """
    ranked = sorted(links.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    return [(node, len(neighbors)) for node, neighbors in ranked[: max(1, top)] if neighbors]


def shortest_path(links: dict[str, set[str]], source: str, target: str) -> list[str]:
    """두 노드를 잇는 가장 짧은 경로. 안 이어져 있으면 빈 목록.

    같은 노드를 둘 다 주면 그 노드 하나짜리 경로다 — 길이 0 의 경로는 "이어져 있다" 의
    가장 짧은 참이고, 빈 목록(안 이어짐)과 구별되어야 한다.

    BFS 라 첫 도달이 최단이고, 이웃을 정렬해 들어가므로 같은 길이의 경로가 여럿일 때도
    답이 매번 같다.
    """
    if source not in links or target not in links:
        return []
    if source == target:
        return [source]
    previous: dict[str, str] = {source: ""}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for neighbor in sorted(links[node]):
            if neighbor in previous:
                continue
            previous[neighbor] = node
            if neighbor == target:
                path = [target]
                while path[-1] != source:
                    path.append(previous[path[-1]])
                return list(reversed(path))
            queue.append(neighbor)
    return []


def expand(links: dict[str, set[str]], seeds: list[str], depth: int = 2) -> tuple[list[str], list[tuple[str, str]]]:
    """씨앗 둘레 `depth` 홉의 부분 그래프 — `(노드, 간선)`, 둘 다 결정론 순서.

    노드는 씨앗에서 가까운 순, 같은 거리면 이름 순이다. 부분 그래프를 글로 옮길 때 이
    순서가 곧 읽는 순서라, 가까운 것이 먼저 실리고 예산이 잘리면 먼 것부터 잘린다.

    간선은 **방문한 노드 사이의 것 전부**다. BFS 트리 간선만 남기면 부분 그래프가 실제보다
    성기게 보이고, 밀도가 곧 답인 질문(이 둘레는 얼마나 얽혀 있나)이 거짓이 된다.
    """
    depth = max(0, min(int(depth), 6))
    frontier = [seed for seed in dict.fromkeys(seeds) if seed in links]
    visited: list[str] = list(frontier)
    seen = set(frontier)
    for _ in range(depth):
        nxt: list[str] = []
        for node in frontier:
            for neighbor in sorted(links[node]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    nxt.append(neighbor)
        if not nxt:
            break
        visited.extend(nxt)
        frontier = nxt
    edges = sorted({(min(a, b), max(a, b)) for a in seen for b in links[a] if b in seen})
    return visited, edges


# 라벨 전파 반복 상한. 수렴하면 그 전에 멈춘다 — 상한은 진동(두 라벨이 서로를 밀어내는
# 짝수 주기)에서 안 돌아 나오지 못하는 것을 막는 자리다.
_LABEL_ROUNDS = 30


def communities(links: dict[str, set[str]]) -> dict[str, int]:
    """노드 → 덩어리 번호. 번호는 **크기 순**이라 0 이 가장 큰 덩어리다.

    이웃이 하나도 없는 노드도 자기 혼자 덩어리를 이룬다 — 고아 페이지가 답에서 사라지면
    "이 기억은 몇 덩어리인가" 가 실제보다 작게 나온다.

    라벨 전파는 노드를 정해진 순서로 훑으며 이웃 라벨 중 가장 흔한 것을 받는다. 무작위
    순서를 쓰는 표준 구현과 달리 여기서는 이름 순으로 고정한다: 같은 wiki 가 부를 때마다
    다른 덩어리를 내놓으면 사람이 그 번호로 얘기할 수 없다.
    """
    label = {node: node for node in links}
    for _ in range(_LABEL_ROUNDS):
        changed = False
        for node in sorted(links):
            neighbors = links[node]
            if not neighbors:
                continue
            tally: dict[str, int] = {}
            for neighbor in neighbors:
                tally[label[neighbor]] = tally.get(label[neighbor], 0) + 1
            best = min(tally.items(), key=lambda pair: (-pair[1], pair[0]))[0]
            if best != label[node]:
                label[node] = best
                changed = True
        if not changed:
            break
    sizes: dict[str, int] = {}
    for name in label.values():
        sizes[name] = sizes.get(name, 0) + 1
    order = {name: index for index, name in enumerate(sorted(sizes, key=lambda name: (-sizes[name], name)))}
    return {node: order[name] for node, name in label.items()}


def stats(links: dict[str, set[str]]) -> dict:
    """그래프 한눈 — 노드·간선·덩어리·고아 수. 표시와 점검이 같은 값을 본다."""
    groups = communities(links)
    return {
        "nodes": len(links),
        "edges": sum(len(neighbors) for neighbors in links.values()) // 2,
        "communities": len(set(groups.values())),
        "isolated": sum(1 for neighbors in links.values() if not neighbors),
    }
