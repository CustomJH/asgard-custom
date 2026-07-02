"""asgard CLI (Python 3.14) — Typer entry. Global flags live on each command (mirrors the TS surface).
Commands delegate to `asgard.commands.*`; templates + guards live in `asgard.templates`."""

import typer

from . import __version__, ui

app = typer.Typer(
    name="asgard",
    help="asgard — make anything, your way",
    no_args_is_help=True,
    add_completion=False,  # we ship an explicit `completions` command (byte-compatible with the TS one)
)


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(False, "--version", "-v", callback=_version, is_eager=True, help="print version"),
) -> None:
    """Root callback — hosts the global --version flag."""


@app.command(help="print version")
def version() -> None:
    typer.echo(__version__)


@app.command(help="diagnose runtime & PATH")
def doctor(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.doctor import run_doctor

    raise typer.Exit(run_doctor(json_out=json_, quiet=quiet))


@app.command(help="set up a project — interactive picker (TTY); --cc/--cursor/--codex/--profile for a specific agent")
def init(
    cc: bool = typer.Option(False, "--cc", help="Claude Code (.claude/) skeleton"),
    cursor: bool = typer.Option(False, "--cursor", help="Cursor (.cursor/) skeleton"),
    codex: bool = typer.Option(False, "--codex", help="Codex (.codex/) skeleton"),
    profile: str = typer.Option(None, "--profile", help="claude-code | cursor | codex | universal"),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip the picker, use the default profile (claude-code)"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.setup import run_init

    raise typer.Exit(run_init(cc=cc, cursor=cursor, codex=codex, profile=profile, force=force, dry_run=dry_run, yes=yes))


@app.command(help="self-update via uv (upgrade [version])")
def upgrade(
    ref: str = typer.Argument(None, metavar="[version]"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.upgrade import run_upgrade

    raise typer.Exit(run_upgrade([ref] if ref else [], dry_run=dry_run))


@app.command(help="remove asgard (uv tool, PATH symlink, ~/.asgard)")
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.uninstall import run_uninstall

    raise typer.Exit(run_uninstall(yes=yes, dry_run=dry_run))


@app.command(help="print shell completion script (bash|zsh|fish)")
def completions(shell: str = typer.Argument(None)) -> None:
    from .commands.completions import run_completions

    raise typer.Exit(run_completions(shell))


@app.command(help="run an .asgardfile task")
def run() -> None:
    typer.echo("asgard run: planned")


@app.command(help="update this project's config (planned)")
def update() -> None:
    typer.echo("asgard update: planned")


if __name__ == "__main__":
    app()
