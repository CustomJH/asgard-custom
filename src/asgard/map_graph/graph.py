"""관계 그래프 빌드·저장·프로젝션·탐색.

소유권: 그래프 상태는 `.asgard/state/map-graph.json`(미추적), 카탈로그 프로젝션은
`.asgard/map/GRAPH.md`(추적·팀 공유)만 소유한다. 프로젝션은 PROJECT.md 와 같은
`- `path` — role` 엔트리 문법을 지켜 맵 컨텍스트에 그대로 융합된다.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..code_map import MapError, _atomic_write, _files, _map_dir, _safe_component
from .evidence import Evidence
from .extract_java import extract_java, extract_mapper_xml, extract_proc, extract_sql
from .extract_python import extract_python
from .extract_tsjs import extract_tsjs
from .spring_props import SpringProps

GRAPH_FILE = "GRAPH.md"
_GRAPH_MARKER = "<!-- asgard:map-graph schema=1 -->"
_STATE_RELATIVE = Path(".asgard") / "state" / "map-graph.json"
_MAX_SOURCE_BYTES = 512 * 1024
_TSJS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".prisma"}
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
}
EDGE_KINDS = ("declares", "calls", "touches", "uses", "emits")
# 스팬 신뢰 확장자 — AST(.py)·주석 제거 후 중괄호 균형(.java)은 포함 관계가 결정론적이다.
# 나머지(원문 정규식 근사 스팬)는 플로우 엣지를 candidate 로 캡한다.
_STRUCTURAL_SPAN_SUFFIXES = (".py", ".java")
_KIND_LABEL = {
    "route": "routes",
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


def _collect(root: Path) -> tuple[int, list[Evidence], str]:
    scanned = 0
    collected: list[Evidence] = []
    props = SpringProps()
    digest = hashlib.sha256()
    for rel in _files(root):
        suffix = rel.suffix.lower()
        is_config = SpringProps.is_config(rel.name)
        if suffix not in _EXTRACTORS and not is_config:
            continue
        if _is_test_path(rel):
            continue
        full = root / rel
        try:
            if full.stat().st_size > _MAX_SOURCE_BYTES:
                continue
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
        collected.extend(_EXTRACTORS[suffix](rel.as_posix(), source))
    return scanned, props.promote(collected), "source-sha256:" + digest.hexdigest()


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


def _build_state(scanned: int, collected: list[Evidence], revision: str) -> dict:
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
        edges[(file_id, item.node_id, _EDGE_KIND[item.kind])] = "confirmed"
    flows = _flow_edges(collected)
    edges.update(flows)
    for node in nodes.values():
        node["files"].sort(key=lambda loc: (loc["file"], loc["line"]))
    return {
        "schema": 1,
        "revision": revision,
        "counts": {
            "files_scanned": scanned,
            "evidence": len(collected),
            "nodes": len(nodes),
            "edges": len(edges),
            "flows": len(flows),
        },
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": [
            {"source": source, "target": target, "kind": kind, "confidence": confidence}
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
    lines += [
        "",
        "## Navigation contract",
        "",
        "- Trace edges with `asgard map trace --from <node-id>` (`--kinds touches,calls` filters edge kinds).",
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
    scanned, collected, revision = _collect(base)
    state = _build_state(scanned, collected, revision)
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


def trace(
    root: str | os.PathLike[str],
    node_id: str,
    *,
    depth: int = 2,
    direction: str = "both",
    kinds: set[str] | None = None,
) -> list[dict]:
    """BFS 로 확인된 엣지만 따라간다 — 전수 블라스트 레디우스가 아니라 인접 지도다.

    `kinds` 는 따라갈 엣지 종류의 화이트리스트다 — 예: DB 앵커 업스트림에 {"touches", "calls"}
    를 주면 한 번의 호출로 DB→핸들러→호출 화면까지 조인해 회수한다.
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
    state = graph_state(root)
    if state is None:
        raise GraphError("relation graph state missing — run `asgard map scan` first")
    if state["revision"] != _collect(Path(root).resolve())[2]:
        raise GraphError("relation graph state is stale — run `asgard map scan` first")
    nodes = {node["id"]: node for node in state["nodes"]}
    if node_id not in nodes:
        near = sorted(nid for nid in nodes if node_id.casefold() in nid.casefold())[:5]
        hint = f" — candidates: {', '.join(near)}" if near else ""
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
            hops.append(
                {
                    "id": neighbor,
                    "kind": node["kind"],
                    "name": node["name"],
                    "confidence": node["confidence"],
                    "depth": level + 1,
                    "via": kind,
                    "via_confidence": edge_confidence,
                }
            )
            frontier.append((neighbor, level + 1, kind))
    return hops
