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

26-08-01 추가 — **기권 축**. 위 지표 넷은 전부 "찾았는가"만 묻는다. 논문의 다섯 능력 축 중
하나인 기권(답이 코퍼스에 없을 때 없다고 말하기)은 아무도 안 재고 있었고, 게다가 그 문항
30건이 옛 지표에서 **거꾸로 채점되고** 있었다 (아래 `is_abstention` 절). 새 산출 칸은
`answerable`·`abstention` 둘이고 기존 `overall`·`by_type` 은 정의도 값도 그대로다.

주의 — 임베더가 다르다. agentmemory 는 all-MiniLM-L6-v2(384d, torch), asgard 는
model2vec potion-multilingual-128M(256d, torch 무의존)이다. 수치를 나란히 놓을 때
이 차이를 빼고 말하면 안 된다.

실행: .venv/bin/python benchmarks/longmemeval/harness.py --data <path> [--limit N]
기권 축만: 위에 `--split mixed` (기권 30건 + 답 있는 문항 앞 120건 — 분리도를 재려면 두 무리가
같이 있어야 한다). `--split abs` 는 기권 30건만.
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
SWEEP_POINTS = 40  # 기권 문턱 스윕의 표본 문턱 수 — 사람이 읽을 표 크기


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


# ── 기권(abstention) 축 ────────────────────────────────────────────────────────
#
# 위 지표 넷은 전부 "찾았는가"만 묻는다. LongMemEval 의 다섯 능력 축 중 하나인 **기권**은
# 반대를 묻는다 — 답이 코퍼스에 없을 때 없다고 말하는가. 데이터셋은 그 문항을 따로 싣는다
# (question_id 에 `_abs` 접미, S 500문항 중 30건 — 실측 26-08-01).
#
# 이 문항들은 지금 이 하니스에서 **거꾸로 채점되고 있었다**. `_abs` 문항의
# `answer_session_ids` 는 답이 든 세션이 아니라 **답이 없는 유인(誘引) 세션**을 가리키는데
# (예: "내 햄스터 이름이 뭐지?" → 고양이 Luna 이야기가 든 세션), 그 58개 세션이 전부
# haystack 안에 들어 있다. recall_any 는 그걸 찾아오면 1점을 준다. 실측: 저장된
# `results-s-rerank-soft.json` 에서 `_abs` 30건의 R@5 는 **1.0000** 이고, 그 만점이
# 전체 평균을 0.9532(답 있는 470건) → 0.9560 으로 밀어 올렸다.
#
# 그래서 이 절은 두 가지를 한다: `_abs` 를 갈라내 **기권 지표로** 다시 재고, 답 있는 문항만의
# 지표(`answerable`)를 따로 낸다. 기존 `overall`·`by_type` 은 손대지 않는다 — 옛 산출물과
# 비교 가능해야 하고, 그 값이 무엇을 섞고 있었는지는 여기 새 칸이 말한다.


def is_abstention(entry_or_row: dict) -> bool:
    """답이 코퍼스에 없는 문항인가 — question_id 의 `_abs` 접미가 유일한 표식이다.

    데이터에 별도 플래그 칼럼이 없어 관례를 그대로 쓴다 (`answer` 필드가 "You did not
    mention this information…" 로 시작하지만 그건 문자열 관례라 접미보다 약하다)."""
    return str(entry_or_row.get("question_id") or "").endswith("_abs")


def abstention_row(hits: list[dict]) -> dict:
    """한 문항의 기권 판정 원료 — 빈손이었는가, 그리고 얼마나 자신 있었는가.

    `empty_hand` 만으로는 고칠 방향이 안 나온다. 지금 `query()` 에는 회수 기권 장치가
    아예 없어서 이 값은 답 있는 문항에서도 없는 문항에서도 똑같이 0 이다 — "못 한다"는
    말만 남고 "할 수 있는가"는 안 남는다. 그래서 점수도 같이 적는다: 1위 RRF 점수와
    1·2위 격차가 두 무리를 가른다면 문턱 하나로 기권을 만들 수 있고, 안 가른다면
    이 신호로는 못 만든다는 뜻이다 (그 판정이 AUC 다)."""
    scores = [float(h.get("score") or 0.0) for h in hits]
    return {
        "hits": len(hits),
        "empty_hand": 1.0 if not hits else 0.0,
        "top_score": round(scores[0], 6) if scores else 0.0,
        "margin": round(scores[0] - scores[1], 6) if len(scores) >= 2 else 0.0,
    }


def auc(positive: list[float], negative: list[float]) -> float:
    """양성 점수가 음성 점수보다 높을 확률 (동점 0.5) — 문턱을 안 고르고 재는 분리도.

    답 있는 문항(양성)의 점수가 답 없는 문항(음성)보다 일관되게 높아야 문턱 기권이 선다.
    0.5 는 동전 던지기 = 이 신호로는 기권을 못 만든다는 뜻이다."""
    if not positive or not negative:
        return 0.0
    wins = sum(sum(1.0 if p > n else 0.5 if p == n else 0.0 for n in negative) for p in positive)
    return round(wins / (len(positive) * len(negative)), 4)


