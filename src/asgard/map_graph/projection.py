"""관계 그래프 상태의 결정론 Markdown 프로젝션."""

from __future__ import annotations

import tomllib
from collections import Counter, defaultdict
from pathlib import Path

from ..code_map import _safe_label

GRAPH_MARKER = "<!-- asgard:map-graph schema=1 -->"

_SEED_KINDS = ("route", "page", "command", "store", "event", "job")
_MAX_SEEDS_PER_KIND = 40
# `## Commands` 절의 상한. 다른 절보다 후한 이유는 이것이 GRAPH.md 에서 유일하게 **라우팅**
# 되는 재고이기 때문이다 — 잘린 명령은 주입면에서 후보로도 못 선다. 통째 열람은 어차피 금지고
# (Navigation contract) `map context` 가 질의별로 셋만 뽑아 간다.
# 200이던 값을 올린 자리다 (26-08-13). 번역 표로 도움말을 선언한 명령 22개를 다시 읽게 되자
# 카탈로그가 180행에서 202행이 되어 상한에 닿았고, 가나다 끝의 두 줄(`yggdrasil sync`·`tick`)이
# 밀려났다. 밀려난 줄은 그 22개가 겪던 것과 같은 증상 — 실재하는 명령이 후보로도 못 서는 것 —
# 이라 상한을 명령 수보다 앞세워 둔다. 근거와 그날 203행이 된 경위는
# `benchmarks/map-shortcut/REPORT.md` 의 "게이트가 한 번 빨간불이 됐다" 절에 있다.
_MAX_COMMAND_ROWS = 400
# 허브 절 — 개념 노드가 이만큼은 있어야 "상위"라는 말이 뜻을 갖는다.
_MIN_HUB_POPULATION = 12
_MIN_HUB_ROWS = 3
_MAX_HUB_ROWS = 12
_KIND_LABEL = {
    "route": "routes",
    "page": "pages",
    "store": "stores",
    "composable": "composables",
    "service": "services",
    "component": "components",
    "command": "commands",
    "model": "models",
    "db_access": "db",
    "api_call": "calls",
    "event": "events",
    "job": "jobs",
    "external_service": "uses",
}


def _fold(names: list[str]) -> str:
    """같은 증거는 이름 하나에 횟수로 접어 주입 예산을 지킨다."""
    counted = Counter(names)
    return ", ".join(name if total == 1 else f"{name}×{total}" for name, total in sorted(counted.items()))


def console_script(root: Path) -> str:
    """`[project.scripts]`가 선언한 실행 이름. 패키지 이름에서 추측하지 않는다."""
    try:
        with (root / "pyproject.toml").open("rb") as stream:
            data = tomllib.load(stream)
    except OSError, tomllib.TOMLDecodeError, ValueError:
        return ""
    scripts = (data.get("project") or {}).get("scripts") if isinstance(data, dict) else {}
    if not isinstance(scripts, dict):
        return ""
    names = sorted(name for name in scripts if isinstance(name, str) and name.strip())
    return _safe_label(names[0]) if names else ""


def _command_rows(state: dict, script: str) -> list[str]:
    """역할을 밝힌 명령만 GRAPH.md 라우팅 재고로 적는다."""
    prefix = f"{script} " if script else ""
    rows = [
        f"- `{prefix}{node['name']}` — {node['summary']}"
        for node in state["nodes"]
        if node["kind"] == "command" and node.get("summary")
    ]
    if not rows:
        return []
    listed = sorted(rows)[:_MAX_COMMAND_ROWS]
    lines = [
        "",
        "## Commands",
        "",
        "> 이 저장소가 이미 답을 내는 표면이다 — 핸들러를 grep 하기 전에 여기서 고른다.",
        "",
        *listed,
    ]
    if len(rows) > len(listed):
        lines.append(f"- (+{len(rows) - len(listed)} more — `asgard map list --kind command`)")
    return lines


def _hub_rows(state: dict) -> list[str]:
    """개념 노드의 인접 차수가 실제로 두드러질 때만 허브 절을 만든다."""
    degree: Counter[str] = Counter()
    for edge in state.get("edges", []):
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    concepts = {node["id"]: node for node in state["nodes"] if node["kind"] != "file" and "id" in node}
    scored = sorted(
        ((degree[node_id], node_id) for node_id in concepts if degree[node_id]),
        key=lambda row: (-row[0], row[1]),
    )
    if len(scored) < _MIN_HUB_POPULATION:
        return []
    middle = sorted(count for count, _ in scored)[len(scored) // 2]
    listed = [(count, node_id) for count, node_id in scored[:_MAX_HUB_ROWS] if count >= max(middle * 3, 4)]
    if len(listed) < _MIN_HUB_ROWS:
        return []
    return [
        "",
        "## Hubs",
        "",
        "> 인접 차수 상위 개념 — 여기를 건드리면 멀리 간다. 정확한 범위는 `asgard map impact <id>`.",
        "",
        *[f"- `{node_id}` — {concepts[node_id]['kind']}, 인접 {count}" for count, node_id in listed],
    ]


def _coverage_rows(state: dict) -> list[str]:
    raw_coverage = state.get("coverage")
    coverage: dict = raw_coverage if isinstance(raw_coverage, dict) else {}
    status = coverage.get("status", "investigated")
    raw_limits = coverage.get("limits")
    limits: list[dict] = [row for row in raw_limits if isinstance(row, dict)] if isinstance(raw_limits, list) else []
    lines = [
        "",
        "## Coverage boundaries",
        "",
        "> Named scanner gaps are evidence too. They weaken absence and blast-radius claims; details live in `map scan --json`.",
        "",
        f"- Coverage status: {status} · {len(limits)} named limits",
    ]
    for limit in limits:
        code = str(limit.get("code") or "unknown")
        subject = str(limit.get("subject") or "repository")
        detail = str(limit.get("detail") or "unspecified scanner boundary")
        files = limit.get("files") if isinstance(limit.get("files"), list) else []
        candidates = limit.get("candidates") if isinstance(limit.get("candidates"), list) else []
        counts = []
        if files:
            counts.append(f"files {len(files)}")
        if candidates:
            counts.append(f"candidates {len(candidates)}")
        tail = f" · {' · '.join(counts)}" if counts else ""
        lines.append(f"- {code} [{subject}] — {detail}{tail}")
    return lines


def render_graph_md(state: dict, script: str = "") -> str:
    """타임스탬프·리비전 없이 구조만 담는 결정론 카탈로그."""
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
        GRAPH_MARKER,
        "# Relation Graph",
        "",
        "> Asgard managed relation catalog. Regenerate with `asgard map scan`; do not hand-edit.",
        "> `?` marks candidate evidence — verify at the cited source before asserting.",
        "",
        f"- Evidence summary: {summary or 'none'}",
    ]
    lines += _coverage_rows(state)
    lines += _hub_rows(state)
    lines += _command_rows(state, script)
    lines += ["", "## Relations by file", ""]
    ranked = sorted(per_file.items(), key=lambda item: (-sum(len(v) for v in item[1].values()), item[0]))
    for path, kinds in ranked:
        parts = []
        for kind in _KIND_LABEL:
            if kinds.get(kind):
                parts.append(f"{_KIND_LABEL[kind]}: {_fold(kinds[kind])}")
        lines.append(f"- `{path}` — " + " · ".join(parts))
    if flows:
        lines += ["", "## Flows", ""]
        for source in sorted(flows):
            lines.append(f"- `{names.get(source, source)}` — " + " · ".join(sorted(flows[source])))
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
