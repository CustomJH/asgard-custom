"""토르 게이트 규칙 카탈로그 (Python) — 트리 하나를 받아 판정 목록을 낸다. git 도 래칫도 모른다.

`craft_rules` 가 **형상**을 잰다면 이쪽은 **정확성**을 잰다. 역할 파일의 NEVER 표는 지금까지
문장으로만 있었고, 문장은 턴이 쌓이면 흐려진다(제약 붕괴, 2605.06445). 그래서 그 표에서
**정적으로 증명 가능한 항만** 여기로 옮겨 기계가 지게 한다. 증명 불가한 항(외부 입력인가,
멱등한가)은 옮기지 않는다 — 스킬이 판단으로 계속 진다.

판정의 갈래는 하나다: **막는 것은 반례가 없는 것뿐이다.** 값 자리에 들어간 보간은 파라미터
바인딩이 존재하므로 예외가 없고, 식별자 자리는 바인딩 자체가 불가능하므로 알림에 그친다.
같은 이유로 좁은 예외 타입의 침묵은 알림이고, `except Exception: pass` 는 막는다.

오탐은 이 파일에서 가장 비싼 결함이다 — 판정기가 오탐을 내면 다음에 일어나는 일은 판정기를
끄는 것이다(craft_rules 와 같은 계약). 애매하면 미검출로 남긴다.
"""

from __future__ import annotations

import ast
import re

from .craft_rules import Finding, Unit, _owner

# ── SQL ────────────────────────────────────────────────────────────
# 두 무리를 **함께** 요구한다 — "select" 한 단어만으로는 문서 문자열·UI 라벨까지 걸린다.
_SQL_VERB = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|MERGE)\b", re.I)
_SQL_CLAUSE = re.compile(r"\b(FROM|INTO|SET|WHERE|VALUES|JOIN)\b", re.I)
# 값 자리 = **비교 연산자 바로 뒤**. 여기 들어갈 수 있는 것은 값 하나뿐이라 바인딩으로 전부
# 대체되고, 그래서 반례가 없다.
#
# `VALUES (` 와 `IN (` 은 일부러 뺐다. 둘은 물음표 목록을 **프로그램으로 조립하는** 자리이기도
# 해서(`VALUES (" + placeholders + ")"`), 값 자리로 읽으면 올바르게 바인딩한 코드를 막는다 —
# 실측(JVM 1,373파일)에서 값 자리 판정 3건이 전부 이 형상이었다. 알림으로는 계속 뜬다.
_VALUE_SLOT = re.compile(r"(?:[=<>!]=|[=<>]|<>|\bLIKE\b|\bBETWEEN\b)\s*$", re.I)
_PRINTF = re.compile(r"%(?:\(\w+\))?[sdifr]")
_HOLE = "\x00"

# ── 시크릿 ──────────────────────────────────────────────────────────
_SECRET_NAME = re.compile(
    r"(?:^|_)(?:password|passwd|pwd|secret|token|apikey|api_key|access_key|private_key|client_secret)(?:_|$)"
)
# camelCase 를 snake 로 편 뒤에 잰다 — `clientSecret`·`authToken` 을 못 보면 JVM/TS 에서 규칙이
# 사실상 발화하지 않는다(그쪽 관용구가 camelCase 다).
_CAMEL = (re.compile(r"(?<=[a-z0-9])(?=[A-Z])"), re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])"))
# 자리표시자는 시크릿이 아니다 — 값이 비밀이 아니라는 것이 문자열 자체로 드러나는 것들.
_PLACEHOLDER = re.compile(r"(?i)^(?:x+|\.+|-+|changeme|placeholder|dummy|example|test|none|null|todo|<.*>|\{.*\})$")

# ── 외부 호출 ───────────────────────────────────────────────────────
_HTTP_MODULE = frozenset({"requests", "httpx", "aiohttp"})
_HTTP_VERB = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "request", "send", "stream"})

# ── 트랜잭션 ────────────────────────────────────────────────────────
_TX_CALL = frozenset({"atomic", "begin", "begin_nested", "transaction", "start_transaction"})
_TX_DECOR = frozenset({"atomic", "transactional", "transaction"})
_PUBLISH = frozenset({"publish", "send_message", "sendmail", "send_mail", "enqueue", "produce", "notify"})

# ── 금액 ────────────────────────────────────────────────────────────
# 좁게 유지한다. `total`·`cost`·`rate` 는 개수·알고리즘 비용·비율에 훨씬 많이 쓰인다 — 넣는 순간
# 오탐이 진양성을 넘는다. 화폐로만 읽히는 낱말만 넣는다.
_MONEY = re.compile(
    r"(?i)(?:^|_)(?:amount|price|balance|salary|payroll|invoice|subtotal|refund|krw|usd|금액|가격|잔액)(?:_|$)"
)


def _at(spans: list[Unit], line: int) -> str:
    return _owner(spans, line)


def secret_name(name: str) -> bool:
    """이름이 시크릿을 담는 자리인가. 중괄호 계열 판정기도 같은 자를 쓴다 (단일 출처)."""
    for pattern in _CAMEL:
        name = pattern.sub("_", name)
    return bool(_SECRET_NAME.search(name.lower()))


