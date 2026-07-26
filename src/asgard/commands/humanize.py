"""`asgard humanize` — 결정론 휴먼체 판정 CLI. 판정만 하고 고치지 않는다.

재작성은 모델의 일이라 여기서 하지 않는다 (스킬 asgard-bragi-humanize 가 이 출력을 읽고 고친다).
이 명령의 계약은 하나뿐이다: 사람이든 스킬이든 같은 판정을 본다.
"""

from __future__ import annotations

import json
import os
import sys

from .. import ui
from ..bragi import detect_lang, grade, tells

_MARK = {"S1": "✘", "S2": "▲", "S3": "·"}


def _read(target: str | None) -> tuple[str, str]:
    if target in (None, "-"):
        return sys.stdin.read(), "(stdin)"
    if not os.path.isfile(target):
        ui.fail(f"no such file: {target}")
        raise SystemExit(2)
    with open(target, encoding="utf-8") as fh:
        return fh.read(), target


def run_humanize(target: str | None = None, lang: str | None = None, as_json: bool = False) -> int:
    """반환 = 종료 코드. 0 = 등급 A(흔적 없음), 1 = 흔적 있음 — CI·훅이 그대로 쓴다."""
    text, name = _read(target)
    detected = lang or detect_lang(text)
    found = tells(text, detected)
    verdict = grade(found)

    if as_json:
        print(
            json.dumps(
                {
                    "source": name,
                    "lang": detected,
                    "grade": verdict,
                    "findings": [f._asdict() for f in found],
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0 if not found else 1

    ui.step(f"{name} · {detected} · naturalness {verdict}")
    if not found:
        ui.ok("no machine-writing tells — reads as human writing")
        return 0
    for f in found:
        print(f"    {_MARK[f.severity]} {f.severity} {f.id} ×{f.hits}")
        print(f"        {ui.dim(f.hint)}")
        if f.sample:
            print(f"        {ui.dim('e.g. ' + repr(f.sample))}")
    ui.warn(f"{len(found)} findings — the asgard-bragi-humanize skill rewrites from this list")
    return 1
