#!/usr/bin/env python3
"""그래프 빌드 — 스캔·플로·트레이스·시드·영향 도시에.

실행: uv run pytest tests/map_graph
"""

import json
import os
import unittest

from map_graph.map_base import (
    _APPLICATION_YML,
    _JAVA_CONTROLLER,
    _JAVA_LISTENER,
    _MAPPER_XML,
    _PY_FIXTURE,
    Base,
)


class TestScanGraph(Base):
    def test_scan_writes_state_and_tracked_catalog_deterministically(self):
        from asgard.map_graph import scan_graph

        self.seed()
        first = scan_graph(self.root)
        state_body = open(first.state_path, encoding="utf-8").read()
        graph_body = open(first.graph_md_path, encoding="utf-8").read()
        second = scan_graph(self.root)
        self.assertFalse(second.changed)
        self.assertEqual(open(second.graph_md_path, encoding="utf-8").read(), graph_body)
        self.assertEqual(
            json.loads(state_body)["counts"], json.loads(open(second.state_path, encoding="utf-8").read())["counts"]
        )
        self.assertTrue(graph_body.startswith("<!-- asgard:map-graph schema=1 -->"))
        self.assertIn("- `src/app/api.py` — ", graph_body)
        self.assertIn("GET /users", graph_body)
        self.assertNotIn("tests/test_api.py", graph_body)
        state = json.loads(state_body)
        self.assertGreater(state["counts"]["edges"], 0)
        # 후보 증거는 카탈로그에서 `?`로 표시된다
        self.assertIn("?", graph_body)

    def test_scan_preserves_named_coverage_limits_in_state_and_projection(self):
        from asgard.map_graph import fresh_state, scan_graph

        self.seed()
        self.write("src/worker.go", "package worker\n")
        self.write("src/oversized.py", "#" * (512 * 1024 + 1))
        with open(os.path.join(self.root, "src/undecodable.py"), "wb") as stream:
            stream.write(b"\xff\xff")

        result = scan_graph(self.root)
        state = fresh_state(self.root)
        limits = {row["code"]: row for row in state["coverage"]["limits"]}

        self.assertEqual(result.coverage_status, "partial")
        self.assertEqual(list(result.coverage_limits), state["coverage"]["limits"])
        self.assertEqual(state["coverage"]["status"], "partial")
        self.assertIn("unsupported_source_suffix", limits)
        self.assertIn("src/worker.go", limits["unsupported_source_suffix"]["files"])
        self.assertIn("source_too_large", limits)
        self.assertIn("src/oversized.py", limits["source_too_large"]["files"])
        self.assertIn("source_undecodable", limits)
        self.assertIn("src/undecodable.py", limits["source_undecodable"]["files"])
        self.assertIn("test_sources_excluded", limits)
        self.assertIn("tests/test_api.py", limits["test_sources_excluded"]["files"])
        body = open(result.graph_md_path, encoding="utf-8").read()
        self.assertIn("## Coverage boundaries", body)
        self.assertIn("Coverage status: partial", body)
        self.assertIn("unsupported_source_suffix", body)

    def test_freshness_includes_files_outside_configured_extractors(self):
        from asgard.map_graph import GraphError, fresh_state, scan_graph

        self.seed()
        scan_graph(self.root)
        self.write("src/new_worker.go", "package worker\n")

        with self.assertRaisesRegex(GraphError, "stale"):
            fresh_state(self.root)

    def hub_state(self, spread: dict[str, int]) -> dict:
        """{개념 이름: 인접 파일 수} → 상태. 파일 노드가 개념을 하나씩 만진다."""
        nodes: list[dict] = []
        edges: list[dict] = []
        for name, count in spread.items():
            nodes.append(
                {"id": f"db_access:{name}", "kind": "db_access", "name": name, "confidence": "confirmed", "files": []}
            )
            for index in range(count):
                edges.append({"source": f"file:m{index}.py", "target": f"db_access:{name}", "kind": "touches"})
        return {"nodes": nodes, "edges": edges}

    def test_hubs_appear_only_where_the_graph_actually_has_hubs(self):
        """별 모양에서는 허브 절이 없어야 한다 — 하나뿐인 싱크는 방향이 아니다."""
        from asgard.map_graph.graph import _render_graph_md

        flat = self.hub_state({f"T{index}": 1 for index in range(20)})
        one_sink = self.hub_state({**{f"T{index}": 1 for index in range(20)}, "CONN": 10})
        peaked = self.hub_state({**{f"T{index}": 1 for index in range(20)}, "A": 40, "B": 30, "C": 12})

        self.assertNotIn("## Hubs", _render_graph_md(flat))
        self.assertNotIn("## Hubs", _render_graph_md(one_sink))
        body = _render_graph_md(peaked)
        self.assertIn("## Hubs", body)
        self.assertIn("`db_access:A` — db_access, 인접 40", body)
        # 꼬리는 허브가 아니다
        self.assertNotIn("`db_access:T0`", body.split("## Hubs", 1)[1].split("\n## ", 1)[0])

    def test_file_nodes_never_count_as_hubs(self):
        """파일 차수는 선언 개수를 그대로 베낀 값이라 '가장 큰 파일'을 다시 말할 뿐이다."""
        from asgard.map_graph.graph import _render_graph_md

        state = self.hub_state({**{f"T{index}": 1 for index in range(20)}, "A": 40, "B": 30, "C": 12})
        body = _render_graph_md(state)

        hubs = body.split("## Hubs", 1)[1].split("\n## ", 1)[0]
        self.assertNotIn("file:", hubs)

    def test_catalog_projects_every_relation_without_a_byte_cutoff(self):
        from asgard.map_graph.graph import _render_graph_md

        paths = [f"services/service-{index:03}/src/main/java/com/acme/Entrypoint.java" for index in range(500)]
        shared = "services/shared/src/main/java/com/acme/ManyEntrypoints.java"
        state = {
            "nodes": [
                {
                    "kind": "command",
                    "name": f"Entrypoint{index}",
                    "confidence": "confirmed",
                    "files": [{"file": path, "line": 1, "confidence": "confirmed", "detail": "boot"}],
                }
                for index, path in enumerate(paths)
            ]
            + [
                {
                    "kind": "command",
                    "name": f"SharedEntrypoint{index}",
                    "confidence": "confirmed",
                    "files": [{"file": shared, "line": index + 1, "confidence": "confirmed", "detail": "boot"}],
                }
                for index in range(20)
            ]
        }
        body = _render_graph_md(state)
        projected = {line.split("`", 2)[1] for line in body.splitlines() if line.startswith("- `")}
        self.assertGreater(len(body.encode("utf-8")), 24 * 1024)
        self.assertEqual(projected, {*paths, shared})
        shared_line = next(line for line in body.splitlines() if f"`{shared}`" in line)
        self.assertTrue(all(f"SharedEntrypoint{index}" in shared_line for index in range(20)))

    def test_scan_preserves_more_than_forty_relations_from_one_file(self):
        from asgard.map_graph import graph_state, scan_graph

        statements = "\n".join(f'<select id="find{index}">SELECT * FROM TABLE_{index}</select>' for index in range(60))
        self.write(
            "svc/src/main/resources/mapper/LargeMapper.xml", f'<mapper namespace="LargeMapper">{statements}</mapper>'
        )
        result = scan_graph(self.root)
        state = graph_state(self.root)
        assert state is not None
        names = {node["name"] for node in state["nodes"] if node["kind"] == "db_access"}
        self.assertIn("LargeMapper.find59", names)
        self.assertIn("TABLE_59", names)
        body = open(result.graph_md_path, encoding="utf-8").read()
        self.assertIn("LargeMapper.find59", body)
        self.assertIn("TABLE_59", body)

    def test_jvm_lane_scan_resolves_topics_and_respects_src_test_convention(self):
        from asgard.map_graph import graph_state, scan_graph, trace

        self.write("pyproject.toml", '[project]\nname = "jvm"\n')
        self.write("svc/src/main/java/com/acme/api/OrderController.java", _JAVA_CONTROLLER)
        self.write("svc/src/main/java/com/acme/stream/FrameListener.java", _JAVA_LISTENER)
        self.write("svc/src/main/resources/application.yml", _APPLICATION_YML)
        self.write("svc/src/main/resources/mapper/MeterMapper.xml", _MAPPER_XML)
        # JVM 관례: src/test 트리는 제외, src/main 아래 test 패키지 세그먼트는 프로덕션이다
        self.write("svc/src/test/java/com/acme/api/OrderControllerTest.java", _JAVA_CONTROLLER)
        self.write("svc/src/main/java/com/acme/rest/test/PingController.java", _JAVA_CONTROLLER)
        result = scan_graph(self.root)
        body = open(result.graph_md_path, encoding="utf-8").read()
        self.assertIn("frame.raw", body)  # ${acme.kafka.in} 이 base 설정으로 해석 승격됐다
        self.assertIn("GET /api/v1/orders/list", body)
        self.assertNotIn("src/test/java", body)
        self.assertIn("rest/test/PingController.java", body)
        state = graph_state(self.root)
        assert state is not None
        node = next(n for n in state["nodes"] if n["id"] == "event:frame.raw")
        self.assertEqual(node["confidence"], "confirmed")
        hops = trace(self.root, "event:frame.raw")
        self.assertIn("file:svc/src/main/java/com/acme/stream/FrameListener.java", {hop["id"] for hop in hops})
        # 자바 @Mapper 인터페이스 없이도 XML 네임스페이스 노드는 단순명으로 선다
        self.assertTrue(any(n["id"] == "db_access:MeterMapper" for n in state["nodes"]))

    def test_refuses_to_overwrite_human_owned_graph_md(self):
        from asgard.map_graph import GraphOwnershipError, scan_graph

        self.seed()
        self.write(".asgard/map/GRAPH.md", "# my own notes\n")
        with self.assertRaises(GraphOwnershipError):
            scan_graph(self.root)

    def test_force_reowns_human_owned_graph_md(self):
        # init 경로 — force는 소유권 거부만 우회해 현재 디렉토리 스캔 결과로 엎어쓴다.
        from asgard.map_graph import GraphOwnershipError, scan_graph

        self.seed()
        self.write(".asgard/map/GRAPH.md", "# my own notes\n")
        result = scan_graph(self.root, force=True)
        body = open(result.graph_md_path, encoding="utf-8").read()
        self.assertNotIn("# my own notes", body)
        scan_graph(self.root)  # 재귀속 후엔 asgard 소유 — 비강제 스캔이 다시 통과한다
        # force는 예약 파일명 충돌(안전 검사)은 우회하지 않는다
        os.remove(os.path.join(self.root, ".asgard", "map", "GRAPH.md"))
        self.write(".asgard/map/graph.md", "# imposter\n")
        with self.assertRaises(GraphOwnershipError):
            scan_graph(self.root, force=True)

    def test_scans_production_names_containing_test_and_rejects_state_symlink(self):
        from asgard.map_graph import GraphError, scan_graph

        self.seed()
        self.write("src/contest.py", 'import httpx\nhttpx.get("https://example.com/contest")\n')
        result = scan_graph(self.root)
        self.assertIn("src/contest.py", open(result.graph_md_path, encoding="utf-8").read())
        os.remove(result.state_path)
        outside = os.path.join(self.root, "outside")
        os.makedirs(outside)
        os.rmdir(os.path.join(self.root, ".asgard", "state"))
        os.symlink(outside, os.path.join(self.root, ".asgard", "state"))
        with self.assertRaises(GraphError):
            scan_graph(self.root)


