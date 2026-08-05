"""asgard CLI — 문서. 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer

from ._app import app

# Sága — the document lane. `asgard skills run asgard-office -- …` is the agent's
# surface; this is the same engine for a person, with a rendered catalog.
office_app = typer.Typer(help="Sága — build, read, verify, and fill documents", invoke_without_command=True)
app.add_typer(office_app, name="office")


@office_app.callback()
def office_default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from ..commands.office import run_office_outline

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
    from ..commands.office import run_office_build

    raise typer.Exit(run_office_build(lane, spec, output, template, values, json_))


@office_app.command("read", help="read a document back out as Markdown or JSON")
def office_read(
    path: str = typer.Argument(..., metavar="<file>"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.office import run_office_read

    raise typer.Exit(run_office_read(path, json_))


@office_app.command(
    "verify", help="check it before you send it — text running over, contrast, placeholders left in, formulas"
)
def office_verify(
    path: str = typer.Argument(..., metavar="<file>"),
    strict: bool = typer.Option(False, "--strict", help="let warnings fail it too, not just errors"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.office import run_office_verify

    raise typer.Exit(run_office_verify(path, strict, json_))


@office_app.command("fill", help="fill {{placeholders}} in a file somebody else designed")
def office_fill(
    path: str = typer.Argument(..., metavar="<file>"),
    values: str = typer.Option("", "--values"),
    output: str = typer.Option("", "-o", "--output"),
    scan: bool = typer.Option(False, "--scan", help="list the placeholders instead of filling them"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.office import run_office_fill

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
    from ..commands.office import run_office_render

    raise typer.Exit(run_office_render(path, outdir, probe, recalc, json_))


@office_app.command("outline", help="skeletons to start from — 23 shapes of document and deck")
def office_outline(
    genre: str = typer.Argument("", metavar="[genre]"),
    language: str = typer.Option("en", "--language", help="en|ko — what language the headings come out in"),
    output: str = typer.Option("", "-o", "--output"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.office import run_office_outline

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
    from ..commands.office import run_office_template

    raise typer.Exit(run_office_template(list(ctx.args) or ["list"], json_))
