"""asgard CLI — 역할 배치와 모드. 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer

from ._app import app

# Trinity 역할 브릿지 — 호스트 도구(Claude Code/Codex/Cursor)가 [trinity.<role>] 배치 provider로
# 역할 턴을 위임할 때 쓴다 (asgard-provider 스킬 참조). [bridge] 기본 꺼짐 = 내부 모델로만 동작.
role_app = typer.Typer(
    help="hand one Trinity role a turn — it runs on whichever provider you placed it on",
    no_args_is_help=True,
)
app.add_typer(role_app, name="role")


@role_app.command("list", help="which bridges are open, where the native roles sit, and what the hosts run")
def role_list(
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.role import run_role_list

    raise typer.Exit(run_role_list(json_out))


@role_app.command("model", help="see or change the model one role uses on native, Claude Code, Cursor, or Codex")
def role_model(
    host: str = typer.Argument(None, metavar="[native|claude-code|cursor|codex]"),
    role: str = typer.Argument(None, metavar="[role]"),
    model: str = typer.Argument(None, metavar="[model]"),
    effort: str = typer.Option(None, "--effort", help="how hard the host should think (Claude Code/Codex)"),
    provider: str = typer.Option(None, "--provider", help="which native provider this role runs on"),
    reset: bool = typer.Option(False, "--reset", help="drop what this project set, and fall back"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.role import run_role_model

    raise typer.Exit(
        run_role_model(host, role, model, effort=effort, provider=provider, reset=reset, json_out=json_out)
    )


@role_app.command("run", help="run one role's turn where it is placed, and write it into the quest log")
def role_run(
    role: str = typer.Argument(..., metavar="<thinker|worker|verifier>"),
    task: str = typer.Argument(..., help="the task and its context (e.g. the Thinker plan a Worker turn works from)"),
    json_out: bool = typer.Option(False, "--json", help="stream to stderr, and print one JSON summary to stdout"),
) -> None:
    from ..commands.role import run_role_run

    raise typer.Exit(run_role_run(role, task, json_out))


mode_app = typer.Typer(
    help="see which model, effort, provider and agent each role runs on — and change any of them",
    invoke_without_command=True,
)
app.add_typer(mode_app, name="mode")


@mode_app.callback()
def mode_default(ctx: typer.Context, json_: bool = typer.Option(False, "--json")) -> None:
    if ctx.invoked_subcommand is None:
        from ..commands.mode import run_mode

        raise typer.Exit(run_mode(json_out=json_))


@mode_app.command("show", help="what each role in one mode actually ends up with, after everything is layered")
def mode_show(
    mode: str = typer.Argument(..., metavar="<native|claude-code|cursor|codex>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.mode import run_mode_show

    raise typer.Exit(run_mode_show(mode, json_out=json_))


@mode_app.command("set", help="pin the agent or model for a whole mode, or for one role inside it")
def mode_set(
    mode: str = typer.Argument(..., metavar="<native|claude-code|cursor|codex>"),
    role: str = typer.Argument(None, metavar="[role]"),
    agent: str = typer.Option(None, "--agent", help="which agent works here"),
    model: str = typer.Option(None, "--model", help="which model the role uses"),
    effort: str = typer.Option(None, "--effort", help="how hard Claude Code or Codex should think"),
    provider: str = typer.Option(None, "--provider", help="which native provider this role runs on"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.mode import run_mode_set

    raise typer.Exit(
        run_mode_set(mode, role, agent=agent, model=model, effort=effort, provider=provider, json_out=json_out)
    )


@mode_app.command("reset", help="drop what this project pinned for one mode, or for one role inside it")
def mode_reset(
    mode: str = typer.Argument(..., metavar="<native|claude-code|cursor|codex>"),
    role: str = typer.Argument(None, metavar="[role]"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.mode import run_mode_reset

    raise typer.Exit(run_mode_reset(mode, role, json_out=json_out))


@mode_app.command("pick", help="change one setting by picking from a list instead of typing it out")
def mode_pick() -> None:
    from ..commands.mode import run_mode_pick

    raise typer.Exit(run_mode_pick())
