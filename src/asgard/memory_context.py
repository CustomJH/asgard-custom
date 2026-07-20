"""개인 로컬 메모리와 선택된 프로젝트 메모리 backend의 범위 분리 협력 회수."""

from __future__ import annotations

import hashlib
import os

from . import memory
from .memory_bridge import find_config, is_backend_trusted, server_recall

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
    except OSError, KeyError, ValueError:
        return False


def _eligible_for_automatic_context(root: str, metadata: dict, cfg: dict | None = None) -> bool:
    """자동 주입은 active·verified 지식과 source artifact만 허용한다.

    provenance를 증명하지 못하는 legacy item은 ambient 및 explicit MCP context에 넣지 않는다.
    두 경로가 공유하는 trust boundary는 fail-closed다.
    """
    if metadata.get("scope") != "project" or metadata.get("status") != "active":
        return False
    if metadata.get("confidence") != "verified":
        return False
    if metadata.get("trust") == "untrusted-conversation" or metadata.get("kind") == "turn":
        return False
    if metadata.get("kind") == "binding" or metadata.get("scope") == "control":
        return False
    if cfg is not None:
        if (
            not cfg.get("project_uid")
            or not cfg.get("binding_id")
            or metadata.get("project_uid") != cfg.get("project_uid")
            or metadata.get("binding_id") != cfg.get("binding_id")
        ):
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


def filter_project_hits(
    root: str, cfg: dict, hits: list[dict], *, max_results: int | None = None
) -> tuple[list[dict], int]:
    """Ambient와 explicit MCP가 공유하는 최소 ownership/provenance 정책."""
    clean: list[dict] = []
    dropped = 0
    for hit in hits:
        text = str(hit.get("text") or "").strip()
        raw_metadata = hit.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        document_id = str(hit.get("document_id") or "")
        if document_id.startswith("asgard:project-binding:"):
            dropped += 1
            continue
        if not text or memory.scan_threats(text) or not _eligible_for_automatic_context(root, metadata, cfg):
            dropped += 1
            continue
        clean.append({**hit, "text": text, "metadata": metadata})
        if max_results is not None and len(clean) >= max_results:
            break
    return clean, dropped


def project_recall_note(query: str, *, start: str | None = None, max_results: int = 5) -> str:
    """현재 프로젝트 backend를 검색한다. 불능·미신뢰·무적중은 빈 문자열로 fail-open."""
    try:
        found = find_config(start or os.getcwd())
        if not found:
            return ""
        root, cfg = found
        if not is_backend_trusted(cfg):
            return ""
        # 턴 시작 자동 주입은 원격 장애로 대화를 붙잡지 않는다. 명시 MCP 조회의 긴 timeout과 분리.
        operation_timeout = min(int(cfg.get("timeout") or 5), 5)
        # raw source artifact가 긴 코드 조각으로 budget을 선점하지 않도록, 더 넓게 검색한 뒤
        # 승인된 구조화 record를 먼저 배치한다. 각 그룹 내부 backend 순위는 유지한다.
        hits = server_recall(cfg, query, max_results=max(8, max_results * 2), operation_timeout=operation_timeout)
        hits = sorted(
            enumerate(hits),
            key=lambda pair: (
                0 if isinstance(pair[1].get("metadata"), dict) and pair[1]["metadata"].get("record_id") else 1,
                pair[0],
            ),
        )
        project_id = _neutralize(str(cfg.get("project_id") or cfg.get("bank") or ""))[:120]
        prefix = (
            '\n\n<memory-recall scope="project">\n'
            f"요청 관련 프로젝트 공유 메모리 (project_id={project_id}; 힌트 — 원본·완료 증거 아님):\n"
        )
        suffix = "\n</memory-recall>"
        if len(prefix + suffix) > PROJECT_RECALL_BUDGET:
            return ""
        filtered, _ = filter_project_hits(root, cfg, [hit for _, hit in hits], max_results=max_results)
        rows: list[str] = []
        for hit in filtered:
            text = str(hit["text"])
            metadata = hit["metadata"]
            provenance = []
            for label, key, cap in (
                ("source", "source", 240),
                ("record", "record_id", 120),
                ("revision", "source_revision", 160),
            ):
                value = _neutralize(str(metadata.get(key) or "").strip())[:cap]
                if value:
                    provenance.append(f"{label}: {value}")
            provenance_note = f" [{'; '.join(provenance)}]" if provenance else ""
            row = f"- {_neutralize(text)[:420]}{provenance_note}"
            if len(prefix + "\n".join([*rows, row]) + suffix) > PROJECT_RECALL_BUDGET:
                break
            rows.append(row)

        if not rows:
            return ""
        return prefix + "\n".join(rows) + suffix
    except Exception:
        return ""


