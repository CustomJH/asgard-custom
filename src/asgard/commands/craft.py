"""asgard craft — 변경분 미시 형상의 사람 표면.

계약 네 줄: ① 막는 것과 알리는 것을 화면에서 섞지 않는다 — 무엇을 고쳐야 통과하는지가 첫 화면에
있어야 한다, ② 판정마다 처방을 같이 넣는다 (증상만 말하는 게이트는 재작업을 안내하지 못한다),
③ 물려받은 부채와 미판정을 같은 화면에 넣는다 — "0건 통과"가 "안 봤다"를 뜻할 수 있으면 안 된다,
④ `--fix` 로 고친 것은 **따로 떨어진 구획**에 적는다 — "5건 고침"이 "통과"로 읽히면 안 된다.

`--fix` 는 판정 → 수리 → 재판정 순으로 돈다. 종료 코드는 언제나 **재판정** 결과로 센다.
`--dry-run` 은 아무것도 쓰지 않으므로 재판정도 고치기 전 상태를 본다 — 그것이 정직한 값이다.
`--json` 의 `fix` 칸은 `--fix` 를 줬을 때만 생긴다. 안 한 일을 0으로 적지 않는다.

수리에는 래칫이 없다. 판정은 이번 변경이 나쁘게 만든 것만 막지만 수리는 판정한 파일의 주석을
전부 고치므로, 이 세션이 손대지 않은 줄도 다시 쓰인다 (근거는 craft_fix 의 모듈 독스트링).
그래서 화면과 `fix.files` 는 고친 파일을 개수가 아니라 이름으로 부른다.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from .. import craft, craft_fix, ui
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


def _fix_payload(report: craft.Report, fixed: craft_fix.FixReport) -> dict[str, object]:
    return {
        "applied": [asdict(r) for r in fixed.applied],
        "refused": [asdict(r) for r in fixed.refused],
        "files": list(fixed.files),
        "remaining_blocking": len(report.blocking),
    }


def _payload(report: craft.Report, fixed: craft_fix.FixReport | None) -> str:
    body: dict[str, object] = {
        "base": report.base,
        "judged": list(report.judged),
        "undetermined": [{"path": p, "why": w} for p, w in report.undetermined],
        "moved": [{"path": p, "from": o} for p, o in report.moved],
        "inherited": report.inherited,
        "blocking": [asdict(f) for f in report.blocking],
        "findings": [asdict(f) for f in report.findings],
    }
    if fixed is not None:
        body["fix"] = _fix_payload(report, fixed)
    return json.dumps(body, ensure_ascii=False, indent=2)


def _emit_fix(fixed: craft_fix.FixReport, dry_run: bool) -> None:
    """네 번째 구획 — 고친 것. 막는 판정 아래에 따로 둔다.

    다시 쓴 파일은 이름으로 부른다. 수리에는 래칫이 없어서 이번 변경이 넣지 않은 줄도 고쳐지므로,
    개수만 적으면 어느 파일이 손 밖에서 바뀌었는지 화면에서 알 수 없다."""
    title = "고칠 수 있는 것" if dry_run else "고친 것"
    tail = " · 쓰지 않았다" if dry_run else ""
    ui.phase(f"{title} — {len(fixed.applied)}건 / 파일 {len(fixed.files)}개{tail}")
    if not fixed.applied:
        ui.step(ui.dim("    표준 표현이 하나로 정해지는 자리가 없었어요"))
    for item in fixed.applied:
        ui.step(f"{item.path}:{item.line} {_RULE_LABEL.get(item.rule, item.rule)}")
        ui.step(ui.dim(f"    - {item.before.strip()}"))
        ui.step(ui.dim(f"    + {item.after.strip()}"))
    if fixed.files:
        verb = "다시 썼을 파일" if dry_run else "다시 쓴 파일"
        ui.step(ui.dim(f"    {verb} — {', '.join(fixed.files)} (래칫이 없어서 이번 변경 밖의 주석도 고쳐요)"))
    if fixed.refused:
        ui.step(
            ui.dim(f"    자동으로 못 고친 게 {len(fixed.refused)}건 있어요 — 어떻게 고칠지는 위 판정에 적어 뒀어요")
        )


def _verdict(blocking: tuple[craft.Finding, ...], fixed: craft_fix.FixReport | None) -> None:
    if not blocking:
        ui.ok("막는 판정이 없어요 — 손댄 자리가 이전보다 나빠지진 않았어요")
    elif fixed is not None:
        ui.fail(f"고친 뒤에도 막는 판정이 {len(blocking)}건 남아요 — 고쳤다고 통과는 아니에요")


def _render(report: craft.Report, targets: tuple[str, ...], fixed: craft_fix.FixReport | None, dry_run: bool) -> None:
    ui.head(f"craft · 변경분 미시 형상 ({report.base})")
    if not targets:
        ui.ok(f"{report.base} 대비 달라진 게 없어요 — 판정할 게 없네요")
        ui.done()
        return
    ui.step(f"판정한 파일 {len(report.judged)}개")
    if report.moved:
        pairs = ", ".join(f"{old} → {new}" for new, old in report.moved[:3])
        ui.step(ui.dim(f"자리를 옮긴 파일 {len(report.moved)}개는 옛 경로에서 기준선을 이어 봤어요 — {pairs}"))
    if report.undetermined:
        ui.warn(
            f"판정에서 빠진 게 {len(report.undetermined)}건 있어요 — {', '.join(p for p, _ in report.undetermined[:5])}"
        )
        ui.step(ui.dim(f"    {report.undetermined[0][1]}"))

    blocking = report.blocking
    if blocking:
        ui.phase(f"이번 변경이 더 나쁘게 만든 것 — {len(blocking)}건")
        for finding in blocking:
            _emit(finding, warn=True)

    notes = [f for f in report.findings if not f.blocking]
    if notes:
        ui.phase(f"알림 — {len(notes)}건, 막지는 않아요")
        for finding in notes:
            _emit(finding, warn=False)

    if fixed is not None:
        _emit_fix(fixed, dry_run)
    if report.inherited:
        ui.step(ui.dim(f"원래 있던 {report.inherited}건은 이번 변경 책임이 아니라 넘겼어요 (래칫)"))
    _verdict(blocking, fixed)
    ui.done()


def run_craft(
    *,
    base: str = "HEAD",
    paths: tuple[str, ...] = (),
    json_out: bool = False,
    quiet: bool = False,
    fix: bool = False,
    dry_run: bool = False,
) -> int:
    """종료 코드 = 막는 판정이 있으면 1, `--dry-run` 오용이면 2. 알림만 있으면 0."""
    if dry_run and not fix:
        ui.fail("--dry-run은 --fix와 같이 써 주세요 — 무엇을 고칠지 정하는 건 --fix예요")
        return 2
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)
    targets = paths or craft.changed_paths(root, base)
    fixed = craft_fix.apply(root, targets, base, write=not dry_run) if fix else None
    report = craft.judge(root, targets, base)

    if json_out:
        print(_payload(report, fixed))
        return 1 if report.blocking else 0

    _render(report, targets, fixed, dry_run)
    return 1 if report.blocking else 0
