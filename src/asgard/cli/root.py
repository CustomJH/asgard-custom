"""asgard CLI — 최상위 명령. 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer
import typer.core

from .. import ui
from ._app import app


@app.command(help="check the install — runtime, PATH, and project wiring")
def doctor(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.doctor import run_doctor

    raise typer.Exit(run_doctor(json_out=json_, quiet=quiet))


@app.command(help="your own project rules (MANUAL.md) — what is loaded, from where, how big")
def manual(
    show: bool = typer.Option(False, "--show", help="print the exact text the agents receive"),
    section: str = typer.Option("identity", "--section", help="identity | thinker | worker | verifier"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.manual import run_manual

    raise typer.Exit(run_manual(show=show, section=section, json_out=json_, quiet=quiet))


class _StartCommand(typer.core.TyperCommand):
    """값 없는 --agent를 같은 명령의 선택 플래그로 판정해요."""

    def parse_args(self, ctx, args):
        values = list(args)
        for index, value in enumerate(values):
            if value == "--agent" and (index + 1 == len(values) or values[index + 1].startswith("-")):
                values[index] = "--agents"
        return super().parse_args(ctx, values)


@app.command(cls=_StartCommand, help="open the Asgard terminal (Heimdall) — chat, connect a provider, run tasks")
def start(
    check: bool = typer.Option(False, "--check", help="just run the checks and stop, without opening — for CI"),
    agent: str = typer.Option(None, "--agent", help="agent to start as; overrides the global --agent option"),
    agents: bool = typer.Option(False, "--agents", help="pick from configured and built-in agents"),
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
    from ..commands.agent import select_agent
    from ..commands.start import run_start

    selected = (
        select_agent(
            agent,
            title="시작할 에이전트를 골라요",
            retry="`asgard start --agent <이름>`으로 이름을 대고 다시 부르세요",
        )
        if agent is not None or agents
        else None
    )
    raise typer.Exit(
        run_start(
            check_only=check,
            agent=selected,
            provider=provider,
            model=model,
            cont=cont,
            execution=execution,
            sandbox_name=sandbox_name,
        )
    )


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
    from ..commands.setup import run_init

    raise typer.Exit(
        run_init(cc=cc, cursor=cursor, codex=codex, profile=profile, force=force, dry_run=dry_run, yes=yes, lagom=lagom)
    )


@app.command(help="what your public API looks like next to a base ref — what broke, and who has to change")
def surface(
    base: str = typer.Option("HEAD", "--base", help="the git ref to compare against (default HEAD)"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.surface import run_surface

    raise typer.Exit(run_surface(base=base, json_out=json_, quiet=quiet))


@app.command(help="what this session has cost you so far — the total, what makes it up, and which lane spent it")
def budget(
    transcript: str = typer.Option("", "--transcript", help="read this transcript instead of the newest one"),
    set_: list[str] = typer.Option(
        None,
        "--set",
        help="raise or lower one limit, e.g. --set session_cost_units=60000000 (repeatable)",
        metavar="KEY=VALUE",
    ),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.budget import run_budget, run_budget_set

    if set_:
        raise typer.Exit(run_budget_set(list(set_), json_out=json_))
    raise typer.Exit(run_budget(transcript=transcript, json_out=json_, quiet=quiet))


@app.command(
    help="the four Trinity settings this repository owns — which command is its baseline, and how long it may take"
)
def trinity(
    set_: list[str] = typer.Option(
        None,
        "--set",
        help="baseline_checks=<command> (repeatable) · baseline_timeout=<seconds> · baseline_parallel=true|false · verify_level=low|high|full",
        metavar="KEY=VALUE",
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    import json
    import os

    from ..commands.setup import run_policy_set

    if not set_:
        from ..commands.setup import PROJECT_OWNED_POLICY_KEYS
        from ..settings import load_project

        policy = load_project(os.getcwd()).get("trinity_policy")
        current = {k: (policy or {}).get(k) for k in PROJECT_OWNED_POLICY_KEYS} if isinstance(policy, dict) else {}
        print(json.dumps(current, ensure_ascii=False, indent=2))
        raise typer.Exit(0)
    raise typer.Exit(run_policy_set(list(set_), json_out=json_))


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
    from ..commands.craft import run_craft

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
    from ..freyja_gate import run_gate

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
    recap: bool = typer.Option(
        False, "--recap", help="the story of this session: what you did, what stayed unanswered"
    ),
    span: str = typer.Option("session", "--span", help="how wide --recap looks back: session · day · week"),
    debt: bool = typer.Option(False, "--debt", help="where you are accepting without reading — the surrender signals"),
    tip: bool = typer.Option(False, "--tip", help="one mid-work nudge, or nothing (hooks only)"),
    expect: bool = typer.Option(
        False, "--expect", help="before the agent runs: write what you think the answer looks like"
    ),
    settle: str = typer.Option("", "--settle", help="close an expectation against what actually landed (its mark)"),
    explain: bool = typer.Option(
        False, "--explain", help="how to read this change: the order, the words it uses, what to run"
    ),
    depth: str = typer.Option("", "--depth", help="how much --explain spells out: first · familiar · owned"),
    mission: bool = typer.Option(
        False, "--mission", help="what you are heading toward (write one, or call it bare to see it)"
    ),
    quiz: bool = typer.Option(
        False, "--quiz", help="ask instead of explain: put the questions back and wait for --answer"
    ),
    sid: str = typer.Option("", "--sid", help="the session this belongs to (hooks pass it; scopes --tip and --recap)"),
    text: str = typer.Option("", "--text", help="the request text --brief matches against"),
    answer: str = typer.Option("", "--answer", help="close a question with your answer (checkpoint mark)"),
    dismiss: str = typer.Option(
        "", "--dismiss", help="close questions as false alarms: a checkpoint mark, a file path, or 'all'"
    ),
    note: str = typer.Option("", "--note", help="the answer or the dismissal reason"),
    collect: bool = typer.Option(
        False, "--collect", help="harvest the answers you wrote into the review report (--out picks another file)"
    ),
    record: bool = typer.Option(False, "--record", help="count these questions in the growth record (hooks only)"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.tutor import run_tutor

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
            recap=recap,
            span=span,
            debt=debt,
            tip=tip,
            expect=expect,
            settle=settle,
            sid=sid,
            explain=explain,
            depth=depth,
            mission=mission,
            quiz=quiz,
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
    from ..commands.thor import run_thor

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
        from ..commands.health import run_gate

        raise typer.Exit(run_gate(json_out=json_, quiet=quiet))
    if next_:
        from ..commands.health import run_next

        raise typer.Exit(run_next(steps=steps, json_out=json_, quiet=quiet))
    from ..commands.health import run_health

    raise typer.Exit(run_health(snapshot=snapshot, json_out=json_, quiet=quiet))


@app.command(help="update asgard to the latest release, or pin a version: update vX.Y.Z")
def update(
    ref: str = typer.Argument(None, metavar="[version]"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_sync: bool = typer.Option(False, "--no-sync", help="skip refreshing set-up projects after the update"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    ui.set_quiet(quiet)
    from ..commands.update import run_update

    raise typer.Exit(run_update([ref] if ref else [], dry_run=dry_run, sync=not no_sync, json_out=json_out))


# `upgrade` 별칭 — 구 TS CLI(asgard-cli)의 근육기억 호환. start 안 /update와 동일 플로우.
app.command("upgrade", hidden=True, help="alias of `update`")(update)


@app.command(help="bring the hooks, agents and skills up to date in every project you have set up")
def sync(
    dry_run: bool = typer.Option(False, "--dry-run"),
    list_: bool = typer.Option(False, "--list", help="just list the registered projects, then stop"),
    here: bool = typer.Option(False, "--here", help="only the project you are standing in"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    ui.set_quiet(quiet)
    from ..commands.sync import run_sync

    raise typer.Exit(run_sync(dry_run=dry_run, list_only=list_, json_out=json_out, here=here))


@app.command(help="remove asgard (the uv tool only — your ~/.asgard data is kept)")
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    ui.set_quiet(quiet)
    from ..commands.uninstall import run_uninstall

    raise typer.Exit(run_uninstall(yes=yes, dry_run=dry_run, json_out=json_out))


@app.command(help="read text back and say where it sounds like a machine wrote it (exit 1 = it does)")
def humanize(
    file: str = typer.Argument(None, help="the file to check; leave it out or pass '-' to read stdin"),
    lang: str = typer.Option(None, "--lang", help="treat it as this language instead of guessing"),
    as_json: bool = typer.Option(False, "--json", help="machine-readable findings"),
) -> None:
    from ..commands.humanize import run_humanize

    raise typer.Exit(run_humanize(file, lang=lang, as_json=as_json))


@app.command(help="print or install shell completion (bash|zsh|fish|powershell)")
def completions(
    shell: str = typer.Argument(None, metavar="[bash|zsh|fish|powershell]"),
    install: bool = typer.Option(False, "--install", help="write the script and wire your shell rc"),
) -> None:
    from ..commands.completions import run_completions

    raise typer.Exit(run_completions(shell, install=install))


@app.command(help="choose how much Asgard orchestrates, and see which engines are actually reachable")
def orchestrate(
    set_: str = typer.Option("", "--set", help="auto · solo · graph · squad · off (default: auto)"),
    global_: bool = typer.Option(False, "--global", help="save for every project instead of just this one"),
    probe: bool = typer.Option(False, "--probe", help="re-check engine connectivity now instead of reading the cache"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.orchestrate import run_orchestrate

    raise typer.Exit(
        run_orchestrate(
            set_policy=set_,
            scope="global" if global_ else "project",
            probe=probe,
            json_out=json_,
            quiet=quiet,
        )
    )


@app.command(help="put one task through the native Trinity loop with nobody watching — for benches and CI")
def run(
    prompt: str = typer.Argument(None, help="the task to do (leave it out when you pass --resume)"),
    provider: str = typer.Option(None, "--provider", help="use this provider instead"),
    model: str = typer.Option(None, "--model", help="use this model instead"),
    effort: str = typer.Option(None, "--effort", help="use this effort when exactly one peer is selected"),
    json_: bool = typer.Option(False, "--json", help="stream to stderr, and print one JSON summary to stdout"),
    resume: bool = typer.Option(False, "--resume", help="pick the active Quest back up where it left off"),
    quest: str = typer.Option(None, "--quest", help="pick this particular Quest back up"),
    dual: bool = typer.Option(False, "--dual", help="have thinker and thinker_alt plan side by side"),
    cc: bool = typer.Option(False, "--cc", help="ask Claude Code as a read-only peer"),
    codex: bool = typer.Option(False, "--codex", help="ask Codex as a read-only peer"),
    cc_model: str = typer.Option(None, "--cc-model", help="use this Claude Code model"),
    cc_effort: str = typer.Option(None, "--cc-effort", help="use this Claude Code effort"),
    codex_model: str = typer.Option(None, "--codex-model", help="use this Codex model"),
    codex_effort: str = typer.Option(None, "--codex-effort", help="use this Codex reasoning effort"),
    rounds: int = typer.Option(2, "--rounds", help="run 1-3 bounded peer exchange rounds"),
    synth: str = typer.Option(None, "--synth", help="choose the final synthesizer: cc | codex"),
    verify: list[str] = typer.Option(None, "--verify", help="run this command after synthesis (repeatable)"),
    keep_open: bool = typer.Option(False, "--keep-open", help="keep this swarm Run open for later prompts"),
    swarm_run: str = typer.Option(None, "--swarm-run", help="resume peers saved in this open swarm Run"),
) -> None:
    from ..commands.start import run_prompt

    raise typer.Exit(
        run_prompt(
            prompt,
            provider=provider,
            model=model,
            effort=effort,
            json_out=json_,
            resume=resume,
            quest_id=quest,
            dual=dual,
            cc=cc,
            codex=codex,
            cc_model=cc_model,
            cc_effort=cc_effort,
            codex_model=codex_model,
            codex_effort=codex_effort,
            rounds=rounds,
            synth=synth,
            verify_commands=verify,
            keep_open=keep_open,
            swarm_run=swarm_run,
        )
    )
