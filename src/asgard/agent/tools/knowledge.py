"""도구 — 바깥 글을 들이는 자리. 문서 추출(docx·pdf·hwp), 프로젝트 기억 담기, 개인 기억 제안."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from ._core import _MAX_ARCHIVE_BYTES, _MAX_DOCUMENT_BYTES, _TIMEOUT, ToolError, _cap, _confine


def _safe_archive(path: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 4096 or sum(item.file_size for item in entries) > _MAX_ARCHIVE_BYTES:
                raise ToolError("문서 압축 해제 크기가 안전 상한을 초과합니다")
    except zipfile.BadZipFile as exc:
        raise ToolError(f"올바른 문서 ZIP이 아닙니다: {exc}") from exc


def _extract_docx(path: str) -> str:
    _safe_archive(path)
    try:
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
    except (KeyError, ET.ParseError) as exc:
        raise ToolError(f"DOCX 본문을 읽을 수 없습니다: {exc}") from exc
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines: list[str] = []
    for paragraph in root.iter(f"{ns}p"):
        text: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{ns}t":
                text.append(node.text or "")
            elif node.tag == f"{ns}tab":
                text.append("\t")
            elif node.tag in {f"{ns}br", f"{ns}cr"}:
                text.append("\n")
        lines.extend("".join(text).splitlines() or [""])
    return "\n".join(lines)


def _extract_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    return "\n".join(f"# Page {index}\n{page.extract_text() or ''}" for index, page in enumerate(reader.pages, 1))


def _extract_hwpx(path: str) -> str:
    from hwpx import TextExtractor

    _safe_archive(path)
    with TextExtractor(path) as extractor:
        return extractor.extract_text(include_nested=True, object_behavior="nested", skip_empty=True)


def _extract_hwp(path: str) -> str:
    script = (
        Path(__file__).resolve().parents[1]
        / "assets"
        / "skill_plugins"
        / "hwpx-skill"
        / "skills"
        / "hwpx"
        / "scripts"
        / "convert_hwp.py"
    )
    with tempfile.TemporaryDirectory(prefix="asgard-hwp-read-") as temp:
        converted = os.path.join(temp, "document.hwpx")
        try:
            result = subprocess.run(
                [sys.executable, str(script), path, "-o", converted],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise ToolError("HWP 읽기에는 Node.js 18+가 필요합니다") from exc
        if result.returncode:
            raise ToolError((result.stderr or result.stdout or "HWP 변환 실패").strip()[:2000])
        return _extract_hwpx(converted)


def run_document(root: str, tool_input: dict) -> str:
    path = _confine(root, str(tool_input.get("path") or ""))
    if not os.path.isfile(path):
        raise ToolError(f"문서 파일 없음: {os.path.relpath(path, root)}")
    if os.path.getsize(path) > _MAX_DOCUMENT_BYTES:
        raise ToolError("문서가 64 MiB 안전 상한을 초과합니다")
    extractors = {".pdf": _extract_pdf, ".docx": _extract_docx, ".hwpx": _extract_hwpx, ".hwp": _extract_hwp}
    suffix = Path(path).suffix.lower()
    if suffix not in extractors:
        raise ToolError("지원 형식: .pdf, .docx, .hwpx, .hwp")
    try:
        text = extractors[suffix](path)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"문서 추출 실패: {exc}") from exc
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        hint = " 스캔 PDF라면 OCR 도구가 필요합니다." if suffix == ".pdf" else ""
        raise ToolError("추출 가능한 텍스트가 없습니다." + hint)
    offset = int(tool_input.get("offset") or 1)
    limit = int(tool_input.get("limit") or 200)
    if offset < 1 or not 1 <= limit <= 500:
        raise ToolError("offset은 1 이상, limit은 1..500이어야 합니다")
    page = lines[offset - 1 : offset - 1 + limit]
    end = min(offset + len(page) - 1, len(lines))
    header = f"[{suffix[1:].upper()} · lines {offset}-{end}/{len(lines)}]"
    if end < len(lines):
        header += f"\n다음: offset={end + 1}"
    return _cap(header + "\n" + "\n".join(page))


def run_ingest_document(root: str, tool_input: dict) -> str:
    """문서를 프로젝트 메모리 승인 대기로 올린다 — 사람은 파일만 던지면 된다.

    쓰기가 아니라 **제안**이다. 팀 공유 스코프라 승인 없이 들어가지 않는다 (프로젝트 메모리
    계약 그대로). 그래서 이 도구는 inspect 권한으로 충분하고, 실제 등록은 사람이 승인한다."""
    from ...memory_bridge import find_config, is_backend_trusted
    from ...project_memory import ingest

    raw = tool_input.get("paths")
    paths = [str(p) for p in raw if str(p).strip()] if isinstance(raw, list) else []
    if not paths:
        raise ToolError("paths가 비었습니다")
    if len(paths) > 20:
        raise ToolError("한 번에 20개까지 처리합니다")
    resolved = [p if os.path.isabs(p) else os.path.join(root, p) for p in paths]
    found = find_config(root)
    if not found:
        raise ToolError("프로젝트 메모리가 연결돼 있지 않습니다 — asgard memory connect <endpoint>")
    project_root, cfg = found
    if not is_backend_trusted(cfg):
        raise ToolError("이 기계에서 신뢰되지 않은 backend 입니다 — asgard memory connect로 재승인")
    strategy = str(tool_input.get("strategy") or "").strip() or None
    ready, failed = ingest.plan(resolved, strategy=strategy)
    if not ready:
        detail = "; ".join(f"{os.path.basename(r['path'])}: {r['error']}" for r in failed) or "읽을 문서가 없습니다"
        raise ToolError(detail)
    if any(d.lane == ingest.LANE_GRAPH for d in ready):
        ingest.ensure_strategies(cfg)
    staged = ingest.stage_documents(project_root, cfg, ready)
    from ...memory_bridge import autosave_enabled

    auto = autosave_enabled(cfg)
    lines = [
        f"{len(staged)}건을 처리했습니다."
        + (
            " 자동저장(project_memory.autosave)이라 승인 없이 등록합니다."
            if auto
            else " 승인 전에는 공유 메모리에 들어가지 않습니다."
        )
    ]
    for row in staged:
        head = (
            f"- {row['name']} · {row['kind']} · 전략 {row['strategy']} · {row['chars']:,}자 · "
            f"엔티티 {row['entities']} · 레인 {row['lane']}"
        )
        if row["lane"] == ingest.LANE_LOCAL:
            # 그래프에 넣으면 뱅크가 죽는 크기 — 저장소 정본 + 로컬 인덱스로 보냈다.
            lines.append(
                f"{head}\n  저장소 정본: {row['canonical_path']} "
                f"(예측 unit {row['graph_units']} > 상한 {ingest.GRAPH_UNIT_CEILING} — 커밋하면 팀과 공유)"
            )
        elif auto:
            # 실패해도 approval_id는 살아 있다 — 문서 한 건이 막혀도 나머지는 계속 들어가고,
            # 막힌 건은 사람이 그 id로 이어받는다 (부분 성공을 전체 실패로 만들지 않는다).
            try:
                from ...project_memory import commit_approved_record

                commit_approved_record(project_root, cfg, row["approval_id"])
            except Exception as exc:
                lines.append(f"{head}\n  자동저장 실패 — asgard memory project-approve {row['approval_id']} ({exc})")
            else:
                lines.append(f"{head}\n  저장 완료 (자동저장)")
        else:
            lines.append(f"{head}\n  승인 대기 — asgard memory project-approve {row['approval_id']}")
    for row in failed:
        lines.append(f"- (읽지 못함) {os.path.basename(row['path'])} — {row['error']}")
    return "\n".join(lines)


def run_memory_propose(root: str, tool_input: dict) -> str:
    """개인 기억 쓰기 — 기본은 대기열(사람이 승인해야 정본), 자동저장이 켜져 있으면 즉시 저장.

    어느 쪽인지는 이 함수가 정하지 않는다: `propose.submit`이 설정 하나를 읽고 정하고,
    표면은 그 결과를 옮긴다 (MCP와 같은 문장 — `propose.outcome_text`).
    거절 사유는 문장으로 돌려준다 — 에이전트가 읽고 고쳐 다시 낼 수 있어야 한다."""
    del root  # 개인 기억은 프로젝트가 아니라 에이전트에 붙는다 (memory_dir이 프로파일별)
    from ...memory import propose

    text = str(tool_input.get("text") or "").strip()
    kind = str(tool_input.get("kind") or "note").strip()
    try:
        outcome = propose.submit(text, kind=kind)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return propose.outcome_text(outcome)
