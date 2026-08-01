"""asgard tutor — 되짚기 자료의 사람 표면.

계약 세 줄: ① **사실과 물음을 화면에서 분리한다** — 무엇이 바뀌었나가 먼저, 당신이 답할
것이 그 다음이다. ② 순위를 매겨 위에서부터 넣는다 — 스무 개를 나란히 늘어놓으면 아무도 첫
번째부터 보지 않는다. ③ 못 본 것을 같은 화면에 넣는다 — "확인할 것 0건"이 "안 봤다"를 뜻할 수
있으면 이 도구는 거짓말을 하는 것이다.

보고서(`--report`)에는 화면에 없는 절이 하나 더 있다: **왜 이렇게 했는가**. 기계는 그 칸을
채울 수 없고 채우려 들면 안 된다 — 빈칸으로 남겨 코드를 쓴 쪽이 채우고 사용자가 검사한다.

여기 표면이 넷 더 있다. 물음만 놓고 끝나던 층을 **왕복**으로 만드는 것들이다:
`--answer`/`--dismiss`는 답이 돌아오는 통로(답이 없으면 이 층은 아무것도 못 배운다),
`--collect`는 보고서에 손으로 적은 답을 한 번에 모아 오는 통로(편집기에서 적는 것이 실제
사람이 답하는 방식이다), `--progress`는 그 왕복이 쌓인 결과, `--brief`는 같은 자리를 다시
건드리기 **전에** 남은 물음을 꺼내는 통로다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict

from .. import tutor, tutor_growth, ui
from .health import _project_root

_KIND = tutor.KIND_LABEL  # 이름은 엔진이 갖는다 — 표면마다 다시 쓰면 화면마다 다르게 불린다
_REPORT_REL = os.path.join(".asgard", "tutor", "last-review.md")
_WHY_SLOT = (
    "> 이 절은 기계가 채우지 않는다. 코드를 쓴 쪽이 여기에 답을 적고, 읽는 쪽이 그 답을 검사한다.\n"
    "> 세 가지만 적으면 된다 — **무엇을 하려 했는가 / 왜 이 방법인가 / 버린 방법은 무엇이고 왜 버렸는가**.\n"
)
_ANSWER_SLOT = "  - 답: "  # `--collect`가 되읽는 자리 — 형식을 바꾸면 그 파서도 같이 바꿔야 한다
_CID_RE = re.compile(r"`([0-9a-f]{8})`")
_ITEM_RE = re.compile(r"^\s*- \[.\] ")
_LADDER = ("○○○", "●○○", "●●○", "●●●")


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
        ui.step(ui.dim(f"    …외 {len(lesson.files) - 20}개 (`--json`이 전부를 싣는다)"))


def _emit_points(rows: list[tuple[tutor.Checkpoint, str]], limit: int) -> None:
    """펼침·접힘·넘침을 한 화면에. 접은 것을 안 적으면 "0건"과 "접었다"가 같은 화면이 된다."""
    if not rows:
        ui.ok("기계가 짚을 자리는 없다 — 그래도 '왜 이렇게 했는가'는 사람만 답할 수 있다")
        return
    open_rows = [r for r in rows if r[1] not in ("fold", "quiet")]
    ui.phase(f"당신이 직접 확인할 것 — {len(rows)}건 (막지 않는다)")
    for point, form in open_rows[:limit]:
        ui.warn(f"{_KIND.get(point.kind, point.kind)} — {point.where}  [{point.cid}]")
        ui.step(ui.dim(f"    {point.what}"))
        if form == "full":  # 왜 당신 눈이 필요한가 — 이미 답해 본 종류에는 세 번째로 설명하지 않는다
            ui.step(ui.dim(f"    {point.why}"))
        ui.step(f"    ▸ {point.ask}")
    if len(open_rows) > limit:
        ui.step(ui.dim(f"    …외 {len(open_rows) - limit}건 (`asgard tutor --report`가 전부를 싣는다)"))
    _emit_folded(rows)


def _emit_folded(rows: list[tuple[tutor.Checkpoint, str]]) -> None:
    folded = _counts(rows, "fold")
    quiet = _counts(rows, "quiet")
    if folded:
        ui.step(ui.dim(f"    접음 — {_count_line(folded)} (이미 답해 온 종류)"))
    if quiet:
        ui.step(ui.dim(f"    접음 — {_count_line(quiet)} (튜터가 스스로 낮춘 종류 · `--progress`)"))


def _counts(rows: list[tuple[tutor.Checkpoint, str]], want: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for point, form in rows:
        if form == want:
            out[point.kind] = out.get(point.kind, 0) + 1
    return out


def _count_line(counts: dict[str, int]) -> str:
    return " · ".join(f"{_KIND.get(k, k)} {n}건" for k, n in sorted(counts.items()))


def _emit_back(back: list[tutor_growth.Revisit]) -> None:
    if not back:
        return
    ui.phase(f"다시 묻는다 — {len(back)}건 (답이 아직 없다)")
    for row in back:
        ui.warn(f"{_KIND.get(row.kind, row.kind)} — {row.where}  [{row.cid}]")
        ui.step(f"    ▸ {row.ask}")


def _payload(lesson: tutor.Lesson, rows: list[tuple[tutor.Checkpoint, str]], back: list) -> str:
    """훅과 화면이 같은 판정을 쓰도록 조절 결과까지 넣는다 — 판정기가 둘이면 반드시 어긋난다."""
    return json.dumps(
        {
            "base": lesson.base,
            "files": [asdict(f) for f in lesson.files],
            "added": lesson.touched[0],
            "removed": lesson.touched[1],
            "checkpoints": [{**asdict(p), "weight": p.weight, "cid": p.cid, "form": form} for p, form in rows],
            "revisits": [
                {"cid": r.cid, "kind": r.kind, "path": r.path, "unit": r.unit, "ask": r.ask, "asks": r.asks}
                for r in back
            ],
            "undetermined": [{"path": p, "why": w} for p, w in lesson.undetermined],
            "mandate": list(lesson.mandate),
        },
        ensure_ascii=False,
        indent=2,
    )


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


# ── 보고서 ─────────────────────────────────────────────────────────


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
        "diff 에는 안 적혀 있고 코드를 읽어서 유도할 수도 없다.",
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
    lines.append("`답:` 칸에 적고 `asgard tutor --collect`를 돌리면 답이 성장 기록으로 들어간다.")
    lines.append("")
    for point in lesson.ranked:
        lines += [
            f"- [ ] **{_KIND.get(point.kind, point.kind)}** — `{point.where}` `{point.cid}`",
            f"  - 사실: {point.what}",
            f"  - 왜 당신 눈이 필요한가: {point.why}",
            f"  - **물음: {point.ask}**",
            _ANSWER_SLOT,
        ]
    return lines


def _report(lesson: tutor.Lesson) -> str:
    lines = [
        "# 변경 되짚기",
        "",
        f"`asgard tutor`가 기준 `{lesson.base}` 대비 만든 자료다. 사실은 기계가, 답은 사람이 채운다.",
        "",
    ]
    lines += _report_mandate(lesson)
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


# ── 답 걷기 ────────────────────────────────────────────────────────


def collect(text: str) -> dict[str, str]:
    """보고서 본문 → {물음 표식: 손으로 적은 답}. 빈 칸은 안 걷는다.

    사람이 실제로 답하는 자리는 명령줄이 아니라 **편집기**다 — 보고서를 열어 놓고 그 자리에
    적는다. 그래서 되걷는 통로가 없으면 그 답은 파일에만 남고 이 층은 계속 아무것도 모른다.
    파서는 일부러 느슨하다: 사람이 손으로 고친 문서를 엄격히 읽으면 대부분 못 읽는다.
    """
    out: dict[str, str] = {}
    cid, buffer, taking = "", [], False
    for line in text.splitlines():
        body = line.strip()
        if _ITEM_RE.match(line):
            _flush(out, cid, buffer)
            found = _CID_RE.search(line)
            cid, buffer, taking = (found.group(1) if found else ""), [], False
            continue
        if body.startswith("- 답:"):
            buffer, taking = [body[len("- 답:") :].strip()], True
            continue
        if taking and body and not body.startswith(("- ", "#", "|", ">")):
            buffer.append(body)  # 여러 줄로 적은 답 — 다음 항목이나 다른 절이 시작될 때까지
            continue
        taking = False
    _flush(out, cid, buffer)
    return out


def _flush(out: dict[str, str], cid: str, buffer: list[str]) -> None:
    body = " ".join(b for b in buffer if b).strip()
    if cid and body:
        out[cid] = body


def _run_collect(root: str, path: str) -> int:
    from ..io_files import read_text

    full = path if os.path.isabs(path) else os.path.join(root, path)
    answers = collect(read_text(full))
    ui.head("tutor · 보고서에 적힌 답을 걷는다")
    if not answers:
        ui.ok(f"{os.path.relpath(full, root)}에 채워진 `답:` 칸이 없다 — 걷을 것이 없다")
        ui.done()
        return 0
    taken, missed = 0, 0
    for cid, body in answers.items():
        ok, note = tutor_growth.answer(root, cid, body)
        if ok:
            taken += 1
            ui.ok(f"[{cid}] {ui.oneline(body, 60)}")
            ui.step(ui.dim(f"    {note}"))
        else:
            missed += 1
    if missed:
        ui.step(ui.dim(f"    {missed}건은 이미 닫혔거나 열린 물음이 아니다 — 건너뛰었다"))
    ui.done(f"{taken}건을 성장 기록에 넣었다")
    return 0


# ── 성장 화면 ──────────────────────────────────────────────────────


def _run_progress(root: str, json_out: bool) -> int:
    data = tutor_growth.summary(root)
    if json_out:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    ui.head("tutor · 같이 자란 기록")
    if not data["topics"]:
        ui.ok("아직 기록이 없다 — 되짚기 카드가 한 번도 안 나왔거나, 이 저장소가 처음이다")
        ui.done()
        return 0
    ui.phase(f"가져간 것 — 답한 물음 {data['answered']}건 (그중 옮겨 적은 답 {data['deep']}건)")
    for row in data["topics"]:
        mark = _LADDER[row["level"]]
        tail = "  ← 접힘" if row["quiet"] else ""
        ui.step(f"{mark} {_KIND.get(row['kind'], row['kind'])}")
        ui.step(ui.dim(f"      물음 {row['asked']} · 답 {row['answered']} · 건너뜀 {row['skipped']}{tail}"))
    ui.phase(f"열린 물음 {data['open']}건 (그중 지금 때가 된 것 {data['due']}건)")
    if data["due"]:
        ui.step(ui.dim("    다음 되짚기 카드에 각도를 바꿔 다시 실린다"))
    if data["quiet"]:
        ui.phase(f"튜터가 스스로 낮춘 탐침 — {len(data['quiet'])}건")
        for kind, why in sorted(data["quiet"].items()):
            ui.warn(f"{_KIND.get(kind, kind)}")
            ui.step(ui.dim(f"    {why}"))
        ui.step(ui.dim("    낮춘 것은 안 묻는 게 아니라 한 줄로 접는 것이다 — 사실은 계속 화면에 남는다"))
    if data["expired"]:
        ui.step(ui.dim(f"    만료 {data['expired']}건 — 코드가 사라졌거나 끝까지 답이 없던 물음"))
    _emit_said(data)
    ui.done()
    return 0


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
        ui.step(ui.dim(f"    “{ui.oneline(str(row.get('said')), 90)}”"))
    ui.step(ui.dim("    같은 자리를 다시 열면 `asgard tutor --brief`가 이 문장을 되돌려 준다"))


# ── 진입점 ─────────────────────────────────────────────────────────


def run_tutor(
    *,
    base: str = "HEAD",
    paths: tuple[str, ...] = (),
    json_out: bool = False,
    report: bool = False,
    out: str = "",
    limit: int = 6,
    quiet: bool = False,
    record: bool = False,
    progress: bool = False,
    brief: bool = False,
    text: str = "",
    answer: str = "",
    dismiss: str = "",
    note: str = "",
    collect: bool = False,
) -> int:
    """종료 코드는 언제나 0 — 튜터는 규율이지 관문이 아니다(`health`와 같은 등급)."""
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)

    if answer or dismiss:
        return _run_close(root, answer, dismiss, note)
    if collect:
        return _run_collect(root, out or _REPORT_REL)
    if progress:
        return _run_progress(root, json_out)
    if brief:
        return _run_brief(root, text, paths, quiet or json_out)

    lesson = tutor.review(root, base, paths)
    # 화면에 들어갔으면 물은 것이다 — 사람이 보는 호출은 그대로 센다. `--json`만 예외로 두는 이유:
    # 기계가 훑어보는 호출까지 세면 "몇 번 물었나"가 사람이 몇 번 봤나와 무관해진다(`--record`로 켠다).
    # 세는 범위는 `limit` 까지다 — 판정이 100건을 찾아도 화면에 여섯이면 물은 것은 여섯이다.
    rows, back = tutor.hand_back(root, lesson.ranked, limit, count=record or not json_out)

    if json_out:
        print(_payload(lesson, rows, back))
        return 0

    ui.head(f"tutor · 이번 변경 되짚기 ({lesson.base})")
    if not lesson.files and not lesson.checkpoints:
        ui.ok(f"{lesson.base} 대비 변경 없음 — 되짚을 것이 없다")
        ui.done()
        return 0
    _emit_mandate(lesson)
    _emit_inventory(lesson)
    _emit_points(rows, limit)
    _emit_back(back)
    if lesson.undetermined:
        ui.phase(f"기계가 못 본 것 — {len(lesson.undetermined)}건")
        for path, why in lesson.undetermined[:5]:
            ui.step(ui.dim(f"    {path} — {why}"))
    if report or out:
        ui.step("")
        ui.ok(f"보고서: {os.path.relpath(_write_report(root, lesson, out or _REPORT_REL), root)}")
    if rows:
        ui.step(ui.dim('    답: `asgard tutor --answer <표식> "..."` · 오탐: `asgard tutor --dismiss <표식>`'))
    ui.done()
    return 0


def _run_close(root: str, answer: str, dismiss: str, note: str) -> int:
    """답 하나를 닫는다. **옳은 답인지는 안 본다** — 채점은 이 층의 일이 아니다(성장 기록 계약 ①)."""
    ui.head("tutor · 물음 닫기")
    if answer:
        ok, message = tutor_growth.answer(root, answer, note)
    else:
        ok, message = tutor_growth.dismiss(root, dismiss, note)
    (ui.ok if ok else ui.warn)(message)
    if not ok:
        ui.step(ui.dim("    열린 물음은 `asgard tutor --progress`로 볼 수 있다"))
    ui.done()
    return 0


def _run_brief(root: str, text: str, paths: tuple[str, ...], quiet: bool) -> int:
    """카드 한 장 또는 침묵.

    `--quiet`는 훅이 켠다. 훅에게 "없다"는 말은 사용자 화면에 그대로 들어갈 빈 카드가 되고, 빈
    카드는 다음 카드의 신뢰를 깎는다 — `ui.ok`는 판정 줄이라 quiet을 무시하므로(ui 계약) 여기서
    끊는다. 사람이 직접 친 경우에만 "없다"고 답한다.
    """
    card = tutor.brief(root, text, paths)
    if card:
        print(card)
        return 0
    if not quiet:
        ui.head("tutor · 들어가기 전")
        ui.ok("이 자리에 남은 답 없는 물음이 없다")
        ui.done()
    return 0
