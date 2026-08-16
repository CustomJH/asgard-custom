"""asgard CLI — the run surface (just). 명령 본문은 `asgard.commands.just`에 있다.

레시피를 **도는** 명령은 여기 없다. `just test` 가 이미 그 일을 하고, 한 겹 감싸면 인자
전달·종료 코드·`--list` 출력이 미묘하게 갈린다 (lagom 사다리 ④ — 플랫폼 기능이 이미 있다)."""

import typer

from ._app import app

just_app = typer.Typer(
    help="the project's run commands — bring the run surface in, keep it current, check it has not drifted",
    no_args_is_help=True,
)
app.add_typer(just_app, name="just")


@just_app.command("init", help="bring the run surface into this repository — install the runner and write the Justfile")
def just_init(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.just import run_just_init

    raise typer.Exit(run_just_init(json_out=json_, quiet=quiet))


@just_app.command("sync", help="redraw the managed recipes from the checked-in manifests; your own recipes stay")
def just_sync(
    dry_run: bool = typer.Option(False, "--dry-run", help="work out the file and write nothing"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.just import run_just_sync

    raise typer.Exit(run_just_sync(dry_run=dry_run, json_out=json_, quiet=quiet))


@just_app.command("check", help="how far the run surface has drifted from the manifests — writes nothing")
def just_check(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.just import run_just_check

    raise typer.Exit(run_just_check(json_out=json_, quiet=quiet))


@just_app.command("install", help="put the just runner on PATH for this machine")
def just_install(
    force: bool = typer.Option(False, "--force", help="install again even when just is already there"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.just import run_just_install

    raise typer.Exit(run_just_install(force=force, json_out=json_, quiet=quiet))
