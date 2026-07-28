"""LongMemEval-V2 회수 어댑터 — held-out 축: 질문도 코퍼스도 리랭크 설계에 쓰이지 않았다.

V1 과 다른 점을 먼저 밝힌다:
  · V2 는 **정답 궤적 라벨이 없다.** 질문에 `answer` 문자열과 `eval_function` 만 있고,
    "어느 궤적에 답이 있는지"는 배포되지 않는다 (원래 end-to-end QA 벤치다).
    그래서 여기서는 **답 문자열이 실제로 들어 있는 궤적**을 정답으로 파생시킨다.
    이건 공식 지표가 아니라 파생 지표다 — 보고할 때 반드시 그렇게 적어야 한다.
  · abstention(`*-abs`) 유형은 전제가 틀린 질문이라 정답 궤적이 존재하지 않는다. 제외한다.
  · 정답 문자열이 haystack 안에서 발견되지 않는 질문도 제외한다 (라벨을 못 만든다).

파생 라벨의 편향도 밝힌다: 정답을 **문자열 포함**으로 정의하므로, 정답이 화면에 그대로
찍히지 않고 추론으로만 얻어지는 질문은 표본에서 빠진다. 남는 표본은 원본보다 쉬운 쪽으로
치우친다. 그래도 리랭크 ON/OFF 를 **같은 표본**에 대고 재는 A/B 이므로, 두 팔의 차이를
읽는 데는 이 치우침이 상쇄된다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from harness import K_VALUES, RETRIEVE_K, mrr, ndcg, recall_any, summarize  # noqa: E402

_SEP = re.compile(r"[,;]")


def answer_phrases(answer: str, min_len: int = 3) -> list[str]:
    """평가기가 쓰는 구분자로 답을 쪼갠다. min_len 미만 조각은 버린다 —
    짧은 답("3", "yes")은 어느 궤적에나 있어서 라벨이 아니라 잡음이 된다."""
    parts = [p.strip() for p in _SEP.split(str(answer or ""))]
    return [p for p in parts if len(p) >= min_len]


def derive_gold(lowered: dict[str, str], phrases: list[str], rule: str) -> set[str]:
    """파생 정답 — 답 조각이 실제로 들어 있는 궤적.

    rule=any 는 한 조각만 있어도 정답으로 친다. 그러면 라벨이 헐거워져 궤적의 43%(평균)가
    정답이 되고, 그 상태의 R@5 는 무작위로 뽑아도 0.663 이 나온다 — 지표가 죽는다.
    rule=all 은 모든 조각이 한 궤적에 같이 있어야 정답으로 친다 (정답 비율 중앙값 0.10)."""
    if rule == "any":
        return {tid for tid, low in lowered.items() if any(p in low for p in phrases)}
    return {tid for tid, low in lowered.items() if all(p in low for p in phrases)}


def random_recall_any(n: int, gold: int, k: int) -> float:
    """무작위 k개 추출의 recall_any 기대값 — 파생 라벨이 헐거우면 이 바닥이 높아진다."""
    from math import comb

    if gold >= n or n - gold < k:
        return 1.0
    return 1.0 - comb(n - gold, k) / comb(n, k)


def trajectory_text(traj: dict, state_budget: int) -> str:
    """궤적 하나를 페이지 본문으로 — 목표·결과·상태별 url/action/thought/관측."""
    lines = [f"goal: {traj.get('goal', '')}", f"outcome: {traj.get('outcome', '')}"]
    for st in traj.get("states") or []:
        chunk = [
            f"[state {st.get('state_index')}] url: {st.get('url', '')}",
            f"action: {st.get('action') or ''}",
            f"thought: {st.get('thought') or ''}",
            str(st.get("accessibility_tree") or "")[:state_budget],
        ]
        lines.append("\n".join(c for c in chunk if c.strip()))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="V2 파일이 있는 HF 스냅샷 디렉터리")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--state-budget", type=int, default=4000)
    ap.add_argument("--rerank", choices=["on", "off"], default="on")
    ap.add_argument("--gold-rule", choices=["any", "all"], default="all")
    ap.add_argument("--min-phrase", type=int, default=5)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    os.environ["ASGARD_MEMORY_SEMANTIC"] = "on"
    os.environ["ASGARD_MEMORY_INJECT"] = "off"
    os.environ["ASGARD_MEMORY_RERANK"] = args.rerank  # 제품의 정식 스위치 — 몽키패치 아님

    from asgard import memory

    questions = [json.loads(line) for line in open(os.path.join(args.root, "questions.jsonl"), encoding="utf-8")]
    haystacks = json.load(open(os.path.join(args.root, "haystacks", "lme_v2_small.json"), encoding="utf-8"))
    print(f"questions={len(questions)} haystacks={len(haystacks)}", flush=True)

    trajectories: dict[str, dict] = {}
    with open(os.path.join(args.root, "trajectories.jsonl"), encoding="utf-8") as handle:
        for line in handle:
            t = json.loads(line)
            trajectories[t["id"]] = t
    print(f"trajectories={len(trajectories)}", flush=True)

    # abstention 은 정답 궤적이 없는 유형이다 — 회수 지표를 정의할 수 없다.
    pool = [q for q in questions if not q["question_type"].endswith("-abs") and q["id"] in haystacks]
    rows: list[dict] = []
    skipped = 0
    started = time.monotonic()

    for q in pool:
        if args.limit and len(rows) >= args.limit:
            break
        ids = haystacks[q["id"]]
        phrases = [p.lower() for p in answer_phrases(q.get("answer", ""), args.min_phrase)]
        if not phrases:
            skipped += 1
            continue
        texts = {tid: trajectory_text(trajectories[tid], args.state_budget) for tid in ids if tid in trajectories}
        lowered = {tid: text.lower() for tid, text in texts.items()}
        gold = derive_gold(lowered, phrases, args.gold_rule)
        if not gold:
            skipped += 1  # 파생 라벨을 만들 수 없는 질문 — 회수로 채점하지 않는다
            continue

        workdir = tempfile.mkdtemp(prefix="lmev2-")
        try:
            d = os.path.join(workdir, "mem")
            os.environ["ASGARD_MEMORY_DIR"] = d
            memory.ensure_home(d)
            slug_to_traj: dict[str, str] = {}
            for tid, text in texts.items():
                title = memory._fm_value(f"{trajectories[tid].get('goal', '') or tid}")[:80]
                slug = memory.slugify(title) or "t"
                if slug in slug_to_traj:
                    slug = f"{slug}-{len(slug_to_traj)}"
                meta = {"title": title, "kind": "note", "created": memory._today(), "updated": memory._today()}
                memory._atomic_write(memory._page_path(d, slug), memory.render_page(meta, text))
                slug_to_traj[slug] = tid
            memory.reindex(d)
            hits = memory.query(q["question"], k=RETRIEVE_K, d=d, track=False)
            retrieved: list[str] = []
            for hit in hits:
                tid = slug_to_traj.get(str(hit.get("slug") or ""))
                if tid and tid not in retrieved:
                    retrieved.append(tid)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        rows.append(
            {
                "question_id": q["id"],
                "question_type": q["question_type"],
                "domain": q["domain"],
                "indexed": len(slug_to_traj),
                "gold": len(gold),
                **{f"recall_any_at_{k}": recall_any(retrieved, gold, k) for k in K_VALUES},
                "ndcg_at_10": ndcg(retrieved, gold, 10),
                "mrr": mrr(retrieved, gold),
            }
        )
        if len(rows) % 10 == 0:
            done = summarize(rows)["overall"]
            print(
                f"[{len(rows)}] R@5={done['recall_any_at_5']:.3f} R@10={done['recall_any_at_10']:.3f} "
                f"MRR={done['mrr']:.3f} ({(time.monotonic() - started) / len(rows):.1f}s/문항)",
                flush=True,
            )

    baseline = (
        {
            f"recall_any_at_{k}": round(sum(random_recall_any(r["indexed"], r["gold"], k) for r in rows) / len(rows), 4)
            for k in K_VALUES
        }
        if rows
        else {}
    )
    report = {
        "dataset": "longmemeval-v2 (small haystack, derived gold)",
        "rerank": args.rerank,
        "gold_rule": args.gold_rule,
        "min_phrase": args.min_phrase,
        "state_budget": args.state_budget,
        "skipped_no_derivable_gold": skipped,
        "random_baseline": baseline,  # 파생 라벨의 바닥 — 이보다 못하면 회수가 아니라 운이다
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