def threshold_sweep(rows: list[dict], key: str = "top_score") -> list[dict]:
    """점수가 문턱 미만이면 기권한다 — 그 정책을 문턱마다 채점한 표.

    두 값을 나란히 놓는 것이 요점이다. 기권 정확도는 문턱을 올릴수록 오르는데, 그 대가로
    답 있는 문항까지 버린다(`오기권률`). 대가를 같이 안 적으면 "문턱 무한대 → 기권 100%"
    라는 무의미한 최적해가 이긴다."""
    ab = [r for r in rows if r.get("abstention")]
    an = [r for r in rows if not r.get("abstention")]
    if not ab or not an:
        return []
    candidates = sorted({round(float(r.get(key) or 0.0), 6) for r in rows})
    if len(candidates) > SWEEP_POINTS:  # 문턱 하나마다 한 줄이면 산출물이 표가 아니라 원자료가 된다
        step = len(candidates) / SWEEP_POINTS
        candidates = [candidates[min(int(i * step), len(candidates) - 1)] for i in range(SWEEP_POINTS)]
    out: list[dict] = []
    for t in candidates:
        # 문턱 미만이면 기권. 답 없는 문항에서 기권 = 정답, 답 있는 문항에서 기권 = 손실.
        abstained_abs = sum(1 for r in ab if float(r.get(key) or 0.0) < t)
        abstained_ans = sum(1 for r in an if float(r.get(key) or 0.0) < t)
        kept = [r for r in an if float(r.get(key) or 0.0) >= t]
        out.append(
            {
                "threshold": t,
                "abstention_accuracy": round(abstained_abs / len(ab), 4),
                "false_claim_rate": round(1 - abstained_abs / len(ab), 4),
                "false_abstention_rate": round(abstained_ans / len(an), 4),
                # 기권은 공짜가 아니다 — 버린 문항은 회수 기회를 잃는다(0점 처리).
                "answerable_recall_at_5": round(sum(r["recall_any_at_5"] for r in kept) / len(an), 4),
            }
        )
    return out


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
        # 기권 축 — `_abs` 문항에서 위 네 지표는 유인 세션을 맞힌 점수라 뜻이 뒤집혀 있다.
        "abstention": is_abstention(entry),
        **abstention_row(hits),
    }


