"""조립 — 파일별 판정과 표면 대조를 하나의 되짚기 자료(`Lesson`)로 묶는다."""

from __future__ import annotations

import os
from dataclasses import replace

from .. import craft, loop
from ..tutor_model import Checkpoint, FileChange, Lesson
from .contracts import _surface_points
from .diffs import _numstat
from .points import MAX_PATHS, _judge, _own_names, _relocations


def review(root: str, base: str = "HEAD", paths: object = ()) -> Lesson:
    """이번 변경의 되짚기 자료. 지목된 경로가 없으면 base 대비 달라진 전부를 본다."""
    named = _normalise(paths)
    targets = named or list(craft.changed_paths(root, base))
    stats = _numstat(root, base)
    own = _own_names(root)
    moves = _relocations(root, base, targets)
    files: list[FileChange] = []
    points: list[Checkpoint] = []
    unknown: list[tuple[str, str]] = []
    anchors: dict[str, dict[str, int]] = {}
    for rel in targets[:MAX_PATHS]:
        change, found, why, lines = _judge(root, rel, base, stats, own, moves)
        files.append(change)
        points.extend(found)
        anchors[rel] = lines
        if why:
            unknown.append((rel, why))
    if len(targets) > MAX_PATHS:
        unknown.append(
            (
                f"(+{len(targets) - MAX_PATHS} more)",
                f"한 번에 {MAX_PATHS}개까지만 읽었어요 — 경로를 좁혀 다시 봐 주세요",
            )
        )
    contract, gaps = _surface_points(root, base)
    # 경로를 지목받았으면 표면 판정도 그 안으로 자른다. surface는 나무 전체의 변경을 보는데,
    # 훅은 "이 세션이 쓴 경로"만 넘긴다 — 안 자르면 남이 만든 계약 파괴를 이 턴의 물음으로
    # 돌려주게 되고, 그건 craft 래칫이 막는 것과 똑같은 종류의 오귀속이다.
    scope = set(named)
    if scope:
        contract = [point for point in contract if point.path in scope]
        gaps = [gap for gap in gaps if gap[0] in scope]
    points.extend(_anchored(point, anchors) for point in contract)
    # 컨트롤러 근거는 **손댄 경로에 대해서만** 넣는다 — 안 건드린 자리의 지시를 이번 되짚기에
    # 붙이면 craft 래칫이 막는 것과 같은 종류의 오귀속이 된다.
    mandate = loop.mandate_for(root, targets)
    return Lesson(base, tuple(files), tuple(points), tuple(unknown + gaps), mandate)


def _anchored(point: Checkpoint, anchors: dict[str, dict[str, int]]) -> Checkpoint:
    """표면 판정에 좌표를 붙인다. `file:1`은 사람이 열어 볼 수 없는 좌표라 물음이 도달하지 않는다."""
    line = anchors.get(point.path, {}).get(point.unit)
    return point if line is None else replace(point, line=line)


def _normalise(paths: object) -> list[str]:
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return []
    return sorted({rel for raw in paths if (rel := str(raw).strip().replace(os.sep, "/"))})
