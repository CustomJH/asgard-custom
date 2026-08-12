"""터미널 화면 — 사실이 먼저, 당신이 답할 것이 그 다음, 못 본 것이 같은 화면에.

셋을 갈라 두는 것이 표면 계약 ①·③ 이다. 접은 것을 안 적으면 "0건"과 "접었다"가 같은 화면이 된다.
"""

from __future__ import annotations

from typing import Any

from ... import tutor, tutor_growth, ui
from .engines import _rationale_lines
from .labels import _KIND, _count_line, _counts, _point_label, _summary, _units_line


def _emit_inventory(lesson: tutor.Lesson) -> None:
    ui.phase(f"무엇이 어떻게 바뀌었나 — {_summary(lesson)}")
    for change in lesson.files[:20]:
        flag = " (신규)" if change.new_file else ""
        ui.step(f"{change.path}{flag} +{change.added}/-{change.removed}")
        ui.step(ui.dim(f"    {_units_line(change)}"))
    if len(lesson.files) > 20:
        ui.step(ui.dim(f"    …외 {len(lesson.files) - 20}개 (`--json`을 붙이면 전부 나와요)"))


def _emit_points(rows: list[tuple[tutor.Checkpoint, str]], limit: int, quiz: bool = True) -> None:
    """펼침·접힘·넘침을 한 화면에. 접은 것을 안 적으면 "0건"과 "접었다"가 같은 화면이 된다."""
    if not rows:
        ui.ok(
            "기계가 짚을 자리는 없어요 — 그래도 왜 이렇게 했는지는 직접 답하셔야 해요"
            if quiz
            else "기계가 짚을 자리는 없어요"
        )
        return
    open_rows = [r for r in rows if r[1] not in ("fold", "quiet")]
    ui.phase(
        f"당신이 직접 확인할 것 — {len(rows)}건 (막지 않아요)"
        if quiz
        else f"짚어 둘 자리 — {len(rows)}건 (막지 않아요)"
    )
    for point, form in open_rows[:limit]:
        mark = f"  [{point.cid}]" if quiz else ""
        ui.warn(f"{_point_label(point)} — {point.where}{mark}")
        ui.step(ui.dim(f"    {point.what}"))
        if form == "full":  # 왜 당신 눈이 필요한가 — 이미 답해 본 종류에는 세 번째로 설명하지 않는다
            ui.step(ui.dim(f"    {point.why}"))
        if quiz:
            ui.step(f"    ▸ {point.ask}")
    if len(open_rows) > limit:
        ui.step(ui.dim(f"    …외 {len(open_rows) - limit}건 (`asgard tutor --report`를 붙이면 전부 나와요)"))
    _emit_folded(rows)


def _emit_folded(rows: list[tuple[tutor.Checkpoint, str]]) -> None:
    folded = _counts(rows, "fold")
    quiet = _counts(rows, "quiet")
    if folded:
        ui.step(ui.dim(f"    접음 — {_count_line(folded)} (이미 답해 온 종류)"))
    if quiet:
        ui.step(ui.dim(f"    접음 — {_count_line(quiet)} (튜터가 스스로 낮춘 종류 · `--progress`)"))


def _emit_back(back: list[tutor_growth.Revisit]) -> None:
    if not back:
        return
    ui.phase(f"다시 여쭤요 — {len(back)}건, 아직 답이 없어요")
    for row in back:
        ui.warn(f"{_KIND.get(row.kind, row.kind)} — {row.where}  [{row.cid}]")
        ui.step(f"    ▸ {row.ask}")


def _emit_mandate(lesson: tutor.Lesson) -> None:
    """컨트롤러가 이 자리를 고른 근거. 사람이 쓴 변경이면 아무것도 안 그린다 (근거가 없다)."""
    if not lesson.mandate:
        return
    ui.phase(f"왜 이 자리였나 — 컨트롤러가 고름 ({len(lesson.mandate)}건)")
    for m in lesson.mandate:
        where = f"{m.get('path')}:{m.get('line')}" + (f" {m['unit']}" if m.get("unit") else "")
        ui.step(f"{m.get('step')}  {where}")
        ui.step(
            ui.dim(
                f"    지표 {m.get('metric')} {m.get('current')} → 목표 {m.get('target')}"
                f" ({m.get('source')}) · 읽을 줄 {m.get('read')} · 점수 {m.get('score')}"
            )
        )
        ui.step(ui.dim(f"    {m.get('why')}"))
        for other in m.get("runners_up") or []:
            ui.step(ui.dim(f"    밀린 후보: {other}"))


