"""AST 로 모듈 레벨 임포트 엣지를 뽑는 공용 계기 — 계층·패키지·사슬 시험이 같은 해석기를 쓴다."""

from __future__ import annotations

import ast
import os

from architecture.layers import _RANK, LAYERS, SRC
from architecture.packages import _FACADE


def _module_dotted(path: str) -> list[str]:
    """src/asgard 기준 상대 경로 → 패키지 경로 성분 (파일명 제외 규칙: __init__은 패키지 자신)."""
    rel = os.path.relpath(path, SRC)
    parts = rel.replace(os.sep, "/").removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return parts


def _iter_py_files():
    for dirpath, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _resolved_targets(node: ast.stmt, parts: list[str]) -> set[tuple[str, ...]]:
    """import 문 → 임포트 대상의 절대 경로 성분 (`asgard` 접두는 뗀다, 외부 라이브러리는 무시).

    상대(`from .server import X`)와 절대(`from asgard.commands.studio.server import X`)를 한
    자리에서 푼다. 대상 해석기가 하나여야 문법을 바꿔 규칙을 비껴가는 자리가 안 생긴다.
    `from pkg import name` 은 name 이 모듈일 수도 있어 `pkg` 와 `pkg.name` 을 둘 다 낸다 —
    쓰는 쪽이 필요한 깊이만 잘라 본다.
    """
    out: set[tuple[str, ...]] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            bits = alias.name.split(".")
            if bits[0] == "asgard" and len(bits) > 1:
                out.add(tuple(bits[1:]))
    elif isinstance(node, ast.ImportFrom):
        if node.level == 0:
            bits = (node.module or "").split(".")
            if bits and bits[0] == "asgard" and len(bits) > 1:
                base = tuple(bits[1:])
                out.add(base)
                out.update(base + (alias.name,) for alias in node.names)
        else:
            # 상대 임포트 해석 — parts는 파일의 패키지 경로 성분 (파일이 모듈이면 모듈명 포함)
            pkg = parts[:-1] if parts else []  # 담는 패키지 (모듈 파일 기준)
            if node.level - 1 > len(pkg):
                return out
            base = tuple(pkg[: len(pkg) - (node.level - 1)])
            if node.module:
                base = base + tuple(node.module.split("."))
                if base:
                    out.add(base)
            out.update(base + (alias.name,) for alias in node.names)
    return out


def _top_targets(node: ast.stmt, parts: list[str]) -> set[str]:
    """import 문 → asgard 내부 top-level 대상 집합 (외부 라이브러리는 무시)."""
    out = {target[0] for target in _resolved_targets(node, parts) if target}
    return {t for t in out if t in _RANK or t == "assets"}


_FUNCTION_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _is_type_checking_guard(node: ast.AST) -> bool:
    """`if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:` 인가 — 본문이 런타임에 안 도는 자리."""
    test = getattr(node, "test", None)
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _module_level_imports(tree: ast.Module) -> list[ast.stmt]:
    """모듈을 임포트할 때 **실제로 도는** import 문. 판정 대상은 이것이고, 들여쓰기가 아니다.

    `tree.body` 직접 자식만 보면 `try: ... except ImportError:` 아래가 규칙 밖으로 빠진다.
    그 자리는 상향 결합이 조용히 들어오는 통로다 — 임포트는 도는데 실패해도 fail-open 이라
    아무 소리가 안 난다. 훅 시험은 이미 try 를 재귀로 훑으므로 같은 파일 안에서 엄밀도가
    갈리지 않게 여기도 맞춘다. `if`/`try`/`with` 와 클래스 본문은 임포트 시점에 도니까 전부
    포함한다.

    빼는 것은 둘뿐이고 둘 다 이유가 같다 — 안 돈다. 함수 안 lazy 임포트(의도된 탈출구)와
    `if TYPE_CHECKING:` 본문이다. 후자는 이 저장소가 순환을 피하려고 고른 형식이고
    (`agent/heimdall/waves.py:25` 가 그 이유를 적어 뒀다), 그 자리를 막으면 남는 선택지는
    타입을 지우는 것뿐이다. `else` 는 실제로 도므로 계속 본다.
    """
    found: list[ast.stmt] = []
    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, _FUNCTION_SCOPES):
            continue
        if isinstance(node, ast.If) and _is_type_checking_guard(node):
            stack.extend(node.orelse)
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(node)
            continue
        stack.extend(ast.iter_child_nodes(node))
    return sorted(found, key=lambda node: (node.lineno, node.col_offset))


