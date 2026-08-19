"""asgard CLI — 기억(위그드라실). 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer

from ._app import app

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
    from ..commands.memory import run_add

    raise typer.Exit(run_add(text, title, kind, links, json_out))


@memory_app.command("ingest", help="take something in — if a page already says nearly this, it grows instead")
def memory_ingest(
    text: str = typer.Argument(...),
    kind: str = typer.Option("note", "--kind"),
    title: str = typer.Option(None, "--title", help="the page title (default: the first sentence of the text)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="save without asking first"),
    plan_id: str = typer.Option(None, "--plan-id", help="carry out the exact plan you already approved"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_ingest

    raise typer.Exit(run_ingest(text, kind, yes, plan_id, json_out, title))


@memory_app.command("query", help="search the wiki — plain text search, no model, and every hit is counted")
def memory_query(
    text: str = typer.Argument(...),
    # 같은 개념(결과 개수)이 다른 명령에서는 `--limit`이다 — 긴 이름을 정본으로 두고 `-k`는 단축으로 남긴다.
    k: int = typer.Option(5, "--limit", "-k", help="how many results to show"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_query

    raise typer.Exit(run_query(text, k, json_))


@memory_app.command(
    "graph",
    help="read the memory as a graph — what it grew around, why two pages are connected, "
    "what sits around one, and how many clumps there are",
)
def memory_graph(
    verb: str = typer.Argument(..., help="hubs|path|expand|communities|stats"),
    source: str = typer.Argument("", help="the node to start from (path, expand)"),
    target: str = typer.Argument("", help="the node to reach (path)"),
    scope: str = typer.Option("personal", "--scope", help="personal|project"),
    edges: str = typer.Option("all", "--edges", help="all|explicit|mention|term — which links to count"),
    top: int = typer.Option(10, "--limit", "-k", help="how many hubs to show"),
    depth: int = typer.Option(2, "--depth", help="how many hops out to walk (expand)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory.graph import run_graph

    raise typer.Exit(run_graph(verb, source, target, scope=scope, edges=edges, top=top, depth=depth, json_out=json_))


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
    from ..commands.memory import run_episodes

    raise typer.Exit(run_episodes(text, k, quest, json_))


@memory_app.command(
    "lint", help="how the wiki is holding up — broken links, pages going stale, duplicates, size, open contradictions"
)
def memory_lint(
    json_: bool = typer.Option(False, "--json"),
    fix: bool = typer.Option(False, "--fix", help="rewrite titles that were copied from the body and cut mid-word"),
) -> None:
    from ..commands.memory import run_lint

    raise typer.Exit(run_lint(json_, fix))


# 모순은 노른이 고치지 않고 사람에게 넘기는 유일한 op 다. 넘길 자리를 두 개 둔다 —
# 목록(무엇끼리 어긋났나)과 표시(봤다). 표시는 해소가 아니라서 이름도 `seen` 이다:
# `resolve`·`fix`로 부르면 사람이 페이지가 고쳐졌다고 읽는데, 페이지는 한 글자도 안 바뀐다.
@memory_app.command("contradictions", help="pages that disagree with each other — you decide, nothing is fixed for you")
def memory_contradictions(
    json_: bool = typer.Option(False, "--json"),
    all_: bool = typer.Option(False, "--all", help="show the pairs you have already marked as seen too"),
) -> None:
    from ..commands.memory import run_contradictions

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
    from ..commands.memory import run_contradiction_seen

    raise typer.Exit(run_contradiction_seen(a, b, note, json_out))


@memory_app.command("proposals", help="what the agent wants to remember, waiting on your say-so")
def memory_proposals(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.memory import run_proposals

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
    from ..commands.memory import run_autosave

    raise typer.Exit(run_autosave(state, tier, json_, yes))


@memory_app.command("approve", help="say yes to a waiting proposal — it goes into the wiki")
def memory_approve(
    proposal_id: str = typer.Argument(..., help="the id shown by `asgard memory proposals`"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_approve

    raise typer.Exit(run_approve(proposal_id, json_))


@memory_app.command("discard", help="throw a waiting proposal away — nothing is written")
def memory_discard(
    proposal_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_discard

    raise typer.Exit(run_discard(proposal_id, json_out))


@memory_app.command("reindex", help="rebuild index.md and state.db from pages/, which is the real record")
def memory_reindex(
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_reindex

    raise typer.Exit(run_reindex(json_out))


@memory_app.command("export-okf", help="write your personal memory out as a read-only OKF v0.1 bundle")
def memory_export_okf(
    destination: str = typer.Argument(..., help="where to write it — a new or empty folder"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_export_okf

    raise typer.Exit(run_export_okf(destination, json_out))


@memory_app.command("show", help="print one page, frontmatter and all")
def memory_show(
    slug: str = typer.Argument(...),
    unsafe: bool = typer.Option(False, "--unsafe", help="open a page held in quarantine, so you can repair it"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_show

    raise typer.Exit(run_show(slug, unsafe=unsafe, json_out=json_out))


@memory_app.command("remove", help="delete a page, and rebuild the index around the gap")
def memory_remove(
    slug: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_remove

    raise typer.Exit(run_remove(slug, json_out))


@memory_app.command("merge", help="fold one page into another — what to do when the wiki has outgrown its budget")
def memory_merge(
    src: str = typer.Argument(..., help="the page to fold in (it is deleted afterwards)"),
    dst: str = typer.Argument(..., help="the page that grows"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_merge

    raise typer.Exit(run_merge(src, dst, json_out))


@memory_app.command("snapshot", help="the memory a new session starts with (nothing, if that is switched off)")
def memory_snapshot(
    provider: str = typer.Option(None, "--provider", help="who is asking — memory is only handed to allowed providers"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_snapshot

    raise typer.Exit(run_snapshot(provider, json_out))


@memory_app.command("recall", help="the memory this question would pull in (nothing, if it is off or nothing matches)")
def memory_recall(
    text: str = typer.Argument(...),
    provider: str = typer.Option(None, "--provider", help="who is asking — memory is only handed to allowed providers"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_recall

    raise typer.Exit(run_recall(text, provider, json_out))


@memory_app.command("sync-turn", help="for hooks: keep one finished turn, read as JSON from stdin", hidden=True)
def memory_sync_turn(
    mode: str = typer.Option(..., "--mode", help="native|claude-code|codex|cursor"),
) -> None:
    from ..commands.memory import run_sync_turn

    raise typer.Exit(run_sync_turn(mode))


@memory_app.command("path", help="print or configure the personal memory directory")
def memory_path(
    directory: str = typer.Option(None, "--set", help="keep your personal memory here from now on, everywhere"),
    reset: bool = typer.Option(False, "--reset", help="put it back where it started"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_path

    raise typer.Exit(run_path(directory, reset, json_out))


@memory_app.command("provider", help="which model looks after your personal memory — see it, or change it")
def memory_provider(
    set_: str = typer.Option("", "--set", help="provider[:model] to hand the curating to"),
    clear: bool = typer.Option(False, "--clear", help="go back to using your main provider"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_provider

    raise typer.Exit(run_provider(set_, clear, json_))


@memory_app.command("semantic", help="search by meaning rather than words — where it stands, and how to turn it on")
def memory_semantic(
    action: str = typer.Argument("status", help="status|on|off|warmup|nudge"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_semantic

    raise typer.Exit(run_semantic(action, json_))


@memory_app.command("backup", help="keep copies of the wiki — make one, list them, restore, check, or prune")
def memory_backup(
    action: str = typer.Argument("create", help="create|list|restore|verify|prune"),
    name: str = typer.Option("", "--name", help="which backup to restore or check (default: the newest)"),
    label: str = typer.Option("", "--label", help="a short word to tack onto the archive name"),
    keep: int = typer.Option(0, "--keep", help="how many to keep (default 10)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_backup

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
    from ..commands.memory import run_sync

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
    from ..commands.memory import run_norn

    raise typer.Exit(run_norn(apply, nudge, json_, auto, wake))


@memory_app.command("pattern", help="notice how Odin works, from past turns. shows only — `--apply` writes it down")
def memory_pattern(
    apply: bool = typer.Option(False, "--apply", help="write the observations that checked out into the wiki"),
    due: bool = typer.Option(False, "--due", hidden=True, help="for hooks: say whether a pass is due"),
    auto: bool = typer.Option(
        False,
        "--auto",
        help="go on its own, but only as far as the pattern_auto tier allows — inferences still come to you as proposals",
    ),
    wake: bool = typer.Option(
        False, "--wake", hidden=True, help="for hooks: start a detached --auto run when one is due"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_pattern

    raise typer.Exit(run_pattern(apply, json_, due, auto, wake))


@memory_app.command("tick", hidden=True, help="for hooks: the end-of-turn nudges, in one process")
def memory_tick(json_: bool = typer.Option(False, "--json")) -> None:
    from ..commands.memory import run_tick

    raise typer.Exit(run_tick(json_))


@memory_app.command("ask", help="ask something about Odin — answered from personal, episodic and project memory")
def memory_ask(
    question: str = typer.Argument(..., help="ask it the way you would out loud"),
    k: int = typer.Option(5, "--limit", "-k", help="how much evidence to pull from each source"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_ask

    raise typer.Exit(run_ask(question, k, json_))


@memory_app.command("norn-restore", help="bring back a page a norn pass filed away")
def memory_norn_restore(
    slug: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_norn_restore

    raise typer.Exit(run_norn_restore(slug, json_out))


@memory_app.command(
    "project-recall", help="search what the project remembers — the same gate the agent's own recall goes through"
)
def memory_project_recall(
    query: str = typer.Argument(..., help="what to look for"),
    max_results: int = typer.Option(8, "--max-results", help="how many to bring back"),
    unfiltered: bool = typer.Option(
        False, "--unfiltered", help="skip the tag prefilter and see what the store holds, gate reasons and all"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_project_recall

    raise typer.Exit(run_project_recall(query, max_results, unfiltered=unfiltered, json_out=json_))


@memory_app.command("project-retain", help="write one project record — validated and staged the same way MCP does")
def memory_project_retain(
    content: str = typer.Argument(..., help="the record body — self-contained, at least 20 characters"),
    record_id: str = typer.Option(..., "--record-id", help="stable id, e.g. decision-auth-rotation"),
    kind: str = typer.Option(..., "--kind", help="decision|policy|incident|experiment|component|contract|migration"),
    title: str = typer.Option(..., "--title", help="one line, at least 4 characters"),
    source: str = typer.Option(..., "--source", help="where it came from — a path, URL, commit, or test"),
    source_revision: str = typer.Option(..., "--source-revision", help="which version of that source"),
    importance: str = typer.Option("normal", "--importance", help="normal|high|critical"),
    confidence: str = typer.Option(
        "observed", "--confidence", help="observed|verified — only verified reaches automatic injection"
    ),
    status: str = typer.Option("active", "--status", help="active|superseded|historical"),
    approve: bool = typer.Option(False, "--approve", help="commit it now instead of leaving it waiting"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_project_retain

    raise typer.Exit(
        run_project_retain(
            content,
            record_id=record_id,
            kind=kind,
            title=title,
            source=source,
            source_revision=source_revision,
            importance=importance,
            confidence=confidence,
            status=status,
            approve=approve,
            json_out=json_,
        )
    )


@memory_app.command(
    "project-reflect", help="have a model think over everything the project remembers — take it as advice"
)
def memory_project_reflect(
    question: str = typer.Argument(..., help="what to think about"),
    budget: str = typer.Option("low", "--budget", help="low|mid|high — how deeply to think"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_project_reflect

    raise typer.Exit(run_project_reflect(question, budget, json_))


@memory_app.command("obsidian", help="set the wiki up as an Obsidian vault and open it there")
def memory_obsidian(
    refresh: bool = typer.Option(False, "--refresh", help="set it up and redraw the maps, but do not open it"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_obsidian

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
    from ..commands.memory import run_connect

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
    from ..commands.memory import run_project_scan

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
    from ..commands.memory import run_project_sync

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
    from ..commands.memory import run_project_evolve

    raise typer.Exit(run_project_evolve(apply, json_))


@memory_app.command("project-learn", help="set up what Hindsight watches, and the picture it keeps of the project")
def memory_project_learn(
    apply: bool = typer.Option(False, "--apply", help="save the settings and line up the next consolidation"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_project_learn

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
    from ..commands.memory import run_project_ingest

    raise typer.Exit(run_project_ingest(paths, strategy, yes, json_, lane))


@memory_app.command("project-approve", help="say yes to one waiting project-memory proposal, and write it")
def memory_project_approve(
    approval_id: str = typer.Argument(..., help="the approval id the proposal printed"),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.memory import run_project_approve

    raise typer.Exit(run_project_approve(approval_id, json_out))


@memory_app.command("project-rehydrate", help="replay the project records Git holds back into the store")
def memory_project_rehydrate(
    yes: bool = typer.Option(False, "--yes", "-y", help="go ahead with the writes you just previewed"),
    plan_id: str | None = typer.Option(None, "--plan-id", help="the plan id the preview printed"),
    tags_only: bool = typer.Option(
        False, "--tags-only", help="only bring the tags up to date — no re-ingest, no re-extraction"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.memory import run_project_rehydrate

    raise typer.Exit(run_project_rehydrate(yes=yes, plan_id=plan_id, json_out=json_, tags_only=tags_only))


@memory_app.command("mcp", help="serve the project memory store over MCP — register it once, for your user")
def memory_mcp() -> None:
    from ..commands.memory import run_mcp

    raise typer.Exit(run_mcp())
