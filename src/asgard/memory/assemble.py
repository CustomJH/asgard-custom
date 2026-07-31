"""회수 조립 — 여러 레인의 후보를 **하나의 예산** 안에서 겨루게 하고 중복을 걷어낸다.

## 왜 이 층이 생겼는가 (26-07-29 감사)

회수 경로가 여섯이 됐는데(개인 위키·프로젝트 record·문서·종합·스킬·에피소드) 조립은
문자열 여섯 개를 그냥 이어 붙이는 것이었다. 실측한 예산:

    개인 900 + 프로젝트 3,000 + 문서 900 + 종합 1,100 + 에피소드 700 + 스킬 ~460
    = 매 턴 7,060자

이 구조의 결함은 크기가 아니라 **아무도 전체를 안 본다**는 것이다:

  · **중복이 안 걸러진다.** 같은 사실이 개인 페이지로·프로젝트 record로·문서 발췌로·
    종합 구획으로·에피소드 구간으로 동시에 실릴 수 있고 그걸 막는 것이 없었다. 검색 문헌은
    이걸 lateral redundancy라 부르고, 고정 예산에서 중복은 곧 **다른 증거의 자리를 뺏는
    일**이다 (AdaGReS, arXiv 2512.25052 — 집합 수준 목적함수 = 관련도 − 집합 내 중복).
  · **레인끼리 못 겨룬다.** 각 레인은 "나한테 뭔가 있나"만 묻고 "이 7천 자가 최선인가"는
    아무도 안 묻는다. 프로젝트 레인이 3,000자를 안 쓰고 남겨도 개인 레인은 900자에서 잘린다.

## 이 모듈이 하는 일

고정 예산 위의 **탐욕 선택**이다 (Replace-don't-Expand, arXiv 2512.10787과 같은 결):

  1. **레인 간 값의 척도** — 순수 RRF `1/(K+rank)`. 레인 가중치를 **안 만든다**: 레인마다
     점수 척도가 달라 섞을 수 없고, 그래서 이 저장소는 어디서나 순위만 융합한다. 어느 레인이든
     1위는 1위만큼의 값이다. 취향으로 정한 가중치를 넣는 순간 그 숫자를 아무도 검증 못 한다.
  2. **중복 제거** — 이미 고른 것과 포함계수(containment)가 문턱 이상이면 버린다. 문턱의
     근거는 이 저장소의 기존 실측이다 (pages.MERGE_CONTAINMENT 주석: 병합쌍 0.56/0.61 vs
     무관쌍 0.00/0.02 — 분리가 커서 보수적으로 잡아도 안 다친다).
  3. **레인 바닥** — 레인마다 최소 예산을 먼저 채운다. 바닥이 없으면 후보가 많은 레인이
     전량을 먹는데, 그건 kind 예산을 나눈 이유(`policy.KIND_BUDGETS`: "예산이 아니라
     굶주림 때문에 칸을 나눈다")와 같은 실패다.
  4. **남은 예산은 전역 경쟁** — 바닥을 채우고 남은 자리는 레인 무관하게 값 순으로 준다.

**총 상한은 기존 레인 예산의 합 그대로다.** 줄이는 것은 별개의 결정이고 계측 없이 하면
회수 품질을 조용히 깎는다. 여기서 바뀌는 것은 천장이 아니라 **같은 천장 아래 무엇이 실리는가**다.

## 계약

  · 순수 함수다 — IO도 설정 읽기도 없다. 레인이 후보를 만들고, 이 모듈은 고르기만 한다.
  · 레인이 하나뿐이면 결과는 그 레인이 혼자 쓰던 것과 같다 (중복 제거만 추가).
  · 실패는 호출측 fail-open에 맡긴다 — 여기서 예외를 삼키면 버그가 조용해진다.
"""

from __future__ import annotations

import dataclasses

from .recall import RRF_K, _grams

# 레인 간 중복 판정 문턱 — 포함계수. Jaccard가 아니라 containment 인 이유는 길이가 크게
# 다른 두 표현(정본 전문 vs 200자 발췌)이 같은 사실일 때 Jaccard는 그걸 못 잡기 때문이다.
# 값의 근거: pages.MERGE_CONTAINMENT(0.45)를 뽑은 그 실측. 여기서는 조금 더 보수적으로
# 잡는다 — 병합(두 페이지를 영구히 합침)은 되돌리기 어렵지만 주입 중복 제거는 한 턴짜리라
# 오판의 대가가 비대칭이면서도, **구별되는 사실을 버리는 쪽**이 훨씬 나쁘기 때문이다.
DEDUP_CONTAINMENT = 0.55


