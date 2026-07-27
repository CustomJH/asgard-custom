"""health — 코드베이스 침식 신호. 결정론 계층: LLM·네트워크 없음.

**왜 이 모듈이 있는가.** 에이전트의 판정 리워드는 "테스트 통과"에 걸려 있고, 나쁜 구조의
비용은 몇 달 뒤에 청구된다. 그 간극 때문에 퀘스트 단위 게이트(criteria↔증거)는 전부 초록인데
나무는 조용히 굳어간다 — 판정이 통과시킨 것과 나무가 잃은 것이 다른 축이다. 이 모듈은 그
두 번째 축을 **측정**한다. 막지는 않는다(뒤 "왜 막지 않는가" 참조).

측정 대상은 실증 문헌에서 유지보수 비용·결함률과의 상관이 확인된 지표군으로 제한한다:

- **크기** — god module/god method. Tornhill & Borg, *Code Red* (TechDebt 2022, arXiv 2203.04374)
  의 code health 구성 요소이자 ISO/IEC 5055 유지보수성 항목. 함수 70행은 CodeScene 관례 문턱.
- **중복** — 토큰 정규화 클론 블록. GitClear 의 AI 코드 품질 추적에서 생성형 도입 이후 가장
  뚜렷하게 움직인 신호다(복사·붙여넣기 상승, 리팩터 하락). 에이전트 특유의 침식 형태라
  우리에게 가장 값이 크다.
- **결합** — 모듈 fan-in/fan-out 과 순환. 아키텍처 침식(erosion) 문헌의 표준 계측이며,
  `tests/test_architecture.py` 가 이미 봉인한 *방향* 규칙이 잡지 못하는 *농도*를 잡는다.
- **핫스팟** — 변경 빈도 × 크기. 복잡하면서 자주 바뀌는 파일이 결함 확률이 가장 높다는
  핫스팟 분석의 산출물. 크기 단독보다 수리 우선순위 신호로 낫다.

**왜 막지 않는가.** 절대 문턱으로 차단하면 두 가지가 깨진다. ① 기존 부채가 전부 새 작업의
차단 사유가 되어 Canon 7(범위 존중)과 정면 충돌한다 — 손대지도 않은 큰 파일 때문에 한 줄
수정이 막힌다. ② 침식은 절대값이 아니라 **추세**로 나타나므로, 한 시점의 값은 판정 근거가
못 된다. 그래서 산출물은 스냅샷과 그 사이의 델타이고, 판정은 사람 몫으로 남긴다. 확정된
구조 위반을 기계가 막아야 한다면 그 경로는 이 모듈이 아니라 fitness function(계층 테스트·
lint 규칙)이다 — `asgard-hlidskjalf` 의 봉인 제안이 그 길이다.

**측정 불능은 미측정으로 남긴다** (fail-closed 표기). 함수 단위·결합 지표는 Python 만
정밀하다. 다른 언어 파일은 크기·중복·변경 빈도만 실어 보내고 `unmeasured` 에 센다 —
0 으로 채워 "깨끗하다"로 읽히게 하지 않는다.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field

from . import settings

# ── 관례 문턱. 판정선이 아니라 "세어서 추세로 볼 대상"의 경계다 ──
UNIT_LINES_WARN = 70  # CodeScene 계열 god method 관례
FILE_LINES_WARN = 400
FILE_LINES_SEVERE = 1000
DEPTH_WARN = 4  # 함수 내부 중첩 깊이
CLONE_WINDOW = 6  # 클론 최소 행 수 (jscpd 기본 5행 대비 보수적)
CLONE_MIN_CHARS = 120  # 창 전체 최소 길이 — 짧은 보일러플레이트 오탐 차단 (~50 토큰 대용)
CHURN_COMMITS = 200  # 변경 빈도 관측 창 (커밋 수)
HISTORY_KEEP = 60  # history.jsonl 보존 스냅샷 수
_MAX_SOURCE_BYTES = 512 * 1024
_TOP_N = 10  # 보고에 싣는 상위 항목 수

# 벤더링·산출물·격리 영역 — 우리 나무의 추세가 아니다. code_map._IGNORED_DIRS 와 목적이
# 다르므로(그쪽은 오리엔테이션 맵 범위) 공유하지 않고 여기서 따로 든다.
#
# `skill_plugins` 는 상류에서 이식해 온 스킬 번들이 사는 우리 관례 디렉터리다. 설정 exclude 로
# 빼면 그 설정 파일이 `.asgard/` 째로 gitignore 되는 리포에서는 규칙이 따라가지 않아, 다른
# 클론·CI 가 남의 코드를 우리 추세로 읽는다 (실측: 654파일·중복 14% 대 160파일·5%). 관례
# 이름이므로 기본값으로 든다.
IGNORED_DIRS = frozenset(
    {
        ".asgard",
        "skill_plugins",
        ".git",
        ".hg",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "archive",
        "build",
        "coverage",
        "dist",
        "external",
        "htmlcov",
        "node_modules",
        "output",
        "ref",
        "site-packages",
        "target",
        "third_party",
        "thirdparty",
        "vendor",
        "vendored",
        "venv",
        "workspace",
    }
)
# 함수 단위·결합을 정밀 측정할 수 있는 확장자. 나머지는 크기·중복·변경 빈도만.
_PRECISE_SUFFIX = {".py": "Python"}
_LANG_BY_SUFFIX = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".vue": "Vue",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".sh": "Shell",
}
# 줄 주석 접두 — 블록 주석(/* */, """)은 정규화하지 않는다 (미처리 한계, 중복 지표에 소폭 노이즈)
_LINE_COMMENT = {
    "Python": ("#",),
    "Shell": ("#",),
    "Ruby": ("#",),
    "TypeScript": ("//",),
    "JavaScript": ("//",),
    "Vue": ("//",),
    "Java": ("//",),
    "Kotlin": ("//",),
    "Go": ("//",),
    "Rust": ("//",),
    "PHP": ("//", "#"),
    "C#": ("//",),
    "Swift": ("//",),
    "C": ("//",),
    "C++": ("//",),
}
# 정당하게 반복되는 행 — 중복 지표에서 제외한다 (import 블록을 클론으로 세면 신호가 죽는다)
_REPEAT_OK = ("import ", "from ", "#include", "using ", "require(", "package ", "export ")


