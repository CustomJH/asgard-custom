"""CLI surfaces for the Asgard-owned skill and plugin catalog."""

import json
import os
import sys

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .. import errors, theme, ui
from ..skill_registry import (
    assign_skill,
    install_plugin,
    plugins,
    resolve_skills,
    run_skill,
    set_skill_enabled,
    show_skill,
    show_skill_resource,
    skills,
)


def _emit(payload: dict) -> None:
    """`--json` 산출물 — 사람 표면(rich 패널·본문)이 차지하던 stdout을 그대로 이어받는다."""
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _console() -> Console:
    return Console(
        file=sys.stdout,
        width=ui.term_cols(),
        color_system="auto" if ui._COLOR else None,
        force_terminal=ui._COLOR,
        highlight=False,
    )


def _title(label: str, count: int) -> Text:
    return Text.assemble((label, theme.SUBTEXT), (f" · {count}", f"bold {theme.TEXT}"))


def _catalog(label: str, rows: list[tuple[Text, Text, Text]]) -> None:
    console = _console()
    table = Table.grid(expand=True, padding=(0, 1))
    if console.width < 96:
        table.add_column(overflow="fold")
        for index, row in enumerate(rows):
            block = Text("\n").join(row)
            table.add_row(block)
            if index + 1 < len(rows):
                table.add_row("")
    else:
        table.add_column(min_width=20, max_width=30, overflow="fold")
        table.add_column(min_width=20, max_width=36, overflow="fold")
        table.add_column(ratio=1, overflow="fold")
        for row in rows:
            table.add_row(*row)
    console.print(
        Panel(table, title=_title(label, len(rows)), title_align="left", border_style=theme.HAIRLINE, box=box.ROUNDED)
    )


def render_skills(rows: list[dict], label: str = "Skills") -> None:
    rendered = []
    for row in rows:
        meta = Text(f"{row['plugin']} · {row['origin']} · {row['invocation']}", style=theme.SUBTEXT)
        rendered.append(
            (
                Text(str(row["name"]), style=f"bold {theme.ACCENT_CYAN}"),
                meta,
                Text(str(row["description"]), style=theme.TEXT),
            )
        )
    _catalog(label, rendered)


def _skill_count(count: int) -> str:
    return f"{count} skill{'s' if count != 1 else ''}"


def render_plugins(rows: list[dict]) -> None:
    rendered = []
    for row in rows:
        version = str(row["version"])
        detail = _skill_count(len(row["skills"]))
        release = Text(
            f"{version} · {detail}" if version == "bundled" else f"{version} · {row['origin']} · {detail}",
            style=theme.SUBTEXT,
        )
        rendered.append(
            (
                Text(str(row["name"]), style=f"bold {theme.ACCENT_CYAN}"),
                release,
                Text(str(row["description"]), style=theme.TEXT),
            )
        )
    _catalog("Plugins", rendered)


def run_skills_list(json_out: bool = False) -> int:
    rows = skills(os.getcwd())
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        render_skills(rows)
    return 0


def run_skills_show(name: str, body_only: bool = True, resource: str | None = None, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)
    try:
        text = show_skill_resource(os.getcwd(), name, resource) if resource else show_skill(os.getcwd(), name)
    except ValueError as exc:
        raise errors.InvalidInput(str(exc), remedy=f"asgard skills show {name} 명령으로 스킬 본문을 보세요") from exc
    if text is None:
        raise errors.NotFound(
            f"skill not found: {name}", remedy="asgard skills list로 있는 스킬을 보세요", detail={"skill": name}
        )
    if resource is None and body_only and text.startswith("---"):
        text = text.split("---", 2)[2].lstrip()
    if json_out:
        _emit({"skill": name, "resource": resource or "", "frontmatter": not body_only, "text": text})
        return 0
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def run_skills_resolve(agent: str, task: str | None, json_out: bool = False, *, scope_only: bool = False) -> int:
    if agent not in ("worker", "freyja", "thor", "thor-lead", "eitri", "mimir", "verifier", "loki"):
        print("invalid agent", file=sys.stderr)
        return 2
    task = task if task is not None else sys.stdin.read()
    if not task.strip():
        print("task is required", file=sys.stderr)
        return 2
    # `--scope-only` 는 프롬프트 주입면이 부르는 얇은 출력이다. 스킬 본문은 합쳐서 16,000자까지
    # 나오는데, 그것을 매 요청에 싣는 것은 이 층이 하려는 일이 아니다 — 여기서 필요한 것은 형상과
    # "이 표면은 전문가에게 넘겨라" 한 줄이고, 본문은 그 전문가가 자기 자리에서 읽는다.
    rows = [] if scope_only else resolve_skills(os.getcwd(), task, agent)
    # 범위 형상 — 판정 표면(verifier/loki)에는 붙이지 않는다: 게이트에 advisory 지식 무주입 규율.
    # 외부 호스트(Codex·Cursor)는 이 출력이 유일한 스킬 통로라 네이티브와 같은 사이징을 여기서 준다.
    shape: dict | None = None
    note = ""
    if agent not in ("verifier", "loki"):
        from ..skill_scope import scope_note, work_shape

        shape = work_shape(task)
        note = scope_note(os.getcwd(), task, agent=agent if agent != "thor-lead" else "thor", loader="cli")
    if json_out:
        payload: dict = {"skills": [{"name": name, "body": body} for name, body in rows]}
        if shape:
            payload["shape"] = shape
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if rows:
        print("\n\n".join(f"# Skill: {name}\n\n{body.rstrip()}" for name, body in rows))
    if note:
        print(note.strip())
    return 0


def run_plugins_list(json_out: bool = False) -> int:
    rows = plugins()
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        render_plugins(rows)
    return 0


def run_plugins_install(source: str, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)
    try:
        manifest = install_plugin(source)
    except ValueError as exc:
        raise errors.InvalidInput(
            str(exc), remedy="플러그인 디렉터리 경로를 확인하세요", detail={"source": source}
        ) from exc
    if json_out:
        _emit(
            {
                "plugin": manifest["name"],
                "version": manifest["version"],
                "skills": list(manifest["skills"]),
                "installed": True,
            }
        )
        return 0
    print(f"installed {manifest['name']} {manifest['version']} ({len(manifest['skills'])} skills)")
    return 0


def run_skills_run(name: str, args: list[str]) -> int:
    try:
        return run_skill(os.getcwd(), name, args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def run_skills_assign(name: str, agent: str, *, assigned: bool, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)
    try:
        assign_skill(os.getcwd(), name, agent, assigned=assigned)
    except ValueError as exc:
        raise errors.InvalidInput(
            str(exc),
            remedy="asgard skills list로 스킬 이름을, --agent로 역할을 확인하세요",
            detail={"skill": name, "role": agent},
        ) from exc
    if json_out:
        _emit({"skill": name, "role": agent, "assigned": assigned})
        return 0
    print(f"{'assigned' if assigned else 'unassigned'} {name} {'to' if assigned else 'from'} {agent}")
    return 0


def run_skills_enable(name: str, *, enabled: bool, json_out: bool = False) -> int:
    errors.set_json_surface(json_out)
    try:
        set_skill_enabled(os.getcwd(), name, enabled=enabled)
    except ValueError as exc:
        raise errors.InvalidInput(
            str(exc), remedy="asgard skills list로 있는 스킬을 보세요", detail={"skill": name}
        ) from exc
    if json_out:
        _emit({"skill": name, "enabled": enabled})
        return 0
    print(f"{'enabled' if enabled else 'disabled'} {name}")
    return 0
