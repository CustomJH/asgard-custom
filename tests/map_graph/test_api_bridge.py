#!/usr/bin/env python3
"""페이지→API→라우트 결합 — 경로 대조와 모호 매치 처리.

실행: uv run pytest tests/map_graph
"""

import unittest

from map_graph.map_base import (
    Base,
)

_JAVA_USER_API = """
package com.acme.api;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.jdbc.core.JdbcTemplate;

@RestController
@RequestMapping("/api/users")
public class UserController {
    private final JdbcTemplate jdbcTemplate;

    @GetMapping
    public String list() {
        jdbcTemplate.queryForList("SELECT * FROM TUSER");
        return "ok";
    }

    @GetMapping("/{id}")
    public String detail() { return "ok"; }
}
"""


_VUE_USERS_PAGE = """
<template><div /></template>
<script setup>
const rows = await $fetch('/api/users')
const one = await $fetch(`/api/users/${id}`)
</script>
"""


class TestApiRouteBridge(Base):
    """API↔라우트 브리지 — 프론트/원격 호출과 백엔드 표면의 경로 수렴 (전부 candidate).

    베이스 URL·프록시 접두는 정적으로 증명할 수 없다: 완전 일치는 "path match", 접두 차이만
    나는 일치는 "path suffix match"로 이유를 보존하고, 수렴 실패(과다 일치)는 통째로 버린다.
    """

    def edges_of(self):
        from asgard.map_graph import graph_state

        state = graph_state(self.root)
        assert state is not None
        return {(e["source"], e["target"], e["kind"]): e for e in state["edges"]}, state

    def seed_stack(self) -> None:
        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write("src/main/java/com/acme/api/UserController.java", _JAVA_USER_API)
        self.write("web/pages/users/index.vue", _VUE_USERS_PAGE)

    def test_exact_and_placeholder_path_match(self):
        from asgard.map_graph import scan_graph

        self.seed_stack()
        result = scan_graph(self.root)
        edges, state = self.edges_of()
        exact = edges.get(("api_call:/api/users", "route:GET_/api/users", "calls"))
        self.assertIsNotNone(exact)
        self.assertEqual(exact["confidence"], "candidate")
        self.assertEqual(exact["detail"], "path match")
        # `${id}` 보간(`{}`)과 Spring `{id}`는 같은 와일드카드 세그먼트로 수렴한다 (id는 슬러그 표기)
        self.assertIn(("api_call:/api/users/_", "route:GET_/api/users/_id_", "calls"), edges)
        self.assertEqual(result.api_links, state["counts"]["api_links"])
        self.assertGreaterEqual(result.api_links, 2)

    def test_full_stack_join_page_to_db(self):
        from asgard.map_graph import scan_graph, trace

        self.seed_stack()
        scan_graph(self.root)
        # 얕은 깊이의 절단은 침묵하지 않는다 — 미탐색 이웃이 남은 홉에 truncated 표식
        shallow = trace(self.root, "page:/users", depth=1, direction="downstream", kinds={"calls", "touches"})
        self.assertTrue(all(hop["depth"] == 1 for hop in shallow))
        self.assertTrue(any(hop["truncated"] for hop in shallow))
        api_hop = next(hop for hop in shallow if hop["id"] == "api_call:/api/users")
        self.assertEqual(api_hop["file"], "web/pages/users/index.vue")
        self.assertGreater(api_hop["line"], 0)
        # 페이지 → 래퍼 호출 → 라우트 → DB를 한 번의 trace로 조인한다 (platty 대등 교차 레인)
        deep = trace(self.root, "page:/users", depth=4, direction="downstream", kinds={"calls", "touches"})
        ids = {hop["id"] for hop in deep}
        self.assertIn("route:GET_/api/users", ids)
        self.assertIn("db_access:jdbcTemplate.queryForList", ids)
        self.assertFalse(any(hop["truncated"] for hop in deep))

    def test_suffix_match_respects_method_and_literal_guard(self):
        from asgard.map_graph import scan_graph

        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write(
            "server/app.ts",
            "const app = express();\napp.get('/users', handler);\napp.post('/users', handler);\n",
        )
        self.write("web/api.ts", "apiGet('/gw/users')\napiGet(`/${id}`)\n")
        scan_graph(self.root)
        edges, _state = self.edges_of()
        suffix = edges.get(("api_call:/gw/users", "route:GET_/users", "calls"))
        self.assertIsNotNone(suffix)
        self.assertEqual(suffix["detail"], "path suffix match")
        # 래퍼 이름의 메서드(apiGet)와 다른 라우트(POST)는 잇지 않는다
        self.assertNotIn(("api_call:/gw/users", "route:POST_/users", "calls"), edges)
        # 순수 와일드카드 경로(`/${id}`)는 리터럴 근거가 없다 — 지어내지 않는다
        wildcard_links = [key for key in edges if key[0] == "api_call:/_" and key[1].startswith("route:")]
        self.assertEqual(wildcard_links, [])

    def test_api_base_extraction_accepts_idioms_and_rejects_noise(self):
        from asgard.map_graph.extract_tsjs import extract_api_bases

        source = """
const API_BASE_URL = '/api/v2'
const client = axios.create({ baseURL: 'https://api.example.com/v1/' })
const fallback = ofetch.create({ baseURL: import.meta.env.VITE_API ?? '/gw' })
const userUrl = '/users'
const origin = 'https://example.com'
const computed = `${API_BASE_URL}/x`
"""
        # base 성격 이름의 체크인 리터럴만 — 일반 상수·경로 없는 오리진·계산식은 제외
        self.assertEqual(extract_api_bases(source), ["/api/v2", "/v1", "/gw"])

    def test_too_many_api_bases_are_preserved_as_an_ambiguity_limit(self):
        from asgard.map_graph import graph_state, scan_graph

        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write(
            "web/services/client.ts",
            "\n".join(
                [
                    "const API_BASE_URL = '/one'",
                    "const apiBase = '/two'",
                    "const apiBasePath = '/three'",
                    "const apiPrefix = '/four'",
                    "const apiRoot = '/five'",
                ]
            ),
        )

        scan_graph(self.root)
        state = graph_state(self.root)
        assert state is not None
        limit = next(row for row in state["coverage"]["limits"] if row["code"] == "api_base_ambiguous")
        self.assertEqual(limit["subject"], "web")
        self.assertEqual(limit["candidates"], ["/five", "/four", "/one", "/three", "/two"])

    def test_fe_base_prefix_promotes_suffix_to_exact_via_base(self):
        from asgard.map_graph import scan_graph

        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write("be/src/main/resources/application.yml", "api:\n  prefix: /api/v2/\n")
        self.write(
            "be/src/main/java/com/acme/mon/MonController.java",
            """
package com.acme.mon;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("${api.prefix}string-monitoring")
public class MonController {
    @GetMapping("/sites")
    public String sites() { return "ok"; }
}
""",
        )
        # helios 관용구 — FE 스코프의 상수 베이스가 같은 스코프의 상대 경로 호출에 적용된다
        self.write("web/services/client.ts", "const API_BASE_URL = '/api/v2'\n")
        self.write(
            "web/pages/mon.vue",
            """
<template><div /></template>
<script setup>
await $fetch('/string-monitoring/sites')
</script>
""",
        )
        scan_graph(self.root)
        edges, _state = self.edges_of()
        link = edges.get(("api_call:/string-monitoring/sites", "route:GET_/api/v2/string-monitoring/sites", "calls"))
        self.assertIsNotNone(link)
        self.assertEqual(link["detail"], "path match via /api/v2")
        self.assertEqual(link["confidence"], "candidate")

    def test_original_exact_match_outranks_base_prefixed(self):
        from asgard.map_graph import scan_graph

        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write("web/services/client.ts", "const API_BASE_URL = '/api'\n")
        self.write(
            "web/server.ts",
            "const app = express();\napp.get('/health', handler);\n",
        )
        self.write("web/pages/x.vue", "<script setup>\nawait $fetch('/health')\n</script>\n")
        scan_graph(self.root)
        edges, _state = self.edges_of()
        link = edges.get(("api_call:/health", "route:GET_/health", "calls"))
        self.assertIsNotNone(link)
        # 원문 그대로의 완전 일치가 있으면 베이스 접두 해석보다 우선한다
        self.assertEqual(link["detail"], "path match")

    def test_resolved_gateway_prefix_yields_exact_and_suffix_links(self):
        from asgard.map_graph import scan_graph

        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write("be/src/main/resources/application.yml", "api:\n  prefix: /api/v2/\n")
        self.write(
            "be/src/main/java/com/acme/mon/MonController.java",
            """
package com.acme.mon;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("${api.prefix}string-monitoring")
public class MonController {
    @GetMapping("/sites")
    public String sites() { return "ok"; }
}
""",
        )
        self.write(
            "web/pages/mon.vue",
            """
<template><div /></template>
<script setup>
await $fetch('/api/v2/string-monitoring/sites')
await $fetch('/string-monitoring/sites')
</script>
""",
        )
        scan_graph(self.root)
        edges, _state = self.edges_of()
        # base yml 해석으로 라우트 이름이 실제 경로가 된다 — 프리픽스 포함 호출은 완전 일치
        exact = edges.get(
            ("api_call:/api/v2/string-monitoring/sites", "route:GET_/api/v2/string-monitoring/sites", "calls")
        )
        self.assertIsNotNone(exact)
        self.assertEqual(exact["detail"], "path match")
        # 프리픽스 없는 호출(게이트웨이 재작성)은 접미 일치로 이유가 남는다
        suffix = edges.get(("api_call:/string-monitoring/sites", "route:GET_/api/v2/string-monitoring/sites", "calls"))
        self.assertIsNotNone(suffix)
        self.assertEqual(suffix["detail"], "path suffix match")

    def test_gateway_prefix_strips_and_wildcard_never_matches_literal(self):
        from asgard.map_graph import scan_graph

        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write(
            "src/main/java/com/acme/mon/MonController.java",
            """
package com.acme.mon;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("${api.prefix}string-monitoring")
public class MonController {
    @GetMapping("/sites/{siteCode}/overview")
    public String overview() { return "ok"; }

    @GetMapping("/users/{id}")
    public String user() { return "ok"; }
}
""",
        )
        self.write(
            "web/pages/mon.vue",
            """
<template><div /></template>
<script setup>
await $fetch(`/string-monitoring/sites/${code}/overview`)
await $fetch('/users/me')
</script>
""",
        )
        scan_graph(self.root)
        edges, _state = self.edges_of()
        # `${api.prefix}` 설정 접두를 벗기면 남은 리터럴이 세그먼트 정체다 — 완전 일치로 승격
        exact = edges.get(
            (
                "api_call:/string-monitoring/sites/_/overview",
                "route:GET_/_api.prefix_string-monitoring/sites/_siteCode_/overview",
                "calls",
            )
        )
        self.assertIsNotNone(exact)
        self.assertEqual(exact["detail"], "path match")
        # 한쪽만 변수인 자리는 잇지 않는다 — `/users/me`는 `/users/{id}`의 증거가 아니다
        me_links = [key for key in edges if key[0] == "api_call:/users/me" and key[1].startswith("route:")]
        self.assertEqual(me_links, [])

    def test_ambiguous_match_is_dropped_whole(self):
        from asgard.map_graph import scan_graph

        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        routes = "\n".join(f"app.get('/a{i}/x', handler);" for i in range(9))
        self.write("server/app.ts", f"const app = express();\n{routes}\n")
        self.write("web/api.ts", "fetch('/x')\n")
        scan_graph(self.root)
        edges, state = self.edges_of()
        links = [key for key in edges if key[0] == "api_call:/x" and key[1].startswith("route:")]
        self.assertEqual(links, [])
        self.assertEqual(state["counts"]["api_links"], 0)
        limit = next(row for row in state["coverage"]["limits"] if row["code"] == "api_route_ambiguous")
        self.assertEqual(limit["subject"], "api_call:/x")
        self.assertEqual(len(limit["candidates"]), 9)


if __name__ == "__main__":
    unittest.main(verbosity=1)