@dataclass(frozen=True)
class FileHealth:
    """파일 1개의 침식 지표. `precise=False` 면 unit/depth 는 측정하지 않은 것(0 이 아님)."""

    path: str
    lang: str
    lines: int  # 코드 행 (공백·줄주석 제외)
    total_lines: int
    max_unit_lines: int  # 최장 함수/메서드 행 수
    max_depth: int  # 함수 내부 최대 중첩 깊이
    units: int  # 함수/메서드 개수
    big_units: int  # UNIT_LINES_WARN 초과 함수 수
    churn: int  # 관측 창 안에서 이 파일을 건드린 커밋 수
    dup_lines: int  # 클론 블록에 참여한 코드 행 수
    fan_out: int = 0  # 내부 모듈 의존 수 (precise 만)
    fan_in: int = 0
    precise: bool = False
    test: bool = False


@dataclass(frozen=True)
class Snapshot:
    """한 시점의 나무 상태. 델타 계산이 유일한 소비처라 필드는 전부 스칼라·정렬된 목록이다."""

    commit: str
    files: int
    unmeasured_files: int  # 함수 단위·결합을 측정하지 못한 파일 수
    excluded_files: int  # 설정 exclude glob 에 걸려 빠진 파일 수 (조용한 절단 금지)
    code_lines: int
    test_files: int
    test_code_lines: int
    big_files: int  # FILE_LINES_WARN 초과
    severe_files: int  # FILE_LINES_SEVERE 초과
    big_units: int
    deep_units: int  # DEPTH_WARN 초과 함수를 가진 파일 수
    dup_lines: int  # 소스만 — 테스트 픽스처 반복이 제품 코드 신호를 덮지 않게 분리한다
    dup_share: float  # dup_lines / code_lines
    test_dup_lines: int  # 테스트 쪽 중복 (참고값 — 판정 대상 아님)
    cycles: int  # 내부 import 순환 개수 (강결합 성분 기준)
    max_fan_in: int
    max_fan_out: int
    hotspots: list[dict] = field(default_factory=list)  # [{path, churn, lines, score}]
    largest: list[dict] = field(default_factory=list)  # [{path, lines}]
    worst_units: list[dict] = field(default_factory=list)  # [{path, lines}]
    dup_top: list[dict] = field(default_factory=list)  # [{paths, copies, lines}] — 소스를 포함한 군만
    coupling_top: list[dict] = field(default_factory=list)  # [{path, fan_in, fan_out}]
    langs: dict[str, int] = field(default_factory=dict)
    churn_window: int = CHURN_COMMITS


