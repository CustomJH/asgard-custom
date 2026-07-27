"""asgard thor — 토르 절차 엔진의 사람 표면. 동사 하나를 부르거나, 다음 동사를 물어본다.

계약 세 줄: ① 무인자 호출은 정적 메뉴가 아니라 **작업 트리를 읽고** 다음 두어 개를 고른다 —
"무엇부터"에 답하지 못하는 라우터는 라우터가 아니다, ② 동사는 플레이북 원문을 그대로 싣는다
(요약하면 절차가 아니라 인상이 된다), ③ `gate` 는 판정과 처방을 같은 화면에 싣고, 못 잰 것을
숨기지 않는다.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from .. import thor_gate, ui
from .health import _project_root

_ENGINE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "skill_plugins",
    "asgard-thor-thrudvangr",
    "skills",
    "asgard-thor-thrudvangr",
    "engine",
    "reference",
)

# 동사 → (한 줄 설명, 싣는 캐논). 순서가 곧 절차의 호(弧)다 — 메뉴도 이 순서로 낸다.
VERBS: dict[str, tuple[str, str]] = {
    "survey": ("여기서 무엇이 지배하는지부터", "—"),
    "shape": ("쓰기 전에 경계·계약·실패 형상을 정한다", "bilskirnir"),
    "diagnose": ("고칠 자격을 먼저 얻는다 — 재현 없이 편집 금지", "gridarvol"),
    "implement": ("읽힐 형상으로 쓴다", "magni · thjalfi"),
    "migrate": ("되돌릴 수 없는 것 — 승인 게이트가 붙는다", "jarngreipr"),
    "integrate": ("내가 통제하지 못하는 경계 너머", "lightning · vimur"),
    "harden": ("실패 경로를 말이 아니라 실행으로", "mjollnir · lightning"),
    "scale": ("배포된 뒤의 거동", "megingjord"),
    "sweep": ("반환 직전 — 모든 경로가 여기로 모인다", "tanngrisnir"),
    "evidence": ("보고를 보고답게 만드는 것", "tanngrisnir"),
    "squad": ("한 머리보다 큰 변경", "einherjar"),
}
_GATED = {"implement": "asgard craft", "migrate": "asgard thor gate", "integrate": "asgard thor gate",
          "harden": "asgard thor gate", "sweep": "asgard craft + asgard thor gate"}  # fmt: skip

_RULE_LABEL = {
    "sql-interpolated": "질의 문자열을 보간으로 조립한다",
    "swallowed-exception": "예외를 삼킨다",
    "call-no-timeout": "외부 호출에 타임아웃이 없다",
    "secret-literal": "시크릿이 코드에 박혀 있다",
    "tx-external-io": "트랜잭션 안에서 외부 I/O",
    "money-float": "금액을 부동소수로 다룬다",
    "naive-now": "시간대 없는 현재 시각",
}


# ── 동사 ────────────────────────────────────────────────────────────


def _playbook(verb: str) -> str | None:
    path = os.path.join(_ENGINE, f"{verb}.md")
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def _menu(root: str) -> int:
    """무인자 — 작업 트리를 읽고 다음 두어 개를 고른다. 절대 자동 실행하지 않는다."""
    ui.head("thor · 절차 엔진 (Þrúðvangr)")
    changed = thor_gate.changed_paths(root)
    judged = [p for p in changed if thor_gate._language(p)]
    picks: list[tuple[str, str]] = []
    if not changed:
        picks = [("survey", "변경이 없다 — 여기서 무엇이 지배하는지부터 읽는다"),
                 ("shape", "쓸 것이 정해졌으면 경계부터 정한다")]  # fmt: skip
    else:
        report = thor_gate.judge(root, judged) if judged else None
        if report and report.blocking:
            picks.append(("sweep", f"게이트가 {len(report.blocking)}건 막고 있다 — 그것부터"))
        picks.append(("implement", f"변경 {len(changed)}개 — 쓰는 중이면 여기"))
        if any(p.endswith((".sql",)) or "migration" in p.lower() for p in changed):
            picks.append(("migrate", "마이그레이션 파일이 변경분에 있다"))
        picks.append(("sweep", "반환 전이면 여기 — 모든 경로가 여기로 모인다"))
    ui.phase("다음으로 부를 것")
    seen: set[str] = set()
    for verb, why in picks:
        if verb in seen:
            continue
        seen.add(verb)
        ui.step(f"asgard thor {verb}")
        ui.step(ui.dim(f"    {why}"))
    ui.phase("전체 동사")
    for verb, (summary, canon) in VERBS.items():
        gate = _GATED.get(verb)
        tail = f"  [{canon}]" + (f" · {gate}" if gate else "")
        ui.step(f"  {verb:<10} {summary}{ui.dim(tail)}")
    ui.step(ui.dim("추천은 제안이다 — 무엇을 부를지는 사람이 정한다"))
    ui.done()
    return 0


# ── 게이트 ──────────────────────────────────────────────────────────


def _emit(finding: thor_gate.Finding, warn: bool) -> None:
    where = f"{finding.path}:{finding.line}" + (f" {finding.unit}" if finding.unit else "")
    (ui.warn if warn else ui.step)(f"{_RULE_LABEL.get(finding.rule, finding.rule)} — {where}")
    ui.step(ui.dim(f"    {finding.detail}"))
    ui.step(ui.dim(f"    → {finding.fix}"))


def _payload(report: thor_gate.Report) -> str:
    return json.dumps(
        {
            "base": report.base,
            "judged": list(report.judged),
            "undetermined": [{"path": p, "why": w} for p, w in report.undetermined],
            "unmeasured": [{"path": p, "rules": list(r)} for p, r in report.unmeasured],
            "inherited": report.inherited,
            "blocking": [asdict(f) for f in report.blocking],
            "findings": [asdict(f) for f in report.findings],
        },
        ensure_ascii=False,
        indent=2,
    )


def _run_gate(root: str, base: str, paths: tuple[str, ...], json_out: bool) -> int:
    targets = paths or thor_gate.changed_paths(root, base)
    report = thor_gate.judge(root, targets, base)
    if json_out:
        print(_payload(report))
        return 1 if report.blocking else 0

    ui.head(f"thor gate · 변경분 백엔드 정확성 ({report.base})")
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

    if report.unmeasured:
        missing = sorted({rule for _, rules in report.unmeasured for rule in rules})
        ui.step(ui.dim(f"이 언어에서 못 잰 규칙 {len(missing)}종 — {', '.join(missing)}"))
        ui.step(ui.dim("    침묵은 '안 봤다'는 뜻이지 '깨끗하다'가 아니다"))
    if report.inherited:
        ui.step(ui.dim(f"기존 부채 {report.inherited}건은 이번 변경의 책임이 아니라 넘겼다 (래칫)"))
    if not blocking:
        ui.ok("막는 판정 없음 — 손댄 자리가 이전보다 나빠지지 않았다")
    ui.done()
    return 1 if blocking else 0


def _show(verb: str) -> int:
    body = _playbook(verb)
    if body is None:
        ui.warn(f"플레이북을 찾지 못했다: {verb}")
        return 1
    print(body)
    return 0


def run_thor(
    verb: str = "",
    *,
    base: str = "HEAD",
    paths: tuple[str, ...] = (),
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)
    name = verb.strip().lower()
    if not name:
        return _menu(root)
    if name == "gate":
        return _run_gate(root, base, paths, json_out)
    if name not in VERBS:
        ui.warn(f"모르는 동사: {verb}")
        ui.step(ui.dim("아는 동사 — " + ", ".join([*VERBS, "gate"])))
        return 2
    return _show(name)
