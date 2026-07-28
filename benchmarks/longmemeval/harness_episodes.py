"""LongMemEval 회수 벤치 — **에피소드 레인**. 개인 위키가 아니라 세션 원문 검색을 잰다.

왜 따로 재는가: 제품에는 회수 경로가 하나가 아니다. `harness.py` 가 재는 것은 개인 위키
`memory.query()`(4스트림 + 구절 리랭크)이고, 실제 대화 회상은 `agent.episodes.search()`
(FTS trigram + lexical 스캔 2스트림 RRF, 시맨틱·리랭크 없음)가 맡는다. 앞의 수치를 뒤의
성능인 양 말하면 안 된다 — 그래서 같은 문항·같은 지표로 이쪽도 잰다.

프로토콜은 `harness.py` 와 동일하다 (문항별 격리 인덱스, recall_any@K, NDCG@10, MRR).
다른 것은 적재 단위뿐이다: 세션을 페이지가 아니라 **턴**으로 넣고, 세션 id 를 턴의 sid 로
달아 회수 결과를 세션 단위로 되돌린다.

실행: .venv/bin/python benchmarks/longmemeval/harness_episodes.py --data <path> [--limit N]
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
sys.path.insert(0, os.path.dirname(__file__))

from harness import K_VALUES, RETRIEVE_K, mrr, ndcg, recall_any, summarize  # noqa: E402


def turn_pairs(turns: list[dict]) -> list[tuple[str, str]]:
    """세션의 role 열을 (요청, 응답) 짝으로 접는다 — 에피소드 저장소의 단위가 그것이다.

    사용자 발화가 연속되면 앞의 것은 빈 응답으로 남기지 않고 이어 붙인다. 응답 없는 턴은
    저장소가 조용히 버리므로(append_turn 계약) 그대로 두면 그 발화가 통째로 사라진다."""
    pairs: list[tuple[str, str]] = []
    pending: list[str] = []
    for turn in turns:
        role, content = str(turn.get("role", "")), str(turn.get("content", ""))
        if not content.strip():
            continue
        if role == "assistant" and pending:
            pairs.append(("\n".join(pending), content))
            pending = []
        elif role == "assistant":
            pairs.append(("", content))
        else:
            pending.append(content)
    if pending:  # 응답 없이 끝난 꼬리 — 버리지 않고 요청만 실어 보낸다
        pairs.append(("\n".join(pending), ""))
    return pairs


def run_one(entry: dict, workdir: str) -> dict:
    """문항 하나 — 격리된 에피소드 저장소에 세션을 턴으로 넣고 질문으로 회수한다."""
    from asgard.agent import episodes
    from asgard.agent.turn_store import store_path

    root = os.path.join(workdir, "project")
    os.makedirs(root, exist_ok=True)
    path = store_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    sessions = entry.get("haystack_sessions") or []
    session_ids = entry.get("haystack_session_ids") or []
    indexed: set[str] = set()
    stamp = 0.0
    # 벌크 적재 — append_turn 은 턴마다 파일을 열고 편집기를 돌린다. 최종 상태가 같은
    # 원문을 한 번에 써 두고 sync 를 한 번 돌리는 편이 훨씬 싸다 (harness.py 와 같은 취지).
    with open(path, "w", encoding="utf-8") as handle:
        for sid, turns in zip(session_ids, sessions, strict=False):
            for request, response in turn_pairs(turns):
                if not response.strip():
                    response = "(응답 없음)"  # 저장소가 빈 응답 턴을 버리므로 자리를 채운다
                stamp += 1.0
                handle.write(
                    json.dumps(
                        {"ts": stamp, "quest": "", "sid": str(sid), "request": request, "response": response},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                indexed.add(str(sid))

    hits = episodes.search(root, entry.get("question", ""), k=RETRIEVE_K * 4)
    retrieved: list[str] = []
    for hit in hits:  # 한 세션이 여러 턴으로 흩어져 있으므로 세션 단위로 접는다
        sid = str(hit.get("sid") or "")
        if sid and sid not in retrieved:
            retrieved.append(sid)

    gold = set(entry.get("answer_session_ids") or [])
    return {
        "question_id": entry.get("question_id"),
        "question_type": entry.get("question_type"),
        "indexed": len(indexed),
        **{f"recall_any_at_{k}": recall_any(retrieved, gold, k) for k in K_VALUES},
        "ndcg_at_10": ndcg(retrieved, gold, 10),
        "mrr": mrr(retrieved, gold),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--only-type", default="")
    parser.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results-episodes.json"))
    args = parser.parse_args()

    os.environ["ASGARD_MEMORY_INJECT"] = "off"

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
        workdir = tempfile.mkdtemp(prefix="lme-ep-")
        try:
            rows.append(run_one(entry, workdir))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if index % 10 == 0 or index == len(entries):
            done = summarize(rows)["overall"]
            print(
                f"[{index}/{len(entries)}] R@5={done['recall_any_at_5']:.3f} "
                f"R@10={done['recall_any_at_10']:.3f} MRR={done['mrr']:.3f} "
                f"({(time.monotonic() - started) / index:.1f}s/문항)",
                flush=True,
            )

    report = {
        "dataset": os.path.basename(args.data),
        "lane": "episodes (FTS trigram + lexical scan, 시맨틱·리랭크 없음)",
        "only_type": args.only_type,
        "offset": args.offset,
        "limit": args.limit,
        "argv": sys.argv[1:],  # 실험군은 파일명이 아니라 파일 내용이 밝힌다
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