@dataclass(frozen=True)
class Delta:
    """지표 1개의 추세. `direction` 은 값의 부호가 아니라 **나빠졌는지**를 말한다."""

    metric: str
    before: float
    after: float
    direction: str  # "regressed" | "improved" | "flat"

    @property
    def change(self) -> float:
        return round(self.after - self.before, 4)


@dataclass(frozen=True)
class Trend:
    from_commit: str
    to_commit: str
    deltas: tuple[Delta, ...]

    @property
    def regressed(self) -> tuple[Delta, ...]:
        return tuple(d for d in self.deltas if d.direction == "regressed")


def _excludes(root: str) -> tuple[str, ...]:
    """프로젝트 설정의 추가 제외 glob — 벤더링 번들처럼 기본 디렉터리 이름으로 안 걸리는 영역."""
    raw = settings.section("health", root).get("exclude")
    return tuple(str(p) for p in raw if str(p).strip()) if isinstance(raw, list) else ()


def _is_test(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return (
        any(p in {"test", "tests", "__tests__", "spec"} for p in parts[:-1])
        or name.startswith("test_")
        or name.endswith(("_test.py", "_test.go", ".test.ts", ".test.js", ".spec.ts", ".spec.js"))
    )


def _iter_files(root: str) -> tuple[list[tuple[str, str]], int]:
    """((리포 상대 posix 경로, 언어) 목록, exclude 로 빠진 수). 심볼릭 링크·거대 파일은 뺀다."""
    excludes = _excludes(root)
    out: list[tuple[str, str]] = []
    dropped = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            lang = _LANG_BY_SUFFIX.get(os.path.splitext(name)[1])
            if not lang:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, pat) for pat in excludes):
                dropped += 1
                continue
            if os.path.islink(full):
                continue
            try:
                if os.path.getsize(full) > _MAX_SOURCE_BYTES:
                    continue
            except OSError:
                continue
            out.append((rel, lang))
    return (out, dropped)


def _read(root: str, rel: str) -> str | None:
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _code_lines(text: str, lang: str) -> list[tuple[int, str]]:
    """(1-기반 행 번호, 정규화 본문) — 공백·줄주석 제외. 블록 주석은 걸러내지 못한다(한계)."""
    marks = _LINE_COMMENT.get(lang, ())
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(text.splitlines(), 1):
        body = " ".join(raw.split())
        if not body or any(body.startswith(m) for m in marks):
            continue
        out.append((i, body))
    return out


def _python_units(text: str) -> tuple[int, int, int, int]:
    """(함수 수, 최장 함수 행 수, 최대 중첩 깊이, 문턱 초과 함수 수). 파싱 실패는 전부 0."""
    try:
        tree = ast.parse(text)
    except SyntaxError, ValueError, RecursionError:
        return (0, 0, 0, 0)
    units = longest = deepest = big = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        units += 1
        span = (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno + 1
        longest = max(longest, span)
        big += 1 if span > UNIT_LINES_WARN else 0
        deepest = max(deepest, _depth(node))
    return (units, longest, deepest, big)


_BRANCHING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.match_case)


def _elif(parent: ast.AST, child: ast.AST) -> bool:
    """`elif` 인가. ast 는 elif 를 orelse 안의 If 로 표현해서 평평한 분기 사슬이 중첩으로 잡힌다 —
    분기 여섯 개짜리 elif 사슬이 깊이 7 로 나온다. 읽는 사람에게 그것은 한 단이다."""
    if not (isinstance(parent, ast.If) and isinstance(child, ast.If)):
        return False  # 자식이 If 일 때만 elif 다 — 안 그러면 문장 하나짜리 else 블록도 전부 면제된다
    return len(parent.orelse) == 1 and parent.orelse[0] is child


def _depth(fn: ast.AST) -> int:
    """함수 본문의 분기 중첩 깊이. 중첩 함수는 자기 깊이로 따로 세므로 여기서 내려가지 않는다."""

    def walk(node: ast.AST, depth: int) -> int:
        best = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            deeper = isinstance(child, _BRANCHING) and not _elif(node, child)
            best = max(best, walk(child, depth + 1 if deeper else depth))
        return best

    return walk(fn, 0)


