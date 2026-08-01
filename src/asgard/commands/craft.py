"""asgard craft — 변경분 미시 형상의 사람 표면.

계약 세 줄: ① 막는 것과 알리는 것을 화면에서 섞지 않는다 — 무엇을 고쳐야 통과하는지가 첫 화면에
있어야 한다, ② 판정마다 처방을 같이 넣는다 (증상만 말하는 게이트는 재작업을 안내하지 못한다),
③ 물려받은 부채와 미판정을 같은 화면에 넣는다 — "0건 통과"가 "안 봤다"를 뜻할 수 있으면 안 된다.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from .. import craft, ui
from .health import _project_root

_RULE_LABEL = {
    "unit-oversize": "함수가 예산을 넘었다",
    "unit-deep": "중첩이 예산을 넘었다",
    "cache-on-method": "메서드 캐시가 인스턴스를 붙잡는다",
    "cache-unbounded": "캐시에 경계가 없다",
    "unclosed-acquire": "획득한 자원을 아무도 안 닫는다",
    "unbounded-accumulator": "모듈 스코프가 자라기만 한다",
    "quadratic-scan": "입력이 열 배면 시간이 백 배다",
    "file-growth": "파일이 문턱을 넘었다",
    # 주석 — 읽는 사람이 비유를 먼저 풀어야 하는 문장
    "note-metaphor": "주석이 비유로 설명한다",
    "note-jargon": "주석에 지어낸 말이 있다",
    # C 계열 — 회수해 주는 런타임이 없으니 이름도 더 분명해야 한다
    "c-alloc-unfreed": "할당에 주인이 없다",
    "c-alloc-unchecked": "할당 실패를 안 본다",
    "c-realloc-self-assign": "realloc 자기대입 — 실패하면 원본을 잃는다",
    "c-handle-unclosed": "연 것을 안 닫는다",
    "c-unbounded-copy": "대상 크기를 모르는 복사",
    "c-quadratic-scan": "입력이 열 배면 시간이 백 배다",
}


def _where(finding: craft.Finding) -> str:
    return f"{finding.path}:{finding.line}" + (f" {finding.unit}" if finding.unit else "")


def _emit(finding: craft.Finding, warn: bool) -> None:
    line = f"{_RULE_LABEL.get(finding.rule, finding.rule)} — {_where(finding)}"
    (ui.warn if warn else ui.step)(line)
    ui.step(ui.dim(f"    {finding.detail}"))
    ui.step(ui.dim(f"    → {finding.fix}"))


def _payload(report: craft.Report) -> str:
    return json.dumps(
        {
            "base": report.base,
            "judged": list(report.judged),
            "undetermined": [{"path": p, "why": w} for p, w in report.undetermined],
            "inherited": report.inherited,
            "blocking": [asdict(f) for f in report.blocking],
            "findings": [asdict(f) for f in report.findings],
        },
        ensure_ascii=False,
        indent=2,
    )


def run_craft(*, base: str = "HEAD", paths: tuple[str, ...] = (), json_out: bool = False, quiet: bool = False) -> int:
    """종료 코드 = 막는 판정이 있으면 1. 알림만 있으면 0 — 알림은 통과를 막지 않는다."""
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)
    targets = paths or craft.changed_paths(root, base)
    report = craft.judge(root, targets, base)

    if json_out:
        print(_payload(report))
        return 1 if report.blocking else 0

    ui.head(f"craft · 변경분 미시 형상 ({report.base})")
    if not targets:
        ui.ok(f"{report.base} 대비 변경 없음 — 판정할 것이 없다")
        ui.done()
        return 0
    ui.step(f"판정한 파일 {len(report.judged)}개")
    if report.undetermined:
        ui.warn(f"미판정 {len(report.undetermined)} — {', '.join(p for p, _ in report.undetermined[:5])}")
        ui.step(ui.dim(f"    {report.undetermined[0][1]}"))

    blocking = report.blocking
    if blocking:
        ui.phase(f"이번 변경이 더 나쁘게 만든 것 — {len(blocking)}건")
        for finding in blocking:
            _emit(finding, warn=True)

    notes = [f for f in report.findings if not f.blocking]
    if notes:
        ui.phase(f"알림 — {len(notes)}건 (막지 않는다)")
        for finding in notes:
            _emit(finding, warn=False)

    if report.inherited:
        ui.step(ui.dim(f"기존 부채 {report.inherited}건은 이번 변경의 책임이 아니라 넘겼다 (래칫)"))
    if not blocking:
        ui.ok("막는 판정 없음 — 손댄 자리가 이전보다 나빠지지 않았다")
    ui.done()
    return 1 if blocking else 0
