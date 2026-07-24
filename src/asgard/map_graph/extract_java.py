"""JVM/DB 레인 증거 추출기 — Java 소스·MyBatis 매퍼 XML·SQL DDL (정규식 기반 보조 추출기).

정규식은 구문 증명이 아니다: 해당 프레임워크 임포트가 뒷받침하는 어노테이션, 매퍼 XML 의
선언, DDL 처럼 관용구가 강한 패턴만 confirmed 로 표시하고, 수신자 타입·런타임 값·SQL 본문
테이블 참조처럼 정적으로 못 묶는 것은 candidate 로 남긴다. 전체-문자열 `${...}` 이벤트
토픽은 graph 스캔이 base 설정(spring_props)으로 해석 승격한다 — 여기서는 원문을 보존한다.
"""

from __future__ import annotations

import re

from .evidence import Evidence, safe_url

# ── Java ──────────────────────────────────────────────────────────────────────
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")  # `://` 는 URL — 주석으로 오인하지 않는다
_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)", re.M)
_TYPE_DECL = re.compile(r"\b(?:class|interface|record|enum)\s+([A-Za-z_$][\w$]*)")
# 어노테이션 경로 값은 리터럴 연쇄(`"${api.prefix}" + "orbit/home"`)일 수 있다 — 전부 리터럴인
# 연쇄는 정적으로 증명되므로 조인한다. 상수 참조가 섞인 식은 여전히 불포착(추측 금지).
_LITERAL_CHAIN = r'"[^"]*"(?:\s*\+\s*"[^"]*")*'
_STRING_LITERAL = re.compile(r'"([^"]*)"')
_MAPPING = re.compile(
    rf"@(Get|Post|Put|Delete|Patch)Mapping\b\s*(?:\(\s*(?:value\s*=\s*|path\s*=\s*)?({_LITERAL_CHAIN}))?"
)
_REQUEST_MAPPING = re.compile(rf"@RequestMapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?({_LITERAL_CHAIN})([^)]*)\)")
_REQUEST_METHOD = re.compile(r"RequestMethod\s*\.\s*(\w+)")
_LISTENER = re.compile(r"@(KafkaListener|RabbitListener|JmsListener)\s*\(")
_LISTENER_TARGET = re.compile(r"\b(topics|topicPattern|queues|destination)\s*=\s*")
_SCHEDULED = re.compile(r"@Scheduled\b")
_CRON = re.compile(r'cron\s*=\s*"([^"]*)"')
_METHOD_NAME = re.compile(r"(?<!@)\b([a-z][\w$]*)\s*\(")
_ANNOTATED_TYPE = {
    "entity": re.compile(r"@Entity\b"),
    "mapper": re.compile(r"@Mapper\b"),
    "boot": re.compile(r"@SpringBootApplication\b"),
    "feign": re.compile(r"@FeignClient\s*\("),
}
# JPA 물리 테이블 매핑 — 어노테이션 리터럴이 DDL/매퍼 XML 테이블 노드와 이름으로 수렴한다.
_JPA_TABLE = re.compile(r'@Table\s*\(\s*[^)]*?\bname\s*=\s*"([^"]+)"')
_REPOSITORY = re.compile(
    r"interface\s+([A-Za-z_$][\w$]*)(?:<[^>]*>)?\s+extends\s+[\w.,<>\s$]*?"
    r"\b(JpaRepository|CrudRepository|PagingAndSortingRepository|ListCrudRepository"
    r"|ReactiveCrudRepository|MongoRepository|R2dbcRepository)\b"
)
_KAFKA_SEND = re.compile(r"\b\w*[kK]afkaTemplate\s*\.\s*send\s*\(\s*(\"([^\"]+)\")?")
_RABBIT_SEND = re.compile(r"\b\w*[rR]abbitTemplate\s*\.\s*convertAndSend\s*\(\s*(\"([^\"]+)\")?")
_REST_CALL = re.compile(
    r"\b\w*[rR]estTemplate\s*\.\s*"
    r"(getForObject|getForEntity|postForObject|postForEntity|exchange|put|delete|patchForObject)"
    r"\s*\(\s*(?:\"([^\"]+)\")?"
)
_WEBCLIENT_URI = re.compile(r"\.\s*uri\s*\(\s*\"([^\"]+)\"")
_JDBC_CALL = re.compile(
    r"\b\w*[jJ]dbcTemplate\s*\.\s*(query|queryForObject|queryForList|queryForMap|update|execute|batchUpdate)\s*\("
)
_FEIGN_ATTR = re.compile(r'\b(name|value|url)\s*=\s*"([^"]*)"')
# 임포트 접두 → 서비스 라벨 (프레임워크 자체(netty/mina/quartz 등)는 서비스가 아니라 제외)
_SERVICE_IMPORTS = (
    ("Altibase.jdbc", "altibase"),
    ("co.elastic.clients", "elasticsearch"),
    ("com.altibase", "altibase"),
    ("com.amazonaws", "aws"),
    ("com.azure", "azure"),
    ("com.clickhouse", "clickhouse"),
    ("com.google.cloud", "google-cloud"),
    ("com.rabbitmq", "rabbitmq"),
    ("com.slack.api", "slack"),
    ("com.stripe", "stripe"),
    ("com.twilio", "twilio"),
    ("io.lettuce", "redis"),
    ("io.minio", "minio"),
    ("jakarta.mail", "mail"),
    ("javax.mail", "mail"),
    ("oracle.jdbc", "oracle"),
    ("oracle.sql", "oracle"),
    ("org.apache.activemq", "activemq"),
    ("org.apache.kafka", "kafka"),
    ("org.elasticsearch", "elasticsearch"),
    ("org.postgresql", "postgresql"),
    ("org.springframework.amqp", "rabbitmq"),
    ("org.springframework.data.redis", "redis"),
    ("org.springframework.kafka", "kafka"),
    ("redis.clients", "redis"),
    ("ru.yandex.clickhouse", "clickhouse"),
    ("software.amazon.awssdk", "aws"),
)
_LISTENER_IMPORT = {
    "KafkaListener": "org.springframework.kafka",
    "RabbitListener": "org.springframework.amqp",
    "JmsListener": "org.springframework.jms",
}

