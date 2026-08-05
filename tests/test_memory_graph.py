"""기억 그래프 — 순수 연산의 불변식과, 회수가 그 그래프를 실제로 쓰는가.

여기서 지키는 것은 값이 아니라 성질이다. 그래프 연산은 위키 내용에 따라 답이 매번 다르므로
"이 위키에서 hubs 가 이것" 을 박아 두면 시험이 코퍼스를 외울 뿐 계약을 안 지킨다. 대신
경로는 최단인가, 확장은 홉 수를 지키는가, 덩어리는 두 번 불러도 같은가를 본다.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from asgard import memory
from asgard.memory import graph as G


class PureGraphOps(unittest.TestCase):
    #  a—b—c   d—e   f(외톨이)
    LINKS = {"a": {"b"}, "b": {"a", "c"}, "c": {"b"}, "d": {"e"}, "e": {"d"}, "f": set()}

    def test_shortest_path_is_shortest_and_symmetric(self):
        self.assertEqual(G.shortest_path(self.LINKS, "a", "c"), ["a", "b", "c"])
        self.assertEqual(G.shortest_path(self.LINKS, "c", "a"), ["c", "b", "a"])

    def test_a_node_reaches_itself_but_an_unlinked_pair_does_not(self):
        """길이 0 의 경로와 '안 이어짐'은 다른 사실이다 — 둘 다 빈 목록이면 구별이 사라진다."""
        self.assertEqual(G.shortest_path(self.LINKS, "a", "a"), ["a"])
        self.assertEqual(G.shortest_path(self.LINKS, "a", "d"), [])
        self.assertEqual(G.shortest_path(self.LINKS, "a", "nope"), [])

    def test_expand_honours_the_hop_budget(self):
        one, _edges = G.expand(self.LINKS, ["a"], 1)
        self.assertEqual(one, ["a", "b"])
        two, edges = G.expand(self.LINKS, ["a"], 2)
        self.assertEqual(two, ["a", "b", "c"])
        # 방문한 노드 사이의 간선은 전부 들어간다 — BFS 트리 간선만 남기면 밀도가 거짓이 된다.
        self.assertEqual(edges, [("a", "b"), ("b", "c")])

    def test_expand_of_an_isolated_node_is_just_itself(self):
        self.assertEqual(G.expand(self.LINKS, ["f"], 3), (["f"], []))

    def test_communities_are_deterministic_and_size_ordered(self):
        first = G.communities(self.LINKS)
        self.assertEqual(first, G.communities(self.LINKS))
        self.assertEqual(first["a"], first["b"])
        self.assertEqual(first["a"], first["c"])
        self.assertNotEqual(first["a"], first["d"])
        self.assertEqual(first["a"], 0)  # 가장 큰 덩어리가 0번
        self.assertNotEqual(first["f"], first["d"])  # 외톨이도 자기 덩어리를 갖는다

    def test_hubs_drop_isolated_nodes(self):
        found = dict(G.hubs(self.LINKS, 10))
        self.assertEqual(found["b"], 2)
        self.assertNotIn("f", found)

    def test_stats_counts_each_edge_once(self):
        # a—b · b—c · d—e = 3. 방향이 없으므로 인접 리스트의 이웃 수 합을 반으로 나눈다.
        self.assertEqual(G.stats(self.LINKS), {"nodes": 6, "edges": 3, "communities": 3, "isolated": 1})


class DerivedEdges(unittest.TestCase):
    def test_mention_edges_need_the_whole_title_and_a_floor(self):
        documents = {
            "long": ("배포본 드리프트", "본문"),
            "cites": ("사본 대조", "배포본 드리프트 를 바이트로 대조한다"),
            "short": ("맵", "본문"),
            "cites-short": ("다른 것", "맵 을 본다"),
        }
        links = G.mention_links(documents)
        self.assertEqual(links["long"], {"cites"})
        # 두 글자 제목은 남의 본문에서 우연히 걸린다 — 바늘 하한이 그것을 막는다.
        self.assertEqual(links["short"], set())

    def test_term_edges_need_two_shared_rare_words(self):
        documents = {
            "a": ("판정자 지연", "verifier 는 baseline_timeout 때문에 느리다"),
            "b": ("설정 기본값", "baseline_timeout 은 trinity_policy 아래 있고 verifier 가 읽는다"),
            "c": ("무관한 것", "원두는 밀폐 용기에 실온 보관한다"),
        }
        links = G.term_links(documents)
        self.assertEqual(links["a"], {"b"})
        self.assertEqual(links["c"], set())

    def test_a_word_everyone_shares_links_nobody(self):
        """흔한 낱말은 아무것도 못 가른다 — 상한이 없으면 위키 전체가 한 덩어리가 된다."""
        documents = {f"p{i}": ("제목", "공통낱말 하나뿐인 본문 공통낱말") for i in range(20)}
        self.assertEqual(sum(len(v) for v in G.term_links(documents).values()), 0)

    def test_record_relations_become_edges_and_unknown_targets_are_dropped(self):
        """2차 메모리는 관계 어휘를 이미 든다 — 그것이 그대로 간선이다."""
        from asgard.project_memory import ProjectRecord

        def record(record_id: str, relations=()):
            return ProjectRecord(
                record_id=record_id,
                kind="decision",
                title=record_id,
                content="본문",
                source="src",
                source_revision="rev",
                relations=tuple(relations),
            )

        rows = [
            record("r-1", [{"type": "supersedes", "target": "r-2"}]),
            record("r-2"),
            # 아직 없는 record 를 가리키는 관계는 노드를 만들지 않는다 — 본문 없는 노드가
            # 중심성 상위에 올라온다.
            record("r-3", [{"type": "dependsOn", "target": "r-nope"}]),
        ]
        links = G.record_links(rows)
        self.assertEqual(links["r-1"], {"r-2"})
        self.assertEqual(links["r-2"], {"r-1"}, "관계가 한쪽에서만 보인다")
        self.assertEqual(links["r-3"], set())
        self.assertNotIn("r-nope", links)

    def test_merge_is_a_union_of_nodes_and_edges(self):
        merged = G.merge({"a": {"b"}, "b": {"a"}}, {"b": {"c"}, "c": {"b"}})
        self.assertEqual(merged, {"a": {"b"}, "b": {"a", "c"}, "c": {"b"}})


class RecallUsesTheGraph(unittest.TestCase):
    """회수가 보는 그래프와 조회 명령이 보는 그래프는 같은 파서에서 나와야 한다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asgard-memgraph-")
        self.d = os.path.join(self.tmp, "memory")
        memory.ensure_home(self.d)
        os.environ.pop("ASGARD_MEMORY_GRAPH_EDGES", None)

    def tearDown(self):
        os.environ.pop("ASGARD_MEMORY_GRAPH_EDGES", None)

    def test_explicit_mode_sees_no_edges_when_nobody_wrote_a_link(self):
        """이 갈래가 종전 동작이고, 실제 위키에서 빈 그래프인 것이 이 층을 만든 이유다."""
        from asgard.memory.recall import _links_for, clean_pages

        memory.add("verifier 는 baseline_timeout 때문에 느리다", title="판정자 지연", kind="note", d=self.d)
        memory.add(
            "baseline_timeout 은 trinity_policy 아래 있고 verifier 가 읽는다", title="설정값", kind="note", d=self.d
        )
        pages = clean_pages(self.d)
        os.environ["ASGARD_MEMORY_GRAPH_EDGES"] = "explicit"
        self.assertEqual(sum(len(v) for v in _links_for(pages, None).values()), 0)
        os.environ["ASGARD_MEMORY_GRAPH_EDGES"] = "all"
        self.assertGreater(sum(len(v) for v in _links_for(pages, None).values()), 0)

    def test_the_memo_follows_the_edge_mode(self):
        """등급을 바꿨는데 지난 그래프가 나오면 A/B 가 통째로 거짓이 된다."""
        from asgard.memory.recall import _links_for, clean_pages

        memory.add("verifier 는 baseline_timeout 때문에 느리다", title="판정자 지연", kind="note", d=self.d)
        memory.add(
            "baseline_timeout 은 trinity_policy 아래 있고 verifier 가 읽는다", title="설정값", kind="note", d=self.d
        )
        pages = clean_pages(self.d)
        os.environ["ASGARD_MEMORY_GRAPH_EDGES"] = "all"
        wide = sum(len(v) for v in _links_for(pages, self.d).values())
        os.environ["ASGARD_MEMORY_GRAPH_EDGES"] = "explicit"
        narrow = sum(len(v) for v in _links_for(pages, self.d).values())
        self.assertGreater(wide, narrow)

    def test_an_explicit_wiki_link_still_makes_an_edge(self):
        from asgard.memory.recall import clean_pages

        memory.add("첫 페이지", title="하나", kind="note", d=self.d)
        memory.add("둘째 페이지는 [[하나]] 를 가리킨다", title="둘", kind="note", d=self.d)
        links = G.page_links(clean_pages(self.d))
        self.assertEqual(links[memory.slugify("둘")], {memory.slugify("하나")})


class GraphCommand(unittest.TestCase):
    def test_unknown_verb_scope_and_edges_are_refused(self):
        from asgard.commands.memory.graph import run_graph

        # 2 = 부른 쪽이 틀렸다 (`_guard` 의 ValueError 봉투). 0 으로 돌리면 스크립트가
        # 오타 난 동사를 성공으로 읽는다.
        for kwargs in ({"verb": "nope"}, {"verb": "hubs", "scope": "nope"}, {"verb": "hubs", "edges": "nope"}):
            verb = kwargs.pop("verb")
            self.assertEqual(run_graph(verb, **kwargs), 2)

    def test_the_verb_table_matches_the_command_body(self):
        """표면 목록과 실제 처리 갈래가 갈리면 도움말이 없는 동사를 광고한다."""
        from asgard.commands.memory.graph import EDGE_SOURCES, VERBS

        self.assertEqual(set(VERBS), {"hubs", "path", "expand", "communities", "stats"})
        self.assertEqual(set(EDGE_SOURCES), {"all", "explicit", "mention", "term"})


if __name__ == "__main__":
    unittest.main()
