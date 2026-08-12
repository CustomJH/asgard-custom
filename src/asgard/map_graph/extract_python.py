"""Python 증거 추출기 — ast 기반 정본 추출기.

지어내지 않는다: 데코레이터·베이스 클래스·임포트처럼 구문이 직접 증명하는 것만 confirmed,
수신자 타입을 못 묶는 호출 패턴은 candidate로 남긴다.
"""

from __future__ import annotations

import ast
from dataclasses import replace

from .evidence import Evidence, safe_summary, safe_url

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "websocket"}
_ROUTE_ATTRS = _HTTP_METHODS | {"route", "api_route"}
_JOB_ATTRS = {"task", "shared_task", "scheduled_job", "on_event", "cron"}
_HTTP_CLIENT_ROOTS = {"requests", "httpx", "aiohttp", "urllib3"}
_DB_CALL_ATTRS = {"execute", "executemany", "executescript"}
_DB_MODULES = {"sqlite3", "sqlalchemy", "psycopg2", "psycopg", "asyncpg", "pymysql", "aiosqlite", "duckdb", "pymongo"}
_MODEL_BASES = {"BaseModel", "DeclarativeBase", "Base", "Model", "TypedDict", "SQLModel", "Document", "Table"}
_EVENT_ATTRS = {"publish", "emit", "dispatch", "send_event", "produce"}
_BROKER_MODULES = {"redis", "kafka", "aiokafka", "pika", "nats", "celery", "confluent_kafka"}
# 외부 서비스 SDK — top-level 모듈명 → 서비스 라벨
_SERVICE_MODULES = {
    "anthropic": "anthropic",
    "boto3": "aws",
    "botocore": "aws",
    "confluent_kafka": "kafka",
    "elasticsearch": "elasticsearch",
    "firebase_admin": "firebase",
    "google": "google-cloud",
    "kafka": "kafka",
    "openai": "openai",
    "pika": "rabbitmq",
    "pinecone": "pinecone",
    "redis": "redis",
    "sendgrid": "sendgrid",
    "slack_sdk": "slack",
    "stripe": "stripe",
    "supabase": "supabase",
    "twilio": "twilio",
}
_WEB_FACTORIES = {
    "fastapi.APIRouter",
    "fastapi.FastAPI",
    "flask.Blueprint",
    "flask.Flask",
    "litestar.Litestar",
    "sanic.Sanic",
    "starlette.applications.Starlette",
}
_COMMAND_FACTORIES = {"click.Group", "typer.Typer"}
_JOB_FACTORIES = {"celery.Celery"}
_MODEL_PREFIXES = ("django.db.models.", "pydantic.", "sqlalchemy.", "sqlmodel.", "typing.TypedDict")


def _dotted_root(node: ast.expr) -> str:
    """호출 수신자 체인의 뿌리 이름 — `httpx.AsyncClient().get` → `httpx`."""
    current = node
    while True:
        if isinstance(current, ast.Attribute):
            current = current.value
        elif isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Name):
            return current.id
        else:
            return ""


def _first_str(call: ast.Call) -> str:
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return ""


def _decorator_call(decorator: ast.expr) -> tuple[str, ast.Call | None]:
    """데코레이터 → (마지막 attr/name, Call 노드) — `@app.get("/x")` → ("get", call)."""
    if isinstance(decorator, ast.Call):
        func = decorator.func
        if isinstance(func, ast.Attribute):
            return func.attr, decorator
        if isinstance(func, ast.Name):
            return func.id, decorator
        return "", decorator
    if isinstance(decorator, ast.Attribute):
        return decorator.attr, None
    if isinstance(decorator, ast.Name):
        return decorator.id, None
    return "", None


def _kwarg_str(call: ast.Call | None, keyword: str) -> str:
    if call is None:
        return ""
    for entry in call.keywords:
        if entry.arg == keyword and isinstance(entry.value, ast.Constant) and isinstance(entry.value.value, str):
            return entry.value.value
    return ""


def _kwarg_lookup_key(call: ast.Call | None, keyword: str) -> str:
    """상수 표를 한 번 거치는 역할 선언의 열쇠 — `help=t("hc_tk_board")` 의 `hc_tk_board`.

    번역 표를 쓰는 코드베이스에서 역할 문장은 선언 자리에 없고 표에 있다. 인자 하나짜리 호출에
    문자열 리터럴 하나만 들어간 꼴로 좁힌다: `t(key)` · `_(key)` · `gettext(key)` 가 다 이 모양이고,
    계산해서 만든 인자는 소스만 읽어서 값을 알 수 없으므로 받지 않는다.
    """
    if call is None:
        return ""
    for entry in call.keywords:
        value = entry.value
        if entry.arg != keyword or not isinstance(value, ast.Call) or value.keywords or len(value.args) != 1:
            continue
        first = value.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.strip():
            return first.value
    return ""


