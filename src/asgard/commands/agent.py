"""asgard agent — 에인헤랴르의 사람 표면.

이 명령이 답해야 하는 질문은 넷이다:
  · 지금 나는 누구인가        (where)
  · 어떤 에이전트가 있는가     (list · show)
  · 새 에이전트를 어떻게 세우나 (create)
  · 이 프로젝트에서 누가 일하나 (bind · unbind)

만드는 것(루트)과 쓰는 것(프로젝트)을 같은 명령 아래 두되 문장으로 갈라 놓는다 — 사용자가
"만들었는데 왜 안 도나"에서 헤매는 자리가 정확히 그 경계이기 때문이다. `where` 는 그래서
결과만 말하지 않고 **어느 선언이 이겼는지**를 같이 말한다.
"""

from __future__ import annotations

import json
import os
import sys

from .. import profiles, swarm, ui
from .health import _project_root


def _fmt_row(row: dict, id_width: int) -> str:
    mark = "●" if row["active"] else " "
    name = row["id"].ljust(id_width)
    kind = f"< {row['based_on']}" if row["based_on"] else ("내장" if row["id"] == profiles.DEFAULT else "")
    pages = f"{row['memory_pages']}p" if row["memory_pages"] else "—"
    desc = ui.oneline(row["description"] or "", 52)
    return f"  {mark} {name}  {pages.rjust(5)}  {kind.ljust(14)}  {ui.dim(desc)}"


