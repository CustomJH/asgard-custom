"""하이브리드 검색 벤치 — 1차 메모리 2경로(lexical) vs 3경로(+시맨틱) A/B 실측.

취지 (26-07-18): agentmemory 실사에서 이식한 시맨틱 스트림이 Tier0 검색을 실제로 강화하는지,
그리고 그 대가로 지연이 얼마나 느는지를 통제된 합성 위키에서 정직하게 잰다.

핵심 설계 — 쿼리 3계층으로 "무회귀 + 강화"를 분리 측정:
  · direct   : 페이지와 낱말이 겹치는 질의 → 두 모드 모두 잡아야 함(무회귀 대조군)
  · paraphrase: 같은 뜻 다른 한국어 낱말 → lexical miss, 시맨틱이 회수해야 이득
  · crosslingual: 영어 질의 ↔ 한국어 페이지 → lexical 원천 불가, 시맨틱 전용 이득

실모델: model2vec(minishlab/potion-multilingual-128M, 256d, torch 무의존). 미설치면 안내 후 종료.
지연: query() 벽시계 p50/p95 (모드별). 산출: results.jsonl(append) + REPORT.md.

사용:  uv run python benchmarks/hybrid-search/harness.py [--pages N] [--latency-iters M]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# 시맨틱 스트림을 실모델로 켠다 (env 오버라이드 — 사용자 config 와 동일 경로).
os.environ["ASGARD_MEMORY_SEMANTIC"] = "local"
os.environ["ASGARD_MEMORY_SEMANTIC_MODEL"] = "minishlab/potion-multilingual-128M"

from asgard import memory  # noqa: E402
from asgard import memory_semantic as sem  # noqa: E402

OUT = Path(__file__).resolve().parent
RESULTS = OUT / "results.jsonl"
REPORT = OUT / "REPORT.md"

# 타깃 페이지: (slug 제목, 본문) — Asgard 도메인. 질의는 아래에서 이 제목을 정답으로 라벨링.
TARGETS = [
    ("라곰 출력 압축", "라곰 모드는 산출물을 사다리로 압축해 토큰을 줄인다. full 모드가 기본이다."),
    ("프레이야 디자인 편대", "시각 작업은 프레이야 페르소나로 디스패치한다. 편대는 대형 과업에만."),
    ("토르 백엔드 강화", "토르는 백엔드·빌드·CI 담당 페르소나다. 에인헤랴르 편대를 이끈다."),
    ("메모리 정본 파일", "개인 메모리의 정본은 마크다운 파일이고 state.db 는 파생 인덱스다."),
    ("힌드사이트 프로젝트 메모리", "2차 공유 메모리는 힌드사이트 서버 어댑터로 연결한다. recall 은 0-LLM."),
    ("승인 게이트 계약", "쓰기는 계획을 먼저 보여주고 동일 계획을 실행한다. TOCTOU 를 차단한다."),
    ("트리니티 오케스트레이터", "헤임달은 게이트-우선 라우팅으로 사고와 실행을 분리한다."),
    ("인젝션 스캔 방어", "메모리는 프롬프트에 주입되므로 오염 패턴을 저장 시 거부한다."),
    ("코드베이스 지도", "map 은 팀 공유 fog-of-war 증분 지도다. close 넛지가 유령을 정리한다."),
    ("셀프 임프루브먼트", "skill_bank 핫리로드와 evolve 인박스로 자가발전한다."),
]

# 질의 라벨링: (질의, 정답 제목, 계층)
QUERIES = [
    # direct — 낱말 겹침(무회귀 대조군): 두 모드 모두 hit 기대
    ("라곰 압축", "라곰 출력 압축", "direct"),
    ("프레이야 디자인", "프레이야 디자인 편대", "direct"),
    ("메모리 정본", "메모리 정본 파일", "direct"),
    ("승인 게이트", "승인 게이트 계약", "direct"),
    ("인젝션 스캔", "인젝션 스캔 방어", "direct"),
    # paraphrase — 같은 뜻 다른 한국어 낱말: lexical miss, 시맨틱 이득
    ("출력 토큰 줄이기", "라곰 출력 압축", "paraphrase"),
    ("UI 시안 담당자", "프레이야 디자인 편대", "paraphrase"),
    ("서버 빌드 파이프라인 담당", "토르 백엔드 강화", "paraphrase"),
    ("지식창고 원본은 어디", "메모리 정본 파일", "paraphrase"),
    ("악성 프롬프트 삽입 막기", "인젝션 스캔 방어", "paraphrase"),
    ("소스 트리 시각화", "코드베이스 지도", "paraphrase"),
    # crosslingual — 영어 질의 ↔ 한국어 페이지: lexical 불가, 시맨틱 전용
    ("output token reduction mode", "라곰 출력 압축", "crosslingual"),
    ("visual design persona", "프레이야 디자인 편대", "crosslingual"),
    ("shared project memory server", "힌드사이트 프로젝트 메모리", "crosslingual"),
    ("approval gate before write", "승인 게이트 계약", "crosslingual"),
    ("self improvement skills", "셀프 임프루브먼트", "crosslingual"),
]

# 검색 잡음용 distractor — 정답과 무관한 주제로 위키를 채워 난이도를 올린다.
DISTRACTORS = [
    ("커피 원두 보관", "원두는 밀폐 용기에 실온 보관하고 2주 내 소비한다."),
    ("등산 준비물", "물·행동식·우비·헤드랜턴을 챙긴다. 날씨를 미리 확인한다."),
    ("김치 담그기", "배추를 절이고 양념을 버무린다. 저온 숙성이 핵심이다."),
    ("자전거 정비", "체인에 오일을 치고 타이어 공기압을 맞춘다."),
    ("화분 물주기", "겉흙이 마르면 듬뿍 준다. 과습이 뿌리를 썩힌다."),
    ("사진 구도", "삼분할과 리딩 라인으로 시선을 유도한다."),
    ("스트레칭 루틴", "아침에 목·어깨·허리를 천천히 풀어준다."),
    ("빵 발효", "실온에서 1차 발효 후 성형하고 2차 발효한다."),
    ("캠핑 텐트", "바람 방향을 보고 팩을 45도로 박는다."),
    ("독서 기록", "읽은 날짜와 인상 깊은 문장을 남긴다."),
]


def build_wiki(d: str, extra_distractors: int) -> None:
    memory.ensure_home(d)
    for title, body in TARGETS:
        memory.add(body, title=title, kind="note", d=d, force=True)
    pool = DISTRACTORS * (extra_distractors // len(DISTRACTORS) + 1)
    for i, (title, body) in enumerate(pool[:extra_distractors]):
        memory.add(body, title=f"{title}-{i}", kind="note", d=d, force=True)
    memory.reindex(d)  # 벡터 파생물까지 생성


def _target_slug(title: str) -> str:
    return memory.slugify(title)


def _apply_mode(semantic_on: bool) -> None:
    """모드 토글 — env 까지 함께 바꾼다. off 인데 env 가 local 로 남으면 embedder() 가
    실모델을 재로드해 '가짜 off' 가 된다(하니스가 한 프로세스에서 두 모드를 오간 탓).
    실사용은 모드를 토글하지 않으므로 이 배려는 벤치 전용이다."""
    if semantic_on:
        os.environ["ASGARD_MEMORY_SEMANTIC"] = "local"
        sem.set_embedder(_EMBEDDER)  # 캐시된 실모델 재사용 (재로드 회피)
    else:
        os.environ["ASGARD_MEMORY_SEMANTIC"] = "off"
        sem.set_embedder(None)


def score_mode(d: str, semantic_on: bool) -> dict:
    _apply_mode(semantic_on)
    layers: dict[str, list[int]] = {"direct": [], "paraphrase": [], "crosslingual": []}
    ranks: dict[str, list[float]] = {"direct": [], "paraphrase": [], "crosslingual": []}
    for q, gold_title, layer in QUERIES:
        hits = memory.query(q, k=5, d=d, track=False)
        gold = _target_slug(gold_title)
        slugs = [h["slug"] for h in hits]
        rank = slugs.index(gold) + 1 if gold in slugs else 0
        layers[layer].append(rank)
        ranks[layer].append(1.0 / rank if rank else 0.0)
    summary = {}
    for layer, rs in layers.items():
        n = len(rs)
        summary[layer] = {
            "n": n,
            "hit@1": sum(1 for r in rs if r == 1) / n,
            "hit@3": sum(1 for r in rs if 1 <= r <= 3) / n,
            "hit@5": sum(1 for r in rs if 1 <= r <= 5) / n,
            "mrr": statistics.mean(ranks[layer]),
        }
    return summary


def latency_mode(d: str, semantic_on: bool, iters: int) -> dict:
    _apply_mode(semantic_on)
    samples = []
    probes = [q for q, _, _ in QUERIES]
    for _ in range(iters):
        for q in probes:
            t0 = time.perf_counter()
            memory.query(q, k=5, d=d, track=False)
            samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return {
        "queries": len(samples),
        "p50_ms": round(statistics.median(samples), 2),
        "p95_ms": round(samples[int(len(samples) * 0.95)], 2),
        "max_ms": round(samples[-1], 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=100, help="총 페이지 수 목표 (타깃 10 + distractor)")
    ap.add_argument("--latency-iters", type=int, default=20)
    args = ap.parse_args()

    global _EMBEDDER
    _EMBEDDER = sem.embedder()
    if _EMBEDDER is None:
        print("시맨틱 임베더를 로드하지 못했습니다. 먼저: uv pip install model2vec", file=sys.stderr)
        return 1

    tmp = tempfile.mkdtemp(prefix="asgard-hybrid-bench-")
    d = os.path.join(tmp, "memory")
    extra = max(0, args.pages - len(TARGETS))
    print(f"위키 생성: 타깃 {len(TARGETS)} + distractor {extra} = {len(TARGETS) + extra} 페이지 …")
    build_wiki(d, extra)

    off_q = score_mode(d, semantic_on=False)
    on_q = score_mode(d, semantic_on=True)
    off_l = latency_mode(d, semantic_on=False, iters=args.latency_iters)
    on_l = latency_mode(d, semantic_on=True, iters=args.latency_iters)

    record = {
        "pages": len(TARGETS) + extra,
        "model": os.environ["ASGARD_MEMORY_SEMANTIC_MODEL"],
        "quality": {"off": off_q, "on": on_q},
        "latency": {"off": off_l, "on": on_l},
    }
    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    write_report(record)
    print(f"\n결과 → {RESULTS}\n리포트 → {REPORT}")
    print_summary(record)
    return 0


def print_summary(rec: dict) -> None:
    print(f"\n{'계층':<14}{'모드':<6}{'hit@1':>7}{'hit@3':>7}{'hit@5':>7}{'MRR':>7}")
    for layer in ("direct", "paraphrase", "crosslingual"):
        for mode in ("off", "on"):
            s = rec["quality"][mode][layer]
            print(f"{layer:<14}{mode:<6}{s['hit@1']:>7.2f}{s['hit@3']:>7.2f}{s['hit@5']:>7.2f}{s['mrr']:>7.3f}")
    print(f"\n지연  off p50={rec['latency']['off']['p50_ms']}ms p95={rec['latency']['off']['p95_ms']}ms")
    print(f"지연  on  p50={rec['latency']['on']['p50_ms']}ms p95={rec['latency']['on']['p95_ms']}ms")


def write_report(rec: dict) -> None:
    lines = [
        "# 하이브리드 검색 벤치 — 2경로 vs 3경로",
        "",
        f"- 페이지: **{rec['pages']}** · 모델: `{rec['model']}` (256d, torch 무의존)",
        "- off = lexical 2경로(FTS5 BM25 + 정본 스캔) · on = +시맨틱 3경로 RRF",
        "",
        "## 검색 품질 (hit@k · MRR)",
        "",
        "| 계층 | 모드 | hit@1 | hit@3 | hit@5 | MRR |",
        "|---|---|---|---|---|---|",
    ]
    for layer in ("direct", "paraphrase", "crosslingual"):
        for mode in ("off", "on"):
            s = rec["quality"][mode][layer]
            lines.append(
                f"| {layer} | {mode} | {s['hit@1']:.2f} | {s['hit@3']:.2f} | {s['hit@5']:.2f} | {s['mrr']:.3f} |"
            )
    lines += [
        "",
        "- **direct** = 두 모드 동일해야 정상(무회귀 대조군)",
        "- **paraphrase / crosslingual** = off 는 원리상 회수 불가, on 의 이득 구간",
        "",
        "## 지연 (query() 벽시계)",
        "",
        "| 모드 | p50 | p95 | max |",
        "|---|---|---|---|",
        f"| off | {rec['latency']['off']['p50_ms']}ms | {rec['latency']['off']['p95_ms']}ms | {rec['latency']['off']['max_ms']}ms |",
        f"| on | {rec['latency']['on']['p50_ms']}ms | {rec['latency']['on']['p95_ms']}ms | {rec['latency']['on']['max_ms']}ms |",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
