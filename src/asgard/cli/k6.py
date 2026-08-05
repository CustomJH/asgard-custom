"""asgard CLI — 부하 시험과 자동화. 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer

from ._app import app

k6_app = typer.Typer(
    help="asgard-k6 — Docker load testing, and the harness that checks itself", invoke_without_command=True
)
app.add_typer(k6_app, name="k6")


@k6_app.callback()
def k6_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from ..commands.k6 import run_k6_doctor

        raise typer.Exit(run_k6_doctor(False))


@k6_app.command("doctor", help="is everything here to run a test — the runner, the k6 build, the kit, the scenarios")
def k6_doctor(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.k6 import run_k6_doctor

    raise typer.Exit(run_k6_doctor(json_))


@k6_app.command("sync", help="lay the kit down in this project's .asgard/k6/ — the folders docker mounts")
def k6_sync(
    force: bool = typer.Option(False, "--force", help="copy it again even if what is there already matches"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.k6 import run_k6_sync

    raise typer.Exit(run_k6_sync(force, json_))


@k6_app.command("scenarios", help="the load scenarios that shipped, and the ones this project wrote")
def k6_scenarios(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.k6 import run_k6_list

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
        [], "--env", "-e", help="KEY=VALUE for the scenario (a bare key gets the ASGARD_K6_ prefix)"
    ),
    runner: str = typer.Option("", "--runner", help="docker | podman | native"),
    json_: bool = typer.Option(False, "--json"),
    no_record: bool = typer.Option(False, "--no-record", help="do not keep this run under .asgard/k6/runs/"),
    live: bool = typer.Option(True, "--live/--no-live", help="watch it per second while it runs (a TTY only)"),
) -> None:
    from ..commands.k6 import run_k6_run

    raise typer.Exit(
        run_k6_run(scenario, target, vus, duration, iterations, p95_max, list(env), runner, json_, not no_record, live)
    )


@k6_app.command("selftest", help="does the harness tell the truth — measured against a target we told how to behave")
def k6_selftest(
    json_: bool = typer.Option(False, "--json"),
    latency_ms: float = typer.Option(80.0, "--latency-ms", help="how long the reference target takes on purpose"),
    iterations: int = typer.Option(40, "--iterations"),
    vus: int = typer.Option(4, "--vus"),
) -> None:
    from ..commands.k6 import run_k6_selftest

    raise typer.Exit(run_k6_selftest(json_, latency_ms, iterations, vus))


@k6_app.command("report", help="lay out a run you already did (the newest one, unless you name another)")
def k6_report(
    path: str = typer.Argument("", metavar="[run dir | report.json]"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.k6 import run_k6_report

    raise typer.Exit(run_k6_report(path, json_))


k6_baseline_app = typer.Typer(
    help="the run this project measures against — pin it, look at it, drop it", invoke_without_command=True
)
k6_app.add_typer(k6_baseline_app, name="baseline")


@k6_baseline_app.callback()
def k6_baseline_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from ..commands.k6 import run_k6_baseline_show

        raise typer.Exit(run_k6_baseline_show(False))


@k6_baseline_app.command("set", help="pin a run as the target to beat (the newest one, unless you name a stamp)")
def k6_baseline_set(
    stamp: str = typer.Argument("", metavar="[stamp]"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.k6 import run_k6_baseline_set

    raise typer.Exit(run_k6_baseline_set(stamp, json_))


@k6_baseline_app.command("show", help="which run is the target right now, and how far a run may drift from it")
def k6_baseline_show(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.k6 import run_k6_baseline_show

    raise typer.Exit(run_k6_baseline_show(json_))


@k6_baseline_app.command("clear", help="drop the target — the gate stops judging until you pin another")
def k6_baseline_clear(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.k6 import run_k6_baseline_clear

    raise typer.Exit(run_k6_baseline_clear(json_))


@k6_app.command(
    "gate",
    help="did the last run get worse than the baseline (exit 1 = it did; it reads files, it does not run load)",
)
def k6_gate(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.k6 import run_k6_gate

    raise typer.Exit(run_k6_gate(json_))


automations_app = typer.Typer(help="saved prompts this project can run when an OS scheduler asks what is due")
app.add_typer(automations_app, name="automations")


@automations_app.command("list", help="show every saved automation and its last outcome")
def automations_list(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.automations import run_list

    raise typer.Exit(run_list(json_))


@automations_app.command("add", help="save one prompt with an hourly/daily/weekdays/weekly or 5-field cron schedule")
def automations_add(
    name: str = typer.Argument(..., metavar="<name>"),
    prompt: str = typer.Argument(..., metavar="<prompt>"),
    schedule: str = typer.Option(..., "--schedule", help="hourly | daily | weekdays | weekly | 5-field cron"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.automations import run_add

    raise typer.Exit(run_add(name, prompt, schedule, json_))


@automations_app.command("remove", help="remove a saved automation; its run history stays")
def automations_remove(
    name: str = typer.Argument(..., metavar="<name>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.automations import run_remove

    raise typer.Exit(run_remove(name, json_))


@automations_app.command("enable", help="let a saved automation become due again")
def automations_enable(
    name: str = typer.Argument(..., metavar="<name>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.automations import run_enable

    raise typer.Exit(run_enable(name, True, json_))


@automations_app.command("disable", help="keep a saved automation without letting it become due")
def automations_disable(
    name: str = typer.Argument(..., metavar="<name>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.automations import run_enable

    raise typer.Exit(run_enable(name, False, json_))


@automations_app.command("due", help="report what is due now; --run explicitly puts each prompt through asgard run")
def automations_due(
    execute: bool = typer.Option(False, "--run", help="actually run each due prompt now"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.automations import run_due

    raise typer.Exit(run_due(execute, json_))


@automations_app.command("history", help="show recent automation runs, newest first")
def automations_history(
    name: str = typer.Argument("", metavar="[name]"),
    limit: int = typer.Option(20, "--limit", help="how many runs to show"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.automations import run_history

    raise typer.Exit(run_history(name, limit, json_))
