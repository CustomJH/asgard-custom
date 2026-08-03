"""폴더에 갇혀 있던 기획을 워크스페이스로 들여오는 레인.

정본이 `<프로젝트>/.asgard/plan/plans.json` 이던 시절의 파일을 한 번만 옮겨 온다. 이 레인이
`store` 와 갈라져 있는 이유는 수명이 다르기 때문이다 — 문서 형상은 계속 쓰이고, 반입은
그 폴더마다 한 번 돌고 표식 파일을 남긴 뒤 다시 안 돈다.

**원본은 안 지운다.** 반입이 잘못됐을 때 돌아갈 곳이 있어야 하고, 그 폴더를 아직 옛 버전으로
여는 사람이 있을 수 있다.
"""

from __future__ import annotations

import os
from typing import Any

from ..io_files import read_json, write_json
from . import intake, store


def pending_roots(roots: list[str]) -> list[str]:
    """아직 안 들여온 폴더 기획을 든 자리들 — 창이 '들여올까요?'를 물을 근거."""
    return [
        root
        for root in roots
        if root and os.path.isfile(store.project_store_path(root)) and not os.path.isfile(_import_mark(root))
    ]


def import_root(root: str, *, force: bool = False) -> dict[str, Any]:
    """폴더 하나의 기획을 워크스페이스로 들여온다.

    두 번 불러도 두 번 안 들어온다 — 표식 파일이 이미 들여왔다는 것을 적는다. 들어온 기획은
    그 폴더를 `root` 로 가리킨다(있는 자리가 아니라 링크). 돌려주는 값의 `imported` 는 반입이
    돌았는가이고, 못 돌았으면 `reason` 에 사람이 읽을 이유가 든다."""
    root = os.path.abspath(root)
    source = store.project_store_path(root)
    out: dict[str, Any] = {"root": root, "imported": False, "plans": 0, "reason": ""}
    if not os.path.isfile(source):
        out["reason"] = "이 폴더에는 기획 파일이 없어요"
        return out
    if os.path.isfile(_import_mark(root)) and not force:
        out["reason"] = "이미 들여온 기획이에요"
        return out
    raw = read_json(source)
    if not isinstance(raw, dict):
        out["reason"] = "기획 파일을 읽지 못했어요"
        return out
    if raw.get("schema") != store.SCHEMA_VERSION:
        out["reason"] = "옛 형상이라 옮길 것이 없어요"
        _mark_imported(root, 0)
        return out
    try:
        incoming = store.checked_state(raw)["plans"]
    except ValueError as exc:
        out["reason"] = f"기획 파일이 정본 형상이 아니에요: {exc}"
        return out
    added = store.adopt(incoming, root)
    _mark_imported(root, added)
    out.update({"imported": True, "plans": added, "source": source})
    return out


def _import_mark(root: str) -> str:
    return os.path.join(os.path.abspath(root), ".asgard", "plan", "imported.json")


def _mark_imported(root: str, count: int) -> None:
    write_json(_import_mark(root), {"imported_at": intake.stamp(), "plans": count})
