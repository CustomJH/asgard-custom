"""asgard style — 이 저장소의 코드 스타일 규격을 선언하고, 변경분에 물린다.

문 셋. `init` 은 저장소를 훑어 찾아낸 도구를 설정에 적는다(그 뒤로는 사용자가 고친 쪽이
정본이다). `list` 는 지금 무엇이 선언돼 있는지 보여 준다. `check` 는 그 도구들을 돌려 판정한다.

`init` 이 따로 있는 이유는 값이다. 감지를 실행 때마다 하면 저장소를 매번 훑고, 사용자가 지운
도구가 다음 실행에서 되살아난다. 한 번 적어 두면 게이트는 설정 파일 한 번 읽는 것으로 이
저장소가 스타일 레인을 들였는지 판단하고, 안 들인 저장소에서는 자식 프로세스를 아예 안 띄운다.

`check --json` 의 형식은 `craft --json` 과 같다 — `blocking` 목록 하나. 게이트 훅이 두 판정기를
한 계약으로 읽기 때문에 여기서 형식을 바꾸면 그쪽이 조용히 못 읽는다.
"""

from __future__ import annotations

import json
import os

from .. import code_style, code_style_catalog, ui
from ..settings import load_project, project_path, save_project
from .health import _project_root


def _payload(report: code_style.Report, enabled: bool = True) -> str:
    def rows(items: list[code_style.Finding]) -> list[dict]:
        return [
            {
                "rule": f.rule,
                "path": f.path,
                "line": f.line,
                "unit": f.unit,
                "detail": f.detail,
                "fix": f.fix,
                "blocking": f.blocking,
            }
            for f in items
        ]

    return json.dumps(
        {
            "configured": True,
            "enabled": enabled,
            "tools": report.tools,
            "scoped": list(report.scoped),
            "repaired": report.repaired,
            "runs": [
                {
                    "tool": r.tool,
                    "command": r.command,
                    "exit_code": r.exit_code,
                    "findings": r.findings,
                    "unparsed": r.unparsed,
                    "error": r.error,
                }
                for r in report.runs
            ],
            "inherited": report.inherited,
            "blocking": rows(report.blocking),
            "findings": rows(report.findings),
        },
        ensure_ascii=False,
        indent=2,
    )


def _emit(finding: code_style.Finding, warn: bool) -> None:
    where = f"{finding.path}:{finding.line}" if finding.line else finding.path
    (ui.warn if warn else ui.step)(f"[{finding.rule}] {where} — {finding.detail}")


def _render(report: code_style.Report) -> None:
    ui.head("style · 이 저장소가 정한 코드 스타일")
    if not report.tools:
        ui.ok("돌릴 도구가 없어요 — 선언된 도구 중 이번 변경의 언어를 맡는 게 없네요")
        ui.done()
        return
    ui.step(f"돌린 도구 {len(report.tools)}개 — {', '.join(report.tools)}")
    if report.repaired:
        ui.warn(
            f"수정 명령 {len(report.repaired)}개를 먼저 돌렸어요 — 파일이 디스크에서 바뀌었으니 다시 읽고 편집하세요"
        )
        for command in report.repaired:
            ui.step(ui.dim(f"    {command}"))

    for run in report.undetermined:
        ui.warn(f"[{run.tool}] 판정을 못 받았어요 — {run.error or f'종료 코드 {run.exit_code}, 읽어낸 판정 0건'}")
        ui.step(ui.dim(f"    {run.command}"))
        if run.unparsed:
            ui.step(ui.dim(f"    출력 {run.unparsed}줄을 형식으로 못 읽었어요 — diagnostic 에 정규식을 적어 주세요"))

    blocking = report.blocking
    if blocking:
        ui.phase(f"이번에 쓴 파일에서 나온 위반 — {len(blocking)}건")
        for finding in blocking[:40]:
            _emit(finding, warn=True)
        if len(blocking) > 40:
            ui.step(ui.dim(f"    …그리고 {len(blocking) - 40}건 더"))
        commands = sorted({f.fix for f in blocking if f.fix})
        for command in commands[:4]:
            ui.step(ui.dim(f"    고치려면 → {command}"))

    if report.inherited:
        ui.step(ui.dim(f"이번 변경 밖에서 나온 {report.inherited}건은 안 막았어요 (물려받은 부채)"))
    if blocking:
        ui.fail(f"막는 위반이 {len(blocking)}건 있어요")
    else:
        ui.ok("이번에 쓴 파일에는 스타일 위반이 없어요")
    ui.done()


def _not_configured() -> None:
    ui.warn("이 저장소는 코드 스타일 규격을 아직 안 들였어요")
    ui.step(ui.dim("    `asgard style init` — 저장소를 훑어 찾아낸 도구를 설정에 적어요"))
    ui.step(
        ui.dim(f"    직접 적으려면 {os.path.join('.asgard', 'asgard-setting-project.json')} 의 code_style.tools 예요")
    )


