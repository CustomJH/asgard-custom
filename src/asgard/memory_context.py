"""개인 로컬 메모리와 Hindsight 프로젝트 메모리의 범위 분리 협력 회수."""

from __future__ import annotations

import hashlib
import os

from . import memory
from .memory_bridge import find_config, server_recall

PROJECT_RECALL_BUDGET = 1600
MAX_METADATA_FIELDS = 128
MAX_METADATA_CHARS = 8192
MAX_METADATA_DEPTH = 8


def _neutralize(value: str) -> str:
    return value.replace("<", "‹").replace(">", "›")


def _metadata_texts(value) -> list[str]:
    texts: list[str] = []
    total = 0
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_METADATA_DEPTH or len(texts) >= MAX_METADATA_FIELDS:
            raise ValueError("project recall metadata exceeds safety bounds")
        if isinstance(item, dict):
            if len(item) * 2 + len(texts) > MAX_METADATA_FIELDS:
                raise ValueError("project recall metadata exceeds safety bounds")
            stack.extend((child, depth + 1) for pair in reversed(list(item.items())) for child in reversed(pair))
            continue
        if isinstance(item, (list, tuple, set)):
            if len(item) + len(texts) > MAX_METADATA_FIELDS:
                raise ValueError("project recall metadata exceeds safety bounds")
            stack.extend((child, depth + 1) for child in reversed(list(item)))
            continue
        if item is None:
            continue
        text = str(item)
        total += len(text)
        if total > MAX_METADATA_CHARS:
            raise ValueError("project recall metadata exceeds safety bounds")
        texts.append(text)
    return texts


def _deterministic_projection_is_current(root: str, metadata: dict) -> bool:
    from .project_memory import load_projection_manifest

    source = str(metadata.get("source") or "")
    expected_hash = str(metadata.get("content_hash") or "")
    if not source or not expected_hash:
        return False
    full = os.path.realpath(os.path.join(root, source))
    canonical_root = os.path.realpath(root)
    try:
        if os.path.commonpath((canonical_root, full)) != canonical_root:
            return False
        manifest_entry = load_projection_manifest(root)["items"].get(source, {})
        if manifest_entry.get("status") != "active" or manifest_entry.get("content_hash") != expected_hash:
            return False
        digest = hashlib.sha256()
        with open(full, "rb") as current:
            for chunk in iter(lambda: current.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected_hash
    except (OSError, KeyError, ValueError):
        return False


def _eligible_for_automatic_context(root: str, metadata: dict) -> bool:
    """자동 주입은 active·verified 지식과 source artifact만 허용한다.

    provenance를 증명하지 못하는 legacy item은 명시 검색에는 남겨도 ambient context에는
    넣지 않는다. 자동 주입 trust boundary는 fail-closed다.
    """
    if metadata.get("scope") != "project" or metadata.get("status") != "active":
        return False
    if metadata.get("confidence") != "verified":
        return False
    if metadata.get("trust") == "untrusted-conversation" or metadata.get("kind") == "turn":
        return False
    try:
        metadata_texts = _metadata_texts(metadata)
    except ValueError:
        return False
    if metadata.get("origin") == "deterministic":
        return _deterministic_projection_is_current(root, metadata) and not memory.scan_threats(*metadata_texts)
    if not metadata.get("record_id") or not metadata.get("source") or not metadata.get("source_revision"):
        return False
    return not memory.scan_threats(*metadata_texts)


def project_recall_note(query: str, *, start: str | None = None, max_results: int = 5) -> str:
    """현재 프로젝트 bank를 검색한다. 불능·무적중은 빈 문자열로 fail-open."""
    try:
        found = find_config(start or os.getcwd())
        if not found:
            return ""
        root, cfg = found
        # 턴 시작 자동 주입은 원격 장애로 대화를 붙잡지 않는다. 명시 MCP 조회의 긴 timeout과 분리.
        recall_cfg = {**cfg, "timeout": min(int(cfg.get("timeout") or 5), 5)}
        # raw source artifact가 긴 코드 조각으로 budget을 선점하지 않도록, 더 넓게 검색한 뒤
        # 승인된 구조화 record를 먼저 배치한다. 각 그룹 내부 Hindsight 순위는 유지한다.
        hits = server_recall(recall_cfg, query, max_results=max(8, max_results * 2))
        hits = sorted(
            enumerate(hits),
            key=lambda pair: (
                0 if isinstance(pair[1].get("metadata"), dict) and pair[1]["metadata"].get("record_id") else 1,
                pair[0],
            ),
        )
        rows: list[str] = []
        total = 0
        for _, hit in hits:
            text = str(hit.get("text") or "").strip()
            raw_metadata = hit.get("metadata")
            metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
            if not text or memory.scan_threats(text) or not _eligible_for_automatic_context(root, metadata):
                continue
            source = str(metadata.get("source") or "").strip()
            suffix = f" [source: {_neutralize(source)}]" if source else ""
            row = f"- {_neutralize(text)[:420]}{suffix}"
            if total + len(row) + 1 > PROJECT_RECALL_BUDGET:
                break
            rows.append(row)
            total += len(row) + 1
            if len(rows) >= max_results:
                break
        if not rows:
            return ""
        return (
            '\n\n<memory-recall scope="project">\n'
            f"요청 관련 프로젝트 공유 메모리 (bank={_neutralize(str(cfg['bank']))}; 힌트 — 원본·완료 증거 아님):\n"
            + "\n".join(rows)
            + "\n</memory-recall>"
        )
    except Exception:
        return ""


def recall_note(query: str, *, start: str | None = None, personal_k: int = 3, project_k: int = 5) -> str:
    """한 질의로 두 메모리를 조회하되 결과 scope를 절대 섞지 않는다."""
    personal = memory.recall_note(query, k=personal_k)
    project = project_recall_note(query, start=start, max_results=project_k)
    return personal + project
