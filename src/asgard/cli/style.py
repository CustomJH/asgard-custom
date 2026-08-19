"""asgard CLI — 코드 스타일 규격 (style). 명령 본문은 `asgard.commands.style` 에 있다."""

import typer

from ._app import app

style_app = typer.Typer(
    help="this repository's own code style — declare the linters and formatters it already uses, and hold the "
    "change to them",
    no_args_is_help=True,
)
app.add_typer(style_app, name="style")


@style_app.command(
    "check",
    help="run the declared style tools. with --path, only violations in those files block — the rest is inherited debt",
)
def style_check(
    path: list[str] = typer.Option(None, "--path", help="attribute violations to these paths (repeatable)"),
    fix: bool = typer.Option(
        False, "--fix", help="run every declared fix command first, then judge again — this rewrites files on disk"
    ),
    autofix: bool = typer.Option(
        False,
        "--autofix",
        help="same, but only for tools that declared `autofix: true` — what the gate uses",
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.style import run_check

    repair = "all" if fix else "auto" if autofix else ""
    raise typer.Exit(run_check(paths=tuple(path or ()), json_out=json_, repair=repair))


@style_app.command("list", help="what this repository declares, and what was found in it but never declared")
def style_list(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.style import run_list

    raise typer.Exit(run_list(json_out=json_))


@style_app.command(
    "init",
    help="scan for style config files (checkstyle.xml, eslint.config.js, .clang-format …) and write what was found "
    "into .asgard/asgard-setting-project.json, where you then edit it",
)
def style_init(
    force: bool = typer.Option(False, "--force", help="overwrite tools already declared"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.style import run_init

    raise typer.Exit(run_init(json_out=json_, force=force))
