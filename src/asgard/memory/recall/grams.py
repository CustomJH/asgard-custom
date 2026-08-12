"""trigram 유사도 — 중복 판정과 조립기가 같은 계산식을 나눠 쓴다."""

from __future__ import annotations

import re


def _grams(text: str, n: int = 3) -> set[str]:
    t = re.sub(r"\s+", " ", text.lower())
    return {t[i : i + n] for i in range(max(len(t) - n + 1, 1))}


def _jaccard(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    # 합집합은 세기만 하면 되므로 만들지 않는다 — |A∪B| = |A|+|B|−|A∩B| 로 값이 같고,
    # 쌍 비교가 O(N²)로 도는 자리(`pages.lint`)에서 집합 하나를 통째로 덜 만든다.
    intersection = len(ga & gb)
    return intersection / ((len(ga) + len(gb) - intersection) or 1)


def _containment(a: str, b: str) -> float:
    """포함 계수 |A∩B|/min(|A|,|B|) — 한쪽이 다른 쪽을 품는 패러프레이즈에 강건."""
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / (min(len(ga), len(gb)) or 1)


class _Grams:
    """본문별 trigram 집합 캐시 — 같은 본문의 그램을 두 번 만들지 않는다.

    왜 필요한가: 쌍 비교는 O(N²)로 도는데 `_jaccard`·`_containment`는 호출마다 양쪽 그램을
    새로 만든다. N개 본문이면 그램 생성이 N² 번인데 실제로 필요한 것은 N 번이다 (실측
    26-07-29: 조립기 후보 60에서 3.72ms).

    **왜 저 두 함수를 안 고치고 옆에 두는가.** 캐시는 수명이 있는 물건이다: 전역 memoize를
    걸면 본문이 큰 위키에서 캐시가 프로세스 수명 내내 안 죽고, 무효화 시점이 없어 외부 편집
    뒤에도 옛 그램을 돌려줄 수 있다. 여기 쓰임(한 번의 lint·한 번의 조립)은 **호출 하나의
    수명**이면 충분하다. 그래서 캐시는 호출자가 만들고 호출자와 함께 죽는다 — 함수 두 개는
    캐시 없는 단발 비교의 정본으로 그대로 남는다 (계산식은 아래에서 글자 그대로 같다).

    자리를 `recall`로 잡은 이유: `pages`·`assemble` 둘 다 그램 정의를 여기서 가져다 쓴다
    (`from .recall import _containment, _jaccard`). 캐시가 소비자 쪽에 살면 정의와 캐시가
    갈라져, 한쪽 계산식을 고쳤을 때 다른 쪽이 조용히 옛 답을 낸다."""

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
        """포함 계수 — `_containment`와 같은 정의, 캐시만 다르다."""
        ga, gb = self.of(a), self.of(b)
        return len(ga & gb) / (min(len(ga), len(gb)) or 1)

    def jaccard(self, a: str, b: str) -> float:
        """Jaccard — `_jaccard`와 같은 정의, 캐시만 다르다."""
        ga, gb = self.of(a), self.of(b)
        intersection = len(ga & gb)
        return intersection / ((len(ga) + len(gb) - intersection) or 1)

    def jaccard_of(self, ga: set[str], gb: set[str]) -> float:
        """이미 손에 든 그램 집합끼리의 Jaccard — 본문으로 다시 찾지 않는다.

        쌍 비교 루프는 같은 집합을 수십만 번 되찾는다. 계산식은 위와 글자 그대로 같다."""
        intersection = len(ga & gb)
        return intersection / ((len(ga) + len(gb) - intersection) or 1)
