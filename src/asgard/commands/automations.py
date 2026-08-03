"""`asgard automations` — 운영체제 스케줄러가 깨우는 프로젝트 자동화 표면.

기본 `due`는 읽기만 한다. 실제 실행에는 `--run`이 반드시 있어야 하며, 그때도 새 실행기를
만들지 않고 `commands.start.run_prompt(..., json_out=True)`에 그대로 넘긴다. 따라서 자동화도
수동 `asgard run`과 같은 Trinity 프리플라이트·헤드리스 계약을 지난다.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from datetime import datetime
from typing import Any

from .. import automations, errors, ui
from .health import _project_root


def _surface(json_out: bool) -> str:
    errors.set_json_surface(json_out)
    ui.set_quiet(json_out)
    return _project_root(os.getcwd())


def _now() -> datetime:
    return datetime.now().astimezone()


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _missing(name: str) -> errors.NotFound:
    return errors.NotFound(
        f"그런 자동화가 없어요: {name}",
        remedy="asgard automations list로 등록된 이름을 보세요",
        detail={"automation": name},
    )


def run_list(json_out: bool = False) -> int:
    rows = automations.list_automations(_surface(json_out))
    if json_out:
        _emit({"automations": rows, "count": len(rows)})
        return 0
    if not rows:
        ui.step("자동화가 없어요 — `asgard automations add`로 먼저 추가해 주세요.")
        return 0
    for row in rows:
        mark = "●" if row["enabled"] else "○"
        outcome = (row.get("last_outcome") or {}).get("status") or "아직 안 돌았어요"
        ui.step(f"{mark} {row['name']}  {row['schedule']}  {ui.dim(outcome)}")
        ui.step(ui.dim(f"    {ui.oneline(row['prompt'], 80)}"))
    return 0


def run_add(name: str, prompt: str, schedule: str, json_out: bool = False) -> int:
    root = _surface(json_out)
    try:
        entry = automations.add(root, name, prompt, schedule, _now())
    except ValueError as exc:
        raise errors.InvalidInput(
            str(exc),
            remedy="schedule은 hourly/daily/weekdays/weekly 또는 `0 9 * * 1-5`처럼 적어 주세요",
        ) from exc
    if json_out:
        _emit(entry)
    else:
        ui.ok(f"자동화를 추가했어요 — {entry['name']} ({entry['schedule']})")
    return 0


def run_remove(name: str, json_out: bool = False) -> int:
    entry = automations.remove(_surface(json_out), name)
    if entry is None:
        raise _missing(name)
    if json_out:
        _emit({"removed": entry})
    else:
        ui.ok(f"자동화를 지웠어요 — {entry['name']}")
    return 0


def run_enable(name: str, enabled: bool, json_out: bool = False) -> int:
    entry = automations.set_enabled(_surface(json_out), name, enabled)
    if entry is None:
        raise _missing(name)
    if json_out:
        _emit(entry)
    else:
        ui.ok(f"자동화를 {'켰어요' if enabled else '껐어요'} — {entry['name']}")
    return 0


def run_due(execute: bool = False, json_out: bool = False) -> int:
    root = _surface(json_out)
    now = _now()
    rows = automations.due_automations(automations.list_automations(root), now)
    results = automations.run_due(root, now, lambda prompt: _run_prompt_once(root, prompt), _now) if execute else []
    if json_out:
        _emit({"now": now.isoformat(), "execute": execute, "due": rows, "results": results})
        return 0 if all(row["status"] == "succeeded" for row in results) else 1
    if not rows:
        ui.step("지금 due인 자동화가 없어요.")
        return 0
    if not execute:
        for row in rows:
            ui.step(f"○ {row['name']}  {row['schedule']}")
        ui.step(ui.dim("실행하려면 `asgard automations due --run`을 쓰세요."))
        return 0
    for row in results:
        mark = "●" if row["status"] == "succeeded" else "✘"
        ui.step(f"{mark} {row['name']}  {row['status']} (exit {row['exit_code']})")
    return 0 if all(row["status"] == "succeeded" for row in results) else 1


def _run_prompt_once(root: str, prompt: str) -> int:
    """프로젝트 루트에서 기존 headless 실행을 돌리고 stdout 요약만 거둔다."""
    from .start import run_prompt

    summary = io.StringIO()
    with contextlib.chdir(root), contextlib.redirect_stdout(summary):
        code = run_prompt(prompt, json_out=True)
    # `run_prompt --json` 계약도 함께 확인한다. 깨지면 성공으로 기록하지 않는다.
    json.loads(summary.getvalue())
    return code


def run_history(name: str = "", limit: int = 20, json_out: bool = False) -> int:
    rows = automations.history(_surface(json_out), name, limit)
    if json_out:
        _emit({"history": rows, "count": len(rows)})
        return 0
    if not rows:
        ui.step("자동화 실행 기록이 없어요.")
        return 0
    for row in rows:
        mark = {"succeeded": "●", "running": "◐", "interrupted": "⊘"}.get(row["status"], "✘")
        ui.step(f"{mark} {row['name']}  {row['status']}  {ui.dim(row['started_at'])}")
    return 0
