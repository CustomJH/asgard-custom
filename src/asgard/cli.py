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
    provider: str = typer.Option(
        None,
        "--provider",
        help="override the provider: anthropic | claude-native | openai | openai-native | openai_compat | ollama | nvidia",
    ),
    model: str = typer.Option(None, "--model", help="override the model id"),
    cont: bool = typer.Option(
        False, "--continue", "-c", help="restore the last conversation for this project (context only)"
    ),
    execution: str = typer.Option(
        None,
        "--execution",
        help="execution boundary: local | container[-shared] | sandbox[-shared]",
    ),
    sandbox_name: str = typer.Option(None, "--sandbox-name", help="reuse a named isolated workspace"),
) -> None:
    from .commands.start import run_start

    raise typer.Exit(
        run_start(
            check_only=check,
            provider=provider,
            model=model,
            cont=cont,
            execution=execution,
            sandbox_name=sandbox_name,
        )
    )


auth_app = typer.Typer(help="manage Asgard-owned provider logins", no_args_is_help=True)
app.add_typer(auth_app, name="auth")


@auth_app.command("login", help="sign in to a subscription provider")
def auth_login(provider: str = typer.Argument("openai-native")) -> None:
    from .commands.auth import run_login

    raise typer.Exit(run_login(provider))


@auth_app.command("status", help="check a subscription login")
def auth_status(provider: str = typer.Argument("openai-native")) -> None:
    from .commands.auth import run_status

    raise typer.Exit(run_status(provider))


@auth_app.command("logout", help="remove an Asgard-owned subscription login")
def auth_logout(provider: str = typer.Argument("openai-native")) -> None:
    from .commands.auth import run_logout

    raise typer.Exit(run_logout(provider))


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


map_app = typer.Typer(help="generate, update, inspect, and validate the project map", no_args_is_help=True)
app.add_typer(map_app, name="map")


