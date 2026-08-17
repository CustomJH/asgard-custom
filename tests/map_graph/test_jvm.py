#!/usr/bin/env python3
"""JVM 레인 — 자바 추출·크로스파일 해소·DB 매퍼·스프링 프로퍼티.

실행: uv run pytest tests/map_graph
"""

import unittest

from map_graph.map_base import (
    _APPLICATION_YML,
    _JAVA_CONTROLLER,
    _JAVA_LISTENER,
    _MAPPER_XML,
    Base,
)

_JAVA_STORE = """
package com.acme.store;

import jakarta.persistence.Entity;
import org.apache.ibatis.annotations.Mapper;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.scheduling.annotation.Scheduled;

@Entity
public class Meter { }

@Mapper
public interface MeterMapper extends MeterStore { }

interface MeterRepository extends JpaRepository<Meter, Long> { }

class Jobs {
    @Scheduled(cron = "0 0 * * * *")
    public void rollup() { }
}
"""


_PROC_FIXTURE = """
int load(void) {
    /* update counters in C code: from memory */
    EXEC SQL SELECT mid INTO :row FROM TCFG_METER WHERE mid = :mid;
    EXEC SQL INSERT INTO REGUL2_TBL_RS ( GUBUN ) VALUES ( :g );
}
"""


class TestJavaExtractor(Base):
    def kinds(self, source: str, path: str = "svc/src/main/java/App.java") -> dict:
        from asgard.map_graph.extract_java import extract_java

        out = {}
        for item in extract_java(path, source):
            out.setdefault(item.kind, []).append(item)
        return out

    def test_spring_routes_join_class_prefix_and_ignore_comment_annotations(self):
        found = self.kinds(_JAVA_CONTROLLER)
        self.assertEqual({e.name for e in found["route"]}, {"GET /api/v1/orders/list", "POST /api/v1/orders"})
        self.assertTrue(all(e.confidence == "confirmed" and e.line > 0 for e in found["route"]))

    def test_annotation_literal_concatenation_joins_route_path(self):
        found = self.kinds(
            """
package com.acme;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("${api.prefix}" + "orbit/home")
public class OrbitHomeController {
    @GetMapping("/{id}" + "/detail")
    public String detail() { return "ok"; }
}
"""
        )
        # 전부-리터럴 `+` 연쇄는 정적으로 증명된다 — 리소스 세그먼트를 유실하지 않는다
        self.assertEqual({e.name for e in found["route"]}, {"GET /${api.prefix}orbit/home/{id}/detail"})
        self.assertNotIn("GET /ghost", {e.name for e in found["route"]})

    def test_route_without_spring_import_is_candidate(self):
        found = self.kinds('@GetMapping("/x")\nclass C { }')
        self.assertEqual(found["route"][0].confidence, "candidate")

    def test_kafka_listener_placeholder_stays_candidate_until_resolution(self):
        found = self.kinds(_JAVA_LISTENER)
        by_name = {e.name: e for e in found["event"]}
        self.assertEqual(by_name["${acme.kafka.in}"].confidence, "candidate")
        self.assertIn("subscribe", by_name["${acme.kafka.in}"].detail)
        self.assertEqual(by_name["audit.raw"].confidence, "confirmed")
        self.assertEqual(by_name["billing.raw"].confidence, "confirmed")
        self.assertEqual(by_name["billing.raw"].detail, "send")
        self.assertEqual(by_name["kafkaTemplate.send"].confidence, "candidate")

    def test_store_declarations_and_boot_entrypoint(self):
        found = self.kinds(_JAVA_STORE)
        self.assertEqual([(e.name, e.confidence) for e in found["model"]], [("Meter", "confirmed")])
        names = {e.name: e for e in found["db_access"]}
        self.assertEqual(names["MeterMapper"].detail, "mybatis mapper")
        self.assertEqual(names["MeterRepository"].detail, "JpaRepository")
        self.assertEqual([(e.name, e.detail) for e in found["job"]], [("rollup", "0 0 * * * *")])
        boot = self.kinds(
            "import org.springframework.boot.autoconfigure.SpringBootApplication;\n"
            "@SpringBootApplication\npublic class FepaApplication { }"
        )
        self.assertEqual([(e.name, e.confidence) for e in boot["command"]], [("FepaApplication", "confirmed")])

    def test_entity_scan_and_mapper_scan_are_not_declarations(self):
        found = self.kinds(
            "import jakarta.persistence.Entity;\nimport org.apache.ibatis.annotations.Mapper;\n"
            "@EntityScan\n@MapperScan\nclass Config { }"
        )
        self.assertNotIn("model", found)
        self.assertNotIn("db_access", found)

    def test_external_service_imports_and_rest_call(self):
        found = self.kinds(
            "import org.apache.kafka.clients.producer.KafkaProducer;\nimport oracle.jdbc.OracleDriver;\n"
            'class C { void f() { restTemplate.getForObject("https://user:pw@pay.example.com/v1?k=s", String.class); } }'
        )
        self.assertEqual({e.name for e in found["external_service"]}, {"kafka", "oracle"})
        self.assertEqual(found["api_call"][0].name, "https://pay.example.com/v1")
        self.assertEqual(found["api_call"][0].confidence, "confirmed")


