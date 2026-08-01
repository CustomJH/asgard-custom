"""asgard surface — 공개 표면 변화의 사람 표면.

계약 두 줄: ① 파괴적 변화를 먼저, 각 건에 호출부 의무를 붙여서 보여준다, ② 이 목록이
전수 증명이 아니라는 한계를 같은 화면에 넣는다 (이름 기반 후보이므로).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from .. import surface, ui
from .health import _project_root


def run_surface(*, base: str = "HEAD", json_out: bool = False, quiet: bool = False) -> int:
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)
    result = surface.diff(root, base)

    if json_out:
        print(
            json.dumps(
                {
                    "base": result.base,
                    "files_compared": result.files_compared,
                    "unparsed": list(result.unparsed),
                    "breaking": [asdict(c) for c in result.breaking],
                    "changes": [asdict(c) for c in result.changes],
                    "obligations": {k: list(v) for k, v in result.obligations.items()},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    ui.head(f"surface · 공개 표면 대조 ({result.base})")
    ui.step(f"대조한 파일 {result.files_compared}개")
    if result.unparsed:
        ui.warn(f"파싱 실패 — 미판정 {len(result.unparsed)}: {', '.join(result.unparsed[:5])}")
    if not result.changes:
        ui.ok("공개 표면 변화 없음 — 호출부 의무가 생기지 않았다")
        ui.done()
        return 0

    breaking = result.breaking
    if breaking:
        ui.phase(f"호출부가 깨진다 — {len(breaking)}건")
        for change in breaking:
            ui.warn(f"{change.qualname} ({change.path}) — {change.kind}: {change.detail}")
            sites = result.obligations.get(change.qualname.rsplit(".", 1)[-1], ())
            if sites:
                ui.step(ui.dim(f"    호출부 후보 {len(sites)}: {', '.join(sites[:6])}"))
            else:
                ui.step(ui.dim("    diff 밖 이름 일치 없음 (0건도 기록할 증거다)"))
        ui.step(ui.dim("후보는 이름 기반이다 — 동적 디스패치·getattr·문자열 참조는 못 잡고, 동명이인이 섞일 수 있다"))

    others = [c for c in result.changes if not c.breaking]
    if others:
        ui.phase(f"깨지지 않는 변화 — {len(others)}건")
        for change in others[:15]:
            ui.step(f"{change.qualname} — {change.kind}: {change.detail}")
        if len(others) > 15:
            ui.step(ui.dim(f"…그리고 {len(others) - 15}건 더"))
    ui.done()
    return 0