# ── ① SQL 문자열 보간 ───────────────────────────────────────────────


def _template(node: ast.AST) -> tuple[str, list[str]] | None:
    """보간식을 (구멍 뚫린 템플릿, 구멍 앞 문맥들) 로 편다. SQL 이 아닌 것은 None."""
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append(_HOLE if not isinstance(value.value, ast.Constant) else "")
        return _split(("".join(parts)))
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        left, right = node.left, node.right
        if not (isinstance(left, ast.Constant) and isinstance(left.value, str)):
            return None
        if isinstance(right, ast.Constant):
            return None  # 리터럴끼리의 결합은 보간이 아니다
        if isinstance(node.op, ast.Add):
            return _split(left.value + _HOLE)
        # `%` 는 자리표시자가 있는 곳에서 값을 갈아끼운다 — 구멍은 끝이 아니라 그 자리에 있다.
        # (같은 `%s` 라도 `cursor.execute(q, params)` 는 보간이 아니라 바인딩이고, 그쪽은
        #  BinOp 이 아니라서 애초에 여기 오지 않는다.)
        return _split(_PRINTF.sub(_HOLE, left.value))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        target = node.func.value
        if not (isinstance(target, ast.Constant) and isinstance(target.value, str)):
            return None
        if all(isinstance(a, ast.Constant) for a in node.args) and not node.keywords:
            return None
        return _split(re.sub(r"\{[^{}]*\}", _HOLE, target.value))
    return None


def _split(template: str) -> tuple[str, list[str]] | None:
    if _HOLE not in template:
        return None
    flat = template.replace(_HOLE, " ")
    if not (_SQL_VERB.search(flat) and _SQL_CLAUSE.search(flat)):
        return None
    return (template, [chunk for chunk in template.split(_HOLE)[:-1]])


def _sql_findings(tree: ast.AST, rel: str, spans: list[Unit]) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        parsed = _template(node)
        if parsed is None:
            continue
        _, before = parsed
        value_slot = any(_VALUE_SLOT.search(chunk.rstrip()) for chunk in before)
        line = getattr(node, "lineno", 1)
        out.append(
            Finding(
                "sql-interpolated",
                rel,
                line,
                _at(spans, line),
                "값 자리에 문자열 보간" if value_slot else "SQL 문자열을 보간으로 조립 (식별자 자리)",
                "파라미터 바인딩으로 옮겨라 — 값 자리는 바인딩으로 전부 대체된다"
                if value_slot
                else "식별자는 바인딩이 안 된다 — 허용 목록으로 좁히고 그 근거를 남겨라",
                blocking=value_slot,
            )
        )
    return out


# ── ② 삼킨 예외 ────────────────────────────────────────────────────


def _silent(body: list[ast.stmt]) -> bool:
    """본문이 침묵뿐인가 — pass / ... / continue 만."""
    for stmt in body:
        if isinstance(stmt, (ast.Pass, ast.Continue)):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
            continue
        return False
    return bool(body)


def _broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    return isinstance(handler.type, ast.Name) and handler.type.id in ("Exception", "BaseException")


def _justified(body: list[ast.stmt], lines: list[str]) -> bool:
    """침묵의 근거가 코드에 남아 있는가 — 정당한 폴백과 삼킨 예외를 가르는 자(탄그리스니르 캐논).

    본문이 pass/.../continue 뿐이므로 그 줄의 `#` 는 문자열일 수 없다 — 주석으로 읽어도 안전하다.
    """
    for stmt in body:
        start, end = stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno) or stmt.lineno
        if any("#" in lines[i - 1] for i in range(start, end + 1) if 0 < i <= len(lines)):
            return True
    return False


def _except_findings(tree: ast.AST, rel: str, spans: list[Unit], lines: list[str]) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not _silent(node.body):
            continue
        broad = _broad(node)
        justified = _justified(node.body, lines)
        detail = "모든 예외를 삼킨다" if broad else "예외를 삼킨다 (좁은 타입)"
        out.append(
            Finding(
                "swallowed-exception",
                rel,
                node.lineno,
                _at(spans, node.lineno),
                detail + (" (근거 주석 있음)" if justified else ""),
                "처리할 수 없으면 문맥을 붙여 전파해라 — 삼킬 근거가 있으면 그 근거를 코드에 남겨라",
                blocking=broad and not justified,
            )
        )
    return out


# ── ③ 타임아웃 없는 외부 호출 ────────────────────────────────────────


