"""`asgard just` — 실행 표면을 들이고, 갱신하고, 어긋났는지 본다.

**실행 표면은 저장소가 고른다.** 설치도 셋업도 `asgard sync` 도 Justfile 을 만들지 않는다 —
`asgard just init` 이 그 문 하나다. 한번 들이고 나면 그 뒤로는 지도처럼 저절로 따라온다:
`asgard sync` 가 관리 구역을 매니페스트에 맞춰 다시 그리고, `asgard doctor` 가 어긋남을 짚는다.

명령을 도는 것은 `just` 자신의 일이다. 이 자리가 하는 것은 넷뿐이다: 러너를 깔고, 매니페스트에서
레시피를 뽑아 관리 구역에 쓰고, 그 구역이 낡았는지 판정하고, 그 둘을 한 번에 하는 문을 연다."""

from __future__ import annotations

import json
import os

from .. import justfile, ui
from .health import _project_root


def run_just_sync(*, dry_run: bool = False, json_out: bool = False, quiet: bool = False) -> int:
    root = _project_root(os.getcwd())
    ui.set_quiet(quiet or json_out)
    try:
        result = justfile.sync(root, dry_run=dry_run)
    except OSError as exc:
        if json_out:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    relative = os.path.relpath(result.path, root)
    if json_out:
        print(
            json.dumps(
                {
                    "path": relative,
                    "created": result.created,
                    "changed": result.changed,
                    "dry_run": dry_run,
                    "recipes": list(result.recipes),
                    "skipped": list(result.skipped),
                    "appended": result.appended,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    verb = "would write" if dry_run else ("wrote" if result.created else "updated")
    if result.changed:
        ui.done(f"{verb} {relative} — {', '.join(result.recipes) or 'no managed recipe'}")
    else:
        ui.done(f"{relative} is current — {', '.join(result.recipes) or 'no managed recipe'}")
    if result.appended:
        ui.step("the managed region was appended at the end; the rest of the file was left alone")
    for name in result.skipped:
        ui.step(f"{name}: you already define it outside the managed region — yours is kept")
    if not justfile.just_version():
        ui.step("just is not on PATH — `asgard just install` puts it there")
    return 0


def run_just_check(*, json_out: bool = False, quiet: bool = False) -> int:
    root = _project_root(os.getcwd())
    ui.set_quiet(quiet or json_out)
    present = justfile.find_justfile(root) is not None
    issues = justfile.check(root)
    if json_out:
        print(json.dumps({"ok": not issues, "present": present, "issues": issues}, ensure_ascii=False, indent=2))
    elif not present:
        # 없는 것은 어긋난 것이 아니다 — 안 들인 저장소에 경고를 내면 도구가 고른 셈이 된다.
        ui.done("this repository has no run surface — `asgard just init` sets one up")
    elif issues:
        ui.warn("the run surface has drifted")
        for issue in issues:
            ui.step(issue)
    else:
        ui.done("the run surface is current")
    return 0 if not issues else 1


def run_just_init(*, json_out: bool = False, quiet: bool = False) -> int:
    """실행 표면을 이 저장소에 들인다 — 러너를 깔고 Justfile 을 쓴다. 사용자가 부르는 문 하나.

    러너 설치가 실패해도 파일은 쓴다. 둘은 다른 실패다: 네트워크가 없어 `just` 를 못 깔았다고
    레시피를 적어 둘 자리까지 없앨 이유가 없고, 다음에 `asgard just install` 한 번이면 선다."""
    root = _project_root(os.getcwd())
    ui.set_quiet(quiet or json_out)
    state, detail = justfile.ensure_just()
    try:
        result = justfile.sync(root)
    except OSError as exc:
        if json_out:
            print(json.dumps({"error": str(exc), "runner": state}, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    relative = os.path.relpath(result.path, root)
    if json_out:
        print(
            json.dumps(
                {
                    "runner": state,
                    "runner_detail": detail,
                    "path": relative,
                    "created": result.created,
                    "changed": result.changed,
                    "recipes": list(result.recipes),
                    "skipped": list(result.skipped),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if state != "unavailable" else 2
    if state == "installed":
        ui.ok(f"installed {detail}")
    elif state == "present":
        ui.step(f"{detail} is already on PATH")
    else:
        ui.warn(f"the runner is not installed: {detail}")
    ui.done(
        f"{'wrote' if result.created else 'updated'} {relative} — {', '.join(result.recipes) or 'no managed recipe'}"
    )
    ui.step("`just --list` shows them; recipes you add outside the asgard markers are never rewritten")
    for name in result.skipped:
        ui.step(f"{name}: you already define it outside the managed region — yours is kept")
    return 0 if state != "unavailable" else 2


def run_just_install(*, force: bool = False, json_out: bool = False, quiet: bool = False) -> int:
    ui.set_quiet(quiet or json_out)
    state, detail = justfile.ensure_just(force=force)
    if json_out:
        print(json.dumps({"state": state, "detail": detail}, ensure_ascii=False))
    elif state == "present":
        ui.done(f"{detail} is already on PATH")
    elif state == "installed":
        ui.done(f"installed {detail}")
    else:
        ui.warn(detail)
    return 0 if state != "unavailable" else 2
