"""tutor 탐침 — 본문 하나를 받아 "사용자가 물어야 할 사실"만 뽑는다. git도 래칫도 모른다.

`craft_rules`와 같은 자리에 같은 이유로 있다: 탐침은 시간이 지나며 늘어나고, 무엇을 이번
변경의 책임으로 볼지(래칫)는 늘어나지 않는다. 여기 있는 함수는 전부 순수하다 — 같은 본문을
주면 같은 사실이 나오고 파일 시스템을 안 만진다.

탐침의 기준은 `craft`의 차단 기준과 **다르다**. craft는 정적으로 증명 가능한 것만 막는다.
튜터는 막지 않으므로 증명까지 갈 필요가 없고, 대신 다른 문턱을 넘어야 한다 — **물을 가치가
있는가**. 사람이 세 번 물어보고 세 번 다 "그건 원래 그렇다"라고 답하면, 네 번째부터는 아무도
안 읽는다. 그래서 여기 들어온 탐침은 전부 "저자가 답을 안 적어둔 자리"로 좁혀져 있다.

돌려주는 값은 전부 **서명 → 줄 번호** 표다. 서명이 줄 번호가 아닌 이유는 래칫 때문이다: 위에서
함수 하나가 길어지면 아래 모든 줄이 밀리고, 줄로 대조하면 안 건드린 자리가 전부 새것이 된다.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import io
import re
import sys
import tokenize

from . import craft_lex, craft_rules
from .craft_rules import Unit

_MARK_RE = re.compile(r"(?:#|//|/\*|\*)\s*(TODO|FIXME|XXX|HACK)\b[:\s]*(.{0,80})")
_MARK_BODY = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b[:\s]*(.{0,80})")  # 이미 주석인 조각에만 쓴다
_STDLIB = getattr(sys, "stdlib_module_names", frozenset())


def units_of(text: str, rel: str) -> dict[str, Unit] | None:
    """경로의 언어에 맞는 단위 표. 모르는 언어·못 읽은 본문은 None (미판정과 없음은 다르다)."""
    if rel.endswith(".py"):
        return craft_rules.units(text)
    lang = craft_lex.language(rel)
    return craft_lex.units(text, lang) if lang else None


def unit_fingerprints(text: str, rel: str) -> dict[str, str]:
    """Python 단위의 본문 지문.

    이름과 줄 좌표만 빼고 서명·장식자·본문은 그대로 센다. 그래서 같은 구현을 다른 파일이나
    다른 이름으로 옮긴 경우는 잡되, 옮기면서 동작을 고친 경우는 삭제가 아니라고 단정하지 않는다.
    이 지문은 Tutor가 대규모 추출을 단위별 삭제 100건으로 오해하지 않게 하는 보수적인 근거다.
    """
    if not rel.endswith(".py"):
        return {}
    tree = _tree(text)
    if tree is None:
        return {}
    out: dict[str, str] = {}

    def visit(node: ast.AST, prefix: tuple[str, ...] = ()) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, prefix + (child.name,))
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = ".".join(prefix + (child.name,))
                clone = copy.deepcopy(child)
                clone.name = "_moved_unit"
                body = ast.dump(clone, annotate_fields=True, include_attributes=False)
                out[name] = hashlib.sha256(body.encode("utf-8")).hexdigest()
                visit(child, prefix + (child.name,))
                continue
            visit(child, prefix)

    visit(tree)
    return out


def _tree(text: str) -> ast.AST | None:
    try:
        return ast.parse(text)
    except SyntaxError, ValueError, RecursionError:
        return None


# ── 탐침 ① 설명 없는 예외 삼킴 ─────────────────────────────────────


def swallows(text: str) -> dict[str, int]:
    """본문이 통째로 무행동이고 **주석 한 줄 없는** 예외 처리기.

    이 저장소는 fail-open을 의도적으로 쓴다 — 훅 계약이 그렇다("관측이 실행을 인질로 잡지
    않는다"). 그러니 삼킴 자체는 결함이 아니고, 결함이라 부르면 그게 오탐이다. 물을 것은 하나뿐
    이다: **삼킨 이유를 아무 데도 안 적었다.** 이유를 적어 둔 자리는 저자가 이미 답한 자리다.
    """
    tree = _tree(text)
    if tree is None:
        return {}
    commented = _comment_lines(text)
    out: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not _inert(node.body):
            continue
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        if any(line in commented for line in range(node.lineno - 1, end + 1)):
            continue
        out.setdefault(f"{_exc_name(node.type)}@{_nearest_def(tree, node.lineno)}", node.lineno)
    return out


def _inert(body: list[ast.stmt]) -> bool:
    """아무 일도 안 하는 본문인가. `raise`·로그·반환·대입이 하나라도 있으면 삼킨 게 아니다."""
    if len(body) != 1:
        return False
    only = body[0]
    if isinstance(only, ast.Pass):
        return True
    return isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) and only.value.value is Ellipsis


def _exc_name(node: ast.expr | None) -> str:
    return ast.unparse(node) if node is not None else "bare except"


def _comment_lines(text: str) -> set[int]:
    """주석이 붙은 줄 번호 — **줄 끝 주석 포함**.

    줄머리만 보면 `pass  # fail-open — 관측이 실행을 막지 않는다`가 통째로 오탐이 된다. 그게
    이 저장소에서 이유를 적는 실제 관용이므로, 줄머리만 보는 판정기는 자기 나무에서 오탐률이
    가장 높다. 문자열 안의 `#`과 구분해야 하니 어휘 분석기로 센다.
    """
    try:
        return {
            token.start[0]
            for token in tokenize.generate_tokens(io.StringIO(text).readline)
            if token.type == tokenize.COMMENT
        }
    except Exception:  # 토큰화 실패 — ast가 읽은 본문이라 드물지만, 못 세면 덜 묻는 쪽으로
        return {i for i, line in enumerate(text.splitlines(), 1) if "#" in line}


def _nearest_def(tree: ast.AST, line: int) -> str:
    """그 줄을 품은 가장 안쪽 정의 이름 — 줄 번호 대신 쓰는 안정적 서명."""
    best, width = "", None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        if node.lineno <= line <= end and (width is None or end - node.lineno < width):
            best, width = node.name, end - node.lineno
    return best


# ── 탐침 ② 새 외부 의존 ────────────────────────────────────────────


def imports(text: str) -> dict[str, int]:
    """top-level 비표준 패키지 → 줄. 표준 라이브러리와 상대 임포트는 뺀다.

    의존 하나는 코드 몇 줄보다 오래 남는다 — 버전·보안·라이선스·이관 비용이 전부 따라온다.
    그래서 이건 구현 세부가 아니라 **사용자가 승인할 결정**이고, 승인은 물어야 일어난다.

    자기 저장소의 패키지를 걸러내는 일은 여기서 안 한다 — 그건 나무를 봐야 아는 사실이고,
    이 모듈은 본문 하나만 본다(순수 계약). 거르는 쪽은 `tutor._own_names` 다.
    """
    tree = _tree(text)
    if tree is None:
        return {}
    out: dict[str, int] = {}
    for node in ast.walk(tree):
        for name in _import_targets(node):
            if name and name not in _STDLIB and not name.startswith("_"):
                out.setdefault(name, getattr(node, "lineno", 1))
    return out


def _import_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0:  # 상대 임포트는 외부가 아니다
        return [(node.module or "").split(".")[0]]
    return []


# ── 탐침 ③ 남긴 표식 ───────────────────────────────────────────────


def marks(text: str, rel: str = "") -> dict[str, int]:
    """`TODO`·`FIXME`·`XXX`·`HACK` 표식 → 줄. 서명이 본문이라 줄이 밀려도 같은 표식으로 붙는다.

    표식은 저자가 스스로 "여기 안 끝났다"고 적어 둔 자리다. 기계가 판정할 것이 없고, 그래서
    가장 싸다 — 사실을 그대로 사용자 앞에 옮기기만 하면 된다.

    Python은 어휘 분석기로 **진짜 주석만** 센다. 정규식으로 훑으면 문자열 리터럴 안의 `#
    TODO`가 표식이 되고, 그게 이 판정기의 실측 오탐 1번이었다(자기 테스트 픽스처가 걸렸다). 다른
    언어는 파서가 없으니 정규식으로 최선을 다하되, 그 한계를 여기 적어 둔다.
    """
    if rel.endswith(".py"):
        return _sign(_comment_tokens(text), _MARK_BODY)
    return _sign({(line, number) for number, line in enumerate(text.splitlines(), 1)}, _MARK_RE)


def _comment_tokens(text: str) -> set[tuple[str, int]]:
    try:
        return {
            (token.string, token.start[0])
            for token in tokenize.generate_tokens(io.StringIO(text).readline)
            if token.type == tokenize.COMMENT
        }
    except Exception:  # 토큰화 실패 — 표식 하나 놓치는 쪽이 없는 표식을 지어내는 쪽보다 낫다
        return set()


def _sign(chunks: set[tuple[str, int]], pattern: re.Pattern[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for chunk, number in sorted(chunks, key=lambda pair: pair[1]):
        found = pattern.search(chunk)
        if found:
            out.setdefault(f"{found.group(1)}:{found.group(2).strip()[:60]}", number)
    return out


# ── 탐침 ④ 사라진 판정 ─────────────────────────────────────────────


def is_test_path(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    return any(p in {"tests", "test", "spec", "__tests__"} for p in parts[:-1]) or parts[-1].startswith("test_")


def test_units(names: object) -> set[str]:
    """테스트로 읽을 단위 이름만. 판정이 사라진 것과 구현이 사라진 것은 물음이 다르다."""
    if not isinstance(names, (list, tuple, set, frozenset, dict)):
        return set()
    return {n for n in names if isinstance(n, str) and n.rsplit(".", 1)[-1].startswith(("test_", "it_", "should_"))}