class TestJvmCrossFileResolution(Base):
    """계층형 Spring 앱의 라우트↔SQL — 같은 파일 스팬으로는 닿지 않는 다리."""

    def seed_layers(self, *, extra_impl: str = "") -> None:
        self.write("pyproject.toml", '[project]\nname = "be"\n')
        self.write(
            "svc/src/main/java/com/acme/rest/MeterController.java",
            "package com.acme.rest;\n\n"
            "import com.acme.spec.MeterService;\n"
            "import org.springframework.web.bind.annotation.RestController;\n\n"
            "@RestController\n"
            '@RequestMapping("/api/meters")\n'
            "public class MeterController {\n"
            "    private final MeterService meterService;\n\n"
            '    @GetMapping("/{id}")\n'
            # 어노테이션 인자로 괄호가 중첩되는 시그니처 — 메서드 스팬이 여기서 끊기면 안 된다
            "    public Object getMeter(@ScopeFilter(allowEmpty = true) Scope scope,\n"
            "            @PathVariable Long id) {\n"
            "        return meterService.findMeter(id);\n"
            "    }\n"
            "}\n",
        )
        self.write(
            "svc/src/main/java/com/acme/spec/MeterService.java",
            "package com.acme.spec;\n\npublic interface MeterService {\n    Object findMeter(Long id);\n}\n",
        )
        self.write(
            "svc/src/main/java/com/acme/logic/MeterLogic.java",
            "package com.acme.logic;\n\n"
            "import com.acme.spec.MeterService;\n"
            "import com.acme.store.MeterStore;\n\n"
            "public class MeterLogic implements MeterService {\n"
            "    private final MeterStore meterStore;\n\n"
            "    @Override\n"
            "    public Object findMeter(Long id) {\n"
            "        return meterStore.findMeter(id);\n"
            "    }\n"
            "}\n",
        )
        self.write(
            "svc/src/main/java/com/acme/store/MeterStore.java",
            "package com.acme.store;\n\npublic interface MeterStore {\n    Object findMeter(Long id);\n}\n",
        )
        # MyBatis 매퍼 인터페이스가 Store를 상속하고, XML namespace가 그 FQN 이다
        self.write(
            "store/src/main/java/com/acme/store/MeterMapper.java",
            "package com.acme.store;\n\npublic interface MeterMapper extends MeterStore {\n"
            "    Object findMeter(Long id);\n}\n",
        )
        self.write("store/src/main/resources/mapper/MeterMapper.xml", _MAPPER_XML)
        if extra_impl:
            self.write("store/src/main/java/com/acme/store/OtherMeterStore.java", extra_impl)

    def test_route_reaches_sql_statement_and_table_across_files(self):
        from asgard.map_graph import graph_state, scan_graph

        self.seed_layers()
        scan_graph(self.root)
        state = graph_state(self.root)
        assert state is not None
        edges = {(e["source"], e["target"], e["kind"]) for e in state["edges"]}
        # 컨트롤러 → 스펙 인터페이스 → 구현 → 스토어 → 매퍼 XML을 건너 라우트가 구문에 닿는다
        self.assertIn(("route:GET_/api/meters/_id_", "db_access:MeterMapper.findMeter", "touches"), edges)
        # 구문 → 테이블은 매퍼 XML이 소유한다 — 둘이 이어져 라우트→테이블 체인이 읽힌다
        self.assertIn(("db_access:MeterMapper.findMeter", "db_access:TCFG_METER", "touches"), edges)
        detail = next(
            e.get("detail", "")
            for e in state["edges"]
            if (e["source"], e["target"]) == ("route:GET_/api/meters/_id_", "db_access:MeterMapper.findMeter")
        )
        self.assertIn("MeterController.getMeter", detail)

    def test_ambiguous_implementations_are_not_linked(self):
        from asgard.map_graph import graph_state, scan_graph

        # 같은 이름의 구문을 가진 매퍼가 둘이면 어느 빈이 뜨는지 정적으로 증명할 수 없다
        self.seed_layers(
            extra_impl="package com.acme.store;\n\npublic interface OtherMeterStore extends MeterStore {\n"
            "    Object findMeter(Long id);\n}\n"
        )
        self.write(
            "store/src/main/resources/mapper/OtherMeterMapper.xml",
            '<mapper namespace="com.acme.store.OtherMeterStore">\n'
            '<select id="findMeter">SELECT * FROM OTHER_METER</select>\n</mapper>\n',
        )
        scan_graph(self.root)
        state = graph_state(self.root)
        assert state is not None
        linked = {
            e["target"]
            for e in state["edges"]
            if e["source"] == "route:GET_/api/meters/_id_" and e["kind"] == "touches"
        }
        self.assertEqual(linked, set())

    def test_non_field_receivers_are_not_resolved(self):
        from asgard.map_graph.resolve_jvm import JvmIndex, index_java

        source = (
            "package com.acme.logic;\n\npublic class LocalOnly {\n"
            "    public void run() {\n"
            "        MeterStore local = factory.create();\n"
            "        local.findMeter(1L);\n"
            "    }\n}\n"
        )
        module = index_java("svc/LocalOnly.java", source)
        index = JvmIndex([module], {"com.acme.store.MeterStore#findMeter": "db_access:MeterMapper.findMeter"})
        unit = next(u for u in module.units if u.name == "run")
        reached = index.statements_from(module, unit)
        self.assertIsNotNone(reached, "상한을 넘지 않았으므로 버려지면 안 된다")
        assert reached is not None
        found, partial = reached
        # 로컬 변수 수신자는 타입이 증명되지 않는다 — 잇지 않고 미해결로 표시한다
        self.assertEqual(found, set())
        self.assertTrue(partial)


