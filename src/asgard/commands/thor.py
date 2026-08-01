"""asgard thor — 토르 절차 엔진의 사람 표면. 동사 하나를 부르거나, 다음 동사를 물어본다.

계약 세 줄: ① 무인자 호출은 정적 메뉴가 아니라 **작업 트리를 읽고** 다음 두어 개를 고른다 —
"무엇부터"에 답하지 못하는 라우터는 라우터가 아니다, ② 동사는 플레이북 원문을 그대로 넣는다
(요약하면 절차가 아니라 인상이 된다), ③ `gate`는 판정과 처방을 같은 화면에 싣고, 못 잰 것을
숨기지 않는다.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from .. import thor_gate, thor_survey, thor_trail, ui
from .health import _project_root

# 빈칸마다 "무엇을 읽어야 답이 나오는가"를 같이 넣는다 — 질문만 던지는 화면은 답을 안내하지 못한다.
_BLANK_HINT = {
    "layering": "무엇이 무엇에 의존하는가 — import 방향을 두세 모듈에서 확인",
    "errors": "실패가 코드인가 예외인가 — 카탈로그가 있는가, 즉흥 문자열인가",
    "transactions": "트랜잭션 경계를 어느 계층이 소유하는가",
    "cleanup": "자원을 누가 어디서 닫는가",
}

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
    recorded = thor_survey.load(root)
    if recorded is None:
        picks.append(("survey", "이 저장소를 아직 정찰하지 않았다 — 무엇이 지배하는지부터"))
    elif thor_survey.stale(root, recorded):
        picks.append(("survey", "매니페스트가 바뀌었다 — 정찰 기록이 낡았다"))
    elif drift := thor_survey.drifted(root, recorded):
        picks.append(("survey", f"적힌 뒤 세계가 움직인 판단 — {', '.join(sorted(drift))}"))
    elif recorded.unsourced:
        picks.append(("survey", f"출처를 모르는 판단 — {', '.join(recorded.unsourced)}"))
    elif recorded.blanks:
        picks.append(("survey", f"정찰에 빈칸이 남았다 — {', '.join(recorded.blanks)}"))
    if not changed:
        picks.append(("shape", "변경이 없다 — 쓸 것이 정해졌으면 경계부터 정한다"))
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
    if recorded and not thor_survey.stale(root, recorded):
        known = " · ".join(recorded.ecosystems) or "생태계 미상"
        ui.step(ui.dim(f"정찰 기록: {known} — {', '.join(recorded.languages) or '언어 미상'}"))
    ui.phase("전체 동사")
    for verb, (summary, canon) in VERBS.items():
        gate = _GATED.get(verb)
        tail = f"  [{canon}]" + (f" · {gate}" if gate else "")
        ui.step(f"  {verb:<10} {summary}{ui.dim(tail)}")
    ui.step(ui.dim("추천은 제안이다 — 무엇을 부를지는 사람이 정한다"))
    ui.done()
    return 0


# ── 정찰 ────────────────────────────────────────────────────────────


def _provenance(note: thor_survey.Note, moved: tuple[str, ...] | None) -> str:
    """판단 한 줄 아래 붙는 출처. 모르는 것은 모른다고 쓴다 — 빈칸을 안 채우는 것과 같은 규율이다."""
    if not note.sourced:
        return "출처 미상 — 언제 적혔는지 기록에 없다"
    when = note.at.split("T")[0]
    return f"{when}" + (f" · 그 뒤 {'·'.join(moved)}가 움직였다" if moved else " · 적힌 뒤 움직인 것 없음")


def _run_survey(root: str, notes: tuple[str, ...], json_out: bool) -> int:
    """탐지는 기계가, 판단은 사람이. 빈칸을 추측으로 채우지 않는 것이 이 명령의 계약이다."""
    parsed: dict[str, str] = {}
    for note in notes:
        key, _, value = note.partition("=")
        key = key.strip().lower()
        if key not in thor_survey.JUDGEMENT_KEYS or not value.strip():
            ui.warn(f"모르는 정찰 항목: {note}")
            ui.step(ui.dim("쓸 수 있는 것 — " + ", ".join(thor_survey.JUDGEMENT_KEYS)))
            return 2
        parsed[key] = value.strip()
    survey = thor_survey.refresh(root, parsed)
    thor_survey.save(root, survey)

    if json_out:
        print(
            json.dumps(
                {
                    "ecosystems": survey.ecosystems,
                    "manifests": survey.manifests,
                    "languages": survey.languages,
                    "verifiers": survey.verifiers,
                    "judgement": {
                        key: {"text": note.text, "at": note.at} for key, note in sorted(survey.judgement.items())
                    },
                    "blanks": survey.blanks,
                    "unsourced": survey.unsourced,
                    "drifted": {k: list(v) for k, v in thor_survey.drifted(root, survey).items()},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    ui.head("thor survey · 여기서 무엇이 지배하는가")
    ui.step(f"생태계 — {' · '.join(survey.ecosystems) or '매니페스트를 찾지 못했다'}")
    ui.step(f"언어 — {', '.join(survey.languages) or '판정기가 아는 언어 없음'}")
    ui.step(f"검증 명령 후보 — {', '.join(survey.verifiers) or '없음 (직접 찾아라)'}")
    if survey.judgement:
        drift = thor_survey.drifted(root, survey)
        ui.phase("적어 둔 판단")
        for key, note in sorted(survey.judgement.items()):
            ui.step(f"  {key:<13} {note.text}")
            ui.step(ui.dim(f"                {_provenance(note, drift.get(key))}"))
        if drift:
            ui.warn(f"적힌 뒤 세계가 움직인 판단 {len(drift)} — {', '.join(sorted(drift))}")
            ui.step(ui.dim("    다시 확인하고 --note로 덮어써라 — 낡은 판단은 틀린 판단보다 조용해서 더 위험하다"))
        if survey.unsourced:
            ui.warn(f"출처를 모르는 판단 {len(survey.unsourced)} — {', '.join(survey.unsourced)}")
            ui.step(ui.dim("    언제 적혔는지 모르면 낡았는지도 모른다 — 확인 후 --note로 다시 적어라"))
        if blind := thor_survey.unmeasured(survey):
            ui.step(ui.dim(f"구조 낡음을 못 잰 판단 {len(blind)} — {', '.join(blind)} (지문 자가 바뀌었다)"))
            ui.step(ui.dim("    침묵은 '안 움직였다'가 아니라 '못 쟀다'다 — 다시 적으면 이 줄이 사라진다"))
    if survey.blanks:
        ui.phase(f"빈칸 {len(survey.blanks)} — 코드를 읽어야 아는 것")
        for key in survey.blanks:
            ui.step(f"  {key:<13} {_BLANK_HINT[key]}")
        ui.step(ui.dim("    채우려면 — asgard thor survey --note 'layering=<한 줄>'"))
        ui.step(ui.dim("    추측으로 채우지 마라 — 거짓말하는 기록은 없느니만 못하다"))
    else:
        ui.ok("빈칸 없음 — 다음 세션은 이 기록을 그대로 쓴다")
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


def _changed_count(root: str) -> int:
    """지금 판정 가능한 변경분 수 — 동사가 작업의 어디쯤에서 불렸는지의 유일한 기계 측정치."""
    try:
        return sum(1 for p in thor_gate.changed_paths(root) if thor_gate._language(p))
    except Exception:
        return 0


def _mark(root: str, verb: str, blocking: int | None = None) -> None:
    thor_trail.record(root, verb, _changed_count(root), blocking)


def _run_trail(root: str, json_out: bool) -> int:
    """자취를 사실로만 낸다. "잘 따랐다/아니다"는 여기서 안 나온다 — 그 판정은 사람의 몫이다."""
    seen = thor_trail.adherence(thor_trail.load(root))
    found = thor_trail.escapes(root)
    if json_out:
        print(
            json.dumps(
                {
                    "steps": [asdict(s) for s in seen.steps],
                    "called": list(seen.called),
                    "skipped": list(seen.skipped),
                    "reached_terminal": seen.reached_terminal,
                    "gate_runs": len(seen.gates),
                    "blocked_runs": seen.blocked_runs,
                    "escapes": [asdict(e) for e in found],
                    "escaped": sum(1 for e in found if e.escaped),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    ui.head("thor trail · 절차가 실제로 어떻게 불렸나")
    if not seen.steps:
        ui.step("자취 없음 — 아직 동사를 부른 적이 없다")
        ui.done()
        return 0
    ui.step(f"기록된 호출 {len(seen.steps)}회")
    ui.phase("부른 순서")
    ui.step("  " + " → ".join(seen.called) if seen.called else "  (절차 동사 호출 없음)")
    if seen.skipped:
        ui.step(ui.dim(f"  안 부른 동사 — {', '.join(seen.skipped)}"))
        ui.step(ui.dim("    건너뛰는 것은 자주 옳다. 여기 있는 것은 판정이 아니라 사실이다"))
    ui.step(f"  sweep·evidence 도달 — {'예' if seen.reached_terminal else '아니오'}")
    if seen.gates:
        ui.phase("게이트 실행")
        ui.step(f"  {len(seen.gates)}회 중 막는 판정이 있던 실행 {seen.blocked_runs}회")
        for step in seen.gates[-5:]:
            verdict = "판정 못 냄" if step.blocking is None else f"막는 판정 {step.blocking}건"
            ui.step(ui.dim(f"    {step.at} · 변경 {step.changed}개 · {verdict}"))
    if found:
        escaped = [e for e in found if e.escaped]
        ui.phase("게이트 통과 뒤의 검증 판정")
        ui.step(f"  앞선 게이트가 있는 검증 {len(found)}건 중 게이트가 통과시킨 뒤 검증이 잡은 것 {len(escaped)}건")
        for item in escaped[-5:]:
            ui.step(ui.dim(f"    {item.quest} · 게이트 {item.gate_at} 통과 → 검증 {item.verdict}"))
        ui.step(ui.dim("    두 판정기는 다른 것을 잰다 — 이 수는 '게이트가 버그를 놓쳤다'가 아니라"))
        ui.step(ui.dim("    '게이트 통과가 검증 통과를 함의하지 않는다'만 뜻한다"))
    ui.step(ui.dim("이 화면은 사실만 싣는다 — 절차를 잘 따랐는지는 이 사실을 본 사람이 정한다"))
    ui.done()
    return 0


def _run_gate(root: str, base: str, paths: tuple[str, ...], json_out: bool) -> int:
    targets = paths or thor_gate.changed_paths(root, base)
    report = thor_gate.judge(root, targets, base)
    _mark(root, "gate", len(report.blocking))
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
    notes: tuple[str, ...] = (),
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
    if name == "trail":
        return _run_trail(root, json_out)
    if name not in VERBS:
        ui.warn(f"모르는 동사: {verb}")
        ui.step(ui.dim("아는 동사 — " + ", ".join([*VERBS, "gate", "trail"])))
        return 2
    _mark(root, name)
    if name == "survey":
        # 정찰만 결정론 절반을 갖는다 — 매니페스트는 기계가 읽는 편이 사람보다 낫고 빠짐없다.
        # `--note`로 부른 것은 "배운다"가 아니라 "적는다"이므로 플레이북을 다시 넣지 않는다.
        if not notes and not json_out:
            _show(name)
        return _run_survey(root, notes, json_out)
    return _show(name)
