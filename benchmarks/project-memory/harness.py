"""2차(프로젝트) 메모리 회수 벤치 — 레인 셋.

지금까지 2차에는 **회수 하니스가 없었다** (리랭커 A/B 와 부하 실측뿐). 형식은
`benchmarks/hybrid-search/` 와 `benchmarks/longmemeval/harness.py` 를 본떴다: 문항마다 격리된
자리, 결정론 지표, 실험군을 산출물 안에 적기.

재는 것 셋:

  1. **로컬 문서 레인 hit@k** — `project_memory/documents.py` 의 FTS5+렉시컬 2스트림 RRF.
     네트워크·모델 무의존이라 언제나 실제로 돈다.
  2. **관계 1홉 확장의 효과** — `memory_context._relation_neighbors` 가 붙이는 이웃이 회수를
     올리는가 내리는가. 감사에서 이 효과는 계측 0 이었다. 외부 근거: HippoRAG 2 는 그래프를
     얹은 RAG 들이 **기본 사실 회수를 표준 RAG 아래로 떨어뜨렸다**고 보고한다. 그래서 이
     레인의 요점은 "관계 질의가 좋아졌나"가 아니라 **"기본 사실이 안 깎였나"** 다.
  3. **동언어 렉시컬 기권 정밀도** — `memory_context._same_language_lexical_admission`.
     한국어·영어 둘 다, 그리고 교차언어에서 **손대지 않는가**까지.

**Hindsight backend 는 안 쓴다.** 위 셋은 전부 정본 파일과 순수 함수 위에서 돈다. 레인 2 의
후보 뽑기만 backend 검색 자리인데, 없으면 결정론 **어휘 대역**으로 대신하고 산출물에
`backend: skipped` 로 적는다 (거짓 수치 대신 빠진 자리를 남긴다). 띄우는 법은 REPORT.md.

실행: .venv/bin/python benchmarks/project-memory/harness.py
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
K_VALUES = (1, 3, 5)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


# ── 레인 1 · 로컬 문서 레인 hit@k ─────────────────────────────────────────────


def lane_documents(root: str, queries: list[tuple[str, list[tuple[str, str]], str]]) -> dict:
    """문서 정본 전문 검색의 hit@k · MRR.

    정답을 **절** 단위로 둔다. 이 레인은 절 제목에서 먼저 자르므로 (`documents.chunk`),
    "3.2.1이 무엇을 요구하는가"에 답하려면 문서가 아니라 절이 맞아야 한다."""
    from asgard.project_memory.documents import search

    rows: list[dict] = []
    for query, gold, lang in queries:
        hits = search(root, query, k=max(K_VALUES))
        got = [(str(h.get("name") or ""), str(h.get("heading") or "")) for h in hits]
        gold_set = {tuple(pair) for pair in gold}
        rank = next((i + 1 for i, pair in enumerate(got) if pair in gold_set), 0)
        rows.append(
            {
                "query": query,
                "lang": lang,
                "gold": [list(pair) for pair in gold],
                "returned": [list(pair) for pair in got[: max(K_VALUES)]],
                **{f"hit_at_{k}": 1.0 if 0 < rank <= k else 0.0 for k in K_VALUES},
                "mrr": round(1.0 / rank, 4) if rank else 0.0,
            }
        )
    by_lang: dict[str, list[dict]] = {}
    for row in rows:
        by_lang.setdefault(row["lang"], []).append(row)
    metrics = [f"hit_at_{k}" for k in K_VALUES] + ["mrr"]
    return {
        "n": len(rows),
        "overall": {m: _mean([r[m] for r in rows]) for m in metrics},
        "by_lang": {
            lang: {"count": len(sub), **{m: _mean([r[m] for r in sub]) for m in metrics}}
            for lang, sub in sorted(by_lang.items())
        },
        "rows": rows,
    }


# ── 레인 2 · 관계 1홉 확장 ────────────────────────────────────────────────────


def _eligible_records(root: str) -> dict:
    """자동 주입 자격을 갖춘 record 만 — 제품이 base 후보에도 거는 그 술어와 같은 것."""
    from asgard.memory_context import _injectable_knowledge
    from asgard.project_memory import load_canonical_records

    return {
        record.record_id: record
        for record, _path, _digest in load_canonical_records(root)
        if _injectable_knowledge(record.scope, record.status, record.confidence)
    }


def _lexical_seeds(records: dict, query: str, k: int) -> list[str]:
    """backend 검색의 **결정론 대역** — 질의어가 제목·본문에 몇 개 들었나로 순위를 매긴다.

    실제 Hindsight 순위와 같지 않다. 같을 필요도 없다 — 이 레인이 묻는 것은 "확장 전후"의
    차이이고, 두 arm 이 **같은 base** 를 쓰는 한 그 차이는 확장의 몫이다. 다만 절대 hit@k 를
    backend 성능으로 읽으면 안 된다는 것이 이 함수가 산출물에 `backend: skipped` 를 적게
    만드는 이유다."""
    from asgard.memory_context import _query_terms

    terms = _query_terms(query)
    scored: list[tuple[int, str]] = []
    for rid, record in records.items():
        hay = f"{record.title} {record.content}".lower()
        hits = sum(1 for term in terms if term in hay)
        if hits:
            scored.append((hits, rid))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [rid for _score, rid in scored[:k]]


def _inject(rows: list[str], budget: int) -> str:
    """제품의 조립기를 그대로 태운다 — 밀려나는 자리를 벤치가 따로 지어내면 안 된다."""
    from asgard.memory.assemble import Candidate, Lane, assemble
    from asgard.memory_context import PROJECT_PREFIX_TEMPLATE, PROJECT_SUFFIX

    lane = Lane("project", PROJECT_PREFIX_TEMPLATE.format(project_id="bench"), PROJECT_SUFFIX, budget)
    return assemble(
        [Candidate("project", body, rank=index) for index, body in enumerate(rows)],
        (lane,),
        budget=budget,
    )


# 예산 스윕. 제품 값(3000)만 재면 이 레인은 "안 깎였다"만 답하는데, 그건 **자르는 자리를 안
# 본** 것이다 — 합성 코퍼스의 주입은 700자 언저리라 3000 은 애초에 안 걸린다. 진짜 저장소의
# record 는 이보다 길고 레인이 여섯이라, 예산이 걸리는 자리에서 이웃이 본체를 밀어내는지가
# HippoRAG 2 가 경고한 그 실패다. 좁혀 가며 그 자리를 만든다.
BUDGET_SWEEP = (3000, 900, 700, 550, 450)


def lane_relations(root: str, queries: list[tuple[str, list[str], str, str]], *, max_results: int = 5) -> dict:
    """확장 없음 vs 1홉 확장 — 같은 base 위에서.

    두 arm 을 **주입면까지** 태운다. 이웃이 회수를 깎는 경로는 순위가 아니라 예산이기 때문이다
    (`project_recall_rows` 는 이웃을 rows 뒤에 붙이고, 그 뒤 `assemble` 이 문자 예산으로 자른다).
    후보 목록에서만 재면 "안 깎였다"는 답이 나오는데 그건 자르는 자리를 안 본 것이다."""
    from asgard.memory_context import _relation_neighbors

    records = _eligible_records(root)
    all_ids = {rid for rid, _r in _load_all(root).items()}
    rows: list[dict] = []
    blocked_neighbors: list[str] = []
    for query, gold, qtype, lang in queries:
        seeds = _lexical_seeds(records, query, max_results)
        base_rows = [f"{records[rid].content} [record: {rid}]" for rid in seeds]
        neighbors = _relation_neighbors(root, set(seeds))
        neighbor_rows = [
            f"{content[:300]} [via {edge}; record: {rid}]" for rid, edge, content in neighbors
        ]
        # 게이트 확인 — 이웃 후보 중 자격 없는 record 가 실제로 나타났다가 막혔는가.
        for rid in _neighbor_candidates(root, set(seeds)):
            if rid in all_ids and rid not in records and rid not in blocked_neighbors:
                blocked_neighbors.append(rid)
        arms: dict[str, dict] = {}
        sweep: dict[str, dict[str, float]] = {}
        for arm, composed in (("off", base_rows), ("on", base_rows + neighbor_rows)):
            for budget in BUDGET_SWEEP:
                text = _inject(composed, budget)
                found = {rid for rid in gold if f"record: {rid}" in text}
                data = {
                    "recall": round(len(found) / len(gold), 4),
                    "injected": text.count("record: "),
                    "chars": len(text),
                    "missing": sorted(set(gold) - found),
                }
                sweep.setdefault(str(budget), {})[arm] = data["recall"]
                if budget == BUDGET_SWEEP[0]:  # 제품 예산이 대표값이다
                    arms[arm] = data
        rows.append(
            {
                "query": query,
                "type": qtype,
                "lang": lang,
                "gold": gold,
                "seeds": seeds,
                "neighbors": [rid for rid, _e, _c in neighbors],
                **{f"recall_{arm}": data["recall"] for arm, data in arms.items()},
                "arms": arms,
                "budget_sweep": sweep,
            }
        )
    by_type: dict[str, list[dict]] = {}
    for row in rows:
        by_type.setdefault(row["type"], []).append(row)
    return {
        "n": len(rows),
        "overall": {
            "recall_off": _mean([r["recall_off"] for r in rows]),
            "recall_on": _mean([r["recall_on"] for r in rows]),
            "delta": round(_mean([r["recall_on"] for r in rows]) - _mean([r["recall_off"] for r in rows]), 4),
        },
        "by_type": {
            qtype: {
                "count": len(sub),
                "recall_off": _mean([r["recall_off"] for r in sub]),
                "recall_on": _mean([r["recall_on"] for r in sub]),
                "delta": round(_mean([r["recall_on"] for r in sub]) - _mean([r["recall_off"] for r in sub]), 4),
                # HippoRAG 2 의 경고를 정면으로 세는 칸 — 확장을 켜서 **잃은** 문항 수.
                "regressed": sum(1 for r in sub if r["recall_on"] < r["recall_off"]),
                "improved": sum(1 for r in sub if r["recall_on"] > r["recall_off"]),
            }
            for qtype, sub in sorted(by_type.items())
        },
        "chars_off": _mean([float(r["arms"]["off"]["chars"]) for r in rows]),
        "chars_on": _mean([float(r["arms"]["on"]["chars"]) for r in rows]),
        # 예산을 좁혀 가며 본 확장의 대가. `fact` 줄에서 on 이 off 아래로 내려가는 지점이
        # 곧 "이웃이 기본 사실을 밀어낸" 자리다.
        "budget_sweep": {
            str(budget): {
                arm: {
                    qtype: _mean([r["budget_sweep"][str(budget)][arm] for r in sub])
                    for qtype, sub in sorted(by_type.items())
                }
                for arm in ("off", "on")
            }
            for budget in BUDGET_SWEEP
        },
        # 자격 없는 record 가 1홉 이웃 후보로 떠올랐다가 `_injectable_knowledge` 에 막힌 목록.
        # 비어 있으면 게이트가 안 돈 것이 아니라 **시험할 거리가 없었다**는 뜻이므로 같이 적는다.
        "gate_blocked_neighbors": blocked_neighbors,
        "rows": rows,
    }


def _load_all(root: str) -> dict:
    from asgard.project_memory import load_canonical_records

    return {record.record_id: record for record, _p, _d in load_canonical_records(root)}


def _neighbor_candidates(root: str, seed_ids: set[str]) -> list[str]:
    """자격 판정 **전**의 1홉 후보 — 게이트가 무엇을 막았는지 세기 위한 대조군."""
    records = _load_all(root)
    out: list[str] = []
    for seed_id in sorted(seed_ids):
        seed = records.get(seed_id)
        if seed is None:
            continue
        out += [str(rel.get("target") or "") for rel in seed.relations]
        out += [rid for rid, record in records.items() if any(r.get("target") == seed_id for r in record.relations)]
    return [rid for rid in out if rid and rid not in seed_ids]


# ── 레인 3 · 동언어 렉시컬 기권 ───────────────────────────────────────────────


def lane_admission(cases: list[dict]) -> dict:
    """기권 게이트의 정밀도 — 특히 **기권한 것 중 정말로 무관했던 비율**.

    두 오류가 다른 값이다. 무관한 것을 들여보내면 예산을 잡음이 먹고, 관련 있는 것을
    기권하면 답이 아예 안 들어온다. 그래서 통과 쪽 정밀도가 아니라 **기권 쪽 정밀도**를
    머리에 둔다 — 이 게이트가 존재하는 이유가 그쪽이기 때문이다."""
    from asgard.memory_context import _same_language_lexical_admission

    rows: list[dict] = []
    for case in cases:
        admitted = _same_language_lexical_admission(case["query"], case["text"])
        rows.append({**case, "admitted": admitted, "correct": admitted == case["relevant"]})
    by_lang: dict[str, list[dict]] = {}
    for row in rows:
        by_lang.setdefault(row["lang"], []).append(row)

    def _score(sub: list[dict]) -> dict:
        abstained = [r for r in sub if not r["admitted"]]
        admitted = [r for r in sub if r["admitted"]]
        irrelevant = [r for r in sub if not r["relevant"]]
        relevant = [r for r in sub if r["relevant"]]
        return {
            "count": len(sub),
            "accuracy": _mean([1.0 if r["correct"] else 0.0 for r in sub]),
            # 기권 정밀도 — 기권한 것 중 정말 무관했던 비율
            "abstention_precision": _mean([1.0 if not r["relevant"] else 0.0 for r in abstained]),
            # 기권 재현율 — 무관한 것 중 실제로 기권한 비율
            "abstention_recall": _mean([1.0 if not r["admitted"] else 0.0 for r in irrelevant]),
            # 오기권률 — 관련 있는데 버린 비율 (이 게이트의 진짜 위험)
            "false_abstention_rate": _mean([1.0 if not r["admitted"] else 0.0 for r in relevant]),
            "admitted": len(admitted),
            "abstained": len(abstained),
        }

    return {
        "overall": _score(rows),
        "by_lang": {lang: _score(sub) for lang, sub in sorted(by_lang.items())},
        "misses": [
            {"query": r["query"], "text": r["text"][:70], "relevant": r["relevant"], "admitted": r["admitted"]}
            for r in rows
            if not r["correct"]
        ],
    }


# ── backend 유무 ─────────────────────────────────────────────────────────────


def backend_status(root: str) -> dict:
    """Hindsight 가 이 자리에 붙어 있는가 — 없으면 무엇을 대역으로 썼는지 적는다."""
    try:
        from asgard.memory_context import find_config, is_backend_trusted
    except Exception as exc:
        return {"state": "skipped", "why": f"import 실패: {exc}"}
    found = find_config(root)
    if not found:
        return {
            "state": "skipped",
            "why": "이 root 에 프로젝트 메모리 config 가 없다 (합성 코퍼스는 정본 파일만 만든다)",
            "substitute": "레인 2 의 base 후보는 결정론 어휘 대역(_lexical_seeds)으로 뽑았다",
        }
    _root, cfg = found
    if not is_backend_trusted(cfg):
        return {"state": "skipped", "why": "backend 가 신뢰 경계를 통과하지 못했다"}
    return {"state": "present", "project_id": str(cfg.get("project_id") or cfg.get("bank") or "")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="")  # 비우면 임시 자리에 합성 코퍼스를 새로 짓는다
    parser.add_argument("--out", default=os.path.join(HERE, "results.json"))
    parser.add_argument("--max-results", type=int, default=5)
    args = parser.parse_args()

    import corpus as corpus_module

    workdir = ""
    if args.root:
        root, built = args.root, {"documents": 0, "records": 0, "note": "기존 root 를 그대로 썼다"}
    else:
        workdir = tempfile.mkdtemp(prefix="asgard-pm-bench-")
        root = workdir
        built = corpus_module.build(root)

    started = time.monotonic()
    try:
        report = {
            "corpus": "합성 (benchmarks/project-memory/corpus.py) — 절대 수치를 제품 품질로 읽지 마라",
            "corpus_built": built,
            "backend": backend_status(root),
            "max_results": args.max_results,
            "documents": lane_documents(root, corpus_module.DOCUMENT_QUERIES),
            "relations": lane_relations(root, corpus_module.RECORD_QUERIES, max_results=args.max_results),
            "admission": lane_admission(corpus_module.ADMISSION_CASES),
        }
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)
    report["seconds"] = round(time.monotonic() - started, 2)

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)

    doc, rel, adm = report["documents"], report["relations"], report["admission"]
    print(f"backend: {report['backend']['state']} — {report['backend'].get('why', '')}\n")
    print(f"[레인 1] 문서 레인 n={doc['n']}  " + "  ".join(f"{m}={v}" for m, v in doc["overall"].items()))
    for lang, sub in doc["by_lang"].items():
        print(f"          {lang} n={sub['count']} hit@1={sub['hit_at_1']} hit@3={sub['hit_at_3']} mrr={sub['mrr']}")
    print(f"\n[레인 2] 관계 1홉 n={rel['n']}  off={rel['overall']['recall_off']} on={rel['overall']['recall_on']} Δ={rel['overall']['delta']}")
    for qtype, sub in rel["by_type"].items():
        print(
            f"          {qtype} n={sub['count']} off={sub['recall_off']} on={sub['recall_on']} "
            f"Δ={sub['delta']} (개선 {sub['improved']} · 퇴행 {sub['regressed']})"
        )
    print(f"          주입 문자 off={rel['chars_off']} on={rel['chars_on']} · 게이트가 막은 이웃 {rel['gate_blocked_neighbors']}")
    print("          예산 스윕 (fact / relation):")
    for budget, arms in rel["budget_sweep"].items():
        cells = " ".join(
            f"{qtype}: off={arms['off'][qtype]} on={arms['on'][qtype]}" for qtype in sorted(arms["off"])
        )
        print(f"            budget={budget:>5}  {cells}")
    o = adm["overall"]
    print(f"\n[레인 3] 동언어 기권 n={o['count']} 정확도={o['accuracy']} 기권정밀도={o['abstention_precision']} 기권재현율={o['abstention_recall']} 오기권률={o['false_abstention_rate']}")
    for lang, sub in adm["by_lang"].items():
        print(
            f"          {lang} n={sub['count']} 정확도={sub['accuracy']} "
            f"기권정밀도={sub['abstention_precision']} 오기권률={sub['false_abstention_rate']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