class TestJvmDbExtractors(Base):
    def test_mapper_xml_namespace_statements_and_table_candidates(self):
        from asgard.map_graph.extract_java import extract_mapper_xml

        found = extract_mapper_xml("store/src/main/resources/mapper/MeterMapper.xml", _MAPPER_XML)
        by_name = {e.name: e for e in found}
        self.assertEqual(by_name["MeterMapper"].confidence, "confirmed")
        self.assertIn("com.acme.store.MeterMapper", by_name["MeterMapper"].detail)
        self.assertEqual(by_name["MeterMapper.findMeter"].detail, "select")
        self.assertEqual(by_name["TCFG_METER"].confidence, "candidate")
        # `<update id=...>` 태그와 SQL 예약어는 테이블이 아니다
        self.assertNotIn("ID", by_name)
        self.assertNotIn("SET", by_name)
        self.assertNotIn("DUAL", by_name)
        self.assertEqual(extract_mapper_xml("pom.xml", "<project><id>x</id></project>"), [])

    def test_comments_are_not_evidence(self):
        from asgard.map_graph.extract_java import extract_mapper_xml, extract_sql

        # XML 주석의 산문("from a page")·주석 처리된 구문은 증거가 아니다
        commented = (
            '<mapper namespace="com.acme.KbTagMapper">\n'
            "<!-- Remove a tag from a page -->\n"
            '<!-- <select id="deadQuery">SELECT * FROM ghost_tbl</select> -->\n'
            '<delete id="deletePageTag">DELETE FROM kb_page_tag WHERE id = 1</delete>\n'
            "</mapper>\n"
        )
        names = {e.name for e in extract_mapper_xml("mapper/KbTagMapper.xml", commented)}
        self.assertIn("KB_PAGE_TAG", names)
        self.assertNotIn("A", names)
        self.assertNotIn("GHOST_TBL", names)
        self.assertNotIn("KbTagMapper.deadQuery", names)
        # SQL 주석 속 죽은 DDL도 선언이 아니다 (줄 번호는 보존)
        sql = "-- CREATE TABLE ghost (id int);\n/*\nCREATE TABLE ghost2 (id int);\n*/\nCREATE TABLE live (id int);\n"
        live = extract_sql("schema/x.sql", sql)
        self.assertEqual([(e.name, e.line) for e in live], [("LIVE", 5)])

    def test_sql_ddl_and_proc_embedded_sql(self):
        from asgard.map_graph.extract_java import extract_proc, extract_sql

        ddl = extract_sql("schema/epas/meter.sql", "CREATE TABLE IF NOT EXISTS mdm.tcfg_meter (id int);")
        self.assertEqual([(e.name, e.confidence, e.detail) for e in ddl], [("TCFG_METER", "confirmed", "create table")])
        proc = extract_proc("aimir/lib/db/REGUL2.pc", _PROC_FIXTURE)
        self.assertEqual({e.name for e in proc}, {"TCFG_METER", "REGUL2_TBL_RS"})
        self.assertTrue(all(e.confidence == "candidate" and e.detail == "exec sql" for e in proc))
        # C 본문 주석의 "from memory"는 EXEC SQL 구간이 아니다
        self.assertNotIn("MEMORY", {e.name for e in proc})