@dataclasses.dataclass(frozen=True)
class Candidate:
    """레인 하나가 내놓는 회수 후보 한 건.

    body는 렌더될 본문(앞의 `- `는 렌더가 붙인다), suffix는 출처 표기다. 예산은 둘 다
    포함해 세지만 **중복 판정은 body 로만** 한다 — 같은 사실을 다른 레인이 내면 출처 표기는
    당연히 다르고, 그걸 비교에 넣으면 중복이 중복으로 안 보인다."""

    lane: str
    body: str
    suffix: str = ""
    rank: int = 0

    @property
    def text(self) -> str:
        return f"- {self.body}{self.suffix}"

    @property
    def cost(self) -> int:
        return len(self.text) + 1  # 줄바꿈 한 자


@dataclasses.dataclass(frozen=True)
class Lane:
    """레인 명세 — 순서는 곧 렌더 순서이자 바닥 배분 순서다."""

    key: str
    prefix: str
    suffix: str
    floor: int


def _value(candidate: Candidate) -> float:
    """레인 간 비교 가능한 값 — 순위만 쓴다 (RRF). 같은 순위면 같은 값이다."""
    return 1.0 / (RRF_K + candidate.rank + 1)


class _Grams:
    """후보별 trigram 집합 캐시 — 같은 본문의 그램을 두 번 만들지 않는다.

    왜 필요한가: 중복 판정은 (고른 것 × 후보) 쌍마다 도는데 `_containment`는 호출마다 양쪽
    그램을 새로 만든다. 후보가 30개면 그램 생성이 수백 번이고 본문은 수백 자다 — 이건 **매 턴**
    도는 경로라 그대로 두면 조립기가 자기가 아끼는 것보다 비싸진다 (실측 26-07-29: 후보 60에서
    3.72ms). 그램은 본문에만 의존하므로 한 번 만들어 재사용하면 결과는 **바이트 동일**하고
    비용만 선형으로 떨어진다."""

    __slots__ = ("_cache",)

    def __init__(self) -> None:
        self._cache: dict[str, set[str]] = {}

    def of(self, text: str) -> set[str]:
        grams = self._cache.get(text)
        if grams is None:
            grams = _grams(text)
            self._cache[text] = grams
        return grams

    def containment(self, a: str, b: str) -> float:
        """포함 계수 |A∩B|/min(|A|,|B|) — `recall._containment`와 같은 정의, 캐시만 다르다."""
        ga, gb = self.of(a), self.of(b)
        return len(ga & gb) / (min(len(ga), len(gb)) or 1)


def _redundant(candidate: Candidate, chosen: list[Candidate], floor: float, grams: _Grams) -> bool:
    """이미 고른 **다른 레인의** 것 중 하나라도 이 후보를 품으면 중복이다.

    왜 레인 **안**은 안 보는가. 중복의 두 종류는 고칠 자리가 다르다:

      · 레인 **간** 중복은 구조적이다. 같은 지식이 개인 위키에도·프로젝트 record 에도·
        문서 발췌에도 정당하게 존재한다 (각각 다른 신뢰 등급과 수명을 갖는다). 저장 쪽에서
        고칠 수 없고, 주입면이 유일하게 고칠 수 있는 자리다.
      · 레인 **안** 중복은 저장의 결함이다. 개인 위키에 거의 같은 페이지가 둘 있으면 그건
        합쳐야 할 페이지이고, `lint`가 이미 `near-duplicate`로 지목한다. 주입에서 조용히
        가리면 사용자는 고쳐야 할 것이 있다는 사실 자체를 못 본다 — 계기를 끄는 셈이다.

    그리고 오판의 대가가 비대칭이다: 구별되는 사실을 버리는 것이 중복 한 줄보다 훨씬 나쁘다.
    좁은 규칙이 넓은 규칙보다 안전하고, 넓힐 근거는 계측이 생긴 뒤에 생긴다."""
    return any(
        picked.lane != candidate.lane and grams.containment(candidate.body, picked.body) >= floor for picked in chosen
    )


