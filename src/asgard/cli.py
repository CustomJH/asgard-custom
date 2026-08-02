"""asgard CLI (Python 3.14) — Typer entry. Global flags live on each command (mirrors the TS surface).
Commands delegate to `asgard.commands.*`; templates + guards live in `asgard.templates`."""

import typer

from . import __version__, i18n, ui
from .i18n import t

# 도움말 언어를 여기서 정한다. Typer는 데코레이터를 import 시점에 평가하므로 help=t(...)가
# 읽히는 순간에 언어가 이미 정해져 있어야 하고, 명령 안에서 부르는 load_lang은 그보다 늦다.
# 실패해도 조용히 en으로 남는다 (load_lang이 자체 try/except).
i18n.load_lang()

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
        help="run this as one particular agent — it has its own memory, settings and sessions",
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


agent_app = typer.Typer(help="agents (Einherjar) — keep several on one install, each remembering you separately")
app.add_typer(agent_app, name="agent")
app.add_typer(agent_app, name="einherjar", hidden=True)  # 세계관 별칭 — 같은 앱, 도움말 중복 없음


@agent_app.command("list", help="every agent on this machine — plus the built-in ones not yet raised")
def agent_list(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.agent import run_agent_list

    raise typer.Exit(run_agent_list(json_out=json_, quiet=quiet))


@agent_app.command("show", help="one agent — who it is, how much it remembers, and what it can do")
def agent_show(
    name: str = typer.Argument(..., help="agent id"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.agent import run_agent_show

    raise typer.Exit(run_agent_show(name, json_out=json_, quiet=quiet))


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


@agent_app.command("delete", help="remove an agent — everything it remembered goes with it")
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
    check: bool = typer.Option(False, "--check", help="just run the checks and stop, without opening — for CI"),
    provider: str = typer.Option(
        None,
        "--provider",
        help="use this provider instead: anthropic | claude-native | openai | openai-native | openai_compat | openrouter | ollama | nvidia",
    ),
    model: str = typer.Option(None, "--model", help="use this model instead"),
    cont: bool = typer.Option(
        False, "--continue", "-c", help="pick this project's last conversation back up — the talk, not the state"
    ),
    execution: str = typer.Option(
        None,
        "--execution",
        help="where the work is allowed to run: local | container[-shared] | sandbox[-shared]",
    ),
    sandbox_name: str = typer.Option(None, "--sandbox-name", help="go back into a walled-off workspace you named"),
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


auth_app = typer.Typer(help="the provider logins Asgard holds for you", no_args_is_help=True)
app.add_typer(auth_app, name="auth")


@auth_app.command("login", help="sign in to a subscription provider")
def auth_login(provider: str = typer.Argument("openai-native")) -> None:
    from .commands.auth import run_login

    raise typer.Exit(run_login(provider))


@auth_app.command("status", help="is that subscription login still good")
def auth_status(
    provider: str = typer.Argument("openai-native"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.auth import run_status

    raise typer.Exit(run_status(provider, json_out))


@auth_app.command("logout", help="drop a subscription login Asgard was holding")
def auth_logout(
    provider: str = typer.Argument("openai-native"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.auth import run_logout

    raise typer.Exit(run_logout(provider, json_out))


@app.command(help="get a project ready for coding agents (Claude Code / Cursor / Codex)")
def init(
    cc: bool = typer.Option(False, "--cc", help="lay down the Claude Code (.claude/) skeleton"),
    cursor: bool = typer.Option(False, "--cursor", help="lay down the Cursor (.cursor/) skeleton"),
    codex: bool = typer.Option(False, "--codex", help="lay down the Codex (.codex/) skeleton"),
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
map_app = typer.Typer(
    help="the project map — where things are, what touches what, and the slice an agent gets",
    no_args_is_help=True,
)
app.add_typer(map_app, name="map")


@map_app.command("scan", help="rebuild the relation graph from evidence in the code — no model involved")
def map_scan(
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.map import run_map_scan

    raise typer.Exit(run_map_scan(dry_run=dry_run, json_out=json_, quiet=quiet))


@map_app.command("trace", help="walk outward from one node — what sits next to it, not everything it could reach")
def map_trace(
    from_: str = typer.Option(..., "--from", help="node id, e.g. external_service:stripe or file:src/app.py"),
    depth: int = typer.Option(2, "--depth"),
    direction: str = typer.Option("both", "--direction", help="both | upstream | downstream"),
    kinds: str = typer.Option(
        "", "--kinds", help="follow only these kinds of edge (comma list of declares,calls,touches,uses,emits)"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_trace

    raise typer.Exit(run_map_trace(from_, depth=depth, direction=direction, kinds=kinds, json_out=json_))


@map_app.command("list", help="every node in the graph, with the id to trace from and where it came from")
def map_list(
    kind: str = typer.Option("", "--kind", help="only this kind of node, e.g. route, page, db_access, file"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_list

    raise typer.Exit(run_map_list(kind=kind, json_out=json_))


@map_app.command("why", help=t("hc_map_why"))
def map_why(
    query: str = typer.Argument(..., metavar="QUERY", help=t("hc_map_why_q")),
    limit: int = typer.Option(5, "--limit", help=t("hc_map_why_limit")),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_why

    raise typer.Exit(run_map_why(query, limit=limit, json_out=json_))


@map_app.command("impact", help="what a change here could reach, both directions — near neighbours, not a proof")
def map_impact(
    node_id: str = typer.Argument(..., metavar="NODE_ID", help="node id, e.g. db_access:USERS or route:GET_/users"),
    depth: int = typer.Option(4, "--depth"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_impact

    raise typer.Exit(run_map_impact(node_id, depth=depth, json_out=json_))


# `map view`는 뺐다 — 창을 여는 문은 `asgard open map` 하나다.


@map_app.command("update", help="draw the project map, or redraw it after the repository has moved around")
def map_update(
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.map import run_map_update

    raise typer.Exit(run_map_update(dry_run=dry_run, json_out=json_, quiet=quiet))


# `generate` 별칭 — 첫 생성과 갱신은 한 함수다. 이름이 셋이면(`map generate`·`map update`·`setup map`)
# 사용자는 셋이 서로 다른 일을 한다고 읽는다. 근육기억은 살리고 도움말에서만 뺀다(`upgrade`→`update`와 같은 처리).
map_app.command("generate", hidden=True, help="alias of `map update`")(map_update)


@map_app.command("check", help="how far the map has drifted, and which area maps are broken — writes nothing")
def map_check(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.map import run_map_check

    raise typer.Exit(run_map_check(json_out=json_, quiet=quiet))


@map_app.command("context", help="the slice of the map an agent would actually be handed")
def map_context(
    # `-q`는 `--quiet` 전용이다 — 26개 명령이 그 뜻으로 쓴다. 검색어는 `--query` 긴 이름으로만 받는다
    # (규칙 본체와 예외 목록: tests/test_cli_surface.py).
    query: str = typer.Option("", "--query"),
    refresh: bool = typer.Option(False, "--refresh", help="redraw the managed map first"),
    managed_only: bool = typer.Option(False, "--managed-only", help="leave out the area maps people wrote by hand"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.map import run_map_context

    raise typer.Exit(run_map_context(query, refresh=refresh, managed_only=managed_only, json_out=json_))


@app.command(help="what your public API looks like next to a base ref — what broke, and who has to change")
def surface(
    base: str = typer.Option("HEAD", "--base", help="the git ref to compare against (default HEAD)"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.surface import run_surface

    raise typer.Exit(run_surface(base=base, json_out=json_, quiet=quiet))


@app.command(help="what this session has cost you so far — the total, what makes it up, and which lane spent it")
def budget(
    transcript: str = typer.Option("", "--transcript", help="read this transcript instead of the newest one"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.budget import run_budget

    raise typer.Exit(run_budget(transcript=transcript, json_out=json_, quiet=quiet))


@app.command(help="how THIS change is built up close — how big each unit is, how deep, how long it holds things")
def craft(
    base: str = typer.Option("HEAD", "--base", help="the git ref to compare against (default HEAD)"),
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
    help="the visual surfaces THIS change touches — each Freyja engine judges its own, against a base",
)
def freyja_gate(
    base: str = typer.Option("HEAD", "--base", help="the git ref to compare against (default HEAD)"),
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
    base: str = typer.Option("HEAD", "--base", help="the git ref to compare against (default HEAD)"),
    path: list[str] = typer.Option(None, "--path", help="review these paths instead of the diff (repeatable)"),
    report: bool = typer.Option(False, "--report", help="also write a markdown review to .asgard/tutor/"),
    out: str = typer.Option("", "--out", help="write the markdown review to this path instead"),
    limit: int = typer.Option(6, "--limit", help="how many checkpoints to show on screen (the report carries all)"),
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


@app.command(help="how backend work is done here — the playbook for each verb, what to do next, and the gate")
def thor(
    verb: str = typer.Argument(
        "", help="survey|shape|diagnose|implement|migrate|integrate|harden|scale|sweep|evidence|squad|gate|trail"
    ),
    base: str = typer.Option("HEAD", "--base", help="gate only: the git ref to compare against (default HEAD)"),
    path: list[str] = typer.Option(
        None, "--path", help="gate only: judge these paths instead of the diff (repeatable)"
    ),
    note: list[str] = typer.Option(
        None, "--note", help="survey only: write down a call as key=value (layering|errors|transactions|cleanup)"
    ),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from .commands.thor import run_thor

    raise typer.Exit(
        run_thor(verb, base=base, paths=tuple(path or ()), notes=tuple(note or ()), json_out=json_, quiet=quiet)
    )


@app.command(
    help="how much the codebase has worn down — size, duplication, coupling, hotspots, and which way it is going"
)
def health(
    snapshot: bool = typer.Option(
        False, "--snapshot", help="record where things stand, so later runs can show the change"
    ),
    next_: bool = typer.Option(False, "--next", help="how far off you are, and the next small step to close it"),
    steps: int = typer.Option(1, "--steps", help="how many steps to suggest (--next only)"),
    gate: bool = typer.Option(False, "--gate", help="fail when the two axes that are expensive to undo got worse"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    if gate:
        from .commands.health import run_gate

        raise typer.Exit(run_gate(json_out=json_, quiet=quiet))
    if next_:
        from .commands.health import run_next

        raise typer.Exit(run_next(steps=steps, json_out=json_, quiet=quiet))
    from .commands.health import run_health

    raise typer.Exit(run_health(snapshot=snapshot, json_out=json_, quiet=quiet))


setup_app = typer.Typer(
    help="lay down the Asgard files this project needs, or bring them up to date", no_args_is_help=True
)
app.add_typer(setup_app, name="setup")


@setup_app.command("map", help="draw the project's code map from what the code actually shows, or redraw it")
def setup_map(
    check: bool = typer.Option(False, "--check", help="say how far the structure has drifted, and write nothing"),
    dry_run: bool = typer.Option(False, "--dry-run", help="show whether the managed map would change at all"),
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
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.update import run_update

    raise typer.Exit(run_update([ref] if ref else [], dry_run=dry_run, sync=not no_sync, json_out=json_out))


# `upgrade` 별칭 — 구 TS CLI(asgard-cli)의 근육기억 호환. start 안 /update와 동일 플로우.
app.command("upgrade", hidden=True, help="alias of `update`")(update)


@app.command(help="bring the hooks, agents and skills up to date in every project you have set up")
def sync(
    dry_run: bool = typer.Option(False, "--dry-run"),
    list_: bool = typer.Option(False, "--list", help="just list the registered projects, then stop"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.sync import run_sync

    raise typer.Exit(run_sync(dry_run=dry_run, list_only=list_, json_out=json_out))


@app.command(help="remove asgard (the uv tool only — your ~/.asgard data is kept)")
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    ui.set_quiet(quiet)
    from .commands.uninstall import run_uninstall

    raise typer.Exit(run_uninstall(yes=yes, dry_run=dry_run, json_out=json_out))


@app.command(help="read text back and say where it sounds like a machine wrote it (exit 1 = it does)")
def humanize(
    file: str = typer.Argument(None, help="the file to check; leave it out or pass '-' to read stdin"),
    lang: str = typer.Option(None, "--lang", help="treat it as this language instead of guessing"),
    as_json: bool = typer.Option(False, "--json", help="machine-readable findings"),
) -> None:
    from .commands.humanize import run_humanize

    raise typer.Exit(run_humanize(file, lang=lang, as_json=as_json))


@app.command(help="print or install shell completion (bash|zsh|fish|powershell)")
def completions(
    shell: str = typer.Argument(None, metavar="[bash|zsh|fish|powershell]"),
    install: bool = typer.Option(False, "--install", help="write the script and wire your shell rc"),
) -> None:
    from .commands.completions import run_completions

    raise typer.Exit(run_completions(shell, install=install))


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
    from .commands.role import run_role_list

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
    from .commands.role import run_role_model

    raise typer.Exit(
        run_role_model(host, role, model, effort=effort, provider=provider, reset=reset, json_out=json_out)
    )


@role_app.command("run", help="run one role's turn where it is placed, and write it into the quest log")
def role_run(
    role: str = typer.Argument(..., metavar="<thinker|worker|verifier>"),
    task: str = typer.Argument(..., help="the task and its context (e.g. the Thinker plan a Worker turn works from)"),
    json_out: bool = typer.Option(False, "--json", help="stream to stderr, and print one JSON summary to stdout"),
) -> None:
    from .commands.role import run_role_run

    raise typer.Exit(run_role_run(role, task, json_out))


mode_app = typer.Typer(
    help="see which model, effort, provider and agent each role runs on — and change any of them",
    invoke_without_command=True,
)
app.add_typer(mode_app, name="mode")


@mode_app.callback()
def mode_default(ctx: typer.Context, json_: bool = typer.Option(False, "--json")) -> None:
    if ctx.invoked_subcommand is None:
        from .commands.mode import run_mode

        raise typer.Exit(run_mode(json_out=json_))


@mode_app.command("show", help="what each role in one mode actually ends up with, after everything is layered")
def mode_show(
    mode: str = typer.Argument(..., metavar="<native|claude-code|cursor|codex>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.mode import run_mode_show

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
    from .commands.mode import run_mode_set

    raise typer.Exit(
        run_mode_set(mode, role, agent=agent, model=model, effort=effort, provider=provider, json_out=json_out)
    )


@mode_app.command("reset", help="drop what this project pinned for one mode, or for one role inside it")
def mode_reset(
    mode: str = typer.Argument(..., metavar="<native|claude-code|cursor|codex>"),
    role: str = typer.Argument(None, metavar="[role]"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.mode import run_mode_reset

    raise typer.Exit(run_mode_reset(mode, role, json_out=json_out))


@mode_app.command("pick", help="change one setting by picking from a list instead of typing it out")
def mode_pick() -> None:
    from .commands.mode import run_mode_pick

    raise typer.Exit(run_mode_pick())


# 배차 장부 — 퀘스트가 어떤 모양으로 돌았고, 어느 시도가 몇 번 만에 붙었고, 무엇이 답을
# 기다리는가. 퀘스트 로그(무엇이 검증됐는가)와 다른 축이다.
# 이름은 asgard-helios 의 어휘를 따른다: `orchestration` 은 기제(도메인 패키지)이고
# `siege` 는 사람이 부르는 모드다.
siege_app = typer.Typer(
    help="look inside a siege — what ran, how the tasks hung together, and what the workers asked",
    invoke_without_command=True,
)
app.add_typer(siege_app, name="siege")


@siege_app.callback()
def siege_default(ctx: typer.Context, json_: bool = typer.Option(False, "--json")) -> None:
    if ctx.invoked_subcommand is None:
        from .commands.siege import run_runs

        raise typer.Exit(run_runs(json_out=json_))


@siege_app.command("show", help="one run in full — its tasks, what each waited on, and every attempt")
def siege_show(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.siege import run_show

    raise typer.Exit(run_show(run_id, json_out=json_))


@siege_app.command("inbox", help="the messages one run sent and received — reading them leaves the mail unread")
def siege_inbox(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    limit: int = typer.Option(50, "--limit"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.siege import run_inbox

    raise typer.Exit(run_inbox(run_id, json_out=json_, limit=limit))


@siege_app.command("blocked", help="the worker questions nobody has answered yet")
def siege_blocked(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.siege import run_blocked

    raise typer.Exit(run_blocked(json_out=json_))


@siege_app.command("answer", help="answer a waiting worker question yourself, and let it carry on")
def siege_answer(
    message_id: str = typer.Argument(..., metavar="<message_id>"),
    answer: str = typer.Argument(..., metavar="<answer>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.siege import run_answer

    raise typer.Exit(run_answer(message_id, answer, json_out=json_))


@siege_app.command("reset", help="wipe the siege record — it is all rebuilt from elsewhere, and the quest log stays")
def siege_reset(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.siege import run_reset

    raise typer.Exit(run_reset(json_out=json_))


# Canonical Tool Kernel — inspect the actual role-scoped surfaces used by the
# native loop and generated Claude Code agents.
tools_app = typer.Typer(help="which tools each role is allowed to reach for", no_args_is_help=True)
app.add_typer(tools_app, name="tools")


@tools_app.command("list", help="every tool one role can use, native and Claude Code alike")
def tools_list(
    role: str = typer.Option("worker", "--role", help="thinker|worker|verifier|freyja|thor|eitri|loki|ullr|mimir"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.tools import run_tools_list

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
        from .commands.skills import run_skills_list

        raise typer.Exit(run_skills_list())


@skills_app.command("list", help="the skills that shipped, the ones you installed, and the ones Asgard learned")
def skills_list(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.skills import run_skills_list

    raise typer.Exit(run_skills_list(json_))


@skills_app.command("show", help="print one skill exactly as the agents read it")
def skills_show(
    name: str = typer.Argument(..., metavar="<skill-name>"),
    frontmatter: bool = typer.Option(False, "--frontmatter", help="keep the SKILL.md frontmatter too"),
    resource: str = typer.Option(None, "--resource", help="print a text file bundled alongside the skill"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.skills import run_skills_show

    raise typer.Exit(run_skills_show(name, body_only=not frontmatter, resource=resource, json_out=json_out))


@skills_app.command("resolve", help="what one role would be told to do, given this task")
def skills_resolve(
    task: str = typer.Argument(None, help="the task at hand (read from stdin if you leave it out)"),
    agent: str = typer.Option("worker", "--agent", help="worker|freyja|thor|eitri|mimir"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.skills import run_skills_resolve

    raise typer.Exit(run_skills_resolve(agent, task, json_))


@skills_app.command(
    "run",
    help="run a helper a skill ships with",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def skills_run(ctx: typer.Context, name: str = typer.Argument(..., metavar="<skill-name>")) -> None:
    from .commands.skills import run_skills_run

    raise typer.Exit(run_skills_run(name, list(ctx.args)))


@skills_app.command("assign", help="give one role this skill, in this project")
def skills_assign(
    name: str,
    agent: str = typer.Option(..., "--agent"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.skills import run_skills_assign

    raise typer.Exit(run_skills_assign(name, agent, assigned=True, json_out=json_out))


@skills_app.command("unassign", help="take this skill back off a role, in this project")
def skills_unassign(
    name: str,
    agent: str = typer.Option(..., "--agent"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.skills import run_skills_assign

    raise typer.Exit(run_skills_assign(name, agent, assigned=False, json_out=json_out))


@skills_app.command("enable", help="let this project use a skill again")
def skills_enable(
    name: str,
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.skills import run_skills_enable

    raise typer.Exit(run_skills_enable(name, enabled=True, json_out=json_out))


@skills_app.command("disable", help="keep this project from reaching for a skill")
def skills_disable(
    name: str,
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.skills import run_skills_enable

    raise typer.Exit(run_skills_enable(name, enabled=False, json_out=json_out))


plugins_app = typer.Typer(help="the resource plugins Asgard can draw skills from", invoke_without_command=True)
app.add_typer(plugins_app, name="plugins")


@plugins_app.callback()
def plugins_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from .commands.skills import run_plugins_list

        raise typer.Exit(run_plugins_list())


@plugins_app.command("list", help="the plugins that shipped, and the ones you installed here")
def plugins_list(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.skills import run_plugins_list

    raise typer.Exit(run_plugins_list(json_))


@plugins_app.command("install", help="install a local resource plugin directory")
def plugins_install(
    source: str = typer.Argument(..., metavar="<path>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.skills import run_plugins_install

    raise typer.Exit(run_plugins_install(source, json_out))


# 위그드라실 (Yggdrasil) — 메모리 시스템의 세계관 이름. 개인 메모리 = LLM Wiki (v3 P1).
# 정본 = ~/.asgard/memory의 md, index/state.db는 파생. 커맨드는 기능명 memory 유지 + 세계관 별칭.
# 창은 `asgard open memory`가 연다 — 여기는 기억을 **만지는** 손이다(add·query·lint·…).
memory_app = typer.Typer(
    help="Yggdrasil — what Asgard remembers about you, kept as a wiki you can read and edit",
    no_args_is_help=True,
)
app.add_typer(memory_app, name="memory")
app.add_typer(memory_app, name="yggdrasil", hidden=True)  # 세계관 별칭 — 같은 앱, 도움말 중복 없음


@memory_app.command("add", help="write a new page — text that looks like a planted instruction is turned away")
def memory_add(
    text: str = typer.Argument(..., help="what you want remembered"),
    title: str = typer.Option(None, "--title", help="the page title (default: its first line)"),
    kind: str = typer.Option("note", "--kind", help="note|user|decision|insight|reference|feedback"),
    links: str = typer.Option("", "--links", help="slugs of related pages, comma-separated"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_add

    raise typer.Exit(run_add(text, title, kind, links, json_out))


@memory_app.command("ingest", help="take something in — if a page already says nearly this, it grows instead")
def memory_ingest(
    text: str = typer.Argument(...),
    kind: str = typer.Option("note", "--kind"),
    yes: bool = typer.Option(False, "--yes", "-y", help="save without asking first"),
    plan_id: str = typer.Option(None, "--plan-id", help="carry out the exact plan you already approved"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_ingest

    raise typer.Exit(run_ingest(text, kind, yes, plan_id, json_out))


@memory_app.command("query", help="search the wiki — plain text search, no model, and every hit is counted")
def memory_query(
    text: str = typer.Argument(...),
    # 같은 개념(결과 개수)이 다른 명령에서는 `--limit`이다 — 긴 이름을 정본으로 두고 `-k`는 단축으로 남긴다.
    k: int = typer.Option(5, "--limit", "-k", help="how many results to show"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_query

    raise typer.Exit(run_query(text, k, json_))


@memory_app.command(
    "episodes",
    help="search the raw session transcripts — rebuilt from the logs, so treat it as a lead, not a source. "
    "an empty query gives you the counts instead",
)
def memory_episodes(
    text: str = typer.Argument("", help="what to look for in this project's past turns"),
    k: int = typer.Option(5, "--limit", "-k", help="how many results to show"),
    quest: str = typer.Option("", "--quest", help="only this quest (on its own, lists that quest's turns)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_episodes

    raise typer.Exit(run_episodes(text, k, quest, json_))


@memory_app.command(
    "lint", help="how the wiki is holding up — broken links, pages going stale, duplicates, size, open contradictions"
)
def memory_lint(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.memory import run_lint

    raise typer.Exit(run_lint(json_))


# 모순은 노른이 고치지 않고 사람에게 넘기는 유일한 op 다. 넘길 자리를 두 개 둔다 —
# 목록(무엇끼리 어긋났나)과 표시(봤다). 표시는 해소가 아니라서 이름도 `seen` 이다:
# `resolve`·`fix`로 부르면 사람이 페이지가 고쳐졌다고 읽는데, 페이지는 한 글자도 안 바뀐다.
@memory_app.command("contradictions", help="pages that disagree with each other — you decide, nothing is fixed for you")
def memory_contradictions(
    json_: bool = typer.Option(False, "--json"),
    all_: bool = typer.Option(False, "--all", help="show the pairs you have already marked as seen too"),
) -> None:
    from .commands.memory import run_contradictions

    raise typer.Exit(run_contradictions(json_, all_))


@memory_app.command(
    "contradiction-seen", help="set a contradiction aside — it is not resolved, and neither page changes"
)
def memory_contradiction_seen(
    a: str = typer.Argument(..., help="one page slug from `asgard memory contradictions`"),
    b: str = typer.Argument(..., help="the other page slug (either order works)"),
    note: str = typer.Option("", "--note", help="why you are setting it aside — you will read this next time"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_contradiction_seen

    raise typer.Exit(run_contradiction_seen(a, b, note, json_out))


@memory_app.command("proposals", help="what the agent wants to remember, waiting on your say-so")
def memory_proposals(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.memory import run_proposals

    raise typer.Exit(run_proposals(json_))


@memory_app.command("autosave", help="let memories be saved without coming back to ask you every time")
def memory_autosave(
    state: str = typer.Argument(
        None,
        metavar="[on|off|approve|revoke]",
        help="on/off changes the setting; approve/revoke is what grants this machine project-memory permission",
    ),
    tier: str = typer.Option("both", "--tier", help="personal | project | both"),
    json_: bool = typer.Option(False, "--json"),
    yes: bool = typer.Option(False, "--yes", "-y", help="grant it without asking first"),
) -> None:
    from .commands.memory import run_autosave

    raise typer.Exit(run_autosave(state, tier, json_, yes))


@memory_app.command("approve", help="say yes to a waiting proposal — it goes into the wiki")
def memory_approve(
    proposal_id: str = typer.Argument(..., help="the id shown by `asgard memory proposals`"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_approve

    raise typer.Exit(run_approve(proposal_id, json_))


@memory_app.command("discard", help="throw a waiting proposal away — nothing is written")
def memory_discard(
    proposal_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_discard

    raise typer.Exit(run_discard(proposal_id, json_out))


@memory_app.command("reindex", help="rebuild index.md and state.db from pages/, which is the real record")
def memory_reindex(
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_reindex

    raise typer.Exit(run_reindex(json_out))


@memory_app.command("export-okf", help="write your personal memory out as a read-only OKF v0.1 bundle")
def memory_export_okf(
    destination: str = typer.Argument(..., help="where to write it — a new or empty folder"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_export_okf

    raise typer.Exit(run_export_okf(destination, json_out))


@memory_app.command("show", help="print one page, frontmatter and all")
def memory_show(
    slug: str = typer.Argument(...),
    unsafe: bool = typer.Option(False, "--unsafe", help="open a page held in quarantine, so you can repair it"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_show

    raise typer.Exit(run_show(slug, unsafe=unsafe, json_out=json_out))


@memory_app.command("remove", help="delete a page, and rebuild the index around the gap")
def memory_remove(
    slug: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_remove

    raise typer.Exit(run_remove(slug, json_out))


@memory_app.command("merge", help="fold one page into another — what to do when the wiki has outgrown its budget")
def memory_merge(
    src: str = typer.Argument(..., help="the page to fold in (it is deleted afterwards)"),
    dst: str = typer.Argument(..., help="the page that grows"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_merge

    raise typer.Exit(run_merge(src, dst, json_out))


@memory_app.command("snapshot", help="the memory a new session starts with (nothing, if that is switched off)")
def memory_snapshot(
    provider: str = typer.Option(None, "--provider", help="who is asking — memory is only handed to allowed providers"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_snapshot

    raise typer.Exit(run_snapshot(provider, json_out))


@memory_app.command("recall", help="the memory this question would pull in (nothing, if it is off or nothing matches)")
def memory_recall(
    text: str = typer.Argument(...),
    provider: str = typer.Option(None, "--provider", help="who is asking — memory is only handed to allowed providers"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_recall

    raise typer.Exit(run_recall(text, provider, json_out))


@memory_app.command("sync-turn", help="for hooks: keep one finished turn, read as JSON from stdin", hidden=True)
def memory_sync_turn(
    mode: str = typer.Option(..., "--mode", help="native|claude-code|codex|cursor"),
) -> None:
    from .commands.memory import run_sync_turn

    raise typer.Exit(run_sync_turn(mode))


@memory_app.command("path", help="print or configure the personal memory directory")
def memory_path(
    directory: str = typer.Option(None, "--set", help="keep your personal memory here from now on, everywhere"),
    reset: bool = typer.Option(False, "--reset", help="put it back where it started"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_path

    raise typer.Exit(run_path(directory, reset, json_out))


@memory_app.command("provider", help="which model looks after your personal memory — see it, or change it")
def memory_provider(
    set_: str = typer.Option("", "--set", help="provider[:model] to hand the curating to"),
    clear: bool = typer.Option(False, "--clear", help="go back to using your main provider"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_provider

    raise typer.Exit(run_provider(set_, clear, json_))


@memory_app.command("semantic", help="search by meaning rather than words — where it stands, and how to turn it on")
def memory_semantic(
    action: str = typer.Argument("status", help="status|on|off|warmup|nudge"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_semantic

    raise typer.Exit(run_semantic(action, json_))


@memory_app.command("backup", help="keep copies of the wiki — make one, list them, restore, check, or prune")
def memory_backup(
    action: str = typer.Argument("create", help="create|list|restore|verify|prune"),
    name: str = typer.Option("", "--name", help="which backup to restore or check (default: the newest)"),
    label: str = typer.Option("", "--label", help="a short word to tack onto the archive name"),
    keep: int = typer.Option(0, "--keep", help="how many to keep (default 10)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_backup

    raise typer.Exit(run_backup(action, name, label, keep, json_))


@memory_app.command("sync", help="keep the wiki in step with a shared folder or a git remote")
def memory_sync(
    set_remote: str = typer.Option("", "--set-remote", help="remember this as the remote — a folder path or a git URL"),
    transport: str = typer.Option("dir", "--transport", help="dir|git — goes with --set-remote"),
    branch: str = typer.Option("main", "--branch", help="which git branch (git only)"),
    unset: bool = typer.Option(False, "--unset", help="forget the remote you set"),
    dry_run: bool = typer.Option(False, "--dry-run", help="show what it would do, and write nothing"),
    adopt: bool = typer.Option(False, "--adopt", help="take over a folder that already has things in it"),
    status_: bool = typer.Option(False, "--status", help="the remote, when it last synced, and what is still clashing"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_sync

    raise typer.Exit(run_sync(set_remote, transport, branch, unset, dry_run, adopt, status_, json_))


@memory_app.command("norn", help="let the wiki grow up — a model suggests the edits, plain code makes them. shows only")
def memory_norn(
    apply: bool = typer.Option(False, "--apply", help="actually make the edits that checked out (backs up, reports)"),
    nudge: bool = typer.Option(False, "--nudge", hidden=True, help="for hooks: one line, once, when a pass is due"),
    auto: bool = typer.Option(
        False,
        "--auto",
        help="go on its own, but only as far as the norn_auto tier allows — insights still come to you as proposals",
    ),
    wake: bool = typer.Option(
        False, "--wake", hidden=True, help="for hooks: start a detached --auto run when one is due"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_norn

    raise typer.Exit(run_norn(apply, nudge, json_, auto, wake))


@memory_app.command("pattern", help="notice how Odin works, from past turns. shows only — `--apply` writes it down")
def memory_pattern(
    apply: bool = typer.Option(False, "--apply", help="write the observations that checked out into the wiki"),
    due: bool = typer.Option(False, "--due", hidden=True, help="for hooks: say whether a pass is due"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_pattern

    raise typer.Exit(run_pattern(apply, json_, due))


@memory_app.command("ask", help="ask something about Odin — answered from personal, episodic and project memory")
def memory_ask(
    question: str = typer.Argument(..., help="ask it the way you would out loud"),
    k: int = typer.Option(5, "--limit", "-k", help="how much evidence to pull from each source"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_ask

    raise typer.Exit(run_ask(question, k, json_))


@memory_app.command("norn-restore", help="bring back a page a norn pass filed away")
def memory_norn_restore(
    slug: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_norn_restore

    raise typer.Exit(run_norn_restore(slug, json_out))


@memory_app.command(
    "project-reflect", help="have a model think over everything the project remembers — take it as advice"
)
def memory_project_reflect(
    question: str = typer.Argument(..., help="what to think about"),
    budget: str = typer.Option("low", "--budget", help="low|mid|high — how deeply to think"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_reflect

    raise typer.Exit(run_project_reflect(question, budget, json_))


@memory_app.command("obsidian", help="set the wiki up as an Obsidian vault and open it there")
def memory_obsidian(
    refresh: bool = typer.Option(False, "--refresh", help="set it up and redraw the maps, but do not open it"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_obsidian

    raise typer.Exit(run_obsidian(refresh, json_))


# `memory dashboard`는 뺐다 — 창을 여는 문은 `asgard open memory` 하나다.


@memory_app.command("connect", help="point this project at the memory store your team shares, and set it up")
def memory_connect(
    endpoint: str = typer.Argument(..., help="where the store lives, e.g. http://memory.internal:8888"),
    engine: str = typer.Option("hindsight", "--engine", help="which store — one built in, or one you installed"),
    project_id: str = typer.Option(
        None, "--project-id", "--bank", help="the name this project keeps (default: its name plus a UUID)"
    ),
    option: list[str] = typer.Option([], "--option", "-O", help="a setting for the store, KEY=VALUE. never secrets"),
    claim: bool = typer.Option(False, "--claim", help="take an empty namespace you named yourself"),
    adopt_existing: bool = typer.Option(
        False, "--adopt-existing", help="take over a namespace that already exists — look at it first"
    ),
    timeout: int = typer.Option(
        None, "--timeout", help="how long to wait, in seconds — slow gateways need more than the usual 15"
    ),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
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
            json_out=json_out,
        )
    )


@memory_app.command("project-scan", help="which code and docs are worth putting into project memory — a look first")
def memory_project_scan(
    all_files: bool = typer.Option(False, "--all", help="start from scratch and look at everything tracked"),
    inventory: bool = typer.Option(
        False, "--inventory", help="list the lower-scoring files too, headers only, so nothing is left out"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_scan

    raise typer.Exit(run_project_scan(all_files=all_files, json_out=json_, inventory=inventory))


@memory_app.command("project-sync", help="send the code and docs you approved into the project memory store")
def memory_project_sync(
    all_files: bool = typer.Option(False, "--all", help="start from scratch and send everything tracked"),
    inventory: bool = typer.Option(
        False, "--inventory", help="register the lower-scoring files too, headers only, so nothing is left out"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="go ahead with the write you just previewed"),
    plan_id: str | None = typer.Option(None, "--plan-id", help="the plan id the preview printed"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_sync

    raise typer.Exit(
        run_project_sync(all_files=all_files, yes=yes, json_out=json_, plan_id=plan_id, inventory=inventory)
    )


@memory_app.command(
    "project-evolve",
    help="find project records that have gone stale, doubled up, or started disagreeing. shows only — "
    "`--apply` queues the fixes for your approval",
)
def memory_project_evolve(
    apply: bool = typer.Option(False, "--apply", help="queue the edits that checked out, for you to approve"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_evolve

    raise typer.Exit(run_project_evolve(apply, json_))


@memory_app.command("project-learn", help="set up what Hindsight watches, and the picture it keeps of the project")
def memory_project_learn(
    apply: bool = typer.Option(False, "--apply", help="save the settings and line up the next consolidation"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_learn

    raise typer.Exit(run_project_learn(apply, json_))


@memory_app.command(
    "project-ingest", help="throw documents at it — pdf, docx, hwp, md — and they land in project memory"
)
def memory_project_ingest(
    paths: list[str] = typer.Argument(..., metavar="FILE...", help="the documents to take in"),
    strategy: str = typer.Option("", "--strategy", help="document|record — decide instead of letting it choose"),
    yes: bool = typer.Option(False, "--yes", "-y", help="queue the documents you just previewed, for approval"),
    lane: str = typer.Option(
        "", "--lane", help="graph|local — decide instead of letting it choose (big documents go local)"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_ingest

    raise typer.Exit(run_project_ingest(paths, strategy, yes, json_, lane))


@memory_app.command("project-approve", help="say yes to one waiting project-memory proposal, and write it")
def memory_project_approve(
    approval_id: str = typer.Argument(..., help="the approval id the proposal printed"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.memory import run_project_approve

    raise typer.Exit(run_project_approve(approval_id, json_out))


@memory_app.command("project-rehydrate", help="replay the project records Git holds back into the store")
def memory_project_rehydrate(
    yes: bool = typer.Option(False, "--yes", "-y", help="go ahead with the writes you just previewed"),
    plan_id: str | None = typer.Option(None, "--plan-id", help="the plan id the preview printed"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_rehydrate

    raise typer.Exit(run_project_rehydrate(yes=yes, plan_id=plan_id, json_out=json_))


@memory_app.command("mcp", help="serve the project memory store over MCP — register it once, for your user")
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
ticket_app = typer.Typer(help=t("hc_ticket"), invoke_without_command=True)
app.add_typer(ticket_app, name="ticket")


@ticket_app.callback()
def ticket_default(ctx: typer.Context) -> None:
    """서브커맨드 없이 `asgard ticket`을 치면 지금의 보드를 보여 준다."""
    if ctx.invoked_subcommand is not None:
        return
    from .commands.ticket import run_board

    raise typer.Exit(run_board(json_out=False))


@ticket_app.command("board", help=t("hc_tk_board"))
def ticket_board(
    team: str = typer.Option("", "--team", help=t("hc_tk_team")),
    project: str = typer.Option("", "--project", help=t("hc_tk_project")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_board

    raise typer.Exit(run_board(json_out, team, project))


@ticket_app.command("list", help=t("hc_tk_list"))
def ticket_list(
    status: str = typer.Option("", "--status", "-s", help=t("hc_tk_f_status")),
    assignee: str = typer.Option("", "--assignee", "-a", help=t("hc_tk_f_assignee")),
    label: str = typer.Option("", "--label", "-l", help=t("hc_tk_f_label")),
    # 단축 없는 필터들 — 한 글자가 CLI 전체에서 한 뜻이어야 근육기억이 맞는다. 티켓의 필드
    # 플래그는 이 그룹 안에서만 통하는 이름이라, 다른 데서 이미 쓰는 글자와 부딪히면 물러난다:
    # `-c`는 `start --continue`, `-e`는 `k6 run --env`, `-p`는 `open --port`, `-q`는 `--quiet`.
    # 긴 이름은 그대로다 (규칙 본체와 예외 목록: tests/test_cli_surface.py).
    cycle: str = typer.Option("", "--cycle", help=t("hc_tk_f_cycle")),
    query: str = typer.Option("", "--query", help=t("hc_tk_f_query")),
    open_only: bool = typer.Option(False, "--open", help=t("hc_tk_f_open")),
    team: str = typer.Option("", "--team", help=t("hc_tk_team")),
    project: str = typer.Option("", "--project", help=t("hc_tk_project")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_list

    raise typer.Exit(run_list(status, assignee, label, cycle, query, open_only, json_out, team, project))


@ticket_app.command("new", help=t("hc_tk_new"))
def ticket_new(
    title: str = typer.Argument(..., help=t("hc_tk_title")),
    body: str = typer.Option("", "--body", "-b", help=t("hc_tk_body")),
    status: str = typer.Option("todo", "--status", "-s", help="backlog|todo|in_progress|in_review|done|canceled"),
    priority: int = typer.Option(0, "--priority", help=t("hc_tk_priority")),
    assignee: str = typer.Option("", "--assignee", "-a", help=t("hc_tk_assignee")),
    labels: str = typer.Option("", "--label", "-l", help=t("hc_tk_labels")),
    parent: str = typer.Option("", "--parent", help=t("hc_tk_parent")),
    estimate: int = typer.Option(None, "--estimate", help=t("hc_tk_estimate")),
    team: str = typer.Option("", "--team", help=t("hc_tk_new_team")),
    project: str = typer.Option("", "--project", help=t("hc_tk_new_project")),
    milestone: str = typer.Option("", "--milestone", help=t("hc_tk_ms_opt")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_new

    raise typer.Exit(
        run_new(title, body, status, priority, assignee, labels, parent, estimate, json_out, team, project, milestone)
    )


@ticket_app.command("show", help=t("hc_tk_show"))
def ticket_show(
    ref: str = typer.Argument(..., help=t("hc_tk_ref_full")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_show

    raise typer.Exit(run_show(ref, json_out))


@ticket_app.command("move", help=t("hc_tk_move"))
def ticket_move(
    ref: str = typer.Argument(..., help=t("hc_tk_ref")),
    status: str = typer.Argument(..., help="backlog|todo|in_progress|in_review|done|canceled"),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_move

    raise typer.Exit(run_move(ref, status, json_out))


@ticket_app.command("set", help=t("hc_tk_set"))
def ticket_set(
    ref: str = typer.Argument(..., help=t("hc_tk_ref")),
    title: str = typer.Option("", "--title", "-t"),
    body: str = typer.Option("", "--body", "-b"),
    priority: int = typer.Option(None, "--priority"),
    assignee: str = typer.Option(None, "--assignee", "-a", help=t("hc_tk_set_assignee")),
    labels: str = typer.Option(None, "--label", "-l", help=t("hc_tk_set_labels")),
    estimate: int = typer.Option(None, "--estimate"),
    parent: str = typer.Option(None, "--parent", help=t("hc_tk_set_parent")),
    cycle: str = typer.Option(None, "--cycle", help=t("hc_tk_set_cycle")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_set

    raise typer.Exit(run_set(ref, title, body, priority, assignee, labels, estimate, parent, cycle, json_out))


@ticket_app.command("comment", help=t("hc_tk_comment"))
def ticket_comment(
    ref: str = typer.Argument(..., help=t("hc_tk_ref")),
    text: str = typer.Argument(..., help=t("hc_tk_comment_text")),
    author: str = typer.Option("", "--author", help=t("hc_tk_comment_author")),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.ticket import run_comment

    raise typer.Exit(run_comment(ref, text, author, json_out))


@ticket_app.command("link", help=t("hc_tk_link"))
def ticket_link(
    ref: str = typer.Argument(..., help=t("hc_tk_link_ref")),
    other: str = typer.Argument(..., help=t("hc_tk_link_other")),
    # `-k`는 결과 개수(`--limit`)가 가져갔다 — memory 셋이 그 뜻으로 쓴다.
    kind: str = typer.Option("blocks", "--kind", help="blocks|relates|duplicates"),
    remove: bool = typer.Option(False, "--remove", help=t("hc_tk_link_remove")),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.ticket import run_link

    raise typer.Exit(run_link(ref, other, kind, remove, json_out))


@ticket_app.command("delete", help=t("hc_tk_delete"))
def ticket_delete(
    ref: str = typer.Argument(..., help=t("hc_tk_ref")),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.ticket import run_delete

    raise typer.Exit(run_delete(ref, json_out))


@ticket_app.command("cycle", help=t("hc_tk_cycle"))
def ticket_cycle(
    new: str = typer.Option("", "--new", "-n", help=t("hc_tk_cycle_new")),
    close: str = typer.Option("", "--close", help=t("hc_tk_cycle_close")),
    team: str = typer.Option("", "--team", help=t("hc_tk_cycle_team")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_cycle

    raise typer.Exit(run_cycle(new, close, json_out, team))


@ticket_app.command("team", help=t("hc_tk_team_cmd"))
def ticket_team(
    new: str = typer.Option("", "--new", "-n", help=t("hc_tk_team_new")),
    key: str = typer.Option("", "--key", help=t("hc_tk_team_key")),
    triage: str = typer.Option("", "--triage", help=t("hc_tk_team_triage")),
    cycle_weeks: int = typer.Option(0, "--cycle-weeks", help=t("hc_tk_team_weeks")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_teams

    raise typer.Exit(run_teams(new, key, triage, cycle_weeks, json_out))


@ticket_app.command("project", help=t("hc_tk_project_cmd"))
def ticket_project(
    new: str = typer.Option("", "--new", "-n", help=t("hc_tk_pj_new")),
    show: str = typer.Option("", "--show", help=t("hc_tk_pj_show")),
    status: str = typer.Option("", "--status", "-s", help="backlog|planned|started|paused|completed|canceled|open"),
    lead: str = typer.Option("", "--lead", help=t("hc_tk_pj_lead")),
    target: str = typer.Option("", "--target", help=t("hc_tk_pj_target")),
    teams: str = typer.Option("", "--teams", help=t("hc_tk_pj_teams")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_projects

    raise typer.Exit(run_projects(new, show, status, lead, target, teams, json_out))


@ticket_app.command("milestone", help=t("hc_tk_milestone"))
def ticket_milestone(
    project: str = typer.Argument(..., help=t("hc_tk_project")),
    new: str = typer.Option("", "--new", "-n", help=t("hc_tk_ms_new")),
    target: str = typer.Option("", "--target", help=t("hc_tk_pj_target")),
    done: str = typer.Option("", "--done", help=t("hc_tk_ms_done")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_milestone

    raise typer.Exit(run_milestone(project, new, target, done, json_out))


@ticket_app.command("update", help=t("hc_tk_update"))
def ticket_update(
    project: str = typer.Argument(..., help=t("hc_tk_project")),
    body: str = typer.Option("", "--body", "-b", help=t("hc_tk_update_body")),
    health: str = typer.Option("", "--health", help="on_track|at_risk|off_track"),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_update

    raise typer.Exit(run_update(project, body, health, json_out))


@ticket_app.command("triage", help=t("hc_tk_triage"))
def ticket_triage(
    accept: str = typer.Option("", "--accept", help=t("hc_tk_triage_accept")),
    decline: str = typer.Option("", "--decline", help=t("hc_tk_triage_decline")),
    note: str = typer.Option("", "--note", help=t("hc_tk_triage_note")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.ticket import run_triage

    raise typer.Exit(run_triage(accept, decline, note, json_out))


@ticket_app.command("import", help=t("hc_tk_import"))
def ticket_import(json_out: bool = typer.Option(False, "--json", help=t("hc_json"))) -> None:
    from .commands.ticket import run_import

    raise typer.Exit(run_import(json_out))


# ── 창 — 문은 하나다 ────────────────────────────────────────────────────────────
# 여태 창을 여는 길이 넷이었다: `asgard desktop`, 그리고 `map`·`memory`·`plan`을 서브커맨드
# 없이 치는 것. 앞의 셋은 **운영 커맨드 그룹이기도** 해서, 같은 단어가 문맥에 따라 창을 열거나
# 도움말을 냈다 — `asgard map`이 무엇을 하는지 치기 전에는 알 수 없었다.
#
# 이제 창은 `asgard open <표면>` 하나로만 연다. `asgard map`/`asgard memory`는 도움말을 내고,
# 운영 서브커맨드(scan·trace·add·query…)는 그대로다. 동사가 문 앞에 서면 헷갈릴 것이 없다.
open_app = typer.Typer(help=t("hc_open"), no_args_is_help=True)
app.add_typer(open_app, name="open")


@open_app.command("studio", help=t("hc_open_studio"))
def open_studio(
    port: int = typer.Option(8766, "--port", "-p", help=t("hc_port")),
    no_open: bool = typer.Option(False, "--no-open", help=t("hc_no_browser")),
    browser: bool = typer.Option(False, "--browser", help=t("hc_open_web")),
    view: str = typer.Option("", "--view", help=t("hc_open_view")),
    root: str = typer.Option("", "--root", help=t("hc_open_workspace")),
) -> None:
    """Open Asgard Studio. 프로젝트 안이 아니어도 열린다 — 작업 공간은 창에서 고른다."""
    from .commands.studio import run_studio

    raise typer.Exit(
        run_studio(port=port, open_browser=not no_open, prefer_native=not browser, view=view, root=root or None)
    )


@open_app.command("map", help=t("hc_open_map"))
def open_map(
    no_open: bool = typer.Option(False, "--no-open", help=t("hc_no_browser")),
    json_: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from .commands.map import run_map_view

    raise typer.Exit(run_map_view(open_browser=not no_open, json_out=json_))


@open_app.command("memory", help=t("hc_open_memory"))
def open_memory(
    port: int = typer.Option(8765, "--port", "-p", help=t("hc_port")),
    no_open: bool = typer.Option(False, "--no-open", help=t("hc_no_browser")),
) -> None:
    from .commands.memory_dashboard import run_dashboard

    raise typer.Exit(run_dashboard(port=port, open_browser=not no_open))


# 자가발전 인박스 (CUS-251) — 퀘스트 로그 채굴 → 스킬 후보 → 승인만이 활성화 경로.
evolve_app = typer.Typer(
    help="what Asgard has learned and wants to keep — dig it out of the quest logs, then say yes or no",
    no_args_is_help=True,
)
app.add_typer(evolve_app, name="evolve")


@evolve_app.command(
    "scan", help="dig through the quest logs for lessons that cost something — every FAIL that became a PASS"
)
def evolve_scan(
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_scan

    raise typer.Exit(run_scan(json_out))


@evolve_app.command("nudge", help="for hooks: mention once that there is something new to dig out, then stay quiet")
def evolve_nudge(
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_nudge

    raise typer.Exit(run_nudge(json_out))


@evolve_app.command("list", help="the skill drafts waiting on you — edit the files first if they need it")
def evolve_list(
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_list

    raise typer.Exit(run_list(json_out))


@evolve_app.command("show", help="print one waiting draft, as its SKILL.md stands")
def evolve_show(
    cid: str = typer.Argument(..., metavar="<id>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_show

    raise typer.Exit(run_show(cid, json_out))


@evolve_app.command("approve", help="check a draft over and install it — the next dispatch can reach it, no restart")
def evolve_approve(
    cid: str = typer.Argument(..., metavar="<id>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_approve

    raise typer.Exit(run_approve(cid, json_out))


@evolve_app.command("reject", help="turn a draft down — that same lesson is never brought to you again")
def evolve_reject(
    cid: str = typer.Argument(..., metavar="<id>"),
    reason: str = typer.Option("", "--reason", help="why, if you want to say — it is kept to judge future drafts"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_reject

    raise typer.Exit(run_reject(cid, reason, json_out))


@evolve_app.command(
    "polish", help="have a model rewrite a draft as principles rather than steps — it still waits on you"
)
def evolve_polish(
    cid: str = typer.Argument(..., metavar="<id>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_polish

    raise typer.Exit(run_polish(cid, json_out))


@evolve_app.command("bench", help="run it with a learned skill off, then on, and say whether the skill earns its place")
def evolve_bench(
    skill: str = typer.Argument(..., metavar="<skill-name>"),
    cmd: str = typer.Option(..., "--cmd", help="the command to run — it must print `METRIC <name>=<float>` to stdout"),
    metric: str = typer.Option(..., "--metric", help="which metric to read out of that output"),
    runs: int = typer.Option(5, "--runs", help="how many runs on each side — it needs 3 before it will call it"),
    direction: str = typer.Option("min", "--direction", help="min (lower is better) | max"),
    timeout: int = typer.Option(600, "--timeout", help="how long one run may take, in seconds"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_bench

    raise typer.Exit(run_bench(skill, cmd, metric, runs, direction, timeout, json_out))


@evolve_app.command(
    "curate", help="which learned skills have gone quiet — stale at 30 days, put away at 90. shows only"
)
def evolve_curate(
    apply: bool = typer.Option(False, "--apply", help="actually put away the ones idle 90 days — you can undo it"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_curate

    raise typer.Exit(run_curate(apply, json_out))


@evolve_app.command("archive", help="put a learned skill away without deleting it — you can bring it back")
def evolve_archive(
    name: str = typer.Argument(..., metavar="<skill-name>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_archive

    raise typer.Exit(run_archive(name, json_out))


@evolve_app.command("restore", help="bring a put-away skill back, so it can be reached again")
def evolve_restore(
    name: str = typer.Argument(..., metavar="<skill-name>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.evolve import run_restore

    raise typer.Exit(run_restore(name, json_out))


@app.command(help="put one task through the native Trinity loop with nobody watching — for benches and CI")
def run(
    prompt: str = typer.Argument(None, help="the task to do (leave it out when you pass --resume)"),
    provider: str = typer.Option(None, "--provider", help="use this provider instead"),
    model: str = typer.Option(None, "--model", help="use this model instead"),
    json_: bool = typer.Option(False, "--json", help="stream to stderr, and print one JSON summary to stdout"),
    resume: bool = typer.Option(False, "--resume", help="pick the active Quest back up where it left off"),
    quest: str = typer.Option(None, "--quest", help="pick this particular Quest back up"),
    dual: bool = typer.Option(False, "--dual", help="have thinker and thinker_alt plan side by side"),
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


@office_app.command(
    "verify", help="check it before you send it — text running over, contrast, placeholders left in, formulas"
)
def office_verify(
    path: str = typer.Argument(..., metavar="<file>"),
    strict: bool = typer.Option(False, "--strict", help="let warnings fail it too, not just errors"),
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


@office_app.command("render", help="turn it into a PDF and page images, or work an .xlsx out — needs LibreOffice")
def office_render(
    path: str = typer.Argument(None, metavar="<file>"),
    # `-o`는 같은 그룹의 `--output`(build·fill·outline) 것이다 — 여기만 디렉터리를 받아
    # 뜻이 다르므로 단축을 내준다. 한 글자가 그룹 안에서 파일과 폴더를 오가면 덮어쓴다.
    outdir: str = typer.Option("", "--outdir"),
    probe: bool = typer.Option(False, "--probe", help="say which outside tools are actually here"),
    recalc: bool = typer.Option(False, "--recalc", help="work an .xlsx out and keep the answers in the file"),
    json_: bool = typer.Option(False, "--json", help="print what was produced, and where, as JSON"),
) -> None:
    from .commands.office import run_office_render

    raise typer.Exit(run_office_render(path, outdir, probe, recalc, json_))


@office_app.command("outline", help="skeletons to start from — 23 shapes of document and deck")
def office_outline(
    genre: str = typer.Argument("", metavar="[genre]"),
    language: str = typer.Option("en", "--language", help="en|ko — what language the headings come out in"),
    output: str = typer.Option("", "-o", "--output"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.office import run_office_outline

    raise typer.Exit(run_office_outline(genre, language, output, json_))


@office_app.command(
    "template",
    help="the templates on file — list, show, new, adopt, check, render",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def office_template(
    ctx: typer.Context,
    json_: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from .commands.office import run_office_template

    raise typer.Exit(run_office_template(list(ctx.args) or ["list"], json_))


k6_app = typer.Typer(
    help="asgard-k6 — Docker load testing, and the harness that checks itself", invoke_without_command=True
)
app.add_typer(k6_app, name="k6")


@k6_app.callback()
def k6_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from .commands.k6 import run_k6_doctor

        raise typer.Exit(run_k6_doctor(False))


@k6_app.command("doctor", help="is everything here to run a test — the runner, the k6 build, the kit, the scenarios")
def k6_doctor(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.k6 import run_k6_doctor

    raise typer.Exit(run_k6_doctor(json_))


@k6_app.command("sync", help="lay the kit down in this project's .asgard/k6/ — the folders docker mounts")
def k6_sync(
    force: bool = typer.Option(False, "--force", help="copy it again even if what is there already matches"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.k6 import run_k6_sync

    raise typer.Exit(run_k6_sync(force, json_))


@k6_app.command("scenarios", help="the load scenarios that shipped, and the ones this project wrote")
def k6_scenarios(json_: bool = typer.Option(False, "--json")) -> None:
    from .commands.k6 import run_k6_list

    raise typer.Exit(run_k6_list(json_))


@k6_app.command("run", help="put the target under load and write down how it went (exit 1 = it missed the threshold)")
def k6_run(
    scenario: str = typer.Argument(..., metavar="<scenario|path.js>"),
    target: str = typer.Option("", "--target", help="the base URL to put under load"),
    vus: int = typer.Option(0, "--vus", help="how many virtual users at the peak"),
    duration: str = typer.Option("", "--duration", help="how long to hold there, e.g. 30s"),
    iterations: int = typer.Option(0, "--iterations", help="a fixed number of requests instead (shared-iterations)"),
    p95_max: float = typer.Option(0.0, "--p95-max", help="the p95 this run has to come in under, in ms"),
    env: list[str] = typer.Option(
        [], "--env", "-e", help="KEY=VALUE for the scenario (a bare UPPERCASE key gets the ASGARD_K6_ prefix)"
    ),
    runner: str = typer.Option("", "--runner", help="docker | podman | native"),
    json_: bool = typer.Option(False, "--json"),
    no_record: bool = typer.Option(False, "--no-record", help="do not keep this run under .asgard/k6/runs/"),
) -> None:
    from .commands.k6 import run_k6_run

    raise typer.Exit(
        run_k6_run(scenario, target, vus, duration, iterations, p95_max, list(env), runner, json_, not no_record)
    )


@k6_app.command("selftest", help="does the harness tell the truth — measured against a target we told how to behave")
def k6_selftest(
    json_: bool = typer.Option(False, "--json"),
    latency_ms: float = typer.Option(80.0, "--latency-ms", help="how long the reference target takes on purpose"),
    iterations: int = typer.Option(40, "--iterations"),
    vus: int = typer.Option(4, "--vus"),
) -> None:
    from .commands.k6 import run_k6_selftest

    raise typer.Exit(run_k6_selftest(json_, latency_ms, iterations, vus))


@k6_app.command("report", help="lay out a run you already did (the newest one, unless you name another)")
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