class TestFlows(Base):
    """개념→개념 플로우 엣지 — 핸들러→자원 조인.

    선언자(라우트/커맨드/잡/리스너) 본문 스팬이 소비 증거(db/api/event/서비스)를 포함하면
    핸들러→자원 엣지를 만든다. 스팬이 근사(비구조 확장자)거나 증거가 candidate 면 candidate.
    """

    def edges_of(self):
        from asgard.map_graph import graph_state

        state = graph_state(self.root)
        assert state is not None
        return {(e["source"], e["target"], e["kind"]): e["confidence"] for e in state["edges"]}, state

    def test_python_handler_flows_confirmed_by_ast_span(self):
        from asgard.map_graph import scan_graph

        self.seed()
        result = scan_graph(self.root)
        edges, state = self.edges_of()
        # GET /users 핸들러 본문의 스트라이프 호출 — AST 스팬 + 양측 confirmed → confirmed
        self.assertEqual(
            edges.get(("route:GET_/users", "api_call:https://api.stripe.com/v1/charges", "calls")), "confirmed"
        )
        # POST /users 핸들러의 커서 실행 — db 증거가 candidate라 플로우도 candidate
        self.assertEqual(edges.get(("route:POST_/users", "db_access:connection.execute", "touches")), "candidate")
        # 모듈 상단 import(외부 서비스, line 1)는 어느 스팬에도 안 들어간다 — 지어내지 않는다
        self.assertNotIn(("route:GET_/users", "external_service:stripe", "uses"), edges)
        self.assertEqual(result.flows, state["counts"]["flows"])
        self.assertGreaterEqual(result.flows, 2)

    def test_java_method_body_flows_and_listener_emit(self):
        from asgard.map_graph import scan_graph

        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write(
            "src/main/java/com/acme/api/MeterController.java",
            """
package com.acme.api;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;
import org.springframework.jdbc.core.JdbcTemplate;

@RestController
public class MeterController {
    private final JdbcTemplate jdbcTemplate;
    private final RestTemplate restTemplate;

    @GetMapping("/meters")
    public String list() {
        jdbcTemplate.queryForList("SELECT * FROM TCFG_METER");
        return restTemplate.getForObject("https://vendor.example.com/v1/meters", String.class);
    }
}
""",
        )
        self.write("src/main/java/com/acme/stream/FrameListener.java", _JAVA_LISTENER)
        scan_graph(self.root)
        edges, _state = self.edges_of()
        # 메서드 본문 중괄호 스팬(.java 결정론) — 양측 confirmed → confirmed 플로우
        self.assertEqual(
            edges.get(("route:GET_/meters", "api_call:https://vendor.example.com/v1/meters", "calls")), "confirmed"
        )
        # jdbc 수신자 타입은 정적으로 못 묶는다(candidate) — 플로우도 candidate
        self.assertEqual(
            edges.get(("route:GET_/meters", "db_access:jdbcTemplate.queryForList", "touches")), "candidate"
        )
        # 리스너 본문의 send — 구독 핸들러 → 이벤트 emits
        emit_edges = [key for key in edges if key[2] == "emits" and key[0].startswith("event:")]
        self.assertTrue(emit_edges)
        # 어노테이션 없는 emit() 메서드의 send는 선언자가 아니다 — 플로우 소스가 되지 않는다
        self.assertNotIn("event:billing.raw", {key[0] for key in edges})

    def test_tsjs_inline_handler_flow_capped_candidate(self):
        from asgard.map_graph import scan_graph

        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write(
            "web/inline.ts",
            """
import express from 'express';
const app = express();
app.get('/inline', async (req, res) => {
  const data = await fetch('https://api.example.com/v1/data');
  res.json(data);
});
""",
        )
        scan_graph(self.root)
        edges, _state = self.edges_of()
        # 정규식 근사 스팬(.ts) — 양측 confirmed 여도 candidate로 캡한다
        self.assertEqual(
            edges.get(("route:GET_/inline", "api_call:https://api.example.com/v1/data", "calls")), "candidate"
        )

    def test_flows_projected_into_graph_md(self):
        from asgard.map_graph import scan_graph

        self.seed()
        result = scan_graph(self.root)
        body = open(result.graph_md_path, encoding="utf-8").read()
        self.assertIn("## Flows", body)
        self.assertIn("- `GET /users` — calls `https://api.stripe.com/v1/charges`", body)
        self.assertIn("touches `connection.execute`?", body)  # candidate 플로우는 `?` 표기

    def test_trace_kinds_filter_joins_db_to_route(self):
        from asgard.map_graph import GraphError, scan_graph, trace

        self.seed()
        scan_graph(self.root)
        # DB 앵커 업스트림 — 어떤 핸들러가 이 접근을 소유하는가
        hops = trace(self.root, "db_access:connection.execute", direction="upstream", kinds={"touches"})
        ids = {hop["id"] for hop in hops}
        self.assertIn("route:POST_/users", ids)
        route_hop = next(hop for hop in hops if hop["id"] == "route:POST_/users")
        self.assertEqual(route_hop["via"], "touches")
        self.assertEqual(route_hop["via_confidence"], "candidate")
        # declares만 따라가면 플로우는 배제된다
        hops = trace(self.root, "db_access:connection.execute", direction="upstream", kinds={"declares"})
        self.assertNotIn("route:POST_/users", {hop["id"] for hop in hops})
        with self.assertRaises(GraphError):
            trace(self.root, "db_access:connection.execute", kinds={"accesses_db"})
        with self.assertRaises(GraphError):
            trace(self.root, "db_access:connection.execute", kinds=set())


