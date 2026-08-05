"""Deterministic impact dossier built from one fresh relation-graph snapshot.

The graph is a fast structural map, not proof of behavior.  This module keeps that
boundary machine-readable: confirmed/candidate evidence, exact source spans, named
coverage limits, and a stable revision travel together in one report.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict

from .bridge import related_records
from .graph import fresh_state, node_span, trace


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _exact_read(file: str, line_start: int, line_end: int) -> str:
    if not file:
        return ""
    if line_start <= 0:
        return file
    suffix = str(line_start) if line_end <= line_start else f"{line_start}-{line_end}"
    return f"{file}:{suffix}"


def _evidence_row(origin: str, direction: str, hop: dict, source_revision: str) -> dict:
    file = str(hop.get("file") or "")
    line_start = int(hop.get("line") or 0)
    line_end = max(line_start, int(hop.get("line_end") or line_start))
    confidence = (
        "confirmed"
        if hop.get("confidence") == "confirmed" and hop.get("via_confidence", "confirmed") == "confirmed"
        else "candidate"
    )
    identity = [
        str(hop.get("kind") or ""),
        str(hop.get("id") or ""),
        direction,
        origin,
        str(hop.get("via") or ""),
        file,
        str(line_start) if line_start else "",
        str(line_end) if line_end else "",
    ]
    missing = []
    if confidence != "confirmed":
        missing.append("candidate node or edge requires bounded source confirmation")
    if hop.get("truncated"):
        missing.append("unvisited edges remain beyond the configured depth")
    return {
        "evidence_id": _digest(identity),
        "target": str(hop.get("id") or ""),
        "target_kind": str(hop.get("kind") or ""),
        "direction": direction,
        "depth": int(hop.get("depth") or 0),
        "relation": str(hop.get("via") or ""),
        "confidence": confidence,
        "file": file,
        "line_start": line_start,
        "line_end": line_end,
        "source_revision": source_revision,
        "missing_evidence": missing,
        "next_exact_read": _exact_read(file, line_start, line_end),
    }


def _limit(
    code: str,
    detail: str,
    *,
    subject: str = "",
    files: list[str] | tuple[str, ...] = (),
    candidates: list[str] | tuple[str, ...] = (),
    next_action: str = "",
) -> dict:
    return {
        "code": code,
        "subject": subject,
        "detail": detail,
        "files": sorted(set(files)),
        "candidates": sorted(set(candidates)),
        "next_action": next_action,
    }


def _sort_objects(rows: list[dict]) -> list[dict]:
    unique = {_canonical(row): row for row in rows}
    return [unique[key] for key in sorted(unique)]


def impact_report(
    root: str | os.PathLike[str],
    node_id: str,
    *,
    depth: int = 4,
    state: dict | None = None,
) -> dict:
    """Return one revision-bound, evidence-separated impact snapshot.

    ``fresh_state`` proves that the derived graph matches the current source inventory.
    It does not turn graph adjacency into a behavioral claim; every row therefore carries
    the bounded source region that must be read before making one.
    """
    if state is None:
        state = fresh_state(root)
    nodes = {node["id"]: node for node in state["nodes"]}
    # ``trace`` owns id validation and depth bounds, so both direct API and CLI paths fail alike.
    upstream = trace(root, node_id, depth=depth, direction="upstream", state=state)
    downstream = trace(root, node_id, depth=depth, direction="downstream", state=state)
    source_revision = state["revision"]
    origin_file, origin_line, origin_line_end = node_span(nodes[node_id])
    origin = {
        "id": node_id,
        "kind": str(nodes[node_id].get("kind") or ""),
        "name": str(nodes[node_id].get("name") or ""),
        "confidence": str(nodes[node_id].get("confidence") or "candidate"),
        "file": origin_file,
        "line_start": origin_line,
        "line_end": origin_line_end,
        "next_exact_read": _exact_read(origin_file, origin_line, origin_line_end),
    }
    evidence = [
        *(_evidence_row(node_id, "upstream", hop, source_revision) for hop in upstream),
        *(_evidence_row(node_id, "downstream", hop, source_revision) for hop in downstream),
    ]
    evidence.sort(key=lambda row: row["evidence_id"])

    raw_coverage = state.get("coverage")
    coverage: dict = raw_coverage if isinstance(raw_coverage, dict) else {}
    raw_limits = coverage.get("limits")
    limits = [row for row in raw_limits if isinstance(row, dict)] if isinstance(raw_limits, list) else []
    source_parity = "partial" if limits else "confirmed"
    for direction, hops in (("upstream", upstream), ("downstream", downstream)):
        frontier = [str(hop["id"]) for hop in hops if hop.get("truncated")]
        if frontier:
            limits.append(
                _limit(
                    "trace_depth_frontier",
                    f"{len(frontier)} nodes retain unvisited edges at depth {depth}",
                    subject=direction,
                    candidates=frontier,
                    next_action=(
                        f"rerun impact with --depth {depth + 1}"
                        if depth < 8
                        else "read the named frontier sources directly; graph depth is at its maximum"
                    ),
                )
            )
        if not hops:
            limits.append(
                _limit(
                    "empty_graph_direction",
                    "no configured graph edge was found; this is not evidence of no dependency",
                    subject=direction,
                    next_action="search the origin symbol and source anchor for graph-invisible consumers or dependencies",
                )
            )
    candidate_rows = [row for row in evidence if row["confidence"] != "confirmed"]
    if candidate_rows:
        limits.append(
            _limit(
                "candidate_graph_evidence",
                f"{len(candidate_rows)} impact rows depend on candidate nodes or edges",
                files=[row["file"] for row in candidate_rows if row["file"]],
                candidates=[row["target"] for row in candidate_rows],
                next_action="read each named source span before promoting it to confirmed impact",
            )
        )
    records = [asdict(record) for record in related_records(root, nodes[node_id])]
    records.sort(key=lambda row: (row["file"], row["match"], row["title"]))
    stale_records = [row for row in records if row.get("validity") == "stale"]
    if stale_records:
        limits.append(
            _limit(
                "stale_related_record",
                f"{len(stale_records)} related project-memory records were captured at another source revision",
                files=[str(row["file"]) for row in stale_records],
                candidates=[str(row["record_id"]) for row in stale_records],
                next_action="re-read the record provenance and current source before applying its constraint",
            )
        )
    limits = _sort_objects(limits)
    coverage_report = {
        "status": "partial" if limits else "investigated",
        "depth": depth,
        "upstream_truncated": sum(1 for hop in upstream if hop.get("truncated")),
        "downstream_truncated": sum(1 for hop in downstream if hop.get("truncated")),
        "candidates": len(candidate_rows),
        "frontier": {
            "upstream": sorted(str(hop["id"]) for hop in upstream if hop.get("truncated")),
            "downstream": sorted(str(hop["id"]) for hop in downstream if hop.get("truncated")),
        },
        "limits": limits,
    }
    snapshot = {
        "schema": 1,
        "source_revision": source_revision,
        "source_parity": source_parity,
        "from": node_id,
        "origin": origin,
        "upstream": upstream,
        "downstream": downstream,
        "evidence": evidence,
        "coverage": coverage_report,
        "records": records,
    }
    snapshot["impact_revision"] = _digest(snapshot)
    return snapshot
