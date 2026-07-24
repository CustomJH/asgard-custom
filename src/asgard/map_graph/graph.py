"""관계 그래프 빌드·저장·프로젝션·탐색.

소유권: 그래프 상태는 `.asgard/state/map-graph.json`(미추적), 카탈로그 프로젝션은
`.asgard/map/GRAPH.md`(추적·팀 공유)만 소유한다. 프로젝션은 PROJECT.md 와 같은
`- `path` — role` 엔트리 문법을 지켜 맵 컨텍스트에 그대로 융합된다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..code_map import MapError, _atomic_write, _files, _map_dir, _safe_component
from .evidence import Evidence
from .extract_java import extract_java, extract_mapper_xml, extract_proc, extract_sql
from .extract_python import extract_python
from .extract_tsjs import extract_api_bases, extract_tsjs
from .spring_props import SpringProps

GRAPH_FILE = "GRAPH.md"
_GRAPH_MARKER = "<!-- asgard:map-graph schema=1 -->"
_STATE_RELATIVE = Path(".asgard") / "state" / "map-graph.json"
_MAX_SOURCE_BYTES = 512 * 1024
_TSJS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".prisma", ".vue", ".svelte"}
# 확장자 → 추출기 (JVM/DB 레인 포함). `.xml`/`.sql` 추출기는 비대상 파일에서 빈 결과를 낸다.
_EXTRACTORS = {
    ".py": extract_python,
    ".java": extract_java,
    ".xml": extract_mapper_xml,
    ".sql": extract_sql,
    ".pc": extract_proc,
    **dict.fromkeys(_TSJS_SUFFIXES, extract_tsjs),
}
# 증거 종류 → 파일-노드 간 엣지 관계
_EDGE_KIND = {
    "route": "declares",
    "page": "declares",
    "store": "declares",
    "composable": "declares",
    "component": "declares",  # 소비(스팬 없음)는 빌드 시 "uses" 로 강등된다
    "command": "declares",
    "model": "declares",
    "job": "declares",
    "event": "declares",
    "api_call": "calls",
    "db_access": "touches",
    "external_service": "uses",
}
# 소비 증거 종류 → 개념-개념 플로우 엣지 관계 (선언자 본문 스팬 포함이 근거)
_FLOW_KIND = {
    "db_access": "touches",
    "api_call": "calls",
    "external_service": "uses",
    "event": "emits",
    "component": "uses",  # 합성 소비 — page/component 스팬 안 태그가 atoms→page 체인을 만든다
}
EDGE_KINDS = ("declares", "calls", "touches", "uses", "emits")
# API↔라우트 브리지 — api_call 경로와 route 경로의 정규화 일치만 근거로 삼는 candidate 엣지.
# 경로 변수 표기(`:id`/`{id}`/`{}`)는 와일드카드 세그먼트 하나로 수렴한다.
_PLACEHOLDER_SEGMENT = re.compile(r"^(?::\w+|\{\w*\})$")
_EMBEDDED_PLACEHOLDER = re.compile(r"\$\{[^{}]*\}|\{[^{}]*\}")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_HTTP_VERBS = ("get", "post", "put", "delete", "patch")
# 한 호출이 이만큼 넘는 라우트와 일치하면 수렴 실패다 — 지어내지 않고 통째로 버린다.
_API_LINK_CAP = 8
# 스코프당 FE 베이스 접두가 이만큼 넘으면 수집 잡음이다 — 그 스코프의 베이스를 쓰지 않는다.
_API_BASE_CAP = 4
# GRAPH.md Trace seeds — 진입 표면 종류만, 종류당 상한 (전체 열람은 `asgard map list`).
_SEED_KINDS = ("route", "page", "command", "store", "event", "job")
_MAX_SEEDS_PER_KIND = 40
# 스팬 신뢰 확장자 — AST(.py)·주석 제거 후 중괄호 균형(.java)은 포함 관계가 결정론적이다.
# 나머지(원문 정규식 근사 스팬)는 플로우 엣지를 candidate 로 캡한다.
_STRUCTURAL_SPAN_SUFFIXES = (".py", ".java")
_KIND_LABEL = {
    "route": "routes",
    "page": "pages",
    "store": "stores",
    "composable": "composables",
    "component": "components",
    "command": "commands",
    "model": "models",
    "db_access": "db",
    "api_call": "calls",
    "event": "events",
    "job": "jobs",
    "external_service": "uses",
}


class GraphError(MapError):
    """그래프 빌드/조회 실패."""


class GraphOwnershipError(GraphError):
    """사람 소유 파일과 예약된 그래프 프로젝션이 충돌한다."""


@dataclass(frozen=True)
class GraphResult:
    files_scanned: int
    evidence_count: int
    nodes: int
    edges: int
    flows: int
    api_links: int
    state_path: str
    graph_md_path: str
    changed: bool


_JVM_SUFFIXES = {".java", ".kt", ".kts"}
_JVM_TEST_DIRS = {"test", "androidtest", "integrationtest", "testfixtures"}


def _is_test_path(path: Path) -> bool:
    parts = [part.casefold() for part in path.parts[:-1]]
    if path.suffix.lower() in _JVM_SUFFIXES:
        # JVM 소스의 테스트는 src/test 트리 관례뿐이다 — "test" 패키지 세그먼트는 프로덕션이다.
        return any(prev == "src" and part in _JVM_TEST_DIRS for prev, part in zip(parts, parts[1:]))
    name = path.name.casefold()
    return (
        bool(set(parts) & {"test", "tests", "__tests__"})
        or name == "test.py"
        or name.startswith("test_")
        or name.endswith("_test.py")
        or any(marker in name for marker in (".test.", ".spec."))
    )


def _scope_of(rel_posix: str) -> str:
    """모노레포 최상위 디렉터리 스코프 — SpringProps 와 동일한 경계."""
    parts = rel_posix.split("/")
    return parts[0] if len(parts) > 1 else ""


def _stat_revision(root: Path) -> str:
    """(경로·크기·mtime_ns) 스탯 다이제스트 — 파일 내용을 읽지 않는 값싼 신선도 표식.

    `_collect` 와 동일한 파일 선별 규칙을 지켜야 비교가 성립한다. mtime 오탐(내용 동일한
    touch)은 stale 방향으로만 틀린다 — 재스캔을 한 번 더 시킬 뿐 낡은 지도를 사실처럼
    보여주지 않는다.
    """
    digest = hashlib.sha256()
    for rel in _files(root):
        suffix = rel.suffix.lower()
        if suffix not in _EXTRACTORS and not SpringProps.is_config(rel.name):
            continue
        if _is_test_path(rel):
            continue
        try:
            stat = (root / rel).stat()
        except OSError:
            continue
        if stat.st_size > _MAX_SOURCE_BYTES:
            continue
        digest.update(f"{rel.as_posix()}\0{stat.st_size}\0{stat.st_mtime_ns}".encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
    return "source-stat-sha256:" + digest.hexdigest()


def _collect(root: Path) -> tuple[int, list[Evidence], str, dict[str, tuple[str, ...]], str]:
    scanned = 0
    collected: list[Evidence] = []
    props = SpringProps()
    base_table: dict[str, set[str]] = defaultdict(set)
    digest = hashlib.sha256()
    stat_digest = hashlib.sha256()
    for rel in _files(root):
        suffix = rel.suffix.lower()
        is_config = SpringProps.is_config(rel.name)
        if suffix not in _EXTRACTORS and not is_config:
            continue
        if _is_test_path(rel):
            continue
        full = root / rel
        try:
            stat = full.stat()
        except OSError:
            continue
        if stat.st_size > _MAX_SOURCE_BYTES:
            continue
        # 스탯 다이제스트는 read/decode 성패와 무관하게 여기서 찍는다 — `_stat_revision` 과 동일 집합.
        stat_digest.update(f"{rel.as_posix()}\0{stat.st_size}\0{stat.st_mtime_ns}".encode("utf-8", "surrogateescape"))
        stat_digest.update(b"\0")
        try:
            raw = full.read_bytes()
        except OSError:
            continue
        try:
            source = raw.decode("utf-8")
        except UnicodeError:
            # 한국 엔터프라이즈 레거시(EUC-KR/CP949) 소스도 증거 대상이다 — 둘 다 아니면 건너뛴다.
            try:
                source = raw.decode("cp949")
            except UnicodeError:
                continue
        digest.update(rel.as_posix().encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(source.encode())
        digest.update(b"\0")
        scanned += 1
        if is_config:
            props.ingest(rel.as_posix(), source)
            continue
        if suffix in _TSJS_SUFFIXES:
            base_table[_scope_of(rel.as_posix())].update(extract_api_bases(source))
        collected.extend(_EXTRACTORS[suffix](rel.as_posix(), source))
    # 스코프당 베이스가 상한을 넘으면 잡음이다 — 그 스코프는 통째로 버린다 (모호성 보존).
    api_bases = {scope: tuple(sorted(bases)) for scope, bases in base_table.items() if 0 < len(bases) <= _API_BASE_CAP}
    return (
        scanned,
        props.promote(collected),
        "source-sha256:" + digest.hexdigest(),
        api_bases,
        "source-stat-sha256:" + stat_digest.hexdigest(),
    )


def _flow_edges(collected: list[Evidence]) -> dict[tuple[str, str, str], str]:
    """선언자 본문 스팬 ⊇ 소비 증거 줄 → 개념-개념 플로우 엣지.

    같은 파일 안 포함 관계만 근거로 삼고, 중첩 시 가장 안쪽 선언자에 귀속한다.
    지어내지 않는다: 스팬이 근사(비구조 확장자)이거나 어느 한쪽 증거가 candidate 면 candidate.
    """
    edges: dict[tuple[str, str, str], str] = {}
    per_file: dict[str, list[Evidence]] = defaultdict(list)
    for item in collected:
        per_file[item.file].append(item)
    for file, items in per_file.items():
        declarers = [item for item in items if item.scope_end]
        if not declarers:
            continue
        structural = file.endswith(_STRUCTURAL_SPAN_SUFFIXES)
        for consumer in items:
            if consumer.scope_end or consumer.kind not in _FLOW_KIND:
                continue
            containing = [d for d in declarers if d.line <= consumer.line <= d.scope_end]
            if not containing:
                continue
            owner = min(containing, key=lambda d: (d.scope_end - d.line, d.line))
            if owner.node_id == consumer.node_id:
                continue
            confirmed = structural and owner.confidence == "confirmed" and consumer.confidence == "confirmed"
            key = (owner.node_id, consumer.node_id, _FLOW_KIND[consumer.kind])
            if confirmed or key not in edges:
                edges[key] = "confirmed" if confirmed else "candidate"
    return edges


def _normal_segment(part: str) -> str:
    """세그먼트 정규화 — 경로 변수는 `{}` 로, 세그먼트에 박힌 `${...}`/`{...}` 는 벗겨낸다.

    Spring 클래스 프리픽스의 `${api.prefix}string-monitoring` 처럼 설정 플레이스홀더가
    리터럴에 붙은 세그먼트는 남은 리터럴이 정체다. 벗기고 나면 빈 세그먼트만 와일드카드다.
    """
    if _PLACEHOLDER_SEGMENT.fullmatch(part):
        return "{}"
    stripped = _EMBEDDED_PLACEHOLDER.sub("", part)
    return stripped.casefold() if stripped else "{}"


def _path_segments(raw: str) -> tuple[str, ...]:
    return tuple(_normal_segment(part) for part in raw.split("/") if part)


def _api_call_segments(name: str) -> tuple[str, ...] | None:
    """api_call 노드 이름 → 정규화 경로 세그먼트. 경로 모양이 아니면(수신자 표기 등) None."""
    if name.startswith(("http://", "https://")):
        raw = urlsplit(name).path
    elif name.startswith("/"):
        raw = name
    else:
        return None
    segments = _path_segments(raw)
    return segments or None  # 루트 단독 호출은 어떤 라우트와도 구별 근거가 없다


def _segments_match(api: tuple[str, ...], route: tuple[str, ...], *, exact_length: bool) -> bool:
    """세그먼트 일치 — 접미 일치는 접두(베이스 URL/프록시/게이트웨이) 차이만 인정한다.

    와일드카드(`{}`)는 와일드카드끼리만 일치한다: 한쪽만 변수인 자리는 경로 모양이 다른
    것이지 같다는 증거가 아니다 (`/users/me` ↔ `/users/{id}` 를 잇지 않는다). 리터럴 일치가
    하나도 없으면(순수 와일드카드) 일치로 치지 않는다.
    """
    if exact_length:
        if len(api) != len(route):
            return False
        pairs = list(zip(api, route))
    else:
        short, long = (api, route) if len(api) < len(route) else (route, api)
        if not short or len(short) == len(long):
            return False
        pairs = list(zip(short, long[-len(short) :]))
    return all(a == b for a, b in pairs) and any(a != "{}" for a, _b in pairs)


def _api_call_method(node: dict) -> str:
    """api_call 증거 detail(래퍼 이름 등)에서 HTTP 메서드를 읽는다 — 못 읽으면 빈 문자열."""
    for location in node["files"]:
        text = _CAMEL_BOUNDARY.sub("_", location.get("detail", "")).casefold()
        for verb in _HTTP_VERBS:
            if re.search(rf"(?:^|[^a-z]){verb}(?:$|[^a-z])", text):
                return verb.upper()
    return ""


def _api_route_links(
    nodes: dict[str, dict], api_bases: dict[str, tuple[str, ...]] | None = None
) -> dict[tuple[str, str, str], str]:
    """api_call → route 브리지 엣지 — 프론트/원격 호출과 백엔드 표면을 경로 일치로 잇는다.

    베이스 URL·프록시 접두는 정적으로 증명할 수 없으므로 전부 candidate 다. 우선순위:
    완전 일치("path match") → 같은 스코프에서 수집한 FE 베이스 접두를 붙인 완전 일치
    ("path match via <base>", 노드 이름은 원문 보존) → 접미 일치("path suffix match").
    """
    api_bases = api_bases or {}
    routes: list[tuple[str, str, tuple[str, ...]]] = []
    for node in nodes.values():
        if node["kind"] != "route":
            continue
        method, _, raw = node["name"].partition(" ")
        if raw.startswith("/"):
            routes.append((node["id"], method.upper(), _path_segments(raw)))
    links: dict[tuple[str, str, str], str] = {}
    for node in nodes.values():
        if node["kind"] != "api_call":
            continue
        segments = _api_call_segments(node["name"])
        if segments is None:
            continue
        # 베이스 접두는 상대 경로 호출에만 후보다 — 절대 URL 은 이미 오리진을 스스로 증명한다.
        based_segments: list[tuple[str, tuple[str, ...]]] = []
        if node["name"].startswith("/"):
            scopes = {_scope_of(location["file"]) for location in node["files"]}
            for base in sorted({base for scope in scopes for base in api_bases.get(scope, ())}):
                based_segments.append((base, _path_segments(base) + segments))
        method = _api_call_method(node)
        exact: list[str] = []
        based: list[tuple[str, str]] = []
        suffix: list[str] = []
        for route_id, route_method, route_segments in routes:
            if method and route_method not in ("ANY", method):
                continue
            if _segments_match(segments, route_segments, exact_length=True):
                exact.append(route_id)
                continue
            hit = next(
                (
                    base
                    for base, candidate in based_segments
                    if _segments_match(candidate, route_segments, exact_length=True)
                ),
                None,
            )
            if hit is not None:
                based.append((route_id, hit))
            elif _segments_match(segments, route_segments, exact_length=False):
                suffix.append(route_id)
        if exact:
            matches = [(route_id, "path match") for route_id in exact]
        elif based:
            matches = [(route_id, f"path match via {base}") for route_id, base in based]
        else:
            matches = [(route_id, "path suffix match") for route_id in suffix]
        if not matches or len(matches) > _API_LINK_CAP:
            continue
        for route_id, reason in matches:
            links[(node["id"], route_id, "calls")] = reason
    return links


def _build_state(
    scanned: int,
    collected: list[Evidence],
    revision: str,
    api_bases: dict[str, tuple[str, ...]] | None = None,
    stat_revision: str = "",
) -> dict:
    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str, str], str] = {}
    for item in collected:
        node = nodes.setdefault(
            item.node_id,
            {"id": item.node_id, "kind": item.kind, "name": item.name, "confidence": item.confidence, "files": []},
        )
        if item.confidence == "confirmed":
            node["confidence"] = "confirmed"
        location = {"file": item.file, "line": item.line, "confidence": item.confidence, "detail": item.detail}
        if location not in node["files"]:
            node["files"].append(location)
        file_id = f"file:{item.file}"
        nodes.setdefault(
            file_id, {"id": file_id, "kind": "file", "name": item.file, "confidence": "confirmed", "files": []}
        )
        # 컴포넌트 소비(스팬 없음)는 선언이 아니다 — 파일 엣지도 uses 로 표기한다.
        file_edge = "uses" if item.kind == "component" and not item.scope_end else _EDGE_KIND[item.kind]
        edges[(file_id, item.node_id, file_edge)] = "confirmed"
    flows = _flow_edges(collected)
    edges.update(flows)
    link_details: dict[tuple[str, str, str], str] = {}
    for key, reason in _api_route_links(nodes, api_bases).items():
        if key not in edges:
            edges[key] = "candidate"
            link_details[key] = reason
    for node in nodes.values():
        node["files"].sort(key=lambda loc: (loc["file"], loc["line"]))
    return {
        "schema": 1,
        "revision": revision,
        "stat_revision": stat_revision,
        "counts": {
            "files_scanned": scanned,
            "evidence": len(collected),
            "nodes": len(nodes),
            "edges": len(edges),
            "flows": len(flows),
            "api_links": len(link_details),
        },
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": [
            {"source": source, "target": target, "kind": kind, "confidence": confidence}
            | ({"detail": link_details[source, target, kind]} if (source, target, kind) in link_details else {})
            for (source, target, kind), confidence in sorted(edges.items())
        ],
    }


def _render_graph_md(state: dict) -> str:
    """결정론 카탈로그 — 타임스탬프·리비전 없이 구조만 담아 팀 diff 를 조용하게 유지한다."""
    per_file: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    kind_totals: dict[str, int] = defaultdict(int)
    for node in state["nodes"]:
        if node["kind"] == "file":
            continue
        kind_totals[node["kind"]] += 1
        suffix = "" if node["confidence"] == "confirmed" else "?"
        for location in node["files"]:
            per_file[location["file"]][node["kind"]].append(node["name"] + suffix)
    summary = " · ".join(f"{_KIND_LABEL[kind]} {kind_totals[kind]}" for kind in _KIND_LABEL if kind_totals.get(kind))
    names = {node["id"]: node["name"] for node in state["nodes"] if "id" in node}
    flows: dict[str, list[str]] = defaultdict(list)
    for edge in state.get("edges", []):
        if edge["source"].startswith("file:"):
            continue
        suffix = "" if edge.get("confidence", "confirmed") == "confirmed" else "?"
        flows[edge["source"]].append(f"{edge['kind']} `{names.get(edge['target'], edge['target'])}`{suffix}")
    lines = [
        _GRAPH_MARKER,
        "# Relation Graph",
        "",
        "> Asgard managed relation catalog. Regenerate with `asgard map scan`; do not hand-edit.",
        "> `?` marks candidate evidence — verify at the cited source before asserting.",
        "",
        f"- Evidence summary: {summary or 'none'}",
        "",
        "## Relations by file",
        "",
    ]
    ranked = sorted(per_file.items(), key=lambda item: (-sum(len(v) for v in item[1].values()), item[0]))
    for path, kinds in ranked:
        parts = []
        for kind in _KIND_LABEL:
            if kinds.get(kind):
                parts.append(f"{_KIND_LABEL[kind]}: {', '.join(sorted(kinds[kind]))}")
        lines.append(f"- `{path}` — " + " · ".join(parts))
    if flows:
        # 개념→개념 플로우 — 어느 핸들러가 어떤 DB/API/이벤트/서비스를 만지는지
        lines += ["", "## Flows", ""]
        for source in sorted(flows):
            lines.append(f"- `{names.get(source, source)}` — " + " · ".join(sorted(flows[source])))
    # 진입 표면의 정확한 노드 id — 카탈로그 행이 곧 trace 시드다 (id 재구성 강요 금지).
    seeds: dict[str, list[str]] = defaultdict(list)
    for node in state["nodes"]:
        if node["kind"] in _SEED_KINDS and "id" in node:
            seeds[node["kind"]].append(node["id"])
    if seeds:
        lines += [
            "",
            "## Trace seeds",
            "",
            "> Exact node ids — copy into `asgard map trace --from <id>` or `asgard map impact <id>`.",
            "",
        ]
        for kind in _SEED_KINDS:
            ids = sorted(seeds.get(kind, ()))
            if not ids:
                continue
            row = " · ".join(f"`{node_id}`" for node_id in ids[:_MAX_SEEDS_PER_KIND])
            if len(ids) > _MAX_SEEDS_PER_KIND:
                row += f" (+{len(ids) - _MAX_SEEDS_PER_KIND} more — `asgard map list --kind {kind}`)"
            lines.append(f"- {_KIND_LABEL[kind]}: {row}")
    lines += [
        "",
        "## Navigation contract",
        "",
        "- Trace edges with `asgard map trace --from <node-id>` (`--kinds touches,calls` filters edge kinds).",
        "- Enumerate node ids with `asgard map list [--kind route]`; both directions at once with `asgard map impact <node-id>`.",
        '- Do not read this catalog whole on large repos — `asgard map context --query "<task>"` returns the bounded, task-ranked slice.',
        "- A missing edge is not evidence of absence — this graph is static-lane adjacency, not an exhaustive dependency inventory.",
        "",
    ]
    return "\n".join(lines)


def _owned_graph_md(content: str) -> bool:
    lines = content.splitlines()
    return bool(lines) and lines[0] == _GRAPH_MARKER


def _state_file(root: Path, name: str, *, create: bool) -> Path:
    asgard = root / ".asgard"
    state_dir = asgard / "state"
    for component in (asgard, state_dir):
        if not _safe_component(component):
            raise GraphError(f"managed graph state path is a symlink/junction: {component}")
    if create:
        state_dir.mkdir(parents=True, exist_ok=True)
    if state_dir.exists():
        try:
            state_dir.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise GraphError(f"managed graph state path escapes project root: {state_dir}") from exc
    return state_dir / name


def _atomic_state_write(root: Path, path: Path, content: str) -> None:
    state_dir = _state_file(root, path.name, create=True).parent
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=state_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def scan_graph(root: str | os.PathLike[str], *, dry_run: bool = False, force: bool = False) -> GraphResult:
    base = Path(root).resolve()
    scanned, collected, revision, api_bases, stat_revision = _collect(base)
    state = _build_state(scanned, collected, revision, api_bases, stat_revision)
    state_path = _state_file(base, _STATE_RELATIVE.name, create=False)
    state_json = json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True)
    graph_md = _render_graph_md(state)
    map_dir = _map_dir(base, create=not dry_run)
    collision = (
        next((child for child in map_dir.iterdir() if child.name.casefold() == GRAPH_FILE.casefold()), None)
        if map_dir.exists()
        else None
    )
    if collision is not None and collision.name != GRAPH_FILE:
        raise GraphOwnershipError(f"reserved graph filename collision: {collision.name}")
    graph_md_path = map_dir / GRAPH_FILE
    try:
        current = graph_md_path.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if graph_md_path.exists() and not _owned_graph_md(current) and not force:
        # force(init 경로)는 이 소유권 거부만 우회한다 — 예약 파일명 충돌 검사는 우회하지 않는다.
        raise GraphOwnershipError(f"refusing to overwrite human-owned {graph_md_path}")
    try:
        current_state = state_path.read_text(encoding="utf-8") if not state_path.is_symlink() else ""
    except OSError:
        current_state = ""
    state_changed = current_state != state_json
    changed = current != graph_md or state_changed
    if not dry_run:
        if state_changed:
            _atomic_state_write(base, state_path, state_json)
        if current != graph_md:
            _atomic_write(base, graph_md_path, graph_md)
    return GraphResult(
        files_scanned=scanned,
        evidence_count=len(collected),
        nodes=state["counts"]["nodes"],
        edges=state["counts"]["edges"],
        flows=state["counts"]["flows"],
        api_links=state["counts"]["api_links"],
        state_path=str(state_path),
        graph_md_path=str(graph_md_path),
        changed=changed,
    )


def graph_state(root: str | os.PathLike[str]) -> dict | None:
    path = _state_file(Path(root).resolve(), _STATE_RELATIVE.name, create=False)
    if path.is_symlink():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    if not isinstance(state, dict) or state.get("schema") != 1:
        return None
    if not isinstance(state.get("nodes"), list) or not isinstance(state.get("edges"), list):
        return None
    if not isinstance(state.get("counts"), dict) or not isinstance(state.get("revision"), str):
        return None
    return state


def fresh_state(root: str | os.PathLike[str]) -> dict:
    """현재 소스와 리비전이 일치하는 그래프 상태만 돌려준다 — 낡은 지도는 사실이 아니다.

    검사는 스탯 다이제스트(내용 무독취) 우선이다 — 대형 리포에서 호출당 전체 재독취 비용을
    없앤다. 스탯 표식이 없는 구 상태만 내용 다이제스트로 폴백한다.
    """
    state = graph_state(root)
    if state is None:
        raise GraphError("relation graph state missing — run `asgard map scan` first")
    base = Path(root).resolve()
    stat_revision = state.get("stat_revision")
    if isinstance(stat_revision, str) and stat_revision:
        current = _stat_revision(base)
    else:
        stat_revision, current = state["revision"], _collect(base)[2]
    if stat_revision != current:
        raise GraphError("relation graph state is stale — run `asgard map scan` first")
    return state


def concept_candidates(state: dict, word: str, *, limit: int = 8) -> list[dict]:
    """개념어 → 종류 라운드로빈 후보(id + 대표 앵커) — 한 번의 호출로 진입 지점을 준다.

    알파벳 선두 종류(api_call)가 독점하지 않게 종류당 하나씩 돌고, 종류 안에서는 짧은 id
    우선이다 — `db_access:ORGANIZATION` 이 긴 구문 id 보다 정규형에 가깝다.
    """
    lowered = word.casefold()
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for node in state.get("nodes", ()):
        node_id = node.get("id", "")
        if lowered in node_id.casefold():
            by_kind[node["kind"]].append(node)
    for kind in by_kind:
        by_kind[kind].sort(key=lambda n: (len(n["id"]), n["id"]))
    picked: list[dict] = []
    while len(picked) < limit and any(by_kind.values()):
        for kind in sorted(by_kind):
            if by_kind[kind] and len(picked) < limit:
                node = by_kind[kind].pop(0)
                file, line = node_anchor(node)
                picked.append({"id": node["id"], "kind": node["kind"], "file": file, "line": line})
    return picked


def node_anchor(node: dict) -> tuple[str, int]:
    """노드의 대표 증거 위치 — confirmed 위치 우선, 파일 노드는 경로 자신이 앵커다."""
    if node["kind"] == "file":
        return node["name"], 0
    locations = node.get("files") or []
    picked = next((loc for loc in locations if loc.get("confidence") == "confirmed"), None) or (
        locations[0] if locations else None
    )
    return (picked["file"], picked["line"]) if picked else ("", 0)


def trace(
    root: str | os.PathLike[str],
    node_id: str,
    *,
    depth: int = 2,
    direction: str = "both",
    kinds: set[str] | None = None,
    state: dict | None = None,
) -> list[dict]:
    """BFS 로 확인된 엣지만 따라간다 — 전수 블라스트 레디우스가 아니라 인접 지도다.

    `kinds` 는 따라갈 엣지 종류의 화이트리스트다 — 예: DB 앵커 업스트림에 {"touches", "calls"}
    를 주면 한 번의 호출로 DB→핸들러→호출 화면까지 조인해 회수한다. `state` 를 주면 신선도
    검사를 이미 통과한 상태를 재사용한다 (impact 처럼 한 번 검사로 여러 번 걸을 때).
    """
    if not 0 <= depth <= 8:
        raise GraphError("trace depth must be between 0 and 8")
    if direction not in {"both", "upstream", "downstream"}:
        raise GraphError("trace direction must be one of: both, upstream, downstream")
    if kinds is not None:
        unknown = kinds - set(EDGE_KINDS)
        if unknown or not kinds:
            allowed = ", ".join(EDGE_KINDS)
            raise GraphError(f"trace kinds must be a non-empty subset of: {allowed}")
    if state is None:
        state = fresh_state(root)
    nodes = {node["id"]: node for node in state["nodes"]}
    if node_id not in nodes:
        near = concept_candidates(state, node_id)
        rendered = [
            candidate["id"]
            + (
                f" @ {candidate['file']}" + (f":{candidate['line']}" if candidate["line"] else "")
                if candidate["file"]
                else ""
            )
            for candidate in near
        ]
        hint = f" — candidates: {', '.join(rendered)}" if rendered else ""
        raise GraphError(f"unknown node id: {node_id}{hint}")
    forward: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    backward: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for edge in state["edges"]:
        if kinds is not None and edge["kind"] not in kinds:
            continue
        confidence = edge.get("confidence", "confirmed")
        forward[edge["source"]].append((edge["target"], edge["kind"], confidence))
        backward[edge["target"]].append((edge["source"], edge["kind"], confidence))
    seen = {node_id}
    frontier = [(node_id, 0, "")]
    hops: list[dict] = []
    index = 0
    while index < len(frontier):
        current, level, _via = frontier[index]
        index += 1
        if level >= depth:
            continue
        neighbors: list[tuple[str, str, str]] = []
        if direction in {"both", "downstream"}:
            neighbors += forward[current]
        if direction in {"both", "upstream"}:
            neighbors += backward[current]
        for neighbor, kind, edge_confidence in sorted(neighbors):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            node = nodes[neighbor]
            file, line = node_anchor(node)
            hops.append(
                {
                    "id": neighbor,
                    "kind": node["kind"],
                    "name": node["name"],
                    "confidence": node["confidence"],
                    "depth": level + 1,
                    "via": kind,
                    "via_confidence": edge_confidence,
                    "file": file,
                    "line": line,
                    "truncated": False,
                }
            )
            frontier.append((neighbor, level + 1, kind))
    # 절단 보고 — 깊이 상한에서 미탐색 이웃이 남은 홉은 커버리지 한계다 (침묵 절단 금지).
    for hop in hops:
        if hop["depth"] != depth:
            continue
        remaining: list[tuple[str, str, str]] = []
        if direction in {"both", "downstream"}:
            remaining += forward[hop["id"]]
        if direction in {"both", "upstream"}:
            remaining += backward[hop["id"]]
        hop["truncated"] = any(neighbor not in seen for neighbor, _kind, _confidence in remaining)
    return hops
