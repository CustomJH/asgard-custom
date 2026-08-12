"""물음 종류를 화면 이름으로 바꾸는 자리.

카드(`native`)와 서사(`recap`)가 같은 이름을 써야 한다 — 두 자리가 각자 표를 들면 한 종류가
화면마다 다르게 불린다.
"""

from __future__ import annotations

from ..tutor_model import KIND_LABEL, Checkpoint


def _point_label(point: Checkpoint) -> str:
    if not point.unit and point.kind == "behavior-removed":
        return "삭제 책임 묶음"
    if not point.unit and point.kind == "test-removed":
        return "판정 책임 묶음"
    return KIND_LABEL.get(point.kind, point.kind)


def _folded_line(counts: dict[str, int]) -> str:
    return " · ".join(f"{KIND_LABEL.get(kind, kind)} {n}건" for kind, n in sorted(counts.items()))
