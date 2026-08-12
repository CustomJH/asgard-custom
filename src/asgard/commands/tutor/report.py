"""보고서(`--report`) — 화면에 없는 절이 하나 더 있는 자리.

**왜 이렇게 했는가**. 그 칸의 절반은 기계가 채우고(`tutor_rationale`), 나머지 절반은 코드를
쓴 쪽이 채운다. 그 빈칸을 다른 절이 대신 채우지 않게 하는 것이 이 모듈의 배치 규칙이다.
"""

from __future__ import annotations

import os
from typing import Any

from ... import tutor
from .engines import _rationale_lines
from .labels import _KIND, _point_counts, _point_label, _shown_rows, _summary, _units_line

_REPORT_REL = os.path.join(".asgard", "tutor", "last-review.md")
_WHY_SLOT = (
    "> 이 절은 기계가 채우지 않는다. 코드를 쓴 쪽이 여기에 답을 적고, 읽는 쪽이 그 답을 검사한다.\n"
    "> 세 가지만 적으면 된다 — **무엇을 하려 했는가 / 왜 이 방법인가 / 버린 방법은 무엇이고 왜 버렸는가**.\n"
)
_ANSWER_SLOT = "  - 답: "  # `--collect`가 되읽는 자리 — 형식을 바꾸면 그 파서도 같이 바꿔야 한다
_REPORT_STEP_LIMIT = 12  # 보고서는 지도다. 원시 단위 목록은 JSON이 맡는다
_REPORT_DETAIL_LIMIT = 20
_REPORT_TERM_LIMIT = 8
_REPORT_GAP_LIMIT = 8


def _report_mandate(lesson: tutor.Lesson) -> list[str]:
    """0 절 — 좌표의 출처. **2 절(왜 이렇게 했는가)을 대신 채우지 않는다.**

    두 절은 다른 물음이다. 0 절은 "왜 하필 여기였나"이고 답이 기계에 있다. 2 절은 "왜 이렇게
    고쳤나"이고 답은 코드를 쓴 쪽에만 있다 — 컨트롤러는 자리를 골랐을 뿐 설계를 안 했다.
    섞으면 저자가 2 절을 이미 채워진 것으로 읽고 넘긴다.
    """
    if not lesson.mandate:
        return []
    lines = [
        "## 0. 왜 이 자리였나",
        "",
        "이 변경은 요청이 아니라 **컨트롤러가 고른 것**이다. 아래는 그 선택의 기계 근거다 —",
        "diff에는 안 적혀 있고 코드를 읽어서 유도할 수도 없다.",
        "",
    ]
    for m in lesson.mandate:
        where = f"`{m.get('path')}:{m.get('line')}`" + (f" `{m['unit']}`" if m.get("unit") else "")
        lines += [
            f"- **{m.get('step')}** {where}",
            f"  - 움직이려는 지표: `{m.get('metric')}` — 지금 {m.get('current')}, 목표 {m.get('target')}"
            f" ({m.get('source')})",
            f"  - 검증하려고 읽어야 하는 줄: **{m.get('read')}** · 점수 {m.get('score')}",
            f"  - {m.get('why')}",
        ]
        for other in m.get("runners_up") or []:
            lines.append(f"  - 밀린 후보: {other}")
    lines.append("")
    return lines