def _declared_summary(
    call: ast.Call | None, node: ast.FunctionDef | ast.AsyncFunctionDef, *keywords: str
) -> tuple[str, str]:
    """선언이 스스로 밝힌 한 줄 역할 — (역할 문장, 상수 표 열쇠).

    찾는 순서는 명시 인자 → 독스트링 첫 줄이고, 문장을 바로 못 얻었을 때만 열쇠를 남긴다.
    셋 다 없으면 둘 다 빈 값이다. 함수 이름을 문장처럼 풀어 역할을 지어내지 않는다 — 이 값은
    "이 명령이 무엇을 하나"의 근거로 주입면까지 가므로, 근거가 없으면 없는 채로 둔다.
    """
    for keyword in keywords:
        declared = _kwarg_str(call, keyword)
        if declared:
            return safe_summary(declared), ""
    doc = (ast.get_docstring(node) or "").strip()
    if doc:
        return safe_summary(doc.splitlines()[0]), ""
    for keyword in keywords:
        key = _kwarg_lookup_key(call, keyword)
        if key:
            return "", key
    return "", ""


def _typer_groups(tree: ast.Module) -> tuple[dict[str, str], dict[str, str]]:
    """`app.add_typer(ticket_app, name="ticket")` 결속 — 명령을 실제로 칠 수 있게 하는 것.

    이름만으로는 숏컷이 못 된다: 이 저장소만 해도 `list`가 여덟 그룹에 있어 한 노드로 접혔다.
    부모 그룹을 거슬러 이어 `ticket board`처럼 호출 경로를 이름으로 삼으면 접힘과 모호함이 함께 풀린다.
    """
    parent: dict[str, str] = {}
    label: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_typer":
            continue
        owner = _dotted_root(node.func)
        child = node.args[0].id if node.args and isinstance(node.args[0], ast.Name) else ""
        if not owner or not child:
            continue
        parent[child] = owner
        name = _kwarg_str(node, "name")
        if name:
            label[child] = name
    return parent, label


def _command_path(receiver: str, parent: dict[str, str], label: dict[str, str], name: str) -> str:
    """수신자에서 뿌리까지 거슬러 그룹 이름을 잇는다. 뿌리 app은 이름이 없어 아무것도 안 보탠다."""
    chain: list[str] = []
    seen: set[str] = set()
    current = receiver
    # 사이클은 소스가 이상한 경우다 — 도는 대신 거기서 멈춘다.
    while current and current not in seen:
        seen.add(current)
        if current in label:
            chain.append(label[current])
        current = parent.get(current, "")
    return " ".join([*reversed(chain), name])


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    if isinstance(base, ast.Subscript):  # Generic[...] 형태
        return _base_name(base.value)
    return ""


