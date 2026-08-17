"""tutor_teach — 이번 변경을 **읽는 순서로 되돌려 주는** 층. 물음이 아니라 전달이다.

`tutor`는 일부러 설명을 안 한다(계약 ①). 그 자리에서 옳은 판단이지만, 절반만 옳았다: 되짚기의
사다리(`tutor_growth`의 1·3·7·21일)와 각도 회전은 전부 **인출** 장치다 — 이미 받은 지식을 다시
꺼내게 만드는 쪽이다. 그런데 이 저장소는 그 앞의 절반을 가진 적이 없다. 전달된 적 없는 지식을
인출 연습시키면 남는 것은 좌표뿐이고, 좌표만으로는 아무도 흐름을 재구성하지 못한다.

두 단계는 난이도를 반대로 쓴다. 지식을 **받는** 동안 난이도는 방해물이라 설명이 짧고 쉬워야
하고, 기술을 **굳히는** 동안 난이도는 도구라 간격·각도·인출이 필요하다. 여기는 앞쪽이고
`tutor`가 뒤쪽이다.

계약 다섯 줄:

  ① 좌표 없는 주장을 안 만든다. `Step`도 `Term`도 `path:line`을 가진다.
  ② `tutor` 계약 ①을 안 깬다. 설명하는 것은 **무엇이 바뀌었나 · 어떤 순서로 읽나 · 무엇이
     무엇을 부르나 · 그 단위가 무엇을 한다고 스스로 적어 두었나** 넷이다. 마지막 것은 추측이
     아니라 **인용**이다 — 그 단위의 docstring 첫 문장을 원문 그대로 옮기고, 없으면 아무것도 안
     쓴다. 기계가 지어낸 의도는 여전히 금지고, 그 경계를 판정하는 자리가 `PurposeTest` 다.
  ③ 용어집에 이미 있는 말은 다시 설명하지 않는다. 회차마다 설명이 짧아지는 것이 목표다.
  ④ 깊이에 따라 화면이 줄어든다 — `owned`는 좌표 한 줄, `familiar`는 읽는 순서, `first`는 전부.
  ⑤ 못 본 것은 `gaps`에 적는다. 조용한 절단은 "0건"을 "안 봤다"로 만든다.

상태 파일 둘(`.asgard/tutor/mission.md`·`glossary.md`)은 gitignore 안이다 — 팀 문서가 아니라
이 사람의 기록이고, 그래서 쓰기 실패는 삼킨다(튜터는 관문이 아니다).
"""

from __future__ import annotations

import ast
import os
import subprocess
from collections import Counter
from dataclasses import dataclass

from . import surface, tutor_growth, tutor_probes
from .health import _read
from .io_files import read_text, write_text

MISSION_REL = os.path.join(".asgard", "tutor", "mission.md")
GLOSSARY_REL = os.path.join(".asgard", "tutor", "glossary.md")
MAX_PATHS = 400  # 한 번에 읽을 파일 상한 — 넘친 만큼은 gaps 에 적는다
MAX_STEPS = 40  # 읽는 순서의 상한. 마흔 자리를 넘기면 그건 순서가 아니라 목록이다
MAX_TEST_FILES = 6  # 확인 명령 한 줄에 넣을 테스트 파일 수
OWNED_AT = 3  # 이 경로들에 대해 답한 물음이 이만큼이면 좌표만 준다
DEPTHS = ("first", "familiar", "owned")
# 코드 단위를 못 읽은 것이 아니라 읽을 단위가 없는 확장자. 이것까지 gaps 에 올리면 문서 한 줄
# 고칠 때마다 "못 봤다"가 쌓이고, 그러면 그 목록을 아무도 안 본다.
_DOC_SUFFIXES = (
    ".md",
    ".txt",
    ".rst",
    ".json",
    ".jsonl",
    ".ndjson",
    ".log",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".lock",
    ".csv",
    ".svg",
)
_DOC_NAMES = frozenset({".gitignore", ".gitattributes", ".dockerignore", "LICENSE", "NOTICE"})


@dataclass(frozen=True)
class Term:
    """이번 변경이 새로 들여온 말 하나 — 새 공개 심볼이거나 새 외부 의존이다."""

    name: str
    where: str  # "path:line"
    gloss: str  # 한 줄 뜻. 시그니처나 docstring 첫 문장에서만 뽑고, 없으면 빈 문자열
    source: str  # "signature" | "docstring" | "dependency"


@dataclass(frozen=True)
class Step:
    """읽는 순서의 한 자리. `what`·`does`·`why_here`에는 기계가 확인한 사실만 들어간다."""

    order: int
    path: str
    line: int
    unit: str
    what: str
    why_here: str
    # 이 단위가 무엇을 하는가 — 그 단위 자신의 docstring 첫 문장이다. 없으면 빈 문자열이고,
    # 그러면 화면은 종전처럼 좌표와 변경 사실만 낸다. 지어내지 않는다(계약 ②).
    does: str = ""

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Explanation:
    base: str
    depth: str
    mission: str
    steps: tuple[Step, ...]
    terms: tuple[Term, ...]
    checks: tuple[str, ...]
    recall: tuple[str, ...]
    gaps: tuple[tuple[str, str], ...]
    # 아래 넷은 카드가 목록보다 먼저 지도를 보여 주기 위한 사실이다. 기본값은 구 payload 호환용.
    total_units: int = 0
    flow_count: int = 0
    primary_units: int = 0
    overview: str = ""


