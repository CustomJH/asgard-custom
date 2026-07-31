"""surface — 공개 표면(심볼·시그니처)의 추출과 기준 대조. 결정론 계층: LLM·네트워크 없음.

**왜 이 모듈이 있는가.** 계획 사슬에 한 층이 비어 있었다: 정의 → 스펙/형상 → 배정 단위(파일+
기준) → 구현. 스펙과 코드 사이, **어떤 타입·시그니처·경계를 새로 만들 것인지 미리 고정하는
단계**가 없었다. 업계가 이 층에 수렴한 근거는 두 갈래다:

- 스펙 주도 개발 도구들이 전부 spec → **design** → tasks → implement로 같은 층을 세운다
  (GitHub Spec Kit의 Specify/Plan/Tasks/Implement, Kiro의 spec/design/tasks/impl). 설계를
  앞으로 당기면 깨진 인터페이스와 재작업이 줄어든다는 것이 그들의 주장이다.
- CodePlan (Microsoft Research, arXiv 2309.12499, ACM PACMSE)은 리포 규모 변경을 **계획
  문제**로 두고, 의존 그래프 + 변경 may-impact 분석으로 "이 편집 다음에 반드시 처리해야 하는
  편집 의무(edit obligation)"의 그래프를 만든다. 모델의 기억이 아니라 그래프가 후속 편집을
  지정한다는 것이 핵심이다.

우리에게 없던 것은 그 **기계적 사실**이다. `asgard-verifier.md`는 바뀐 공개 심볼의 호출부를
전수 대조하라고 요구하지만, 그 목록을 만드는 일이 모델의 손 grep에 맡겨져 있었다 — 심볼
하나를 빠뜨리면 그대로 통과한다. 이 모듈은 그 목록을 결정론으로 만든다.

**사정거리와 한계.** Python만 정밀하다(AST). 호출부 후보는 **이름 기반**이므로 동적 디스패치·
getattr·문자열 참조는 잡지 못하고, 같은 이름의 남의 심볼을 잡을 수 있다 — 그래서 산출물의
이름은 `candidates` 이고 "전수 증명"이라고 말하지 않는다. 판정은 사람·판정자 몫이다.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from dataclasses import dataclass, field

_SKIP_PARAMS = frozenset({"self", "cls"})
_MAX_CANDIDATE_FILES = 40
_MAX_SOURCE_BYTES = 512 * 1024
# 호출부 후보에서 뺄 영역 — 남의 나무와 산출물
_IGNORED_DIRS = frozenset(
    {".asgard", ".git", ".venv", "__pycache__", "build", "dist", "node_modules", "target", "vendor", "venv"}
)
# 표면을 **뜨지 않을** 영역. 테스트·벤치의 심볼은 아무도 호출하는 계약이 아니다 — 테스트 메서드
# 하나를 지운 것이 `removed`(breaking)로 올라오면 판정자는 가짜 편집 의무를 받는다. 반대로
# 호출부 **후보**에서는 빼지 않는다: 바뀐 함수를 부르는 테스트는 진짜 고쳐야 할 곳이다.
# `testing`·`bench`는 진짜 패키지 이름으로도 쓰여서(pandas.testing) 넣지 않는다 — 표면을 조용히
# 빠뜨리는 쪽이 가짜 의무보다 나쁘다. 관례가 확실한 이름만 건다.
_NON_SURFACE_DIRS = frozenset({"benchmarks", "test", "tests"})


@dataclass(frozen=True)
class Sig:
    """공개 심볼 1개의 계약면. 비교 가능한 값들만 담는다 — 본문은 표면이 아니다."""

    qualname: str
    kind: str  # "function" | "class" | "method"
    params: tuple[str, ...] = ()  # positional-or-keyword, 선언 순서
    required: tuple[str, ...] = ()  # 기본값 없는 것
    kwonly: tuple[str, ...] = ()
    kwonly_required: tuple[str, ...] = ()
    vararg: bool = False
    kwarg: bool = False
    returns: str = ""


@dataclass(frozen=True)
class Change:
    """표면 변화 1건. `breaking`은 **호출부 관점** — 호출부가 그대로면 깨지는지를 말한다."""

    path: str
    qualname: str
    kind: str  # 변화 종류
    breaking: bool
    detail: str


@dataclass(frozen=True)
class SurfaceDiff:
    base: str
    changes: tuple[Change, ...] = ()
    files_compared: int = 0
    unparsed: tuple[str, ...] = ()  # 파싱 실패 — 미판정으로 명기 (fail-closed)
    obligations: dict[str, tuple[str, ...]] = field(default_factory=dict)  # qualname → 호출부 후보

    @property
    def breaking(self) -> tuple[Change, ...]:
        return tuple(c for c in self.changes if c.breaking)


def _public(name: str) -> bool:
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def _annotation(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


def _sig(node: ast.FunctionDef | ast.AsyncFunctionDef, qualname: str, kind: str) -> Sig:
    a = node.args
    pos = [p.arg for p in (*a.posonlyargs, *a.args) if p.arg not in _SKIP_PARAMS]
    # 기본값은 뒤에서부터 채워진다 — 앞쪽 len(pos)-len(defaults) 개가 필수
    n_defaults = len(a.defaults)
    all_pos = [p.arg for p in (*a.posonlyargs, *a.args)]
    required = [name for name in all_pos[: len(all_pos) - n_defaults] if name not in _SKIP_PARAMS]
    kwonly = [p.arg for p in a.kwonlyargs]
    kwonly_required = [p.arg for p, d in zip(a.kwonlyargs, a.kw_defaults) if d is None]
    return Sig(
        qualname=qualname,
        kind=kind,
        params=tuple(pos),
        required=tuple(required),
        kwonly=tuple(kwonly),
        kwonly_required=tuple(kwonly_required),
        vararg=a.vararg is not None,
        kwarg=a.kwarg is not None,
        returns=_annotation(node.returns),
    )


def extract(text: str) -> dict[str, Sig] | None:
    """모듈 소스 → {qualname: Sig}. 공개 심볼만. 파싱 실패는 None (0 개와 구분한다)."""
    try:
        tree = ast.parse(text)
    except SyntaxError, ValueError, RecursionError:
        return None
    out: dict[str, Sig] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _public(node.name):
            out[node.name] = _sig(node, node.name, "function")
        elif isinstance(node, ast.ClassDef) and _public(node.name):
            out[node.name] = Sig(qualname=node.name, kind="class")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and _public(item.name):
                    qual = f"{node.name}.{item.name}"
                    out[qual] = _sig(item, qual, "method")
    return out


def _compare(path: str, before: dict[str, Sig], after: dict[str, Sig]) -> list[Change]:
    """두 표면 지도의 차이를 호출부 관점으로 분류한다."""
    changes: list[Change] = []
    for name in sorted(set(before) - set(after)):
        changes.append(Change(path, name, "removed", True, f"{before[name].kind} disappeared from the public surface"))
    for name in sorted(set(after) - set(before)):
        changes.append(Change(path, name, "added", False, f"new public {after[name].kind}"))
    for name in sorted(set(before) & set(after)):
        old, new = before[name], after[name]
        if old.kind != new.kind:
            changes.append(Change(path, name, "kind_changed", True, f"{old.kind} → {new.kind}"))
            continue
        if old.kind == "class":
            continue  # 클래스 자체는 이름·종류만 표면 (메서드는 따로 잡힌다)
        gone = [p for p in old.params if p not in new.params]
        fresh = [p for p in new.params if p not in old.params]
        if gone and fresh and len(gone) == len(fresh):
            changes.append(
                Change(path, name, "param_renamed", True, f"{', '.join(gone)} → {', '.join(fresh)} (keyword callers)")
            )
        else:
            if gone:
                changes.append(Change(path, name, "param_removed", True, f"dropped: {', '.join(gone)}"))
            newly_required = [p for p in fresh if p in new.required]
            if newly_required:
                changes.append(
                    Change(path, name, "required_param_added", True, f"now required: {', '.join(newly_required)}")
                )
            optional = [p for p in fresh if p not in new.required]
            if optional:
                changes.append(Change(path, name, "optional_param_added", False, f"added: {', '.join(optional)}"))
        promoted = [p for p in new.required if p in old.params and p not in old.required]
        if promoted:
            changes.append(Change(path, name, "default_removed", True, f"no longer optional: {', '.join(promoted)}"))
        newly_kwonly_required = [p for p in new.kwonly_required if p not in old.kwonly_required]
        if newly_kwonly_required:
            changes.append(
                Change(
                    path,
                    name,
                    "required_kwonly_added",
                    True,
                    f"now required keyword: {', '.join(newly_kwonly_required)}",
                )
            )
        gone_kwonly = [p for p in old.kwonly if p not in new.kwonly]
        if gone_kwonly:
            changes.append(Change(path, name, "kwonly_removed", True, f"dropped keyword: {', '.join(gone_kwonly)}"))
        # 새 **선택** 키워드는 깨뜨리지 않지만 표면 변화다 — 안 실으면 시그니처의 절반이 조용히 빠진다
        fresh_kwonly = [p for p in new.kwonly if p not in old.kwonly and p not in new.kwonly_required]
        if fresh_kwonly:
            changes.append(
                Change(path, name, "optional_kwonly_added", False, f"added keyword: {', '.join(fresh_kwonly)}")
            )
        if old.returns != new.returns:
            changes.append(
                Change(
                    path,
                    name,
                    "return_changed",
                    False,
                    f"return {old.returns or '(none)'} → {new.returns or '(none)'} — check consumers of the value",
                )
            )
    return changes


def _git(root: str, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        return (proc.returncode, proc.stdout)
    except OSError, subprocess.SubprocessError:
        return (1, "")


def is_surface_path(path: str) -> bool:
    """이 파일의 심볼을 공개 표면으로 셀지. 테스트·벤치·산출물 트리는 표면이 아니다."""
    parts = path.split("/")
    if any(part in _NON_SURFACE_DIRS or part in _IGNORED_DIRS for part in parts[:-1]):
        return False
    name = parts[-1]
    return not (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py")


def changed_python(root: str, base: str) -> tuple[str, ...]:
    """기준 대비 변경·추가·삭제된 **표면** .py 목록 (rename은 양쪽 경로로 나온다)."""
    code, out = _git(root, "diff", "--name-only", base, "--", "*.py")
    if code != 0:
        return ()
    found = {line.strip() for line in out.splitlines() if line.strip().endswith(".py")}
    return tuple(sorted(path for path in found if is_surface_path(path)))


def _at_ref(root: str, base: str, path: str) -> str | None:
    """기준 시점의 파일 내용. 그 시점에 없던 파일이면 None (= 신규 파일)."""
    code, out = _git(root, "show", f"{base}:{path}")
    return out if code == 0 else None


def _worktree(root: str, path: str) -> str | None:
    full = os.path.join(root, path)
    try:
        if os.path.getsize(full) > _MAX_SOURCE_BYTES:
            return None
        with open(full, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _identifiers(qualnames: object) -> tuple[str, ...]:
    """qualname 집합 → 검색할 말단 식별자. `Class.method`는 `method`로 찾는다."""
    if not isinstance(qualnames, (list, tuple, set, frozenset)):
        return ()
    return tuple(sorted({str(q).rsplit(".", 1)[-1] for q in qualnames if str(q).strip()}))


def candidates(root: str, qualnames: object, exclude: object = ()) -> dict[str, tuple[str, ...]]:
    """이름 기반 호출부 후보 — {말단 식별자: (파일,...)}. 전수 증명이 아니라 **후보 목록**이다.

    동적 디스패치·getattr·문자열 참조는 잡지 못하고, 동명이인을 잡을 수 있다. 그래서 판정자는
    이 목록을 grep 대체가 아니라 **빠뜨림 방지용 하한**으로 쓴다 (0건도 기록할 증거다).
    """
    names = _identifiers(qualnames)
    if not names:
        return {}
    skip = {str(p) for p in exclude} if isinstance(exclude, (list, tuple, set, frozenset)) else set()
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b")
    hits: dict[str, set[str]] = {name: set() for name in names}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRS and not d.startswith("."))
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, filename), root).replace(os.sep, "/")
            if rel in skip:
                continue
            text = _worktree(root, rel)
            if text is None:
                continue
            for match in set(pattern.findall(text)):
                hits[match].add(rel)
    return {name: tuple(sorted(paths)[:_MAX_CANDIDATE_FILES]) for name, paths in hits.items() if paths}


def diff(root: str, base: str = "HEAD", *, with_candidates: bool = True) -> SurfaceDiff:
    """기준 대비 공개 표면 변화 + 각 파괴적 변화의 호출부 후보.

    변경된 .py만 대조한다 — 나무 전체 표면을 뜨는 것은 이 질문에 필요하지 않다.
    """
    paths = changed_python(root, base)
    changes: list[Change] = []
    unparsed: list[str] = []
    compared = 0
    for path in paths:
        old_text = _at_ref(root, base, path)
        new_text = _worktree(root, path)
        old = extract(old_text) if old_text is not None else {}
        new = extract(new_text) if new_text is not None else {}
        if old is None or new is None:
            unparsed.append(path)
            continue
        compared += 1
        changes.extend(_compare(path, old, new))
    obligations: dict[str, tuple[str, ...]] = {}
    if with_candidates:
        breaking = [c for c in changes if c.breaking]
        found = candidates(root, [c.qualname for c in breaking], exclude={c.path for c in breaking})
        obligations = {name: files for name, files in found.items()}
    return SurfaceDiff(
        base=base,
        changes=tuple(changes),
        files_compared=compared,
        unparsed=tuple(unparsed),
        obligations=obligations,
    )


def note(root: str, base: str = "HEAD") -> str:
    """판정자·구현자 프롬프트에 실을 블록. 변화가 없으면 빈 문자열 (토큰 회귀 없음).

    이 블록은 grep을 **면제하지 않는다**: 기계가 만든 하한을 주고, 그 위에서 확인하게 한다.
    """
    try:
        result = diff(root, base)
    except Exception:
        return ""
    if not result.changes and not result.unparsed:
        return ""
    lines = ["\n\n## Public surface vs " + result.base + " (harness-computed, deterministic)"]
    breaking = result.breaking
    if breaking:
        lines.append(f"Breaking for callers ({len(breaking)}):")
        for change in breaking[:20]:
            sites = result.obligations.get(change.qualname.rsplit(".", 1)[-1], ())
            where = (
                f" — call-site candidates: {', '.join(sites[:8])}" if sites else " — no name matches outside the diff"
            )
            lines.append(f"- `{change.qualname}` in {change.path}: {change.kind} ({change.detail}){where}")
        lines.append(
            "Each line above is an **edit obligation**: confirm every candidate still works, or state why it is"
            " unaffected. Candidates are name-based — dynamic dispatch, getattr, and string references are not"
            " covered, and same-name symbols from elsewhere may appear. This is a floor for the call-site check,"
            " not a substitute for it."
        )
    non_breaking = [c for c in result.changes if not c.breaking]
    if non_breaking:
        lines.append(
            f"Non-breaking surface changes ({len(non_breaking)}): "
            + ", ".join(f"`{c.qualname}` {c.kind}" for c in non_breaking[:12])
        )
    if result.unparsed:
        lines.append(f"Unparsed (not judged): {', '.join(result.unparsed[:8])}")
    return "\n".join(lines)