class TestSpringProps(Base):
    def evidence(self, name: str, file: str = "svc/src/main/java/App.java"):
        from asgard.map_graph.evidence import Evidence

        return Evidence("event", name, file, 3, "candidate", "subscribe")

    def test_promotes_placeholder_from_scoped_base_config_with_env_default(self):
        from asgard.map_graph.spring_props import SpringProps

        props = SpringProps()
        props.ingest("svc/src/main/resources/application.yml", _APPLICATION_YML)
        promoted = props.promote([self.evidence("${acme.kafka.in}")])[0]
        self.assertEqual(promoted.name, "frame.raw")
        self.assertEqual(promoted.confidence, "confirmed")
        self.assertIn("${acme.kafka.in} → svc/src/main/resources/application.yml", promoted.detail)

    def test_ambiguous_and_unknown_keys_preserve_the_placeholder(self):
        from asgard.map_graph.spring_props import SpringProps

        props = SpringProps()
        props.ingest("svc/src/main/resources/application.yml", _APPLICATION_YML)
        props.ingest("svc/config/application.yml", "acme:\n  kafka:\n    ambiguous: two\n")
        kept = props.promote([self.evidence("${acme.kafka.ambiguous}"), self.evidence("${acme.missing}")])
        self.assertEqual([e.name for e in kept], ["${acme.kafka.ambiguous}", "${acme.missing}"])
        self.assertTrue(all(e.confidence == "candidate" for e in kept))

    def test_scope_isolation_with_unique_repo_wide_fallback(self):
        from asgard.map_graph.spring_props import SpringProps

        props = SpringProps()
        props.ingest("svc/src/main/resources/application.yml", _APPLICATION_YML)
        # 다른 스코프의 소비자도 리포 전체에서 유일한 정의는 증명으로 쓸 수 있다
        unique = props.promote([self.evidence("${acme.kafka.in}", file="other/src/main/java/App.java")])[0]
        self.assertEqual(unique.name, "frame.raw")
        props.ingest("other/src/main/resources/application.yml", "acme:\n  kafka:\n    in: other.raw\n")
        scoped = props.promote([self.evidence("${acme.kafka.in}", file="other/src/main/java/App.java")])[0]
        self.assertEqual(scoped.name, "other.raw")

    def test_annotation_inline_default_is_last_resort(self):
        from asgard.map_graph.spring_props import SpringProps

        promoted = SpringProps().promote([self.evidence("${ACME_TOPIC:inline.raw}")])[0]
        self.assertEqual((promoted.name, promoted.confidence), ("inline.raw", "confirmed"))
        self.assertIn("annotation default", promoted.detail)

    def test_route_embedded_prefix_resolves_from_base_config(self):
        from asgard.map_graph.evidence import Evidence
        from asgard.map_graph.spring_props import SpringProps

        props = SpringProps()
        props.ingest("svc/src/main/resources/application.yml", "api:\n  prefix: /api/v2/\n")
        route = Evidence("route", "GET /${api.prefix}orders/{id}", "svc/src/main/java/App.java", 9, "confirmed")
        promoted = props.promote([route])[0]
        # 임베디드 치환 + 프리픽스 값의 중복 슬래시 정돈 — 실제 경로가 노드 정체가 된다
        self.assertEqual(promoted.name, "GET /api/v2/orders/{id}")
        self.assertEqual(promoted.confidence, "confirmed")
        self.assertIn("${api.prefix} → /api/v2/ (svc/src/main/resources/application.yml)", promoted.detail)
        # 못 푸는 키는 원문 보존 — 브리지의 접두 벗김 폴백이 이어받는다
        unresolved = Evidence("route", "GET /${gw.prefix}orders", "svc/src/main/java/App.java", 9, "confirmed")
        self.assertEqual(props.promote([unresolved])[0].name, "GET /${gw.prefix}orders")

    def test_api_call_url_resolution_promotes_like_literal_url(self):
        from asgard.map_graph.evidence import Evidence
        from asgard.map_graph.spring_props import SpringProps

        props = SpringProps()
        props.ingest("svc/src/main/resources/application.yml", "payment:\n  url: https://pay.example.com\n")
        feign = Evidence("api_call", "${payment.url}/charges", "svc/src/main/java/Pay.java", 4, "candidate", "feign")
        promoted = props.promote([feign])[0]
        # 설정이 URL 정체를 증명한다 — 추출기의 리터럴 URL 기준과 동일하게 confirmed
        self.assertEqual(promoted.name, "https://pay.example.com/charges")
        self.assertEqual(promoted.confidence, "confirmed")
        # 경로만 남는 해석(비 URL)은 베이스 URL 미증명 — confidence를 올리지 않는다
        props.ingest("svc/src/main/resources/application.properties", "svc.base=/internal\n")
        relative = Evidence("api_call", "${svc.base}/health", "svc/src/main/java/Pay.java", 5, "candidate")
        kept = props.promote([relative])[0]
        self.assertEqual((kept.name, kept.confidence), ("/internal/health", "candidate"))


class TestJpaTableConvergence(Base):
    def test_table_annotation_converges_with_ddl_node(self):
        from asgard.map_graph import scan_graph

        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write("db/schema.sql", "CREATE TABLE users (id INT PRIMARY KEY);\n")
        self.write(
            "src/main/java/com/acme/domain/User.java",
            """
package com.acme.domain;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;

@Entity
@Table(name = "users")
public class User {
}
""",
        )
        scan_graph(self.root)
        from asgard.map_graph import graph_state

        state = graph_state(self.root)
        assert state is not None
        node = next(n for n in state["nodes"] if n["id"] == "db_access:USERS")
        # DDL(confirmed)과 JPA @Table(candidate)이 같은 테이블 노드로 수렴한다
        self.assertEqual(node["confidence"], "confirmed")
        files = {loc["file"]: loc for loc in node["files"]}
        self.assertIn("db/schema.sql", files)
        self.assertIn("src/main/java/com/acme/domain/User.java", files)
        self.assertEqual(files["src/main/java/com/acme/domain/User.java"]["confidence"], "candidate")
        self.assertEqual(files["src/main/java/com/acme/domain/User.java"]["detail"], "jpa @Table")


if __name__ == "__main__":
    unittest.main(verbosity=1)