@dataclass(frozen=True)
class _Node:
    """읽는 순서를 만들기 전의 단위 하나. 간선을 놓기 전이라 아직 차례가 없다."""

    path: str
    line: int
    unit: str
    what: str
    python: bool
    does: str = ""


_Key = tuple[str, str]  # (경로, 단위 이름)

# 식별자 뒤에는 조사를 안 붙인다. 은/는·이/가·을/를은 앞 낱말을 **소리 내어 읽은** 받침으로
# 갈리는데, 라틴 식별자의 소리는 기계가 모른다 — `top`은 톱(받침 있음)이고 `card`는 카드(없음)라
# 철자로도 어미로도 못 가른다. 그래서 이름 뒤에는 늘 한국어 낱말(`단위`·`곳`)을 하나 두고
# 조사는 그 낱말에 붙인다. 판정기 없이 지킬 수 있는 유일한 규칙이다.


# ── git 재료 ───────────────────────────────────────────────────────


def _git(root: str, args: list[str], timeout: int = 30) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except OSError, subprocess.SubprocessError:
        return None  # git 이 없거나 저장소가 아니다 — 설명이 없을 뿐 실행은 계속된다
    return proc.stdout if proc.returncode == 0 else None


def _changed(root: str, base: str) -> list[str]:
    """base 대비 달라진 경로 + 추적되지 않은 새 파일."""
    out: set[str] = set()
    for args in (["diff", "--name-only", base], ["ls-files", "--others", "--exclude-standard"]):
        raw = _git(root, args)
        out.update(line.strip() for line in (raw or "").splitlines() if line.strip())
    return sorted(out)


def _at_base(root: str, rel: str, base: str) -> str | None:
    """base 시점의 본문. 그때 없던 파일이면 None."""
    return _git(root, ["show", f"{base}:{rel}"], 20)


def _normalise(paths: object) -> list[str]:
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return []
    return sorted({rel for raw in paths if (rel := str(raw).strip().replace(os.sep, "/"))})


# ── 이번 변경에서 새로 생기거나 바뀐 단위 ──────────────────────────


def _scan(root: str, base: str, targets: list[str]) -> tuple[dict[str, tuple[str, dict, dict]], list[tuple[str, str]]]:
    """경로 → (현재 본문, 현재 단위표, base 단위표). 못 읽은 자리는 gaps 로 나간다."""
    seen: dict[str, tuple[str, dict, dict]] = {}
    gaps: list[tuple[str, str]] = []
    for rel in targets:
        text = _read(root, rel)
        if text is None:
            # 기준에는 있고 지금 없는 파일은 "못 읽은 파일"이 아니라 삭제된 파일이다. 삭제와 이동은
            # tutor 인벤토리가 맡고, 현재 실행 흐름에는 넣을 본문이 없으므로 여기서는 조용히 뺀다.
            if _at_base(root, rel, base) is not None:
                continue
            gaps.append((rel, "파일을 읽지 못해서 읽는 순서에 못 넣었어요"))
            continue
        now = tutor_probes.units_of(text, rel)
        if now is None:
            if not rel.lower().endswith(_DOC_SUFFIXES) and os.path.basename(rel) not in _DOC_NAMES:
                gaps.append((rel, "코드 단위를 읽지 못해서 읽는 순서에 못 넣었어요"))
            continue
        before = _at_base(root, rel, base)
        old = (tutor_probes.units_of(before, rel) or {}) if before is not None else {}
        seen[rel] = (text, now, old)
    return (seen, gaps)


def _shape(unit: object) -> tuple[int, int, int]:
    """단위의 형상. 줄 위치가 밀린 것은 변경이 아니라서 줄 번호를 안 넣는다."""
    return (int(getattr(unit, "lines", 0)), int(getattr(unit, "depth", 0)), int(getattr(unit, "stmts", 0)))


def _nodes(seen: dict[str, tuple[str, dict, dict]]) -> dict[_Key, _Node]:
    """새로 생겼거나 본문이 바뀐 단위만. 자리가 밀리기만 한 단위는 이번 변경이 아니다."""
    out: dict[_Key, _Node] = {}
    for rel, (text, now, old) in seen.items():
        python = rel.endswith(".py")
        docs = _doclines(text) if python else {}
        for name, unit in now.items():
            prior = old.get(name)
            if prior is None:
                what = f"새로 생긴 단위예요 ({getattr(unit, 'lines', 0)}행)"
            elif _shape(prior) != _shape(unit):
                what = f"본문이 바뀐 단위예요 ({getattr(prior, 'lines', 0)}행 → {getattr(unit, 'lines', 0)}행)"
            else:
                continue
            out[(rel, name)] = _Node(rel, int(getattr(unit, "line", 1)), name, what, python, docs.get(name, ""))
    return out


