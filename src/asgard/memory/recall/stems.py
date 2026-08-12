"""어간을 깎는 형태소 표 — 조사·어미·접미 목록과 하한, 근거 판정에서 빼는 낱말."""

from __future__ import annotations

import re

# ── 근거 대조 원시함수 — 패턴(관측)과 노른(통찰)이 같은 기준을 쓴다 ─────────────────


def _content_words(text: str) -> set[str]:
    """근거 대조용 내용어 — 2자 이상 토큰. 조사·기호는 분리자로 흘려보낸다."""
    return {word.lower() for word in re.split(r"[^\w가-힣]+", text) if len(word) >= 2}


# ── 형태소 목록 — 어간을 깎는 **단 하나의** 자 ────────────────────────────────────
#
# **늘리는 사람은 여기 세 표만 보면 된다.** 조사를 더하려면 `_KO_PARTICLES`, 용언 어미는
# `_KO_ENDINGS`, 영어 굴절·파생 접미는 `_EN_SUFFIXES`. 다른 자리에 목록을 새로 적지 마라 —
# 이 저장소는 한동안 한국어를 두 가지 자로 쟀다: 회수(`query`)는 조사 목록으로 형태를 보고,
# 근거 대조(`_stem_floor`)는 낱말 길이의 절반으로 잘랐다. 그 비대칭이 근거 정밀도를 0.544 에
# 묶어 두었다 — 같은 코퍼스를 목록으로 재면 0.882 다 (`benchmarks/grounding/REPORT.md`).
#
# 표를 문자 체계로 가르는 이유: 한국어는 조사·어미가 낱말 **뒤에 붙어** 자라고(`배포`+`를`),
# 영어는 굴절·파생 접미가 어간을 **바꾸며** 붙는다(`deploy`+`ing`). 붙는 물건이 다르니 목록도
# 다르다. 한 표에 섞으면 영어 낱말이 한글 조사로 끝날 리 없어 헛돌기만 하고, 표를 늘리는
# 사람이 자기가 어느 언어를 건드리는지 못 본다.

_KO_PARTICLES: tuple[str, ...] = (
    "에서는", "으로는", "에게는", "한테는",
    "으로", "에서", "에게", "한테", "처럼", "까지", "부터", "에는", "에도", "로는",
    "이나", "라도", "마다", "밖에", "조차", "께서",
    "은", "는", "이", "가", "을", "를", "에", "의", "로", "과", "와", "도", "만",
)  # fmt: skip
_KO_ENDINGS: tuple[str, ...] = (
    "한다", "했다", "하고", "하는", "하며", "하지", "하기", "하게", "해서",
    "된다", "됐다", "되고", "되는", "되며",
    "이라", "라고", "이며",
)  # fmt: skip
# 영어 접미는 길이가 어간 길이에 **안 비례한다** — `deploys`는 1자만, `authorization`은 5자를
# 떼야 한다. 옛 절반 규칙이 둘 다 절반으로 깎아 `dep`가 `dependency`를 삼켰다.
#
# `ization`이 목록에 **없는** 것은 일부러다. 넣으면 `authorization`→`author`,
# `organization`→`organ`처럼 어근까지 벗겨져 남의 낱말을 삼킨다. `ation`만 두면 같은 파생을
# `authoriz`·`organiz`로 잡아 `authorize`·`organized`에는 붙고 어근에는 안 붙는다 —
# 벤치 수치는 그대로고(P 0.882·R 0.938, 실측 26-08-01) 과잉 절단만 사라진다.
_EN_SUFFIXES: tuple[str, ...] = (
    "ation", "ments", "tion", "ment", "ing", "ers", "ized", "ize", "ed", "er", "es", "s", "d",
)  # fmt: skip

# 판정용으로는 셋을 문자 체계별로 합쳐 **긴 것부터** 본다 — `에서는`을 `는`으로 먼저 떼면
# 남는 어간이 달라진다. 길이가 같은 두 접미는 한 낱말의 같은 끝에 동시에 붙을 수 없으므로
# 길이 내림차순 하나로 순서가 결정된다.
_KO_STEM_SUFFIXES: tuple[str, ...] = tuple(sorted({*_KO_PARTICLES, *_KO_ENDINGS}, key=len, reverse=True))
_EN_STEM_SUFFIXES: tuple[str, ...] = tuple(sorted(set(_EN_SUFFIXES), key=len, reverse=True))

