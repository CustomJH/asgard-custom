"""분포 자질 — 구(句) 목록으로 못 잡는 쉼표 밀도·어미 단조·길이 균일·문장 미완결."""

from __future__ import annotations

import re

from .clean import lintable_spans
from .tell import Finding

_SENT_SPLIT = re.compile(r"[.!?。！？\n]+")

# ── 문장 미완결 — 문단을 이어 붙인 뒤에만 잴 수 있는 자질.
#
# 위의 _SENT_SPLIT 은 줄바꿈도 문장 끝으로 센다. 밀도·단조를 잴 때는 그래도 되지만 종결
# 형태를 볼 때는 안 된다: 산문은 화면 너비에서 접히므로, 줄 하나를 문장으로 읽으면 접힌
# 자리마다 조사가 문장 끝으로 잡힌다. 그래서 문단부터 이어 붙인다.
#
# 이 아래 문턱과 면제를 정한 실측은 benchmarks/bragi-humanvoice 가 가지고 있다 — 코퍼스가
# git 이력에서 다시 세워지므로 값이 실행마다 움직이고, 움직이는 값을 주석이 사본으로 들면
# 한쪽만 낡는다. 수치가 필요하면 measure.py 를 돌려라. 여기 적는 것은 이유와 기제뿐이다.
_BLOCK_SPLIT = re.compile(r"\n\s*\n")
_SENT_END = re.compile(r"(?<=[.!?])\s+")
# 제목·목록·표 행은 문장이 아니라 항목이라 종결어미가 없는 것이 정상이다.
_ITEM_LINE = re.compile(r"^\s*(?:#{1,6}\s|[-*+•]\s|\d+[.)]\s|\|)")
_HANGUL_CH = re.compile(r"[가-힣]")
# 문장으로 셀 최소 길이. 이보다 짧은 조각은 제목·라벨·표 칸이 문장 부호를 달고 남은 것이라
# 종결어미가 없는 것이 정상이다. 이 값을 정한 것은 측정이 아니라 판단이다 — 여덟 글자면
# 주어와 서술어가 들어갈 자리는 된다.
_MIN_SENT_CHARS = 8
# 용언에 붙은 연결어미 — 이것으로 문장이 끝나면 뒤에 올 절이 통째로 없다.
# `고`·`면`은 어간을 고정한 형태만 받는다. 그러지 않으면 명사 `보고`·`참고`·`표면`·`화면`이
# 어미로 읽힌다 — 어간을 안 고정한 첫 판이 사람 글에서 이 명사들을 어미로 잡았다.
# `까지만`의 뒤 두 글자도 어미가 아니라 조사라, 앞에 `까`가 서면 받지 않는다.
# `니까`는 합쇼체 의문형(`적용하시겠습니까`)과 끝 두 글자가 같다. 그쪽은 종결어미라 물음표를
# 뗀 뒤에도 갈라야 하고, 표지는 앞 음절의 종성 ㅂ이다 (_formal_question).
_CONNECTIVE_END = re.compile(
    r"(?:[가-힣]며|하고|되고|이고|있고|없고|지고|으면|하면|되면|려면"
    r"|(?<!까)지만|[는은]데|니까|[라어아해]서|면서|으?므로|도록)$"
)
# 앞 문장에 이어 붙인 꼬리 — 대시·쉼표·콜론이 서면 절이 빠진 것이 아니라 앞 문장에서 옮겨졌거나
# 앞 문장을 늘여 적은 것이다 ("판정기를 끄는 것이라서", "6회차, 전/후를 번갈아, 뒤집어서",
# "이유가 그것이다: 옛 배치를 계속 증명하지 않도록").
#
# 이것이 이 규칙의 사각이고 작지 않다. 크기는 measure.py 가 `blind spot` 줄로 인쇄한다. 그래도
# 받아들이는 이유는 두 형상을 형태소 분석기 없이 못 가르기 때문이다 — 이 모듈의 계약은 못 읽은
# 것을 읽은 척하지 않는 것이고, 오탐을 내는 판정기는 다음에 꺼진다.
_CONTINUATION = re.compile(r"[—–,:：]")


def _sentences(body: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(body) if len(s.strip()) >= 10]


