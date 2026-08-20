"""진입점 — 플래그 하나를 갈래 하나에 맞추고, 기본 갈래(이번 변경 되짚기)를 직접 돈다."""

from __future__ import annotations

import os

from ... import tutor, ui
from ..health import _project_root
from .answers import _run_collect
from .engines import _explanation, _learned, _rationale
from .lanes import (
    _placement,
    _run_brief,
    _run_close,
    _run_debt,
    _run_exam,
    _run_expect,
    _run_explain,
    _run_mission,
    _run_progress,
    _run_recap,
    _run_settle,
    _run_tip,
    _run_track,
)
from .payload import _payload
from .report import _REPORT_REL, _write_report
from .screen import _emit_review


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
    recap: bool = False,
    span: str = "session",
    debt: bool = False,
    tip: bool = False,
    expect: bool = False,
    settle: str = "",
    sid: str = "",
    explain: bool = False,
    depth: str = "",
    mission: bool = False,
    quiz: bool = False,
    track: bool = False,
    exam: str = "",
) -> int:
    """종료 코드는 언제나 0 — 튜터는 규율이지 관문이 아니다(`health`와 같은 등급)."""
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)

    if track:
        return _run_track(root, json_out)
    # `--exam`은 `--answer`보다 위다 — 같은 옵션이 여기서는 채점 답이고 아래에서는 닫을 표식이라,
    # 트랙 이름이 있는 쪽을 먼저 고른다. 내려 두면 시험 답이 물음 닫기로 새서 표식을 못 찾고 끝난다.
    if exam:
        return _run_exam(root, exam, answer, json_out)
    if mission:
        return _run_mission(root, text or note, json_out)
    if explain:
        return _run_explain(root, base, paths, depth, json_out)
    if settle:
        return _run_settle(root, settle, note)
    if expect:
        return _run_expect(root, sid, text or note, json_out)
    if tip:
        return _run_tip(root, sid, 1)  # 도중에 놓는 것은 언제나 하나다 — 둘이면 그건 카드지 팁이 아니다
    if debt:
        return _run_debt(root, sid, json_out)
    if recap:
        return _run_recap(root, sid, span, json_out, quiet)
    if answer or dismiss:
        return _run_close(root, answer, dismiss, note)
    if collect:
        return _run_collect(root, out or _REPORT_REL)
    if progress:
        return _run_progress(root, json_out)
    if brief:
        return _run_brief(root, text, paths, quiet or json_out)
    return _run_review(
        root,
        base,
        paths,
        json_out=json_out,
        report=report,
        out=out,
        limit=limit,
        record=record,
        depth=depth,
        quiz=tutor.mode(root, "quiz" if quiz else "") == "quiz",
        session=sid,
    )


def _run_review(
    root: str,
    base: str,
    paths: tuple[str, ...],
    *,
    json_out: bool,
    report: bool,
    out: str,
    limit: int,
    record: bool,
    depth: str,
    quiz: bool = True,
    session: str = "",
) -> int:
    """기본 갈래 — 이번 변경을 화면이나 JSON, 그리고 보고서로 돌려준다."""
    lesson = tutor.review(root, base, paths)
    # 화면에 들어갔으면 물은 것이다 — 사람이 보는 호출은 그대로 센다. `--json`만 예외로 두는 이유:
    # 기계가 훑어보는 호출까지 세면 "몇 번 물었나"가 사람이 몇 번 봤나와 무관해진다(`--record`로 켠다).
    # 세는 범위는 `limit` 까지다 — 판정이 100건을 찾아도 화면에 여섯이면 물은 것은 여섯이다.
    # `explain` 모드는 물음을 놓지 않으므로 세지도 않는다 — 안 물은 것을 물었다고 세면 조절
    # (fading)·재방문이 사람이 본 적 없는 회차 위에서 돈다.
    rows, back = tutor.hand_back(root, lesson.ranked, limit, count=quiz and (record or not json_out))
    # 설명은 실을 자리가 있을 때만 만든다 — 기본 화면(`--explain` 없이)은 물음 축만 놓는다.
    exp = _explanation(root, base, paths, depth) if (json_out or report or out) else None

    # 보고서를 `--json`보다 **먼저** 쓴다. 훅은 언제나 `--json --record --report`로 부르므로 JSON
    # 갈래에서 먼저 돌아서면 카드가 가리키는 `.asgard/tutor/last-review.md`가 영영 안 갱신된다
    # (26-07-27 이후 8일간 그렇게 멈춰 있었다). 되짚을 게 없을 때 안 쓰는 것은 그대로다 —
    # 빈 보고서로 덮으면 직전에 쓴 진짜 보고서가 사라진다.
    why = _rationale(root, paths or tuple(f.path for f in lesson.files), quiz, session)
    written = ""
    if (report or out) and (lesson.files or lesson.checkpoints):
        written = os.path.relpath(_write_report(root, lesson, out or _REPORT_REL, exp, rows, limit, why), root)

    # 세는 조건은 물음 쪽(`hand_back`)과 같다 — 화면이나 보고서로 사람 앞에 나간 회차만 병합한다.
    if record or not json_out:
        _learned(root, exp)

    if json_out:
        print(_payload(lesson, rows, back, exp, written, limit, why, quiz, track=_placement(root)))
        return 0
    _emit_review(lesson, rows, back, limit, written, why, quiz)
    return 0
