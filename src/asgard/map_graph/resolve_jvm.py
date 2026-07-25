"""JVM 크로스파일 심볼 해석 — 라우트가 실제로 어떤 SQL 구문에 닿는지 잇는다.

같은 파일 스팬 규칙만으로는 계층형 Spring 앱에서 라우트와 DB 가 영원히 단절된다:
컨트롤러 파일에는 SQL 이 없고, SQL 은 여러 계층 건너 매퍼 XML 에 있다. 이 모듈은
**소스 리터럴만으로 증명되는** 다리를 놓는다. 네 조각이 전부 소스에 적혀 있다:

    import  com.nuriflex.helios.mapper.user.UserConfigMapper;   ← 타입의 정체(FQN)
    private final UserConfigMapper userConfigMapper;            ← 필드 이름 → 타입
    userConfigMapper.selectUserConfig(...)                      ← 호출 지점
    <mapper namespace="…user.UserConfigMapper"><select id="selectUserConfig">

지어내지 않는다. 하나라도 못 풀면 잇지 않는다 — 수신자가 로컬 변수·정적 호출·메서드
인자이거나, 인터페이스 구현체가 여럿이거나, 타입 이름이 리포에서 유일하지 않으면 포기한다.
계층 자체는 노드로 세우지 않는다(개념 그래프의 어휘를 늘리지 않는다). 대신 라우트에서
도달한 SQL 구문으로 바로 엣지를 내고, 구문→테이블은 매퍼 XML 이 이미 소유한다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
_IMPORT_FQN = re.compile(r"^\s*import\s+(?:static\s+)?([\w.$]+)\s*;", re.M)
_TYPE_HEAD = re.compile(r"\b(?:class|interface|enum|record)\s+(\w+)([^{;]*)\{")
_SUPER_NAME = re.compile(r"\b([A-Z]\w*)")
# 필드 주입 — Lombok `@RequiredArgsConstructor` + final 필드가 Spring 의 지배 관용구다.
_FIELD = re.compile(
    r"\b(?:private|protected|public)\s+(?:static\s+)?(?:final\s+)?([A-Z]\w*)(?:\s*<[^;=()]*>)?\s+(\w+)\s*[;=]"
)
# 메서드/생성자 본문 — 파라미터에 어노테이션이 들어가면 괄호가 중첩되므로(`@Scope(x = 1) T p`)
# 정규식으로 인자 목록을 통째로 삼키지 않고, 여는 괄호부터 균형을 맞춰 닫는 위치를 찾는다.
_METHOD_HEAD = re.compile(r"(?<![\w.$@])(\w+)\s*\(")
_AFTER_PARAMS = re.compile(r"\s*(?:throws\s+[\w.,\s]+?)?\{")
_CALL = re.compile(r"(?<![\w.$])(\w+)\s*\.\s*(\w+)\s*\(")
_NOT_A_METHOD = frozenset(
    {"if", "for", "while", "switch", "catch", "synchronized", "try", "do", "else", "new", "return", "case"}
)
# 한 라우트에서 따라갈 최대 홉 — 계층이 이보다 깊으면 수렴 실패로 보고 멈춘다.
_MAX_DEPTH = 8
# 한 라우트가 이만큼 넘는 구문에 닿으면 해석이 아니라 잡음이다 — 통째로 버린다.
_MAX_STATEMENTS = 40


@dataclass
class _Unit:
    """메서드 단위 — 크로스파일 호출 그래프의 노드."""

    owner: str  # 클래스 simple name
    name: str
    start_line: int
    end_line: int
    calls: list[tuple[str, str]] = field(default_factory=list)  # (수신자, 호출 메서드)


@dataclass
class JavaModule:
    """한 Java 파일에서 뽑은 해석 재료 — 소스는 들고 있지 않는다."""

    path: str
    package: str
    imports: dict[str, str] = field(default_factory=dict)  # simple → FQN
    supers: dict[str, list[str]] = field(default_factory=dict)  # class simple → 부모 simple 목록
    fields: dict[str, dict[str, str]] = field(default_factory=dict)  # class simple → {필드: 타입 simple}
    units: list[_Unit] = field(default_factory=list)


def _span_end(text: str, start: int, opener: str = "{", closer: str = "}", *, limit: int = 200_000) -> int:
    """`start`(여는 문자)의 짝이 닫히는 오프셋 — 실패 시 -1. 문자열 리터럴은 건너뛴다."""
    if start < 0:
        return -1
    index, depth, quote = start, 0, ""
    end = min(len(text), start + limit)
    while index < end:
        char = text[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def index_java(path: str, text: str) -> JavaModule:
    """주석이 제거된 Java 소스 → 해석 재료. 줄 번호는 원본과 일치해야 한다."""
    package_match = _PACKAGE.search(text)
    module = JavaModule(path=path, package=package_match.group(1) if package_match else "")
    for match in _IMPORT_FQN.finditer(text):
        fqn = match.group(1)
        module.imports[fqn.rsplit(".", 1)[-1]] = fqn
    types: list[tuple[str, int, int]] = []  # (simple, 본문 시작, 본문 끝)
    for match in _TYPE_HEAD.finditer(text):
        simple = match.group(1)
        body_start = match.end() - 1
        body_end = _span_end(text, body_start)
        if body_end < 0:
            continue
        types.append((simple, body_start, body_end))
        module.supers[simple] = _SUPER_NAME.findall(match.group(2))
        module.fields[simple] = {name: type_name for type_name, name in _FIELD.findall(text[body_start : body_end + 1])}
    for match in _METHOD_HEAD.finditer(text):
        name = match.group(1)
        if name in _NOT_A_METHOD:
            continue
        params_end = _span_end(text, match.end() - 1, "(", ")")
        if params_end < 0:
            continue
        header = _AFTER_PARAMS.match(text, params_end + 1)
        if header is None:
            continue  # 인자 목록 뒤가 본문이 아니면 메서드 선언이 아니다 (호출식·어노테이션)
        body_start = header.end() - 1
        body_end = _span_end(text, body_start)
        if body_end < 0:
            continue
        # 가장 안쪽으로 감싸는 타입이 소유자다 — 중첩 클래스는 자기 것으로 가져간다.
        containing = [t for t in types if t[1] < match.start() < t[2]]
        if not containing:
            continue
        owner = min(containing, key=lambda t: t[2] - t[1])[0]
        unit = _Unit(
            owner=owner,
            name=name,
            start_line=text.count("\n", 0, match.start()) + 1,
            end_line=text.count("\n", 0, body_end) + 1,
        )
        seen: set[tuple[str, str]] = set()
        for call in _CALL.finditer(text, body_start, body_end):
            pair = (call.group(1), call.group(2))
            if pair not in seen:
                seen.add(pair)
                unit.calls.append(pair)
        module.units.append(unit)
    return module


class JvmIndex:
    """리포 전역 심볼 색인 — FQN 으로 타입·메서드·SQL 구문을 찾는다."""

    def __init__(self, modules: list[JavaModule], statements: dict[str, str]) -> None:
        self._modules = {module.path: module for module in modules}
        self._statements = statements  # "FQN#구문id" → db_access 노드 id
        self._by_fqn: dict[str, tuple[str, str]] = {}  # 타입 FQN → (파일, simple)
        by_simple: dict[str, set[str]] = defaultdict(set)
        for module in modules:
            for simple in module.fields:
                fqn = f"{module.package}.{simple}" if module.package else simple
                self._by_fqn[fqn] = (module.path, simple)
                by_simple[simple].add(fqn)
        # 이름이 리포에서 유일할 때만 임포트 없는 참조를 그 타입으로 인정한다.
        self._unique_simple = {simple: next(iter(fqns)) for simple, fqns in by_simple.items() if len(fqns) == 1}
        self._impls: dict[str, list[str]] = defaultdict(list)
        for module in modules:
            for simple, parents in module.supers.items():
                child = f"{module.package}.{simple}" if module.package else simple
                for parent in parents:
                    resolved = self._resolve_type(parent, module)
                    if resolved:
                        self._impls[resolved].append(child)

    def _resolve_type(self, simple: str, module: JavaModule) -> str | None:
        """타입 simple name → FQN. 임포트 > 같은 패키지 > 리포 전역 유일 이름 순으로만 인정한다."""
        if simple in module.imports:
            return module.imports[simple]
        same_package = f"{module.package}.{simple}" if module.package else simple
        if same_package in self._by_fqn:
            return same_package
        return self._unique_simple.get(simple)

    def _own_unit(self, fqn: str, method: str) -> tuple[JavaModule, _Unit] | None:
        """그 타입이 직접 소유한 메서드 본문 (상속·구현은 따르지 않는다)."""
        located = self._by_fqn.get(fqn)
        if located is None:
            return None
        module = self._modules[located[0]]
        for unit in module.units:
            if unit.owner == located[1] and unit.name == method:
                return module, unit
        return None

    def _descendants(self, fqn: str, *, depth: int = 0) -> list[str]:
        """구현·상속 후손 전부 (인터페이스 → 매퍼 인터페이스 → 구현 클래스처럼 여러 단)."""
        if depth > 4:
            return []
        out: list[str] = []
        for child in self._impls.get(fqn, []):
            out.append(child)
            out.extend(self._descendants(child, depth=depth + 1))
        return out

    def _resolve_call(self, fqn: str, method: str) -> tuple[str | None, tuple[JavaModule, _Unit] | None, bool]:
        """`타입#메서드` → (SQL 구문 노드, 이어서 걸을 메서드 본문, 미해결 여부).

        런타임에 어느 빈이 주입되는지는 정적으로 못 정한다. 그래서 후보를 좁히는 축은
        **증명된 사실**뿐이다: 매퍼 XML 이 그 이름의 구문을 실제로 선언했는가, 혹은 그 이름의
        본문을 실제로 가진 후손이 하나뿐인가. 둘 다 여럿이면 모호성으로 보고 잇지 않는다.
        """
        statement = self._statements.get(f"{fqn}#{method}")
        if statement is not None:
            return statement, None, False
        own = self._own_unit(fqn, method)
        if own is not None:
            return None, own, False
        descendants = self._descendants(fqn)
        proven = [child for child in descendants if f"{child}#{method}" in self._statements]
        if len(proven) == 1:
            return self._statements[f"{proven[0]}#{method}"], None, False
        if len(proven) > 1:
            return None, None, True  # SQL 이 여러 후손에 있다 — 어느 쪽이 뜨는지 증명 불가
        bodied = [child for child in descendants if self._own_unit(child, method) is not None]
        if len(bodied) == 1:
            return None, self._own_unit(bodied[0], method), False
        return None, None, True

    def statements_from(self, module: JavaModule, unit: _Unit, *, depth: int = 0) -> tuple[set[str], bool] | None:
        """메서드에서 도달 가능한 SQL 구문 노드 집합. 상한 초과 시 None(=버림).

        두 번째 값은 "미해결 호출이 있었나" — 커버리지가 부분임을 표시에 쓴다.
        """
        found: set[str] = set()
        partial = False
        visited: set[tuple[str, str]] = set()
        stack = [(module, unit, depth)]
        while stack:
            current_module, current_unit, current_depth = stack.pop()
            key = (current_module.path, f"{current_unit.owner}#{current_unit.name}#{current_unit.start_line}")
            if key in visited:
                continue
            visited.add(key)
            if current_depth >= _MAX_DEPTH:
                partial = True
                continue
            owner_fields = current_module.fields.get(current_unit.owner, {})
            for receiver, callee in current_unit.calls:
                type_simple = owner_fields.get(receiver)
                if type_simple is None:
                    partial = True  # 로컬 변수·정적 호출·인자 — 필드가 아니면 정체를 모른다
                    continue
                fqn = self._resolve_type(type_simple, current_module)
                if fqn is None:
                    partial = True
                    continue
                statement, nested, unresolved = self._resolve_call(fqn, callee)
                if statement is not None:
                    found.add(statement)
                    if len(found) > _MAX_STATEMENTS:
                        return None
                elif nested is not None:
                    stack.append((nested[0], nested[1], current_depth + 1))
                if unresolved:
                    partial = True
        return found, partial

    def unit_for(self, path: str, end_line: int) -> tuple[JavaModule, _Unit] | None:
        """라우트 스팬(본문 끝 줄)이 가리키는 메서드 단위."""
        module = self._modules.get(path)
        if module is None:
            return None
        for unit in module.units:
            if unit.end_line == end_line:
                return module, unit
        return None
