"""asgard agent — 에인헤랴르의 사람 표면.

이 명령이 답해야 하는 질문은 넷이다:
  · 지금 나는 누구인가        (where)
  · 어떤 에이전트가 있는가     (list · show)
  · 새 에이전트를 어떻게 세우나 (create)
  · 이 프로젝트에서 누가 일하나 (bind · unbind)

만드는 것(루트)과 쓰는 것(프로젝트)을 같은 명령 아래 두되 문장으로 갈라 놓는다 — 사용자가
"만들었는데 왜 안 도나"에서 헤매는 자리가 정확히 그 경계이기 때문이다. `where`는 그래서
결과만 말하지 않고 **어느 선언이 이겼는지**를 같이 말한다.
"""

from __future__ import annotations

import json
import os
import time

from .. import errors, picker, profiles, swarm, ui
from .health import _project_root


def _surface(json_out: bool, quiet: bool) -> None:
    """이 실행의 표면을 두 곳에 알린다 — 화면 장식(`quiet`)과 오류의 얼굴(`json`).

    둘은 같은 플래그가 아니다. `--quiet`은 장식을 빼라는 말이고, `--json`은 stdout이 기계의
    것이라는 말이다. 여태 후자를 아무도 안 알려 줘서, 실패는 플래그와 무관하게 사람 말로
    나갔다."""
    ui.set_quiet(json_out or quiet)
    errors.set_json_surface(json_out)


def _boundary(exc: Exception, *, remedy: str) -> errors.AsgardError:
    """`profiles`·`swarm`이 던진 것을 경계의 어휘로 옮긴다 — 종류마다 `code`가 갈린다.

    셋 다 종료 코드는 2다(호출자가 고칠 수 있는 잘못). 그래도 코드를 갈라 두는 이유는
    소비자가 분기하기 때문이다: 없는 것(`not_found`)은 만들라고, 이미 있는 것(`conflict`)은
    다른 이름을 쓰라고 안내해야 한다."""
    if isinstance(exc, FileExistsError):
        return errors.Conflict(str(exc), remedy=remedy)
    if isinstance(exc, FileNotFoundError):
        return errors.NotFound(str(exc), remedy=remedy)
    return errors.InvalidInput(str(exc), remedy=remedy)


def _fmt_row(row: dict, id_width: int) -> str:
    mark = "●" if row["active"] else " "
    name = row["id"].ljust(id_width)
    kind = f"< {row['based_on']}" if row["based_on"] else ("내장" if row["id"] == profiles.DEFAULT else "")
    pages = f"{row['memory_pages']}p" if row["memory_pages"] else "—"
    desc = ui.oneline(row["description"] or "", 52)
    return f"  {mark} {name}  {pages.rjust(5)}  {kind.ljust(14)}  {ui.dim(desc)}"


def _inventory() -> tuple[list[dict], dict[str, dict]]:
    rows = profiles.listing()
    made = {row["id"] for row in rows}
    return rows, {name: row for name, row in profiles.builtin_roster().items() if name not in made}


def _render_inventory(rows: list[dict], available: dict[str, dict]) -> None:
    ui.head(f"agent · 에인헤랴르 — {len(rows)}")
    width = max((len(row["id"]) for row in rows), default=7)
    for row in rows:
        print(_fmt_row(row, width))
    if available:
        ui.step("")
        ui.step(f"내장 에이전트 — 아직 안 세웠어요 ({len(available)})")
        width = max(len(name) for name in available)
        for name, row in sorted(available.items()):
            print(f"    {name.ljust(width)}  {ui.dim(ui.oneline(str(row.get('description') or ''), 68))}")
        ui.step(ui.dim("    `asgard agent use <이름>`을 치면 그 자리에서 세워져요 (자기 기억도 같이 열려요)"))


