"""asgard CLI — 코드 지도. 명령 본문은 `asgard.commands.*`에 있고 여기는 표면 선언만 진다."""

import typer

from ..i18n import t
from ._app import app

# 창은 `asgard open map`이 연다 — 여기는 지도를 **만지는** 손이다(scan·trace·impact·context).
# 한 단어가 문맥에 따라 창을 열거나 도움말을 내던 시절의 `invoke_without_command`는 뺐다.
map_app = typer.Typer(
    help="the project map — where things are, what touches what, and the slice an agent gets",
    no_args_is_help=True,
)
app.add_typer(map_app, name="map")


@map_app.command(
    "scan", help="rebuild source-grounded relation evidence and retain every named scanner coverage limit"
)
def map_scan(
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.map import run_map_scan

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
    from ..commands.map import run_map_trace

    raise typer.Exit(run_map_trace(from_, depth=depth, direction=direction, kinds=kinds, json_out=json_))


@map_app.command("list", help="every node in the graph, with the id to trace from and where it came from")
def map_list(
    kind: str = typer.Option("", "--kind", help="only this kind of node, e.g. route, page, db_access, file"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.map import run_map_list

    raise typer.Exit(run_map_list(kind=kind, json_out=json_))


@map_app.command("why", help=t("hc_map_why"))
def map_why(
    query: str = typer.Argument(..., metavar="QUERY", help=t("hc_map_why_q")),
    limit: int = typer.Option(5, "--limit", help=t("hc_map_why_limit")),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.map import run_map_why

    raise typer.Exit(run_map_why(query, limit=limit, json_out=json_))


@map_app.command(
    "impact", help="revision-bound two-way impact evidence, candidates, frontiers, and next exact source reads"
)
def map_impact(
    node_id: str = typer.Argument(..., metavar="NODE_ID", help="node id, e.g. db_access:USERS or route:GET_/users"),
    depth: int = typer.Option(4, "--depth"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    from ..commands.map import run_map_impact

    raise typer.Exit(run_map_impact(node_id, depth=depth, json_out=json_))


# `map view`는 뺐다 — 창을 여는 문은 `asgard open map` 하나다.


@map_app.command("update", help="draw the project map, or redraw it after the repository has moved around")
def map_update(
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.map import run_map_update

    raise typer.Exit(run_map_update(dry_run=dry_run, json_out=json_, quiet=quiet))


# `generate` 별칭 — 첫 생성과 갱신은 한 함수다. 이름이 셋이면(`map generate`·`map update`·`setup map`)
# 사용자는 셋이 서로 다른 일을 한다고 읽는다. 근육기억은 살리고 도움말에서만 뺀다(`upgrade`→`update`와 같은 처리).
map_app.command("generate", hidden=True, help="alias of `map update`")(map_update)


@map_app.command("check", help="how far the map has drifted, and which area maps are broken — writes nothing")
def map_check(
    json_: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    from ..commands.map import run_map_check

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
    from ..commands.map import run_map_context

    raise typer.Exit(run_map_context(query, refresh=refresh, managed_only=managed_only, json_out=json_))


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
    from ..commands.map import run_setup_map

    raise typer.Exit(run_setup_map(check=check, dry_run=dry_run, json_out=json_, quiet=quiet))
