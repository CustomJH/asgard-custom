"""화면·보고서·JSON 이 같이 쓰는 이름표와 세는 자.

세 표면이 각자 표를 들면 같은 물음이 자리마다 다르게 불린다. 이름은 여기 하나뿐이다.
"""

from __future__ import annotations

from ... import tutor

_KIND = tutor.KIND_LABEL  # 이름은 엔진이 갖는다 — 표면마다 다시 쓰면 화면마다 다르게 불린다
_LADDER = ("○○○", "●○○", "●●○", "●●●")
# 항복 신호의 사람 이름. `KIND_LABEL`이 엔진에 있는 것과 달리 이 표는 표면이 갖는다 —
# `tutor_debt.Signal`은 `fact`·`why`로 이미 사람 문장을 들고 오고, 여기서 더할 것은 그 신호를
# 화면에서 부르는 이름 하나뿐이다. 엔진에 두면 재료와 표현이 다시 한 자리에 섞인다.
#
# 이름은 문장이 아니라 **명사**다. 한동안 여기만 문장("읽기 전에 닫았어요")이라 같은 신호가
# 훅 줄에서는 "답 수용 속도"로 불렸고, 한 신호에 이름이 둘이었다. 명사여야 세 자리가 다 선다 —
# 여기(`이름 — fact`)와 도중 점검 머리, 그리고 "가장 큰 신호는 ○○ 쪽이에요"의 빈칸.
_SIGNAL_LABEL = {
    "acceptance-latency": "답 수용 속도",
    "unanswered-backlog": "답 없는 물음",
    "review-ratio": "검토 비율",
    "skip-streak": "연속 건너뜀",
    "session-load": "세션 부하",
}
_LEVEL_MARK = ("·", "▸", "▲")  # 0 안전 · 1 주의 · 2 경고 — 색이 없는 터미널에서도 등급이 보이게
_TRACK_MARK = ("·", "▸")  # 0 지금 열린 물음 없음 · 1 있음 — 어느 트랙이 지금 도는지 한 글자로

# 승급 시험 채점 화면이 같이 적는 한계. 물음 문장은 `tutor_track._question`이 이미 안고 나오지만
# `--answer`로 부르면 그 문장이 화면에 안 뜨므로, 채점만 본 사람이 판정을 전지한 것으로 읽는다.
# 단계 이름·기준 문장과 달리 이것은 화면에만 있는 말이라 표면이 갖는다(`_SIGNAL_LABEL`과 같은 자리).
_EXAM_BLIND = "이름으로 찾은 후보라 동적 호출은 못 봐요 — 못 댄 것만 세고 더 댄 것은 안 깎아요"


def _summary(lesson: tutor.Lesson) -> str:
    added, removed = lesson.touched
    return f"파일 {len(lesson.files)}개 · +{added:,}/-{removed:,}행"


def _units_line(change: tutor.FileChange) -> str:
    """단위 요약 한 줄. 문서·설정을 "판정 못 함"으로 적으면 진짜 못 읽은 코드가 그 속에 묻힌다."""
    if not change.code:
        return "코드 파일 아님"
    if not change.judged:
        return "코드 단위 못 읽음"
    bits = [
        f"새 단위 {len(change.units_added)}" if change.units_added else "",
        f"바뀐 단위 {len(change.units_changed)}" if change.units_changed else "",
        f"사라진 단위 {len(change.units_removed)}" if change.units_removed else "",
        f"옮긴 단위 {len(getattr(change, 'units_moved', ()))}" if getattr(change, "units_moved", ()) else "",
    ]
    return " · ".join(b for b in bits if b) or "단위 변화 없음"


def _counts(rows: list[tuple[tutor.Checkpoint, str]], want: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for point, form in rows:
        if form == want:
            out[point.kind] = out.get(point.kind, 0) + 1
    return out


def _count_line(counts: dict[str, int]) -> str:
    return " · ".join(f"{_KIND.get(k, k)} {n}건" for k, n in sorted(counts.items()))


def _point_label(point: tutor.Checkpoint) -> str:
    if not point.unit and point.kind == "behavior-removed":
        return "삭제 책임 묶음"
    if not point.unit and point.kind == "test-removed":
        return "판정 책임 묶음"
    return _KIND.get(point.kind, point.kind)


def _shown_rows(rows: list[tuple[tutor.Checkpoint, str]], limit: int) -> list[tuple[tutor.Checkpoint, str]]:
    return [row for row in rows if row[1] not in ("fold", "quiet")][: max(0, limit)]


def _point_counts(rows: list[tuple[tutor.Checkpoint, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for point, _ in rows:
        counts[point.kind] = counts.get(point.kind, 0) + 1
    return counts
