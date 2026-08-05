"""asgard CLI — 티켓과 창. 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer

from ..i18n import t
from ._app import app

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
    from ..commands.ticket import run_board

    raise typer.Exit(run_board(json_out=False))


@ticket_app.command("board", help=t("hc_tk_board"))
def ticket_board(
    team: str = typer.Option("", "--team", help=t("hc_tk_team")),
    project: str = typer.Option("", "--project", help=t("hc_tk_project")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_board

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
    from ..commands.ticket import run_list

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
    from ..commands.ticket import run_new

    raise typer.Exit(
        run_new(title, body, status, priority, assignee, labels, parent, estimate, json_out, team, project, milestone)
    )


@ticket_app.command("show", help=t("hc_tk_show"))
def ticket_show(
    ref: str = typer.Argument(..., help=t("hc_tk_ref_full")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_show

    raise typer.Exit(run_show(ref, json_out))


@ticket_app.command("move", help=t("hc_tk_move"))
def ticket_move(
    ref: str = typer.Argument(..., help=t("hc_tk_ref")),
    status: str = typer.Argument(..., help="backlog|todo|in_progress|in_review|done|canceled"),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_move

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
    from ..commands.ticket import run_set

    raise typer.Exit(run_set(ref, title, body, priority, assignee, labels, estimate, parent, cycle, json_out))


@ticket_app.command("comment", help=t("hc_tk_comment"))
def ticket_comment(
    ref: str = typer.Argument(..., help=t("hc_tk_ref")),
    text: str = typer.Argument(..., help=t("hc_tk_comment_text")),
    author: str = typer.Option("", "--author", help=t("hc_tk_comment_author")),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.ticket import run_comment

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
    from ..commands.ticket import run_link

    raise typer.Exit(run_link(ref, other, kind, remove, json_out))


@ticket_app.command("evidence", help=t("hc_tk_evidence"))
def ticket_evidence(
    ref: str = typer.Argument(..., help=t("hc_tk_ref")),
    stamp: str = typer.Argument("", help=t("hc_tk_ev_stamp")),
    scenario: str = typer.Option("", "--scenario", help=t("hc_tk_ev_scenario")),
    note: str = typer.Option("", "--note", help=t("hc_tk_ev_note")),
    list_only: bool = typer.Option(False, "--list", help=t("hc_tk_ev_list")),
    remove: str = typer.Option("", "--remove", help=t("hc_tk_ev_remove")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_evidence

    raise typer.Exit(run_evidence(ref, stamp, scenario, note, list_only, remove, json_out))


@ticket_app.command("delete", help=t("hc_tk_delete"))
def ticket_delete(
    ref: str = typer.Argument(..., help=t("hc_tk_ref")),
    json_out: bool = typer.Option(False, "--json", help="print the result as JSON"),
) -> None:
    from ..commands.ticket import run_delete

    raise typer.Exit(run_delete(ref, json_out))


@ticket_app.command("cycle", help=t("hc_tk_cycle"))
def ticket_cycle(
    new: str = typer.Option("", "--new", "-n", help=t("hc_tk_cycle_new")),
    close: str = typer.Option("", "--close", help=t("hc_tk_cycle_close")),
    team: str = typer.Option("", "--team", help=t("hc_tk_cycle_team")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_cycle

    raise typer.Exit(run_cycle(new, close, json_out, team))


@ticket_app.command("team", help=t("hc_tk_team_cmd"))
def ticket_team(
    new: str = typer.Option("", "--new", "-n", help=t("hc_tk_team_new")),
    key: str = typer.Option("", "--key", help=t("hc_tk_team_key")),
    triage: str = typer.Option("", "--triage", help=t("hc_tk_team_triage")),
    cycle_weeks: int = typer.Option(0, "--cycle-weeks", help=t("hc_tk_team_weeks")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_teams

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
    from ..commands.ticket import run_projects

    raise typer.Exit(run_projects(new, show, status, lead, target, teams, json_out))


@ticket_app.command("milestone", help=t("hc_tk_milestone"))
def ticket_milestone(
    project: str = typer.Argument(..., help=t("hc_tk_project")),
    new: str = typer.Option("", "--new", "-n", help=t("hc_tk_ms_new")),
    target: str = typer.Option("", "--target", help=t("hc_tk_pj_target")),
    done: str = typer.Option("", "--done", help=t("hc_tk_ms_done")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_milestone

    raise typer.Exit(run_milestone(project, new, target, done, json_out))


@ticket_app.command("update", help=t("hc_tk_update"))
def ticket_update(
    project: str = typer.Argument(..., help=t("hc_tk_project")),
    body: str = typer.Option("", "--body", "-b", help=t("hc_tk_update_body")),
    health: str = typer.Option("", "--health", help="on_track|at_risk|off_track"),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_update

    raise typer.Exit(run_update(project, body, health, json_out))


@ticket_app.command("triage", help=t("hc_tk_triage"))
def ticket_triage(
    accept: str = typer.Option("", "--accept", help=t("hc_tk_triage_accept")),
    decline: str = typer.Option("", "--decline", help=t("hc_tk_triage_decline")),
    note: str = typer.Option("", "--note", help=t("hc_tk_triage_note")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_triage

    raise typer.Exit(run_triage(accept, decline, note, json_out))


@ticket_app.command("import", help=t("hc_tk_import"))
def ticket_import(json_out: bool = typer.Option(False, "--json", help=t("hc_json"))) -> None:
    from ..commands.ticket import run_import

    raise typer.Exit(run_import(json_out))


@ticket_app.command("doc", help=t("hc_tk_doc"))
def ticket_doc(
    new: str = typer.Option("", "--new", "-n", help=t("hc_tk_doc_new")),
    show: str = typer.Option("", "--show", help=t("hc_tk_doc_show")),
    edit: str = typer.Option("", "--edit", help=t("hc_tk_doc_edit")),
    body: str = typer.Option("", "--body", "-b", help=t("hc_tk_doc_body")),
    delete: str = typer.Option("", "--delete", help=t("hc_tk_doc_delete")),
    # `-p`는 안 붙인다 — 이미 `--port`가 쓰고 있어 한 글자가 두 뜻이 된다(test_cli_surface).
    project: str = typer.Option("", "--project", help=t("hc_tk_doc_project")),
    team: str = typer.Option("", "--team", help=t("hc_tk_doc_team")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_doc

    raise typer.Exit(run_doc(new, show, edit, body, delete, project, team, json_out))


@ticket_app.command("doctor", help=t("hc_tk_doctor"))
def ticket_doctor(
    recover: bool = typer.Option(False, "--recover", help=t("hc_tk_doctor_recover")),
    json_out: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.ticket import run_doctor

    raise typer.Exit(run_doctor(recover, json_out))


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
    agent: str = typer.Option("", "--agent", help="default agent for this window; overrides the global --agent option"),
    isolated: bool = typer.Option(False, "--isolated", help="start a dedicated server for this agent"),
    install: bool = typer.Option(
        False, "--install", help="install the native window before opening (a first run installs it on its own)"
    ),
) -> None:
    """Open Asgard Studio. 프로젝트 안이 아니어도 열린다 — 작업 공간은 창에서 고른다."""
    from ..commands.studio import install_shell, run_studio

    if install:
        code = install_shell()
        if code:
            raise typer.Exit(code)

    raise typer.Exit(
        run_studio(
            port=port,
            open_browser=not no_open,
            prefer_native=not browser,
            view=view,
            root=root or None,
            agent=agent or None,
            isolated=isolated,
        )
    )


@open_app.command("map", help=t("hc_open_map"))
def open_map(
    no_open: bool = typer.Option(False, "--no-open", help=t("hc_no_browser")),
    json_: bool = typer.Option(False, "--json", help=t("hc_json")),
) -> None:
    from ..commands.map import run_map_view

    raise typer.Exit(run_map_view(open_browser=not no_open, json_out=json_))


@open_app.command("memory", help=t("hc_open_memory"))
def open_memory(
    port: int = typer.Option(8765, "--port", "-p", help=t("hc_port")),
    no_open: bool = typer.Option(False, "--no-open", help=t("hc_no_browser")),
) -> None:
    from ..commands.memory_dashboard import run_dashboard

    raise typer.Exit(run_dashboard(port=port, open_browser=not no_open))
