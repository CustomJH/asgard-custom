"""런타임 상태 기록 IO — .asgard/state/ 아래 텔레메트리·write sentinel.

classify 텔레메트리(append-only)와 네이티브 write 흔적 기록. 게이트·감사가 읽는 파일이라
계약 경로를 바꾸지 않는다. 전부 fail-open — 기록 장애가 본 작업을 죽이면 안 된다.
"""

from __future__ import annotations

import json
import os
import time


def _log_classify(root: str, entry: dict) -> None:
    """classify 텔레메트리 — predicted vs actual 감사 데이터. append-only, fail-open."""
    try:
        d = os.path.join(root, ".asgard", "state")  # 런타임 텔레메트리 — state/ 격리
        os.makedirs(d, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **entry}
        with open(os.path.join(d, "classify.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _record_writes(root: str, sid: str, writes: list[str]) -> None:
    """write-sentinel 대응 — 네이티브 세션의 write 흔적을 게이트가 보는 파일에 기록.
    temp+rename 원자 쓰기 — 크래시 절단 파일은 게이트가 못 읽어 fail-open(orphan write 통과)이 된다."""
    if not writes:
        return
    d = os.path.join(root, ".asgard", "state")  # verifier-gate 읽기 경로와 동일 유지 (계약)
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, f"writes-{sid}.json")
    try:
        prev = json.load(open(f))
    except Exception:
        prev = []
    merged = prev + [w for w in writes if w not in prev]
    tmp = f"{f}.{os.getpid()}.tmp"
    json.dump(merged[:500], open(tmp, "w"))
    os.replace(tmp, f)