class TestTrace(Base):
    def test_trace_walks_edges_and_unknown_node_suggests_candidates(self):
        from asgard.map_graph import GraphError, scan_graph, trace

        self.seed()
        scan_graph(self.root)
        hops = trace(self.root, "external_service:stripe")
        ids = {hop["id"] for hop in hops}
        self.assertIn("file:src/app/api.py", ids)
        # depth 2: 파일을 거쳐 그 파일이 선언한 라우트까지 도달한다
        self.assertTrue(any(hop["id"].startswith("route:") for hop in hops))
        with self.assertRaises(GraphError) as caught:
            trace(self.root, "external_service:strip")
        self.assertIn("candidates", str(caught.exception))

    def test_unknown_concept_word_recovers_kind_diverse_candidates(self):
        from asgard.map_graph import GraphError, scan_graph, trace

        self.seed()
        scan_graph(self.root)
        # "users" 개념어 — api_call이 알파벳 선두여도 route 후보가 함께 나와야 회복이 된다
        with self.assertRaises(GraphError) as caught:
            trace(self.root, "users")
        message = str(caught.exception)
        self.assertIn("route:GET_/users", message)
        # 후보에는 대표 앵커가 동봉된다 — 두 번째 호출 없이 소스로 직행할 수 있다
        self.assertIn("route:GET_/users @ src/app/api.py:", message)

    def test_stat_freshness_detects_touch_and_legacy_state_falls_back(self):
        import time as time_module

        from asgard.map_graph import GraphError, fresh_state, scan_graph, trace

        self.seed()
        result = scan_graph(self.root)
        state = fresh_state(self.root)
        # 스탯 검사 경로 — 표식이 있으면 내용 재독취 없이 통과한다
        self.assertTrue(state.get("stat_revision", "").startswith("source-stat-sha256:"))
        # 내용 동일 touch(mtime 변경)도 stale로 본다 — 오탐은 재스캔 방향으로만 틀린다
        target = os.path.join(self.root, "src/app/api.py")
        stamp = time_module.time() + 5
        os.utime(target, (stamp, stamp))
        with self.assertRaises(GraphError):
            trace(self.root, "external_service:stripe")
        scan_graph(self.root)
        # 구 상태(스탯 표식 없음)는 내용 다이제스트 폴백으로 여전히 동작한다
        with open(result.state_path, encoding="utf-8") as stream:
            legacy = json.load(stream)
        del legacy["stat_revision"]
        with open(result.state_path, "w", encoding="utf-8") as stream:
            json.dump(legacy, stream, ensure_ascii=False)
        self.assertTrue(trace(self.root, "external_service:stripe"))

    def test_trace_rejects_stale_state_and_invalid_bounds(self):
        from asgard.map_graph import GraphError, scan_graph, trace

        self.seed()
        scan_graph(self.root)
        self.write("src/app/api.py", _PY_FIXTURE + '\nhttpx.get("https://new.example.com")\n')
        with self.assertRaisesRegex(GraphError, "stale"):
            trace(self.root, "external_service:stripe")
        scan_graph(self.root)
        with self.assertRaisesRegex(GraphError, "depth"):
            trace(self.root, "external_service:stripe", depth=9)
        with self.assertRaisesRegex(GraphError, "direction"):
            trace(self.root, "external_service:stripe", direction="sideways")