def run_agent_list(*, json_out: bool = False, quiet: bool = False) -> int:
    ui.set_quiet(json_out or quiet)
    rows = profiles.listing()
    roster = profiles.builtin_roster()
    made = {r["id"] for r in rows}
    available = {k: v for k, v in roster.items() if k not in made}

    if json_out:
        print(
            json.dumps(
                {"agents": rows, "builtin_available": available, "active": profiles.active(), "root": profiles.root()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    ui.head(f"agent · 에인헤랴르 — {len(rows)}")
    width = max((len(r["id"]) for r in rows), default=7)
    for row in rows:
        print(_fmt_row(row, width))
    if available:
        ui.step("")
        ui.step(f"내장 에이전트 — 아직 안 세움 ({len(available)}): " + ui.dim(" · ".join(sorted(available))))
        ui.step(ui.dim("    `asgard agent use <이름>` 이면 그 자리에서 세워진다 (자기 1차 기억이 열린다)"))
    warning = profiles.fallback_warning()
    if warning:
        ui.warn(warning)
    ui.done()
    return 0


def run_agent_show(name: str, *, json_out: bool = False, quiet: bool = False) -> int:
    ui.set_quiet(json_out or quiet)
    canon = profiles.normalize(name)
    if not profiles.exists(canon):
        roster = profiles.builtin_roster()
        if canon in roster:
            payload = {"id": canon, "builtin": True, **roster[canon], "created": False}
            if json_out:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0
            ui.head(f"agent · {canon} (내장 — 아직 안 세움)")
            ui.step(str(roster[canon]["description"]))
            ui.step(ui.dim(f"    `asgard agent use {canon}` 로 세운다"))
            ui.done()
            return 0
        print(json.dumps({"error": f"에이전트 {canon!r} 없음"}, ensure_ascii=False))
        return 1

    row = next((r for r in profiles.listing() if r["id"] == canon), None) or {}
    body = profiles._meaningful(profiles.identity(canon))
    payload = {
        **row,
        "identity_chars": len(body),
        "identity_path": os.path.join(profiles.profile_dir(canon), profiles.IDENTITY),
    }
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    ui.head(f"agent · {row.get('name') or canon}")
    if row.get("description"):
        ui.step(str(row["description"]))
    ui.step(ui.dim(f"    홈       {row.get('path')}"))
    ui.step(ui.dim(f"    1차 기억  {row.get('memory_pages', 0)} 페이지 (이 에이전트 전용)"))
    if row.get("based_on"):
        ui.step(ui.dim(f"    바탕     내장 {row['based_on']}"))
    if row.get("capabilities"):
        ui.step(ui.dim("    할 수 있는 일  " + " · ".join(str(c) for c in row["capabilities"])))
    if body:
        ui.ok(f"정체성 {len(body)}자 — {payload['identity_path']}")
    else:
        ui.warn(f"정체성 비어 있음 (주석뿐) — {payload['identity_path']} 에 쓰면 세션에 실린다")
    ui.done()
    return 0


def run_agent_create(
    name: str,
    *,
    based_on: str | None = None,
    description: str | None = None,
    can: list[str] | None = None,
    clone_from: str | None = None,
    display: str | None = None,
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    ui.set_quiet(json_out or quiet)
    try:
        path = profiles.create(
            name,
            based_on=based_on,
            description=description,
            capabilities=list(can or []),
            clone_from=clone_from,
            display=display,
        )
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    canon = profiles.normalize(name)
    if json_out:
        print(json.dumps({"created": canon, "path": path, **profiles.manifest(canon)}, ensure_ascii=False, indent=2))
        return 0

    ui.head(f"agent · {canon} 세움")
    ui.ok(f"홈 {path}")
    ui.step(ui.dim(f"    1차 기억  {os.path.join(path, 'memory')} — 비어 있음, 이 에이전트만 읽고 쓴다"))
    ui.step(ui.dim(f"    정체성    {os.path.join(path, profiles.IDENTITY)}"))
    if not description and not based_on:
        ui.warn(
            "설명이 없다 — 스웜이 일을 어디로 보낼지 고를 때 읽는 유일한 문장이다. `asgard agent describe` 로 채워라"
        )
    ui.step("")
    ui.step(f"이 에이전트로 일하려면:  {ui.bold(f'asgard agent use {canon}')}")
    ui.step(ui.dim(f"    또는 이 프로젝트에서만:  asgard agent bind {canon}"))
    ui.done()
    return 0


def run_agent_use(name: str, *, json_out: bool = False, quiet: bool = False) -> int:
    ui.set_quiet(json_out or quiet)
    try:
        path = profiles.ensure(name)
        canon = profiles.set_active(name)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if json_out:
        print(json.dumps({"active": canon, "path": path}, ensure_ascii=False, indent=2))
        return 0
    ui.head(f"agent · {canon}")
    ui.ok(f"이제 이 기계의 기본 에이전트다 — {path}")
    ui.step(ui.dim(f"    1차 기억  {os.path.join(path, 'memory')}"))
    ui.step(ui.dim("    되돌리려면  asgard agent use default"))
    ui.done()
    return 0


def run_agent_delete(name: str, *, yes: bool = False, json_out: bool = False, quiet: bool = False) -> int:
    ui.set_quiet(json_out or quiet)
    canon = profiles.normalize(name)
    if not profiles.exists(canon) or canon == profiles.DEFAULT:
        print(json.dumps({"error": f"지울 수 없는 이름: {canon!r}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    row = next((r for r in profiles.listing() if r["id"] == canon), {})
    if not yes:
        ui.head(f"agent · {canon} 삭제")
        ui.warn(f"1차 기억 {row.get('memory_pages', 0)} 페이지가 함께 사라진다 — 되돌릴 수 없다")
        ui.step(ui.dim(f"    {row.get('path')}"))
        ui.step(f"확인하려면: {ui.bold(f'asgard agent delete {canon} --yes')}")
        return 1
    try:
        path = profiles.delete(canon)
    except (ValueError, FileNotFoundError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if json_out:
        print(json.dumps({"deleted": canon, "path": path}, ensure_ascii=False))
        return 0
    ui.head(f"agent · {canon} 삭제")
    ui.ok(f"제거됨 — {path}")
    ui.done()
    return 0


def run_agent_describe(
    name: str,
    description: str | None = None,
    *,
    can: list[str] | None = None,
    display: str | None = None,
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    """설명·능력 갱신 — 스웜 라우팅이 읽는 문장을 채우는 자리."""
    ui.set_quiet(json_out or quiet)
    canon = profiles.normalize(name)
    if not profiles.exists(canon):
        print(json.dumps({"error": f"에이전트 {canon!r} 없음"}, ensure_ascii=False), file=sys.stderr)
        return 2
    profiles.write_manifest(
        canon,
        description=description,
        capabilities=list(can) if can else None,
        name=display,
    )
    m = profiles.manifest(canon)
    if json_out:
        print(json.dumps(m, ensure_ascii=False, indent=2))
        return 0
    ui.head(f"agent · {canon}")
    ui.ok(m.get("description") or "(설명 없음)")
    if m.get("capabilities"):
        ui.step(ui.dim("    할 수 있는 일  " + " · ".join(str(c) for c in m["capabilities"])))
    ui.done()
    return 0


# ── 프로젝트 배치 (스웜) ──────────────────────────────────────────────────────────


def run_agent_bind(
    name: str,
    *,
    mode: str | None = None,
    role: str | None = None,
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    ui.set_quiet(json_out or quiet)
    root = _project_root(os.getcwd())
    try:
        out = swarm.bind(root, name, mode=mode, role=role)
    except (ValueError, FileNotFoundError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if json_out:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    where = f"role {role}" if role else (f"mode {mode}" if mode else "이 프로젝트의 대표")
    ui.head("agent · bind")
    ui.ok(f"{where} → {profiles.normalize(name)}")
    ui.step(ui.dim(f"    {out['path']}"))
    if swarm.is_swarm(root):
        placed = swarm.swarm(root)
        ui.step(
            f"스웜 — 역할 {len(placed)}개가 서로 다른 에이전트로 돈다: "
            + " · ".join(f"{k}={v}" for k, v in placed.items())
        )
        ui.step(ui.dim("    각자 자기 1차 기억을 쓴다 — Verifier 가 Worker 의 일지를 못 본다"))
    ui.done()
    return 0


def run_agent_unbind(
    *, mode: str | None = None, role: str | None = None, json_out: bool = False, quiet: bool = False
) -> int:
    ui.set_quiet(json_out or quiet)
    root = _project_root(os.getcwd())
    out = swarm.unbind(root, mode=mode, role=role)
    if json_out:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    where = f"role {role}" if role else (f"mode {mode}" if mode else "이 프로젝트의 대표")
    ui.head("agent · unbind")
    ui.ok(f"{where} 배치 해제")
    ui.done()
    return 0


def run_agent_where(*, json_out: bool = False, quiet: bool = False) -> int:
    """지금 여기서 누가 일하는가 — 그리고 **왜** 그 에이전트인가."""
    ui.set_quiet(json_out or quiet)
    root = _project_root(os.getcwd())
    d = swarm.describe(root)
    now = profiles.active()
    payload = {**d, "process": now, "home": profiles.home(), "memory": os.path.join(profiles.home(), "memory")}
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    ui.head("agent · where")
    ui.ok(f"이 프로세스 — {now}")
    ui.step(ui.dim(f"    홈       {payload['home']}"))
    ui.step(ui.dim(f"    1차 기억  {payload['memory']}"))
    b = d["binding"]
    ui.step("")
    if b["default"]:
        ui.step(f"프로젝트 대표  {b['default']}")
    for m, agent in sorted(b["modes"].items()):
        ui.step(f"모드 {m.ljust(12)} {agent}")
    for r, agent in sorted(b["roles"].items()):
        ui.step(f"역할 {r.ljust(12)} {agent}")
    if not (b["default"] or b["modes"] or b["roles"]):
        ui.step(ui.dim("이 프로젝트에는 배치 선언이 없다 — 루트의 활성 에이전트가 그대로 일한다"))
        ui.step(ui.dim("    `asgard agent bind <이름>` 으로 이 프로젝트만의 대표를 정할 수 있다"))
    if d["swarm"]:
        ui.step("")
        ui.ok("스웜 — 역할마다 다른 에이전트, 각자 자기 1차 기억")
    for miss in d["missing"]:
        scope = miss["scope"] + (f" {miss['key']}" if miss["key"] else "")
        ui.warn(f"{scope} 에 배치된 {miss['agent']!r} 이 이 기계에 없다 — 그 자리는 기본으로 돈다")
    warning = profiles.fallback_warning()
    if warning:
        ui.warn(warning)
    ui.done()
    return 0
