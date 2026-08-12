"""분포 자질 — 구(句) 목록으로 못 잡는 쉼표 밀도·어미 단조·길이 균일."""

from __future__ import annotations

import re

from .tell import Finding

_SENT_SPLIT = re.compile(r"[.!?。！？\n]+")


def _sentences(body: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(body) if len(s.strip()) >= 10]


def _comma_density(body: str) -> tuple[float, int]:
    """쉼표를 포함한 문장의 비율. KatFishNet 최고 판별 자질(94.88% AUC)의 결정론 근사.

    논문 실측: LLM 한국어 61% vs 사람 26%. 임계는 0.70 — 논문의 LLM 평균보다 위다.
    논문 표본은 뉴스·에세이인데 이 게이트가 보는 글은 기술 산문이라, 쉼표로 열거하는
    사람 글이 정상적으로 더 많다 (26-07-26 실측: 이 저장소 커밋 본문 326건에서 0.55 임계는
    3.7%를 오탐, 0.70은 그 대부분을 제거한다). 분포 자질은 보수적으로 두고 군집에 맡긴다."""
    sents = _sentences(body)
    if not sents:
        return 0.0, 0
    return sum(1 for s in sents if "," in s or "、" in s) / len(sents), len(sents)


def _ending_monotony(body: str) -> tuple[float, int]:
    """같은 어미로 끝나는 문장의 비율 — 구조 단조로움의 결정론 근사.

    어미가 형태론적으로 존재하는 언어(한국어·일본어)에서만 뜻이 있다. 영어 문장의 끝 세 글자는
    어미가 아니라 그냥 마지막 단어의 꼬리라서, 목록·명세에서 대량 오탐을 낸다 (26-07-26 실측 635건)."""
    sents = _sentences(body)
    if len(sents) < 4:
        return 0.0, len(sents)
    tails: dict[str, int] = {}
    for s in sents:
        tails[s[-3:]] = tails.get(s[-3:], 0) + 1
    return max(tails.values()) / len(sents), len(sents)


def _length_uniformity(body: str) -> tuple[float, int]:
    """문장 길이 변동계수 — 낮을수록 기계적 리듬 (사람 글은 길이가 들쭉날쭉하다).

    📊 경험적 자질 (burstiness) — 단독 판정 금지라 S3 로만 쓴다."""
    sents = _sentences(body)
    if len(sents) < 8:
        return 1.0, len(sents)
    lens = [len(s) for s in sents]
    mean = sum(lens) / len(lens)
    if mean <= 0:
        return 1.0, len(sents)
    var = sum((x - mean) ** 2 for x in lens) / len(lens)
    return (var**0.5) / mean, len(sents)


def _statistical(body: str, lang: str) -> list[Finding]:
    """구(句) 목록으로 못 잡는 분포 자질 — 쉼표 밀도·어미 단조·길이 균일."""
    found: list[Finding] = []
    if lang == "ko":
        ratio, n = _comma_density(body)
        if n >= 8 and ratio > 0.70:
            found.append(
                Finding(
                    "KO-comma-density",
                    "S2",
                    "punctuation",
                    "쉼표를 포함한 문장이 과반 — 영어식 쉼표를 덜어낸다 (KatFishNet 94.88% AUC)",
                    f"{ratio:.0%} of {n} sentences",
                    n,
                )
            )
    ratio, n = _ending_monotony(body) if lang in ("ko", "ja") else (0.0, 0)
    if n >= 6 and ratio > 0.7:
        found.append(
            Finding(
                "U-ending-monotony",
                "S2",
                "structure",
                "문장 어미가 한 형태로 수렴 — 길이와 종결을 섞는다",
                f"{ratio:.0%} identical endings",
                n,
            )
        )
    cv, n = _length_uniformity(body)
    if n >= 8 and cv < 0.32:
        found.append(
            Finding(
                "U-length-uniformity",
                "S3",
                "structure",
                "문장 길이가 균일 — 사람 글은 짧고 긴 문장이 섞인다",
                f"CV {cv:.2f} over {n} sentences",
                n,
            )
        )
    return found
