"""asgard CLI — 도구·스킬·플러그인. 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer

from ._app import app

# Canonical Tool Kernel — inspect the actual role-scoped surfaces used by the
# native loop and generated Claude Code agents.
tools_app = typer.Typer(help="which tools each role is allowed to reach for", no_args_is_help=True)
app.add_typer(tools_app, name="tools")


@tools_app.command("list", help="every tool one role can use, native and Claude Code alike")
def tools_list(
    role: str = typer.Option("worker", "--role", help="thinker|worker|verifier|freyja|thor|eitri|loki|ullr|mimir"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.tools import run_tools_list

    raise typer.Exit(run_tools_list(role, json_out=json_))


# Composio-style catalog → router boundary. Client-native skill folders contain adapters only;
# selection and policy bodies are owned by these Asgard surfaces.
skills_app = typer.Typer(
    help="every skill Asgard knows, and which one it reaches for on a given task",
    invoke_without_command=True,
)
app.add_typer(skills_app, name="skills")


@skills_app.callback()
def skills_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from ..commands.skills import run_skills_list

        raise typer.Exit(run_skills_list())


@skills_app.command("list", help="the skills that shipped, the ones you installed, and the ones Asgard learned")
def skills_list(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.skills import run_skills_list

    raise typer.Exit(run_skills_list(json_))


@skills_app.command("show", help="print one skill exactly as the agents read it")
def skills_show(
    name: str = typer.Argument(..., metavar="<skill-name>"),
    frontmatter: bool = typer.Option(False, "--frontmatter", help="keep the SKILL.md frontmatter too"),
    resource: str = typer.Option(None, "--resource", help="print a text file bundled alongside the skill"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.skills import run_skills_show

    raise typer.Exit(run_skills_show(name, body_only=not frontmatter, resource=resource, json_out=json_out))


@skills_app.command("resolve", help="what one role would be told to do, given this task")
def skills_resolve(
    task: str = typer.Argument(None, help="the task at hand (read from stdin if you leave it out)"),
    agent: str = typer.Option("worker", "--agent", help="worker|freyja|thor|eitri|mimir"),
    json_: bool = typer.Option(False, "--json"),
    scope_only: bool = typer.Option(
        False, "--scope-only", help="work shape and specialist match only — no skill bodies (prompt injection)"
    ),
) -> None:
    from ..commands.skills import run_skills_resolve

    raise typer.Exit(run_skills_resolve(agent, task, json_, scope_only=scope_only))


@skills_app.command(
    "run",
    help="run a helper a skill ships with",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def skills_run(ctx: typer.Context, name: str = typer.Argument(..., metavar="<skill-name>")) -> None:
    from ..commands.skills import run_skills_run

    raise typer.Exit(run_skills_run(name, list(ctx.args)))


@skills_app.command("assign", help="give one role this skill, in this project")
def skills_assign(
    name: str,
    agent: str = typer.Option(..., "--agent"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.skills import run_skills_assign

    raise typer.Exit(run_skills_assign(name, agent, assigned=True, json_out=json_out))


@skills_app.command("unassign", help="take this skill back off a role, in this project")
def skills_unassign(
    name: str,
    agent: str = typer.Option(..., "--agent"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.skills import run_skills_assign

    raise typer.Exit(run_skills_assign(name, agent, assigned=False, json_out=json_out))


@skills_app.command("enable", help="let this project use a skill again")
def skills_enable(
    name: str,
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.skills import run_skills_enable

    raise typer.Exit(run_skills_enable(name, enabled=True, json_out=json_out))


@skills_app.command("disable", help="keep this project from reaching for a skill")
def skills_disable(
    name: str,
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.skills import run_skills_enable

    raise typer.Exit(run_skills_enable(name, enabled=False, json_out=json_out))


plugins_app = typer.Typer(help="the resource plugins Asgard can draw skills from", invoke_without_command=True)
app.add_typer(plugins_app, name="plugins")


@plugins_app.callback()
def plugins_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from ..commands.skills import run_plugins_list

        raise typer.Exit(run_plugins_list())


@plugins_app.command("list", help="the plugins that shipped, and the ones you installed here")
def plugins_list(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.skills import run_plugins_list

    raise typer.Exit(run_plugins_list(json_))


@plugins_app.command("install", help="install a local resource plugin directory")
def plugins_install(
    source: str = typer.Argument(..., metavar="<path>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.skills import run_plugins_install

    raise typer.Exit(run_plugins_install(source, json_out))