def _report_files(lesson: tutor.Lesson) -> list[str]:
    lines = ["## 1. 무엇이 어떻게 바뀌었나", "", f"기준 `{lesson.base}` 대비 — {_summary(lesson)}.", ""]
    lines += ["| 파일 | 행 | 단위 |", "| --- | --- | --- |"]
    for change in lesson.files:
        name = f"`{change.path}`" + (" *(신규)*" if change.new_file else "")
        lines.append(f"| {name} | +{change.added}/-{change.removed} | {_units_line(change)} |")
    # 신규 파일은 단위가 전부 새것이라 나열할 값이 없다 — 표의 개수로 충분하고, 나열하면
    # 기존 파일에서 실제로 생기고 사라진 것이 그 속에 묻힌다.
    detail = [
        f
        for f in lesson.files
        if not f.new_file and (f.units_added or f.units_removed or getattr(f, "units_moved", ()))
    ]
    if detail:
        lines += ["", "대표 함수 수준 변화:", ""]
        rows: list[str] = []
        for change in detail:
            for name in change.units_added:
                rows.append(f"- `{change.path}` — 새 단위 `{name}`")
            for name in change.units_removed:
                rows.append(f"- `{change.path}` — 사라진 단위 `{name}`")
            for move in getattr(change, "units_moved", ()):
                rows.append(f"- `{change.path}` — 옮긴 단위 `{move}`")
        lines += rows[:_REPORT_DETAIL_LIMIT]
        if len(rows) > _REPORT_DETAIL_LIMIT:
            lines.append(f"- 나머지 {len(rows) - _REPORT_DETAIL_LIMIT}건은 위 표와 `--json` 인벤토리에 접어 뒀다.")
    return lines


def _report_points(
    lesson: tutor.Lesson,
    rows: list[tuple[tutor.Checkpoint, str]] | None = None,
    limit: int = 1,
) -> list[str]:
    lines = ["## 3. 당신이 직접 확인할 것", ""]
    if not lesson.ranked:
        lines.append("기계가 짚을 자리는 없었다. 그래도 위 2절의 답이 스스로 납득되는지는 사람만 판정할 수 있다.")
        return lines
    shaped = rows if rows is not None else [(point, "full") for point in lesson.ranked]
    shown = _shown_rows(shaped, limit)
    counts = _point_counts(shaped)
    labels = " · ".join(f"{_KIND.get(kind, kind)} {count}건" for kind, count in sorted(counts.items()))
    lines.append(f"기계 후보 {len(shaped)}건 ({labels}) 중 이번 회차에는 {len(shown)}건만 묻는다.")
    lines.append("체크박스는 읽었다는 뜻이 아니라 **답했다**는 뜻이다.")
    lines.append("`답:` 칸에 적고 `asgard tutor --collect`를 돌리면 답이 성장 기록으로 들어간다.")
    lines.append("")
    for point, _ in shown:
        lines += [
            f"- [ ] **{_point_label(point)}** — `{point.where}` `{point.cid}`",
            f"  - 사실: {point.what}",
            f"  - 왜 당신 눈이 필요한가: {point.why}",
            f"  - **물음: {point.ask}**",
            _ANSWER_SLOT,
        ]
    if len(shaped) > len(shown):
        lines += [
            "",
            "나머지 후보는 질문으로 기록하지 않았다. 원시 판정은 `asgard tutor --json`에서 볼 수 있다.",
        ]
    return lines


