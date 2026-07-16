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
    provider: str = typer.Option(None, "--provider", help="override the provider: anthropic | openai_compat | nvidia"),
    model: str = typer.Option(None, "--model", help="override the model id"),
    tui: bool = typer.Option(False, "--tui", help="full-screen TUI (experimental)"),
    plain: bool = typer.Option(False, "--plain", help="force the plain readline REPL (no TUI)"),
) -> None:
    from .commands.start import run_start

    raise typer.Exit(run_start(check_only=check, provider=provider, model=model, tui=tui, plain=plain))


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


@role_app.command("list", help="bridge flags + role placements (JSON)")
def role_list() -> None:
    from .commands.role import run_role_list

    raise typer.Exit(run_role_list())


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
    role: str = typer.Option("worker", "--role", help="thinker|worker|verifier|freyja|thor|loki"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.tools import run_tools_list

    raise typer.Exit(run_tools_list(role, json_out=json_))


# 개인 메모리 — LLM Wiki (v3 P1). 정본 = ~/.asgard/memory 의 md, index/state.db 는 파생.
memory_app = typer.Typer(help="personal memory — LLM wiki (ingest/query/lint)", no_args_is_help=True)
app.add_typer(memory_app, name="memory")


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


@memory_app.command("sync-turn", help="internal hook: retain one completed conversation turn from JSON stdin", hidden=True)
def memory_sync_turn(
    mode: str = typer.Option(..., "--mode", help="native|claude-code|codex|cursor"),
) -> None:
    from .commands.memory import run_sync_turn

    raise typer.Exit(run_sync_turn(mode))


@memory_app.command("path", help="print the memory directory")
def memory_path() -> None:
    from .commands.memory import run_path

    raise typer.Exit(run_path())


@memory_app.command("connect", help="link this project to the shared memory server (.asgard/memory-server.json)")
def memory_connect(
    server: str = typer.Argument(..., help="server URL, e.g. http://172.16.30.58:8888"),
    bank: str = typer.Option(None, "--bank", help="bank id (default: project directory name)"),
) -> None:
    from .commands.memory import run_connect

    raise typer.Exit(run_connect(server, bank))


@memory_app.command("project-scan", help="preview important code/docs eligible for Hindsight project memory")
def memory_project_scan(
    all_files: bool = typer.Option(False, "--all", help="bootstrap scan of all important tracked artifacts"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from .commands.memory import run_project_scan

    raise typer.Exit(run_project_scan(all_files=all_files, json_out=json_))


@memory_app.command("project-sync", help="sync approved important code/docs into the Hindsight project bank")
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


@memory_app.command("mcp", help="stdio MCP bridge for the shared memory server (register once, user scope)")
def memory_mcp() -> None:
    from .commands.memory import run_mcp

    raise typer.Exit(run_mcp())


@app.command(help="run one task headless through the native Trinity loop (benches/CI)")
def run(
    prompt: str = typer.Argument(..., help="the task to execute"),
    provider: str = typer.Option(None, "--provider", help="override the provider"),
    model: str = typer.Option(None, "--model", help="override the model id"),
    json_: bool = typer.Option(False, "--json", help="stream to stderr, print a final JSON summary to stdout"),
) -> None:
    from .commands.start import run_prompt

    raise typer.Exit(run_prompt(prompt, provider=provider, model=model, json_out=json_))


if __name__ == "__main__":
    app()
