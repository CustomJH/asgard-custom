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


def _agent(value: str) -> None:
    """--agent를 ASGARD_PROFILE로 옮긴다 — 하위 명령이 무엇이든 그 에이전트로 돈다.

    is_eager라 하위 명령보다 먼저 실행된다. 홈 해석(profiles.home)은 전부 호출 시점이라
    여기서 env를 세우면 이후 모든 경로가 그 에이전트를 가리킨다 (모듈 상수 캐시 없음)."""
    if not value:
        return
    import os

    from .profiles import validate

    try:
        os.environ["ASGARD_PROFILE"] = validate(value)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-v", callback=_version, is_eager=True, help="show version and exit"
    ),
    agent: str = typer.Option(
        "",
        "--agent",
        "-A",
        callback=_agent,
        is_eager=True,
        help="run this command as a specific agent (its own tier-1 memory, settings, sessions)",
    ),
) -> None:
    """Root callback — hosts the global --version / --agent flags.

    여기서 PATH부터 되찾는다. 독에서 띄운 창은 셸을 안 거쳐 사용자 bin 자리를 통째로 잃은 채
    서고, 그러면 `claude`도 `codex`도 없는 기계처럼 보여 **모든 작업이 엔진 없음으로 막힌다**.
    `main()`이 아니라 이 자리인 이유는 문이 하나가 아니기 때문이다 — 콘솔 스크립트가 `app()`을
    직접 부르는 설치본도 있다. 명령이 무엇이든 반드시 지나는 곳은 여기다."""
    from .platform import ensure_user_path

    ensure_user_path()  # 멱등 — 창이 띄우는 자식(`asgard run`)도 이 PATH를 물려받는다