# ── MyBatis XML / SQL ────────────────────────────────────────────────────────
# 주석은 증거가 아니다 — XML 주석의 산문("from a page")·주석 처리된 구문·SQL 주석의
# 죽은 DDL 이 테이블/구문 증거로 오인되는 것을 막는다. 줄 번호 보존을 위해 개행만 남긴다.
_XML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_SQL_LINE_COMMENT = re.compile(r"--[^\n]*")
_MAPPER_NS = re.compile(r"<(?:mapper|sqlMap)\s+namespace\s*=\s*[\"']([^\"']+)[\"']")
_STATEMENT = re.compile(r"<(select|insert|update|delete|statement|procedure)\s+[^>]*?\bid\s*=\s*[\"']([\w.-]+)[\"']")
_SQL_TABLE = re.compile(r"\b(?:from|join|update|into)\s+([A-Za-z_][\w$#.]*)", re.I)
_SQL_STOPWORDS = {
    "dual",
    "id",
    "select",
    "set",
    "the",
    "values",
    "when",
    "where",
}
_CREATE_TABLE = re.compile(
    r"\bCREATE\s+(?:GLOBAL\s+TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?([\w.$]+)", re.I
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _strip_comments(source: str) -> str:
    """주석 제거 — 줄 번호 보존을 위해 블록 주석은 동일 개수의 개행으로 치환한다."""
    without_blocks = _BLOCK_COMMENT.sub(lambda match: "\n" * match.group(0).count("\n"), source)
    return _LINE_COMMENT.sub("", without_blocks)


def _annotation_args(text: str, start: int) -> tuple[str, int]:
    """`start`(여는 괄호 위치)부터 균형 잡힌 인자 블록을 긁는다 — 실패 시 빈 문자열."""
    depth, index, in_string = 0, start, False
    limit = min(len(text), start + 2_000)
    while index < limit:
        char = text[index]
        if in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index
        index += 1
    return "", start


def _concat_literals(chain: str | None) -> str:
    """리터럴 연쇄(`"A" + "B"`) → 조인된 문자열. None/빈 연쇄는 빈 문자열."""
    return "".join(_STRING_LITERAL.findall(chain)) if chain else ""


def _join_route(prefix: str, path: str) -> str:
    combined = "/".join(part.strip("/") for part in (prefix, path) if part.strip("/"))
    return "/" + combined


def _listener_topics(args: str) -> list[tuple[str, bool]]:
    """topics/queues 인자 → (이름, 리터럴 여부). 상수 참조·패턴 구독은 원문을 보존하되 리터럴로 치지 않는다."""
    anchor = _LISTENER_TARGET.search(args)
    if anchor is None:
        return []
    if anchor.group(1) == "topicPattern":
        rest = args[anchor.end() :].lstrip()
        if rest.startswith('"'):
            closing = rest.find('"', 1)
            return [(rest[1:closing], False)] if closing > 0 else []
        return []
    rest = args[anchor.end() :].lstrip()
    if rest.startswith("{"):
        body = rest[1 : rest.index("}")] if "}" in rest else rest[1:]
        found = [(match.group(1), True) for match in re.finditer(r'"([^"]*)"', body)]
        return found or [(body.strip(), False)] if body.strip() else found
    if rest.startswith('"'):
        closing = rest.find('"', 1)
        return [(rest[1:closing], True)] if closing > 0 else []
    identifier = re.match(r"[\w.$]+", rest)
    return [(identifier.group(0), False)] if identifier else []


def _method_after(text: str, offset: int) -> str:
    matched = _METHOD_NAME.search(text, offset, offset + 400)
    return matched.group(1) if matched else ""


def _body_end_line(text: str, offset: int, *, limit: int = 120_000) -> int:
    """`offset`(어노테이션 뒤) 이후 메서드 본문 `{…}` 의 끝 줄 — 없으면 0.

    주석은 이미 제거된 텍스트를 전제한다. 어노테이션 인자 속 `{}` 는 괄호 깊이>0 이라
    건너뛰고, 깊이 0 에서 `{` 보다 `;` 를 먼저 만나면 본문 없는 선언(인터페이스 메서드)이다.
    """
    index, paren, in_string, in_char = offset, 0, False, False
    end = min(len(text), offset + limit)
    while index < end:
        char = text[index]
        if in_string or in_char:
            if char == "\\":
                index += 1
            elif char == ('"' if in_string else "'"):
                in_string = in_char = False
        elif char == '"':
            in_string = True
        elif char == "'":
            in_char = True
        elif char == "(":
            paren += 1
        elif char == ")":
            paren = max(0, paren - 1)  # 어노테이션 인자 중간에서 출발해도 견딘다
        elif paren == 0 and char == ";":
            return 0
        elif paren == 0 and char == "{":
            break
        index += 1
    else:
        return 0
    depth = 0
    while index < end:
        char = text[index]
        if in_string or in_char:
            if char == "\\":
                index += 1
            elif char == ('"' if in_string else "'"):
                in_string = in_char = False
        elif char == '"':
            in_string = True
        elif char == "'":
            in_char = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return _line_of(text, index)
        index += 1
    return 0


def extract_java(path: str, source: str) -> list[Evidence]:
    text = _strip_comments(source)
    evidence: list[Evidence] = []
    imports = set(_IMPORT.findall(text))

    def imported(prefix: str) -> bool:
        return any(name.startswith(prefix) for name in imports)

    seen_services: set[str] = set()
    for match in _IMPORT.finditer(text):
        for prefix, label in _SERVICE_IMPORTS:
            if match.group(1).startswith(prefix) and label not in seen_services:
                seen_services.add(label)
                evidence.append(
                    Evidence(
                        "external_service", label, path, _line_of(text, match.start()), "confirmed", match.group(1)
                    )
                )

    first_type = _TYPE_DECL.search(text)
    type_pos = first_type.start() if first_type else len(text)
    spring_web = imported("org.springframework.web.bind.annotation")

    class_prefix = ""
    for match in _REQUEST_MAPPING.finditer(text):
        verb_match = _REQUEST_METHOD.search(match.group(2) or "")
        if match.start() < type_pos and verb_match is None:
            class_prefix = _concat_literals(match.group(1))
            continue
        verb = verb_match.group(1).upper() if verb_match else "ANY"
        route = _join_route(class_prefix if match.start() > type_pos else "", _concat_literals(match.group(1)))
        confidence = "confirmed" if spring_web else "candidate"
        line = _line_of(text, match.start())
        span = _body_end_line(text, match.end())
        evidence.append(
            Evidence(
                "route", f"{verb} {route}", path, line, confidence, "spring", scope_end=max(span, line) if span else 0
            )
        )
    for match in _MAPPING.finditer(text):
        route = _join_route(class_prefix, _concat_literals(match.group(2)))
        confidence = "confirmed" if spring_web else "candidate"
        line = _line_of(text, match.start())
        span = _body_end_line(text, match.end())
        evidence.append(
            Evidence(
                "route",
                f"{match.group(1).upper()} {route}",
                path,
                line,
                confidence,
                "spring",
                scope_end=max(span, line) if span else 0,
            )
        )

    for match in _LISTENER.finditer(text):
        args, block_end = _annotation_args(text, match.end() - 1)
        line = _line_of(text, match.start())
        handler = _method_after(text, block_end or match.end())
        mechanism = imported(_LISTENER_IMPORT[match.group(1)])
        span = _body_end_line(text, (block_end or match.end()) + 1)
        for topic, is_literal in _listener_topics(args):
            # `${...}` 는 리터럴 문자열이어도 토픽 정체가 미해석 상태다 — 설정 해석 승격 전까지 candidate.
            confidence = "confirmed" if mechanism and is_literal and "${" not in topic else "candidate"
            detail = "subscribe" + (f" · {handler}" if handler else "")
            evidence.append(
                Evidence("event", topic, path, line, confidence, detail, scope_end=max(span, line) if span else 0)
            )

    for pattern, mechanism_prefix in (
        (_KAFKA_SEND, "org.springframework.kafka"),
        (_RABBIT_SEND, "org.springframework.amqp"),
    ):
        for match in pattern.finditer(text):
            line = _line_of(text, match.start())
            if match.group(2):
                confidence = "confirmed" if imported(mechanism_prefix) else "candidate"
                evidence.append(Evidence("event", match.group(2), path, line, confidence, "send"))
            else:
                receiver = "kafkaTemplate.send" if pattern is _KAFKA_SEND else "rabbitTemplate.convertAndSend"
                evidence.append(Evidence("event", receiver, path, line, "candidate", "send"))

    for match in _SCHEDULED.finditer(text):
        end = match.end()
        args = ""
        if text[end : end + 1] == "(":
            args, end = _annotation_args(text, end)
        handler = _method_after(text, end)
        cron = _CRON.search(args)
        confidence = "confirmed" if imported("org.springframework.scheduling") else "candidate"
        line = _line_of(text, match.start())
        span = _body_end_line(text, end + 1)
        evidence.append(
            Evidence(
                "job",
                handler or "scheduled",
                path,
                line,
                confidence,
                cron.group(1) if cron else "@Scheduled",
                scope_end=max(span, line) if span else 0,
            )
        )

    for kind_key, pattern in _ANNOTATED_TYPE.items():
        for match in pattern.finditer(text):
            declared = _TYPE_DECL.search(text, match.end())
            if kind_key == "feign":
                args, _end = _annotation_args(text, match.end() - 1)
                attrs = dict((k, v) for k, v in _FEIGN_ATTR.findall(args))
                target = attrs.get("url") or attrs.get("name") or attrs.get("value") or ""
                if target:
                    confidence = "confirmed" if target.startswith(("http://", "https://")) else "candidate"
                    evidence.append(
                        Evidence("api_call", safe_url(target), path, _line_of(text, match.start()), confidence, "feign")
                    )
                continue
            if declared is None:
                continue
            name, line = declared.group(1), _line_of(text, match.start())
            if kind_key == "entity" and (imported("jakarta.persistence") or imported("javax.persistence")):
                evidence.append(Evidence("model", name, path, line, "confirmed", "jpa"))
            elif kind_key == "entity":
                evidence.append(Evidence("model", name, path, line, "candidate", "jpa"))
            elif kind_key == "mapper":
                confidence = "confirmed" if imported("org.apache.ibatis") else "candidate"
                evidence.append(Evidence("db_access", name, path, line, confidence, "mybatis mapper"))
            elif kind_key == "boot":
                confidence = "confirmed" if imported("org.springframework.boot") else "candidate"
                evidence.append(Evidence("command", name, path, line, confidence, "spring-boot main"))

    if imported("jakarta.persistence") or imported("javax.persistence"):
        for match in _JPA_TABLE.finditer(text):
            # 물리 테이블명은 JPA 관례상 리터럴이지만 스키마 접두·네이밍 전략이 개입할 수 있다 — candidate.
            table = match.group(1).rsplit(".", 1)[-1].upper()
            evidence.append(
                Evidence("db_access", table, path, _line_of(text, match.start()), "candidate", "jpa @Table")
            )

    for match in _REPOSITORY.finditer(text):
        confidence = "confirmed" if imported("org.springframework.data") else "candidate"
        evidence.append(
            Evidence("db_access", match.group(1), path, _line_of(text, match.start()), confidence, match.group(2))
        )

    if imported("org.springframework.jdbc"):
        for match in _JDBC_CALL.finditer(text):
            evidence.append(
                Evidence(
                    "db_access", f"jdbcTemplate.{match.group(1)}", path, _line_of(text, match.start()), "candidate"
                )
            )

    for match in _REST_CALL.finditer(text):
        url = match.group(2) or ""
        confidence = "confirmed" if url.startswith(("http://", "https://")) else "candidate"
        name = safe_url(url) if url else f"restTemplate.{match.group(1)}"
        evidence.append(Evidence("api_call", name, path, _line_of(text, match.start()), confidence, "resttemplate"))
    if imported("org.springframework.web.reactive.function.client"):
        for match in _WEBCLIENT_URI.finditer(text):
            evidence.append(
                Evidence(
                    "api_call", safe_url(match.group(1)), path, _line_of(text, match.start()), "candidate", "webclient"
                )
            )
    return evidence


def extract_mapper_xml(path: str, source: str) -> list[Evidence]:
    """MyBatis(3)/iBATIS(2) 매퍼 XML — 네임스페이스·구문 id 는 선언(confirmed), 테이블 참조는 candidate."""
    source = _XML_COMMENT.sub(lambda match: "\n" * match.group(0).count("\n"), source)
    ns_match = _MAPPER_NS.search(source)
    if ns_match is None:
        return []
    namespace = ns_match.group(1)
    simple = namespace.rsplit(".", 1)[-1]
    evidence = [
        Evidence("db_access", simple, path, _line_of(source, ns_match.start()), "confirmed", f"mybatis-xml {namespace}")
    ]
    tables: list[Evidence] = []
    seen_tables: set[str] = set()
    for match in _SQL_TABLE.finditer(source):
        raw = match.group(1).rstrip(".")
        table = raw.rsplit(".", 1)[-1].upper()
        if not table or table.casefold() in _SQL_STOPWORDS or table in seen_tables:
            continue
        seen_tables.add(table)
        tables.append(Evidence("db_access", table, path, _line_of(source, match.start()), "candidate", "sql table ref"))
    evidence.extend(tables)
    for match in _STATEMENT.finditer(source):
        evidence.append(
            Evidence(
                "db_access",
                f"{simple}.{match.group(2)}",
                path,
                _line_of(source, match.start()),
                "confirmed",
                match.group(1),
            )
        )
    return evidence


_EXEC_SQL = re.compile(r"\bEXEC\s+SQL\b")


def extract_proc(path: str, source: str) -> list[Evidence]:
    """Pro*C 임베디드 SQL — `EXEC SQL … ;` 구간의 테이블 참조만 캔다 (C 본문은 스캔하지 않는다)."""
    evidence: list[Evidence] = []
    seen: set[str] = set()
    for match in _EXEC_SQL.finditer(source):
        terminator = source.find(";", match.end())
        segment = source[match.end() : terminator if 0 <= terminator - match.end() <= 2_000 else match.end() + 2_000]
        for table_match in _SQL_TABLE.finditer(segment):
            table = table_match.group(1).rstrip(".").rsplit(".", 1)[-1].upper()
            if not table or table.casefold() in _SQL_STOPWORDS or table in seen:
                continue
            seen.add(table)
            evidence.append(
                Evidence(
                    "db_access",
                    table,
                    path,
                    _line_of(source, match.end() + table_match.start()),
                    "candidate",
                    "exec sql",
                )
            )
    return evidence


def extract_sql(path: str, source: str) -> list[Evidence]:
    """SQL DDL — `CREATE TABLE` 은 스키마가 직접 증명하는 테이블 선언이다."""
    source = _BLOCK_COMMENT.sub(lambda match: "\n" * match.group(0).count("\n"), source)
    source = _SQL_LINE_COMMENT.sub("", source)
    evidence: list[Evidence] = []
    seen: set[str] = set()
    for match in _CREATE_TABLE.finditer(source):
        table = match.group(1).rstrip(".").rsplit(".", 1)[-1].upper()
        if not table or table in seen:
            continue
        seen.add(table)
        evidence.append(
            Evidence("db_access", table, path, _line_of(source, match.start()), "confirmed", "create table")
        )
    return evidence
