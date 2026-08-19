"""자립형 그래프 뷰 — 외부 리소스 0의 단일 HTML로 관계 그래프를 그린다.

`asgard open map`이 연다. 산출물은 런타임 상태
(`.asgard/state/map-view.html`)로, git에 추적되지 않는다.
"""

from __future__ import annotations

import base64
import json
import os
from importlib.resources import files
from pathlib import Path

from .bridge import related_records
from .evidence import node_kinds
from .graph import GraphError, _atomic_state_write, _state_file, graph_state

_VIEW_RELATIVE = Path(".asgard") / "state" / "map-view.html"

_TEMPLATE_ASSET = "map_view.html"


def _template() -> str:
    """자립형 뷰의 HTML 뼈대 (assets/map_view.html, 1,337줄).

    파이썬 문자열이 아니라 자산 파일인 이유는 그것이 파이썬이 아니어서다 — 소스에 두면 이 모듈을
    여는 모든 도구가 그 줄들을 같이 읽고, 편집기는 HTML·CSS·JS 를 문자열 한 덩이로 본다.
    원복 백업은 `view_legacy._TEMPLATE_LEGACY` — 되돌리려면 이 함수가 그것을 돌려주면 된다."""
    return (files("asgard") / "assets" / _TEMPLATE_ASSET).read_text(encoding="utf-8")


def _logo_data_uri() -> str:
    """위그드라실 엠블럼(yggdrasil-mark.png)을 데이터 URI로 — 실패 시 빈 값(img는 onerror로 숨김)."""
    try:
        raw = (files("asgard") / "assets" / "yggdrasil-mark.png").read_bytes()
    except Exception:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def graph_payload(root: str | os.PathLike[str], state: dict) -> dict:
    """그리는 쪽이 읽는 자료 — 굽는 문(`build_view`)과 창구(`studio.map_api`)가 함께 쓴다.

    문이 둘인데 자료를 두 자리에서 조립하면 한쪽에만 칸이 늘어난다. `kinds` 가 그 예다: 그리는
    쪽이 종류 목록을 손으로 적어 두고 있었고, 그 목록에 없던 `service` 는 범례에도 레인에도
    서지 못한 채 사라졌다. 이제 종류의 정본은 `evidence.node_kinds()` 하나다.
    """
    records: dict[str, list[dict]] = {}
    for node in state["nodes"]:
        if node["kind"] == "file":
            continue
        found = related_records(root, node)
        if found:
            records[node["id"]] = [{"title": r.title, "file": r.file, "match": r.match} for r in found]
    return {
        "counts": state["counts"],
        "revision": state.get("revision", ""),
        "kinds": list(node_kinds()),
        "nodes": state["nodes"],
        "edges": state["edges"],
        "records": records,
    }


def build_view(root: str | os.PathLike[str]) -> str:
    state = graph_state(root)
    if state is None:
        raise GraphError("relation graph state missing — run `asgard map scan` first")
    data = json.dumps(graph_payload(root, state), ensure_ascii=False).replace("</", "<\\/")
    return _template().replace("__DATA__", data).replace("__LOGO__", _logo_data_uri())


def write_view(root: str | os.PathLike[str]) -> str:
    base = Path(root).resolve()
    path = _state_file(base, _VIEW_RELATIVE.name, create=True)
    _atomic_state_write(base, path, build_view(base))
    return str(path)
