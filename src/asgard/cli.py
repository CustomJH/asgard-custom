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
        help="override the provider: anthropic | claude-native | openai | openai-native | openai_compat | openrouter | ollama | nvidia",
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


map_app = typer.Typer(
    help="project map — orientation, relation graph, and bounded context", invoke_without_command=True
)
app.add_typer(map_app, name="map")


@map_app.callback()
def map_default(
    ctx: typer.Context,
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
) -> None:
    """서브커맨드 없이 `asgard map` 만 치면 관계 그래프 뷰가 열린다 (`asgard memory` 와 동일 UX).
    운영 서브커맨드(generate/update/scan/…)와 --help 는 그대로다."""
    if ctx.invoked_subcommand is not None:
        return
    from .commands.map import run_map_view

    raise typer.Exit(run_map_view(open_browser=not no_open))


@map_app.command("scan", help="rebuild the relation graph (deterministic evidence, no LLM)")
def map_scan(
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.map import run_map_scan

    raise typer.Exit(run_map_scan(dry_run=dry_run, json_out=json_, quiet=quiet))


@map_app.command("trace", help="walk relation edges from a node (adjacent map, not exhaustive impact)")
def map_trace(
    from_: str = typer.Option(..., "--from", help="node id, e.g. external_service:stripe or file:src/app.py"),
    depth: int = typer.Option(2, "--depth"),
    direction: str = typer.Option("both", "--direction", help="both | upstream | downstream"),
    kinds: str = typer.Option(
        "", "--kinds", help="follow only these edge kinds (comma list of declares,calls,touches,uses,emits)"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_trace

    raise typer.Exit(run_map_trace(from_, depth=depth, direction=direction, kinds=kinds, json_out=json_))


@map_app.command("list", help="catalog graph nodes with exact trace-seed ids and source anchors")
def map_list(
    kind: str = typer.Option("", "--kind", help="filter by node kind, e.g. route, page, db_access, file"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_list

    raise typer.Exit(run_map_list(kind=kind, json_out=json_))


@map_app.command("impact", help="both-direction impact map with coverage limits (adjacency, not proof)")
def map_impact(
    node_id: str = typer.Argument(..., metavar="NODE_ID", help="node id, e.g. db_access:USERS or route:GET_/users"),
    depth: int = typer.Option(4, "--depth"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_impact

    raise typer.Exit(run_map_impact(node_id, depth=depth, json_out=json_))


@map_app.command("view", help="build and open the standalone relation-graph view")
def map_view(
    no_open: bool = typer.Option(False, "--no-open"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_view

    raise typer.Exit(run_map_view(open_browser=not no_open, json_out=json_))


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


@app.command(help="public API surface vs a base ref — breaking signature changes and call-site obligations")
def surface(
    base: str = typer.Option("HEAD", "--base", help="git ref to compare against (default HEAD)"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.surface import run_surface

    raise typer.Exit(run_surface(base=base, json_out=json_, quiet=quiet))


@app.command(help="what this session has spent — weighted cost units, raw components, and per-lane attribution")
def budget(
    transcript: str = typer.Option("", "--transcript", help="read this transcript instead of the newest one"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.budget import run_budget

    raise typer.Exit(run_budget(transcript=transcript, json_out=json_, quiet=quiet))


@app.command(help="micro-shape of THIS diff — unit size/nesting, resource lifetime, and cost, ratcheted vs a base")
def craft(
    base: str = typer.Option("HEAD", "--base", help="git ref to compare against (default HEAD)"),
    path: list[str] = typer.Option(None, "--path", help="judge these paths instead of the diff (repeatable)"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.craft import run_craft

    raise typer.Exit(run_craft(base=base, paths=tuple(path or ()), json_out=json_, quiet=quiet))


@app.command(help="hand THIS diff back to you — what changed, and the questions only you can answer")
def tutor(
    words: list[str] = typer.Argument(
        None, help="your answer (--answer) · the false-alarm reason (--dismiss) · the request text (--brief)"
    ),
    base: str = typer.Option("HEAD", "--base", help="git ref to compare against (default HEAD)"),
    path: list[str] = typer.Option(None, "--path", help="review these paths instead of the diff (repeatable)"),
    report: bool = typer.Option(False, "--report", help="also write a markdown review to .asgard/tutor/"),
    out: str = typer.Option("", "--out", help="write the markdown review to this path instead"),
    limit: int = typer.Option(6, "--limit", help="checkpoints shown on screen (the report carries all)"),
    progress: bool = typer.Option(False, "--progress", help="what you have actually taken ownership of, over time"),
    brief: bool = typer.Option(False, "--brief", help="before you start: questions still open where you are headed"),
    text: str = typer.Option("", "--text", help="the request text --brief matches against"),
    answer: str = typer.Option("", "--answer", help="close a question with your answer (checkpoint mark)"),
    dismiss: str = typer.Option("", "--dismiss", help="close a question as a false alarm (checkpoint mark)"),
    note: str = typer.Option("", "--note", help="the answer or the dismissal reason"),
    collect: bool = typer.Option(
        False, "--collect", help="harvest the answers you wrote into the review report (--out picks another file)"
    ),
    record: bool = typer.Option(False, "--record", help="count these questions in the growth record (hooks only)"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.tutor import run_tutor

    # 답은 따옴표 없이 그냥 쓰는 것이 사람이 실제로 치는 방식이다 — `--note` 를 기억해야만
    # 답할 수 있으면 답은 안 온다. 명시 옵션이 있으면 그쪽이 이긴다(스크립트 경로 보존).
    loose = " ".join(words or ()).strip()
    raise typer.Exit(
        run_tutor(
            base=base,
            paths=tuple(path or ()),
            json_out=json_,
            report=report,
            out=out,
            limit=limit,
            quiet=quiet,
            record=record,
            progress=progress,
            brief=brief,
            text=text or loose,
            answer=answer,
            dismiss=dismiss,
            note=note or loose,
            collect=collect,
        )
    )


@app.command(help="backend procedure engine — verb playbooks, the next verb, and the correctness gate")
def thor(
    verb: str = typer.Argument(
        "", help="survey|shape|diagnose|implement|migrate|integrate|harden|scale|sweep|evidence|squad|gate|trail"
    ),
    base: str = typer.Option("HEAD", "--base", help="gate only: git ref to compare against (default HEAD)"),
    path: list[str] = typer.Option(
        None, "--path", help="gate only: judge these paths instead of the diff (repeatable)"
    ),
    note: list[str] = typer.Option(
        None, "--note", help="survey only: record a judgement as key=value (layering|errors|transactions|cleanup)"
    ),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.thor import run_thor

    raise typer.Exit(
        run_thor(verb, base=base, paths=tuple(path or ()), notes=tuple(note or ()), json_out=json_, quiet=quiet)
    )


@app.command(help="codebase erosion signal — size, duplication, coupling, hotspots, and the trend")
def health(
    snapshot: bool = typer.Option(False, "--snapshot", help="record this state so later runs can show a delta"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.health import run_health

    raise typer.Exit(run_health(snapshot=snapshot, json_out=json_, quiet=quiet))


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


@app.command(help="grade text for machine-writing tells in any language (exit 1 = tells found)")
def humanize(
    file: str = typer.Argument(None, help="file to check; omit or '-' to read stdin"),
    lang: str = typer.Option(None, "--lang", help="force a language instead of detecting it"),
    as_json: bool = typer.Option(False, "--json", help="machine-readable findings"),
) -> None:
    from .commands.humanize import run_humanize

    raise typer.Exit(run_humanize(file, lang=lang, as_json=as_json))


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


@memory_app.command("add", help="add a page (rejects on injection scan)")
def memory_add(
    text: str = typer.Argument(..., help="the fact/insight to remember"),
    title: str = typer.Option(None, "--title", help="page title (default: first line)"),
    kind: str = typer.Option("note", "--kind", help="note|user|decision|insight|reference|feedback"),
    links: str = typer.Option("", "--links", help="related slugs, comma-separated"),
) -> None:
    from .commands.memory import run_add

    raise typer.Exit(run_add(text, title, kind, links))


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


@memory_app.command(
    "episodes", help="search raw session transcript segments (derived index, non-authoritative; empty query = stats)"
)
def memory_episodes(
    text: str = typer.Argument("", help="query over past turns of this project"),
    k: int = typer.Option(5, "-k", help="max results"),
    quest: str = typer.Option("", "--quest", help="filter by quest id (alone = list that quest's turns)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_episodes

    raise typer.Exit(run_episodes(text, k, quest, json_))


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


@memory_app.command("provider", help="show or set the provider that curates personal memory")
def memory_provider(
    set_: str = typer.Option(
        "", "--set", help="provider[:model] to curate personal memory (empty --clear restores the main provider)"
    ),
    clear: bool = typer.Option(False, "--clear", help="fall back to the main provider"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_provider

    raise typer.Exit(run_provider(set_, clear, json_))


@memory_app.command("semantic", help="semantic search state (status|on|off|warmup|nudge)")
def memory_semantic(
    action: str = typer.Argument("status", help="status|on|off|warmup|nudge"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_semantic

    raise typer.Exit(run_semantic(action, json_))


@memory_app.command("backup", help="snapshot the canonical wiki (create/list/restore/verify/prune)")
def memory_backup(
    action: str = typer.Argument("create", help="create|list|restore|verify|prune"),
    name: str = typer.Option("", "--name", help="backup name for restore/verify (default: latest)"),
    label: str = typer.Option("", "--label", help="short label appended to the archive name"),
    keep: int = typer.Option(0, "--keep", help="retention count (default 10)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_backup

    raise typer.Exit(run_backup(action, name, label, keep, json_))


@memory_app.command("sync", help="sync the canonical wiki with a shared folder or git remote")
def memory_sync(
    set_remote: str = typer.Option("", "--set-remote", help="persist the sync remote (folder path or git URL)"),
    transport: str = typer.Option("dir", "--transport", help="dir|git — used with --set-remote"),
    branch: str = typer.Option("main", "--branch", help="git branch (git transport only)"),
    unset: bool = typer.Option(False, "--unset", help="forget the configured remote"),
    dry_run: bool = typer.Option(False, "--dry-run", help="print the plan without writing"),
    adopt: bool = typer.Option(False, "--adopt", help="use a non-empty unmarked folder as the remote"),
    status_: bool = typer.Option(False, "--status", help="print remote, last sync, and unresolved conflicts"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_sync

    raise typer.Exit(run_sync(set_remote, transport, branch, unset, dry_run, adopt, status_, json_))


@memory_app.command("norn", help="evolve the wiki — LLM proposes deltas, deterministic code applies (dry-run)")
def memory_norn(
    apply: bool = typer.Option(False, "--apply", help="commit the validated deltas (backup + report)"),
    nudge: bool = typer.Option(False, "--nudge", hidden=True, help="hook surface: one latched line when due"),
    auto: bool = typer.Option(
        False,
        "--auto",
        help="autonomous pass: apply ops the norn_auto tier allows (safe=contradiction; insights stay proposals)",
    ),
    wake: bool = typer.Option(
        False, "--wake", hidden=True, help="hook surface: spawn a detached --auto run when due (tier-gated)"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_norn

    raise typer.Exit(run_norn(apply, nudge, json_, auto, wake))


@memory_app.command("pattern", help="learn patterns about Odin from past turns (dry-run; --apply promotes)")
def memory_pattern(
    apply: bool = typer.Option(False, "--apply", help="promote the validated observations into the wiki"),
    due: bool = typer.Option(False, "--due", hidden=True, help="hook surface: report whether a pass is due"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_pattern

    raise typer.Exit(run_pattern(apply, json_, due))


@memory_app.command("ask", help="answer a question about Odin from personal, episodic, and project memory")
def memory_ask(
    question: str = typer.Argument(..., help="natural-language question about the user"),
    k: int = typer.Option(5, "-k", help="evidence per source"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_ask

    raise typer.Exit(run_ask(question, k, json_))


@memory_app.command("norn-restore", help="restore a page archived by a norn pass")
def memory_norn_restore(slug: str = typer.Argument(...)) -> None:
    from .commands.memory import run_norn_restore

    raise typer.Exit(run_norn_restore(slug))


@memory_app.command("project-reflect", help="LLM-synthesized answer over the project memory bank (advisory)")
def memory_project_reflect(
    question: str = typer.Argument(..., help="the question to reflect on"),
    budget: str = typer.Option("low", "--budget", help="low|mid|high — reflection depth"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_reflect

    raise typer.Exit(run_project_reflect(question, budget, json_))


@memory_app.command("obsidian", help="prepare the wiki as an Obsidian vault (config + maps) and open it")
def memory_obsidian(
    refresh: bool = typer.Option(False, "--refresh", help="prepare the vault and rebuild maps without opening"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_obsidian

    raise typer.Exit(run_obsidian(refresh, json_))


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
    timeout: int = typer.Option(
        None, "--timeout", help="backend request timeout in seconds (slow LLM gateways need more than the 15s default)"
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
            timeout=timeout,
        )
    )


@memory_app.command("project-scan", help="preview important code/docs eligible for project memory")
def memory_project_scan(
    all_files: bool = typer.Option(False, "--all", help="bootstrap scan of all important tracked artifacts"),
    inventory: bool = typer.Option(
        False, "--inventory", help="also list lower-scoring files as digest-tier (header only, full coverage)"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_scan

    raise typer.Exit(run_project_scan(all_files=all_files, json_out=json_, inventory=inventory))


@memory_app.command("project-sync", help="sync approved important code/docs into the selected project-memory backend")
def memory_project_sync(
    all_files: bool = typer.Option(False, "--all", help="bootstrap all important tracked artifacts"),
    inventory: bool = typer.Option(
        False, "--inventory", help="also register lower-scoring files as digest-tier (header only, full coverage)"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="execute the previewed external write"),
    plan_id: str | None = typer.Option(None, "--plan-id", help="SHA-256 plan id emitted by the preview"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_sync

    raise typer.Exit(
        run_project_sync(all_files=all_files, yes=yes, json_out=json_, plan_id=plan_id, inventory=inventory)
    )


@memory_app.command(
    "project-evolve", help="find stale/duplicate/contradictory project records (dry-run; --apply stages approvals)"
)
def memory_project_evolve(
    apply: bool = typer.Option(False, "--apply", help="stage the validated deltas for approval"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_evolve

    raise typer.Exit(run_project_evolve(apply, json_))


@memory_app.command("project-learn", help="configure Hindsight observations and living project mental models")
def memory_project_learn(
    apply: bool = typer.Option(False, "--apply", help="apply learning config and schedule consolidation"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_learn

    raise typer.Exit(run_project_learn(apply, json_))


@memory_app.command("project-ingest", help="parse thrown documents (pdf/docx/hwp/md/…) into project memory")
def memory_project_ingest(
    paths: list[str] = typer.Argument(..., metavar="FILE...", help="documents to ingest"),
    strategy: str = typer.Option("", "--strategy", help="document|record — override the automatic choice"),
    yes: bool = typer.Option(False, "--yes", "-y", help="stage the previewed documents for approval"),
    lane: str = typer.Option(
        "", "--lane", help="graph|local — override the automatic lane (large documents default to local)"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_ingest

    raise typer.Exit(run_project_ingest(paths, strategy, yes, json_, lane))


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


# Asgard Plan — 생각을 PRD·기능 구조·유저 플로우로 정리하는 로컬 표면.
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


@app.command(help="open Asgard Desktop — tasks, artifacts, and settings")
def desktop(
    port: int = typer.Option(8766, "--port", "-p", help="local port (falls back to a free port if taken)"),
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
    browser: bool = typer.Option(False, "--browser", help="use a browser instead of the native Tauri app"),
) -> None:
    """Open the local Asgard Desktop workspace."""
    from .commands.desktop import run_desktop

    raise typer.Exit(run_desktop(port=port, open_browser=not no_open, prefer_native=not browser))


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


@evolve_app.command("curate", help="deterministic learned-skill aging report — stale 30d / archive 90d (dry-run)")
def evolve_curate(
    apply: bool = typer.Option(False, "--apply", help="actually archive 90d-idle candidates (reversible)"),
) -> None:
    from .commands.evolve import run_curate

    raise typer.Exit(run_curate(apply))


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


# Sága — the document lane. `asgard skills run asgard-office -- …` is the agent's
# surface; this is the same engine for a person, with a rendered catalog.
office_app = typer.Typer(help="Sága — build, read, verify, and fill documents", invoke_without_command=True)
app.add_typer(office_app, name="office")


@office_app.callback()
def office_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from .commands.office import run_office_outline

        raise typer.Exit(run_office_outline("", "en", "", False))


@office_app.command("build", help="build a document from a spec (docx | pptx | xlsx)")
def office_build(
    lane: str = typer.Argument(..., metavar="docx|pptx|xlsx"),
    spec: str = typer.Argument(..., metavar="<spec file>"),
    output: str = typer.Option(..., "-o", "--output"),
    template: str = typer.Option("", "--template", help="named template from the Office registry"),
    values: str = typer.Option("", "--values", help="JSON/YAML values for {{placeholders}}"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.office import run_office_build

    raise typer.Exit(run_office_build(lane, spec, output, template, values, json_))


@office_app.command("read", help="read a document back out as Markdown or JSON")
def office_read(
    path: str = typer.Argument(..., metavar="<file>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.office import run_office_read

    raise typer.Exit(run_office_read(path, json_))


@office_app.command("verify", help="static delivery gate — overflow, contrast, placeholders, formulas")
def office_verify(
    path: str = typer.Argument(..., metavar="<file>"),
    strict: bool = typer.Option(False, "--strict", help="fail on warnings as well as errors"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.office import run_office_verify

    raise typer.Exit(run_office_verify(path, strict, json_))


@office_app.command("fill", help="fill {{placeholders}} in a file somebody else designed")
def office_fill(
    path: str = typer.Argument(..., metavar="<file>"),
    values: str = typer.Option("", "--values"),
    output: str = typer.Option("", "-o", "--output"),
    scan: bool = typer.Option(False, "--scan", help="list the placeholders instead of filling them"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.office import run_office_fill

    raise typer.Exit(run_office_fill(path, values, output, scan, json_))


@office_app.command("render", help="PDF and page images, or workbook recalculation (needs LibreOffice)")
def office_render(
    path: str = typer.Argument(None, metavar="<file>"),
    outdir: str = typer.Option("", "-o", "--outdir"),
    probe: bool = typer.Option(False, "--probe", help="report which external tools are available"),
    recalc: bool = typer.Option(False, "--recalc", help="evaluate an .xlsx and cache the results in place"),
) -> None:
    from .commands.office import run_office_render

    raise typer.Exit(run_office_render(path, outdir, probe, recalc))


@office_app.command("outline", help="genre skeletons — 23 document and deck shapes")
def office_outline(
    genre: str = typer.Argument("", metavar="[genre]"),
    language: str = typer.Option("en", "--language", help="en|ko heading language"),
    output: str = typer.Option("", "-o", "--output"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.office import run_office_outline

    raise typer.Exit(run_office_outline(genre, language, output, json_))


@office_app.command(
    "template",
    help="template registry: list | show | new | adopt | check | render",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def office_template(ctx: typer.Context) -> None:
    from .commands.office import run_office_template

    raise typer.Exit(run_office_template(list(ctx.args) or ["list"]))


k6_app = typer.Typer(
    help="asgard-k6 — Docker load testing, and the harness that checks itself", invoke_without_command=True
)
app.add_typer(k6_app, name="k6")


@k6_app.callback()
def k6_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from .commands.k6 import run_k6_doctor

        raise typer.Exit(run_k6_doctor(False))


@k6_app.command("doctor", help="is the lane ready — runner, k6 build, kit, scenarios")
def k6_doctor(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.k6 import run_k6_doctor

    raise typer.Exit(run_k6_doctor(json_))


@k6_app.command("sync", help="materialise the kit into this project's .asgard/k6/ — the volumes docker mounts")
def k6_sync(
    force: bool = typer.Option(False, "--force", help="re-copy even when the kit already matches"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.k6 import run_k6_sync

    raise typer.Exit(run_k6_sync(force, json_))


@k6_app.command("scenarios", help="built-in and project load scenarios")
def k6_scenarios(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.k6 import run_k6_list

    raise typer.Exit(run_k6_list(json_))


@k6_app.command("run", help="run a load scenario and record the verdict (exit 1 = thresholds breached)")
def k6_run(
    scenario: str = typer.Argument(..., metavar="<scenario|path.js>"),
    target: str = typer.Option("", "--target", help="base URL under load"),
    vus: int = typer.Option(0, "--vus", help="peak virtual users"),
    duration: str = typer.Option("", "--duration", help="hold time, e.g. 30s"),
    iterations: int = typer.Option(0, "--iterations", help="fixed request count (shared-iterations scenarios)"),
    p95_max: float = typer.Option(0.0, "--p95-max", help="threshold in ms — the gate this run must clear"),
    env: list[str] = typer.Option(
        [], "--env", "-e", help="KEY=VALUE for the scenario (a bare UPPERCASE key gets the ASGARD_K6_ prefix)"
    ),
    runner: str = typer.Option("", "--runner", help="docker | podman | native"),
    json_: bool = typer.Option(False, "--json"),
    no_record: bool = typer.Option(False, "--no-record", help="do not keep the run under .asgard/k6/runs/"),
) -> None:
    from .commands.k6 import run_k6_run

    raise typer.Exit(
        run_k6_run(scenario, target, vus, duration, iterations, p95_max, list(env), runner, json_, not no_record)
    )


@k6_app.command("selftest", help="does the harness tell the truth — measured against a target whose behavior is known")
def k6_selftest(
    json_: bool = typer.Option(False, "--json"),
    latency_ms: float = typer.Option(80.0, "--latency-ms", help="service time the reference target injects"),
    iterations: int = typer.Option(40, "--iterations"),
    vus: int = typer.Option(4, "--vus"),
) -> None:
    from .commands.k6 import run_k6_selftest

    raise typer.Exit(run_k6_selftest(json_, latency_ms, iterations, vus))


@k6_app.command("report", help="render a recorded run (defaults to the latest)")
def k6_report(
    path: str = typer.Argument("", metavar="[run dir | report.json]"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.k6 import run_k6_report

    raise typer.Exit(run_k6_report(path, json_))


if __name__ == "__main__":
    app()