class TestGraphMdSeeds(Base):
    def test_trace_seeds_and_navigation_contract(self):
        from asgard.map_graph import scan_graph

        self.seed()
        result = scan_graph(self.root)
        with open(result.graph_md_path, encoding="utf-8") as stream:
            body = stream.read()
        # 카탈로그 행이 곧 trace 시드다 — 노드 id 재구성을 강요하지 않는다 (platty traceId 대등)
        self.assertIn("## Trace seeds", body)
        self.assertIn("`route:GET_/users`", body)
        self.assertIn("asgard map list", body)
        self.assertIn("asgard map impact", body)
        # 부재 규율 — 엣지 없음은 의존 없음의 증거가 아니다
        self.assertIn("not evidence of absence", body)


class TestImpactDossier(Base):
    def test_stable_snapshot_separates_evidence_and_named_limits(self):
        from asgard.map_graph import fresh_state, impact_report, scan_graph

        self.seed()
        scan_graph(self.root)

        first = impact_report(self.root, "route:GET_/users", depth=1)
        state = fresh_state(self.root)
        reordered_state = {
            **state,
            "nodes": list(reversed(state["nodes"])),
            "edges": list(reversed(state["edges"])),
            "coverage": {**state["coverage"], "limits": list(reversed(state["coverage"]["limits"]))},
        }
        reordered = impact_report(self.root, "route:GET_/users", depth=1, state=reordered_state)

        self.assertEqual(first["schema"], 1)
        self.assertTrue(first["source_revision"].startswith("source-sha256:"))
        self.assertTrue(first["impact_revision"].startswith("sha256:"))
        self.assertEqual(first["impact_revision"], reordered["impact_revision"])
        self.assertEqual(first["origin"]["id"], "route:GET_/users")
        self.assertEqual(first["origin"]["file"], "src/app/api.py")
        self.assertGreaterEqual(first["origin"]["line_end"], first["origin"]["line_start"])
        self.assertEqual(first["coverage"]["status"], "partial")
        codes = {row["code"] for row in first["coverage"]["limits"]}
        self.assertIn("test_sources_excluded", codes)
        self.assertTrue(first["evidence"])
        self.assertTrue(all(row["evidence_id"].startswith("sha256:") for row in first["evidence"]))
        self.assertTrue(all(row["line_end"] >= row["line_start"] for row in first["evidence"] if row["file"]))
        self.assertTrue(all("next_exact_read" in row for row in first["evidence"]))

        self.write("src/app/api.py", _PY_FIXTURE + '\nhttpx.get("https://new.example.com")\n')
        scan_graph(self.root)
        changed = impact_report(self.root, "route:GET_/users", depth=1)
        self.assertNotEqual(first["impact_revision"], changed["impact_revision"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