def run_check(*, paths: tuple[str, ...] = (), json_out: bool = False, repair: str = "") -> int:
    """종료 코드 = 막는 위반이 있으면 1, 없으면 0. 선언이 없으면 0 (안 들인 것은 실패가 아니다).

    `enabled: false` 여도 선언된 도구는 돈다 — 손으로 부른 실행까지 막을 이유가 없다. 대신 그
    상태를 한 줄 말한다: 게이트가 안 보고 있다는 사실을 모르고 초록을 읽으면 안 된다.
    """
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    tools = code_style.declared(root)
    if not tools:
        if json_out:
            print(json.dumps({"tools": [], "blocking": [], "findings": [], "configured": False}, ensure_ascii=False))
            return 0
        _not_configured()
        return 0
    enabled = code_style.configured(root)
    if not enabled and not json_out:
        # `--json` 일 때 이 줄을 화면에 내면 안 된다 — stdout 이 게이트가 파싱하는 통로라,
        # 사람에게 하는 말 한 줄이 그 파싱을 깨고 게이트는 판정을 못 받은 채 통과한다.
        ui.warn("게이트는 꺼져 있어요 (enabled: false) — 이 실행은 손으로 부른 것만 판정해요")
    report = code_style.run(root, tools, paths, repair=repair)
    if json_out:
        print(_payload(report, enabled))
        return 1 if report.blocking else 0
    _render(report)
    return 1 if report.blocking else 0


def run_list(*, json_out: bool = False) -> int:
    """선언된 도구와, 아직 안 적힌 감지 결과를 같은 화면에 둔다."""
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    tools = code_style.declared(root)
    found = code_style_catalog.detect(root)
    unclaimed = [t for t in found if t.name not in {d.name for d in tools}]
    if json_out:
        print(
            json.dumps(
                {
                    "configured": bool(tools),
                    "enabled": code_style.configured(root),
                    "tools": code_style.as_rows(tools),
                    "detected_not_declared": code_style.as_rows(unclaimed),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    ui.head("style · 선언된 규격")
    if not tools:
        _not_configured()
    for tool in tools:
        languages = ", ".join(tool.languages) if tool.languages else "모든 파일"
        ui.step(f"{tool.name} — {languages}")
        ui.step(ui.dim(f"    검사 {tool.check}"))
        if tool.fix:
            ui.step(ui.dim(f"    수정 {tool.fix}" + (" (게이트가 직접 돌려요)" if tool.autofix else "")))
    if unclaimed:
        ui.phase(f"저장소에서 찾았지만 안 적힌 것 — {len(unclaimed)}개")
        for tool in unclaimed:
            ui.step(f"{tool.name} — {tool.check}")
        ui.step(ui.dim("    `asgard style init` 이 이것들을 설정에 적어요"))
    ui.done()
    return 0


def run_init(*, json_out: bool = False, force: bool = False) -> int:
    """감지 결과를 설정에 적는다. 이미 적혀 있으면 `--force` 없이는 안 덮는다."""
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out)
    section = load_project(root).get(code_style.SECTION)
    existing = code_style.declared(root)
    if existing and not force:
        if json_out:
            print(json.dumps({"written": False, "why": "already-declared", "tools": code_style.as_rows(existing)}))
            return 0
        ui.warn(f"이미 도구 {len(existing)}개가 적혀 있어요 — 감지 결과로 덮으려면 --force 예요")
        ui.step(ui.dim(f"    지금 적힌 것은 `asgard style list` 로 봐요 · 파일은 {project_path(root)}"))
        return 0
    found = code_style_catalog.detect(root)
    if not found:
        if json_out:
            print(json.dumps({"written": False, "why": "nothing-detected", "tools": []}))
            return 0
        ui.warn("규격 파일을 못 찾았어요 — 감지는 checkstyle.xml·eslint.config.js 같은 파일이 있어야 걸려요")
        ui.step(ui.dim(f"    직접 적는 자리는 {project_path(root)} 의 code_style.tools 예요"))
        ui.step(ui.dim('    한 항목은 {"name": …, "check": …, "fix": …, "languages": [".java"]} 예요'))
        return 0
    keep = section if isinstance(section, dict) else {}
    body = {k: v for k, v in keep.items() if str(k).startswith("_")}
    body["enabled"] = True
    body["tools"] = code_style.as_rows(found)
    path = save_project(root, code_style.SECTION, body)
    if json_out:
        print(json.dumps({"written": True, "path": path, "tools": body["tools"]}, ensure_ascii=False, indent=2))
        return 0
    ui.head("style · 규격을 설정에 적었어요")
    for tool in found:
        ui.step(f"{tool.name} — {tool.check}")
    ui.step(ui.dim(f"    적힌 자리 {path}"))
    ui.step(ui.dim("    명령이 이 저장소에서 실제로 도는지 `asgard style check` 로 한 번 확인하세요"))
    ui.done()
    return 0
