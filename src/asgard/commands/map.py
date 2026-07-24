"""Project-map generation, refresh, context rendering, and legacy `setup map` compatibility."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from .. import ui
from ..code_map import MapError, check_map, refresh_map
from ..map_context import build_map_context, validate_area_maps


def _project_root(start: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return str(Path(proc.stdout.strip()).resolve())
    except OSError, subprocess.TimeoutExpired:
        pass
    return str(Path(start).resolve())


def _gitignore_preview(root: str) -> tuple[Path, str | None, str, bool, Path, str, bool]:
    from .setup import _ASGARD_GITIGNORE, merge_gitignore

    path = Path(root, ".gitignore")
    try:
        previous = path.read_text(encoding="utf-8")
    except OSError:
        previous = None
    merged = merge_gitignore(previous)
    internal = Path(root, ".asgard", ".gitignore")
    try:
        internal_previous = internal.read_text(encoding="utf-8")
    except OSError:
        internal_previous = None
    # Existing projects may intentionally keep project settings ignored or add local runtime
    # exceptions. Map refresh owns the map, not the whole internal ignore policy; seed only when
    # absent and let check_map's trackability test catch rules that actually hide PROJECT.md.
    internal_merged = _ASGARD_GITIGNORE if internal_previous is None else internal_previous
    internal_changed = internal_previous is None
    return path, previous, merged, merged != previous, internal, internal_merged, internal_changed


def _atomic_root_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def run_setup_map(*, check: bool = False, dry_run: bool = False, json_out: bool = False, quiet: bool = False) -> int:
    root = _project_root(os.getcwd())
    ui.set_quiet(quiet or json_out)
    if check and dry_run:
        payload = {"error": "--check and --dry-run are mutually exclusive"}
        if json_out:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            ui.fail(payload["error"])
        return 2
    ignore, _previous, merged, gitignore_changed, internal_ignore, internal_merged, internal_changed = (
        _gitignore_preview(root)
    )
    try:
        if check:
            result = check_map(root)
            ok = result.ok and not gitignore_changed and not internal_changed
            payload = asdict(result)
            payload.update(
                {"ok": ok, "gitignore_changed": gitignore_changed, "asgard_gitignore_changed": internal_changed}
            )
            if json_out:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            elif ok:
                ui.done("project map is current")
            else:
                ui.warn("project map drift detected")
                for path in result.added:
                    ui.step(f"added   {path}")
                for path in result.removed:
                    ui.step(f"removed {path}")
                ui.step("run: asgard map update")
            return 0 if ok else 1

        preview = refresh_map(root, dry_run=True)
        changed = preview.changed or preview.index_changed or gitignore_changed or internal_changed
        result = preview
        if not dry_run:
            if gitignore_changed:
                _atomic_root_write(ignore, merged)
            result = refresh_map(root)
            if internal_changed:
                _atomic_root_write(internal_ignore, internal_merged)
        payload = asdict(result)
        payload.update(
            {
                "project_changed": preview.changed,
                "changed": changed,
                "index_changed": preview.index_changed,
                "gitignore_changed": gitignore_changed,
                "asgard_gitignore_changed": internal_changed,
                "dry_run": dry_run,
            }
        )
    except (MapError, OSError) as exc:
        payload = {"error": str(exc)}
        if json_out:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif dry_run:
        ui.head("setup · project map preview")
        ui.step(f"{result.files_scanned} files → {result.landmarks} landmarks")
        ui.step(("would update " if changed else "already current ") + result.path)
    else:
        ui.head("setup · project map")
        ui.ok(f"{result.files_scanned} files → {result.landmarks} landmarks")
        ui.done(("updated " if changed else "current ") + result.path)
    return 0


def run_map_generate(*, dry_run: bool = False, json_out: bool = False, quiet: bool = False) -> int:
    """Create the map if missing; repeated generation is deliberately idempotent."""
    return run_setup_map(dry_run=dry_run, json_out=json_out, quiet=quiet)


def run_map_update(*, dry_run: bool = False, json_out: bool = False, quiet: bool = False) -> int:
    """Refresh the same managed projection used by generate."""
    return run_setup_map(dry_run=dry_run, json_out=json_out, quiet=quiet)


def run_map_check(*, json_out: bool = False, quiet: bool = False) -> int:
    root = _project_root(os.getcwd())
    ui.set_quiet(quiet or json_out)
    try:
        result = check_map(root)
        _, issues = validate_area_maps(root)
        _, _, _, gitignore_changed, _, _, internal_changed = _gitignore_preview(root)
        ok = result.ok and not issues and not gitignore_changed and not internal_changed
    except (MapError, OSError) as exc:
        if json_out:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    payload = asdict(result)
    payload.update(
        {
            "ok": ok,
            "gitignore_changed": gitignore_changed,
            "asgard_gitignore_changed": internal_changed,
            "area_issues": [asdict(issue) for issue in issues],
        }
    )
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif ok:
        ui.done("project map is current")
    else:
        ui.warn("project map drift or invalid area map detected")
        for path in result.added:
            ui.step(f"added   {path}")
        for path in result.removed:
            ui.step(f"removed {path}")
        for issue in issues:
            ui.step(f"{issue.source}: {issue.reason}")
        if gitignore_changed:
            ui.step("gitignore: .gitignore is missing the Asgard map rules")
        if internal_changed:
            ui.step("gitignore: .asgard/.gitignore seed is missing")
        ui.step("run: asgard map update")
    return 0 if ok else 1


def run_map_scan(*, dry_run: bool = False, json_out: bool = False, quiet: bool = False) -> int:
    """관계 그래프 재구축 — 결정론 추출 (LLM 0토큰)."""
    root = _project_root(os.getcwd())
    ui.set_quiet(quiet or json_out)
    from ..map_graph import GraphError, scan_graph

    try:
        result = scan_graph(root, dry_run=dry_run)
    except (GraphError, MapError, OSError) as exc:
        if json_out:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps({**asdict(result), "dry_run": dry_run}, ensure_ascii=False, indent=2))
    else:
        ui.head("map · relation graph")
        ui.ok(
            f"{result.files_scanned} files → {result.evidence_count} evidence · {result.nodes} nodes"
            f" · {result.edges} edges · {result.flows} flows · {result.api_links} api links"
        )
        if dry_run:
            ui.step(("would update " if result.changed else "already current ") + result.graph_md_path)
        else:
            ui.done(("updated " if result.changed else "current ") + result.graph_md_path)
    return 0


def _resolve_concept(state: dict, node_id: str) -> tuple[str, str | None]:
    """개념어 원콜 진입 — 정확한 id 가 아니고 매치가 정확히 하나면 그 노드로 해석한다.

    복수 매치는 해석하지 않는다(지어내기 금지) — trace 가 앵커 동봉 후보 목록으로 거부한다.
    """
    from ..map_graph import concept_candidates

    if any(node.get("id") == node_id for node in state.get("nodes", ())):
        return node_id, None
    candidates = concept_candidates(state, node_id)
    if len(candidates) == 1:
        return candidates[0]["id"], node_id
    return node_id, None


def run_map_trace(
    node_id: str, *, depth: int = 2, direction: str = "both", kinds: str = "", json_out: bool = False
) -> int:
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    from ..map_graph import GraphError, fresh_state, related_records, trace

    kind_set = {part.strip() for part in kinds.split(",") if part.strip()} or None
    try:
        state = fresh_state(root)
        node_id, resolved_from = _resolve_concept(state, node_id)
        hops = trace(root, node_id, depth=depth, direction=direction, kinds=kind_set, state=state)
    except (GraphError, OSError) as exc:
        if json_out:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    origin = next((node for node in state["nodes"] if node.get("id") == node_id), {})
    records = [asdict(record) for record in related_records(root, origin)] if origin else []
    if json_out:
        payload = {"from": node_id, "resolved_from": resolved_from, "hops": hops, "records": records}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    ui.head(f"map · trace {node_id}")
    if resolved_from:
        ui.step(f"resolved: {resolved_from} → {node_id} (유일 매치 — 다르면 `asgard map list` 로 확인)")
    if not hops:
        ui.step("no adjacent edges — 인접 지도가 비어 있다 (전수 부재의 증거가 아님)")
    for hop in hops:
        mark = (
            "" if hop["confidence"] == "confirmed" and hop.get("via_confidence", "confirmed") == "confirmed" else " ?"
        )
        anchor = f" @ {hop['file']}" + (f":{hop['line']}" if hop.get("line") else "") if hop.get("file") else ""
        ui.step(f"{'  ' * hop['depth']}{hop['via']} → {hop['id']}{mark}{anchor}")
    truncated = sum(1 for hop in hops if hop.get("truncated"))
    if truncated:
        ui.step(f"{truncated} nodes at depth limit still have unexplored edges — raise --depth to continue")
    for record in records:
        ui.step(f"관련 기록: {record['title']} [{record['match']}]")
    return 0


def run_map_list(*, kind: str = "", json_out: bool = False) -> int:
    """노드 카탈로그 — 정확한 trace 시드(id)와 대표 앵커를 종류별로 열람한다."""
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    from ..map_graph import EVIDENCE_KINDS, GraphError, fresh_state, node_anchor

    try:
        if kind and kind != "file" and kind not in EVIDENCE_KINDS:
            allowed = ", ".join((*EVIDENCE_KINDS, "file"))
            raise GraphError(f"unknown node kind: {kind} — expected one of: {allowed}")
        state = fresh_state(root)
    except (GraphError, OSError) as exc:
        if json_out:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    nodes = [node for node in state["nodes"] if not kind or node["kind"] == kind]
    nodes.sort(key=lambda node: (node["kind"], node["id"]))
    rows = []
    for node in nodes:
        file, line = node_anchor(node)
        rows.append(
            {
                "id": node["id"],
                "kind": node["kind"],
                "name": node["name"],
                "confidence": node["confidence"],
                "file": file,
                "line": line,
                "locations": len(node.get("files") or []),
            }
        )
    if json_out:
        print(json.dumps({"kind": kind or None, "total": len(rows), "nodes": rows}, ensure_ascii=False, indent=2))
        return 0
    ui.head("map · list" + (f" · {kind}" if kind else ""))
    if not rows:
        ui.step("no nodes — `asgard map scan` 이후에도 비면 해당 종류의 증거가 없는 것이다")
    current_kind = ""
    for row in rows:
        if not kind and row["kind"] != current_kind:
            current_kind = row["kind"]
            ui.step(f"[{current_kind}]")
        mark = "" if row["confidence"] == "confirmed" else " ?"
        anchor = f" @ {row['file']}" + (f":{row['line']}" if row["line"] else "") if row["file"] else ""
        ui.step(f"- {row['id']}{mark}{anchor}")
    return 0


def run_map_impact(node_id: str, *, depth: int = 4, json_out: bool = False) -> int:
    """양방향 영향 지도 — 업스트림(도달 경로)과 다운스트림(파급 효과)을 한 번에, 한계와 함께.

    전수 블라스트 레디우스 증명이 아니다: 정적 레인 증거의 인접 지도이며, 절단·candidate
    수를 커버리지 한계로 함께 보고한다 (no-edge ≠ no-dependency).
    """
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    from ..map_graph import GraphError, fresh_state, related_records, trace

    try:
        state = fresh_state(root)
        node_id, resolved_from = _resolve_concept(state, node_id)
        upstream = trace(root, node_id, depth=depth, direction="upstream", state=state)
        downstream = trace(root, node_id, depth=depth, direction="downstream", state=state)
    except (GraphError, OSError) as exc:
        if json_out:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    origin = next((node for node in state["nodes"] if node.get("id") == node_id), {})
    records = [asdict(record) for record in related_records(root, origin)] if origin else []
    candidates = sum(
        1
        for hop in [*upstream, *downstream]
        if hop["confidence"] != "confirmed" or hop.get("via_confidence", "confirmed") != "confirmed"
    )
    coverage = {
        "depth": depth,
        "upstream_truncated": sum(1 for hop in upstream if hop.get("truncated")),
        "downstream_truncated": sum(1 for hop in downstream if hop.get("truncated")),
        "candidates": candidates,
    }
    if json_out:
        payload = {
            "from": node_id,
            "resolved_from": resolved_from,
            "upstream": upstream,
            "downstream": downstream,
            "records": records,
            "coverage": coverage,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    ui.head(f"map · impact {node_id}")
    if resolved_from:
        ui.step(f"resolved: {resolved_from} → {node_id} (유일 매치 — 다르면 `asgard map list` 로 확인)")
    for label, hops in (("upstream — 이 노드에 닿는 것", upstream), ("downstream — 이 노드가 만지는 것", downstream)):
        ui.step(f"[{label}]")
        if not hops:
            ui.step("  no adjacent edges — 부재의 증거가 아니다")
        for hop in sorted(hops, key=lambda h: (h["depth"], h["kind"], h["id"])):
            mark = (
                ""
                if hop["confidence"] == "confirmed" and hop.get("via_confidence", "confirmed") == "confirmed"
                else " ?"
            )
            anchor = f" @ {hop['file']}" + (f":{hop['line']}" if hop.get("line") else "") if hop.get("file") else ""
            tail = " …" if hop.get("truncated") else ""
            ui.step(f"  d{hop['depth']} {hop['via']} → {hop['id']}{mark}{anchor}{tail}")
    truncated = coverage["upstream_truncated"] + coverage["downstream_truncated"]
    ui.step(f"coverage: depth {depth} · all edge kinds · candidates {candidates}")
    if truncated:
        ui.step(f"{truncated} nodes at depth limit still have unexplored edges — raise --depth to continue")
    ui.step("no-edge ≠ no-dependency — 정적 레인 인접 지도다; `?` candidate 는 원문 확인 전 단정 금지")
    for record in records:
        ui.step(f"관련 기록: {record['title']} [{record['match']}]")
    return 0


def run_map_view(*, open_browser: bool = True, json_out: bool = False) -> int:
    """그래프 뷰 HTML 생성·오픈 — 상태가 없으면 먼저 스캔한다."""
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    from ..map_graph import GraphError, scan_graph, write_view

    try:
        # 뷰는 관측 표면이다. 열 때마다 결정론 스캔해 낡은 상태를 사실처럼 보여주지 않는다.
        scan_graph(root)
        path = write_view(root)
    except (GraphError, MapError, OSError) as exc:
        if json_out:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps({"path": path}, ensure_ascii=False))
        return 0
    ui.head("map · view")
    ui.done(path)
    if open_browser:
        import webbrowser

        uri = Path(path).as_uri()
        if not webbrowser.open(uri):  # pragma: no cover - 데스크톱 환경 의존
            ui.step(f"브라우저를 못 열었다 — 직접 열기: {uri}")
    return 0


def run_map_context(
    query: str,
    *,
    refresh: bool = False,
    managed_only: bool = False,
    json_out: bool = False,
) -> int:
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    try:
        result = build_map_context(root, query, refresh=refresh, managed_only=managed_only)
    except (MapError, OSError) as exc:
        if json_out:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    if json_out:
        print(
            json.dumps(
                {
                    "text": result.text,
                    "managed_hash": result.managed_hash,
                    "entries": [asdict(entry) for entry in result.entries],
                    "issues": [asdict(issue) for issue in result.issues],
                    "refreshed": asdict(result.refresh) if result.refresh else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif result.text:
        print(result.text)
    if not json_out:
        for issue in result.issues:
            ui.warn(f"{issue.source}: {issue.reason}")
    return 0
