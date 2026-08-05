"""asgard CLI — 자가진화. 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer

from ._app import app

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
    from ..commands.evolve import run_scan

    raise typer.Exit(run_scan(json_out))


@evolve_app.command("nudge", help="for hooks: mention once that there is something new to dig out, then stay quiet")
def evolve_nudge(
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.evolve import run_nudge

    raise typer.Exit(run_nudge(json_out))


@evolve_app.command("list", help="the skill drafts waiting on you — edit the files first if they need it")
def evolve_list(
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.evolve import run_list

    raise typer.Exit(run_list(json_out))


@evolve_app.command("show", help="print one waiting draft, as its SKILL.md stands")
def evolve_show(
    cid: str = typer.Argument(..., metavar="<id>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.evolve import run_show

    raise typer.Exit(run_show(cid, json_out))


@evolve_app.command("approve", help="check a draft over and install it — the next dispatch can reach it, no restart")
def evolve_approve(
    cid: str = typer.Argument(..., metavar="<id>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.evolve import run_approve

    raise typer.Exit(run_approve(cid, json_out))


@evolve_app.command("reject", help="turn a draft down — that same lesson is never brought to you again")
def evolve_reject(
    cid: str = typer.Argument(..., metavar="<id>"),
    reason: str = typer.Option("", "--reason", help="why, if you want to say — it is kept to judge future drafts"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.evolve import run_reject

    raise typer.Exit(run_reject(cid, reason, json_out))


@evolve_app.command(
    "polish", help="have a model rewrite a draft as principles rather than steps — it still waits on you"
)
def evolve_polish(
    cid: str = typer.Argument(..., metavar="<id>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.evolve import run_polish

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
    from ..commands.evolve import run_bench

    raise typer.Exit(run_bench(skill, cmd, metric, runs, direction, timeout, json_out))


@evolve_app.command(
    "curate", help="which learned skills have gone quiet — stale at 30 days, put away at 90. shows only"
)
def evolve_curate(
    apply: bool = typer.Option(False, "--apply", help="actually put away the ones idle 90 days — you can undo it"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.evolve import run_curate

    raise typer.Exit(run_curate(apply, json_out))


@evolve_app.command("archive", help="put a learned skill away without deleting it — you can bring it back")
def evolve_archive(
    name: str = typer.Argument(..., metavar="<skill-name>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.evolve import run_archive

    raise typer.Exit(run_archive(name, json_out))


@evolve_app.command("restore", help="bring a put-away skill back, so it can be reached again")
def evolve_restore(
    name: str = typer.Argument(..., metavar="<skill-name>"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.evolve import run_restore

    raise typer.Exit(run_restore(name, json_out))