def _emit_said(data: dict) -> None:
    """당신이 실제로 적은 문장들. 숫자만 있는 성장 화면은 성장한 것처럼 보이기만 한다.

    이 절이 이 화면의 유일한 **내용**이다 — 나머지는 전부 세는 것이고, 여기만 당신이 남긴 것이다.
    """
    said = [row for row in data.get("recent") or [] if isinstance(row, dict) and row.get("said")]
    if not said:
        return
    ui.phase(f"당신이 남긴 답 — 최근 {len(said)}건")
    for row in said[:5]:
        tag = "오탐" if row.get("reason") == "dismissed" else _KIND.get(row.get("kind"), row.get("kind"))
        where = str(row.get("path") or "")
        ui.step(f"{tag} — {where}{' ' + str(row.get('unit')) if row.get('unit') else ''}")
        ui.step(ui.dim(f'    "{ui.oneline(str(row.get("said")), 90)}"'))
    ui.step(ui.dim("    같은 자리를 다시 열면 `asgard tutor --brief`가 이 문장을 되돌려 줘요"))


def _emit_explain(exp: Any) -> None:
    """읽는 순서 · 말뜻 · 확인 명령 · 못 닿은 자리.

    `owned`면 좌표만 남긴다. 이미 아는 자리를 세 번째로 설명하면 다음 설명도 안 읽는다 —
    `_emit_points`의 접기(fold)와 같은 근거다.
    """
    if exp.mission:
        ui.phase(f"지금 향하는 곳 — {exp.mission}")
    short = exp.depth == "owned"
    if exp.steps:
        ui.phase(f"읽는 순서 — {len(exp.steps)}단계")
    for step in exp.steps:
        ui.step(f"{step.order}. {step.path}:{step.line}" + (f"  {step.unit}" if step.unit else ""))
        if short:
            continue
        does = str(getattr(step, "does", "") or "").strip()
        if does:
            ui.step(ui.dim(f"    하는 일 — {does}"))
        ui.step(ui.dim(f"    {step.what}"))
        if exp.depth != "familiar":  # 두 번째부터는 "왜 여기부터인가"가 이미 아는 말이 된다
            ui.step(ui.dim(f"    {step.why_here}"))
    if not short:
        _emit_terms(exp)
        if exp.checks:
            ui.phase("직접 쳐 보실 것")
            for line in exp.checks:
                ui.step(f"▸ {line}")
        if exp.recall:
            ui.phase("되짚어 보실 물음")
            for line in exp.recall:
                ui.step(f"▸ {line}")
            ui.step(ui.dim("    답은 안 적어 드려요 — 적어 두면 그 답이 당신의 답 자리를 차지해요"))
    if exp.gaps:
        ui.phase(f"설명이 못 닿은 자리 — {len(exp.gaps)}건")
        for where, why in exp.gaps:
            ui.step(ui.dim(f"    {where} — {why}"))


def _emit_terms(exp: Any) -> None:
    if not exp.terms:
        return
    ui.phase(f"이 변경이 쓰는 말 — {len(exp.terms)}개")
    for term in exp.terms:
        ui.step(f"{term.name} — {term.gloss}")
        ui.step(ui.dim(f"    {term.where} · {term.source}"))


def _emit_review(
    lesson: tutor.Lesson,
    rows: list[tuple[tutor.Checkpoint, str]],
    back: list,
    limit: int,
    written: str,
    why: Any = None,
    quiz: bool = True,
) -> None:
    ui.head(f"tutor · 이번 변경 되짚기 ({lesson.base})")
    if not lesson.files and not lesson.checkpoints:
        ui.ok(f"{lesson.base} 대비 달라진 게 없어요 — 되짚을 게 없네요")
        ui.done()
        return
    _emit_mandate(lesson)
    _emit_inventory(lesson)
    _emit_why(why)
    _emit_points(rows, limit, quiz)
    if quiz:
        _emit_back(back)
    if lesson.undetermined:
        ui.phase(f"기계가 못 본 것 — {len(lesson.undetermined)}건")
        for path, reason in lesson.undetermined[:5]:
            ui.step(ui.dim(f"    {path} — {reason}"))
    if written:
        ui.step("")
        ui.ok(f"보고서: {written}")
    if rows and quiz:
        ui.step(ui.dim('    답: `asgard tutor --answer <표식> "..."` · 오탐: `asgard tutor --dismiss <표식>`'))
    ui.done()


def _emit_why(why: Any) -> None:
    """왜 이렇게 했는가 — 퀘스트 기록에서. 기록이 없으면 아무것도 안 그린다(빈칸은 빈칸으로)."""
    rows = _rationale_lines(why)
    if not rows:
        return
    ui.phase(rows[0].removeprefix("⠶ ").strip())
    for line in rows[1:]:
        ui.step(ui.dim("  " + line.strip()))
