"""`asgard office` — a human surface over the Sága document lanes.

The skill entrypoint (`asgard skills run asgard-office -- …`) is what an agent
calls. This is the same engine with a shorter name and a rendered catalog, for
the person who wants to look at their templates without remembering that.
"""

import json
import os
import subprocess
import sys

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .. import theme, ui
from ..skill_registry import run_skill

SKILL = "asgard-office"


def _console() -> Console:
    return Console(
        file=sys.stdout,
        width=ui.term_cols(),
        color_system="auto" if ui._COLOR else None,
        force_terminal=ui._COLOR,
        highlight=False,
    )


def _run(args: list[str]) -> int:
    try:
        return run_skill(os.getcwd(), SKILL, args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def run_office_build(lane: str, spec: str, output: str, template: str, values: str, json_: bool) -> int:
    args = ["build", lane, spec, "-o", output]
    if template:
        args += ["--template", template]
    if values:
        args += ["--values", values]
    if json_:
        args.append("--json")
    return _run(args)


def run_office_read(path: str, json_: bool) -> int:
    return _run(["read", path, "--format", "json" if json_ else "markdown"])


def run_office_verify(path: str, strict: bool, json_: bool) -> int:
    return _run(["verify", path, *(["--strict"] if strict else []), *(["--json"] if json_ else [])])


def run_office_fill(path: str, values: str, output: str, scan: bool, json_: bool) -> int:
    if scan:
        return _run(["fill", path, "--scan", *(["--json"] if json_ else [])])
    return _run(["fill", path, "--values", values, "-o", output, *(["--json"] if json_ else [])])


def run_office_render(path: str, outdir: str, probe: bool, recalc: bool) -> int:
    if probe:
        return _run(["render", "--probe"])
    args = ["render", path]
    if recalc:
        args.append("--recalc")
    elif outdir:
        args += ["-o", outdir]
    return _run(args)


def run_office_outline(genre: str, language: str, output: str, json_: bool) -> int:
    if not genre:
        return _catalog_outline(json_)
    args = ["outline", genre, "--language", language]
    if output:
        args += ["-o", output]
    return _run(args)


def run_office_template(args: list[str]) -> int:
    if args and args[0] == "list" and not any(item == "--json" for item in args):
        return _catalog_templates()
    return _run(["template", *args])


# ------------------------------------------------------------------ rendering


def _panel(label: str, rows: list, columns: list[dict]) -> None:
    console = _console()
    table = Table.grid(expand=True, padding=(0, 1))
    if console.width < 96:
        table.add_column(overflow="fold")
        for index, row in enumerate(rows):
            table.add_row(Text("\n").join(row))
            if index + 1 < len(rows):
                table.add_row("")
    else:
        for column in columns:
            table.add_column(**column)
        for row in rows:
            table.add_row(*row)
    title = Text.assemble((label, theme.SUBTEXT), (f" · {len(rows)}", f"bold {theme.TEXT}"))
    console.print(Panel(table, title=title, title_align="left", border_style=theme.HAIRLINE, box=box.ROUNDED))


def _capture(args: list[str]) -> tuple[int, str]:
    """Run the lane entrypoint and keep its stdout.

    The subprocess is the single contract with the lane. Importing the lane
    modules in-process would put a directory holding `outline.py`, `verify.py`,
    and `template.py` on the CLI's own sys.path, where any of those names could
    shadow something later — a rendered table is not worth that.
    """
    from pathlib import Path

    from ..skill_registry import bundled_plugins

    plugin = bundled_plugins().get(SKILL)
    if not plugin:
        raise ValueError(f"{SKILL} is not installed")
    entrypoint = Path(plugin["root"], "skills", SKILL, plugin["entrypoints"][SKILL])
    result = subprocess.run(
        [sys.executable, str(entrypoint), *args],
        cwd=os.getcwd(),
        # Both halves of the pipe are pinned, not just this one. Reading UTF-8
        # from a child that writes cp949 fails the same way as the reverse, and
        # a Korean template title is enough to trigger it on a Korean Windows.
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode, result.stdout


def _catalog_templates() -> int:
    try:
        code, payload = _capture(["template", "list", "--json"])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if code or not payload.strip():
        return code or 1
    data = json.loads(payload)
    rows = []
    for item in data["templates"]:
        required = sum(1 for entry in item["fields"] if entry["required"])
        rows.append(
            (
                Text(item["name"], style=f"bold {theme.TEXT}"),
                Text.assemble(
                    (item["kind"], theme.SUBTEXT),
                    ("  ", ""),
                    (item["origin"], theme.SUBTEXT),
                    ("  ", ""),
                    (f"{len(item['fields'])} fields / {required} required", theme.SUBTEXT),
                ),
                Text(item["title"] or item["description"], style=theme.SUBTEXT),
            )
        )
    problems = data.get("problems") or []
    if not rows:
        print("no templates yet — asgard office template new <name> --genre report")
        return 0
    _panel(
        "office templates",
        rows,
        [
            {"min_width": 18, "max_width": 28, "overflow": "fold"},
            {"min_width": 22, "max_width": 40, "overflow": "fold"},
            {"ratio": 1, "overflow": "fold"},
        ],
    )
    for problem in problems:
        print(f"  unreadable: {problem}", file=sys.stderr)
    return 0


def _catalog_outline(json_: bool) -> int:
    if json_:
        return _run(["outline", "--json"])
    try:
        code, payload = _capture(["outline", "--json"])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if code or not payload.strip():
        return code or 1
    rows = [
        (
            Text(row["genre"], style=f"bold {theme.TEXT}"),
            Text.assemble((row["kind"], theme.SUBTEXT), ("  ", ""), (f"{row['sections']} sections", theme.SUBTEXT)),
            Text(row["title"], style=theme.SUBTEXT),
        )
        for row in json.loads(payload)
    ]
    _panel(
        "document genres",
        rows,
        [
            {"min_width": 14, "max_width": 20, "overflow": "fold"},
            {"min_width": 16, "max_width": 24, "overflow": "fold"},
            {"ratio": 1, "overflow": "fold"},
        ],
    )
    return 0
