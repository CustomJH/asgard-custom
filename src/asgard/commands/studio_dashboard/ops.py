"""CLI 운영 서브커맨드 — list/path. 생성 파이프라인(new/refine/open)은 CUS-261 소유."""

from __future__ import annotations

import json as _json

from ... import ui
from .data import ensure_home, projects_data, studio_dir


def run_list(json_out: bool = False) -> int:
    ensure_home()
    rows = projects_data()
    if json_out:
        print(_json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        ui.step("스튜디오 프로젝트 없음 — `asgard studio` 로 대시보드를 열거나, 생성 파이프라인(CUS-261)을 기다리세요")
        return 0
    for r in rows:
        line = f"{r['slug']}  ·  {r['name']}  ·  artifacts {r['artifacts']}"
        if r["updated"]:
            line += f"  ·  {r['updated']}"
        ui.step(line)
    return 0


def run_path() -> int:
    print(studio_dir())
    return 0
