"""asgard CLI — 에이전트(에인헤랴르)와 인증. 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer

from ._app import app

agent_app = typer.Typer(help="agents (Einherjar) — keep several on one install, each remembering you separately")
app.add_typer(agent_app, name="agent")
app.add_typer(agent_app, name="einherjar", hidden=True)  # 세계관 별칭 — 같은 앱, 도움말 중복 없음


@agent_app.command("list", help="every agent on this machine — plus the built-in ones not yet raised")
def agent_list(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_list

    raise typer.Exit(run_agent_list(json_out=json_, quiet=quiet))


@agent_app.command("show", help="one agent — who it is, how much it remembers, and what it can do")
def agent_show(
    name: str = typer.Argument(..., help="agent id"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_show

    raise typer.Exit(run_agent_show(name, json_out=json_, quiet=quiet))


@agent_app.command("open", help="open one agent's Studio window, reusing its live window unless --new is set")
def agent_open(
    name: str = typer.Argument(None, help="agent id; omit to pick from configured and built-in agents"),
    new: bool = typer.Option(False, "--new", help="start another window even when this agent already has one"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.agent import run_agent_open

    raise typer.Exit(run_agent_open(name, new=new, json_out=json_))


@agent_app.command("windows", help="show registered Studio windows, their agents, URLs, processes, and state")
def agent_windows(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.agent import run_agent_windows

    raise typer.Exit(run_agent_windows(json_out=json_))


@agent_app.command("config", help="show or change one agent's model, provider, permissions, and other settings")
def agent_config(
    name: str = typer.Argument(..., help="agent id"),
    set_values: list[str] = typer.Option(None, "--set", help="set SECTION.KEY=VALUE (repeatable)"),
    unset_values: list[str] = typer.Option(None, "--unset", help="remove SECTION.KEY from this agent (repeatable)"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_config

    raise typer.Exit(
        run_agent_config(
            name,
            set_values=list(set_values or []),
            unset_values=list(unset_values or []),
            json_out=json_,
            quiet=quiet,
        )
    )


@agent_app.command("identity", help="show or replace an agent's AGENT.md instructions")
def agent_identity(
    name: str = typer.Argument(..., help="agent id"),
    set_file: str = typer.Option(None, "--set-file", help="replace AGENT.md from a UTF-8 file"),
    set_value: str = typer.Option(None, "--set", help="use '-' to replace AGENT.md from stdin"),
    edit: bool = typer.Option(False, "--edit", help="open AGENT.md with $EDITOR"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_identity

    raise typer.Exit(
        run_agent_identity(
            name,
            set_file=set_file,
            set_value=set_value,
            edit=edit,
            json_out=json_,
            quiet=quiet,
        )
    )


@agent_app.command("create", help="raise a new agent — it gets its own home, its own identity, its own memory")
def agent_create(
    name: str = typer.Argument(..., help="agent id — [a-z0-9][a-z0-9_-]*"),
    from_: str = typer.Option(None, "--from", help="seed the identity from a built-in Asgard agent (freyja, loki, …)"),
    description: str = typer.Option(
        None, "--description", "-d", help="what this agent is good at — the swarm reads it"
    ),
    can: list[str] = typer.Option(None, "--can", help="a capability this agent has (repeatable)"),
    clone: str = typer.Option(
        None, "--clone", help="copy settings/identity/skills from an existing agent (never its memory)"
    ),
    display: str = typer.Option(None, "--name", help="display name"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_create

    raise typer.Exit(
        run_agent_create(
            name,
            based_on=from_,
            description=description,
            can=list(can or []),
            clone_from=clone,
            display=display,
            json_out=json_,
            quiet=quiet,
        )
    )


@agent_app.command("use", help="make this the machine's active agent (built-in names are raised on demand)")
def agent_use(
    name: str = typer.Argument(..., help="agent id, or 'default'"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_use

    raise typer.Exit(run_agent_use(name, json_out=json_, quiet=quiet))


@agent_app.command("describe", help="set what this agent is good at — the sentence the swarm routes on")
def agent_describe(
    name: str = typer.Argument(..., help="agent id"),
    description: str = typer.Argument(None, help="one or two sentences"),
    can: list[str] = typer.Option(None, "--can", help="a capability this agent has (repeatable, replaces the list)"),
    display: str = typer.Option(None, "--name", help="display name"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_describe

    raise typer.Exit(
        run_agent_describe(name, description, can=list(can or []), display=display, json_out=json_, quiet=quiet)
    )


@agent_app.command("delete", help="remove an agent — everything it remembered goes with it")
def agent_delete(
    name: str = typer.Argument(..., help="agent id"),
    yes: bool = typer.Option(False, "--yes", help="skip the confirmation"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_delete

    raise typer.Exit(run_agent_delete(name, yes=yes, json_out=json_, quiet=quiet))


@agent_app.command("rename", help="rename an agent and keep its settings, identity, and memory together")
def agent_rename(
    old: str = typer.Argument(..., help="current agent id"),
    new: str = typer.Argument(..., help="new agent id"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_rename

    raise typer.Exit(run_agent_rename(old, new, json_out=json_, quiet=quiet))


@agent_app.command("export", help="export an agent to a local tar.gz backup")
def agent_export(
    name: str = typer.Argument(..., help="agent id"),
    out_path: str = typer.Option(None, "--output", "-o", help="archive path (default: ./<name>.tar.gz)"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_export

    raise typer.Exit(run_agent_export(name, out_path=out_path, json_out=json_, quiet=quiet))


@agent_app.command("import", help="import an agent from a tar.gz backup without overwriting an existing agent")
def agent_import(
    archive: str = typer.Argument(..., help="tar.gz archive path"),
    as_name: str = typer.Option(None, "--as", help="import under a different agent id"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_import

    raise typer.Exit(run_agent_import(archive, as_name=as_name, json_out=json_, quiet=quiet))


@agent_app.command(
    "bind", help="place an agent in THIS project — as its default, per mode, or per Trinity role (swarm)"
)
def agent_bind(
    name: str = typer.Argument(..., help="agent id"),
    mode: str = typer.Option(None, "--mode", help="native | claude-code | cursor | codex"),
    role: str = typer.Option(None, "--role", help="thinker | worker | verifier | …"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_bind

    raise typer.Exit(run_agent_bind(name, mode=mode, role=role, json_out=json_, quiet=quiet))


@agent_app.command("unbind", help="drop a placement from this project")
def agent_unbind(
    mode: str = typer.Option(None, "--mode", help="native | claude-code | cursor | codex"),
    role: str = typer.Option(None, "--role", help="thinker | worker | verifier | …"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_unbind

    raise typer.Exit(run_agent_unbind(mode=mode, role=role, json_out=json_, quiet=quiet))


@agent_app.command("where", help="who works here, and which declaration won")
def agent_where(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.agent import run_agent_where

    raise typer.Exit(run_agent_where(json_out=json_, quiet=quiet))


auth_app = typer.Typer(help="the provider logins Asgard holds for you", no_args_is_help=True)
app.add_typer(auth_app, name="auth")


@auth_app.command("login", help="sign in to a subscription provider")
def auth_login(provider: str = typer.Argument("openai-native")) -> None:
    from ..commands.auth import run_login

    raise typer.Exit(run_login(provider))


@auth_app.command("status", help="is that subscription login still good")
def auth_status(
    provider: str = typer.Argument("openai-native"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.auth import run_status

    raise typer.Exit(run_status(provider, json_out))


@auth_app.command("logout", help="drop a subscription login Asgard was holding")
def auth_logout(
    provider: str = typer.Argument("openai-native"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.auth import run_logout

    raise typer.Exit(run_logout(provider, json_out))