@map_app.command("generate", help="create the deterministic project map")
def map_generate(
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.map import run_map_generate

    raise typer.Exit(run_map_generate(dry_run=dry_run, json_out=json_, quiet=quiet))


@map_app.command("update", help="refresh a project map when repository structure changes")
def map_update(
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.map import run_map_update

    raise typer.Exit(run_map_update(dry_run=dry_run, json_out=json_, quiet=quiet))


@map_app.command("check", help="report map drift and invalid area maps without writing")
def map_check(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.map import run_map_check

    raise typer.Exit(run_map_check(json_out=json_, quiet=quiet))


@map_app.command("context", help="show the bounded map context an agent would receive")
def map_context(
    query: str = typer.Option("", "--query", "-q"),
    refresh: bool = typer.Option(False, "--refresh", help="refresh the managed map before rendering"),
    managed_only: bool = typer.Option(False, "--managed-only", help="exclude human-authored area maps"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_context

    raise typer.Exit(run_map_context(query, refresh=refresh, managed_only=managed_only, json_out=json_))


setup_app = typer.Typer(help="set up or refresh project-aware Asgard assets", no_args_is_help=True)
app.add_typer(setup_app, name="setup")


@setup_app.command("map", help="draw or refresh the evidence-based project code map")
def setup_map(
    check: bool = typer.Option(False, "--check", help="report structural drift without writing"),
    dry_run: bool = typer.Option(False, "--dry-run", help="preview whether the managed map would change"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.map import run_setup_map

    raise typer.Exit(run_setup_map(check=check, dry_run=dry_run, json_out=json_, quiet=quiet))


@app.command(help="update asgard to the latest release, or pin a version: update vX.Y.Z")
def update(
    ref: str = typer.Argument(None, metavar="[version]"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_sync: bool = typer.Option(False, "--no-sync", help="skip refreshing set-up projects after the update"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.update import run_update

    raise typer.Exit(run_update([ref] if ref else [], dry_run=dry_run, sync=not no_sync))


# `upgrade` 별칭 — 구 TS CLI(asgard-cli)의 근육기억 호환. start 안 /update 와 동일 플로우.
app.command("upgrade", hidden=True, help="alias of `update`")(update)


@app.command(help="refresh the scaffolded cores (hooks/agents/skills) in every asgard-set-up project")
def sync(
    dry_run: bool = typer.Option(False, "--dry-run"),
    list_: bool = typer.Option(False, "--list", help="list registered projects and exit"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.sync import run_sync

    raise typer.Exit(run_sync(dry_run=dry_run, list_only=list_))


@app.command(help="remove asgard (uv tool, PATH symlink, ~/.asgard)")
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.uninstall import run_uninstall

    raise typer.Exit(run_uninstall(yes=yes, dry_run=dry_run))


@app.command(help="print or install shell completion (bash|zsh|fish)")
def completions(
    shell: str = typer.Argument(None),
    install: bool = typer.Option(False, "--install", help="write the script and wire your shell rc"),
) -> None:
    from .commands.completions import run_completions

    raise typer.Exit(run_completions(shell, install=install))


# Trinity 역할 브릿지 — 호스트 도구(Claude Code/Codex/Cursor)가 [trinity.<role>] 배치 provider 로
# 역할 턴을 위임할 때 쓴다 (asgard-provider 스킬 참조). [bridge] 기본 꺼짐 = 내부 모델로만 동작.
role_app = typer.Typer(help="Trinity role bridge — run a single role on its placed provider", no_args_is_help=True)
app.add_typer(role_app, name="role")


@role_app.command("list", help="bridge flags + native placements + hosted agent models (JSON)")
def role_list() -> None:
    from .commands.role import run_role_list

    raise typer.Exit(run_role_list())


@role_app.command("model", help="list or set one role model for native, Claude Code, Cursor, or Codex")
def role_model(
    host: str = typer.Argument(None, metavar="[native|claude-code|cursor|codex]"),
    role: str = typer.Argument(None, metavar="[role]"),
    model: str = typer.Argument(None, metavar="[model]"),
    effort: str = typer.Option(None, "--effort", help="host-specific effort level (Claude Code/Codex)"),
    provider: str = typer.Option(None, "--provider", help="native provider placement"),
    reset: bool = typer.Option(False, "--reset", help="remove the project override"),
) -> None:
    from .commands.role import run_role_model

    raise typer.Exit(run_role_model(host, role, model, effort=effort, provider=provider, reset=reset))


@role_app.command("run", help="run one role turn on its placed provider and record it to the quest log")
def role_run(
    role: str = typer.Argument(..., metavar="<thinker|worker|verifier>"),
    task: str = typer.Argument(..., help="task + context (e.g. the Thinker plan for a Worker turn)"),
) -> None:
    from .commands.role import run_role_run

    raise typer.Exit(run_role_run(role, task))


# Canonical Tool Kernel — inspect the actual role-scoped surfaces used by the
# native loop and generated Claude Code agents.
tools_app = typer.Typer(help="inspect Asgard's role-scoped tool catalog", no_args_is_help=True)
app.add_typer(tools_app, name="tools")


@tools_app.command("list", help="list native + Claude Code tools for one role")
def tools_list(
    role: str = typer.Option("worker", "--role", help="thinker|worker|verifier|freyja|thor|eitri|loki|ullr|mimir"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.tools import run_tools_list

    raise typer.Exit(run_tools_list(role, json_out=json_))


# Composio-style catalog → router boundary. Client-native skill folders contain adapters only;
# selection and policy bodies are owned by these Asgard surfaces.
skills_app = typer.Typer(help="central Asgard skill catalog and deterministic router", invoke_without_command=True)
app.add_typer(skills_app, name="skills")


@skills_app.callback()
def skills_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from .commands.skills import run_skills_list

        raise typer.Exit(run_skills_list())


@skills_app.command("list", help="list bundled, installed, and learned skills")
def skills_list(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.skills import run_skills_list

    raise typer.Exit(run_skills_list(json_))


@skills_app.command("show", help="print one canonical skill body")
def skills_show(
    name: str = typer.Argument(..., metavar="<skill-name>"),
    frontmatter: bool = typer.Option(False, "--frontmatter", help="include SKILL.md frontmatter"),
    resource: str = typer.Option(None, "--resource", help="print a relative text resource bundled with the skill"),
) -> None:
    from .commands.skills import run_skills_show

    raise typer.Exit(run_skills_show(name, body_only=not frontmatter, resource=resource))


@skills_app.command("resolve", help="resolve task-matched policy for one Asgard role")
def skills_resolve(
    task: str = typer.Argument(None, help="current task (reads stdin when omitted)"),
    agent: str = typer.Option("worker", "--agent", help="worker|freyja|thor|eitri|mimir"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.skills import run_skills_resolve

    raise typer.Exit(run_skills_resolve(agent, task, json_))


@skills_app.command(
    "run",
    help="run a declared helper from a resource skill",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def skills_run(ctx: typer.Context, name: str = typer.Argument(..., metavar="<skill-name>")) -> None:
    from .commands.skills import run_skills_run

    raise typer.Exit(run_skills_run(name, list(ctx.args)))


@skills_app.command("assign", help="assign a skill to one role in this project")
def skills_assign(name: str, agent: str = typer.Option(..., "--agent")) -> None:
    from .commands.skills import run_skills_assign

    raise typer.Exit(run_skills_assign(name, agent, assigned=True))


@skills_app.command("unassign", help="remove a skill from one role in this project")
def skills_unassign(name: str, agent: str = typer.Option(..., "--agent")) -> None:
    from .commands.skills import run_skills_assign

    raise typer.Exit(run_skills_assign(name, agent, assigned=False))


@skills_app.command("enable", help="enable a skill in this project")
def skills_enable(name: str) -> None:
    from .commands.skills import run_skills_enable

    raise typer.Exit(run_skills_enable(name, enabled=True))


@skills_app.command("disable", help="disable a skill in this project")
def skills_disable(name: str) -> None:
    from .commands.skills import run_skills_enable

    raise typer.Exit(run_skills_enable(name, enabled=False))


plugins_app = typer.Typer(help="Asgard resource plugin catalog", invoke_without_command=True)
app.add_typer(plugins_app, name="plugins")


@plugins_app.callback()
def plugins_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from .commands.skills import run_plugins_list

        raise typer.Exit(run_plugins_list())


@plugins_app.command("list", help="list bundled and locally installed plugins")
def plugins_list(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.skills import run_plugins_list

    raise typer.Exit(run_plugins_list(json_))


@plugins_app.command("install", help="install a local resource plugin directory")
def plugins_install(source: str = typer.Argument(..., metavar="<path>")) -> None:
    from .commands.skills import run_plugins_install

    raise typer.Exit(run_plugins_install(source))


# 위그드라실 (Yggdrasil) — 메모리 시스템의 세계관 이름. 개인 메모리 = LLM Wiki (v3 P1).
# 정본 = ~/.asgard/memory 의 md, index/state.db 는 파생. 커맨드는 기능명 memory 유지 + 세계관 별칭.
memory_app = typer.Typer(help="Yggdrasil — personal memory · LLM wiki (ingest/query/lint)", invoke_without_command=True)
app.add_typer(memory_app, name="memory")
app.add_typer(memory_app, name="yggdrasil", hidden=True)  # 세계관 별칭 — 같은 앱, 도움말 중복 없음


@memory_app.callback()
def memory_default(
    ctx: typer.Context,
    port: int = typer.Option(8765, "--port", "-p", help="dashboard port (bare `asgard memory` only)"),
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
) -> None:
    """서브커맨드 없이 `asgard memory` 만 치면 위그드라실 대시보드가 열린다 (agentmemory 식
    원커맨드 UX). 운영 서브커맨드(add/query/…)와 --help 는 그대로다."""
    if ctx.invoked_subcommand is not None:
        return
    from .commands.memory_dashboard import run_dashboard

    raise typer.Exit(run_dashboard(port=port, open_browser=not no_open))


@memory_app.command("add", help="add a page (rejects on injection scan or index budget)")
def memory_add(
    text: str = typer.Argument(..., help="the fact/insight to remember"),
    title: str = typer.Option(None, "--title", help="page title (default: first line)"),
    kind: str = typer.Option("note", "--kind", help="note|user|decision|insight|reference|feedback"),
    links: str = typer.Option("", "--links", help="related slugs, comma-separated"),
    force: bool = typer.Option(False, "--force", help="bypass the index budget gate"),
) -> None:
    from .commands.memory import run_add

    raise typer.Exit(run_add(text, title, kind, links, force))


@memory_app.command("ingest", help="absorb new knowledge — near-duplicates merge into existing pages")
def memory_ingest(
    text: str = typer.Argument(...),
    kind: str = typer.Option("note", "--kind"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip the save confirmation"),
    plan_id: str = typer.Option(None, "--plan-id", help="execute the exact non-interactive plan previously approved"),
) -> None:
    from .commands.memory import run_ingest

    raise typer.Exit(run_ingest(text, kind, yes, plan_id))


@memory_app.command("query", help="search the wiki (FTS, zero-LLM; hits are usage-tracked)")
def memory_query(
    text: str = typer.Argument(...),
    k: int = typer.Option(5, "-k", help="max results"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_query

    raise typer.Exit(run_query(text, k, json_))


@memory_app.command("lint", help="wiki health — dead links, decay candidates, duplicates, budget")
def memory_lint(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.memory import run_lint

    raise typer.Exit(run_lint(json_))


@memory_app.command("reindex", help="rebuild index.md + state.db from pages/ (canonical)")
def memory_reindex() -> None:
    from .commands.memory import run_reindex

    raise typer.Exit(run_reindex())


@memory_app.command("export-okf", help="export personal memory as a read-only OKF v0.1 bundle")
def memory_export_okf(destination: str = typer.Argument(..., help="new or empty destination directory")) -> None:
    from .commands.memory import run_export_okf

    raise typer.Exit(run_export_okf(destination))


@memory_app.command("show", help="print one page (frontmatter + body)")
def memory_show(
    slug: str = typer.Argument(...),
    unsafe: bool = typer.Option(False, "--unsafe", help="show a quarantined (poisoned) page for repair"),
) -> None:
    from .commands.memory import run_show

    raise typer.Exit(run_show(slug, unsafe=unsafe))


@memory_app.command("remove", help="delete a page and rebuild the derived index")
def memory_remove(slug: str = typer.Argument(...)) -> None:
    from .commands.memory import run_remove

    raise typer.Exit(run_remove(slug))


@memory_app.command("merge", help="absorb one page into another (consolidate over budget)")
def memory_merge(
    src: str = typer.Argument(..., help="page to absorb (deleted after)"),
    dst: str = typer.Argument(..., help="page to grow"),
) -> None:
    from .commands.memory import run_merge

    raise typer.Exit(run_merge(src, dst))


@memory_app.command("snapshot", help="print the session injection snapshot (empty when disabled)")
def memory_snapshot(
    provider: str = typer.Option(None, "--provider", help="injection surface/provider allowlist identity"),
) -> None:
    from .commands.memory import run_snapshot

    raise typer.Exit(run_snapshot(provider))


@memory_app.command("recall", help="print query-relevant memory context (empty when disabled/no match)")
def memory_recall(
    text: str = typer.Argument(...),
    provider: str = typer.Option(None, "--provider", help="injection surface/provider allowlist identity"),
) -> None:
    from .commands.memory import run_recall

    raise typer.Exit(run_recall(text, provider))


@memory_app.command(
    "sync-turn", help="internal hook: retain one completed conversation turn from JSON stdin", hidden=True
)
def memory_sync_turn(
    mode: str = typer.Option(..., "--mode", help="native|claude-code|codex|cursor"),
) -> None:
    from .commands.memory import run_sync_turn

    raise typer.Exit(run_sync_turn(mode))


@memory_app.command("path", help="print or configure the personal memory directory")
def memory_path(
    directory: str = typer.Option(None, "--set", help="persist a global personal memory directory"),
    reset: bool = typer.Option(False, "--reset", help="restore the default personal memory directory"),
) -> None:
    from .commands.memory import run_path

    raise typer.Exit(run_path(directory, reset))


@memory_app.command("obsidian", help="open the personal memory wiki in Obsidian")
def memory_obsidian() -> None:
    from .commands.memory import run_obsidian

    raise typer.Exit(run_obsidian())


@memory_app.command("dashboard", help="open a read-only local dashboard for the personal memory wiki")
def memory_dashboard(
    port: int = typer.Option(8765, "--port", "-p", help="local port (falls back to a free port if taken)"),
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
) -> None:
    from .commands.memory_dashboard import run_dashboard

    raise typer.Exit(run_dashboard(port=port, open_browser=not no_open))


@memory_app.command("connect", help="select and configure this project's shared-memory backend")
def memory_connect(
    endpoint: str = typer.Argument(..., help="backend endpoint, e.g. http://memory.internal:8888"),
    engine: str = typer.Option("hindsight", "--engine", help="backend name (built-in or installed plugin entry point)"),
    project_id: str = typer.Option(
        None, "--project-id", "--bank", help="stable project namespace (default: unique project name + UUID suffix)"
    ),
    option: list[str] = typer.Option([], "--option", "-O", help="backend option KEY=VALUE; repeatable, no secrets"),
    claim: bool = typer.Option(False, "--claim", help="claim an empty explicitly named namespace"),
    adopt_existing: bool = typer.Option(
        False, "--adopt-existing", help="explicitly bind an existing unbound/legacy namespace (review first)"
    ),
) -> None:
    from .commands.memory import run_connect

    raise typer.Exit(
        run_connect(
            endpoint,
            project_id,
            engine=engine,
            option_values=option,
            claim=claim,
            adopt_existing=adopt_existing,
        )
    )


@memory_app.command("project-scan", help="preview important code/docs eligible for project memory")
def memory_project_scan(
    all_files: bool = typer.Option(False, "--all", help="bootstrap scan of all important tracked artifacts"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_scan

    raise typer.Exit(run_project_scan(all_files=all_files, json_out=json_))


@memory_app.command("project-sync", help="sync approved important code/docs into the selected project-memory backend")
def memory_project_sync(
    all_files: bool = typer.Option(False, "--all", help="bootstrap all important tracked artifacts"),
    yes: bool = typer.Option(False, "--yes", "-y", help="execute the previewed external write"),
    plan_id: str | None = typer.Option(None, "--plan-id", help="SHA-256 plan id emitted by the preview"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_sync

    raise typer.Exit(run_project_sync(all_files=all_files, yes=yes, json_out=json_, plan_id=plan_id))


@memory_app.command("project-approve", help="approve and commit one pending project-memory proposal")
def memory_project_approve(
    approval_id: str = typer.Argument(..., help="approval id shown in the completion proposal"),
) -> None:
    from .commands.memory import run_project_approve

    raise typer.Exit(run_project_approve(approval_id))


@memory_app.command("project-rehydrate", help="replay Git canonical project records into the selected backend")
def memory_project_rehydrate(
    yes: bool = typer.Option(False, "--yes", "-y", help="execute the previewed external writes"),
    plan_id: str | None = typer.Option(None, "--plan-id", help="SHA-256 plan id emitted by the preview"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_rehydrate

    raise typer.Exit(run_project_rehydrate(yes=yes, plan_id=plan_id, json_out=json_))


@memory_app.command("mcp", help="stdio MCP bridge for the selected project-memory backend (register once, user scope)")
def memory_mcp() -> None:
    from .commands.memory import run_mcp

    raise typer.Exit(run_mcp())


# Asgard Plan — 생각을 PRD·기능 구조·유저 플로우로 정리하고 Studio 실행으로 잇는 로컬 표면.
plan_app = typer.Typer(help="Asgard Plan — local product planning workspace", invoke_without_command=True)
app.add_typer(plan_app, name="plan")


@plan_app.callback()
def plan_default(
    ctx: typer.Context,
    port: int = typer.Option(8767, "--port", "-p", help="dashboard port (bare `asgard plan` only)"),
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
) -> None:
    """서브커맨드 없이 `asgard plan`을 실행하면 로컬 기획 워크스페이스를 연다."""
    if ctx.invoked_subcommand is not None:
        return
    from .commands.plan_dashboard import run_dashboard

    raise typer.Exit(run_dashboard(port=port, open_browser=not no_open))


@plan_app.command("dashboard", help="open the local Asgard Plan workspace")
def plan_dashboard(
    port: int = typer.Option(8767, "--port", "-p", help="local port (falls back to a free port if taken)"),
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
) -> None:
    from .commands.plan_dashboard import run_dashboard

    raise typer.Exit(run_dashboard(port=port, open_browser=not no_open))


# 세스룸니르 (Sessrúmnir) — 프레이야 스튜디오 (CUS-258). 표면 = studio + 세계관 별칭.
# 정본 = ~/.asgard/studio/projects/. 생성 파이프라인(new/refine)은 CUS-261, 내보내기는 대시보드 전용(CUS-263).
studio_app = typer.Typer(help="Sessrúmnir — Freyja design studio (dashboard/list)", invoke_without_command=True)
app.add_typer(studio_app, name="studio")
app.add_typer(studio_app, name="sessrumnir", hidden=True)  # 세계관 별칭 — 같은 앱, 도움말 중복 없음


@studio_app.callback()
def studio_default(
    ctx: typer.Context,
    port: int = typer.Option(8766, "--port", "-p", help="dashboard port (bare `asgard studio` only)"),
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
) -> None:
    """서브커맨드 없이 `asgard studio` 만 치면 세스룸니르 대시보드가 열린다 (memory 와 같은
    원커맨드 UX). 운영 서브커맨드(list/path)와 --help 는 그대로다."""
    if ctx.invoked_subcommand is not None:
        return
    from .commands.studio_dashboard import run_dashboard

    raise typer.Exit(run_dashboard(port=port, open_browser=not no_open))


@studio_app.command("dashboard", help="open the local studio dashboard (projects · artifacts · preview)")
def studio_dashboard(
    port: int = typer.Option(8766, "--port", "-p", help="local port (falls back to a free port if taken)"),
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
) -> None:
    from .commands.studio_dashboard import run_dashboard

    raise typer.Exit(run_dashboard(port=port, open_browser=not no_open))


@studio_app.command("new", help="create a studio project from a brief and generate its first artifact")
def studio_new(
    brief: str = typer.Argument(..., help="what to design/build — one clear brief"),
    name: str = typer.Option(None, "--name", help="project name (default: brief first line)"),
    provider: str = typer.Option(None, "--provider", help="override the provider"),
    model: str = typer.Option(None, "--model", help="override the model id"),
) -> None:
    from .commands.studio import run_new

    raise typer.Exit(run_new(brief, name=name, provider=provider, model=model))


@studio_app.command("open", help="open the studio dashboard focused on one project")
def studio_open(
    slug: str = typer.Argument(..., help="project slug (see `asgard studio list`)"),
    port: int = typer.Option(8766, "--port", "-p", help="local port (falls back to a free port if taken)"),
) -> None:
    from .commands.studio import run_open

    raise typer.Exit(run_open(slug, port=port))


@studio_app.command("generate", hidden=True, help="internal worker: run generation for an existing project")
def studio_generate(
    slug: str = typer.Argument(...),
    provider: str = typer.Option(None, "--provider"),
    model: str = typer.Option(None, "--model"),
) -> None:
    from .commands.studio import run_generation

    raise typer.Exit(run_generation(slug, provider=provider, model=model))


@studio_app.command(
    "engine", help="show or switch the generation engine — claude(-native CLI) | codex(openai-native CLI)"
)
def studio_engine(
    name: str = typer.Argument(None, metavar="[claude|codex]", help="omit to show the current engine"),
) -> None:
    from .commands.studio import run_engine

    raise typer.Exit(run_engine(name))


studio_tpl_app = typer.Typer(help="bundled template library — instant project scaffolds", no_args_is_help=True)
studio_app.add_typer(studio_tpl_app, name="template")


@studio_tpl_app.command("list", help="list bundled templates (design + media prompts)")
def studio_template_list(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.studio import run_template_list

    raise typer.Exit(run_template_list(json_))


@studio_tpl_app.command("use", help="scaffold a project from a template (no LLM — instant artifact)")
def studio_template_use(
    name: str = typer.Argument(..., help="template name (see `asgard studio template list`)"),
    brief: str = typer.Option(None, "--brief", help="project brief (default: template description)"),
) -> None:
    from .commands.studio import run_template_use

    raise typer.Exit(run_template_use(name, brief))


@studio_app.command("list", help="list studio projects (slug · name · artifact count)")
def studio_list(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.studio_dashboard import run_list

    raise typer.Exit(run_list(json_))


@studio_app.command("path", help="print the studio directory")
def studio_path() -> None:
    from .commands.studio_dashboard import run_path

    raise typer.Exit(run_path())


# 자가발전 인박스 (CUS-251) — 퀘스트 로그 채굴 → 스킬 후보 → 승인만이 활성화 경로.
evolve_app = typer.Typer(
    help="self-evolution inbox — mine quest logs into skill drafts, then approve", no_args_is_help=True
)
app.add_typer(evolve_app, name="evolve")


@evolve_app.command("scan", help="mine quest logs for hard-won lessons (FAIL→PASS) into pending drafts")
def evolve_scan() -> None:
    from .commands.evolve import run_scan

    raise typer.Exit(run_scan())


@evolve_app.command(
    "nudge", help="print an unmined-signal nudge once per new signal set (hook surface; silent otherwise)"
)
def evolve_nudge() -> None:
    from .commands.evolve import run_nudge

    raise typer.Exit(run_nudge())


@evolve_app.command("list", help="list pending skill drafts (edit the files before approving if needed)")
def evolve_list() -> None:
    from .commands.evolve import run_list

    raise typer.Exit(run_list())


@evolve_app.command("show", help="print one pending draft (SKILL.md)")
def evolve_show(cid: str = typer.Argument(..., metavar="<id>")) -> None:
    from .commands.evolve import run_show

    raise typer.Exit(run_show(cid))


@evolve_app.command("approve", help="validate and install a draft — routes on the next dispatch, no restart")
def evolve_approve(cid: str = typer.Argument(..., metavar="<id>")) -> None:
    from .commands.evolve import run_approve

    raise typer.Exit(run_approve(cid))


@evolve_app.command("reject", help="reject a draft — the same signal is never proposed again")
def evolve_reject(
    cid: str = typer.Argument(..., metavar="<id>"),
    reason: str = typer.Option("", "--reason", help="optional note (kept for distillation-quality audits)"),
) -> None:
    from .commands.evolve import run_reject

    raise typer.Exit(run_reject(cid, reason))


@evolve_app.command("polish", help="LLM-rewrite a pending draft into principle-level prose (opt-in; stays pending)")
def evolve_polish(cid: str = typer.Argument(..., metavar="<id>")) -> None:
    from .commands.evolve import run_polish

    raise typer.Exit(run_polish(cid))


@evolve_app.command("bench", help="A/B a learned skill OFF vs ON — MAD-confidence keep/discard verdict")
def evolve_bench(
    skill: str = typer.Argument(..., metavar="<skill-name>"),
    cmd: str = typer.Option(..., "--cmd", help="bench command printing `METRIC <name>=<float>` to stdout"),
    metric: str = typer.Option(..., "--metric", help="metric name to parse from the command output"),
    runs: int = typer.Option(5, "--runs", help="runs per arm (needs ≥3 for a verdict)"),
    direction: str = typer.Option("min", "--direction", help="min (lower is better) | max"),
    timeout: int = typer.Option(600, "--timeout", help="seconds per run"),
) -> None:
    from .commands.evolve import run_bench

    raise typer.Exit(run_bench(skill, cmd, metric, runs, direction, timeout))


@evolve_app.command("archive", help="retire a learned skill without deleting it (reversible)")
def evolve_archive(name: str = typer.Argument(..., metavar="<skill-name>")) -> None:
    from .commands.evolve import run_archive

    raise typer.Exit(run_archive(name))


@evolve_app.command("restore", help="bring an archived learned skill back into routing")
def evolve_restore(name: str = typer.Argument(..., metavar="<skill-name>")) -> None:
    from .commands.evolve import run_restore

    raise typer.Exit(run_restore(name))


@app.command(help="run one task headless through the native Trinity loop (benches/CI)")
def run(
    prompt: str = typer.Argument(None, help="the task to execute (omit with --resume)"),
    provider: str = typer.Option(None, "--provider", help="override the provider"),
    model: str = typer.Option(None, "--model", help="override the model id"),
    json_: bool = typer.Option(False, "--json", help="stream to stderr, print a final JSON summary to stdout"),
    resume: bool = typer.Option(False, "--resume", help="resume the active durable native Quest"),
    quest: str = typer.Option(None, "--quest", help="specific Quest id to resume"),
    dual: bool = typer.Option(False, "--dual", help="plan writes with thinker + thinker_alt in parallel"),
) -> None:
    from .commands.start import run_prompt

    raise typer.Exit(
        run_prompt(prompt, provider=provider, model=model, json_out=json_, resume=resume, quest_id=quest, dual=dual)
    )


if __name__ == "__main__":
    app()