def _edges(
    seen: dict[str, tuple[str, dict, dict]], nodes: dict[_Key, _Node]
) -> tuple[set[tuple[_Key, _Key]], list[tuple[str, str]]]:
    """이 변경 **안에서의** 호출 간선과, 세면서 못 센 자리.

    이름으로 부르는 호출(`run()`)만 센다. 속성 호출(`dev.run()`·`self.run()`)은 수신자가 무엇인지
    이 층이 모르므로 안 센다 — `dev`가 남의 객체면 그 `run` 단위는 여기 있는 것이 아니고, 그래도
    간선을 놓으면 화면에 없는 호출 관계가 사실로 나간다. 오탐 하나가 읽는 순서 전체의 값을 깎는다.

    같은 이름의 단위가 **여러 파일에** 있으면 이름만으로는 어느 쪽인지 못 정하므로 그때도 간선을
    안 놓는다. 파일 경계로 자르지 않는 이유는 그 반대쪽이다 — 이름이 한 자리뿐이면 교차 파일
    호출(`from x import foo`)도 이어야 하고, 파일로 자르면 그 간선이 같이 죽는다.

    못 놓은 간선 둘 다 돌려준다(계약 ⑤). 속성 호출은 **이 변경의 단위 이름과 겹치는 것**만 파일마다
    세고, 겹치지 않는 호출까지 세면 그 목록이 소음이 된다.
    """
    by_name: dict[str, set[_Key]] = {}
    for key in nodes:
        by_name.setdefault(key[1].rsplit(".", 1)[-1], set()).add(key)
    twins = {name for name, keys in by_name.items() if len({key[0] for key in keys}) > 1}
    out: set[tuple[_Key, _Key]] = set()
    missed: dict[str, int] = {}
    unsure: set[str] = set()
    for rel, (text, now, _) in seen.items():
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError, ValueError, RecursionError:
            continue  # _scan 이 이미 단위를 읽은 본문이라 드물다 — 간선만 빠지고 자리는 남는다
        spans = sorted(
            ((int(getattr(u, "line", 1)), int(getattr(u, "end", 1)), name) for name, u in now.items()),
            key=lambda row: row[1] - row[0],
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            caller = _owner(spans, getattr(node, "lineno", 0))
            if not caller or (rel, caller) not in nodes:
                continue
            func = node.func
            if isinstance(func, ast.Name):
                called = func.id
            elif isinstance(func, ast.Attribute):
                called = func.attr
            else:
                continue
            hits = {target for target in by_name.get(called, ()) if target != (rel, caller)}
            if not hits:
                continue
            if isinstance(func, ast.Attribute):
                missed[rel] = missed.get(rel, 0) + 1
                continue
            if called in twins:
                unsure.add(called)
                continue
            out.update(((rel, caller), target) for target in hits)
    gaps = [
        (rel, f"속성 호출 {count}곳은 수신자를 몰라서 호출 관계에서 뺐어요") for rel, count in sorted(missed.items())
    ]
    gaps += [
        (
            " · ".join(sorted({key[0] for key in by_name[name]})) + f" {name}",
            "이름이 같은 단위가 여러 파일에 있어서 어느 쪽을 부르는지 못 정하고 호출 관계에서 뺐어요",
        )
        for name in sorted(unsure)
    ]
    return (out, gaps)


def _owner(spans: list[tuple[int, int, str]], line: int) -> str:
    """그 줄을 품은 가장 안쪽 단위 이름. 모듈 스코프면 빈 문자열."""
    for start, end, name in spans:
        if start <= line <= end:
            return name
    return ""


def _order(nodes: dict[_Key, _Node], edges: set[tuple[_Key, _Key]]) -> list[_Key]:
    """부르는 쪽이 먼저 오는 순서. 순환이 남으면 `(path, line)`으로 안정 정렬해 그대로 놓는다."""
    left = {key: 0 for key in nodes}
    for _, callee in edges:
        if callee in left:
            left[callee] += 1

    def coord(key: _Key) -> tuple[str, int, str]:
        return (nodes[key].path, nodes[key].line, key[1])

    out: list[_Key] = []
    while left:
        ready = [key for key, count in left.items() if count == 0]
        if not ready:
            out.extend(sorted(left, key=coord))
            break
        key = min(ready, key=coord)
        out.append(key)
        left.pop(key)
        for caller, callee in edges:
            if caller == key and callee in left:
                left[callee] -= 1
    return out


def _flow_order(nodes: dict[_Key, _Node], edges: set[tuple[_Key, _Key]]) -> tuple[list[_Key], tuple[int, ...]]:
    """호출 관계로 이어진 묶음을 큰 것부터 놓고, 각 묶음 안에서는 호출자가 먼저 오게 한다.

    전역 위상 정렬은 서로 무관한 흐름을 경로 이름순으로 섞는다. 그러면 카드의 첫 세 자리가 한
    실행 흐름이 아니라 세 파일의 시작점이 된다. 묶음은 설명용일 뿐이라 방향을 버린 연결 성분으로
    만들고, 실제 읽는 순서는 기존 위상 정렬을 그대로 쓴다.
    """
    ordered = _order(nodes, edges)
    neighbours = {key: set() for key in nodes}
    for left, right in edges:
        if left in neighbours and right in neighbours:
            neighbours[left].add(right)
            neighbours[right].add(left)
    components: list[set[_Key]] = []
    remaining = set(nodes)
    while remaining:
        seed = min(remaining, key=lambda key: (nodes[key].path, nodes[key].line, key[1]))
        component, stack = set(), [seed]
        while stack:
            key = stack.pop()
            if key in component:
                continue
            component.add(key)
            stack.extend(neighbours[key] - component)
        remaining -= component
        components.append(component)
    components.sort(
        key=lambda group: (
            -len(group),
            min((nodes[key].path, nodes[key].line, key[1]) for key in group),
        )
    )
    grouped = [key for group in components for key in ordered if key in group]
    return (grouped, tuple(len(group) for group in components))


def _area(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    if parts[:1] == ["src"] and len(parts) >= 3:
        return "/".join(parts[:3])
    return parts[0] if parts and parts[0] else "(root)"


def _overview(targets: list[str], total: int, flows: int) -> str:
    """의도를 만들지 않고도 먼저 줄 수 있는 시스템 배경 — 경로와 호출 관계만 쓴다."""
    areas = Counter(_area(rel) for rel in targets)
    scope = " · ".join(f"`{name}` {count}개 파일" for name, count in areas.most_common(2))
    if not total:
        return (scope + "에서 " if scope else "") + "현재 읽을 코드 단위는 없어요."
    prefix = (scope + "에 걸친 " if scope else "") + f"변경 단위 {total}곳"
    return prefix + f"을 호출 관계 기준 {max(1, flows)}개 흐름으로 나눴어요."


def _why_here(key: _Key, node: _Node, nodes: dict[_Key, _Node], edges: set[tuple[_Key, _Key]]) -> str:
    """왜 이 차례인가 — 이 변경 안의 호출 관계만 적는다. 의도는 여기서 안 만든다(계약 ②).

    "무엇을 부르나"와 "누가 부르나"는 **다른 사실이라 문장을 나눈다**. 실측으로 잡힌 자리다:
    둘을 `·`로 이으면 앞 문장의 이름 목록과 뒤 문장이 한 목록으로 읽혀서, 부르는 쪽 이름이
    불리는 쪽 목록에 섞인 것처럼 보인다(`_texts · 이 변경 안에서 여기를 부르는 자리 — main`).
    `·`는 같은 종류의 항목만 잇는 글리프다.
    """
    calls = sorted({nodes[c].unit for a, c in edges if a == key and c in nodes})
    called_by = sorted({nodes[a].unit for a, c in edges if c == key and a in nodes})
    parts = []
    if calls:
        parts.append("이 변경 안에서 이 자리가 부르는 곳 — " + _names(calls))
    if called_by:
        parts.append(("" if calls else "이 변경 안에서 ") + "이 자리를 부르는 곳 — " + _names(called_by))
    if parts:
        return ". ".join(parts)
    if not node.python:
        return "호출 관계를 못 읽는 언어라 좌표 순서로 놓았어요"
    return "이 변경 안에서는 호출 관계가 안 보여요"


def _names(units: list[str]) -> str:
    return " · ".join(f"`{name}`" for name in units)


# ── 새로 들어온 말 ─────────────────────────────────────────────────


def _own_names(root: str) -> frozenset[str]:
    """이 저장소가 자기 이름으로 쓰는 top-level 패키지 — 자기 나무를 외부 의존이라 부르지 않는다.

    `tutor._own_names`와 같은 판정이지만 그 함수를 부르지 않는다. `tutor`는 적용 등급이고 여기는
    판정 등급이라, 부르면 방향이 거꾸로 선다(`tests/architecture/test_layered.py`가 잡는다).
    """
    names = {os.path.basename(root.rstrip("/\\")), "tests", "test"}
    for parent in (root, os.path.join(root, "src")):
        try:
            entries = os.listdir(parent)
        except OSError:
            continue
        for entry in entries:
            path = os.path.join(parent, entry)
            if entry.startswith(".") or not os.path.isdir(path):
                continue
            if parent.endswith("src") or os.path.exists(os.path.join(path, "__init__.py")):
                names.add(entry)
    return frozenset(names)


def _doclines(text: str) -> dict[str, str]:
    """단위 이름 → 그 단위의 docstring 첫 문장. 없는 단위는 표에서 빠진다 — 지어내지 않는다.

    이름은 `tutor_probes.units_of`가 쓰는 것과 같은 점 이어붙인 이름(`Class.method`)이다. 한
    파일을 한 번만 훑는 이유는 값이다: 이 층은 턴마다 돌고 한 변경이 단위 백 개를 넘길 수 있어서,
    단위마다 파일을 다시 파싱하면 그 비용이 설명 하나의 값을 넘는다.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError, ValueError, RecursionError:
        return {}
    out: dict[str, str] = {}

    def visit(node: ast.AST, prefix: tuple[str, ...] = ()) -> None:
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, prefix)
                continue
            name = prefix + (child.name,)
            head = _first_sentence(ast.get_docstring(child) or "")
            if head:
                out[".".join(name)] = head
            visit(child, name)

    visit(tree)
    return out


def _first_sentence(body: str) -> str:
    """docstring 의 첫 문장. 여러 줄 요약은 첫 줄에서 끊는다 — 카드 한 줄에 들어가야 한다."""
    head = (body.strip().splitlines() or [""])[0].strip()
    cut = head.find(". ")
    return (head[: cut + 1] if cut > 0 else head)[:120]


def _docline(text: str, name: str) -> str:
    """한 단위의 docstring 첫 문장. `_doclines`가 정본이고 여기는 한 이름만 꺼내는 창구다."""
    return _doclines(text).get(name, "")


def _signature(sig: object) -> str:
    params = ", ".join(getattr(sig, "params", ()) or ())
    returns = str(getattr(sig, "returns", "") or "")
    name = str(getattr(sig, "qualname", "") or "")
    return f"{name}({params})" + (f" -> {returns}" if returns else "")


def _symbol_terms(
    root: str, base: str, scope: set[str], seen: dict
) -> tuple[list[Term], list[tuple[str, str]], list[str]]:
    """새 공개 심볼 → (용어, 못 본 자리, 심볼 이름). 좌표를 못 만든 심볼은 용어로 안 만든다(계약 ①).

    표면 대조는 `scope` 안에서만 돌린다. 아래에서 쓰는 것은 전부 `path in scope` 로 거른 뒤라
    나무 전체를 대조하면 그 결과를 버리려고 파일마다 `git show` 를 부르는 꼴이 된다. 호출부
    후보(`obligations`)도 여기서는 안 읽으므로 끄고 부른다 — 켜면 나무의 .py 를 전부 연다.
    """
    try:
        diff = surface.diff(root, base, with_candidates=False, scope=tuple(sorted(scope)))
    except Exception:
        return ([], [("(public surface)", "표면 대조를 돌리지 못해서 새 심볼을 못 봤어요")], [])
    gaps = [(path, "구문을 못 읽어서 표면 대조에서 빠졌어요") for path in diff.unparsed if path in scope]
    gaps.extend(_unstaged_gaps(scope, seen, set(diff.paths)))
    terms: list[Term] = []
    names: list[str] = []
    docs: dict[str, dict[str, str]] = {}  # 경로마다 한 번만 파싱한다 (`_doclines` 와 같은 이유)
    for change in diff.changes:
        if change.kind != "added" or change.path not in scope:
            continue
        names.append(change.qualname)
        row = seen.get(change.path)
        unit = row[1].get(change.qualname) if row else None
        if row is None or unit is None:
            gaps.append((f"{change.path} {change.qualname}", "심볼의 줄 번호를 못 찾아서 용어로 안 만들었어요"))
            continue
        text = row[0]
        if change.path not in docs:
            docs[change.path] = _doclines(text)
        gloss, source = docs[change.path].get(change.qualname, ""), "docstring"
        if not gloss:
            sigs = surface.extract(text) or {}
            gloss = _signature(sigs[change.qualname]) if change.qualname in sigs else ""
            source = "signature"
        terms.append(Term(change.qualname, f"{change.path}:{int(getattr(unit, 'line', 1))}", gloss, source))
    return (terms, gaps, names)


def _unstaged_gaps(scope: set[str], seen: dict, tracked: set[str]) -> list[tuple[str, str]]:
    """`surface`는 추적되는 변경만 본다 — 인덱스에 없는 새 파일은 새 심볼도 확인 명령도 못 낸다.

    실측으로 잡힌 자리다: 방금 만든 파일 둘로 `explain`을 돌리면 읽는 순서는 40자리가 나오는데
    용어와 확인 명령이 통째로 0건이었고, 화면 어디에도 그 이유가 없었다. 조용한 0건은 "없다"로
    읽힌다(계약 ⑤).

    `tracked` 는 부르는 쪽이 이미 받아 둔 `SurfaceDiff.paths` 다 — 같은 `git diff` 를 여기서 다시
    부르면 tutor 한 번이 같은 답을 두 번 받으려고 git 프로세스를 하나 더 띄운다.
    """
    return [
        (rel, "`git add` 전이라 표면 대조에서 빠졌어요 — 새 심볼과 확인 명령을 못 만들었어요")
        for rel in sorted(seen)
        if rel.endswith(".py") and rel in scope and rel not in tracked and surface.is_surface_path(rel)
    ]


def _dependency_terms(root: str, base: str, seen: dict) -> list[Term]:
    """이번에 새로 들어온 외부 의존. 자기 패키지와 표준 라이브러리는 뺀다."""
    own = _own_names(root)
    out: list[Term] = []
    for rel, (text, _, _) in sorted(seen.items()):
        if not rel.endswith(".py"):
            continue
        before = _at_base(root, rel, base)
        old = tutor_probes.imports(before) if before is not None else {}
        for name, line in sorted(tutor_probes.imports(text).items()):
            if name in old or name in own:
                continue
            out.append(Term(name, f"{rel}:{line}", "", "dependency"))
    return out


# ── 확인 명령 ──────────────────────────────────────────────────────


def _checks(
    root: str, names: list[str], targets: list[str], scope: list[str]
) -> tuple[tuple[str, ...], list[tuple[str, str]]]:
    """이 변경을 직접 확인하는 한 줄. 못 찾으면 비우고 그 사실을 gaps 에 적는다.

    두 갈래를 합친다. ① **이번에 바뀐 테스트 파일** — 이건 후보가 아니라 사실이다. ② 새 공개
    심볼의 이름이 보이는 테스트 파일(`surface.candidates`). ①이 없으면 바뀐 단위가 전부 비공개인
    변경에서 명령이 0건이 된다 — 정작 그 변경이 테스트 파일을 같이 고쳤는데도 그렇다(실측).
    """
    files = _test_paths(root, targets)
    by_name: set[str] = set()
    gaps: list[tuple[str, str]] = []
    if names:
        try:
            found = surface.candidates(root, names)
        except Exception:
            gaps.append(("(tests)", "테스트 트리를 훑지 못해서 이름으로 찾는 쪽은 빠졌어요"))
        else:
            by_name = _test_paths(root, [path for paths in found.values() for path in paths])
            files |= by_name
    if not files:
        return ((), gaps + [("(tests)", "이 변경을 직접 확인하는 판정을 못 찾았어요")])
    stems = {os.path.basename(rel)[:-3] for rel in scope if rel.endswith(".py") and not tutor_probes.is_test_path(rel)}
    picked = sorted(files, key=lambda rel: (rel not in by_name, not _near(rel, stems), rel))
    if len(picked) > MAX_TEST_FILES:
        gaps.append(("(tests)", f"확인 명령에는 테스트 파일 {MAX_TEST_FILES}개까지만 넣었어요"))
    return ((f"python -m pytest {' '.join(sorted(picked[:MAX_TEST_FILES]))}",), gaps)


def _near(rel: str, stems: set[str]) -> bool:
    """읽고 있는 파일과 이름이 닿는 테스트인가 — `tutor.py` 옆의 `test_tutor_note_hook.py`까지 센다.

    상한을 자를 때 순서가 값을 정한다. 이름순으로만 자르면 이 변경과 무관한 테스트가 앞자리를
    먹고, 정작 이 변경을 확인하는 파일이 잘려 나간다(실측: 같은 트리에서 도는 다른 작업의
    테스트 여섯 개가 창을 다 채웠다).
    """
    stem = os.path.basename(rel)[:-3].removeprefix("test_")
    return any(stem.startswith(other) or other.startswith(stem) for other in stems if other)


def _test_paths(root: str, paths: object) -> set[str]:
    """실제로 단독 수집되는 테스트 모듈만.

    `tests/conftest.py`와 `tests/hookscaffold.py`도 테스트 트리 안에는 있지만 pytest의 실행 대상은
    아니다. 지원 파일을 명령 인자로 넣으면 확인 줄이 길어지고 수집 의미도 달라진다.
    """
    rows = paths if isinstance(paths, (list, tuple, set, frozenset)) else ()
    candidates = {
        rel
        for raw in rows
        if (rel := str(raw).replace(os.sep, "/")).endswith(".py")
        and tutor_probes.is_test_path(rel)
        and (os.path.basename(rel).startswith("test_") or os.path.basename(rel).endswith("_test.py"))
        and os.path.exists(os.path.join(root, rel))
    }
    if not candidates:
        return set()
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=root,
            input="\n".join(sorted(candidates)) + "\n",
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        ignored = {line.strip().replace(os.sep, "/") for line in proc.stdout.splitlines() if line.strip()}
    except OSError, subprocess.SubprocessError:
        ignored = set()  # git 판정이 없으면 존재하는 테스트를 버리지는 않는다
    return candidates - ignored


# ── 임무·용어집 (이 사람의 기록) ───────────────────────────────────


def mission(root: str) -> str:
    """지금 이 사람이 무엇을 익히는 중인가. 안 적어 뒀으면 빈 문자열."""
    return read_text(os.path.join(root, MISSION_REL)).strip()


def set_mission(root: str, text: str) -> str:
    """임무를 적는다. 반환 = 적힌 본문 (못 적었으면 빈 문자열)."""
    body = str(text or "").strip()
    try:
        write_text(os.path.join(root, MISSION_REL), body + "\n" if body else "")
    except OSError:
        return ""  # 기록 실패가 설명을 막지 않는다 — 튜터는 관문이 아니다
    return body


def glossary_known(root: str) -> set[str]:
    """이미 설명한 말. 회차마다 설명이 줄어드는 근거가 이 집합이다(계약 ③)."""
    out: set[str] = set()
    for line in read_text(os.path.join(root, GLOSSARY_REL)).splitlines():
        body = line.strip()
        if not body.startswith("- `"):
            continue
        name = body[3:].split("`", 1)[0].strip()
        if name:
            out.add(name)
    return out


def glossary_merge(root: str, terms: object) -> int:
    """설명한 말을 용어집에 더한다. 반환 = 새로 적은 수 (이미 있던 말은 안 센다)."""
    if not isinstance(terms, (list, tuple, set, frozenset)):
        return 0
    known = glossary_known(root)
    rows = []
    for term in terms:
        name = str(term.get("name", "") if isinstance(term, dict) else getattr(term, "name", "")).strip()
        where = str(term.get("where", "") if isinstance(term, dict) else getattr(term, "where", "")).strip()
        gloss = str(term.get("gloss", "") if isinstance(term, dict) else getattr(term, "gloss", "")).strip()
        if not name or name in known:
            continue
        known.add(name)
        rows.append(f"- `{name}` — {where}" + (f" — {gloss}" if gloss else ""))
    if not rows:
        return 0
    path = os.path.join(root, GLOSSARY_REL)
    body = read_text(path)
    head = body if body.endswith("\n") or not body else body + "\n"
    try:
        write_text(path, head + "\n".join(rows) + "\n")
    except OSError:
        return 0  # 못 적었으면 다음 회차에 같은 말을 한 번 더 설명한다 — 중복이 침묵보다 낫다
    return len(rows)


# ── 깊이 ───────────────────────────────────────────────────────────


def depth_for(root: str, paths: object) -> str:
    """이 자리들을 이 사람이 얼마나 아는가 — 답해서 닫은 물음 수로만 센다.

    0건이면 `first`, 1~2건이면 `familiar`, 3건 이상이면 `owned`다. 오탐으로 닫은 것은 안 센다 —
    "이 물음은 틀렸다"는 그 자리를 이해했다는 뜻이 아니다.
    """
    wanted = _normalise(paths)
    if not wanted:
        return DEPTHS[0]
    try:
        said = tutor_growth.recall(root, wanted, cap=10_000)
    except Exception:
        return DEPTHS[0]
    answered = sum(1 for row in said if not row.dismissed)
    if answered >= OWNED_AT:
        return "owned"
    return "familiar" if answered else "first"


# ── 조립 ───────────────────────────────────────────────────────────


def explain(root: str, base: str = "HEAD", paths: object = (), depth: str = "") -> Explanation:
    """이번 변경의 설명 재료. 지목된 경로가 없으면 base 대비 달라진 전부를 본다."""
    named = _normalise(paths)
    touched = _changed(root, base)
    targets = named or touched
    gaps: list[tuple[str, str]] = []
    if len(targets) > MAX_PATHS:
        gaps.append((f"(+{len(targets) - MAX_PATHS}개)", f"한 번에 {MAX_PATHS}개까지만 읽었어요"))
        targets = targets[:MAX_PATHS]
    seen, read_gaps = _scan(root, base, targets)
    gaps.extend(read_gaps)
    nodes = _nodes(seen)
    edges, edge_gaps = _edges(seen, nodes)
    gaps.extend(edge_gaps)
    keys, component_sizes = _flow_order(nodes, edges)
    total_units = len(keys)
    flow_count = len(component_sizes)
    primary_units = component_sizes[0] if component_sizes else 0
    if len(keys) > MAX_STEPS:
        gaps.append((f"(+{len(keys) - MAX_STEPS}개 단위)", f"읽는 순서는 {MAX_STEPS}자리까지만 만들었어요"))
        keys = keys[:MAX_STEPS]
    steps = tuple(
        Step(
            index,
            nodes[key].path,
            nodes[key].line,
            nodes[key].unit,
            nodes[key].what,
            _why_here(key, nodes[key], nodes, edges),
            nodes[key].does,
        )
        for index, key in enumerate(keys, 1)
    )
    terms, term_gaps, names = _symbol_terms(root, base, set(targets), seen)
    gaps.extend(term_gaps)
    known = glossary_known(root)
    fresh = tuple(t for t in terms + _dependency_terms(root, base, seen) if t.name not in known)
    # 확인 명령만 지목 경로를 안 따른다. "이걸 확인하려면 무엇을 돌리나"는 **이번 변경**의
    # 성질이고, 지목은 읽을 자리를 좁힐 뿐이다 — 훅이 소스 경로만 넘기면 같이 고친 테스트가
    # 화면에서 사라진다(실측: `--path` 둘로 부르면 명령이 0건이었다).
    checks, check_gaps = _checks(root, names, touched or targets, targets)
    # 읽을 자리가 없는 변경에서도 이 줄은 남는다. 확인 명령을 못 찾은 것은 읽는 순서와 무관한
    # 사실이고, 조용히 지우면 "0건"과 "안 봤다"가 같은 화면이 된다(계약 ⑤).
    gaps.extend(check_gaps)
    level = depth if depth in DEPTHS else depth_for(root, targets)
    return Explanation(
        base=base,
        depth=level,
        mission=mission(root),
        steps=steps,
        terms=fresh,
        checks=checks,
        recall=_recall(level, steps, keys, edges, nodes, min(3, primary_units)),
        gaps=tuple(gaps),
        total_units=total_units,
        flow_count=flow_count,
        primary_units=primary_units,
        overview=_overview(targets, total_units, flow_count),
    )


def _recall(
    depth: str,
    steps: tuple[Step, ...],
    keys: list[_Key],
    edges: set[tuple[_Key, _Key]],
    nodes: dict[_Key, _Node],
    visible: int = 3,
) -> tuple[str, ...]:
    """설명 뒤에 놓는 인출 물음 하나. **채점하지 않는다**(`tutor_growth` 계약 ①).

    처음 만나는 자리에서만, 그리고 읽을 자리가 둘 이상일 때만 놓는다. 자리가 하나면 "흐름"이
    없어서 인출할 것이 없고, 이미 아는 자리면 인출은 `tutor`의 재방문 사다리가 맡는다.

    묻는 대상은 **읽는 순서에서 가장 먼저 불리는 자리**다. 이름 순으로 고르면 화면에 안 들어간
    자리를 묻게 되고(카드는 앞에서 몇 자리만 편다), 그러면 물음이 도달하지 않는다.
    """
    if depth != "first" or len(steps) < 2:
        return ()
    rank = {key: index for index, key in enumerate(keys)}
    # 카드에 안 보인 단위를 되묻지 않는다. 설명을 받지 못한 것을 인출시키면 그 질문은 학습이
    # 아니라 검색 숙제가 된다.
    called = sorted((rank[c] for a, c in edges if a in rank and c in rank and rank[a] < visible and rank[c] < visible))
    if called:
        name = nodes[keys[called[0]]].unit
        return (f"방금 본 흐름에서 `{name}` 단위를 부르는 자리는 어디였나요?",)
    return ("방금 본 흐름에서 가장 먼저 읽는 자리는 어디였나요?",)


# ── 화면 ───────────────────────────────────────────────────────────


def shown_terms(exp: Explanation, limit: int = 3) -> tuple[Term, ...]:
    """이 깊이·이 상한에서 카드에 **실제로 실리는** 말. `card`가 그리는 목록 그 자체다.

    적립하는 쪽(`commands/tutor.py`의 `_learned`, `tutor._explained`)이 이 목록만 용어집에 넣는다.
    화면에 없던 말을 적립하면 그 말은 다음 회차부터 `explain`의 용어집 필터에서 빠지고, 사람은 한
    번도 설명을 못 받은 채로 "이미 설명한 말" 취급을 받는다. 가장자리가 아니다 — `depth_for`는 답
    3건이면 `owned`로 올리고 그 깊이의 카드는 좌표뿐이라, 사다리가 익을수록 도달하는 자리가 바로
    이 구간이다. 물음 쪽이 `tutor.hand_back`에서 이미 정해 둔 규칙과 같다.
    """
    if exp.depth != "first" or not exp.terms:
        return ()
    return exp.terms[: max(0, limit)]


def card(exp: Explanation, limit: int = 3, quiz: bool = True) -> str:
    """설명 카드. 깊이가 올라갈수록 줄어든다(계약 ④). 실을 것이 없으면 빈 문자열.

    `gaps`만 남은 회차도 빈 카드다. 못 본 것은 계속 `gaps`에 남지만(계약 ⑤) 그것 하나로 카드를
    내면 "읽을 자리 0곳" 두 줄이 턴마다 나가고, 빈 카드는 다음 카드의 신뢰를 깎는다
    (`tutor.turn_note`가 같은 판정을 한다). 그 줄은 `--explain`과 보고서가 받는다.
    """
    if not exp.steps and not exp.terms and not exp.checks:
        return ""
    if exp.depth == "owned":
        where = " · ".join(f"{s.where} {s.unit}".strip() for s in exp.steps[:limit])
        return f"⠶ 설명 — {where}" if where else ""
    headline = exp.overview or _fallback_overview(exp)
    lines = [f"⠶ 설명 — {headline}"]
    if exp.depth == "first" and exp.mission:
        lines.append("  임무 — " + " ".join(exp.mission.split())[:120])
    shown = shown_steps(exp, limit)
    if shown:
        lines.append(f"  먼저 읽을 흐름 — {len(shown)}곳")
        lines.extend(_card_steps(shown))
        if (exp.total_units or len(exp.steps)) > len(shown):
            lines.append("  나머지 흐름은 보고서에 접어 뒀어요.")
    if exp.depth != "first":
        return "\n".join(lines)
    lines.extend(_card_terms(shown_terms(exp, limit), len(exp.terms)))
    for check in exp.checks:
        lines.append(f"  확인 — {check}")
    if quiz:
        for ask in exp.recall:
            lines.append(f"    ▸ {ask}")
    for where, why in exp.gaps[:limit]:
        lines.append(f"  못 본 것 — {where}: {why}")
    return "\n".join(lines)


def shown_steps(exp: Explanation, limit: int = 3) -> tuple[Step, ...]:
    """카드가 실제로 펼칠 한 호출 흐름. 다음 연결 성분으로 넘어가 목록을 섞지 않는다."""
    cap = min(max(0, limit), exp.primary_units or len(exp.steps))
    return exp.steps[:cap]


def _fallback_overview(exp: Explanation) -> str:
    total = exp.total_units or len(exp.steps)
    if not total:
        return "현재 읽을 코드 단위는 없어요."
    flows = exp.flow_count or 1
    return f"변경 단위 {total}곳을 호출 관계 기준 {flows}개 흐름으로 나눴어요."


def _card_steps(steps: tuple[Step, ...]) -> list[str]:
    """한 자리는 최대 두 줄이다. 첫 줄은 **그 단위가 무엇을 하는가**, 둘째 줄이 이번에 무엇이 바뀌었나다.

    순서가 이렇게 선 이유는 이 층이 무엇을 위한 것인가에 있다. 줄 수 증감(`57행 → 67행`)은 그
    단위를 이미 아는 사람에게만 뜻이 있고, 처음 보는 사람에게는 좌표 하나가 더 늘어난 것뿐이다.
    docstring 이 없으면 첫 줄도 종전 그대로 한 줄로 돌아간다 — 없는 설명을 지어내지 않는다.
    """
    lines: list[str] = []
    for step in steps:
        head = f"  {step.order}. {step.where} {step.unit}"
        if step.does:
            lines.append(f"{head} — {step.does}")
            lines.append(f"     {step.what} · {step.why_here}")
        else:
            lines.append(f"{head} — {step.what} · {step.why_here}")
    return lines


def _card_terms(shown: tuple[Term, ...], total: int) -> list[str]:
    """실리는 말은 `shown_terms`가 이미 골랐다 — 여기서 다시 자르면 규칙이 두 벌이 된다."""
    if not shown:
        return []
    lines = ["  새로 들어온 말"]
    for term in shown:
        lines.append(f"    `{term.name}` — {term.where}" + (f" — {term.gloss}" if term.gloss else ""))
    if total > len(shown):
        lines.append("    나머지 말은 보고서에 접어 뒀어요.")
    return lines
