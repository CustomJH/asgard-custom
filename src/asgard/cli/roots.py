"""asgard CLI — 작업 뿌리. 명령 본문은 `asgard.commands.workroots` 에 있고 여기는 표면 선언만 진다."""

import typer

from ._app import app

root_app = typer.Typer(
    help="the directories outside this repo that agents may edit — declare one, list them, take one back",
    no_args_is_help=True,
)
app.add_typer(root_app, name="root")


@root_app.command("list", help="the work roots in force right now, and which of them this project declared")
def root_list(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.workroots import run_root_list

    raise typer.Exit(run_root_list(json_out=json_))


@root_app.command("add", help="open a directory outside this repo as a work target — asks first, or takes --yes")
def root_add(
    directory: str = typer.Argument(..., metavar="DIR"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Odin already agreed — write the declaration without asking"),
    absolute: bool = typer.Option(False, "--absolute", help="store the absolute path, not one relative to this repo"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.workroots import run_root_add

    raise typer.Exit(run_root_add(directory, assume_yes=yes, absolute=absolute, json_out=json_))


@root_app.command("remove", help="take a declared directory back out of the work roots")
def root_remove(
    directory: str = typer.Argument(..., metavar="DIR"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.workroots import run_root_remove

    raise typer.Exit(run_root_remove(directory, json_out=json_))