def _report_explain(exp: Any, include_recall: bool = True) -> list[str]:
    """1 절과 2 절 사이 — 읽는 순서와 말뜻. **2 절을 대신 채우지 않는다.**

    0 절과 같은 이유로 2 절 앞에 둔다. 여기 있는 것은 "어디부터 읽어야 하는가"이고, 답이
    diff 에 있다. 2 절은 "왜 이렇게 고쳤나"이고 답은 코드를 쓴 쪽에만 있다 — 뒤에 두면 저자가
    설명을 읽은 뒤 2 절을 이미 채워진 것으로 보고 넘긴다.
    """
    if exp is None or not (exp.steps or exp.terms or exp.checks or exp.recall):
        return []
    lines = ["", "## 1-1. 이 변경을 읽는 순서", ""]
    overview = str(getattr(exp, "overview", "") or "").strip()
    if overview:
        lines += [overview, ""]
    if exp.mission:
        lines += [f"향하는 곳: {exp.mission}", ""]
    primary = int(getattr(exp, "primary_units", 0) or len(exp.steps))
    step_limit = min(_REPORT_STEP_LIMIT, primary)
    for step in exp.steps[:step_limit]:
        where = f"`{step.path}:{step.line}`" + (f" `{step.unit}`" if step.unit else "")
        does = str(getattr(step, "does", "") or "").strip()
        lines.append(f"{step.order}. {where} — {does or step.what}")
        if does:
            lines.append(f"   - {step.what}")
        lines.append(f"   - {step.why_here}")
    total = int(getattr(exp, "total_units", 0) or len(exp.steps))
    if total > step_limit:
        lines += [
            "",
            f"나머지 {total - step_limit}개 단위는 다른 흐름이라 여기서 접었다. "
            "전체 지도는 `asgard tutor --explain`로 본다.",
        ]
    if exp.terms:
        lines += ["", "이 변경이 쓰는 말:", ""]
        lines += [f"- **{t.name}** — {t.gloss} (`{t.where}` · {t.source})" for t in exp.terms[:_REPORT_TERM_LIMIT]]
        if len(exp.terms) > _REPORT_TERM_LIMIT:
            lines.append(f"- 나머지 {len(exp.terms) - _REPORT_TERM_LIMIT}개 말은 다음 회차로 넘긴다.")
    if exp.checks:
        lines += ["", "직접 쳐 볼 확인 명령:", ""]
        lines += [f"- `{c}`" for c in exp.checks]
    if include_recall and exp.recall:
        lines += ["", "되짚어 볼 물음:", ""]
        lines += [f"- {q}" for q in exp.recall]
    if exp.gaps:
        lines += ["", "설명이 못 닿은 자리:", ""]
        lines += [f"- `{where}` — {why}" for where, why in exp.gaps[:_REPORT_GAP_LIMIT]]
        if len(exp.gaps) > _REPORT_GAP_LIMIT:
            lines.append(f"- 나머지 {len(exp.gaps) - _REPORT_GAP_LIMIT}개 한계는 원시 JSON에 남겼다.")
    return lines


def _report_why(why: Any) -> list[str]:
    """2 절의 본문 — 기록이 있으면 사실로, 없으면 빈칸으로.

    빈칸이 계약이던 이유는 저자가 사람이라는 전제였다(모듈 계약 ③). 에이전트가 쓴 변경에는 그
    저자가 없고, 대신 퀘스트 로그에 그 턴이 무엇을 맞추려 했고 무엇으로 닫혔는지가 남아 있다.
    그래도 **왜 이 방법이었나**는 여전히 사람 칸이라, 기록을 실은 뒤에도 빈칸 안내는 남긴다.
    """
    rows = _rationale_lines(why)
    if not rows:
        return [_WHY_SLOT]
    body = ["기록: 퀘스트 로그가 이 변경의 목표와 검증을 이렇게 적어 뒀다.", ""]
    body += [f"- {line.strip()}" for line in rows[1:] if line.strip()]
    body += ["", "아래 빈칸은 그 기록이 답하지 못하는 것이다 — **왜 이 방법이었고, 버린 방법은 무엇인가**.", ""]
    return body + [_WHY_SLOT]


def _report(
    lesson: tutor.Lesson,
    exp: Any = None,
    rows: list[tuple[tutor.Checkpoint, str]] | None = None,
    limit: int = 1,
    why: Any = None,
) -> str:
    lines = [
        "# 변경 되짚기",
        "",
        f"`asgard tutor`가 기준 `{lesson.base}` 대비 만든 자료다. 사실은 기계가, 답은 사람이 채운다.",
        "",
    ]
    lines += _report_mandate(lesson)
    lines += _report_files(lesson)
    shown = _shown_rows(rows or [(point, "full") for point in lesson.ranked], limit)
    lines += _report_explain(exp, include_recall=not bool(shown))
    lines += ["", "## 2. 왜 이렇게 했는가", "", *_report_why(why)]
    lines += ["", *_report_points(lesson, rows, limit)]
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


def _write_report(
    root: str,
    lesson: tutor.Lesson,
    out: str,
    exp: Any = None,
    rows: list[tuple[tutor.Checkpoint, str]] | None = None,
    limit: int = 1,
    why: Any = None,
) -> str:
    from ...io_files import write_text

    path = out if os.path.isabs(out) else os.path.join(root, out)
    write_text(path, _report(lesson, exp, rows, limit, why))
    return path