def select(
    candidates: list[Candidate],
    lanes: tuple[Lane, ...],
    *,
    budget: int,
    dedup: float = DEDUP_CONTAINMENT,
) -> list[Candidate]:
    """고정 예산 위의 탐욕 선택 — 레인 바닥을 먼저, 남은 자리는 전역 경쟁으로.

    반환은 **입력 순서가 아니라 선택 순서**가 아니라, 렌더 순서(레인 순 → 레인 내 순위)로
    정렬해 돌려준다. 고른 이유와 읽는 순서는 다른 축이다."""
    if budget <= 0 or not candidates:
        return []
    order = {lane.key: index for index, lane in enumerate(lanes)}
    # 레인이 실제로 쓰이면 머리글·꼬리도 프롬프트에 실린다. 예산은 **최종 문자열**에 걸려야
    # 하므로 그 몫을 같이 청구한다 — 행만 세면 블록마다 수십~수백 자가 상한 밖으로 샌다
    # (구 동작은 `len(prefix + rows + suffix)`로 재고 있었고, 그 계약을 지켜야 한다).
    overhead = {lane.key: len(lane.prefix) + len(lane.suffix) for lane in lanes}
    chosen: list[Candidate] = []
    used = 0
    opened: set[str] = set()
    grams = _Grams()

    def _take(pool: list[Candidate], ceiling: int) -> None:
        nonlocal used
        for candidate in pool:
            if candidate in chosen:
                continue
            # 그 레인의 첫 후보라면 블록을 여는 값을 같이 낸다.
            entry = 0 if candidate.lane in opened else overhead.get(candidate.lane, 0)
            if used + entry + candidate.cost > ceiling:
                continue  # 이 후보는 안 들어가도 더 짧은 뒤 후보는 들어갈 수 있다
            # 예산 판정을 **먼저** 한다: 안 들어갈 후보의 그램을 만드는 것은 순수한 낭비다.
            if _redundant(candidate, chosen, dedup, grams):
                continue
            chosen.append(candidate)
            opened.add(candidate.lane)
            used += entry + candidate.cost

    # 1단계 — 레인 바닥. 레인 순서대로, 그 레인 예산 안에서만.
    for lane in lanes:
        pool = sorted(
            (c for c in candidates if c.lane == lane.key),
            key=lambda c: (c.rank, c.body),
        )
        _take(pool, min(budget, used + max(0, lane.floor)))

    # 2단계 — 남은 예산은 레인 무관 전역 경쟁. 값이 같으면 레인 순서, 그다음 순위.
    surplus = sorted(
        (c for c in candidates if c not in chosen),
        key=lambda c: (-_value(c), order.get(c.lane, len(order)), c.rank, c.body),
    )
    _take(surplus, budget)

    chosen.sort(key=lambda c: (order.get(c.lane, len(order)), c.rank))
    return chosen


def render(chosen: list[Candidate], lanes: tuple[Lane, ...]) -> str:
    """선택된 후보를 레인별 블록으로. 빈 레인은 머리글도 안 낸다.

    블록 경계(`<memory-recall scope=...>`)를 유지하는 것이 의도다 — 근거의 성격이 다른 것을
    한 칸에 섞으면 모델이 정본과 요약을, 권위와 힌트를 구분할 근거를 잃는다."""
    blocks: list[str] = []
    for lane in lanes:
        rows = [c.text for c in chosen if c.lane == lane.key]
        if rows:
            blocks.append(lane.prefix + "\n".join(rows) + lane.suffix)
    return "".join(blocks)


def assemble(
    candidates: list[Candidate],
    lanes: tuple[Lane, ...],
    *,
    budget: int,
    dedup: float = DEDUP_CONTAINMENT,
) -> str:
    """select + render — 호출측이 쓰는 유일한 문."""
    return render(select(candidates, lanes, budget=budget, dedup=dedup), lanes)


def stats(candidates: list[Candidate], chosen: list[Candidate]) -> dict:
    """조립 결과 계기 — 무엇이 들어가고 무엇이 밀렸나 (대시보드·테스트·감사용).

    `dropped_redundant`를 따로 세는 이유: 예산이 모자라 밀린 것과 중복이라 버린 것은 전혀
    다른 사건인데 합쳐 놓으면 "예산을 늘려야 하나"라는 잘못된 질문으로 간다."""
    picked = set(id(c) for c in chosen)
    lanes_in = sorted({c.lane for c in candidates})
    return {
        "candidates": len(candidates),
        "chosen": len(chosen),
        "chars": sum(c.cost for c in chosen),
        "lanes_offered": lanes_in,
        "lanes_used": sorted({c.lane for c in chosen}),
        "dropped": [c.lane for c in candidates if id(c) not in picked],
    }


__all__ = ["DEDUP_CONTAINMENT", "Candidate", "Lane", "assemble", "render", "select", "stats"]
