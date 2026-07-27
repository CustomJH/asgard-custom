"""asgard tutor — 되짚기 자료의 사람 표면.

계약 세 줄: ① **사실과 물음을 화면에서 분리한다** — 무엇이 바뀌었나가 먼저, 당신이 답할
것이 그 다음이다. ② 순위를 매겨 위에서부터 싣는다 — 스무 개를 나란히 늘어놓으면 아무도 첫
번째부터 보지 않는다. ③ 못 본 것을 같은 화면에 싣는다 — "확인할 것 0건"이 "안 봤다"를 뜻할 수
있으면 이 도구는 거짓말을 하는 것이다.

보고서(`--report`)에는 화면에 없는 절이 하나 더 있다: **왜 이렇게 했는가**. 기계는 그 칸을
채울 수 없고 채우려 들면 안 된다 — 빈칸으로 남겨 코드를 쓴 쪽이 채우고 사용자가 검사한다.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from .. import tutor, ui
from .health import _project_root

_KIND = tutor.KIND_LABEL  # 이름은 엔진이 갖는다 — 표면마다 다시 쓰면 화면마다 다르게 불린다
_REPORT_REL = os.path.join(".asgard", "tutor", "last-review.md")
_WHY_SLOT = (
    "> 이 절은 기계가 채우지 않는다. 코드를 쓴 쪽이 여기에 답을 적고, 읽는 쪽이 그 답을 검사한다.\n"
    "> 세 가지만 적으면 된다 — **무엇을 하려 했는가 / 왜 이 방법인가 / 버린 방법은 무엇이고 왜 버렸는가**.\n"
)


def _summary(lesson: tutor.Lesson) -> str:
    added, removed = lesson.touched
    return f"파일 {len(lesson.files)}개 · +{added:,}/-{removed:,}행"


def _units_line(change: tutor.FileChange) -> str:
    """단위 요약 한 줄. 문서·설정을 "판정 못 함"으로 적으면 진짜 못 읽은 코드가 그 속에 묻힌다."""
    if not change.code:
        return "코드 파일 아님"
    if not change.judged:
        return "코드 단위를 못 읽었다"
    bits = [
        f"새 단위 {len(change.units_added)}" if change.units_added else "",
        f"바뀐 단위 {len(change.units_changed)}" if change.units_changed else "",
        f"사라진 단위 {len(change.units_removed)}" if change.units_removed else "",
    ]
    return " · ".join(b for b in bits if b) or "단위 변화 없음"


def _emit_inventory(lesson: tutor.Lesson) -> None:
    ui.phase(f"무엇이 어떻게 바뀌었나 — {_summary(lesson)}")
    for change in lesson.files[:20]:
        flag = " (신규)" if change.new_file else ""
        ui.step(f"{change.path}{flag} +{change.added}/-{change.removed}")
        ui.step(ui.dim(f"    {_units_line(change)}"))
    if len(lesson.files) > 20:
        ui.step(ui.dim(f"    …외 {len(lesson.files) - 20}개 (`--json` 이 전부를 싣는다)"))


def _emit_points(lesson: tutor.Lesson, limit: int) -> None:
    points = lesson.ranked
    if not points:
        ui.ok("기계가 짚을 자리는 없다 — 그래도 '왜 이렇게 했는가'는 사람만 답할 수 있다")
        return
    ui.phase(f"당신이 직접 확인할 것 — {len(points)}건 (막지 않는다)")
    for point in points[:limit]:
        ui.warn(f"{_KIND.get(point.kind, point.kind)} — {point.where}")
        ui.step(ui.dim(f"    {point.what}"))
        ui.step(ui.dim(f"    {point.why}"))
        ui.step(f"    ▸ {point.ask}")
    if len(points) > limit:
        ui.step(ui.dim(f"    …외 {len(points) - limit}건 (`asgard tutor --report` 가 전부를 싣는다)"))


def _payload(lesson: tutor.Lesson) -> str:
    return json.dumps(
        {
            "base": lesson.base,
            "files": [asdict(f) for f in lesson.files],
            "added": lesson.touched[0],
            "removed": lesson.touched[1],
            "checkpoints": [{**asdict(p), "weight": p.weight} for p in lesson.ranked],
            "undetermined": [{"path": p, "why": w} for p, w in lesson.undetermined],
        },
        ensure_ascii=False,
        indent=2,
    )


# ── 보고서 ─────────────────────────────────────────────────────────


def _report_files(lesson: tutor.Lesson) -> list[str]:
    lines = ["## 1. 무엇이 어떻게 바뀌었나", "", f"기준 `{lesson.base}` 대비 — {_summary(lesson)}.", ""]
    lines += ["| 파일 | 행 | 단위 |", "| --- | --- | --- |"]
    for change in lesson.files:
        name = f"`{change.path}`" + (" *(신규)*" if change.new_file else "")
        lines.append(f"| {name} | +{change.added}/-{change.removed} | {_units_line(change)} |")
    # 신규 파일은 단위가 전부 새것이라 나열할 값이 없다 — 표의 개수로 충분하고, 나열하면
    # 기존 파일에서 실제로 생기고 사라진 것이 그 속에 묻힌다.
    detail = [f for f in lesson.files if not f.new_file and (f.units_added or f.units_removed)]
    if detail:
        lines += ["", "기존 파일의 함수 수준 변화:", ""]
        for change in detail:
            for name in change.units_added:
                lines.append(f"- `{change.path}` — 새 단위 `{name}`")
            for name in change.units_removed:
                lines.append(f"- `{change.path}` — 사라진 단위 `{name}`")
    return lines


def _report_points(lesson: tutor.Lesson) -> list[str]:
    lines = ["## 3. 당신이 직접 확인할 것", ""]
    if not lesson.ranked:
        lines.append("기계가 짚을 자리는 없었다. 그래도 위 2절의 답이 스스로 납득되는지는 사람만 판정할 수 있다.")
        return lines
    lines.append("체크박스는 읽었다는 뜻이 아니라 **답했다**는 뜻이다.")
    lines.append("")
    for point in lesson.ranked:
        lines += [
            f"- [ ] **{_KIND.get(point.kind, point.kind)}** — `{point.where}`",
            f"  - 사실: {point.what}",
            f"  - 왜 당신 눈이 필요한가: {point.why}",
            f"  - **물음: {point.ask}**",
        ]
    return lines


def _report(lesson: tutor.Lesson) -> str:
    lines = [
        "# 변경 되짚기",
        "",
        f"`asgard tutor` 가 기준 `{lesson.base}` 대비 만든 자료다. 사실은 기계가, 답은 사람이 채운다.",
        "",
    ]
    lines += _report_files(lesson)
    lines += ["", "## 2. 왜 이렇게 했는가", "", _WHY_SLOT]
    lines += ["", *_report_points(lesson)]
    if lesson.undetermined:
        lines += [
            "",
            "## 4. 기계가 못 본 것",
            "",
            "아래는 판정에서 빠졌다 — '확인할 것'에 안 나왔다고 안전하다는 뜻이 아니다.",
            "",
        ]
        lines += [f"- `{path}` — {why}" for path, why in lesson.undetermined]
    return "\n".join(lines) + "\n"


def _write_report(root: str, lesson: tutor.Lesson, out: str) -> str:
    from ..io_files import write_text

    path = out if os.path.isabs(out) else os.path.join(root, out)
    write_text(path, _report(lesson))
    return path


def run_tutor(
    *,
    base: str = "HEAD",
    paths: tuple[str, ...] = (),
    json_out: bool = False,
    report: bool = False,
    out: str = "",
    limit: int = 6,
    quiet: bool = False,
) -> int:
    """종료 코드는 언제나 0 — 튜터는 규율이지 관문이 아니다(`health` 와 같은 등급)."""
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)
    lesson = tutor.review(root, base, paths)

    if json_out:
        print(_payload(lesson))
        return 0

    ui.head(f"tutor · 이번 변경 되짚기 ({lesson.base})")
    if not lesson.files and not lesson.checkpoints:
        ui.ok(f"{lesson.base} 대비 변경 없음 — 되짚을 것이 없다")
        ui.done()
        return 0
    _emit_inventory(lesson)
    _emit_points(lesson, limit)
    if lesson.undetermined:
        ui.phase(f"기계가 못 본 것 — {len(lesson.undetermined)}건")
        for path, why in lesson.undetermined[:5]:
            ui.step(ui.dim(f"    {path} — {why}"))
    if report or out:
        ui.step("")
        ui.ok(f"보고서: {os.path.relpath(_write_report(root, lesson, out or _REPORT_REL), root)}")
    ui.done()
    return 0
