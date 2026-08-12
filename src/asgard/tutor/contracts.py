"""표면 계약 (surface 재사용) — 공개 시그니처가 바뀐 자리와 판정 없는 새 심볼."""

from __future__ import annotations

from .. import surface, tutor_probes
from ..tutor_model import Checkpoint


def _surface_points(root: str, base: str) -> tuple[list[Checkpoint], list[tuple[str, str]]]:
    """공개 시그니처 변화 + 호출부 후보. 목록을 손 grep에 맡기지 않는 것이 surface의 존재 이유다."""
    try:
        diff = surface.diff(root, base)
    except Exception:
        return ([], [("(public surface)", "표면 대조를 돌리지 못해서 계약이 바뀌었는지 못 봤어요")])
    out: list[Checkpoint] = []
    for change in diff.changes:
        if not change.breaking or change.kind == "removed":
            continue  # 삭제는 단위 인벤토리가 이미 묻는다 — 같은 것을 두 번 묻지 않는다
        sites = diff.obligations.get(change.qualname.rsplit(".", 1)[-1], ())
        where = ", ".join(sites[:6]) if sites else "이 변경 밖에서 같은 이름을 못 찾았어요"
        out.append(
            Checkpoint(
                "contract-break",
                change.path,
                1,
                change.qualname,
                f"공개 계약이 바뀌었어요 — {change.kind} ({change.detail})",
                f"호출부가 그대로면 깨져요. 이름으로 찾은 후보는 {where}예요",
                "위 후보를 하나씩 열어 확인해 보셨나요? 안 고쳐도 되는 것은 왜 그런가요?",
            )
        )
    unparsed = [(p, "구문을 못 읽어서 표면 대조에서 빠졌어요") for p in diff.unparsed]
    return (out + _untested_points(root, diff), unparsed)


def _untested_points(root: str, diff: surface.SurfaceDiff) -> list[Checkpoint]:
    """새로 생긴 공개 심볼 중 테스트 트리 어디에서도 이름이 안 보이는 것."""
    added = [c for c in diff.changes if c.kind == "added"]
    if not added:
        return []
    try:
        found = surface.candidates(root, [c.qualname for c in added])
    except Exception:
        return []
    out: list[Checkpoint] = []
    for change in added:
        name = change.qualname.rsplit(".", 1)[-1]
        if any(tutor_probes.is_test_path(p) for p in found.get(name, ())):
            continue
        out.append(
            Checkpoint(
                "untested-surface",
                change.path,
                1,
                change.qualname,
                f"새 공개 심볼 `{change.qualname}` — 테스트 트리에서 이름이 안 보여요",
                "판정 없는 표면은 다음 사람이 마음대로 바꿔도 아무것도 빨개지지 않아요",
                "이게 틀렸을 때 무엇이 빨개지나요? 아무것도 안 빨개진다면 그래도 괜찮은 이유는 뭔가요?",
            )
        )
    return out
