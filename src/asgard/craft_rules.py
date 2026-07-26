"""craft 규칙 카탈로그 — AST 하나를 받아 판정 목록을 낸다. git 도 래칫도 여기서는 모른다.

경계를 이렇게 그은 이유: 규칙은 시간이 지나며 늘어나고, 래칫(무엇이 이번 변경의 책임인가)은
늘어나지 않는다. 둘을 한 파일에 두면 규칙을 하나 더할 때마다 판정 계층을 다시 읽어야 한다.
여기 있는 함수는 전부 순수하다 — 같은 트리를 주면 같은 판정이 나오고, 파일 시스템을 안 만진다.

규칙은 셋이다. ① 단위 형상(길이·중첩) ② 자원 수명(캐시·획득·누적) ③ 시간복잡도(제곱 형상).
전부 보수적이다 — 못 보는 것을 못 본다고 말하는 쪽이, 애매한 것을 걸어 신뢰를 잃는 쪽보다 낫다.
판정기가 오탐을 내기 시작하면 그 다음에 일어나는 일은 판정기를 끄는 것이다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .health import DEPTH_WARN, UNIT_LINES_WARN, _depth

UNIT_LINES_BUDGET = UNIT_LINES_WARN  # health 와 같은 자 — 게이트와 계측이 어긋나면 둘 다 못 믿는다
DEPTH_BUDGET = DEPTH_WARN
# 길이 예산은 "한 자리에서 너무 많은 일이 벌어진다"의 대리 지표다. 설정 리터럴 하나를 돌려주는
# 함수는 250행이어도 벌어지는 일이 하나뿐이라 그 대리가 틀린다(실측: cc_settings 257행·문장 3·
# 분기 0). 문장이 이보다 적으면 길이는 로직이 아니라 데이터로 읽는다.
DATA_STMT_MAX = 10

# 획득 즉시 수명이 생기는 호출. 이름이 곧 의미인 것만 넣는다 — `connect`/`socket` 은 Qt 시그널·
# 기존 소켓의 메서드와 이름이 겹쳐 오탐을 만든다(미검출로 남기는 편이 낫다).
_ACQUIRE = frozenset(
    {"open", "Popen", "NamedTemporaryFile", "TemporaryFile", "ThreadPoolExecutor", "ProcessPoolExecutor"}
)
_RELEASE = frozenset({"close", "shutdown", "terminate", "kill", "wait", "communicate", "__exit__"})
# `os.open` 은 이름만 같고 물건이 다르다 — 파일 객체가 아니라 int fd 라서 해제도 `os.close(fd)`
# 나 `os.fdopen(fd)` 로의 소유 이전으로 일어난다. 같은 자로 재면 전부 오탐이 된다(실측: 저장소
# 전수에서 이 한 가지가 오탐의 절반). 미검출로 남긴다.
_ACQUIRE_EXCLUDE_BASE = frozenset({"os"})
_CACHE_DECORATORS = frozenset({"lru_cache", "cache"})
_GROW = frozenset({"append", "add", "extend", "update", "setdefault", "insert", "appendleft"})
_SHRINK = frozenset({"clear", "pop", "popleft", "popitem", "remove", "discard"})
_CONTAINER_CALLS = frozenset({"list", "dict", "set", "defaultdict", "OrderedDict", "Counter", "deque"})


@dataclass(frozen=True)
class Finding:
    """판정 1건. `fix` 는 무엇을 하면 풀리는지 — 증상만 말하는 게이트는 재작업을 안내하지 못한다."""

    rule: str
    path: str
    line: int
    unit: str  # 함수 qualname (모듈 스코프면 "")
    detail: str
    fix: str
    blocking: bool = True


@dataclass(frozen=True)
class Unit:
    qualname: str
    line: int
    end: int
    lines: int
    depth: int
    stmts: int  # 실행 문장 수 — 행 수만으로는 데이터와 로직을 구분할 수 없다


# ── 단위 추출 ──────────────────────────────────────────────────────


def units(text: str) -> dict[str, Unit] | None:
    """qualname → 단위 사실. 파싱 실패는 None (0 이 아니다 — 측정 못 한 것과 없는 것은 다르다)."""
    try:
        tree = ast.parse(text)
    except SyntaxError, ValueError, RecursionError:
        return None
    out: dict[str, Unit] = {}
    _collect_units(tree, (), out)
    return out


def _collect_units(node: ast.AST, prefix: tuple[str, ...], out: dict[str, Unit]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            _collect_units(child, prefix + (child.name,), out)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = ".".join(prefix + (child.name,))
            end = getattr(child, "end_lineno", child.lineno) or child.lineno
            out[name] = Unit(name, child.lineno, end, end - child.lineno + 1, _depth(child), _stmts(child))
            _collect_units(child, prefix + (child.name,), out)
        else:
            _collect_units(child, prefix, out)


def _stmts(fn: ast.AST) -> int:
    """본문의 실행 문장 수. 리터럴 표 하나를 돌려주는 함수는 길어도 문장이 몇 개 없다."""
    return sum(1 for node in ast.walk(fn) if isinstance(node, ast.stmt))


def _owner(spans: list[Unit], line: int) -> str:
    """그 줄을 품은 가장 안쪽 함수. 모듈 스코프면 빈 문자열."""
    best = ""
    width = None
    for unit in spans:
        if unit.line <= line <= unit.end and (width is None or unit.lines < width):
            best, width = unit.qualname, unit.lines
    return best


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    table: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            table[id(child)] = node
    return table


# ── 규칙 ① 단위 형상 (래칫) ────────────────────────────────────────


def shape_findings(rel: str, current: dict[str, Unit], base: dict[str, Unit] | None) -> list[Finding]:
    """예산을 넘는 단위 중 **이번에 새로 생겼거나 더 나빠진 것**만. 줄어든 것은 개선이므로 침묵한다."""
    out: list[Finding] = []
    for name, unit in sorted(current.items(), key=lambda kv: kv[1].line):
        prior = base.get(name) if base is not None else None
        oversize = unit.lines > UNIT_LINES_BUDGET and unit.stmts > DATA_STMT_MAX
        if oversize and (prior is None or unit.lines > prior.lines):
            out.append(
                Finding(
                    "unit-oversize",
                    rel,
                    unit.line,
                    name,
                    f"{unit.lines}행 (예산 {UNIT_LINES_BUDGET}행"
                    + (f", 이전 {prior.lines}행" if prior else ", 이번에 신설")
                    + ")",
                    "한 함수는 한 추상 수준만 진술한다 — 다른 수준의 덩어리를 이름 있는 함수로 빼라",
                )
            )
        if unit.depth > DEPTH_BUDGET and (prior is None or unit.depth > prior.depth):
            out.append(
                Finding(
                    "unit-deep",
                    rel,
                    unit.line,
                    name,
                    f"중첩 {unit.depth} (예산 {DEPTH_BUDGET}"
                    + (f", 이전 {prior.depth}" if prior else ", 이번에 신설")
                    + ")",
                    "가드 절로 먼저 빠져나가라 — 실패 조건을 앞에서 return 하면 본문이 한 단 내려온다",
                )
            )
    return out


# ── 규칙 ② 자원 수명 ───────────────────────────────────────────────


def pattern_findings(text: str, rel: str, spans: list[Unit]) -> list[Finding]:
    """자원 수명 + 시간복잡도 판정. 파싱 실패는 빈 목록 — 호출부가 ast 를 알 필요는 없다."""
    try:
        tree: ast.AST = ast.parse(text)
    except SyntaxError, ValueError, RecursionError:
        return []
    parents = _parents(tree)
    out: list[Finding] = []
    out.extend(_cache_findings(tree, rel, spans))
    out.extend(_acquire_findings(tree, rel, spans, parents))
    out.extend(_accumulator_findings(tree, rel, parents))
    out.extend(_cost_findings(tree, rel, spans))
    return out


def _decorators(node: ast.AST) -> list[tuple[str, ast.Call | None]]:
    found: list[tuple[str, ast.Call | None]] = []
    for dec in getattr(node, "decorator_list", ()):
        call = dec if isinstance(dec, ast.Call) else None
        target = call.func if call else dec
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name in _CACHE_DECORATORS:
            found.append((name, call))
    return found


def _unbounded_cache(name: str, call: ast.Call | None) -> bool:
    """`@cache` 는 무경계. `@lru_cache` 는 기본 maxsize=128 이라 경계가 있고, None 이면 없다."""
    if name == "cache":
        return True
    if call is None:
        return False
    for kw in call.keywords:
        if kw.arg == "maxsize":
            return isinstance(kw.value, ast.Constant) and kw.value.value is None
    return bool(call.args) and isinstance(call.args[0], ast.Constant) and call.args[0].value is None


def _cache_findings(tree: ast.AST, rel: str, spans: list[Unit]) -> list[Finding]:
    """메서드 캐시는 인스턴스를 영원히 붙잡는다 — 프로세스가 사는 동안 해제되지 않는 참조다."""
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = child.args.posonlyargs + child.args.args
            if not args or args[0].arg not in ("self", "cls"):
                continue
            for name, _ in _decorators(child):
                out.append(
                    Finding(
                        "cache-on-method",
                        rel,
                        child.lineno,
                        f"{node.name}.{child.name}",
                        f"@{name} 가 메서드에 걸려 self 가 캐시 키로 남는다",
                        "인스턴스 수명 안에서 캐시하라 — @cached_property 나 인스턴스 소유 dict",
                    )
                )
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args.posonlyargs + node.args.args
        if args and args[0].arg in ("self", "cls"):
            continue
        for name, call in _decorators(node):
            if _unbounded_cache(name, call) and (args or node.args.kwonlyargs):
                out.append(
                    Finding(
                        "cache-unbounded",
                        rel,
                        node.lineno,
                        _owner(spans, node.lineno) or node.name,
                        f"@{name} 에 경계가 없어 키 종류만큼 무한히 자란다",
                        "maxsize 를 정하라 — 키 공간이 유한하다는 근거가 있으면 그 근거를 주석으로 남겨라",
                    )
                )
    return out


def _managed(tree: ast.AST) -> set[int]:
    """`with` 가 수명을 쥔 표현식 안의 모든 호출 — contextlib.closing(open(x)) 같은 감싸기도 포함."""
    safe: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            for inner in ast.walk(item.context_expr):
                safe.add(id(inner))
    return safe


def _acquire_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name) and base.id in _ACQUIRE_EXCLUDE_BASE:
            return ""
        return func.attr
    return getattr(func, "id", "")


def _released(scope: ast.AST, target: str) -> bool:
    """그 이름이 같은 스코프 안에서 해제되거나, 수명이 밖으로 넘어갔는가.

    다른 호출의 인자로 넘어가면 해제로 친다 — 그 지점부터 소유가 어디로 갔는지는 이 분석이
    따라갈 수 없고, 따라가지 못하는 것을 누수라고 부르면 그것은 판정이 아니라 짐작이다.
    """
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                base = func.value
                if func.attr in _RELEASE and isinstance(base, ast.Name) and base.id == target:
                    return True
            if any(isinstance(a, ast.Name) and a.id == target for a in node.args):
                return True
        if isinstance(node, (ast.Return, ast.Yield)) and isinstance(node.value, ast.Name) and node.value.id == target:
            return True
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id == target:
            return any(isinstance(t, ast.Attribute) for t in node.targets)  # self.x = f — 소유 이전
    return False


def _acquire_findings(tree: ast.AST, rel: str, spans: list[Unit], parents: dict[int, ast.AST]) -> list[Finding]:
    safe = _managed(tree)
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in safe:
            continue
        name = _acquire_name(node)
        if name not in _ACQUIRE:
            continue
        holder = _holder(node, parents)
        if holder is not None and _released(_scope_of(node, parents, tree), holder):
            continue
        if holder is None and _handed_off(node, parents):
            continue
        out.append(
            Finding(
                "unclosed-acquire",
                rel,
                node.lineno,
                _owner(spans, node.lineno),
                f"{name}() 의 수명을 아무도 안 쥔다"
                + (f" — {holder} 가 닫히지 않는다" if holder else " — 결과를 붙잡지도 닫지도 않는다"),
                "with 로 감싸라 — 예외가 나도 닫히는 경로는 그것뿐이다",
            )
        )
    return out


def _holder(call: ast.Call, parents: dict[int, ast.AST]) -> str | None:
    """`f = open(...)` 형태에서 f. 그 외(인자로 넘김·체이닝·버림)는 None."""
    parent = parents.get(id(call))
    if isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
        return parent.targets[0].id
    return None


def _handed_off(call: ast.Call, parents: dict[int, ast.AST]) -> bool:
    """반환·yield·속성 대입은 수명을 밖으로 넘긴 것 — 이 함수가 닫을 일이 아니다."""
    parent = parents.get(id(call))
    if isinstance(parent, (ast.Return, ast.Yield)):
        return True
    if isinstance(parent, ast.Assign):
        return any(isinstance(t, (ast.Attribute, ast.Subscript)) for t in parent.targets)
    return False


def _scope_of(node: ast.AST, parents: dict[int, ast.AST], tree: ast.AST) -> ast.AST:
    cur: ast.AST | None = node
    while cur is not None:
        cur = parents.get(id(cur))
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur
    return tree


def _module_containers(tree: ast.AST) -> dict[str, int]:
    """모듈 스코프의 가변 컨테이너 이름 → 정의 줄. maxlen 이 달린 deque 는 이미 경계가 있다."""
    found: dict[str, int] = {}
    for node in getattr(tree, "body", ()):
        target = _single_target(node)
        value = getattr(node, "value", None)
        if target is None or not _is_container(value):
            continue
        found[target] = node.lineno
    return found


def _single_target(node: ast.AST) -> str | None:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None


def _is_container(value: ast.AST | None) -> bool:
    if isinstance(value, (ast.List, ast.Dict, ast.Set)):
        return True
    if not isinstance(value, ast.Call):
        return False
    name = value.func.attr if isinstance(value.func, ast.Attribute) else getattr(value.func, "id", "")
    if name == "deque":
        return not any(kw.arg == "maxlen" for kw in value.keywords) and len(value.args) < 2
    return name in _CONTAINER_CALLS


def _accumulator_findings(tree: ast.AST, rel: str, parents: dict[int, ast.AST]) -> list[Finding]:
    """모듈 스코프 컨테이너가 런타임에 자라기만 하면, 프로세스 수명 = 그 자료구조의 수명이다."""
    containers = _module_containers(tree)
    if not containers:
        return []
    grows, shrinks = _mutations(tree, set(containers), parents)
    out: list[Finding] = []
    for name, line in sorted(containers.items(), key=lambda kv: kv[1]):
        if name in grows and name not in shrinks:
            out.append(
                Finding(
                    "unbounded-accumulator",
                    rel,
                    grows[name],
                    "",
                    f"모듈 스코프 {name} 이 실행 중에 자라기만 한다 (줄이는 자리 없음)",
                    "경계를 정하라 — maxlen·축출·주기적 비움 중 하나, 아니면 호출자가 소유하게 넘겨라",
                    # 막지 않고 묻는다: 키 공간이 유한하다는 것(플러그인 레지스트리 같은)을 정적으로
                    # 증명할 수 없다. 증명 못 하는 것을 결함이라 부르면 그게 오탐이다.
                    blocking=False,
                )
            )
    return out


def _mutations(tree: ast.AST, names: set[str], parents: dict[int, ast.AST]) -> tuple[dict[str, int], set[str]]:
    """(이름 → 성장이 일어난 줄, 줄어드는 이름들). 성장은 **함수 안**에서 일어난 것만 센다.

    import 시점에 한 번 채우는 상수 표(모듈 최상단의 append)는 성장이 아니라 정의다.
    """
    builders = _import_time_builders(tree)
    grows: dict[str, int] = {}
    shrinks: set[str] = set()
    for node in ast.walk(tree):
        name, kind = _mutation_of(node, names)
        if name is None:
            continue
        # 모듈 스코프에서 일어나는 일은 정의다 — 최상단의 `X = {}` 은 비움이 아니고, 그 옆의
        # 채우기는 성장이 아니라 상수 표를 짓는 것이다. 런타임 성장·비움만 수명 신호가 된다.
        scope = _scope_of(node, parents, tree)
        in_function = not isinstance(scope, ast.Module)
        if kind == "shrink":
            shrinks.add(name)
        elif kind == "rebind":
            if in_function:
                shrinks.add(name)
        elif in_function and getattr(scope, "name", "") not in builders:
            grows.setdefault(name, getattr(node, "lineno", 0))
    return grows, shrinks


def _import_time_builders(tree: ast.AST) -> set[str]:
    """모듈 최상단에서 호출되는 함수 이름 — 표를 짓는 헬퍼(`rule(...)` × 40줄)를 런타임 성장으로
    오인하지 않기 위한 것. import 때 한 번 채워지는 표는 수명이 아니라 정의다."""
    called: set[str] = set()
    for node in getattr(tree, "body", ()):
        # def/class 는 정의일 뿐 실행이 아니다 — 본문까지 훑으면 모듈 안 모든 호출이 여기 들어와
        # 규칙이 통째로 죽는다 (실측: 억제 후 9건 → 3건이 아니라 규칙 자체가 침묵했다).
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                called.add(inner.func.id)
    return called


def _mutation_of(node: ast.AST, names: set[str]) -> tuple[str | None, str]:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        base = node.func.value
        if isinstance(base, ast.Name) and base.id in names:
            if node.func.attr in _GROW:
                return base.id, "grow"
            if node.func.attr in _SHRINK:
                return base.id, "shrink"
    if isinstance(node, ast.Delete):
        for target in node.targets:
            hit = _subscript_name(target, names)
            if hit:
                return hit, "shrink"
    if isinstance(node, ast.Assign):
        for target in node.targets:
            hit = _subscript_name(target, names)
            if hit:
                return hit, "grow"
            if isinstance(target, ast.Name) and target.id in names:
                return target.id, "rebind"  # 함수 안이면 갈아끼우기(비움), 모듈 최상단이면 정의
    return None, ""


def _subscript_name(target: ast.AST, names: set[str]) -> str | None:
    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id in names:
        return target.value.id
    return None


# ── 규칙 ③ 시간복잡도 ──────────────────────────────────────────────
# 루프 안에서 한 번 더 훑는 것은 자료구조 선택 실수지 최적화 문제가 아니다. 그래서 "측정 없이는
# 최적화 금지"(역할 캐논 7)와 충돌하지 않는다 — 이건 빠르게 만드는 게 아니라 **처음부터 자료
# 구조를 맞게 고르는** 일이다. 입력이 열 배가 되면 백 배가 되는 형상만 잡는다.


def _cost_findings(tree: ast.AST, rel: str, spans: list[Unit]) -> list[Finding]:
    out: list[Finding] = []
    for scope in _scopes(tree):
        looped = _loop_bodies(scope)
        if not looped:
            continue
        dynamic = _dynamic_sequences(scope)
        out.extend(_scan_findings(scope, rel, spans, looped, dynamic))
        out.extend(_shift_findings(scope, rel, spans, looped))
        out.extend(_concat_findings(scope, rel, spans, looped))
    return out


def _scopes(tree: ast.AST) -> list[ast.AST]:
    return [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _walk_local(scope: ast.AST):
    """그 스코프에 **속한** 노드만 — 중첩 함수·클래스 본문으로는 내려가지 않는다.

    ast.walk 를 그대로 쓰면 바깥 스코프가 안쪽 함수의 노드까지 같이 세서 같은 판정이 두 번
    나오고, 안쪽 지역 변수가 바깥의 이름 표에 섞인다.
    """
    stack = [scope]
    while stack:
        node = stack.pop()
        if node is not scope:
            yield node
        if node is not scope and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _loop_bodies(scope: ast.AST) -> set[int]:
    """루프 본문 안에 있는 모든 노드 id. 중첩 함수는 자기 스코프에서 따로 본다."""
    inside: set[int] = set()
    for node in _walk_local(scope):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            continue
        for stmt in node.body:
            for inner in ast.walk(stmt):
                inside.add(id(inner))
    return inside


# 크기가 입력에 따라 정해지는 시퀀스를 만드는 호출. 고정 상수 목록(`(".py", ".ts")`)은 여기
# 없다 — 원소가 셋인 튜플을 훑는 것은 비용이 아니라 가독성이고, 그걸 걸면 게이트가 소음이 된다.
_DYNAMIC_SEQ_CALLS = frozenset({"list", "sorted", "split", "rsplit", "splitlines", "readlines", "findall"})


def _dynamic_sequences(scope: ast.AST) -> dict[str, int]:
    found: dict[str, int] = {}
    for node in _walk_local(scope):
        target = _single_target(node)
        value = getattr(node, "value", None)
        if target is None:
            continue
        if isinstance(value, ast.ListComp):
            found[target] = node.lineno
        elif isinstance(value, ast.Call):
            name = value.func.attr if isinstance(value.func, ast.Attribute) else getattr(value.func, "id", "")
            if name in _DYNAMIC_SEQ_CALLS:
                found[target] = node.lineno
        elif isinstance(value, ast.List) and not value.elts:
            found[target] = node.lineno  # `out = []` 뒤에 append 로 자라는 것도 크기가 입력을 탄다
    return found


def _scan_findings(
    scope: ast.AST, rel: str, spans: list[Unit], looped: set[int], dynamic: dict[str, int]
) -> list[Finding]:
    out: list[Finding] = []
    for node in _walk_local(scope):
        if not isinstance(node, ast.Compare) or id(node) not in looped or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], (ast.In, ast.NotIn)):
            continue
        right = node.comparators[0]
        if not isinstance(right, ast.Name) or right.id not in dynamic:
            continue
        out.append(
            Finding(
                "quadratic-scan",
                rel,
                node.lineno,
                _owner(spans, node.lineno),
                f"루프 안에서 목록 {right.id} 를 매번 처음부터 훑는다 (O(n·m))",
                f"{right.id} 를 set 으로 한 번 만들어 두고 조회하라 — 원소 수가 열 배면 시간은 백 배다",
            )
        )
    return out


def _shift_findings(scope: ast.AST, rel: str, spans: list[Unit], looped: set[int]) -> list[Finding]:
    """앞에서 넣고 빼는 연산은 매번 뒤 전체를 옮긴다 — 루프 안에 있으면 그것만으로 제곱이다."""
    out: list[Finding] = []
    for node in _walk_local(scope):
        if not isinstance(node, ast.Call) or id(node) not in looped:
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
            continue
        head = node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 0
        if not head or func.attr not in ("insert", "pop"):
            continue
        out.append(
            Finding(
                "quadratic-scan",
                rel,
                node.lineno,
                _owner(spans, node.lineno),
                f"{func.value.id}.{func.attr}(0…) 이 루프 안에 있다 — 한 번에 뒤 전체가 밀린다",
                "collections.deque 를 써라 — 양끝 삽입·삭제가 상수 시간이다",
            )
        )
    return out


def _concat_findings(scope: ast.AST, rel: str, spans: list[Unit], looped: set[int]) -> list[Finding]:
    """`s = s + x` 는 루프마다 새 객체를 통째로 만든다. `+=` 와 달리 확장이 아니라 복사다."""
    out: list[Finding] = []
    for node in _walk_local(scope):
        if not isinstance(node, ast.Assign) or id(node) not in looped:
            continue
        target = _single_target(node)
        value = node.value
        if target is None or not isinstance(value, ast.BinOp) or not isinstance(value.op, ast.Add):
            continue
        if not (isinstance(value.left, ast.Name) and value.left.id == target):
            continue
        out.append(
            Finding(
                "quadratic-scan",
                rel,
                node.lineno,
                _owner(spans, node.lineno),
                f"루프 안에서 {target} = {target} + … 로 매번 통째로 다시 만든다",
                "조각을 목록에 모아 마지막에 한 번 합쳐라 (str 이면 join, list 면 extend)",
            )
        )
    return out