def summarize(rows: list[dict]) -> dict:
    def avg(key: str, subset: list[dict]) -> float:
        return round(sum(r[key] for r in subset) / len(subset), 4) if subset else 0.0

    metrics = [f"recall_any_at_{k}" for k in K_VALUES] + ["ndcg_at_10", "mrr"]
    by_type: dict[str, list[dict]] = {}
    for row in rows:
        by_type.setdefault(str(row["question_type"]), []).append(row)
    ab = [r for r in rows if r.get("abstention")]
    an = [r for r in rows if not r.get("abstention")]
    return {
        "n": len(rows),
        # `overall` 은 옛 산출물과 형상·정의가 같다 — 답 없는 문항을 섞은 채로 둔다.
        # 무엇을 섞고 있었는지는 `answerable`·`abstention` 두 칸이 말한다.
        "overall": {m: avg(m, rows) for m in metrics},
        "by_type": {
            qtype: {"count": len(subset), **{m: avg(m, subset) for m in metrics}}
            for qtype, subset in sorted(by_type.items())
        },
        "answerable": {"count": len(an), **{m: avg(m, an) for m in metrics}},
        "abstention": {
            "count": len(ab),
            # 안 줘야 할 때 안 주는 비율 / 없는데 준 비율. 둘은 합이 1 이지만 둘 다 적는다 —
            # 보고서에서 어느 쪽을 인용하든 계산을 다시 하지 않게.
            "abstention_accuracy": avg("empty_hand", ab),
            "false_claim_rate": round(1 - avg("empty_hand", ab), 4) if ab else 0.0,
            # 답 있는 문항에서의 빈손 — 회수가 아예 실패한 비율. 위 값과 대조군이다.
            "answerable_empty_hand": avg("empty_hand", an),
            # `_abs` 문항이 옛 지표에서 받던 점수. 1.0 에 가까울수록 유인 세션을 정확히
            # 물어 온다는 뜻이고, 그건 회수가 잘된 게 아니라 **틀리게 확신한다**는 뜻이다.
            "distractor_recall_at_5": avg("recall_any_at_5", ab),
            "auc_top_score": auc([float(r["top_score"]) for r in an], [float(r["top_score"]) for r in ab]),
            "auc_margin": auc([float(r["margin"]) for r in an], [float(r["margin"]) for r in ab]),
            "sweep_top_score": threshold_sweep(rows, "top_score"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--limit", type=int, default=0)
    # 샤드 실행용 — 전량 한 번에 돌리면 실행 환경의 시간 상한에 걸린다. 샤드 결과는 rows 를
    # 이어 붙인 뒤 summarize() 를 다시 돌리면 합쳐진다 (전용 병합 도구는 없다).
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results.json"))
    parser.add_argument("--semantic", default="on", choices=["on", "off"])
    # 구절 리랭크 A/B — 전/후 표를 코드 되돌리기 없이 재현하기 위한 스위치.
    parser.add_argument("--rerank", default="on", choices=["on", "off"])
    # QPP 분산 게이트 A/B. "off" = 게이트 없음(도입 전 거동), 숫자 = 그 문턱,
    # 미지정 = 제품 기본값(RERANK_DISPERSION_FLOOR). 산출물이 자기 실험군을 밝히도록 기록한다.
    parser.add_argument("--dispersion", default="")
    # 게이트 모양 A/B — hard(기권) vs soft(감쇠). 산출물이 자기 실험군을 밝힌다.
    parser.add_argument("--gate", default="", choices=["", "hard", "soft"])
    parser.add_argument("--kind", default="note")  # reference 로 두면 최신성 보정(TEMPORAL_KINDS)이 켜진다
    parser.add_argument("--event-dates", action="store_true")  # 세션 날짜를 event 메타로 심는다
    parser.add_argument("--only-type", default="")  # 한 유형만 (예: temporal-reasoning)
    # 기권 축 표본 — abs 는 30건뿐이라 전량이 싸다. mixed 는 그 30건 + 답 있는 문항 앞머리로,
    # 분리도(AUC)·문턱 스윕을 재려면 두 무리가 다 있어야 하기 때문에 둔다.
    parser.add_argument("--split", default="all", choices=["all", "abs", "answerable", "mixed"])
    parser.add_argument("--mixed-answerable", type=int, default=120)  # mixed 에서 쓸 답 있는 문항 수
    args = parser.parse_args()

    os.environ["ASGARD_MEMORY_SEMANTIC"] = args.semantic
    os.environ["ASGARD_MEMORY_INJECT"] = "off"  # 주입면은 이 벤치와 무관하다

    # 2단계 어블레이션은 제품의 정식 스위치를 쓴다 — 벤치가 몽키패치로 만든 상태는
    # 사용자가 재현할 수 없는 상태다. off 면 리랭크 도입 이전과 같은 순위가 나온다.
    os.environ["ASGARD_MEMORY_RERANK"] = args.rerank

    # QPP 분산 게이트. 미지정이면 제품 기본값을 그대로 쓰되, **그 값이 무엇이었는지**를
    # 산출물에 적는다 — 나중에 상수가 바뀌면 이 파일이 어느 문턱의 결과인지 알 수 없어진다.
    if args.dispersion:
        os.environ["ASGARD_MEMORY_RERANK_DISPERSION"] = "0" if args.dispersion == "off" else args.dispersion
    if args.gate:
        os.environ["ASGARD_MEMORY_RERANK_GATE"] = args.gate
    from asgard.memory import recall as _recall

    _effective_floor = _recall._dispersion_floor() if args.rerank == "on" else None

    with open(args.data, encoding="utf-8") as handle:
        entries = json.load(handle)
    if args.only_type:
        entries = [e for e in entries if e.get("question_type") == args.only_type]
    if args.split == "abs":
        entries = [e for e in entries if is_abstention(e)]
    elif args.split == "answerable":
        entries = [e for e in entries if not is_abstention(e)]
    elif args.split == "mixed":
        # 데이터 순서를 그대로 쓴다 — 무작위 표본은 seed 를 산출물에 적어야 재현되는데,
        # 앞머리 잘라 쓰기는 인자만으로 재현된다 (표본 크기는 아래 report 에 남는다).
        answerable = [e for e in entries if not is_abstention(e)][: max(0, args.mixed_answerable)]
        entries = [e for e in entries if is_abstention(e)] + answerable
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

    # 실험군은 **결과 파일 안에서** 자기를 밝혀야 한다. 파일명(`...-rerank-off.json`)이 실험군을
    # 주장하면 그 주장은 검증 불가다 — 이름은 사람이 붙이고, 나중에 바뀌고, 옮겨진다. 감사자가
    # 두 결과를 비교할 때 무엇과 무엇을 비교하는지는 파일 내용만으로 확정돼야 한다.
    report = {
        "dataset": os.path.basename(args.data),
        "semantic": args.semantic,
        "rerank": args.rerank,
        "dispersion_floor": _effective_floor,
        "gate_mode": _recall._gate_mode() if args.rerank == "on" else None,
        "kind": args.kind,
        "event_dates": args.event_dates,
        "only_type": args.only_type,
        "split": args.split,
        "offset": args.offset,
        "limit": args.limit,
        "argv": sys.argv[1:],
        "seconds": round(time.monotonic() - started, 1),
        **summarize(rows),
        "rows": rows,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
    # 화면에는 스윕 표를 빼고 찍는다 — 40줄짜리 표는 파일에서 읽을 것이지 흘려 볼 것이 아니다.
    shown = {k: v for k, v in report.items() if k != "rows"}
    abstention = shown.get("abstention")
    if isinstance(abstention, dict):
        shown["abstention"] = {k: v for k, v in abstention.items() if k != "sweep_top_score"}
    print(json.dumps(shown, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