def _origin(node: ast.expr, modules: dict[str, str], symbols: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return symbols.get(node.id, modules.get(node.id, ""))
    if isinstance(node, ast.Attribute):
        root = _dotted_root(node)
        module = modules.get(root, "")
        return f"{module}.{node.attr}" if module else symbols.get(root, "")
    return ""


def extract_python(path: str, source: str) -> list[Evidence]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError, ValueError:
        return []
    evidence: list[Evidence] = []
    imported_tops: set[str] = set()
    modules: dict[str, str] = {}
    symbols: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                imported_tops.add(top)
                modules[alias.asname or top] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported_tops.add(node.module.split(".")[0])
            for alias in node.names:
                symbols[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    group_parent, group_label = _typer_groups(tree)
    receivers: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
            continue
        factory = _origin(node.value.func, modules, symbols)
        kind = (
            "route"
            if factory in _WEB_FACTORIES
            else "command"
            if factory in _COMMAND_FACTORIES
            else "job"
            if factory in _JOB_FACTORIES
            else ""
        )
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if kind:
            receivers.update({target.id: kind for target in targets if isinstance(target, ast.Name)})

    for top in sorted(imported_tops & set(_SERVICE_MODULES)):
        evidence.append(
            Evidence("external_service", _SERVICE_MODULES[top], path, 1, "confirmed", detail=f"import {top}")
        )

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # 본문 스팬 — 데코레이터 줄부터 함수 끝 줄까지. AST가 직접 증명하는 포함 관계다.
            span_end = max(node.end_lineno or node.lineno, node.lineno)
            for decorator in node.decorator_list:
                attr, call = _decorator_call(decorator)
                if attr in _ROUTE_ATTRS and call is not None:
                    route_path = _first_str(call)
                    if route_path.startswith("/"):
                        method = "ANY" if attr in {"route", "api_route"} else attr.upper()
                        receiver = _dotted_root(call.func.value) if isinstance(call.func, ast.Attribute) else ""
                        confidence = "confirmed" if receivers.get(receiver) == "route" else "candidate"
                        summary, summary_key = _declared_summary(call, node, "summary", "description")
                        evidence.append(
                            Evidence(
                                "route",
                                f"{method} {route_path}",
                                path,
                                decorator.lineno,
                                confidence,
                                node.name,
                                scope_end=span_end,
                                summary=summary,
                                summary_key=summary_key,
                            )
                        )
                elif attr == "command":
                    name = _first_str(call) if call is not None else ""
                    receiver = (
                        _dotted_root(call.func.value)
                        if call is not None and isinstance(call.func, ast.Attribute)
                        else ""
                    )
                    confidence = "confirmed" if receivers.get(receiver) == "command" else "candidate"
                    summary, summary_key = _declared_summary(call, node, "help")
                    evidence.append(
                        Evidence(
                            "command",
                            _command_path(receiver, group_parent, group_label, name or node.name),
                            path,
                            decorator.lineno,
                            confidence,
                            node.name,
                            scope_end=span_end,
                            summary=summary,
                            summary_key=summary_key,
                        )
                    )
                elif attr in _JOB_ATTRS:
                    subject = decorator.func if isinstance(decorator, ast.Call) else decorator
                    origin = _origin(subject, modules, symbols)
                    receiver = _dotted_root(subject.value) if isinstance(subject, ast.Attribute) else ""
                    confidence = (
                        "confirmed" if origin.startswith("celery.") or receivers.get(receiver) == "job" else "candidate"
                    )
                    evidence.append(
                        Evidence("job", node.name, path, decorator.lineno, confidence, attr, scope_end=span_end)
                    )
        elif isinstance(node, ast.ClassDef):
            matched = sorted(_base_name(base) for base in node.bases if _base_name(base) in _MODEL_BASES)
            if matched:
                confirmed = any(_origin(base, modules, symbols).startswith(_MODEL_PREFIXES) for base in node.bases)
                evidence.append(
                    Evidence(
                        "model", node.name, path, node.lineno, "confirmed" if confirmed else "candidate", matched[0]
                    )
                )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            root = _dotted_root(node.func)
            if attr in (_HTTP_METHODS - {"websocket"}) | {"request"} and root in _HTTP_CLIENT_ROOTS:
                url = _first_str(node)
                confidence = "confirmed" if url.startswith(("http://", "https://")) else "candidate"
                evidence.append(
                    Evidence(
                        "api_call", safe_url(url) if url else f"{root}.{attr}", path, node.lineno, confidence, root
                    )
                )
            elif attr in _DB_CALL_ATTRS and imported_tops & _DB_MODULES:
                # 수신자 타입을 정적으로 못 묶는다 — 커서/세션일 개연성만 있으므로 candidate.
                evidence.append(Evidence("db_access", f"{root or 'cursor'}.{attr}", path, node.lineno, "candidate"))
            elif attr in _EVENT_ATTRS and imported_tops & _BROKER_MODULES:
                topic = _first_str(node)
                evidence.append(Evidence("event", topic or f"{root}.{attr}", path, node.lineno, "candidate", attr))
    return evidence


def extract_string_table(source: str) -> dict[str, str]:
    """모듈 수준 딕셔너리 리터럴이 담은 열쇠 → 문장 — 번역 표를 읽는 자리.

    값이 묶음(`("영문", "한글")`)이면 첫 항목을 쓴다. 언어를 고르는 것이 아니라, 표를 쓰는
    코드베이스가 첫 자리에 기준 표기를 두는 관례를 따르는 것이다. 계산이 들어간 값은 소스만
    읽어서 결과를 알 수 없으므로 건너뛴다.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError, ValueError:
        return {}
    table: dict[str, str] = {}
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Dict):
            continue
        for key, entry in zip(value.keys, value.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.strip()):
                continue
            first = entry.elts[0] if isinstance(entry, (ast.Tuple, ast.List)) and entry.elts else entry
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.strip():
                # 열쇠가 두 표에서 갈리면 어느 쪽이 맞는지 소스가 안 말해 준다 — 먼저 본 것을 지킨다.
                table.setdefault(key.value, first.value)
    return table


def resolve_summaries(collected: list[Evidence], table: dict[str, str]) -> list[Evidence]:
    """상수 표에 위임된 역할 문장을 채운다 — 저장소를 다 훑은 뒤에만 할 수 있는 일.

    표에 없는 열쇠는 채우지 않는다. 열쇠 자체를 역할 문장으로 적으면 `hc_tk_board` 같은 내부
    이름이 주입면에 실리고, 그건 근거 없는 한 줄을 지어내는 것과 같다.
    """
    if not table:
        return collected
    return [
        replace(item, summary=safe_summary(table[item.summary_key]), summary_key="")
        if item.summary_key and not item.summary and table.get(item.summary_key, "").strip()
        else item
        for item in collected
    ]
