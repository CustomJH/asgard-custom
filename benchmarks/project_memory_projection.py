#!/usr/bin/env python3
"""Benchmark Asgard's rebuildable project-memory projection.

Local mode compares the pre-projection behavior with deterministic AST fingerprints,
manifest reconciliation, and automatic-context freshness gates. Live mode uses two
throwaway Hindsight banks and always deletes them in a finally block.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, TypeVar
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from asgard import project_memory  # noqa: E402
from asgard.memory_bridge import find_config, server_recall, server_retain_items  # noqa: E402
from asgard.memory_context import _eligible_for_automatic_context  # noqa: E402

T = TypeVar("T")
U = TypeVar("U")


def _write(root: str, relative: str, content: str) -> None:
    path = Path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fixture(root: str, count: int) -> list[str]:
    paths: list[str] = []
    for index in range(count):
        path = f"src/components/component_{index:03d}.py"
        dependency = f"services.store_{index % 7}"
        _write(
            root,
            path,
            f'''"""Component {index} project boundary."""\n\nfrom {dependency} import Bank\n\n\nclass Component{index:03d}:\n    def recall(self, query: str, limit: int = 5):\n        return Bank().recall(query, limit=limit)\n\n\ndef retain_{index:03d}(item):\n    return Bank().retain(item)\n''',
        )
        paths.append(path)
    _write(root, "docs/architecture.md", "# Architecture\nProject memory is a derived projection over canonical source.\n")
    paths.append("docs/architecture.md")
    return paths


def _baseline_scan(root: str, changed: list[str]) -> list[dict]:
    """Behavioral model of the old scanner: policy scoring + content hash only."""
    changed_set = set(changed)
    rows: list[dict] = []
    paths = project_memory._git_paths(root)
    if paths is None:
        paths = project_memory._walk_paths(root)
    for path in sorted(set(paths) | changed_set):
        normalized = path.replace(os.sep, "/")
        parts = [part.lower() for part in normalized.split("/")]
        name = parts[-1] if parts else ""
        if (
            not normalized
            or any(part in project_memory._SKIP_DIRS for part in parts[:-1])
            or name in project_memory._SECRET_NAMES
            or (parts and parts[0] in {"tests", "test", "spikes", "examples"})
            or name.endswith((".lock", ".min.js", ".map"))
            or not project_memory._is_text_candidate(normalized)
        ):
            continue
        full = os.path.realpath(os.path.join(root, normalized))
        try:
            if not os.path.isfile(full) or os.path.getsize(full) > project_memory.MAX_ARTIFACT_BYTES:
                continue
            content = Path(full).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if not content.strip() or project_memory.scan_secrets(content):
            continue
        score, kind, importance, reasons = project_memory._assess(normalized, content, normalized in changed_set)
        if score < 35:
            continue
        rows.append(
            {
                "path": normalized,
                "content": content,
                "content_hash": hashlib.sha256(content.encode()).hexdigest(),
                "kind": kind,
                "importance": importance,
                "score": score,
                "reasons": reasons,
            }
        )
    return rows


def _timed_pair(first: Callable[[], T], second: Callable[[], U], repeats: int = 7) -> tuple[float, T, float, U]:
    durations = [[], []]
    first_result: T | None = None
    second_result: U | None = None
    for repeat in range(repeats):
        for index in ((0, 1) if repeat % 2 == 0 else (1, 0)):
            started = time.perf_counter()
            if index == 0:
                first_result = first()
            else:
                second_result = second()
            durations[index].append((time.perf_counter() - started) * 1000)
    assert first_result is not None and second_result is not None
    return statistics.median(durations[0]), first_result, statistics.median(durations[1]), second_result


def local_benchmark(files: int) -> dict:
    root = tempfile.mkdtemp(prefix="asgard-projection-bench-")
    try:
        changed = _fixture(root, files)
        baseline_ms, baseline_rows, enhanced_ms, enhanced_rows = _timed_pair(
            lambda: _baseline_scan(root, changed),
            lambda: project_memory.scan_project(root, changed_paths=changed),
        )
        candidates = list(enhanced_rows)

        first = next(candidate for candidate in candidates if candidate.path == "src/components/component_000.py")
        source = Path(root, first.path)
        original = source.read_text(encoding="utf-8")
        source.write_text(original.replace("return Bank().retain(item)", "return {'retained': Bank().retain(item)}"), encoding="utf-8")
        body_only = next(c for c in project_memory.scan_project(root, changed_paths=[first.path]) if c.path == first.path)
        source.write_text(original.replace("def retain_000(item):", "def retain_000(item, replace: bool = False):"), encoding="utf-8")
        signature = next(c for c in project_memory.scan_project(root, changed_paths=[first.path]) if c.path == first.path)
        source.write_text(original, encoding="utf-8")
        candidates = project_memory.scan_project(root, changed_paths=changed)

        cfg = {"server": "http://benchmark.invalid", "bank": "projection-local-bench"}
        captured: list[list[dict]] = []

        def retain(_cfg, items):
            captured.append(items)
            return {"success": True}

        with mock.patch("asgard.project_memory.server_retain_items", side_effect=retain):
            initial = project_memory.sync_artifacts(root, cfg, candidates, source_revision="HEAD=initial")
            noop = project_memory.sync_artifacts(root, cfg, candidates, source_revision="HEAD=initial")
            deleted_path = candidates[-1].path
            os.remove(os.path.join(root, deleted_path))
            after_delete = [candidate for candidate in candidates if candidate.path != deleted_path]
            deletion = project_memory.sync_artifacts(root, cfg, after_delete, source_revision="HEAD=deleted")

        active = after_delete[0]
        active_metadata = project_memory.artifact_item(active, cfg["bank"], "HEAD=initial")["metadata"]
        active_allowed = _eligible_for_automatic_context(root, active_metadata)
        Path(root, active.path).write_text("# unsynchronized replacement\n", encoding="utf-8")
        stale_allowed = _eligible_for_automatic_context(root, active_metadata)
        baseline_accepted_stale_classes = 3  # superseded, unverified, and raw turn all passed the old text-only gate
        enhanced_accepted_stale_classes = sum(
            _eligible_for_automatic_context(
                root,
                metadata,
            )
            for metadata in (
                {"record_id": "old", "status": "superseded", "confidence": "verified"},
                {"record_id": "draft", "status": "active", "confidence": "observed"},
                {"kind": "turn", "status": "active", "trust": "untrusted-conversation"},
            )
        )

        overhead = ((enhanced_ms / baseline_ms) - 1) * 100 if baseline_ms else 0.0
        return {
            "mode": "local",
            "fixture_files": files + 1,
            "candidate_count": len(candidates),
            "scan_latency_ms_median": {"baseline": round(baseline_ms, 3), "enhanced": round(enhanced_ms, 3)},
            "scan_overhead_percent": round(overhead, 2),
            "structural_semantics": {
                "body_only_keeps_structural_hash": first.structural_hash == body_only.structural_hash,
                "signature_change_updates_structural_hash": first.structural_hash != signature.structural_hash,
            },
            "publish_calls": {
                "baseline_equivalent_full_noop_items": len(baseline_rows),
                "enhanced_initial_items": initial["items_count"],
                "enhanced_noop_items": noop["items_count"],
                "enhanced_delete_tombstones": deletion["deleted_count"],
            },
            "freshness_gate": {
                "active_projection_allowed": bool(active_allowed),
                "unsynchronized_source_allowed": bool(stale_allowed),
                "baseline_accepted_stale_classes": baseline_accepted_stale_classes,
                "enhanced_accepted_stale_classes": enhanced_accepted_stale_classes,
            },
            "checks_passed": bool(
                first.structural_hash == body_only.structural_hash
                and first.structural_hash != signature.structural_hash
                and noop["items_count"] == 0
                and deletion["deleted_count"] == 1
                and active_allowed
                and not stale_allowed
                and enhanced_accepted_stale_classes == 0
            ),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _json_request(url: str, method: str, payload: dict | None = None, timeout: int = 180) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def _bank_absent(server: str, bank: str) -> bool:
    response = _json_request(f"{server}/v1/default/banks", "GET", timeout=30)
    banks = response.get("banks")
    return isinstance(banks, list) and all(not isinstance(item, dict) or item.get("bank_id") != bank for item in banks)


def _hit_source(hit: dict) -> str:
    raw_metadata = hit.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    if metadata.get("source"):
        return str(metadata["source"])
    text = str(hit.get("text") or "")
    for line in text.splitlines():
        if line.startswith("Path: "):
            return line[6:].strip()
    return ""


def live_benchmark() -> dict:
    found = find_config(str(ROOT))
    if not found:
        raise RuntimeError("project memory is not connected")
    _, base_cfg = found
    server = str(base_cfg["server"]).rstrip("/")
    suffix = uuid.uuid4().hex[:10]
    bank_ids = {"baseline": f"asgard-bench-baseline-{suffix}", "enhanced": f"asgard-bench-enhanced-{suffix}"}
    cleanup: dict[str, bool] = {name: False for name in bank_ids}
    benchmark_result: dict | None = None
    root = tempfile.mkdtemp(prefix="asgard-live-projection-bench-")
    try:
        paths = _fixture(root, 6)[:-1]
        candidates = project_memory.scan_project(root, changed_paths=paths)
        candidates = [candidate for candidate in candidates if candidate.path.endswith(".py")]
        create_payload = {
            "retain_extraction_mode": "concise",
            "enable_observations": False,
            "retain_mission": "Index parser-verified project structure and source facts without speculation.",
        }
        for bank in bank_ids.values():
            _json_request(f"{server}/v1/default/banks/{bank}", "PUT", create_payload)

        baseline_items = []
        for candidate in candidates:
            baseline_header = (
                f"[ProjectArtifact:{candidate.kind}]\n"
                f"Path: {candidate.path}\n"
                "Revision: HEAD=benchmark\n"
                f"Content-SHA256: {candidate.content_hash}\n"
                f"Importance: {candidate.importance}\n\n"
            )
            baseline_items.append(
                {
                    "content": baseline_header + candidate.content,
                    "context": f"asgard project artifact {candidate.kind}",
                    "document_id": project_memory._artifact_document_id(candidate.path),
                    "update_mode": "replace",
                    "metadata": {
                        "source": candidate.path,
                        "source_revision": "HEAD=benchmark",
                        "content_hash": candidate.content_hash,
                        "kind": candidate.kind,
                        "importance": candidate.importance,
                        "scope": "project",
                    },
                }
            )
        configs = {
            name: {**base_cfg, "bank": bank, "timeout": 240}
            for name, bank in bank_ids.items()
        }
        retain_ms: dict[str, float] = {}
        started = time.perf_counter()
        server_retain_items(configs["baseline"], baseline_items)
        retain_ms["baseline"] = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        project_memory.sync_artifacts(root, configs["enhanced"], candidates, source_revision="HEAD=benchmark")
        retain_ms["enhanced"] = (time.perf_counter() - started) * 1000

        queries = [
            ("Which source file defines class Component000?", "src/components/component_000.py"),
            ("Where is top-level function retain_003 defined?", "src/components/component_003.py"),
            ("Which component imports services.store_5 Bank?", "src/components/component_005.py"),
        ]
        quality: dict[str, dict] = {}
        for name, cfg in configs.items():
            top1 = 0
            top3 = 0
            latencies = []
            details = []
            for query, expected in queries:
                started = time.perf_counter()
                hits = server_recall(cfg, query, max_results=5)
                latencies.append((time.perf_counter() - started) * 1000)
                sources = [_hit_source(hit) for hit in hits]
                top1 += int(bool(sources) and sources[0] == expected)
                top3 += int(expected in sources[:3])
                details.append({"query": query, "expected": expected, "top_sources": sources[:3]})
            quality[name] = {
                "hit_at_1": top1 / len(queries),
                "hit_at_3": top3 / len(queries),
                "query_latency_ms_median": round(statistics.median(latencies), 2),
                "details": details,
            }
        removed = candidates[0]
        os.remove(os.path.join(root, removed.path))
        remaining = [candidate for candidate in candidates if candidate.path != removed.path]
        tombstone = project_memory.sync_artifacts(
            root,
            configs["enhanced"],
            remaining,
            source_revision="HEAD=deleted-benchmark",
        )
        stale_query = f"Which source file defines class {removed.symbols[0].split(':', 1)[1]}?"
        stale_lifecycle = {}
        for name, cfg in configs.items():
            hits = server_recall(cfg, stale_query, max_results=5)
            removed_hits = 0
            eligible_removed_hits = 0
            for hit in hits:
                if _hit_source(hit) != removed.path:
                    continue
                removed_hits += 1
                if name == "baseline":
                    # Pre-gate behavior accepted legacy hits with no provenance fields.
                    eligible_removed_hits += 1
                else:
                    raw_metadata = hit.get("metadata")
                    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                    eligible_removed_hits += int(_eligible_for_automatic_context(root, metadata))
            stale_lifecycle[name] = {
                "raw_hits": len(hits),
                "removed_source_raw_hits": removed_hits,
                "removed_source_automatic_context_eligible_hits": eligible_removed_hits,
                "top_sources": [_hit_source(hit) for hit in hits[:3]],
            }
        stale_lifecycle["enhanced"]["tombstones_published"] = tombstone["deleted_count"]
        benchmark_result = {
            "mode": "live-hindsight",
            "server": urlparse(server).netloc,
            "documents_per_bank": len(candidates),
            "retain_latency_ms": {name: round(value, 2) for name, value in retain_ms.items()},
            "quality": quality,
            "stale_lifecycle": stale_lifecycle,
            "checks_passed": bool(
                quality["enhanced"]["hit_at_3"] >= quality["baseline"]["hit_at_3"]
                and stale_lifecycle["enhanced"]["removed_source_automatic_context_eligible_hits"] == 0
                and tombstone["deleted_count"] == 1
            ),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)
        for name, bank in bank_ids.items():
            try:
                bank_url = f"{server}/v1/default/banks/{bank}"
                _json_request(bank_url, "DELETE", timeout=60)
                cleanup[name] = _bank_absent(server, bank)
            except Exception:
                cleanup[name] = False
    if benchmark_result is None:
        raise RuntimeError("live benchmark did not produce a result")
    benchmark_result["cleanup"] = dict(cleanup)
    benchmark_result["checks_passed"] = bool(benchmark_result["checks_passed"] and cleanup and all(cleanup.values()))
    return benchmark_result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("local", "live", "both"), default="both")
    parser.add_argument("--files", type=int, default=200)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = []
    if args.mode in ("local", "both"):
        results.append(local_benchmark(args.files))
    if args.mode in ("live", "both"):
        results.append(live_benchmark())
    payload = {"benchmark": "asgard-project-memory-projection-v1", "results": results}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(result.get("checks_passed") for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
