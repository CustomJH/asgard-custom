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
    version: bool = typer.Option(False, "--version", "-v", callback=_version, is_eager=True,
                                 help="show version and exit"),
) -> None:
    """Root callback — hosts the global --version flag."""


@app.command(help="check the install — runtime, PATH, and project wiring")
def doctor(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.doctor import run_doctor

    raise typer.Exit(run_doctor(json_out=json_, quiet=quiet))


@app.command(help="open the Asgard terminal (Heimdall) — chat, connect a provider, run tasks")
def start(
    check: bool = typer.Option(False, "--check", help="run preflight checks only, then exit (for CI)"),
    provider: str = typer.Option(None, "--provider", help="override the provider: anthropic | openai_compat | nvidia"),
    model: str = typer.Option(None, "--model", help="override the model id"),
    tui: bool = typer.Option(False, "--tui", help="full-screen TUI (experimental)"),
    plain: bool = typer.Option(False, "--plain", help="force the plain readline REPL (no TUI)"),
) -> None:
    from .commands.start import run_start

    raise typer.Exit(run_start(check_only=check, provider=provider, model=model, tui=tui, plain=plain))


@app.command(help="scaffold a project for coding agents (Claude Code / Cursor / Codex)")
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


@app.command(help="update asgard to the latest release, or pin a version: update vX.Y.Z")
def update(
    ref: str = typer.Argument(None, metavar="[version]"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.update import run_update

    raise typer.Exit(run_update([ref] if ref else [], dry_run=dry_run))


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


# 미구현 스텁 — 정식 커맨드처럼 목록에 노출하지 않도록 hidden. 구현되면 hidden 제거.
@app.command(hidden=True)
def run() -> None:
    typer.echo("asgard run: planned")


if __name__ == "__main__":
    app()