@app.command(help="check the install — runtime, PATH, and project wiring")
def doctor(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.doctor import run_doctor

    raise typer.Exit(run_doctor(json_out=json_, quiet=quiet))


@app.command(help="your own project rules (MANUAL.md) — what is loaded, from where, how big")
def manual(
    show: bool = typer.Option(False, "--show", help="print the exact text the agents receive"),
    section: str = typer.Option("identity", "--section", help="identity | thinker | worker | verifier"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.manual import run_manual

    raise typer.Exit(run_manual(show=show, section=section, json_out=json_, quiet=quiet))


agent_app = typer.Typer(help="agents (Einherjar) — many agents on one install, each with its own tier-1 memory")
app.add_typer(agent_app, name="agent")
app.add_typer(agent_app, name="einherjar", hidden=True)  # 세계관 별칭 — 같은 앱, 도움말 중복 없음


@agent_app.command("list", help="every agent on this machine — plus the built-in ones not yet raised")
def agent_list(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.agent import run_agent_list

    raise typer.Exit(run_agent_list(json_out=json_, quiet=quiet))


@agent_app.command("show", help="one agent — identity, tier-1 memory size, what it can do")
def agent_show(
    name: str = typer.Argument(..., help="agent id"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.agent import run_agent_show

    raise typer.Exit(run_agent_show(name, json_out=json_, quiet=quiet))


@agent_app.command("create", help="raise a new agent — its own home, identity and tier-1 memory")
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
    from .commands.agent import run_agent_create

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
    from .commands.agent import run_agent_use

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
    from .commands.agent import run_agent_describe

    raise typer.Exit(
        run_agent_describe(name, description, can=list(can or []), display=display, json_out=json_, quiet=quiet)
    )


@agent_app.command("delete", help="remove an agent — its tier-1 memory goes with it")
def agent_delete(
    name: str = typer.Argument(..., help="agent id"),
    yes: bool = typer.Option(False, "--yes", help="skip the confirmation"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.agent import run_agent_delete

    raise typer.Exit(run_agent_delete(name, yes=yes, json_out=json_, quiet=quiet))


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
    from .commands.agent import run_agent_bind

    raise typer.Exit(run_agent_bind(name, mode=mode, role=role, json_out=json_, quiet=quiet))


@agent_app.command("unbind", help="drop a placement from this project")
def agent_unbind(
    mode: str = typer.Option(None, "--mode", help="native | claude-code | cursor | codex"),
    role: str = typer.Option(None, "--role", help="thinker | worker | verifier | …"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.agent import run_agent_unbind

    raise typer.Exit(run_agent_unbind(mode=mode, role=role, json_out=json_, quiet=quiet))


@agent_app.command("where", help="who works here, and which declaration won")
def agent_where(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.agent import run_agent_where

    raise typer.Exit(run_agent_where(json_out=json_, quiet=quiet))


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


# 창은 `asgard open map`이 연다 — 여기는 지도를 **만지는** 손이다(scan·trace·impact·context).
# 한 단어가 문맥에 따라 창을 열거나 도움말을 내던 시절의 `invoke_without_command`는 뺐다.
map_app = typer.Typer(help="project map — orientation, relation graph, and bounded context", no_args_is_help=True)
app.add_typer(map_app, name="map")


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


@map_app.command("why", help="왜 이렇게 돼 있나 — 근거를 단 주석·독스트링을 질의로 찾는다 (why is the code like this)")
def map_why(
    query: str = typer.Argument(..., metavar="QUERY", help="무엇의 근거를 찾나, 예: '주입 예산 이유'"),
    limit: int = typer.Option(5, "--limit", help="최대 근거 수"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_why

    raise typer.Exit(run_map_why(query, limit=limit, json_out=json_))


@map_app.command("impact", help="both-direction impact map with coverage limits (adjacency, not proof)")
def map_impact(
    node_id: str = typer.Argument(..., metavar="NODE_ID", help="node id, e.g. db_access:USERS or route:GET_/users"),
    depth: int = typer.Option(4, "--depth"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_impact

    raise typer.Exit(run_map_impact(node_id, depth=depth, json_out=json_))


# `map view`는 뺐다 — 창을 여는 문은 `asgard open map` 하나다.


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
    fix: bool = typer.Option(
        False,
        "--fix",
        help="rewrite the comments whose right wording is already settled, then judge again. this reaches "
        "comments your change never touched, so the files it judges are rewritten on disk",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="with --fix: work out every repair and write nothing"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.craft import run_craft

    raise typer.Exit(
        run_craft(base=base, paths=tuple(path or ()), json_out=json_, quiet=quiet, fix=fix, dry_run=dry_run)
    )


@app.command(
    "freyja-gate",
    help="visual surfaces of THIS diff — judged by each Freyja engine, ratcheted vs a base",
)
def freyja_gate(
    base: str = typer.Option("HEAD", "--base", help="git ref to compare against (default HEAD)"),
    path: list[str] = typer.Option(None, "--path", help="judge these paths instead of the diff (repeatable)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """엔진 이름만 부르고 흐름은 안 도는 실패를 표면에서 잡는다 — 규칙은 각 엔진의 판정기가 갖는다."""
    from .freyja_gate import run_gate

    raise typer.Exit(run_gate(base=base, json_out=json_, paths=tuple(path or ())))


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

    # 답은 따옴표 없이 그냥 쓰는 것이 사람이 실제로 치는 방식이다 — `--note`를 기억해야만
    # 답할 수 있으면 답은 안 온다. 명시 옵션이 있으면 그쪽이 우선한다(스크립트 경로 보존).
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
    next_: bool = typer.Option(False, "--next", help="the control signal — measured error and the next small step"),
    steps: int = typer.Option(1, "--steps", help="how many steps the controller may emit (--next only)"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    if next_:
        from .commands.health import run_next

        raise typer.Exit(run_next(steps=steps, json_out=json_, quiet=quiet))
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


# `upgrade` 별칭 — 구 TS CLI(asgard-cli)의 근육기억 호환. start 안 /update와 동일 플로우.
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


# Trinity 역할 브릿지 — 호스트 도구(Claude Code/Codex/Cursor)가 [trinity.<role>] 배치 provider로
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
# 정본 = ~/.asgard/memory의 md, index/state.db는 파생. 커맨드는 기능명 memory 유지 + 세계관 별칭.
# 창은 `asgard open memory`가 연다 — 여기는 기억을 **만지는** 손이다(add·query·lint·…).
memory_app = typer.Typer(help="Yggdrasil — personal memory · LLM wiki (ingest/query/lint)", no_args_is_help=True)
app.add_typer(memory_app, name="memory")
app.add_typer(memory_app, name="yggdrasil", hidden=True)  # 세계관 별칭 — 같은 앱, 도움말 중복 없음


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


@memory_app.command("lint", help="wiki health — dead links, decay candidates, duplicates, budget, open contradictions")
def memory_lint(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.memory import run_lint

    raise typer.Exit(run_lint(json_))


# 모순은 노른이 고치지 않고 사람에게 넘기는 유일한 op 다. 넘길 자리를 두 개 둔다 —
# 목록(무엇끼리 어긋났나)과 표시(봤다). 표시는 해소가 아니라서 이름도 `seen` 이다:
# `resolve`·`fix`로 부르면 사람이 페이지가 고쳐졌다고 읽는데, 페이지는 한 글자도 안 바뀐다.
@memory_app.command("contradictions", help="pages that contradict each other — a human decides, nothing is auto-fixed")
def memory_contradictions(
    json_: bool = typer.Option(False, "--json"),
    all_: bool = typer.Option(False, "--all", help="include pairs already marked as seen"),
) -> None:
    from .commands.memory import run_contradictions

    raise typer.Exit(run_contradictions(json_, all_))


@memory_app.command(
    "contradiction-seen", help="mark a contradiction as seen — this does NOT resolve it; both pages stay unchanged"
)
def memory_contradiction_seen(
    a: str = typer.Argument(..., help="one page slug from `asgard memory contradictions`"),
    b: str = typer.Argument(..., help="the other page slug (order does not matter)"),
    note: str = typer.Option("", "--note", help="why you are setting it aside (kept for your next read)"),
) -> None:
    from .commands.memory import run_contradiction_seen

    raise typer.Exit(run_contradiction_seen(a, b, note))


@memory_app.command("proposals", help="pending memory proposals the agent staged for your approval")
def memory_proposals(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.memory import run_proposals

    raise typer.Exit(run_proposals(json_))


@memory_app.command("autosave", help="save memories without the approval round-trip (tier-1 and/or tier-2)")
def memory_autosave(
    state: str = typer.Argument(
        None,
        metavar="[on|off|approve|revoke]",
        help="on/off writes the setting; approve/revoke grants this machine's tier-2 permission",
    ),
    tier: str = typer.Option("both", "--tier", help="personal (tier-1) | project (tier-2) | both"),
    json_: bool = typer.Option(False, "--json"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip the approve confirmation prompt"),
) -> None:
    from .commands.memory import run_autosave

    raise typer.Exit(run_autosave(state, tier, json_, yes))


@memory_app.command("approve", help="approve a staged memory proposal (writes it to the wiki)")
def memory_approve(
    proposal_id: str = typer.Argument(..., help="proposal id from `asgard memory proposals`"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_approve

    raise typer.Exit(run_approve(proposal_id, json_))


@memory_app.command("discard", help="discard a staged memory proposal without writing it")
def memory_discard(proposal_id: str = typer.Argument(...)) -> None:
    from .commands.memory import run_discard

    raise typer.Exit(run_discard(proposal_id))


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


# `memory dashboard`는 뺐다 — 창을 여는 문은 `asgard open memory` 하나다.


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


# 기획에는 CLI 문이 없다 — **스튜디오 안에서만** 쓴다.
#
# 여태 `asgard plan`은 스튜디오를 `?view=plan`으로 열어 주는 별도 명령이었다. 같은 창을 두
# 이름으로 부르는 셈이라, 기획이 어디에 사는지가 흐려졌다: 창 안의 목적지인가, 독립 도구인가.
# 기획은 앞뒤 문서가 서로를 물고(PRD → 기능명세 → 유저플로우) 티켓·작업과 같은 워크스페이스를
# 쓴다 — 그 맥락은 스튜디오 안에 있을 때만 온전하다. 그래서 문을 하나로 줄였다:
#   `asgard open studio` 의 **기획** 목적지 (딥링크가 필요하면 `--view plan`)
# API(`commands.plan_api`)는 남는다. 그건 창이 쓰는 계약이지 사람이 치는 명령이 아니다.


# 업무 — Studio 보드와 같은 저장소를 창 없이 만지는 손 (<에이전트 홈>/studio/workspace.db).
ticket_app = typer.Typer(
    help="Asgard 업무 보드 — 티켓 발급·이동·연결 (Studio 창과 같은 저장소)",
    invoke_without_command=True,
)
app.add_typer(ticket_app, name="ticket")


@ticket_app.callback()
def ticket_default(ctx: typer.Context) -> None:
    """서브커맨드 없이 `asgard ticket`을 치면 지금의 보드를 보여 준다."""
    if ctx.invoked_subcommand is not None:
        return
    from .commands.ticket import run_board

    raise typer.Exit(run_board(json_out=False))


@ticket_app.command("board", help="상태 칸으로 접은 지금의 보드")
def ticket_board(
    team: str = typer.Option("", "--team", help="팀 키로 좁힌다 — `.`은 이 폴더의 팀 (기본: 워크스페이스 전체)"),
    project: str = typer.Option("", "--project", help="프로젝트 이름 또는 id"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_board

    raise typer.Exit(run_board(json_out, team, project))


@ticket_app.command("list", help="티켓 목록 — 우선순위 순 (긴급이 먼저, '없음'이 맨 뒤)")
def ticket_list(
    status: str = typer.Option("", "--status", "-s", help="상태로 거르기 (쉼표로 여럿)"),
    assignee: str = typer.Option("", "--assignee", "-a", help="담당으로 거르기"),
    label: str = typer.Option("", "--label", "-l", help="라벨로 거르기"),
    cycle: str = typer.Option("", "--cycle", "-c", help="주기 번호 또는 이름"),
    query: str = typer.Option("", "--query", "-q", help="제목·설명·번호 부분 일치"),
    open_only: bool = typer.Option(False, "--open", help="완료·취소를 뺀 것만"),
    team: str = typer.Option("", "--team", help="팀 키로 좁힌다 — `.`은 이 폴더의 팀 (기본: 워크스페이스 전체)"),
    project: str = typer.Option("", "--project", help="프로젝트 이름 또는 id"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_list

    raise typer.Exit(run_list(status, assignee, label, cycle, query, open_only, json_out, team, project))


@ticket_app.command("new", help="티켓 발급 — 번호는 한 번만 나오고 다시 쓰이지 않는다")
def ticket_new(
    title: str = typer.Argument(..., help="무엇을 끝내면 되는지 (주제가 아니라 결과로)"),
    body: str = typer.Option("", "--body", "-b", help="맥락·재현·수용 기준"),
    status: str = typer.Option("todo", "--status", "-s", help="backlog|todo|in_progress|in_review|done|canceled"),
    priority: int = typer.Option(0, "--priority", "-p", help="1 긴급 · 2 높음 · 3 보통 · 4 낮음 · 0 없음"),
    assignee: str = typer.Option("", "--assignee", "-a", help="담당"),
    labels: str = typer.Option("", "--label", "-l", help="라벨 (쉼표로 여럿)"),
    parent: str = typer.Option("", "--parent", help="상위 티켓 — 한 겹까지"),
    estimate: int = typer.Option(None, "--estimate", "-e", help="추정 포인트"),
    team: str = typer.Option("", "--team", help="이 팀에 끊는다 (기본: 결속된 폴더면 그 팀, 아니면 기본 팀)"),
    project: str = typer.Option("", "--project", help="프로젝트에 붙인다 — 팀을 가로지른다"),
    milestone: str = typer.Option("", "--milestone", help="프로젝트 안의 마일스톤"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_new

    raise typer.Exit(
        run_new(title, body, status, priority, assignee, labels, parent, estimate, json_out, team, project, milestone)
    )


@ticket_app.command("show", help="티켓 한 건 — 본문·하위·관계·댓글·활동")
def ticket_show(
    ref: str = typer.Argument(..., help="번호(PRJ-12), 숫자(12), 또는 id"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_show

    raise typer.Exit(run_show(ref, json_out))


@ticket_app.command("move", help="상태를 옮긴다 — 시작·완료 시각이 함께 기록된다")
def ticket_move(
    ref: str = typer.Argument(..., help="번호 또는 id"),
    status: str = typer.Argument(..., help="backlog|todo|in_progress|in_review|done|canceled"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_move

    raise typer.Exit(run_move(ref, status, json_out))


@ticket_app.command("set", help="준 칸만 바꾼다 — 안 준 칸은 그대로 둔다")
def ticket_set(
    ref: str = typer.Argument(..., help="번호 또는 id"),
    title: str = typer.Option("", "--title", "-t"),
    body: str = typer.Option("", "--body", "-b"),
    priority: int = typer.Option(None, "--priority", "-p"),
    assignee: str = typer.Option(None, "--assignee", "-a", help="빈 문자열이면 담당을 뗀다"),
    labels: str = typer.Option(None, "--label", "-l", help="쉼표로 여럿 — 통째로 갈아 끼운다"),
    estimate: int = typer.Option(None, "--estimate", "-e"),
    parent: str = typer.Option(None, "--parent", help="빈 문자열이면 상위에서 뗀다"),
    cycle: str = typer.Option(None, "--cycle", "-c", help="빈 문자열이면 주기에서 뺀다"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_set

    raise typer.Exit(run_set(ref, title, body, priority, assignee, labels, estimate, parent, cycle, json_out))


@ticket_app.command("comment", help="티켓에 한 줄 남긴다")
def ticket_comment(
    ref: str = typer.Argument(..., help="번호 또는 id"),
    text: str = typer.Argument(..., help="남길 말"),
    author: str = typer.Option("", "--author", help="글쓴이 (기본 cli)"),
) -> None:
    from .commands.ticket import run_comment

    raise typer.Exit(run_comment(ref, text, author))


@ticket_app.command("link", help="티켓을 잇는다 — blocks는 방향이 있다 (ref가 other를 막는다)")
def ticket_link(
    ref: str = typer.Argument(..., help="막는 쪽"),
    other: str = typer.Argument(..., help="막히는 쪽"),
    kind: str = typer.Option("blocks", "--kind", "-k", help="blocks|relates|duplicates"),
    remove: bool = typer.Option(False, "--remove", help="잇지 말고 끊는다"),
) -> None:
    from .commands.ticket import run_link

    raise typer.Exit(run_link(ref, other, kind, remove))


@ticket_app.command("delete", help="티켓을 지운다 — 번호는 다시 발급되지 않는다")
def ticket_delete(ref: str = typer.Argument(..., help="번호 또는 id")) -> None:
    from .commands.ticket import run_delete

    raise typer.Exit(run_delete(ref))


@ticket_app.command("cycle", help="주기(사이클) — 목록·신설·마감. 닫으면 안 끝난 일감이 다음 주기로 넘어간다")
def ticket_cycle(
    new: str = typer.Option("", "--new", "-n", help="이 이름으로 새 주기를 연다"),
    close: str = typer.Option("", "--close", help="이 번호/이름의 주기를 닫는다"),
    team: str = typer.Option("", "--team", help="어느 팀의 주기인가 (기본: 결속된 폴더면 그 팀, 아니면 기본 팀)"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_cycle

    raise typer.Exit(run_cycle(new, close, json_out, team))


@ticket_app.command("team", help="팀 — 번호의 주인, 워크플로·사이클·트리아지의 단위")
def ticket_team(
    new: str = typer.Option("", "--new", "-n", help="이 이름으로 팀을 세운다"),
    key: str = typer.Option("", "--key", help="번호 앞자리 (기본: 이름에서 뽑는다)"),
    triage: str = typer.Option("", "--triage", help="on|off — 밖에서 들어온 일감을 인박스에 세운다"),
    cycle_weeks: int = typer.Option(0, "--cycle-weeks", help="사이클 길이(주)"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_teams

    raise typer.Exit(run_teams(new, key, triage, cycle_weeks, json_out))


@ticket_app.command("project", help="프로젝트 — 끝이 있는 일. 팀을 가로지른다")
def ticket_project(
    new: str = typer.Option("", "--new", "-n", help="이 이름으로 프로젝트를 연다"),
    show: str = typer.Option("", "--show", help="이 프로젝트의 상세 (마일스톤·진척·보고)"),
    status: str = typer.Option("", "--status", "-s", help="backlog|planned|started|paused|completed|canceled|open"),
    lead: str = typer.Option("", "--lead", help="리드 한 사람 — 책임이 갈리지 않게"),
    target: str = typer.Option("", "--target", help="목표일 YYYY-MM-DD"),
    teams: str = typer.Option("", "--teams", help="참여 팀 키 (쉼표로 여럿)"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_projects

    raise typer.Exit(run_projects(new, show, status, lead, target, teams, json_out))


@ticket_app.command("milestone", help="프로젝트 안의 마일스톤 — 목록·신설·완료")
def ticket_milestone(
    project: str = typer.Argument(..., help="프로젝트 이름 또는 id"),
    new: str = typer.Option("", "--new", "-n", help="이 이름으로 마일스톤을 만든다"),
    target: str = typer.Option("", "--target", help="목표일 YYYY-MM-DD"),
    done: str = typer.Option("", "--done", help="이 마일스톤을 완료로 표시한다"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_milestone

    raise typer.Exit(run_milestone(project, new, target, done, json_out))


@ticket_app.command("update", help="프로젝트 진행 보고 — 건강도는 사람이 적는다")
def ticket_update(
    project: str = typer.Argument(..., help="프로젝트 이름 또는 id"),
    body: str = typer.Option("", "--body", "-b", help="이번에 무엇이 됐고 무엇이 남았는지"),
    health: str = typer.Option("", "--health", help="on_track|at_risk|off_track"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_update

    raise typer.Exit(run_update(project, body, health, json_out))


@ticket_app.command("triage", help="팀의 인박스 — 아직 받아들이지 않은 일감")
def ticket_triage(
    accept: str = typer.Option("", "--accept", help="이 번호를 받아들여 보드로 넣는다"),
    decline: str = typer.Option("", "--decline", help="이 번호를 거절한다 (취소로 닫고 이유를 남긴다)"),
    note: str = typer.Option("", "--note", help="받거나 거절하며 남길 한 줄"),
    json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.ticket import run_triage

    raise typer.Exit(run_triage(accept, decline, note, json_out))


@ticket_app.command("import", help="폴더마다 보드가 하나이던 시절의 저장소를 워크스페이스로 들여온다")
def ticket_import(json_out: bool = typer.Option(False, "--json", help="기계가 읽을 형태로")) -> None:
    from .commands.ticket import run_import

    raise typer.Exit(run_import(json_out))


# ── 창 — 문은 하나다 ────────────────────────────────────────────────────────────
# 여태 창을 여는 길이 넷이었다: `asgard desktop`, 그리고 `map`·`memory`·`plan`을 서브커맨드
# 없이 치는 것. 앞의 셋은 **운영 커맨드 그룹이기도** 해서, 같은 단어가 문맥에 따라 창을 열거나
# 도움말을 냈다 — `asgard map`이 무엇을 하는지 치기 전에는 알 수 없었다.
#
# 이제 창은 `asgard open <표면>` 하나로만 연다. `asgard map`/`asgard memory`는 도움말을 내고,
# 운영 서브커맨드(scan·trace·add·query…)는 그대로다. 동사가 문 앞에 서면 헷갈릴 것이 없다.
open_app = typer.Typer(help="open a local Asgard window — studio · map · memory", no_args_is_help=True)
app.add_typer(open_app, name="open")


@open_app.command("studio", help="Asgard Studio — 작업·업무·기획·산출물·스킬·설정")
def open_studio(
    port: int = typer.Option(8766, "--port", "-p", help="local port (falls back to a free port if taken)"),
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
    browser: bool = typer.Option(False, "--browser", help="use a browser instead of the native Tauri app"),
    view: str = typer.Option("", "--view", help="바로 들어갈 화면 (tickets|plan|projects|artifacts|plugins|settings)"),
    root: str = typer.Option(
        "", "--root", help="작업 공간을 정해서 연다 (기본: 여기가 프로젝트면 여기, 아니면 최근 프로젝트)"
    ),
) -> None:
    """Open Asgard Studio. 프로젝트 안이 아니어도 열린다 — 작업 공간은 창에서 고른다."""
    from .commands.studio import run_studio

    raise typer.Exit(
        run_studio(port=port, open_browser=not no_open, prefer_native=not browser, view=view, root=root or None)
    )


@open_app.command("map", help="관계 그래프 뷰 — 코드가 무엇에 닿는지")
def open_map(
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
    json_: bool = typer.Option(False, "--json", help="기계가 읽을 형태로"),
) -> None:
    from .commands.map import run_map_view

    raise typer.Exit(run_map_view(open_browser=not no_open, json_out=json_))


@open_app.command("memory", help="위그드라실 대시보드 — 개인 메모리 위키 (읽기 전용)")
def open_memory(
    port: int = typer.Option(8765, "--port", "-p", help="local port (falls back to a free port if taken)"),
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser automatically"),
) -> None:
    from .commands.memory_dashboard import run_dashboard

    raise typer.Exit(run_dashboard(port=port, open_browser=not no_open))


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


def main() -> None:
    """터미널의 마지막 방어선 — 아스가르드가 아는 실패는 트레이스백으로 새지 않는다.

    Typer는 명령이 던진 예외를 그대로 위로 올린다. 그래서 여태 `StoreError` 하나가
    사용자 터미널에 40줄짜리 파이썬 스택으로 떨어졌다 — 사용자가 고칠 수 있는 잘못이었는데도
    화면은 "우리가 깨졌다"고 말한 셈이다. 여기서 아는 실패만 골라 사유 한 줄과 처방 한 줄로
    닫고, 그 예외가 정한 종료 코드로 끝낸다.

    **모르는 예외는 그대로 둔다.** 전부 삼키면 진짜 버그의 스택이 사라지고, 그건 진단을
    없애는 것이지 오류 처리가 아니다."""
    import sys

    from . import errors

    # PATH 되찾기는 `_main` 콜백이 진다 — 이 문으로 안 들어오는 설치본도 있어서다.
    try:
        app()
    except errors.AsgardError as exc:
        errors.render_cli(exc)
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        # Ctrl-C는 사고가 아니다 — 스택을 뱉지 않고 관례대로 130으로 닫는다.
        sys.stderr.write("\n")
        sys.exit(130)


if __name__ == "__main__":
    main()