def _ko_sentences(spans: str) -> list[str]:
    """문단을 이어 붙여 얻은 한국어 문장 — 종결 부호로 끝난 것만, 종결 부호는 떼고 돌려준다.

    검사 사본은 `lintable`이 아니라 `lintable_spans`를 받는다. 종결 형태를 보는 규칙이라
    문장 끝이 남아 있어야 하는데, `lintable`은 인라인 코드와 경로를 지워서 문장이 코드로
    끝나면 그 자리를 잘라 낸다."""
    out: list[str] = []
    for block in _BLOCK_SPLIT.split(spans):
        lines = [ln.strip() for ln in block.splitlines() if not _ITEM_LINE.match(ln)]
        joined = " ".join(ln for ln in lines if ln)
        for raw in _SENT_END.split(joined):
            raw = raw.strip()
            if not raw.endswith((".", "!", "?")):
                continue  # 문단 끝의 미종결 조각 — 잘린 것인지 안 끝낸 것인지 못 가린다
            if raw.endswith("?"):
                continue  # 의문문은 종결어미로 끝난 완성된 문장이다
            sent = raw.rstrip(".!…").strip()
            if len(sent) >= _MIN_SENT_CHARS and len(_HANGUL_CH.findall(sent)) >= 5 and _HANGUL_CH.match(sent[-1]):
                out.append(sent)
    return out


def _formal_question(sent: str) -> bool:
    """합쇼체 의문형 `-습니까`·`-ㅂ니까` — 연결어미 `-니까`와 끝 두 글자가 같은 종결어미다.

    가르는 표지는 앞 음절의 종성 ㅂ이다: 합니까·봅니까·있습니까는 전부 그렇고, 연결어미 쪽
    (`없으니까`·`되니까`)은 아니다. 물음표를 안 붙이고 마침표로 끝낸 자리까지 잡는다."""
    if not sent.endswith("니까") or len(sent) < 3:
        return False
    ch = sent[-3]
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 == 17


def _unfinished_sentences(spans: str, quote: str = "") -> list[str]:
    """연결어미로 끝난 문장 — 서술어와 종결어미가 없어 뒤 절이 비어 있다.

    한국어 문장은 서술어 + 종결어미로 끝난다. 연결어미로 끝나면 읽는 사람은 이어질 절을
    기다리다 다음 문장으로 넘어간다. 명사구 종결(`… 갈리는 자리.`)은 같은 결함이지만 여기서
    안 잰다 — 사람이 쓴 기술 노트가 개조식으로 명사 종결을 쓰는 탓에, 어느 임계에서도 오탐이
    0에 가까워지지 않았다. 임계별 오탐은 measure.py 가 `noun-phrase endings` 줄로 인쇄한다.
    그 축은 계약(`templates/bragi.py`의 Korean 항목)이 맡는다.

    `quote`는 사용자가 먼저 쓴 글이다. 거기 이미 있는 문장은 새로 지은 것이 아니라 인용이라
    빼는데, 나머지 흔적이 `tell.rx.search(quote)`로 받는 면제와 같은 규칙이다."""
    return [
        s
        for s in _ko_sentences(spans)
        if _CONNECTIVE_END.search(s) and not _CONTINUATION.search(s) and not _formal_question(s) and s not in quote
    ]


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


def _statistical(body: str, lang: str, raw: str = "", source: str = "") -> list[Finding]:
    """구(句) 목록으로 못 잡는 분포 자질 — 쉼표 밀도·어미 단조·길이 균일·문장 미완결.

    `body`는 보존 계약 대상을 지운 검사 사본이고, `raw`는 손대지 않은 원문이다. 둘 다 받는
    이유는 문장 미완결이 종결 자리를 보기 때문이다 — `body`는 인라인 코드와 경로를 지워서
    문장이 코드로 끝나면 그 자리를 잘라 낸다. 원문을 안 주면 그 자질만 건너뛴다."""
    found: list[Finding] = []
    if lang == "ko":
        unfinished = _unfinished_sentences(lintable_spans(raw), lintable_spans(source)) if raw else []
        if unfinished:
            found.append(
                Finding(
                    "KO-unfinished-sentence",
                    "S1",
                    "grammar",
                    "문장이 연결어미로 끝났다 — 서술어와 종결어미로 끝맺는다 (`캐시를 지우도록.` → `캐시를 지운다.`)",
                    unfinished[0][-40:],
                    len(unfinished),
                )
            )
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
