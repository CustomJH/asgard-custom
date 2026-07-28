"""LongMemEval-S 회수 벤치 — asgard `query()` 를 공개 자로 잰다.

왜 이 벤치인가: asgard 자체 벤치는 전부 자작 코퍼스라 "우리 기준으로 좋다"밖에 못 말한다.
LongMemEval-S 는 500문항·문항당 ~48세션이고, **LLM 을 루프에 안 넣는 순수 회수 평가**라
결정론인 asgard query() 로 그대로 재현 가능하다 (판정자 편차가 안 낀다).

프로토콜은 ref/agentmemory/benchmark/longmemeval-bench.ts 를 그대로 옮겼다 — 남이 정한 자로
재야 자기 평가가 아니다:
  · 세션 텍스트 = "role: content" 를 줄바꿈으로 이은 것
  · 문항마다 **격리된** 인덱스 (교차 오염 금지)
  · recall_any@K = gold 세션 중 **하나라도** 상위 K 에 있으면 1
  · NDCG@10, MRR 동일 정의

주의 — 임베더가 다르다. agentmemory 는 all-MiniLM-L6-v2(384d, torch), asgard 는
model2vec potion-multilingual-128M(256d, torch 무의존)이다. 수치를 나란히 놓을 때
이 차이를 빼고 말하면 안 된다.

실행: .venv/bin/python benchmarks/longmemeval/harness.py --data <path> [--limit N]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

K_VALUES = (5, 10, 20)
RETRIEVE_K = 20  # 상위 K 까지만 지표에 쓴다 — R@20 이 최대 K


def session_text(turns: list[dict]) -> str:
    return "\n".join(f"{t.get('role', '')}: {t.get('content', '')}" for t in turns)


def recall_any(retrieved: list[str], gold: set[str], k: int) -> float:
    return 1.0 if gold & set(retrieved[:k]) else 0.0


def dcg(rels: list[bool], k: int) -> float:
    return sum((1.0 if rel else 0.0) / math.log2(i + 2) for i, rel in enumerate(rels[:k]))


def ndcg(retrieved: list[str], gold: set[str], k: int) -> float:
    ideal = dcg([True] * min(k, len(gold)), k)
    return dcg([rid in gold for rid in retrieved[:k]], k) / ideal if ideal else 0.0


def mrr(retrieved: list[str], gold: set[str]) -> float:
    return next((1.0 / (i + 1) for i, rid in enumerate(retrieved) if rid in gold), 0.0)


def run_one(entry: dict, workdir: str, *, kind: str = "note", event_dates: bool = False) -> dict:
    """문항 하나 — 격리된 메모리에 세션을 넣고 질문으로 회수한다."""
    from asgard import memory

    d = os.path.join(workdir, "mem")
    os.environ["ASGARD_MEMORY_DIR"] = d
    memory.ensure_home(d)

    sessions = entry.get("haystack_sessions") or []
    session_ids = entry.get("haystack_session_ids") or []
    # 세션 날짜는 본문이 아니라 메타로 온다 ("2022/12/19 (Mon) 12:04"). 텍스트 접지로는 안 잡히므로
    # 이 축을 재려면 그 날짜를 event 로 직접 넣어야 한다 — agentmemory 의 TemporalGrounder 와 같은 취지.
    dates = entry.get("haystack_dates") or []
    slug_to_session: dict[str, str] = {}
    # 벌크 적재 — 페이지를 다 쓴 뒤 reindex 를 **한 번** 돌린다.
    # memory.add 는 페이지마다 인덱스와 목차를 통째로 다시 만든다(O(n²) + maps 재생성). 그 비용은
    # 회수 품질과 무관한 쓰기 경로의 성질이라, 벤치에서는 같은 최종 인덱스를 훨씬 싸게 만든다.
    for sid, turns in zip(session_ids, sessions, strict=False):
        text = session_text(turns).strip()
        if not text:
            continue
        title = memory._fm_value(next((ln.strip() for ln in text.splitlines() if ln.strip()), "untitled"))[:80]
        slug = memory.slugify(title)
        if slug in slug_to_session:  # 같은 첫 줄을 가진 세션 — 충돌 회피
            slug = f"{slug}-{len(slug_to_session)}"
        meta = {"title": title, "kind": kind, "created": memory._today(), "updated": memory._today()}
        if event_dates:
            raw = str(dates[len(slug_to_session)] if len(slug_to_session) < len(dates) else "")
            if grounded := memory.ground_event_date(raw):
                meta["event"] = grounded
        memory._atomic_write(memory._page_path(d, slug), memory.render_page(meta, text))
        slug_to_session[slug] = sid
    memory.reindex(d)

    hits = memory.query(entry.get("question", ""), k=RETRIEVE_K, d=d, track=False)
    retrieved: list[str] = []
    for hit in hits:
        sid = slug_to_session.get(str(hit.get("slug") or ""))
        if sid and sid not in retrieved:  # 세션 단위 중복 제거 (한 세션 = 한 페이지지만 방어적으로)
            retrieved.append(sid)

    gold = {g for g in (entry.get("answer_session_ids") or [])}
    return {
        "question_id": entry.get("question_id"),
        "question_type": entry.get("question_type"),
        "indexed": len(slug_to_session),
        **{f"recall_any_at_{k}": recall_any(retrieved, gold, k) for k in K_VALUES},
        "ndcg_at_10": ndcg(retrieved, gold, 10),
        "mrr": mrr(retrieved, gold),
    }


def summarize(rows: list[dict]) -> dict:
    def avg(key: str, subset: list[dict]) -> float:
        return round(sum(r[key] for r in subset) / len(subset), 4) if subset else 0.0

    metrics = [f"recall_any_at_{k}" for k in K_VALUES] + ["ndcg_at_10", "mrr"]
    by_type: dict[str, dict] = {}
    for row in rows:
        by_type.setdefault(str(row["question_type"]), []).append(row)  # type: ignore[arg-type]
    return {
        "n": len(rows),
        "overall": {m: avg(m, rows) for m in metrics},
        "by_type": {
            qtype: {"count": len(subset), **{m: avg(m, subset) for m in metrics}}
            for qtype, subset in sorted(by_type.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--limit", type=int, default=0)
    # 샤드 실행용 — 전량 한 번에 돌리면 실행 환경의 시간 상한에 걸린다. 결과는 merge.py 가 합친다.
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results.json"))
    parser.add_argument("--semantic", default="on", choices=["on", "off"])
    parser.add_argument("--kind", default="note")  # reference 로 두면 최신성 보정(TEMPORAL_KINDS)이 켜진다
    parser.add_argument("--event-dates", action="store_true")  # 세션 날짜를 event 메타로 심는다
    parser.add_argument("--only-type", default="")  # 한 유형만 (예: temporal-reasoning)
    args = parser.parse_args()

    os.environ["ASGARD_MEMORY_SEMANTIC"] = args.semantic
    os.environ["ASGARD_MEMORY_INJECT"] = "off"  # 주입면은 이 벤치와 무관하다

    with open(args.data, encoding="utf-8") as handle:
        entries = json.load(handle)
    if args.only_type:
        entries = [e for e in entries if e.get("question_type") == args.only_type]
    entries = entries[args.offset :]
    if args.limit:
        entries = entries[: args.limit]

    rows: list[dict] = []
    started = time.monotonic()
    for index, entry in enumerate(entries, 1):
        workdir = tempfile.mkdtemp(prefix="lme-")
        try:
            rows.append(run_one(entry, workdir, kind=args.kind, event_dates=args.event_dates))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if index % 10 == 0 or index == len(entries):
            done = summarize(rows)["overall"]
            elapsed = time.monotonic() - started
            print(
                f"[{index}/{len(entries)}] R@5={done['recall_any_at_5']:.3f} "
                f"R@10={done['recall_any_at_10']:.3f} MRR={done['mrr']:.3f} "
                f"({elapsed / index:.1f}s/문항)",
                flush=True,
            )

    report = {
        "dataset": os.path.basename(args.data),
        "semantic": args.semantic,
        "kind": args.kind,
        "event_dates": args.event_dates,
        "seconds": round(time.monotonic() - started, 1),
        **summarize(rows),
        "rows": rows,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
