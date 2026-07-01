"""asgard CLI (Python 3.14) — CUS-108 Path B. Phase 1 scaffold: version + help + command shells.

Logic (doctor/setup/upgrade/uninstall/completions) ports in later phases; the TypeScript CLI
(src/cli.ts) stays authoritative until parity is reached.
"""

import typer

from . import __version__

app = typer.Typer(
    name="asgard",
    help="asgard — make anything, your way",
    no_args_is_help=True,
    add_completion=True,  # Typer generates bash/zsh/fish completions (replaces the hand-rolled ones)
)


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-v", callback=_version, is_eager=True, help="print version"
    ),
) -> None:
    """Root callback — hosts the global --version flag."""


@app.command()
def version() -> None:
    """print version"""
    typer.echo(__version__)


def _planned(cmd: str) -> None:
    typer.echo(f"asgard {cmd}: migrating to Python (CUS-108)")


@app.command()
def doctor() -> None:
    """diagnose runtime & PATH"""
    _planned("doctor")


@app.command()
def setup() -> None:
    """set up project — AGENTS.md (all agents); --cc/--cursor/--codex add per-tool skeletons"""
    _planned("setup")


@app.command()
def upgrade() -> None:
    """self-update the binary (upgrade [version])"""
    _planned("upgrade")


@app.command()
def uninstall() -> None:
    """remove asgard (binary, PATH symlink, ~/.asgard)"""
    _planned("uninstall")


@app.command()
def completions() -> None:
    """print shell completion script (bash|zsh|fish)"""
    _planned("completions")


if __name__ == "__main__":
    app()