# 접미를 떼고 이만큼은 남아야 뗀다 — 안 남으면 안 뗀다(= 완전 일치). 이 값도 문자 체계마다
# 다르다: 한국어 내용어는 2음절이 흔하고 그 2음절이 **온전한 낱말**이지만(`배포`·`검증`),
# 영어 2글자는 대개 낱말이 아니라 조각이다(`action`→`ac`, `add`→`ad`). 조각에서 맞히기
# 시작하면 우연 일치가 근거로 둔갑한다.
#
# 이 축은 근거 벤치가 못 잰다 — 합성 코퍼스에 짧은 영어 낱말 사례가 없어 en 2·3·4 가 전부
# 같은 수치를 낸다. 그래서 **영어 사전 235,616낱말**로 따로 쟀다 (실측 26-08-01): 2자 이하로
# 깎이는 낱말이 옛 절반 규칙에서 6,712건(2.8%), 목록+en=2 에서 320건(0.14%), en=3 에서
# **0건**이다. 4 로 더 올려도 0건이라 이득이 없고 `use`·`log`·`add` 같은 3자 어간만 죽는다.
KO_STEM_MIN = 2
EN_STEM_MIN = 3


def _stem_floor(word: str) -> int:
    """어간을 여기까지만 깎는다 — 근거 대조 판정의 **단 하나의** 하한.

    `_stem_hit`과 `norn._spans`가 같은 낱말을 같은 자리에서 찾아야 한다 (근거 검사는 통과했는데
    극성이 낱말을 못 찾는 일을 막는다 — `_spans` 독스트링). 두 곳이 각자 식을 적고 있으면 한쪽만
    고쳤을 때 그 계약이 조용히 깨진다. 규칙을 바꾸려는 사람은 여기 한 자리만 보면 된다.

    **무엇의 하한인가** (26-08-01 개정): 낱말 길이의 절반이 아니라 **형태소를 뗀 길이**다.
    위 세 표에 있는 조사·어미·접미로만 깎고, 없으면 완전 일치를 요구한다. 그래서 `_stem_hit`이
    시도하는 절단은 사실상 둘뿐이다 — 낱말 전체와 어간. 사이의 임의 절단은 어간의 접두사를
    다시 담을 뿐이라 판정을 못 바꾼다.

    **왜 길이를 버렸나.** 한국어는 길이로 원리적으로 못 가른다: `배포를`(진짜 근거)과
    `저장소`(가짜)가 **둘 다 3자→2자**로 깎인다. 하한을 3으로 올리면 한국어 재현율이
    1.000 → 0.588 → 0.059로 무너진다. 값의 문제가 아니라 자의 문제였다
    (`benchmarks/grounding/REPORT.md`, 합성 코퍼스 61낱말·12주장 실측 26-08-01):

        낱말 정밀도 0.544 → 0.882 · 재현율 0.969 → 0.938 · F0.5 0.596 → 0.893
        통찰 자동승격 정밀도 0.417 → 0.714 (허구 7건 중 0건 차단 → 5건 차단)

    코퍼스가 합성이라 절대 수치는 제품 품질이 아니다 — 두 자를 나란히 놓은 상대 비교로만 읽는다.

    **남는 대가**: 한 글자 조사(`도`·`로`)는 진짜 명사의 끝 글자이기도 해서 `가속도`→`가속`을
    만들고, 영어 자음 중복(`committed`→`commit`)과 어간 교체(`verification`→`verify`)는 목록이
    못 푼다. 실측 6건이 여기 걸린다 — 옛 자가 틀리던 28건의 5분의 1이다."""
    ascii_ = word.isascii()
    suffixes = _EN_STEM_SUFFIXES if ascii_ else _KO_STEM_SUFFIXES
    minimum = EN_STEM_MIN if ascii_ else KO_STEM_MIN
    for suffix in suffixes:
        if word.endswith(suffix) and len(word) - len(suffix) >= minimum:
            return len(word) - len(suffix)
    return len(word)


def _stem_hit(word: str, haystack: str) -> bool:
    """낱말이 건초더미에 어간으로 남아 있는가.

    집합 교집합으로는 한국어의 근거 일치를 못 잰다 — 조사·어미가 낱말 **뒤**에 붙어서 "금요일"과
    "금요일에는"이 서로 남남이 된다. 그래서 앞에서부터 잘라 보며 어간을 찾는다 (영어의
    굴절 deploy/deploying도 같은 기준으로 걸린다). 붙은 형태소를 뗀 자리까지만 자른다: 아무
    데서나 자르기 시작하면 우연 일치가 근거로 둔갑한다 (어디까지 자르는가는 `_stem_floor`)."""
    floor = _stem_floor(word)
    return any(word[:cut] in haystack for cut in range(len(word), floor - 1, -1))


# 근거 판정에서 빼는 주어·기능어 — 누구에 대한 기록인지는 근거의 증거가 아니다.
_GROUNDING_STOP = frozenset("오딘 사용자 유저 user odin the is are was were and or for with that this it its".split())


def _stopword(word: str) -> bool:
    """주어·기능어인가 — 조사·어미가 붙어도 같은 낱말이다 ("오딘은" = 오딘).

    꼬리 길이를 제한하는 이유: 앞을 우연히 공유하는 남의 낱말까지 삼키면 안 된다
    ("withdraw"는 "with"가 아니다)."""
    return any(word.startswith(stop) and len(word) - len(stop) <= 3 for stop in _GROUNDING_STOP)
