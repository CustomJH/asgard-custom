"""CLI surfaces for the Asgard-owned skill and plugin catalog."""

import json
import os
import sys

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .. import theme, ui
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


def run_skills_show(name: str, body_only: bool = True, resource: str | None = None) -> int:
    try:
        text = show_skill_resource(os.getcwd(), name, resource) if resource else show_skill(os.getcwd(), name)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if text is None:
        print(f"skill not found: {name}", file=sys.stderr)
        return 2
    if resource is None and body_only and text.startswith("---"):
        text = text.split("---", 2)[2].lstrip()
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def run_skills_resolve(agent: str, task: str | None, json_out: bool = False) -> int:
    if agent not in ("worker", "freyja", "thor", "thor-lead", "eitri", "mimir", "verifier", "loki"):
        print("invalid agent", file=sys.stderr)
        return 2
    task = task if task is not None else sys.stdin.read()
    if not task.strip():
        print("task is required", file=sys.stderr)
        return 2
    rows = resolve_skills(os.getcwd(), task, agent)
    if json_out:
        print(json.dumps([{"name": name, "body": body} for name, body in rows], ensure_ascii=False, indent=2))
    elif rows:
        print("\n\n".join(f"# Skill: {name}\n\n{body.rstrip()}" for name, body in rows))
    return 0


def run_plugins_list(json_out: bool = False) -> int:
    rows = plugins()
    if json_out:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        render_plugins(rows)
    return 0


def run_plugins_install(source: str) -> int:
    try:
        manifest = install_plugin(source)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"installed {manifest['name']} {manifest['version']} ({len(manifest['skills'])} skills)")
    return 0


def run_skills_run(name: str, args: list[str]) -> int:
    try:
        return run_skill(os.getcwd(), name, args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def run_skills_assign(name: str, agent: str, *, assigned: bool) -> int:
    try:
        assign_skill(os.getcwd(), name, agent, assigned=assigned)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"{'assigned' if assigned else 'unassigned'} {name} {'to' if assigned else 'from'} {agent}")
    return 0


def run_skills_enable(name: str, *, enabled: bool) -> int:
    try:
        set_skill_enabled(os.getcwd(), name, enabled=enabled)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"{'enabled' if enabled else 'disabled'} {name}")
    return 0
