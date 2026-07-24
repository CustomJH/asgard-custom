"""노른 진화 벤치 — 노른 OFF(baseline) vs ON(norn 적용) 위키의 회상 품질·예산 효율 실측.

설계:
- 고정 코퍼스 24페이지 = 중복쌍 6(12p) + 패턴 클러스터 2×3(6p) + 고유 사실 4 + 부패 2(120d).
- 두 arm 모두 동일 질의 12개(중복 6·패턴 2·고유 4)를 결정론 query(k=5, track=False)로 평가.
- norn arm 은 baseline 사본에 norn plan+apply 를 최대 3패스(수확 없으면 조기 종료) — 실 LLM.
- ground truth 는 norn 의 병합·통찰을 remap 해 추적한다 (병합 dst·insight slug 승계).

지표:
  hit@1 / hit@3 / MRR      — 회상 정확도 (노른이 정확도를 깨지 않는가 + 통찰 승격 이득)
  pages / index_chars      — 예산 효율 (같은 사실 수를 더 적은 지면에)
  near_dups (lint)         — 중복 부채
  insight_top3             — 패턴 질의에서 insight 페이지가 top3 에 오르는 비율 (baseline=0 구조적)
  facts_retained           — 사실 보존 검증 (노른이 지식을 잃지 않는가, hit@5 기준)

사용:
  .venv/bin/python benchmarks/norn-evolution/harness.py run [replicates]
결과: benchmarks/norn-evolution/results.jsonl (런마다 append)
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from asgard import memory  # noqa: E402
from asgard.memory import norn  # noqa: E402

# ── 코퍼스 (결정론) ─────────────────────────────────────────────────────────────

DUP_PAIRS = [
    (
        "커밋 메시지는 한국어로 작성하고 gitmoji 접두사를 붙인다",
        "커밋 메시지를 쓸 때는 한국어와 gitmoji 접두사를 사용하는 것이 규칙이다",
    ),
    (
        "릴리스는 태그 푸시로만 트리거한다 — 수동 릴리스 금지",
        "릴리스 트리거는 태그 푸시 단일 경로다. 수동 릴리스는 금지되어 있다",
    ),
    (
        "테스트는 uv run pytest 로 실행한다 — .venv python 직접 호출 금지",
        "테스트 실행은 uv run pytest 가 정석이다. .venv python 을 직접 부르지 않는다",
    ),
    (
        "프로젝트 메모리 서버는 Hindsight 0.8.3 도커 스택이다",
        "Hindsight 0.8.3 도커 스택이 프로젝트 메모리 서버로 돌고 있다",
    ),
    (
        "대시보드 포트는 8765, 플랜 대시보드는 8767 이다",
        "메모리 대시보드는 8765 포트, 플랜 워크스페이스는 8767 포트를 쓴다",
    ),
    ("스킬 승인 없이는 learned 스킬이 활성화되지 않는다", "learned 스킬 활성화는 승인(approve)만이 유일한 경로다"),
]
PATTERN_CLUSTERS = [
    (
        "사용자는 금요일 오후에 배포하는 경향",
        [
            "7월 4일 금요일 오후에 v0.6.1 을 배포했다",
            "7월 11일 금요일 오후에 v0.6.8 을 배포했다",
            "7월 18일 금요일 오후에 v0.6.17 을 배포했다",
        ],
    ),
    (
        "사용자는 리뷰 전 lint 를 먼저 돌리는 습관",
        [
            "PR 리뷰 요청 전에 ruff check 를 먼저 돌렸다 (7월 첫째 주)",
            "리뷰 전에 ruff format --check 로 포맷을 먼저 정리했다 (7월 둘째 주)",
            "코드 리뷰 전 lint 4단을 먼저 완주하는 것을 반복 확인 (7월 셋째 주)",
        ],
    ),
]
UNIQUE_FACTS = [
    "환경 변수 ASGARD_MEMORY_DIR 로 개인 메모리 위치를 바꿀 수 있다",
    "인덱스 예산 기본값은 2200자이고 config [memory].index_budget_chars 로 조정한다",
    "Windows 파일 락은 msvcrt 폴백을 쓴다",
    "OKF export 는 단방향 스냅샷이며 원본을 수정하지 않는다",
]
STALE_NOTES = [
    "임시 메모 — 예전 브랜치 정리 목록 (완료됨)",
    "옛날 스크래치 노트 — 폐기된 실험 아이디어",
]

QUERIES: list[tuple[str, str, list[int]]] = [
    # (질의, 종류, 정답 인덱스) — dup: DUP_PAIRS idx / pattern: cluster idx / unique: idx
    ("커밋 메시지 언어 규칙", "dup", [0]),
    ("릴리스는 어떻게 트리거하나", "dup", [1]),
    ("테스트 실행 명령", "dup", [2]),
    ("프로젝트 메모리 서버 스택", "dup", [3]),
    ("대시보드 포트 번호", "dup", [4]),
    ("learned 스킬 활성화 경로", "dup", [5]),
    ("배포는 주로 언제 하나", "pattern", [0]),
    ("리뷰 전에 먼저 하는 일", "pattern", [1]),
    ("개인 메모리 위치 변경 방법", "unique", [0]),
    ("인덱스 예산 조정", "unique", [1]),
    ("Windows 파일 락", "unique", [2]),
    ("OKF export 성격", "unique", [3]),
]


def _age(d: str, slug: str, days: int) -> None:
    pg = memory._read(d, slug)
    assert pg is not None
    meta, body = pg
    past = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    meta["updated"] = meta["created"] = past
    memory._atomic_write(memory._page_path(d, slug), memory.render_page(meta, body))


def build_wiki(d: str) -> dict:
    """코퍼스 → 위키. 반환 = ground truth: 그룹키 → slug 집합."""
    memory.ensure_home(d)
    truth: dict[str, set[str]] = {}
    for i, (a, b) in enumerate(DUP_PAIRS):
        s1, _ = memory.add(a, title=f"규칙 관측 {i}a", d=d, force=True)
        s2, _ = memory.add(b, title=f"규칙 관측 {i}b", d=d, force=True)
        truth[f"dup:{i}"] = {s1, s2}
    for i, (_, obs) in enumerate(PATTERN_CLUSTERS):
        slugs = set()
        for j, text in enumerate(obs):
            s, _ = memory.add(text, title=f"활동 관측 {i}-{j}", d=d, force=True)
            slugs.add(s)
        truth[f"pattern:{i}"] = slugs
    for i, text in enumerate(UNIQUE_FACTS):
        s, _ = memory.add(text, title=f"고유 사실 {i}", d=d, force=True)
        truth[f"unique:{i}"] = {s}
    for i, text in enumerate(STALE_NOTES):
        s, _ = memory.add(text, title=f"부패 노트 {i}", d=d, force=True)
        _age(d, s, 120)
    memory.reindex(d)
    return {k: sorted(v) for k, v in truth.items()}


# ── 노른 적용 + ground truth remap ─────────────────────────────────────────────

MAX_PASSES = 3


def run_norn(d: str, truth: dict) -> dict:
    """norn 을 수확이 없을 때까지(≤3패스) 적용. truth 를 remap 하고 op 로그를 반환."""
    truth = {k: set(v) for k, v in truth.items()}
    insight_slugs: set[str] = set()
    ops_log: list[dict] = []
    for _ in range(MAX_PASSES):
        plan = norn.plan_norn(REPO, d)
        if not plan["ops"]:
            break
        result = norn.apply_norn(d, plan)
        for op in result["applied"]:
            ops_log.append({k: v for k, v in op.items() if k != "text"})
            if op["op"] == "merge":
                for group in truth.values():
                    if op["src"] in group:
                        group.discard(op["src"])
                        group.add(op["dst"])
            elif op["op"] == "insight":
                insight_slugs.add(op["slug"])
                for key, group in truth.items():
                    if key.startswith("pattern:") and set(op["sources"]) & group:
                        group.add(op["slug"])  # 통찰 페이지도 패턴 질의의 정답이다
        if not result["applied"]:
            break
    return {"truth": {k: sorted(v) for k, v in truth.items()}, "insights": sorted(insight_slugs), "ops": ops_log}


# ── 평가 ───────────────────────────────────────────────────────────────────────


def evaluate(d: str, truth: dict, insight_slugs: set[str]) -> dict:
    hits1 = hits3 = 0
    rr_sum = 0.0
    pattern_total = pattern_insight_top3 = 0
    facts_retained = 0
    for text, kind, idxs in QUERIES:
        answers = set().union(*({s for s in truth[f"{kind}:{i}"]} for i in idxs))
        rows = memory.query(text, k=5, d=d, track=False)
        ranked = [r["slug"] for r in rows]
        rank = next((i + 1 for i, s in enumerate(ranked) if s in answers), 0)
        hits1 += 1 if rank == 1 else 0
        hits3 += 1 if 0 < rank <= 3 else 0
        rr_sum += (1.0 / rank) if rank else 0.0
        facts_retained += 1 if rank else 0
        if kind == "pattern":
            pattern_total += 1
            if any(s in insight_slugs for s in ranked[:3]):
                pattern_insight_top3 += 1
    findings = memory.lint(d)
    near_dups = sum(1 for f in findings if f["code"] == "near-duplicate")
    return {
        "hit@1": round(hits1 / len(QUERIES), 3),
        "hit@3": round(hits3 / len(QUERIES), 3),
        "mrr": round(rr_sum / len(QUERIES), 3),
        "facts_retained": f"{facts_retained}/{len(QUERIES)}",
        "pages": len(memory._pages(d)),
        "index_chars": len(memory.build_index(d)),
        "snapshot_chars": len(memory.snapshot_note(d)),
        "near_dups": near_dups,
        "insight_top3": f"{pattern_insight_top3}/{pattern_total}",
    }


def run_replicate(rep: int) -> dict:
    tmp = tempfile.mkdtemp(prefix=f"asgard-nornbench-{rep}-")
    base_d = os.path.join(tmp, "baseline")
    norn_d = os.path.join(tmp, "norned")
    try:
        truth = build_wiki(base_d)
        baseline = evaluate(base_d, {k: set(v) for k, v in truth.items()}, set())
        shutil.copytree(base_d, norn_d)
        t0 = time.time()
        outcome = run_norn(norn_d, truth)
        elapsed = round(time.time() - t0, 1)
        memory.reindex(norn_d)
        norned = evaluate(norn_d, {k: set(v) for k, v in outcome["truth"].items()}, set(outcome["insights"]))
        return {
            "replicate": rep,
            "baseline": baseline,
            "norned": norned,
            "norn_seconds": elapsed,
            "ops": outcome["ops"],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    replicates = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.jsonl")
    print(f"노른 진화 벤치 — {replicates} replicate (실 LLM norn arm)")
    for rep in range(1, replicates + 1):
        row = run_replicate(rep)
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        b, m = row["baseline"], row["norned"]
        print(f"\n[replicate {rep}] norn {row['norn_seconds']}s · ops {len(row['ops'])}건")
        print(f"  {'지표':<14}{'baseline':>10}{'norned':>10}")
        for key in (
            "hit@1",
            "hit@3",
            "mrr",
            "facts_retained",
            "pages",
            "index_chars",
            "snapshot_chars",
            "near_dups",
            "insight_top3",
        ):
            print(f"  {key:<14}{b[key]!s:>10}{m[key]!s:>10}")
        for op in row["ops"]:
            desc = {
                "merge": lambda o: f"merge {o['src']} → {o['dst']} (sim {o.get('sim')})",
                "archive": lambda o: f"archive {o['slug']}",
                "insight": lambda o: (
                    f"insight {o.get('slug')} ({o.get('confidence')}) ← {', '.join(o.get('sources', []))}"
                ),
                "contradiction": lambda o: f"contradiction {o.get('a')} ↔ {o.get('b')}",
            }[op["op"]](op)
            print(f"    · {desc}")
    print(f"\n결과 파일: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