def _toplevel_edges():
    """계층 등재 모듈 사이의 모듈 레벨 임포트 전수 → (파일, 행, 출발 최상위, 도착 최상위)."""
    for path in _iter_py_files():
        parts = _module_dotted(path)
        if not parts:  # asgard/__init__.py — 루트 파사드는 규칙 밖 (버전 표면)
            continue
        src_top = parts[0]
        if src_top not in _RANK:
            continue
        rel = os.path.relpath(path, SRC)
        # __init__.py는 패키지 자신이 담는 패키지 — 상대 해석용 성분에 sentinel 추가
        file_parts = (parts + ["__init__"]) if rel.endswith("__init__.py") else parts
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in _module_level_imports(tree):
            for target in _top_targets(node, file_parts):
                if target == "assets" or target == src_top:
                    continue
                yield rel, node.lineno, src_top, target


def _iter_packages() -> list[tuple[str, ...]]:
    """src/asgard 아래 패키지 전수 → dotted 성분. `.py`를 담은 디렉터리면 전부 센다.

    `__init__.py` 존재를 조건으로 걸지 않는다: 그러면 규칙이 재는 범위가 파일 하나의 유무로
    움직이고, 그 파일을 지우는 것만으로 패키지를 규칙 밖으로 뺄 수 있다. assets 는 코드가
    아니라 배포 자료라서 제외한다 (계층 규칙도 같은 이유로 assets 를 통과시킨다).
    """
    out: list[tuple[str, ...]] = []
    for dirpath, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(dirpath, SRC).replace(os.sep, "/")
        if rel == ".":
            continue
        parts = tuple(rel.split("/"))
        if parts[0] == "assets" or not any(f.endswith(".py") for f in files):
            continue
        out.append(parts)
    return sorted(out)


def _package_children(pkg: tuple[str, ...]) -> set[str]:
    """패키지의 직속 자식 — 모듈·서브패키지 + 파사드(`__init__`). 등급표가 덮어야 하는 이름이다."""
    base = os.path.join(SRC, *pkg)
    out = {_FACADE}
    for entry in sorted(os.listdir(base)):
        if entry in ("__pycache__", "__init__.py"):
            continue
        full = os.path.join(base, entry)
        if entry.endswith(".py"):
            out.add(entry.removesuffix(".py"))
        elif os.path.isdir(full) and any(f.endswith(".py") for f in os.listdir(full)):
            out.add(entry)
    return out


def _package_edges(pkg: tuple[str, ...]):
    """패키지 안쪽 모듈 레벨 임포트 전수 → (파일, 행, 출발 자식, 도착 자식).

    깊은 자리는 직속 자식 하나로 접는다: `commands/studio/server.py` 가 `commands/loopback.py`
    를 부르면 `commands` 층에서는 studio → loopback 한 건이고, 같은 자식 안쪽
    (`studio/server.py` → `studio/state.py`)은 `commands.studio` 층에서 잰다. 그래서 한 임포트가
    두 층에서 두 번 세지지 않는다.

    안에서 패키지 자신을 절대 경로로 부른 자리(`from asgard.memory import Foo` in memory/*)는
    파사드로 되돌아오는 엣지로 잡는다 — 형제 모듈 이름이 안 나온 경우만이다. 형제가 나오면
    그건 서브모듈 임포트이고, 그쪽으로 세는 것이 실제 결합을 가리킨다.
    """
    depth = len(pkg)
    children = _package_children(pkg)
    for path in _iter_py_files():
        parts = _module_dotted(path)
        if tuple(parts[:depth]) != pkg:
            continue
        src = _FACADE if len(parts) == depth else parts[depth]
        rel = os.path.relpath(path, SRC)
        file_parts = (parts + [_FACADE]) if os.path.basename(path) == "__init__.py" else parts
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in _module_level_imports(tree):
            targets = _resolved_targets(node, file_parts)
            hits = {
                target[depth]
                for target in targets
                if len(target) > depth and tuple(target[:depth]) == pkg and target[depth] in children
            }
            if not hits and any(tuple(target) == pkg for target in targets):
                hits = {_FACADE}
            for dst in sorted(hits):
                if dst != src:
                    yield rel, node.lineno, src, dst


def _layer(top: str) -> str:
    return LAYERS[_RANK[top]][0]