def select_agent(
    name: str | None,
    *,
    title: str,
    retry: str,
    json_out: bool = False,
) -> str:
    """명시 이름을 검증하거나, 세운 에이전트와 내장 에이전트 중 하나를 골라요."""
    if name is not None:
        return _agent(name)

    rows, available = _inventory()
    options = [
        picker.Option(
            row["id"],
            f"세운 에이전트 · {row['id']}",
            detail=" · ".join(
                filter(
                    None,
                    (
                        str(row.get("description") or "설명이 없어요"),
                        f"1차 기억 {row.get('memory_pages', 0)}페이지",
                        "지금 활성" if row.get("active") else "",
                    ),
                )
            ),
        )
        for row in rows
    ]
    options.extend(
        picker.Option(
            builtin,
            f"내장 에이전트 · {builtin}",
            detail=f"{row.get('description') or '설명이 없어요'} · 고르면 바로 세워요",
        )
        for builtin, row in sorted(available.items())
    )
    if json_out or not picker.available():
        if not json_out:
            _render_inventory(rows, available)
        raise errors.InvalidInput(
            "에이전트 선택기는 대화형 터미널에서만 열 수 있어요",
            remedy=retry,
            detail={"agents": rows, "builtin_available": available},
        )
    default = next((index for index, row in enumerate(rows) if row.get("active")), 0)
    selected = picker.pick(title, options, default=default)
    if selected is None:
        raise errors.InvalidInput("에이전트를 고르지 않았어요", remedy=retry)
    if selected in available:
        try:
            profiles.ensure(selected)
        except (ValueError, FileExistsError, FileNotFoundError, OSError) as exc:
            raise _boundary(exc, remedy=retry) from exc
    return _agent(selected)