LEARNED_SKILLS_CAP = 2  # 스킬 힌트 상한 — skill_bank 라우팅 상한(_CAP)과 같은 근거 (과주입 = 노이즈)


def learned_skills_note(query: str, *, start: str | None = None, cap: int = LEARNED_SKILLS_CAP) -> str:
    """질의 관련 learned 스킬 포인터 — 자가발전 산출물을 회수 계층으로 노출.

    CC 모드에는 네이티브 루프의 디스패치 주입(heimdall resolve_learned)이 닿지 않으므로,
    승인된 스킬을 UserPromptSubmit 회수에 포인터(이름·설명·경로)로 흘린다. 본문 전체는
    주입하지 않는다 — CC 에이전트는 경로를 Read 로 열 수 있고, 네이티브 루프와의 이중
    주입도 피한다(recall_note 기본값이 스킬 제외인 이유). Verifier/loki 차단은 호출측
    (memory-activate 감사 매트릭스)이 지킨다 — 스킬 뱅크 헌법과 같은 결."""
    try:
        from .skill_bank import learned_skills, record_use

        root = os.path.realpath(start or os.getcwd())
        task = query.lower()
        hits: list[tuple[int, str, dict]] = []
        for name, skill in learned_skills(root).items():
            matched = sum(1 for k in skill["triggers"] if k in task)
            if matched:
                hits.append((-matched, name, skill))
        if not hits:
            return ""
        hits.sort(key=lambda row: (row[0], row[1]))
        hits = hits[: max(1, cap)]
        rows = []
        for _, name, skill in hits:
            desc = _neutralize(str(skill.get("description") or "").strip())[:160]
            path = str(skill.get("path") or "")
            rel = os.path.relpath(path, root)
            shown = rel if not rel.startswith("..") else path  # 글로벌(~/.asgard) 스킬은 절대경로 유지
            rows.append(f"- {name} — {desc} ({shown})")
        record_use(root, [name for _, name, _ in hits])  # 큐레이션 원료 — 주입도 사용이다
        return (
            '\n\n<memory-recall scope="skills">\n'
            "요청 관련 learned 스킬 (승인된 과거 교훈 — 힌트다, 필요하면 파일을 읽어라):\n"
            + "\n".join(rows)
            + "\n</memory-recall>"
        )
    except Exception:
        return ""  # 스킬 힌트 불능이 회수를 막지 않는다 (fail-open)


def recall_note(
    query: str,
    *,
    start: str | None = None,
    personal_k: int = 3,
    project_k: int = 5,
    include_skills: bool = False,
) -> str:
    """한 질의로 두 메모리를 조회하되 결과 scope를 절대 섞지 않는다.

    include_skills 는 CC 훅 표면(run_recall)만 켠다 — 네이티브 루프는 디스패치 라우팅이
    스킬 본문을 직접 주입하므로 여기서 또 흘리면 이중 주입이 된다."""
    personal = memory.recall_note(query, k=personal_k)
    project = project_recall_note(query, start=start, max_results=project_k)
    skills = learned_skills_note(query, start=start) if include_skills else ""
    return personal + project + skills
