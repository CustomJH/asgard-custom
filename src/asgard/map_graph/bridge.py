"""2차 메모리(프로젝트 메모리) 브리지 — 앵커드 오버레이 조회.

계약: 그래프는 코드에서 재생성되는 **사실**만 소유하고, 왜/결정/정정 같은 **증언**은
프로젝트 메모리 레코드(`.asgard/memory/records/`)가 소유한다. 여기서는 레코드가 그래프
노드 id 또는 증거 파일 경로를 언급하는지로 후보 연관만 찾는다 — 연관은 언제나 candidate
이며, 레코드 내용을 그래프로 승격하거나 그래프 사실을 레코드로 복제하지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..project_memory.canonical import _read_record_file, records_dir

_MAX_RECORD_FILES = 400
_MAX_RECORD_BYTES = 1_000_000


@dataclass(frozen=True)
class RelatedRecord:
    file: str  # 레코드 파일명
    title: str
    match: str  # "node-id" | 매칭된 파일 경로


def related_records(root: str | os.PathLike[str], node: dict) -> list[RelatedRecord]:
    """노드를 언급하는 승인 레코드를 찾는다 (후보 연관, 최대 근거는 레코드 본문)."""
    base = Path(root).resolve()
    try:
        directory = Path(records_dir(str(base)))
    except ValueError:
        return []
    if not directory.is_dir():
        return []
    needles: dict[str, str] = {str(node.get("id", "")): "node-id"}
    for location in node.get("files", ()):
        path = str(location.get("file", ""))
        if path:
            needles[path] = path
    needles.pop("", None)
    related: list[RelatedRecord] = []
    try:
        candidates = sorted(directory.glob("record-*.md"))[:_MAX_RECORD_FILES]
    except OSError:
        return []
    for record_path in candidates:
        try:
            if record_path.is_symlink() or record_path.stat().st_size > _MAX_RECORD_BYTES:
                continue
            record, _digest = _read_record_file(str(record_path))
        except OSError, UnicodeError, ValueError:
            continue
        text = "\n".join(
            [
                record.record_id,
                record.title,
                record.content,
                record.source,
                *(str(row.get("target") or "") for row in record.relations),
            ]
        )
        matched = next((label for needle, label in sorted(needles.items()) if needle in text), None)
        if matched is None:
            continue
        related.append(RelatedRecord(file=record_path.name, title=record.title, match=matched))
    return related