def run_agent_list(*, json_out: bool = False, quiet: bool = False) -> int:
    _surface(json_out, quiet)
    rows, available = _inventory()

    if json_out:
        print(
            json.dumps(
                {"agents": rows, "builtin_available": available, "active": profiles.active(), "root": profiles.root()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    _render_inventory(rows, available)
    warning = profiles.fallback_warning()
    if warning:
        ui.warn(warning)
    ui.done()
    return 0


def run_agent_show(name: str, *, json_out: bool = False, quiet: bool = False) -> int:
    _surface(json_out, quiet)
    canon = profiles.normalize(name)
    if not profiles.exists(canon):
        roster = profiles.builtin_roster()
        if canon in roster:
            payload = {"id": canon, "builtin": True, **roster[canon], "created": False}
            if json_out:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0
            ui.head(f"agent · {canon} (내장 — 아직 안 세웠어요)")
            ui.step(str(roster[canon]["description"]))
            ui.step(ui.dim(f"    `asgard agent use {canon}`로 세우세요"))
            ui.done()
            return 0
        raise errors.NotFound(
            f"에이전트 {canon!r}를 못 찾았어요",
            remedy="`asgard agent list`로 세워 둔 이름을 확인하세요",
            detail={"agent": canon},
        )

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
        ui.warn(f"정체성이 비어 있어요 (주석뿐이에요) — {payload['identity_path']}에 쓰면 세션에 실려요")
    ui.done()
    return 0


def run_agent_open(name: str | None, *, new: bool = False, json_out: bool = False) -> int:
    _surface(json_out, False)
    canon = select_agent(
        name,
        title="열 에이전트를 골라요",
        retry="`asgard agent open <이름>`으로 이름을 대고 다시 부르세요",
        json_out=json_out,
    )
    if not new:
        from .. import runs

        live = [row for row in runs.find(agent=canon, kind="studio") if row.get("state") == "live"]
        if live:
            row = max(live, key=lambda item: str(item.get("started", "")))
            if json_out:
                print(json.dumps({"window": row, "reused": True}, ensure_ascii=False, indent=2))
                return 0
            ui.head("agent · open")
            ui.ok(f"{canon} 창이 이미 열려 있어요 — {row['url']}")
            ui.done()
            return 0

    from .studio import run_studio

    return run_studio(agent=canon, json_out=json_out)


def run_agent_windows(*, json_out: bool = False) -> int:
    _surface(json_out, False)
    from .. import runs

    rows = runs.listing(prune=False)
    if json_out:
        print(json.dumps({"windows": rows}, ensure_ascii=False, indent=2))
        return 0

    ui.head(f"agent · windows — {len(rows)}")
    if not rows:
        ui.step("열린 창이 없어요")
    for row in rows:
        started = row.get("started")
        opened = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started))
            if isinstance(started, (int, float))
            else started
        )
        ui.step(
            f"{row.get('agent') or 'default'}  {row.get('url') or '—'}  "
            f"pid {row.get('pid') or '—'}  {row.get('state') or 'indeterminate'}  {opened or '—'}"
        )
    if any(row.get("state") == "stale" for row in rows):
        ui.warn("stale 등록이 있어요 — 프로세스 종료를 확인한 뒤 등록부에서 정리하세요")
    if any(row.get("state") == "indeterminate" for row in rows):
        ui.warn("indeterminate 등록은 소유권을 확인할 수 없어 자동으로 지우지 않아요")
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
    _surface(json_out, quiet)
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
        raise _boundary(exc, remedy="`asgard agent list`로 이미 있는 이름을 확인하고 다른 이름을 고르세요") from exc

    canon = profiles.normalize(name)
    if json_out:
        # 명세를 펼쳐 넣으면 그 안의 `created`(생성 시각)가 이 자리의 `created`(만든 에이전트 id)를
        # 덮어써, JSON 계약이 조용히 숫자를 뱉었다 (실측 26-07-29). 명세는 중첩해 충돌을 없앤다.
        print(
            json.dumps(
                {"created": canon, "path": path, "manifest": profiles.manifest(canon)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    ui.head(f"agent · {canon} 세웠어요")
    ui.ok(f"홈 {path}")
    ui.step(ui.dim(f"    기억      {os.path.join(path, 'memory')} — 아직 비었고, 이 에이전트만 읽고 써요"))
    ui.step(ui.dim(f"    정체성    {os.path.join(path, profiles.IDENTITY)}"))
    if not description and not based_on:
        ui.warn(
            "설명이 없어요 — 스웜이 일을 어디로 보낼지 고를 때 읽는 유일한 문장이에요. `asgard agent describe`로 채워 주세요"
        )
    ui.step("")
    ui.step(f"이 에이전트로 일하려면:  {ui.bold(f'asgard agent use {canon}')}")
    ui.step(ui.dim(f"    또는 이 프로젝트에서만:  asgard agent bind {canon}"))
    ui.done()
    return 0


def run_agent_use(name: str, *, json_out: bool = False, quiet: bool = False) -> int:
    _surface(json_out, quiet)
    try:
        path = profiles.ensure(name)
        canon = profiles.set_active(name)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        raise _boundary(exc, remedy="`asgard agent list`로 쓸 수 있는 이름을 확인하세요") from exc
    if json_out:
        print(json.dumps({"active": canon, "path": path}, ensure_ascii=False, indent=2))
        return 0
    ui.head(f"agent · {canon}")
    ui.ok(f"이제 이 기계의 기본 에이전트예요 — {path}")
    ui.step(ui.dim(f"    1차 기억  {os.path.join(path, 'memory')}"))
    ui.step(ui.dim("    되돌리려면  asgard agent use default"))
    ui.done()
    return 0


def run_agent_delete(name: str, *, yes: bool = False, json_out: bool = False, quiet: bool = False) -> int:
    _surface(json_out, quiet)
    canon = profiles.normalize(name)
    if canon == profiles.DEFAULT:
        raise errors.InvalidInput(
            "기본 에이전트는 지울 수 없어요",
            remedy="이 프로젝트의 배치를 걷어내려는 거라면 `asgard agent unbind`를 쓰세요",
            detail={"agent": canon},
        )
    if not profiles.exists(canon):
        raise errors.NotFound(
            f"에이전트 {canon!r}를 못 찾았어요",
            remedy="`asgard agent list`로 세워 둔 이름을 확인하세요",
            detail={"agent": canon},
        )
    row = next((r for r in profiles.listing() if r["id"] == canon), {})
    if not yes:
        # 확인을 요구하는 것도 실패다 — 요청한 일이 안 일어났고, 그 사실이 종료 코드로 나가야
        # 스크립트가 "지웠다"고 오해하지 않는다. 잃을 것(기억 페이지)은 사유 안에 적는다.
        raise errors.Conflict(
            f"에이전트 {canon!r}를 지우면 기억 {row.get('memory_pages', 0)}페이지도 같이 사라져요 — 되돌릴 수 없어요",
            remedy=f"확인하려면: asgard agent delete {canon} --yes",
            detail={"agent": canon, "path": row.get("path"), "memory_pages": row.get("memory_pages", 0)},
        )
    try:
        path = profiles.delete(canon)
    except (ValueError, FileNotFoundError) as exc:
        raise _boundary(exc, remedy="`asgard agent list`로 지금 있는 이름을 확인하세요") from exc
    if json_out:
        print(json.dumps({"deleted": canon, "path": path}, ensure_ascii=False))
        return 0
    ui.head(f"agent · {canon} 삭제")
    ui.ok(f"지웠어요 — {path}")
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
    _surface(json_out, quiet)
    canon = profiles.normalize(name)
    if not profiles.exists(canon):
        raise errors.NotFound(
            f"에이전트 {canon!r}를 못 찾았어요",
            remedy=f"`asgard agent create {canon}`로 먼저 세우세요",
            detail={"agent": canon},
        )
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
    ui.ok(m.get("description") or "(설명이 없어요)")
    if m.get("capabilities"):
        ui.step(ui.dim("    할 수 있는 일  " + " · ".join(str(c) for c in m["capabilities"])))
    ui.done()
    return 0


def _agent(name: str) -> str:
    """이름을 사용자 경계에서 검증하고, 실제로 세운 에이전트만 돌려준다."""
    try:
        canon = profiles.validate(name)
    except ValueError as exc:
        raise _boundary(exc, remedy="`asgard agent list`로 쓸 수 있는 이름을 확인하세요") from exc
    if not profiles.exists(canon):
        raise errors.NotFound(
            f"에이전트 {canon!r}를 못 찾았어요",
            remedy=f"`asgard agent create {canon}`로 먼저 세우세요",
            detail={"agent": canon},
        )
    return canon


def _config_key(text: str) -> tuple[str, str]:
    """`section.key` 한 층만 받는다 — 저장 계약도 바로 그 섹션 단위다."""
    target = str(text or "").strip()
    if target.count(".") != 1:
        raise errors.InvalidInput(
            f"설정 키 {text!r} 형식이 잘못됐어요",
            remedy="`provider.model`처럼 <섹션>.<키>로 쓰세요",
            detail={"key": text},
        )
    section, key = target.split(".", 1)
    if not section or not key or any(ch.isspace() for ch in target):
        raise errors.InvalidInput(
            f"설정 키 {text!r} 형식이 잘못됐어요",
            remedy="`provider.model`처럼 빈칸 없이 <섹션>.<키>로 쓰세요",
            detail={"key": text},
        )
    return section, key


def _config_set(text: str) -> tuple[str, str, object]:
    target, sep, raw = str(text or "").partition("=")
    if not sep:
        raise errors.InvalidInput(
            f"설정 값 {text!r} 형식이 잘못됐어요",
            remedy="`provider.model=<id>`처럼 <섹션>.<키>=<값>으로 쓰세요",
            detail={"setting": text},
        )
    section, key = _config_key(target)
    lower = raw.casefold()
    if lower in ("true", "false"):
        value: object = lower == "true"
    else:
        try:
            value = int(raw)
        except ValueError:
            value = raw
    return section, key, value


def _config_sources(view: dict, own: dict) -> dict:
    """병합 결과의 각 값을 자기 선언과 기계 뿌리 상속으로 가른다."""
    sources: dict = {}
    for section, value in view.items():
        declared = own.get(section)
        if isinstance(value, dict):
            declared_keys = declared if isinstance(declared, dict) else {}
            sources[section] = {key: "profile" if key in declared_keys else "machine" for key in value}
        else:
            sources[section] = "profile" if section in own else "machine"
    return sources


def run_agent_config(
    name: str,
    *,
    set_values: list[str] | None = None,
    unset_values: list[str] | None = None,
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    _surface(json_out, quiet)
    from .. import settings

    canon = _agent(name)
    parsed_sets = [_config_set(item) for item in set_values or []]
    parsed_unsets = [_config_key(item) for item in unset_values or []]
    try:
        own = settings.profile_config(canon)
        changed: dict[str, dict] = {}
        for section, key, value in parsed_sets:
            section_values = changed.setdefault(section, dict(own.get(section) or {}))
            section_values[key] = value
        for section, key in parsed_unsets:
            section_values = changed.setdefault(section, dict(own.get(section) or {}))
            section_values.pop(key, None)
        path = settings.profile_config_path(canon)
        for section, values in changed.items():
            path = settings.save_profile_config(canon, section, values)
        own = settings.profile_config(canon)
        view = settings.profile_config_view(canon)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise _boundary(exc, remedy="`asgard agent list`로 에이전트 이름과 설정 키를 확인하세요") from exc

    sources = _config_sources(view, own)
    payload = {"agent": canon, "path": path, "config": view, "declared": own, "sources": sources}
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    ui.head(f"agent · {canon} config")
    if changed:
        ui.ok(f"설정을 저장했어요 — {path}")
    if not view:
        ui.step("설정이 없어요 — 이 에이전트에도, 기계 기본값에도 아무것도 없어요")
    for section, values in sorted(view.items()):
        if isinstance(values, dict):
            for key, value in sorted(values.items()):
                source = "이 에이전트가 선언" if sources[section][key] == "profile" else "기계 기본값에서 상속"
                ui.step(f"{section}.{key} = {json.dumps(value, ensure_ascii=False)}  {ui.dim(f'({source})')}")
        else:
            source = "이 에이전트가 선언" if sources[section] == "profile" else "기계 기본값에서 상속"
            ui.step(f"{section} = {json.dumps(values, ensure_ascii=False)}  {ui.dim(f'({source})')}")
    ui.done()
    return 0


def run_agent_identity(
    name: str,
    *,
    set_file: str | None = None,
    set_value: str | None = None,
    edit: bool = False,
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    _surface(json_out, quiet)
    canon = _agent(name)
    choices = sum((set_file is not None, set_value is not None, edit))
    if choices > 1:
        raise errors.InvalidInput(
            "정체성을 바꾸는 방법을 하나만 골라야 해요",
            remedy="`--set-file <경로>`, `--set -`, `--edit` 중 하나만 쓰세요",
            detail={"agent": canon},
        )

    path = os.path.join(profiles.profile_dir(canon), profiles.IDENTITY)
    body: str | None = None
    if set_file is not None:
        try:
            with open(os.path.abspath(os.path.expanduser(set_file)), encoding="utf-8") as handle:
                body = handle.read()
        except FileNotFoundError as exc:
            raise errors.NotFound(
                f"정체성 파일 {set_file!r}을 못 찾았어요",
                remedy="실제로 있는 UTF-8 파일 경로를 `--set-file`에 주세요",
                detail={"path": set_file},
            ) from exc
        except (OSError, UnicodeError) as exc:
            raise errors.InvalidInput(
                f"정체성 파일 {set_file!r}을 읽지 못했어요: {exc}",
                remedy="읽을 수 있는 UTF-8 파일을 주세요",
                detail={"path": set_file},
            ) from exc
    elif set_value is not None:
        if set_value != "-":
            raise errors.InvalidInput(
                f"--set 값 {set_value!r}은 지원하지 않아요",
                remedy="표준 입력에서 읽으려면 `--set -`로 쓰세요",
                detail={"value": set_value},
            )
        import sys

        body = sys.stdin.read()
    elif edit:
        import shlex
        import subprocess

        editor = str(os.environ.get("EDITOR") or "").strip()
        if not editor:
            raise errors.InvalidInput(
                "$EDITOR가 없어 편집기를 열 수 없어요",
                remedy="`EDITOR=vim asgard agent identity <이름> --edit`처럼 편집기를 지정하세요",
                detail={"agent": canon},
            )
        try:
            argv = shlex.split(editor)
            if not argv:
                raise ValueError("편집기 명령이 비어 있어요")
            completed = subprocess.run([*argv, path], check=False)
        except (OSError, ValueError) as exc:
            raise errors.InvalidInput(
                f"편집기 {editor!r}를 열지 못했어요: {exc}",
                remedy="실행할 수 있는 프로그램을 $EDITOR에 지정하세요",
                detail={"editor": editor},
            ) from exc
        if completed.returncode:
            raise errors.InvalidInput(
                f"편집기가 종료 코드 {completed.returncode}로 끝났어요",
                remedy="편집기 오류를 고치거나 `--set-file`로 정체성을 교체하세요",
                detail={"editor": editor, "exit_code": completed.returncode},
            )

    if body is not None:
        try:
            path = profiles.write_identity(canon, body)
        except (ValueError, FileNotFoundError) as exc:
            raise _boundary(exc, remedy=f"`asgard agent create {canon}`로 먼저 세우세요") from exc

    current = profiles.identity(canon)
    meaningful = bool(profiles._meaningful(current))
    payload = {"agent": canon, "path": path, "body": current, "meaningful": meaningful}
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    ui.head(f"agent · {canon} identity")
    if body is not None:
        ui.ok(f"정체성을 교체했어요 — {path}")
    elif edit:
        ui.ok(f"정체성을 편집했어요 — {path}")
    if meaningful:
        if body is None and not edit:
            ui.ok(f"AGENT.md — {path}")
        print(current.rstrip())
    else:
        ui.step(f"AGENT.md는 주석뿐이에요 — {path}")
    ui.done()
    return 0


def run_agent_rename(old: str, new: str, *, json_out: bool = False, quiet: bool = False) -> int:
    _surface(json_out, quiet)
    try:
        path = profiles.rename(old, new)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        raise _boundary(exc, remedy="`asgard agent list`로 지금 이름을 확인하고 비어 있는 새 이름을 고르세요") from exc
    before, after = profiles.normalize(old), profiles.normalize(new)
    if json_out:
        print(json.dumps({"renamed": {"from": before, "to": after}, "path": path}, ensure_ascii=False, indent=2))
        return 0
    ui.head("agent · rename")
    ui.ok(f"{before} → {after}")
    ui.step(ui.dim(f"    {path}"))
    ui.done()
    return 0


def run_agent_export(
    name: str,
    *,
    out_path: str | None = None,
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    _surface(json_out, quiet)
    canon = profiles.normalize(name)
    target = os.path.abspath(os.path.expanduser(out_path or os.path.join(os.getcwd(), f"{canon}.tar.gz")))
    if os.path.exists(target):
        raise errors.Conflict(
            f"내보낼 파일이 이미 있어요 — {target}",
            remedy="기존 파일을 보존하려면 `-o`로 다른 경로를 고르세요",
            detail={"agent": canon, "path": target},
        )
    try:
        path = profiles.export_archive(canon, target)
    except (ValueError, FileExistsError, FileNotFoundError, OSError) as exc:
        raise _boundary(exc, remedy="에이전트 이름과 쓸 수 있는 출력 경로를 확인하세요") from exc
    if json_out:
        print(json.dumps({"exported": canon, "path": path}, ensure_ascii=False, indent=2))
        return 0
    ui.head("agent · export")
    ui.ok(f"내보냈어요 — {canon} → {path}")
    ui.done()
    return 0


def run_agent_import(
    archive_path: str,
    *,
    as_name: str | None = None,
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    _surface(json_out, quiet)
    archive = os.path.abspath(os.path.expanduser(archive_path))
    if not os.path.isfile(archive):
        raise errors.NotFound(
            f"가져올 보관 파일 {archive!r}을 못 찾았어요",
            remedy="실제로 있는 `.tar.gz` 파일 경로를 주세요",
            detail={"path": archive},
        )
    if as_name is not None:
        try:
            target = profiles.validate(as_name)
        except ValueError as exc:
            raise _boundary(exc, remedy="`[a-z0-9][a-z0-9_-]*` 형식의 새 이름을 `--as`에 주세요") from exc
        if profiles.exists(target):
            raise errors.Conflict(
                f"에이전트 {target!r}가 이미 있어 덮어쓰지 않았어요",
                remedy="기존 에이전트를 보존하려면 `--as`로 비어 있는 이름을 고르세요",
                detail={"agent": target, "path": profiles.profile_dir(target)},
            )
    try:
        path = profiles.import_archive(archive, name=as_name)
    except (ValueError, FileExistsError, FileNotFoundError, OSError) as exc:
        raise _boundary(exc, remedy="보관 파일을 확인하고, 이름이 겹치면 `--as`로 새 이름을 고르세요") from exc
    canon = profiles.normalize(as_name or os.path.basename(os.path.normpath(path)))
    if json_out:
        print(json.dumps({"imported": canon, "path": path}, ensure_ascii=False, indent=2))
        return 0
    ui.head("agent · import")
    ui.ok(f"가져왔어요 — {canon} → {path}")
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
    _surface(json_out, quiet)
    root = _project_root(os.getcwd())
    try:
        out = swarm.bind(root, name, mode=mode, role=role)
    except (ValueError, FileNotFoundError) as exc:
        # 없는 이름과 잘못 쓴 자리는 다음 손이 다르다: 하나는 만들어야 하고, 하나는 고쳐 써야 한다.
        fix = (
            f"`asgard agent create {profiles.normalize(name)}`로 먼저 세우세요"
            if isinstance(exc, FileNotFoundError)
            else "`asgard agent where`로 지금 배치를 보고 --mode/--role 중 하나만 주세요"
        )
        raise _boundary(exc, remedy=fix) from exc
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
            f"스웜 — 역할 {len(placed)}개가 서로 다른 에이전트로 돌아요: "
            + " · ".join(f"{k}={v}" for k, v in placed.items())
        )
        ui.step(ui.dim("    각자 자기 기억을 써요 — Verifier는 Worker의 일지를 못 봐요"))
    ui.done()
    return 0


def run_agent_unbind(
    *, mode: str | None = None, role: str | None = None, json_out: bool = False, quiet: bool = False
) -> int:
    _surface(json_out, quiet)
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
    _surface(json_out, quiet)
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
        ui.step(ui.dim("이 프로젝트엔 따로 배치한 게 없어요 — 기본 에이전트가 그대로 일해요"))
        ui.step(ui.dim("    `asgard agent bind <이름>`으로 이 프로젝트만의 대표를 정하세요"))
    if d["swarm"]:
        ui.step("")
        ui.ok("스웜 — 역할마다 다른 에이전트가 각자 자기 기억으로 일해요")
    for miss in d["missing"]:
        scope = miss["scope"] + (f" {miss['key']}" if miss["key"] else "")
        ui.warn(f"{scope}에 배치한 {miss['agent']!r}이 이 기계엔 없어요 — 그 자리는 기본값으로 돌아가요")
    warning = profiles.fallback_warning()
    if warning:
        ui.warn(warning)
    ui.done()
    return 0