def _churn(root: str) -> tuple[dict[str, int], int]:
    """(경로 → 커밋 수, 관측한 커밋 수). git 이 없거나 이력이 짧으면 빈 지도 — 오류 아님."""
    try:
        proc = subprocess.run(
            # quotepath=false: 한글 경로가 \xxx 로 이스케이프돼 매칭이 깨지는 것을 막는다
            ["git", "-c", "core.quotepath=false", "log", f"-n{CHURN_COMMITS}", "--format=%x00", "--name-only"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except OSError, subprocess.SubprocessError:
        return ({}, 0)
    if proc.returncode != 0:
        return ({}, 0)
    counts: dict[str, int] = {}
    commits = 0
    for line in proc.stdout.splitlines():
        if line.startswith("\x00"):
            commits += 1
            continue
        path = line.strip()
        if path:
            counts[path] = counts.get(path, 0) + 1
    return (counts, commits)


def _clones(sources: dict[str, list[tuple[int, str]]]) -> tuple[dict[str, set[int]], list[dict]]:
    """토큰 정규화 클론 검출 → (경로 → 중복 참여 행 번호, 상위 클론 그룹).

    CLONE_WINDOW 행 창을 해시해 2회 이상 나타난 창의 행을 중복으로 표시한다. 창이 겹쳐도
    행 집합으로 합치므로 이중 계상이 없다. import 류 반복 행은 창 구성에서 제외한다.
    Type-1/2 클론(공백·주석 차이)까지가 사정거리 — 이름만 바꾼 Type-3 는 못 잡는다(한계).
    """
    buckets: dict[str, list[tuple[str, tuple[int, ...]]]] = {}
    for path, lines in sources.items():
        usable = [(no, body) for no, body in lines if not body.startswith(_REPEAT_OK)]
        for i in range(len(usable) - CLONE_WINDOW + 1):
            window = usable[i : i + CLONE_WINDOW]
            joined = "\n".join(body for _, body in window)
            if len(joined) < CLONE_MIN_CHARS:
                continue
            key = hashlib.sha1(joined.encode("utf-8")).hexdigest()
            buckets.setdefault(key, []).append((path, tuple(no for no, _ in window)))
    marked: dict[str, set[int]] = {}
    groups: list[dict] = []
    for hits in buckets.values():
        if len(hits) < 2:
            continue
        for path, nos in hits:
            marked.setdefault(path, set()).update(nos)
        groups.append({"paths": sorted({path for path, _ in hits}), "copies": len(hits), "lines": CLONE_WINDOW})
    groups.sort(key=lambda g: (-g["copies"], g["paths"]))
    return (marked, groups[: _TOP_N * 20])  # 호출부가 소스 포함 여부로 걸러낼 여유분까지 넘긴다


def _py_module(rel: str, roots: tuple[str, ...]) -> str | None:
    """리포 상대 경로 → 내부 도트 모듈명. 패키지 루트 밖 파일은 None (해석 불능 = 미측정)."""
    if not rel.endswith(".py"):
        return None
    for prefix in roots:
        if rel.startswith(prefix):
            body = rel[len(prefix) :]
            parts = body[:-3].split("/")
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]
            return ".".join(parts) if parts else None
    return None


def _package_roots(paths: list[str]) -> tuple[str, ...]:
    """`__init__.py` 를 가진 최상위 패키지의 부모 디렉터리들 — import 해석의 기준점."""
    roots = {rel[: -len(f"{rel.split('/')[-2]}/__init__.py")] for rel in paths if rel.endswith("/__init__.py")}
    tops = {r for r in roots if not any(r != other and r.startswith(other) for other in roots)}
    return tuple(sorted(tops))


def _import_graph(root: str, texts: dict[str, str], roots: tuple[str, ...]) -> dict[str, set[str]]:
    """내부 모듈 간 top-level import 그래프. 외부 패키지·함수 내부 lazy import 는 제외한다."""
    modules = {rel: mod for rel in texts if (mod := _py_module(rel, roots))}
    known = set(modules.values())
    graph: dict[str, set[str]] = {mod: set() for mod in known}
    for rel, mod in modules.items():
        try:
            tree = ast.parse(texts[rel])
        except SyntaxError, ValueError, RecursionError:
            continue
        pkg = mod.split(".")[:-1]
        for node in tree.body:  # top-level 만 — 함수 내부 lazy import 는 의도된 탈출구
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg[: len(pkg) - (node.level - 1)] if node.level - 1 <= len(pkg) else []
                    head = ".".join([*base, node.module] if node.module else base)
                else:
                    head = node.module or ""
                # `from . import sibling` 은 패키지 __init__ 에 대한 의존이 아니다 — 형제 모듈만 센다.
                # node.module 이 있을 때만 head 자체를 대상으로 올린다 (`from a.b import c` → a.b 도 의존).
                targets = [f"{head}.{alias.name}" for alias in node.names if head]
                if node.module:
                    targets.append(head)
            for target in targets:
                # 가장 긴 알려진 접두를 내부 대상으로 본다 (`a.b.c` import → 실존 모듈 `a.b`)
                best = max((k for k in known if target == k or target.startswith(k + ".")), key=len, default=None)
                if best and best != mod:
                    graph[mod].add(best)
    return graph


def _cycles(graph: dict[str, set[str]]) -> int:
    """순환 개수 = 크기 2 이상인 강결합 성분 수 (Tarjan, 반복 구현 — 재귀 한계 회피)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = 0
    found = 0
    for start in sorted(graph):
        if start in index:
            continue
        work: list[tuple[str, list[str]]] = [(start, sorted(graph.get(start, ())))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, pending = work[-1]
            if pending:
                nxt = pending.pop()
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, sorted(graph.get(nxt, ()))))
                elif nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                size = 0
                while stack:
                    popped = stack.pop()
                    on_stack.discard(popped)
                    size += 1
                    if popped == node:
                        break
                found += 1 if size > 1 else 0
    return found


def scan(root: str) -> Snapshot:
    """나무 전체를 훑어 스냅샷 1개를 만든다. 순수 관측 — 파일을 쓰지 않는다."""
    listing, excluded = _iter_files(root)
    texts = {rel: text for rel, _ in listing if (text := _read(root, rel)) is not None}
    langs = {rel: lang for rel, lang in listing if rel in texts}
    code = {rel: _code_lines(texts[rel], langs[rel]) for rel in texts}
    churn, window = _churn(root)
    marked, clone_groups = _clones(code)
    roots = _package_roots(list(texts))
    graph = _import_graph(root, texts, roots)
    fan_in: dict[str, int] = {}
    for deps in graph.values():
        for dep in deps:
            fan_in[dep] = fan_in.get(dep, 0) + 1

    files: list[FileHealth] = []
    for rel, lang in sorted(langs.items()):
        precise = os.path.splitext(rel)[1] in _PRECISE_SUFFIX
        units, longest, deepest, big = _python_units(texts[rel]) if precise else (0, 0, 0, 0)
        mod = _py_module(rel, roots) if precise else None
        files.append(
            FileHealth(
                path=rel,
                lang=lang,
                lines=len(code[rel]),
                total_lines=len(texts[rel].splitlines()),
                max_unit_lines=longest,
                max_depth=deepest,
                units=units,
                big_units=big,
                churn=churn.get(rel, 0),
                dup_lines=len(marked.get(rel, ())),
                fan_out=len(graph.get(mod, ())) if mod else 0,
                fan_in=fan_in.get(mod, 0) if mod else 0,
                precise=precise,
                test=_is_test(rel),
            )
        )

    source = [f for f in files if not f.test]
    tests = [f for f in files if f.test]
    code_lines = sum(f.lines for f in source)
    dup_lines = sum(f.dup_lines for f in source)
    hotspots = sorted(
        ({"path": f.path, "churn": f.churn, "lines": f.lines, "score": f.churn * f.lines} for f in source if f.churn),
        key=lambda h: (-h["score"], h["path"]),
    )
    lang_counts: dict[str, int] = {}
    for f in files:
        lang_counts[f.lang] = lang_counts.get(f.lang, 0) + 1
    return Snapshot(
        commit=_head(root),
        files=len(source),
        unmeasured_files=sum(1 for f in source if not f.precise),
        excluded_files=excluded,
        code_lines=code_lines,
        test_files=len(tests),
        test_code_lines=sum(f.lines for f in tests),
        big_files=sum(1 for f in source if f.lines > FILE_LINES_WARN),
        severe_files=sum(1 for f in source if f.lines > FILE_LINES_SEVERE),
        big_units=sum(f.big_units for f in source),
        deep_units=sum(1 for f in source if f.max_depth > DEPTH_WARN),
        dup_lines=dup_lines,
        dup_share=round(dup_lines / code_lines, 4) if code_lines else 0.0,
        test_dup_lines=sum(f.dup_lines for f in tests),
        cycles=_cycles(graph),
        max_fan_in=max((f.fan_in for f in source), default=0),
        max_fan_out=max((f.fan_out for f in source), default=0),
        hotspots=hotspots[:_TOP_N],
        largest=[{"path": f.path, "lines": f.lines} for f in sorted(source, key=lambda f: -f.lines)[:_TOP_N]],
        worst_units=[
            {"path": f.path, "lines": f.max_unit_lines, "depth": f.max_depth}
            for f in sorted((f for f in source if f.max_unit_lines > UNIT_LINES_WARN), key=lambda f: -f.max_unit_lines)[
                :_TOP_N
            ]
        ],
        dup_top=[g for g in clone_groups if any(not _is_test(p) for p in g["paths"])][:_TOP_N],
        coupling_top=[
            {"path": f.path, "fan_in": f.fan_in, "fan_out": f.fan_out}
            for f in sorted(source, key=lambda f: (-(f.fan_in + f.fan_out), f.path))[:_TOP_N]
            if f.fan_in or f.fan_out
        ],
        langs=dict(sorted(lang_counts.items())),
        churn_window=window,
    )


def _head(root: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        return proc.stdout.strip() if proc.returncode == 0 else "unknown"
    except OSError, subprocess.SubprocessError:
        return "unknown"


def oversized(root: str, paths: object) -> tuple[str, ...]:
    """주어진 경로 중 FILE_LINES_WARN 을 넘는 것만. 전수 스캔 없이 그 파일들만 읽는다.

    턴마다 부르는 자리(트리니티 프롬프트 조립)가 소비처이므로 `scan()` 을 쓸 수 없다 —
    나무 전체를 훑는 비용은 신호 수집용이고, 이쪽은 지목한 파일에 대한 즉답이어야 한다.
    """
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return ()
    out = []
    for raw in paths:
        rel = str(raw).strip().replace(os.sep, "/")
        if not rel or os.path.splitext(rel)[1] not in _LANG_BY_SUFFIX:
            continue
        text = _read(root, rel)
        if text is None:
            continue
        lang = _LANG_BY_SUFFIX[os.path.splitext(rel)[1]]
        if len(_code_lines(text, lang)) > FILE_LINES_WARN:
            out.append(rel)
    return tuple(sorted(set(out)))


def history_path(root: str) -> str:
    return os.path.join(root, ".asgard", "health", "history.jsonl")


# 추세 방향 — 값이 오르면 나빠지는 지표들. 여기 없는 필드는 델타를 내지 않는다
# (code_lines 증가는 침식이 아니라 성장이다 — 비율 지표만 판정한다).
_WORSE_WHEN_UP = (
    "big_files",
    "severe_files",
    "big_units",
    "deep_units",
    "dup_share",
    "cycles",
    "max_fan_in",
    "max_fan_out",
)


def record(root: str) -> Snapshot:
    """스냅샷을 찍어 이력에 덧붙인다. 보존은 마지막 HISTORY_KEEP 개 — 원자적 재작성."""
    snap = scan(root)
    path = history_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = _history(root)
    rows.append(asdict(snap))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows[-HISTORY_KEEP:]:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return snap


def _history(root: str) -> list[dict]:
    try:
        with open(history_path(root), encoding="utf-8") as fh:
            return [row for line in fh if line.strip() and isinstance(row := _row(line), dict)]
    except OSError:
        return []


def _row(line: str) -> dict | None:
    try:
        return json.loads(line)
    except ValueError:
        return None


def trend(root: str, current: Snapshot | None = None) -> Trend | None:
    """마지막 기록과 현재 상태의 델타. 기록이 없으면 None — 추세는 두 점부터 존재한다."""
    rows = _history(root)
    if not rows:
        return None
    before = rows[-1]
    after = asdict(current) if current is not None else asdict(scan(root))
    deltas = []
    for metric in _WORSE_WHEN_UP:
        old, new = float(before.get(metric) or 0), float(after.get(metric) or 0)
        if old == new:
            direction = "flat"
        else:
            direction = "regressed" if new > old else "improved"
        deltas.append(Delta(metric=metric, before=old, after=new, direction=direction))
    return Trend(
        from_commit=str(before.get("commit") or "unknown"), to_commit=str(after.get("commit")), deltas=tuple(deltas)
    )
