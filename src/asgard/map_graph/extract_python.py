"""Python 증거 추출기 — ast 기반 정본 추출기.

지어내지 않는다: 데코레이터·베이스 클래스·임포트처럼 구문이 직접 증명하는 것만 confirmed,
수신자 타입을 못 묶는 호출 패턴은 candidate 로 남긴다.
"""

from __future__ import annotations

import ast

from .evidence import Evidence, safe_url

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
            # 본문 스팬 — 데코레이터 줄부터 함수 끝 줄까지. AST 가 직접 증명하는 포함 관계다.
            span_end = max(node.end_lineno or node.lineno, node.lineno)
            for decorator in node.decorator_list:
                attr, call = _decorator_call(decorator)
                if attr in _ROUTE_ATTRS and call is not None:
                    route_path = _first_str(call)
                    if route_path.startswith("/"):
                        method = "ANY" if attr in {"route", "api_route"} else attr.upper()
                        receiver = _dotted_root(call.func.value) if isinstance(call.func, ast.Attribute) else ""
                        confidence = "confirmed" if receivers.get(receiver) == "route" else "candidate"
                        evidence.append(
                            Evidence(
                                "route",
                                f"{method} {route_path}",
                                path,
                                decorator.lineno,
                                confidence,
                                node.name,
                                scope_end=span_end,
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
                    evidence.append(
                        Evidence(
                            "command",
                            name or node.name,
                            path,
                            decorator.lineno,
                            confidence,
                            node.name,
                            scope_end=span_end,
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