def _http_call(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in _HTTP_VERB:
        base = func.value
        if isinstance(base, ast.Name) and base.id in _HTTP_MODULE:
            return f"{base.id}.{func.attr}"
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return name if name in ("urlopen", "create_connection") else None


def _timeout_findings(tree: ast.AST, rel: str, spans: list[Unit]) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        label = _http_call(node)
        if label is None:
            continue
        # `**kwargs` 가 있으면 타임아웃의 부재를 증명할 수 없다 — 미검출로 남긴다.
        if any(kw.arg is None for kw in node.keywords) or any(kw.arg == "timeout" for kw in node.keywords):
            continue
        out.append(
            Finding(
                "call-no-timeout",
                rel,
                node.lineno,
                _at(spans, node.lineno),
                f"{label}() 에 타임아웃이 없다 — 기본값은 무한 대기다",
                "timeout= 을 명시해라. 바깥 계층보다 짧아야 한다 (계층 타임아웃)",
            )
        )
    return out


# ── ④ 하드코딩된 시크릿 ─────────────────────────────────────────────


def _secretish(text: str) -> bool:
    """값 자체가 비밀처럼 생겼는가. 짧은 것·자리표시자·문장은 시크릿이 아니다."""
    if len(text) < 16 or " " in text or _PLACEHOLDER.match(text):
        return False
    if text.startswith(("http://", "https://", "/", "./", "{")):
        return False
    return bool(re.search(r"\d", text) and re.search(r"[A-Za-z]", text))


def _secret_findings(tree: ast.AST, rel: str, spans: list[Unit]) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
            if not secret_name(name) or not _secretish(value.value):
                continue
            out.append(
                Finding(
                    "secret-literal",
                    rel,
                    node.lineno,
                    _at(spans, node.lineno),
                    f"{name} 에 비밀처럼 생긴 문자열이 박혀 있다",
                    "환경변수·시크릿 저장소로 옮기고, 이미 커밋됐으면 그 값을 폐기해라",
                )
            )
    return out


# ── ⑤ 트랜잭션 안의 외부 I/O ────────────────────────────────────────


def _is_tx(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        node = node.func
    name = node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")
    return name in _TX_CALL


def _external_io(scope: ast.AST) -> tuple[int, str] | None:
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        label = _http_call(node)
        if label:
            return (node.lineno, label)
        func = node.func
        attr = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if attr in _PUBLISH:
            return (node.lineno, attr)
    return None


def _tx_findings(tree: ast.AST, rel: str, spans: list[Unit]) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        scopes: list[ast.AST] = []
        if isinstance(node, (ast.With, ast.AsyncWith)) and any(_is_tx(item.context_expr) for item in node.items):
            scopes = list(node.body)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            _is_tx(d) or getattr(d, "attr", getattr(d, "id", "")) in _TX_DECOR for d in node.decorator_list
        ):
            scopes = list(node.body)
        for stmt in scopes:
            hit = _external_io(stmt)
            if hit is None:
                continue
            line, label = hit
            out.append(
                Finding(
                    "tx-external-io",
                    rel,
                    line,
                    _at(spans, line),
                    f"트랜잭션 안에서 {label}() — 커밋 전 부수효과는 롤백이 되돌리지 못한다",
                    "트랜잭션 밖으로 빼거나 outbox 로 옮겨라",
                )
            )
            break
    return out


# ── ⑥ 부동소수 금액 · ⑦ 시간대 없는 현재시각 ─────────────────────────


def _money_findings(tree: ast.AST, rel: str, spans: list[Unit]) -> list[Finding]:
    out: list[Finding] = []

    def note(line: int, name: str) -> None:
        out.append(
            Finding(
                "money-float",
                rel,
                line,
                _at(spans, line),
                f"{name} 을 부동소수로 다룬다 — 0.1 + 0.2 는 0.3 이 아니다",
                "정수 최소단위(원·센트)나 Decimal 로 바꿔라",
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Name):
            name = getattr(node.target, "id", getattr(node.target, "attr", ""))
            if node.annotation.id == "float" and _MONEY.search(name):
                note(node.lineno, name)
        elif isinstance(node, ast.arg) and isinstance(node.annotation, ast.Name):
            if node.annotation.id == "float" and _MONEY.search(node.arg):
                note(node.lineno, node.arg)
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "float" and len(node.args) == 1:
            inner = node.args[0]
            name = getattr(inner, "id", getattr(inner, "attr", ""))
            if name and _MONEY.search(name):
                note(node.lineno, name)
    return out


def _now_findings(tree: ast.AST, rel: str, spans: list[Unit]) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        if attr == "utcnow" or (attr == "now" and not node.args and not node.keywords):
            base = node.func.value
            if getattr(base, "id", getattr(base, "attr", "")) not in ("datetime", "date"):
                continue
            out.append(
                Finding(
                    "naive-now",
                    rel,
                    node.lineno,
                    _at(spans, node.lineno),
                    f"{attr}() 가 시간대 없는 값을 낸다",
                    "저장은 UTC(aware)로, 변환은 표시 경계에서 — 막지는 않는다",
                    blocking=False,
                )
            )
    return out


def findings(text: str, rel: str, spans: list[Unit]) -> list[Finding] | None:
    """파싱 실패는 None (0 이 아니다 — 못 잰 것과 없는 것은 다르다)."""
    try:
        tree = ast.parse(text)
    except SyntaxError, ValueError, RecursionError:
        return None
    lines = text.split("\n")
    out = _except_findings(tree, rel, spans, lines)
    for rule in (_sql_findings, _timeout_findings, _secret_findings, _tx_findings, _money_findings, _now_findings):
        out.extend(rule(tree, rel, spans))
    return sorted(out, key=lambda f: (f.line, f.rule))
