"""기억 그래프 벤치 — 회수의 네 번째 스트림을 명시 링크만으로 돌릴 때 vs 파생 간선까지 겹칠 때.

왜 재는가 (26-08-06). 개인 기억의 그래프 스트림은 사람이 손으로 쓴 `[[링크]]` 위에서만
돌았다. 그런데 실제 위키에는 그 링크가 없다 — 이 저장소의 개인 기억은 14페이지에 명시 링크
0개였고, 그러면 네 번째 스트림은 켜져 있으나 언제나 빈 그래프를 본다. graphify 와
microsoft/graphrag 가 같은 자리에서 하는 일은 간선을 **자료에서 뽑는** 것이다. 이 벤치는
같은 것을 모델 없이 했을 때 회수가 실제로 올라가는지, 그리고 직접 질의를 깎지 않는지 잰다.

두 팔:
  explicit  명시 `[[링크]]` 만 (종전 동작)
  all       거기에 결정론 간선 둘을 겹침 — 제목 언급(`mention_links`) + 드문 낱말 공유(`term_links`)

질의 두 계층:
  direct       질의 낱말이 정답 페이지에 있다 → 두 팔 모두 잡아야 한다 (무회귀 대조군)
  associative  질의 낱말은 **이웃 페이지**에만 있고 정답은 그 옆에 있다 → 그래프 확장 전용 이득

시맨틱 스트림은 끈다. 켜면 파생 간선의 몫과 임베딩의 몫이 섞여 어느 쪽이 움직였는지 못 가른다.

이 벤치가 못 재는 것: 코퍼스가 합성이고 손으로 썼다. 재는 것은 **기전이 작동하는가**이지
실제 위키에서 몇 점 오르는가가 아니다. 후자는 오딘의 진짜 기억 위에서만 답이 나온다.

사용:  uv run --no-project python benchmarks/memory-graph/harness.py [--pages N]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ["ASGARD_MEMORY_SEMANTIC"] = "off"  # 파생 간선의 몫만 남긴다

from asgard import memory  # noqa: E402
from asgard.memory import graph as G  # noqa: E402
from asgard.memory import recall  # noqa: E402

OUT = Path(__file__).resolve().parent
RESULTS = OUT / "results.jsonl"
REPORT = OUT / "REPORT.md"

# 타깃 — 짝을 이루는 페이지들. 같은 드문 낱말을 나눠 갖되 본문은 서로 다른 사실을 말한다.
TARGETS = [
    ("판정자 지연 원인", "verifier 가 느린 원인은 재검증 루프와 baseline_timeout 오설정이다. trinity_policy 를 본다."),
    ("baseline_timeout 기본값", "baseline_timeout 의 기본값은 120초다. trinity_policy 아래에 적는다."),
    ("서브에이전트 위임 표", "subagent_gate 의 AGENT_TARGETS 는 전수여야 한다. 표에 없는 역할은 무엇이든 띄운다."),
    ("위임 층위 불변식", "AGENT_TARGETS 는 층위가 단조로워야 한다. subagent_gate 가 같은 층 호출을 끊는다."),
    ("힌드사이트 뱅크 구성", "hindsight 백엔드는 프로젝트 뱅크를 하나 쓴다. recall 은 0-LLM 경로다."),
    ("프로젝트 기억 정본", "프로젝트 record 의 정본은 Git 이고 hindsight 인덱스는 파생이다. recall 은 그 위를 본다."),
    ("훅 배포 배치", "훅은 asgard_hooklib 과 함께 깔린다. 배포본 드리프트는 시험이 사본까지 태워야 잡힌다."),
    ("배포본 사본 대조", "asgard_hooklib 사본이 원본과 어긋나면 판정이 두 벌이 된다. 드리프트는 바이트로 대조한다."),
    ("라곰 출력 압축", "라곰은 문장을 지워 산출물을 줄인다. full 모드가 기본이다."),
    ("코드베이스 지도", "map 은 팀 공유 증분 지도다. close 넛지가 유령 항목을 정리한다."),
]

# (질의, 정답 제목, 계층)
QUERIES = [
    # direct — 정답 페이지에 질의 낱말이 있다. 두 팔 모두 잡아야 한다.
    ("verifier 느린 원인", "판정자 지연 원인", "direct"),
    ("AGENT_TARGETS 전수", "서브에이전트 위임 표", "direct"),
    ("hindsight 뱅크", "힌드사이트 뱅크 구성", "direct"),
    ("asgard_hooklib 배포", "훅 배포 배치", "direct"),
    ("라곰 압축", "라곰 출력 압축", "direct"),
    ("map 유령 정리", "코드베이스 지도", "direct"),
    # associative — 질의 낱말은 이웃에만 있고 정답은 그 옆이다.
    ("verifier 가 느릴 때 만지는 설정의 기본값은 몇 초", "baseline_timeout 기본값", "associative"),
    ("표에 없는 역할이 무엇이든 띄운다면 무엇으로 막나", "위임 층위 불변식", "associative"),
    ("recall 이 0-LLM 이라면 정본은 어디에 있나", "프로젝트 기억 정본", "associative"),
    ("사본이 갈리면 판정이 두 벌이 된다는데 무엇으로 대조하나", "배포본 사본 대조", "associative"),
]

_NOISE_SUBJECTS = [
    ("커피 원두", "원두는 밀폐 용기에 실온 보관한다."),
    ("등산 준비", "물과 행동식과 우비를 챙긴다."),
    ("김치 담그기", "배추를 절이고 양념을 버무린다."),
    ("자전거 정비", "체인에 오일을 치고 공기압을 맞춘다."),
    ("화분 물주기", "겉흙이 마르면 듬뿍 준다."),
    ("사진 구도", "삼분할과 리딩 라인으로 시선을 유도한다."),
    ("스트레칭", "아침에 목과 어깨를 천천히 풀어준다."),
    ("빵 발효", "실온에서 1차 발효 후 성형한다."),
    ("텐트 설치", "바람 방향을 보고 팩을 비스듬히 박는다."),
    ("독서 기록", "읽은 날짜와 인상 깊은 문장을 남긴다."),
]


def build_wiki(d: str, extra: int) -> None:
    memory.ensure_home(d)
    for title, body in TARGETS:
        memory.add(body, title=title, kind="note", d=d)
    for index in range(extra):
        subject, body = _NOISE_SUBJECTS[index % len(_NOISE_SUBJECTS)]
        # 번호를 본문에도 넣어 사본끼리 드문 낱말을 공유하지 않게 한다 — 안 그러면 잡음
        # 페이지들이 하나의 큰 덩어리를 이뤄 그래프 밀도가 실제 위키와 달라진다.
        memory.add(f"{body} 사례 {index}번 기록 n{index}.", title=f"{subject}-{index}", kind="note", d=d)
    memory.reindex(d)


def score_arm(d: str, mode: str) -> dict:
    os.environ["ASGARD_MEMORY_GRAPH_EDGES"] = mode
    assert recall.graph_edges() == mode
    ranks: dict[str, list[int]] = {"direct": [], "associative": []}
    for question, gold_title, layer in QUERIES:
        hits = memory.query(question, k=5, d=d, track=False)
        slugs = [hit["slug"] for hit in hits]
        gold = memory.slugify(gold_title)
        ranks[layer].append(slugs.index(gold) + 1 if gold in slugs else 0)
    summary = {}
    for layer, found in ranks.items():
        n = len(found)
        summary[layer] = {
            "n": n,
            "hit@1": round(sum(1 for r in found if r == 1) / n, 3),
            "hit@3": round(sum(1 for r in found if 1 <= r <= 3) / n, 3),
            "hit@5": round(sum(1 for r in found if 1 <= r <= 5) / n, 3),
            "mrr": round(statistics.mean([1.0 / r if r else 0.0 for r in found]), 3),
        }
    return summary


def graph_shape(d: str) -> dict:
    pages = recall.clean_pages(d)
    documents = {slug: (str(meta.get("title") or slug), body) for slug, (meta, body) in pages.items()}
    explicit = G.page_links(pages)
    merged = G.merge(explicit, G.mention_links(documents), G.term_links(documents))
    return {"explicit": G.stats(explicit), "all": G.stats(merged)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=60, help="총 페이지 수 목표 (타깃 10 + 잡음)")
    args = parser.parse_args()

    temporary = tempfile.mkdtemp(prefix="asgard-memgraph-bench-")
    d = os.path.join(temporary, "memory")
    extra = max(0, args.pages - len(TARGETS))
    print(f"위키 생성: 타깃 {len(TARGETS)} + 잡음 {extra} = {len(TARGETS) + extra} 페이지 …")
    build_wiki(d, extra)

    shape = graph_shape(d)
    print(f"그래프: explicit {shape['explicit']} / all {shape['all']}")
    record = {"pages": len(TARGETS) + extra, "graph": shape, "arms": {}}
    for mode in ("explicit", "all"):
        record["arms"][mode] = score_arm(d, mode)
        print(f"  {mode:9s} {json.dumps(record['arms'][mode], ensure_ascii=False)}")

    with open(RESULTS, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\n기록: {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
