"""asgard CLI — 배차 장부. 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer

from ._app import app

# 배차 장부 — 퀘스트가 어떤 모양으로 돌았고, 어느 시도가 몇 번 만에 붙었고, 무엇이 답을
# 기다리는가. 퀘스트 로그(무엇이 검증됐는가)와 다른 축이다.
# 이름은 asgard-helios 의 어휘를 따른다: `orchestration` 은 기제(도메인 패키지)이고
# `siege` 는 사람이 부르는 모드다.
siege_app = typer.Typer(
    help="run a siege and look inside it — tasks and their order, attempts, mail, and the questions still open",
    invoke_without_command=True,
)
app.add_typer(siege_app, name="siege")


@siege_app.callback()
def siege_default(ctx: typer.Context, json_: bool = typer.Option(False, "--json")) -> None:
    if ctx.invoked_subcommand is None:
        from ..commands.siege import run_runs

        raise typer.Exit(run_runs(json_out=json_))


@siege_app.command("show", help="one run in full — its tasks, what each waited on, and every attempt")
def siege_show(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege import run_show

    raise typer.Exit(run_show(run_id, json_out=json_))


@siege_app.command("inbox", help="the messages one run sent and received — reading them leaves the mail unread")
def siege_inbox(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    limit: int = typer.Option(50, "--limit"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege import run_inbox

    raise typer.Exit(run_inbox(run_id, json_out=json_, limit=limit))


@siege_app.command("blocked", help="the worker questions nobody has answered yet")
def siege_blocked(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.siege import run_blocked

    raise typer.Exit(run_blocked(json_out=json_))


@siege_app.command("answer", help="answer a waiting worker question yourself, and let it carry on")
def siege_answer(
    message_id: str = typer.Argument(..., metavar="<message_id>"),
    answer: str = typer.Argument(..., metavar="<answer>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege import run_answer

    raise typer.Exit(run_answer(message_id, answer, json_out=json_))


@siege_app.command("gates", help="the decisions a coordinator stopped to ask about — still waiting on you")
def siege_gates(
    run_id: str = typer.Argument("", metavar="[run_id]"),
    all_: bool = typer.Option(False, "--all"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege import run_gates

    raise typer.Exit(run_gates(run_id, json_out=json_, all_gates=all_))


@siege_app.command("decide", help="close a waiting decision gate with your choice, and let the run carry on")
def siege_decide(
    gate_id: str = typer.Argument(..., metavar="<gate_id>"),
    resolution: str = typer.Argument(..., metavar="<resolution>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege import run_decide

    raise typer.Exit(run_decide(gate_id, resolution, json_out=json_))


@siege_app.command("reset", help="wipe the siege record — it is all rebuilt from elsewhere, and the quest log stays")
def siege_reset(
    tasks: bool = typer.Option(False, "--tasks", help="clear the task DAG only — the run and mailbox stay"),
    messages: bool = typer.Option(False, "--messages", help="clear the mailbox only — the task DAG stays"),
    all_: bool = typer.Option(False, "--all", help="wipe the whole record (default when no scope is given)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege import run_reset

    raise typer.Exit(run_reset(json_out=json_, tasks=tasks, messages=messages, all_=all_))


# 여기서부터 장부를 **모는** 명령이다. 네이티브 Trinity 루프는 같은 계약을 프로세스 안에서
# 부르지만(`agent/heimdall/bifrost.py`), Claude Code·Cursor·Codex 모드에는 그 문이 없었다 —
# 호스트 도구의 에이전트가 배차를 쓰려면 프로세스 밖에서 부를 자리가 있어야 한다.
# 소비자가 사람이 아니라 에이전트인 경우가 많으므로 전부 `--json` 을 받는다.


@siege_app.command("start", help="open a run — the namespace for its tasks and the coordinator's mailbox")
def siege_start(
    objective: str = typer.Argument(..., metavar="<objective>"),
    quest: str = typer.Option("", "--quest", help="bind it to this quest, reusing the run that quest already has"),
    coordinator: str = typer.Option("", "--coordinator", help="who is running this siege"),
    shape: str = typer.Option("", "--shape", help="direct | single | graph | squad"),
    why: str = typer.Option("", "--why", help="one line on why that shape — it is read back in `siege show`"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_start

    raise typer.Exit(
        run_start(objective, quest_id=quest, coordinator=coordinator, shape=shape, why=why, json_out=json_)
    )


@siege_app.command("add", help="add one task to the run's graph — with --dep it waits, without it is ready at once")
def siege_add(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    spec: str = typer.Argument(..., metavar="<spec>"),
    dep: list[str] = typer.Option(None, "--dep", help="a task id in this same run that must finish first"),
    unit: str = typer.Option("", "--unit", help="the assignment-unit id this task carries"),
    parent: str = typer.Option("", "--parent", help="the task this one was split out of"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_add

    raise typer.Exit(run_add(run_id, spec, deps=list(dep or []), unit_id=unit, parent=parent, json_out=json_))


@siege_app.command("ready", help="the tasks you can dispatch right now — everything they waited on is done")
def siege_ready(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_ready

    raise typer.Exit(run_ready(run_id, json_out=json_))


@siege_app.command("waves", help="the graph laid out as batches — everything in one batch can run side by side")
def siege_waves(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_waves

    raise typer.Exit(run_waves(run_id, json_out=json_))


@siege_app.command("open", help="open an attempt on one task — a task carries one live attempt at a time")
def siege_open(
    task_id: str = typer.Argument(..., metavar="<task_id>"),
    worker: str = typer.Option("", "--worker", help="who is taking it"),
    role: str = typer.Option("", "--role", help="which Trinity role this attempt runs as"),
    agent: str = typer.Option("", "--agent", help="which agent the host launched"),
    model: str = typer.Option("", "--model", help="which model it runs on"),
    retry_of: str = typer.Option("", "--retry-of", help="the settled dispatch this one retries"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_open

    raise typer.Exit(
        run_open(task_id, worker=worker, role=role, agent=agent, model=model, retry_of=retry_of, json_out=json_)
    )


@siege_app.command("done", help="report an attempt finished — the mail and the settlement land together")
def siege_done(
    dispatch_id: str = typer.Argument(..., metavar="<dispatch_id>"),
    outcome: str = typer.Argument(..., metavar="succeeded|failed"),
    run_id: str = typer.Option("", "--run", help="check the dispatch really belongs to this run"),
    task_id: str = typer.Option("", "--task", help="check the dispatch really belongs to this task"),
    subject: str = typer.Option("", "--subject", help="the one-line headline of the report"),
    body: str = typer.Option("", "--body", help="what happened, in full"),
    file: list[str] = typer.Option(None, "--file", help="a path this attempt modified"),
    sender: str = typer.Option("", "--sender", help="who is reporting"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_done

    raise typer.Exit(
        run_done(
            dispatch_id,
            outcome,
            run_id=run_id,
            task_id=task_id,
            subject=subject,
            body=body,
            files=list(file or []),
            sender=sender,
            json_out=json_,
        )
    )


@siege_app.command("settle", help="close an attempt from the coordinator's side, when the worker left no report")
def siege_settle(
    dispatch_id: str = typer.Argument(..., metavar="<dispatch_id>"),
    outcome: str = typer.Argument(..., metavar="succeeded|failed"),
    summary: str = typer.Option("", "--summary", help="what the attempt came to"),
    file: list[str] = typer.Option(None, "--file", help="a path this attempt modified"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_settle

    raise typer.Exit(run_settle(dispatch_id, outcome, summary=summary, files=list(file or []), json_out=json_))


@siege_app.command("mark", help="mark an attempt stopped or outcome_unknown — neither one closes the task")
def siege_mark(
    dispatch_id: str = typer.Argument(..., metavar="<dispatch_id>"),
    state: str = typer.Argument(..., metavar="stopped|outcome_unknown"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_mark

    raise typer.Exit(run_mark(dispatch_id, state, json_out=json_))


@siege_app.command("ask", help="a stuck worker asks the coordinator — whether it waits is yours to say")
def siege_ask(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    question: str = typer.Argument(..., metavar="<question>"),
    option: list[str] = typer.Option(None, "--option", help="one answer the asker will accept"),
    sender: str = typer.Option("", "--sender", help="who is asking"),
    task_id: str = typer.Option("", "--task", help="the task this question came out of"),
    dispatch_id: str = typer.Option("", "--dispatch", help="the attempt this question came out of"),
    wait_ms: int = typer.Option(0, "--wait-ms", help="wait this long for an answer — 0 returns straight away"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_ask

    raise typer.Exit(
        run_ask(
            run_id,
            question,
            options=list(option or []),
            sender=sender,
            task_id=task_id,
            dispatch_id=dispatch_id,
            wait_ms=wait_ms,
            json_out=json_,
        )
    )


@siege_app.command("send", help="put a message in the run's mailbox — a finished report goes through `done` instead")
def siege_send(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    message_type: str = typer.Argument(..., metavar="<type>"),
    subject: str = typer.Option("", "--subject", help="the one-line headline"),
    body: str = typer.Option("", "--body", help="the message itself"),
    sender: str = typer.Option("", "--sender", help="who is sending"),
    recipient: str = typer.Option("", "--recipient", help="who it is for"),
    task_id: str = typer.Option("", "--task", help="the task it concerns"),
    dispatch_id: str = typer.Option("", "--dispatch", help="the attempt it concerns"),
    priority: str = typer.Option("normal", "--priority", help="low | normal | high"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_send

    raise typer.Exit(
        run_send(
            run_id,
            message_type,
            subject=subject,
            body=body,
            sender=sender,
            recipient=recipient,
            task_id=task_id,
            dispatch_id=dispatch_id,
            priority=priority,
            json_out=json_,
        )
    )


@siege_app.command("check", help="take the oldest unacked batch of mail — pass --ack to clear the one before it")
def siege_check(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    ack: str = typer.Option("", "--ack", help="the delivery id you are done with"),
    type_: list[str] = typer.Option(None, "--type", help="a message type worth waking for"),
    peek: bool = typer.Option(False, "--peek", help="look without taking — the replay contract stays untouched"),
    wait_ms: int = typer.Option(0, "--wait-ms", help="wait this long for mail to arrive"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_check

    raise typer.Exit(run_check(run_id, ack=ack, types=list(type_ or []), peek=peek, wait_ms=wait_ms, json_out=json_))


@siege_app.command("escalate", help="say the coordinator has to step in — for when there is no question to ask yet")
def siege_escalate(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    reason: str = typer.Argument(..., metavar="<reason>"),
    task_id: str = typer.Option("", "--task", help="the task this came out of"),
    dispatch_id: str = typer.Option("", "--dispatch", help="the attempt this came out of"),
    sender: str = typer.Option("", "--sender", help="who is escalating"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_escalate

    raise typer.Exit(
        run_escalate(run_id, reason, task_id=task_id, dispatch_id=dispatch_id, sender=sender, json_out=json_)
    )


@siege_app.command("heartbeat", help="say a long attempt is still alive, so `reclaim` leaves it alone")
def siege_heartbeat(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    task_id: str = typer.Argument(..., metavar="<task_id>"),
    dispatch_id: str = typer.Argument(..., metavar="<dispatch_id>"),
    phase: str = typer.Option("", "--phase", help="what it is doing right now"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_heartbeat

    raise typer.Exit(run_heartbeat(run_id, task_id, dispatch_id, phase=phase, json_out=json_))


@siege_app.command("gate", help="stop the graph on a decision only a person should make — `decide` closes it")
def siege_gate(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    question: str = typer.Argument(..., metavar="<question>"),
    option: list[str] = typer.Option(None, "--option", help="one branch the coordinator would accept"),
    task_id: str = typer.Option("", "--task", help="the task this decision holds up"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_gate

    raise typer.Exit(run_gate(run_id, question, options=list(option or []), task_id=task_id, json_out=json_))


@siege_app.command("force", help="write a task's status by hand — for recovery, not for the normal path")
def siege_force(
    task_id: str = typer.Argument(..., metavar="<task_id>"),
    status: str = typer.Argument(..., metavar="pending|ready|dispatched|completed|failed|blocked"),
    result: str = typer.Option("", "--result", help="a JSON object to record alongside the status"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_force

    raise typer.Exit(run_force(task_id, status, result=result, json_out=json_))


@siege_app.command("refresh", help="work out every task's status from its dependencies again")
def siege_refresh(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_refresh

    raise typer.Exit(run_refresh(run_id, json_out=json_))


@siege_app.command("reclaim", help="take back attempts whose worker vanished without settling them")
def siege_reclaim(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    older_than: float = typer.Option(0.0, "--older-than", help="leave attempts touched within this many seconds"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_reclaim

    raise typer.Exit(run_reclaim(run_id, older_than=older_than, json_out=json_))


@siege_app.command("close", help="close a run — no more tasks, gates, or attempts go into it")
def siege_close(
    run_id: str = typer.Argument(..., metavar="<run_id>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.siege_act import run_close_cmd

    raise typer.Exit(run_close_cmd(run_id, json_out=json_))
