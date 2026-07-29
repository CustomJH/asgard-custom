"""리랭크 QPP 게이트 문턱 보정 — **개발 집합(S)에서만** 뽑는다.

왜 이 스크립트가 따로 있는가. `RERANK_DISPERSION_FLOOR` 를 held-out(M·V2) 점수를 보며
고르면 그 held-out 은 그 순간 개발 집합이 되고, REPORT.md 의 "일반화 검증" 절이 증명하던
것이 사라진다. 보고서가 스스로 경계한 그 행동이다. 그래서 문턱을 뽑는 자리를 코드로 분리하고,
입력을 S 로 못박는다.

보정 규칙 (과적합 방지를 위해 의도적으로 둔하게):

    floor = min{ dispersion(q) : q ∈ S, 리랭크가 그 질의를 0→1 로 **이긴** 경우 }

즉 "리랭크가 실제로 값을 한 질의는 하나도 안 막는다"를 **구성으로** 보장하는 가장 큰 문턱이다.
S 점수를 최대화하는 값을 찾지 않는다 — 그러면 30문항 위의 2문항을 좇는 그 과적합이 된다.
이 규칙은 S 에서 리랭크의 이득을 정의상 보존하고, 그 아래(안 갈리는 질의)에서만 기권한다.

측정하는 것: 문항마다 리랭크 ON/OFF 를 **같은 인덱스**에 대고 돌려 짝지은 결과를 얻고,
그때 실제로 관측된 변동계수를 같이 적는다. 짝지은 A/B 라 인덱싱 잡음이 상쇄된다.

실행:
    .venv/bin/python benchmarks/longmemeval/calibrate_dispersion.py \
        --data ~/.cache/.../longmemeval_s_cleaned.json --out calibration-dispersion.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from harness import RETRIEVE_K, recall_any, session_text  # noqa: E402


def _probe_one(entry: dict, workdir: str) -> dict | None:
    """문항 하나 — 같은 인덱스에 ON/OFF 두 번 회수하고 그때의 분산을 기록한다."""
    from asgard import memory
    from asgard.memory import recall as _recall

    d = os.path.join(workdir, "mem")
    os.environ["ASGARD_MEMORY_DIR"] = d
    memory.ensure_home(d)

    sessions = entry.get("haystack_sessions") or []
    session_ids = entry.get("haystack_session_ids") or []
    slug_to_session: dict[str, str] = {}
    for sid, turns in zip(session_ids, sessions, strict=False):
        text = session_text(turns).strip()
        if not text:
            continue
        title = memory._fm_value(next((ln.strip() for ln in text.splitlines() if ln.strip()), "untitled"))[:80]
        slug = memory.slugify(title)
        if slug in slug_to_session:
            slug = f"{slug}-{len(slug_to_session)}"
        meta = {"title": title, "kind": "note", "created": memory._today(), "updated": memory._today()}
        memory._atomic_write(memory._page_path(d, slug), memory.render_page(meta, text))
        slug_to_session[slug] = sid
    memory.reindex(d)

    question = entry.get("question", "")
    gold = set(entry.get("answer_session_ids") or [])

    # 관측된 분산을 가로챈다. 게이트 자체는 꺼 둔 상태로 재야(floor=0) 리랭크가 무엇을
    # 했는지와 그때의 분산이 **같은 실행**에서 나온다.
    seen: list[float] = []
    original = _recall._dispersion

    def _spy(scores: list[float]) -> float:
        value = original(scores)
        seen.append(value)
        return value

    def _retrieve() -> list[str]:
        hits = memory.query(question, k=RETRIEVE_K, d=d, track=False)
        out: list[str] = []
        for hit in hits:
            sid = slug_to_session.get(str(hit.get("slug") or ""))
            if sid and sid not in out:
                out.append(sid)
        return out

    _recall._dispersion = _spy
    os.environ["ASGARD_MEMORY_RERANK_DISPERSION"] = "0"
    try:
        os.environ["ASGARD_MEMORY_RERANK"] = "on"
        seen.clear()
        on = _retrieve()
        dispersion = seen[0] if seen else None
        os.environ["ASGARD_MEMORY_RERANK"] = "off"
        off = _retrieve()
    finally:
        _recall._dispersion = original

    if dispersion is None:
        return None  # 리랭크가 길이 게이트에서 아예 안 켜진 문항 — 이 축의 표본이 아니다
    return {
        "question_id": entry.get("question_id"),
        "question_type": entry.get("question_type"),
        "dispersion": round(float(dispersion), 6),
        "hit_on": recall_any(on, gold, 5),
        "hit_off": recall_any(off, gold, 5),
    }


def calibrate(rows: list[dict]) -> dict:
    """리랭크가 이긴 질의를 하나도 안 잃는 가장 큰 문턱."""
    wins = [r for r in rows if r["hit_on"] > r["hit_off"]]
    losses = [r for r in rows if r["hit_on"] < r["hit_off"]]
    ties = [r for r in rows if r["hit_on"] == r["hit_off"]]
    floor = min((r["dispersion"] for r in wins), default=0.0)
    # 부동소수 경계에서 이긴 질의가 아슬아슬하게 막히지 않도록 문턱을 아주 조금 낮춘다.
    floor = max(0.0, floor * 0.99)
    return {
        "rule": "floor = 0.99 × min(dispersion over S questions where rerank flipped 0→1)",
        "floor": round(floor, 6),
        "samples": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "ties": len(ties),
        "win_dispersions": sorted(round(r["dispersion"], 4) for r in wins),
        "loss_dispersions": sorted(round(r["dispersion"], 4) for r in losses),
        "abstain_share": round(sum(1 for r in rows if r["dispersion"] < floor) / len(rows), 4) if rows else 0.0,
        "wins_blocked": sum(1 for r in wins if r["dispersion"] < floor),
        "losses_blocked": sum(1 for r in losses if r["dispersion"] < floor),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="LongMemEval **S** (개발 집합) 경로")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "calibration-dispersion.json"))
    args = parser.parse_args()

    if "_s_" not in os.path.basename(args.data):
        print(f"거부: 보정은 개발 집합(S)에서만 한다 — 받은 파일: {os.path.basename(args.data)}", file=sys.stderr)
        return 2

    os.environ["ASGARD_MEMORY_SEMANTIC"] = "on"
    os.environ["ASGARD_MEMORY_INJECT"] = "off"

    with open(args.data, encoding="utf-8") as handle:
        entries = json.load(handle)
    if args.limit:
        entries = entries[: args.limit]

    rows: list[dict] = []
    started = time.monotonic()
    for index, entry in enumerate(entries, 1):
        workdir = tempfile.mkdtemp(prefix="lme-cal-")
        try:
            row = _probe_one(entry, workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if row is not None:
            rows.append(row)
        if index % 25 == 0 or index == len(entries):
            elapsed = time.monotonic() - started
            print(f"[{index}/{len(entries)}] 리랭크 발동 표본 {len(rows)} ({elapsed / index:.1f}s/문항)", flush=True)

    summary = calibrate(rows)
    payload = {
        "dataset": os.path.basename(args.data),
        "seconds": round(time.monotonic() - started, 1),
        **summary,
        "rows": rows,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
