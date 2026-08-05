"""``asgard review`` — 승인 요청, 실행, 제안 피드백의 사람 표면."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from .. import errors, review_agent, ui
from .health import _project_root

_STATUS = {
    "awaiting_confirmation": "승인 대기",
    "running": "검토 중",
    "open": "제안 있음",
    "no_findings": "제안 없음",
    "closed": "모두 처리",
    "canceled": "호출 안 함",
    "expired": "승인 만료",
    "stale": "범위 달라짐",
    "failed": "실행 실패",
}
_SEVERITY = {"critical": "치명적", "major": "중요", "minor": "보통", "trivial": "사소함", "info": "참고"}


def _surface(json_out: bool, quiet: bool) -> None:
    errors.set_json_surface(json_out)
    ui.set_quiet(json_out or quiet)


def _emit(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _preview(row: dict[str, Any]) -> None:
    scope = row.get("scope") or {}
    paths = list(scope.get("paths") or [])
    ui.head("review · 오딘 확인")
    ui.step(
        f"{scope.get('base') or 'HEAD'} 대비 {len(paths)}파일 · "
        f"+{int(scope.get('added') or 0):,}/-{int(scope.get('removed') or 0):,}행"
    )
    for path in paths[:8]:
        ui.step(ui.dim(f"    {path}"))
    if len(paths) > 8:
        ui.step(ui.dim(f"    …외 {len(paths) - 8}파일"))
    if row.get("focus"):
        ui.step(f"집중할 것: {row['focus']}")
    ui.step(ui.dim("읽기 전용으로 검사하고 제안만 저장해요. 코드 수정과 PASS/FAIL 판정은 하지 않아요."))
    ui.step(ui.dim(f"승인 표식: {row['id']}"))


def _interactive(json_out: bool) -> bool:
    return not json_out and sys.stdin.isatty() and sys.stdout.isatty()


def _ask() -> bool:
    from rich.prompt import Confirm

    return bool(Confirm.ask("  오딘, 이 범위로 asgard-review를 부를까요?", default=False))


def _needs_confirmation(row: dict[str, Any], json_out: bool) -> int:
    command = f"asgard review --approve {row['id']} --yes"
    if json_out:
        _emit(
            {
                "status": "needs_confirmation",
                "request": row,
                "remedy": command + " --json",
                "message": "오딘의 명시 승인을 받은 뒤에만 Review 에이전트를 불러요",
            }
        )
    else:
        ui.warn("아직 Review 에이전트를 부르지 않았어요 — 오딘의 답을 기다려요")
        ui.step(f"승인받은 뒤 실행: {command}")
    return errors.Conflict.exit_code


def _render_result(row: dict[str, Any]) -> None:
    status = str(row.get("status") or "")
    ui.head(f"review · {_STATUS.get(status, status or '결과')}")
    if status in {"running", "canceled", "expired", "failed"}:
        messages = {
            "running": "승인한 범위를 아직 읽고 있어요",
            "canceled": "오딘이 호출하지 않기로 한 요청이에요",
            "expired": "실행하지 않은 채 승인 시간이 끝난 요청이에요",
            "failed": str((row.get("error") or {}).get("message") or "Review 실행이 끝나지 못했어요"),
        }
        ui.step(messages[status])
        ui.done()
        return
    if status == "stale" and not row.get("finished_at"):
        ui.warn(str(row.get("stale_reason") or "승인한 뒤 변경 범위가 달라졌어요"))
        ui.done()
        return
    ui.step(str(row.get("summary") or "요약이 없어요"))
    findings = list(row.get("findings") or [])
    if findings:
        ui.phase(f"제안 — {len(findings)}건")
        for finding in findings:
            severity = _SEVERITY.get(str(finding.get("severity")), str(finding.get("severity") or ""))
            ui.warn(f"[{finding.get('id')}] {severity} · {finding.get('path')}:{finding.get('line')}")
            ui.step(f"    {finding.get('title')}")
            ui.step(ui.dim(f"    {finding.get('body')}"))
            ui.step(ui.dim(f"    근거: {finding.get('evidence')}"))
            if finding.get("suggestion"):
                ui.step(ui.dim(f"    제안: {finding.get('suggestion')}"))
        ui.step(ui.dim(f"피드백: asgard review decide {row['id']} <제안 표식> <accept|dismiss|resolve>"))
    else:
        ui.ok("높은 확신으로 남길 제안은 없어요 — 검토하지 못한 범위는 아래에 따로 적어요")
    gaps = list(row.get("gaps") or [])
    if gaps:
        ui.phase(f"확인하지 못한 것 — {len(gaps)}건")
        for gap in gaps[:10]:
            if isinstance(gap, dict):
                ui.step(f"{gap.get('path')}: {gap.get('why')}")
            else:
                ui.step(str(gap))
    if row.get("status") == "stale":
        ui.warn(str(row.get("stale_reason") or "검토한 뒤 변경이 달라져 현재 제안으로 쓰지 않아요"))
    ui.done()


def run_review(
    *,
    base: str = "HEAD",
    paths: tuple[str, ...] = (),
    focus: str = "",
    approve: str = "",
    yes: bool = False,
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    """승인 없는 호출은 모델 직전에서 멈춘다. 승인 ID와 ``--yes``가 실행 표식이다."""

    _surface(json_out, quiet)
    if yes and not approve:
        raise errors.InvalidInput(
            "새 Review 요청은 --yes만으로 바로 실행할 수 없어요",
            remedy="먼저 `asgard review --json`으로 범위를 고정하고, 오딘의 승인을 받은 뒤 안내된 --approve 명령을 실행해 주세요",
            detail={"required": ["--approve", "--yes"]},
        )
    root = _project_root(os.getcwd())
    if approve:
        row = review_agent.get(root, approve)
        if row is None:
            raise errors.NotFound(
                f"Review 요청 {approve!r}을 찾지 못했어요",
                remedy="`asgard review list`로 대기 요청을 확인해 주세요",
                detail={"review_id": approve},
            )
    else:
        scope = review_agent.inspect_scope(root, base, paths)
        row = review_agent.stage(root, scope, focus)

    if not json_out:
        _preview(row)
    approved = yes
    if not approved and _interactive(json_out):
        approved = _ask()
        if not approved:
            canceled = review_agent.cancel(root, str(row["id"]))
            ui.step("이번에는 부르지 않았어요")
            ui.done()
            return 0 if canceled else 1
    if not approved:
        return _needs_confirmation(row, json_out)

    if json_out:
        result = review_agent.execute(root, str(row["id"]))
        _emit(result)
    else:
        with ui.spin("asgard-review가 승인한 변경을 읽고 있어요…"):
            result = review_agent.execute(root, str(row["id"]))
        _render_result(result)
    return 0


def run_list(*, json_out: bool = False, quiet: bool = False, limit: int = 50) -> int:
    _surface(json_out, quiet)
    root = _project_root(os.getcwd())
    state = review_agent.panel_state(root, limit=limit)
    if json_out:
        _emit(state)
        return 0
    ui.head("review · 기록")
    rows = state["reviews"]
    if not rows:
        ui.ok("아직 Review를 부른 기록이 없어요")
        ui.done()
        return 0
    for row in rows:
        scope = row.get("scope") or {}
        label = _STATUS.get(str(row.get("status")), str(row.get("status") or "?"))
        ui.step(
            f"{row.get('id')} · {label} · {len(scope.get('paths') or [])}파일 · 제안 {len(row.get('findings') or [])}건"
        )
    ui.done()
    return 0


def run_show(review_id: str, *, json_out: bool = False, quiet: bool = False) -> int:
    _surface(json_out, quiet)
    root = _project_root(os.getcwd())
    row = review_agent.get(root, review_id)
    if row is None:
        raise errors.NotFound(
            f"Review {review_id!r}을 찾지 못했어요",
            remedy="`asgard review list`로 기록을 확인해 주세요",
        )
    if json_out:
        _emit(row)
    elif row.get("status") == "awaiting_confirmation":
        _preview(row)
    else:
        _render_result(row)
    return 0


def run_decide(
    review_id: str,
    finding_id: str,
    decision: str,
    *,
    note: str = "",
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    _surface(json_out, quiet)
    root = _project_root(os.getcwd())
    row = review_agent.decide(root, review_id, finding_id, decision, note)
    finding = next(item for item in row["findings"] if item.get("id") == finding_id)
    if json_out:
        _emit({"review_id": review_id, "finding": finding, "review_status": row["status"]})
    else:
        ui.ok(f"{review_id}/{finding_id} → {finding['status']}")
        if note:
            ui.step(ui.dim(f"메모: {note}"))
    return 0


def run_cancel(review_id: str, *, json_out: bool = False, quiet: bool = False) -> int:
    _surface(json_out, quiet)
    root = _project_root(os.getcwd())
    row = review_agent.cancel(root, review_id)
    if json_out:
        _emit(row)
    else:
        ui.ok(f"{review_id} — Review 에이전트를 부르지 않았어요")
    return 0
