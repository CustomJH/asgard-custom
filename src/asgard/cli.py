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
    version: bool = typer.Option(
        False, "--version", "-v", callback=_version, is_eager=True, help="show version and exit"
    ),
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
    lagom: str = typer.Option(None, "--lagom", help="lagom default mode: off | lite | full (default full)"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.setup import run_init

    raise typer.Exit(
        run_init(cc=cc, cursor=cursor, codex=codex, profile=profile, force=force, dry_run=dry_run, yes=yes, lagom=lagom)
    )


@app.command(help="update asgard to the latest release, or pin a version: update vX.Y.Z")
def update(
    ref: str = typer.Argument(None, metavar="[version]"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.update import run_update

    raise typer.Exit(run_update([ref] if ref else [], dry_run=dry_run))


# `upgrade` 별칭 — 구 TS CLI(asgard-cli)의 근육기억 호환. start 안 /update 와 동일 플로우.
app.command("upgrade", hidden=True, help="alias of `update`")(update)


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


# Trinity 역할 브릿지 — 호스트 도구(Claude Code/Codex/Cursor)가 [trinity.<role>] 배치 provider 로
# 역할 턴을 위임할 때 쓴다 (asgard-provider 스킬 참조). [bridge] 기본 꺼짐 = 내부 모델로만 동작.
role_app = typer.Typer(help="Trinity role bridge — run a single role on its placed provider", no_args_is_help=True)
app.add_typer(role_app, name="role")


@role_app.command("list", help="bridge flags + role placements (JSON)")
def role_list() -> None:
    from .commands.role import run_role_list

    raise typer.Exit(run_role_list())


@role_app.command("run", help="run one role turn on its placed provider and record it to the quest log")
def role_run(
    role: str = typer.Argument(..., metavar="<thinker|worker|verifier>"),
    task: str = typer.Argument(..., help="task + context (e.g. the Thinker plan for a Worker turn)"),
) -> None:
    from .commands.role import run_role_run

    raise typer.Exit(run_role_run(role, task))


@app.command(help="run one task headless through the native Trinity loop (benches/CI)")
def run(
    prompt: str = typer.Argument(..., help="the task to execute"),
    provider: str = typer.Option(None, "--provider", help="override the provider"),
    model: str = typer.Option(None, "--model", help="override the model id"),
    json_: bool = typer.Option(False, "--json", help="stream to stderr, print a final JSON summary to stdout"),
) -> None:
    from .commands.start import run_prompt

    raise typer.Exit(run_prompt(prompt, provider=provider, model=model, json_out=json_))


if __name__ == "__main__":
    app()
