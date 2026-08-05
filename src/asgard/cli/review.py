"""asgard CLI — 명시 승인형 Review 에이전트."""

import typer

from ._app import app

review_app = typer.Typer(
    help="ask the read-only Review agent for line-level suggestions — it runs only after Odin approves",
    invoke_without_command=True,
)
app.add_typer(review_app, name="review")


@review_app.callback()
def review_default(
    ctx: typer.Context,
    base: str = typer.Option("HEAD", "--base", help="the git ref the approved change is compared against"),
    path: list[str] = typer.Option(None, "--path", help="review only changed files under this path (repeatable)"),
    focus: str = typer.Option("", "--focus", help="one concern Odin wants the reviewer to prioritize"),
    approve: str = typer.Option("", "--approve", help="the pending review id Odin explicitly approved"),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="run the model now; agents may use this only after Odin explicitly said yes",
    ),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    from ..commands.review import run_review

    raise typer.Exit(
        run_review(
            base=base,
            paths=tuple(path or ()),
            focus=focus,
            approve=approve,
            yes=yes,
            json_out=json_,
            quiet=quiet,
        )
    )


@review_app.command("list", help="show pending, running, and completed Review records")
def review_list(
    limit: int = typer.Option(50, "--limit", min=1, max=500),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.review import run_list

    raise typer.Exit(run_list(json_out=json_, quiet=quiet, limit=limit))


@review_app.command("show", help="show one Review request or its saved suggestions")
def review_show(
    review_id: str = typer.Argument(..., help="review id"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.review import run_show

    raise typer.Exit(run_show(review_id, json_out=json_, quiet=quiet))


@review_app.command("decide", help="accept, dismiss, resolve, or reopen one saved suggestion")
def review_decide(
    review_id: str = typer.Argument(..., help="review id"),
    finding_id: str = typer.Argument(..., help="finding id shown by review show"),
    decision: str = typer.Argument(..., help="accept | dismiss | resolve | reopen"),
    note: str = typer.Option("", "--note", help="why Odin made this decision"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.review import run_decide

    raise typer.Exit(
        run_decide(
            review_id,
            finding_id,
            decision,
            note=note,
            json_out=json_,
            quiet=quiet,
        )
    )


@review_app.command("cancel", help="decline a pending Review request without running the model")
def review_cancel(
    review_id: str = typer.Argument(..., help="pending review id"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.review import run_cancel

    raise typer.Exit(run_cancel(review_id, json_out=json_, quiet=quiet))
