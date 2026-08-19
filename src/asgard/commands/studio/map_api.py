"""맵 창구 — 어느 뿌리의 관계 그래프를 볼 것인가, 그리고 그 자료.

맵은 창이었다가 이 창의 화면이 됐다. 자료를 만드는 쪽(`map_graph.graph`)은 그대로 두고 여기서는
**읽기만** 한다. 그것이 이 모듈의 경계다: 그래프 상태 파일은 `<뿌리>/.asgard/state/` 에 쓰이므로,
남의 저장소를 스캔하면 거기에 파일을 만들게 된다(AGENTS.md 의 짝 저장소 규칙이 금지하는 것).
그래서 스캔이 안 된 뿌리는 대신 스캔하지 않고 409 `map_unscanned` 와 처방을 낸다.

뿌리 목록의 출처는 셋이고 합집합이다 — 지금 창이 선 자리(session), 스튜디오 등록부(workspace),
`paths.additional_roots` 선언(declared). 한 자리가 여러 출처에 있으면 먼저 든 출처가 우선한다.
"""

from __future__ import annotations

import os

from ...map_graph.graph import _STATE_RELATIVE, GraphError, graph_state
from ...map_graph.view import graph_payload
from .. import loopback
from .boundary import workspace_label


def roots(current: str) -> list[dict]:
    """볼 수 있는 뿌리들 — `{root, name, current, scanned, source}`.

    같은 자리를 realpath 로 접는다. 심링크와 `/var`→`/private/var` 같은 자리는 문자열로는 다른
    경로라, 접지 않으면 선택기에 같은 프로젝트가 두 줄로 뜬다.

    사라진 자리는 뺀다 — 등록부에는 지운 임시 디렉터리가 남아 있고, 그것을 그대로 내면 눌러도
    아무 일도 안 일어나는 줄이 선택기에 쌓인다."""
    from ... import settings
    from .. import studio_store

    here = os.path.realpath(current)
    found: dict[str, dict] = {}

    def offer(candidate: str, name: str, source: str) -> None:
        if not candidate:
            return
        target = os.path.realpath(os.path.expanduser(candidate))
        if target in found or not os.path.isdir(target):
            return
        found[target] = {
            "root": target,
            "name": name or os.path.basename(target) or target,
            "current": target == here,
            "scanned": os.path.isfile(os.path.join(target, *_STATE_RELATIVE.parts)),
            "source": source,
        }

    offer(here, workspace_label(here), "session")
    for row in studio_store.list_projects(current):
        offer(str(row.get("root") or ""), str(row.get("name") or ""), "workspace")
    for declared in settings.declared_roots(current):
        offer(declared, "", "declared")
    return list(found.values())


def _graph(params: dict[str, list[str]], root: str) -> tuple[int, str, bytes]:
    wanted = (params.get("root") or [""])[0].strip()
    target = os.path.realpath(os.path.expanduser(wanted)) if wanted else os.path.realpath(root)
    row = next((entry for entry in roots(root) if entry["root"] == target), None)
    if row is None:
        # 질의가 임의 경로를 받으면 이 창구는 파일 시스템 탐색기가 된다 — 목록에 있는 자리만 연다.
        return loopback.api_error(
            403,
            "map_root_unknown",
            "목록에 없는 뿌리예요 — 맵은 열어 둔 프로젝트만 봐요",
            remedy="창의 프로젝트 목록에서 고르거나 `asgard root add` 로 먼저 선언하세요",
            detail={"root": target},
        )
    try:
        state = graph_state(target)
    except (GraphError, OSError, ValueError) as exc:
        return loopback.error_result(exc, surface="map", root=target)
    if state is None:
        # 대신 스캔하지 않는다 — 스캔은 그 뿌리 안에 상태 파일을 쓴다.
        return loopback.api_error(
            409,
            "map_unscanned",
            f"{row['name']} 에는 아직 관계 그래프가 없어요",
            remedy="그 뿌리에서 `asgard map scan` 을 한 번 돌리세요",
            detail={"root": target},
        )
    try:
        return loopback.json_body(200, graph_payload(target, state))
    except (GraphError, OSError, ValueError, KeyError) as exc:
        return loopback.error_result(exc, surface="map", root=target)


def dispatch(
    method: str, path: str, params: dict[str, list[str]] | None = None, root: str | None = None
) -> tuple[int, str, bytes]:
    if method not in ("GET", "HEAD"):
        return 405, "text/plain; charset=utf-8", b"method not allowed"
    params = params or {}
    here = os.path.abspath(root or os.getcwd())
    if path == "/api/map/roots":
        return loopback.json_body(200, {"roots": roots(here), "current": os.path.realpath(here)})
    if path == "/api/map/graph":
        return _graph(params, here)
    return 404, "text/plain; charset=utf-8", b"not found"
