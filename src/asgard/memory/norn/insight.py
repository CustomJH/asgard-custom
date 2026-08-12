"""통찰 검사 — 근거 대조와 극성, 그리고 자기중독 방지 필터.

세 물음이 다 다르다: 소스가 있는가(`validate`) · 통찰이 그 소스에서 나왔는가
(`_insight_grounding`) · 나왔는데 뒤집지는 않았는가(`_polarity_conflict`).
어휘를 그대로 쓰면서 부정만 떼어 낸 문장은 근거 점수가 오히려 높으므로 두 검사가 다 필요하다.
"""

from __future__ import annotations

import re

from ..recall import _content_words, _stem_floor, _stem_hit, _stopword

INSIGHT_MAX_CHARS = 1200
INSIGHT_MIN_SOURCES, INSIGHT_MAX_SOURCES = 2, 6

# 통찰 근거 대역 — 소스의 **실존**이 아니라 **내용**을 보는 기준.
#
# 검증기가 파일 존재·개수·스캔만 보면 LLM은 무관한 페이지 두 장을 근거로 달아 허구를
# 정본으로 만들 수 있다. 실측(26-07-28): "금요일 배포 회피" + "점심에는 국수"를 근거로
# 제안된 "오딘은 매주 화성으로 이주한다"가 기각 사유 하나 없이 통과해 기본 safe에서
# 자동 적용됐다. 패턴 계층이 explicit 관측에 이미 거는 근거 검사를, 통찰에도 건다.
#
# 값은 실측에서 왔다 (진짜 통찰 7건 · 허구 4건, 한국어·영어 혼합):
#   허구            0.000 – 0.167  (주제어만 빌린 반쪽 허구가 0.167로 최고)
#   진짜(정직한 출처) 0.375 – 0.636
# 0.25는 그 사이에 있되 허구 쪽에 붙여 둔 값이다 — 통찰은 귀납이라 출처에 없던 추상어
# ("경향", "습관")를 정당하게 데려오므로 관측용 플로어(pattern.GROUNDING_FLOOR 0.34)를
# 그대로 쓰면 진짜를 벤다. 대신 근거가 옅은 구간은 버리지 않고 사람에게 넘긴다:
# 자율 적용은 0.40 이상만, 그 아래는 접수하되 제안으로 남는다. 코퍼스가 11건짜리
# 손수 만든 표본이라 자동 자격에는 여유를 더 둔다 — 틀렸을 때 비용이 다르다.
INSIGHT_GROUNDING_FLOOR = 0.25
INSIGHT_AUTO_FLOOR = 0.40

# 극성 판정 창 — 낱말에 붙은 부정을 어디까지 보고 읽을 것인가.
#
# 근거 검사는 "어디서 왔는가"를 묻지 "참인가"를 묻지 않는다. 두 물음은 다르고, 앞의 것만 물으면
# 어휘 재조합 거짓말이 통과한다. 실측 반례(26-07-28): 출처 "금요일에는 배포하지 않는다" ·
# "배포 전에 테스트를 전부 돌린다"에서 뽑은 "금요일마다 테스트 없이 배포한다"가 근거 점수
# 0.714로 통과했다 — 낱말은 전부 출처에서 왔는데 주장은 정반대다.
#
# 그 자리를 닫는 결정적 신호가 극성이다. 다만 부정의 **작용역**이 언어마다 다르다:
#
#   한국어 — 낱말에 붙어 인접에서 끝난다: "배포하지 않는다", "테스트 없이"
#   영어   — 동사에 붙어 절 오른쪽 전체를 덮는다: "never deploys on Fridays"
#            (부정어와 대상 낱말 사이가 멀다 — 인접 창으로는 영영 못 본다)
#
# 그래서 뒤는 짧은 창으로, 앞은 **절 단위**로 읽는다. 절 경계에 등위접속사를 넣는 것이
# 핵심이다: "avoids Friday deploys **and** always tests first"에서 avoids는 and를 넘지
# 못한다. 이 경계가 없으면 정직한 통찰이 자기 문장의 앞 절 때문에 부정으로 물든다 (실측).
POLARITY_PRE, POLARITY_POST, POLARITY_CLAUSE = 14, 12, 80
# 영어는 뒤쪽도 절 단위다. 수동태가 그 증거다 — "checks are bypassed"는 부정 동사가 주어
# 뒤에 서고, 한국어용 인접 창(12자)으로는 영영 닿지 않는다. 그래서 ASCII 앵커만 뒤도
# 절 경계까지 본다. 경계를 두는 것이 핵심이다: 창만 넓히면 "tests are run, deploys are
# skipped"에서 앞 절의 tests가 뒤 절의 부정에 물든다.
POLARITY_POST_CLAUSE = 40

# 낱말 뒤에 붙어 그 낱말을 부정하는 것들 (한국어 어미·보조용언 + 영어 후치 전치사).
#
# "안 한다" 만이 부정이 아니다. 한국어는 **하지 않음을 뜻하는 본동사**로도 똑같이 부정한다 —
# "테스트를 생략한다", "점검을 건너뛴다", "리뷰를 제외하고". 실측(26-07-30): 이 갈래가 사전에
# 없어 `_polarity("테스트", "배포 시 테스트를 생략한다")`가 **+1**을 돌려줬다. 출처가 부정하는
# 것을 긍정으로 읽으면 극성 게이트는 그 출처에 대해 영영 눈이 먼다.
_NEG_AFTER = re.compile(
    # 어간이 모음으로 끝나는 것들은 활용에서 음절이 통째로 갈린다 — "피하"로는 "피한다"를,
    # "삼가"로는 "삼간다"를 못 잡는다 (한자어 어간 지양·중단·거부 등은 활용해도 어간이 그대로다).
    r"않|못하|못한|못\s|없|말라|마라|금지|피하|피한|피함|피해|지양|삼가|삼간|삼감|회피|자제|거부|중단|아니|"
    # 한국어 활용은 어간의 **음절이 통째로 바뀐다** — "건너뛰"로는 "건너뛴다"를 못 잡는다
    # (뛰≠뛴, 자모가 아니라 음절이 코드포인트다). 갈래를 적어 두는 편이 어간을 줄이는 것보다
    # 안전하다: "건너"까지 줄이면 "건너편"·"건너서"가 부정으로 읽힌다.
    r"생략|누락|건너뛰|건너뛴|건너뜁|건너뜀|제외|빼고|빼는|빼먹|무시하|미실행|미적용|"
    r"(?:^|\s)안\s|\bwithout\b|\bnever\b|\bnot\b|\bno\b|\brather than\b|\binstead of\b|"
    # 영어 수동태 — "checks are bypassed"처럼 부정 동사가 주어 **뒤에** 온다. 능동태
    # ("omit the review")는 절 작용역인 _NEG_BEFORE가 잡는다.
    r"\b(?:are|is|was|were|get|gets|got)\s+(?:being\s+)?"
    r"(?:skipped|omitted|excluded|bypassed|ignored|dropped)\b",
    re.IGNORECASE,
)
# 낱말 앞 — 절 작용역. 영어 부정어만 본다: 한국어의 앞선 부정("결코")은 뒤의 "않"과 짝을
# 이루므로 _NEG_AFTER가 이미 잡고, 절까지 넓히면 옆 낱말까지 부정으로 물든다.
_NEG_BEFORE = re.compile(
    r"\b(?:not|never|no|without|avoids?|avoiding|refrains?|skips?|skipping|cannot|can'?t|don'?t|"
    # 하지 않음을 뜻하는 본동사 — 영어는 이것도 목적어 **앞**에 서서 절을 덮는다
    # ("deploys omit the review step"). 한국어 대응분은 _NEG_AFTER 쪽에 있다.
    r"omits?|omitting|exclud(?:e|es|ing)|bypass(?:es|ing)?|ignor(?:e|es|ing)|"
    r"doesn'?t|didn'?t|won'?t|rarely|seldom)\b",
    re.IGNORECASE,
)
# 낱말 앞 — 인접 작용역. 한국어 강조 부정 부사는 뒤 낱말 하나만 덮는 것으로 본다.
_NEG_BEFORE_ADJACENT = re.compile(r"결코|절대|(?:^|\s)안\s|(?:^|\s)못\s")
# 절 경계 — 구두점과 등위·종속 접속사. 부정은 이 선을 넘지 못한다.
_CLAUSE_EDGE = re.compile(
    r"[.;:,!?()\[\]\n]|\b(?:and|but|or|yet|while|whereas|though|although|however|because|so)\b",
    re.IGNORECASE,
)


# 자기중독 방지 — 환경 의존 실패·도구 부정 주장은 통찰이 아니라 그날의 사정이다.
_FORBIDDEN_INSIGHT = re.compile(
    r"command not found|no such file|permission denied|not installed|rate.?limit|"
    r"(?:tool|mcp|browser)s?\s+(?:is\s+)?(?:broken|not\s+work)|do(?:es)?\s+not\s+work|not supported|"
    r"credential|api.?key|unauthorized|미설치|권한 거부|작동하지 않",
    re.IGNORECASE,
)


def _confidence(n_sources: int) -> str:
    """근거 수가 confidence를 결정한다 — 2=low, 3~4=medium, 5+=high (LLM 자기 신고 불신)."""
    return "high" if n_sources >= 5 else "medium" if n_sources >= 3 else "low"


def _insight_grounding(title: str, text: str, sources: list[tuple[dict, str]]) -> tuple[float, list[float]]:
    """통찰의 내용어가 출처에 실제로 남아 있는 비율과, **출처별** 기여도.

    두 값이 다른 일을 한다. 총량은 "이 문장이 어디서 왔는가"를 묻고 (허구는 0에 붙는다),
    출처별 기여도는 "이 근거가 정말 근거인가"를 묻는다 — 통찰은 2장 이상에 걸쳐야만 보이는
    것이라는 계약(_NORN_SYS)이라, 아무것도 기여하지 않는 소스가 끼어 있으면 그 계약은
    거짓이다. 총량만 보면 진짜 소스 하나에 장식 소스를 달아 문턱을 넘길 수 있다."""
    claim = {w for w in _content_words(f"{title} {text}") if not _stopword(w)}
    if not claim:
        return 0.0, []
    haystacks = [f"{meta.get('title', '')} {body}".lower() for meta, body in sources]
    total = sum(1 for w in claim if any(_stem_hit(w, h) for h in haystacks)) / len(claim)
    per_source = [sum(1 for w in claim if _stem_hit(w, h)) / len(claim) for h in haystacks]
    return total, per_source


def _spans(word: str, haystack: str) -> list[tuple[int, int]]:
    """낱말이 건초더미에 나타난 자리들 — `_stem_hit`과 **같은 어간 규칙**으로 찾는다.

    근거 검사가 "있다/없다"로 답하는 자리를 극성은 "어디에 있나"로 물어야 해서 위치가 필요하다.
    두 함수가 다른 어간 규칙을 쓰면 근거 검사는 통과했는데 극성은 낱말을 못 찾는 일이 생긴다 —
    그래서 하한을 여기 다시 적지 않고 `_stem_floor` 하나에서 가져온다 (각자 적으면 갈라진다)."""
    floor = _stem_floor(word)
    for cut in range(len(word), floor - 1, -1):
        stem = word[:cut]
        found: list[tuple[int, int]] = []
        at = haystack.find(stem)
        while at != -1:
            found.append((at, at + len(stem)))
            at = haystack.find(stem, at + 1)
        if found:
            return found
    return []


def _anchors(text: str) -> set[str]:
    """극성을 물을 만한 낱말 — 짧은 기능어는 뺀다.

    한국어와 영어의 낱말 길이가 같은 뜻을 담지 않는다: "배포"는 두 글자로 내용어지만
    영어의 두세 글자는 대개 전치사·관사다("on", "to", "the"). 그런 낱말은 부분 문자열로
    남의 낱말 안에서도 걸려("on" ⊂ "front") 극성 판정을 흔든다. 척도를 문자 체계로 가른다."""
    return {w for w in _content_words(text) if not _stopword(w) and not (w.isascii() and len(w) < 4)}


def _clause_before(haystack: str, start: int) -> str:
    """낱말이 속한 절의 시작부터 낱말 앞까지 — 영어 부정의 작용역."""
    window = haystack[max(0, start - POLARITY_CLAUSE) : start]
    edges = [m.end() for m in _CLAUSE_EDGE.finditer(window)]
    return window[edges[-1] :] if edges else window


def _clause_after(haystack: str, end: int) -> str:
    """낱말 뒤부터 그 절이 끝나는 데까지 — 영어 수동태 부정("are bypassed")의 작용역."""
    window = haystack[end : end + POLARITY_POST_CLAUSE]
    edge = _CLAUSE_EDGE.search(window)
    return window[: edge.start()] if edge else window


def _polarity(word: str, haystack: str, *, assertion: bool = False) -> int | None:
    """낱말에 붙은 극성 — +1 긍정, -1 부정, None = 언급 없음 (또는 문서에서의 혼재).

    **혼재를 읽는 법이 문서와 주장에서 다르다.** 두 쪽이 다른 것이라서다:

      문서(출처) — 여러 문장의 모음. 같은 낱말을 긍정으로도 부정으로도 쓰면("배포에
        신중하며 … 금요일 배포를 피하고") 그 문서는 이 낱말에 **아무 편도 안 든다**.
        모르는 것을 모른다고 말해야 진짜 통찰이 극성으로 잘리지 않는다 → None.

      주장(통찰) — 하나의 단언. 제목은 본문에 붙은 **딱지**이지 따로 선 주장이 아니다.
        그래서 낱말에 부정이 한 번이라도 걸리면 그 단언은 부정을 말한 것이다 → -1.

    이 구분이 없을 때 무슨 일이 났는지 (실측 26-07-30). 검증기는 `title + text`를 한 덩어리로
    보는데, 제목은 본문의 핵심 명사를 되풀이하는 것이 정상이고 `_NORN_SYS`가 title+text 쌍을
    요구한다. 그 되풀이가 **비부정 위치의 +1**을 하나 만들어 본문의 -1과 상쇄되고, 혼재는
    None이 되어 게이트가 통째로 침묵했다 — 같은 거짓말이 제목만 갈아입으면 표식을 잃었다:

        제목 "배포 습관"          → 표식 있음   (앵커를 안 건드림)
        제목 "금요일 무테스트 배포"  → 표식 없음 ← 근거 점수 0.714로 자동 승격까지 갔다
        제목 "테스트 관련 습관"     → 표식 없음 ←

    부정 쪽으로 읽는 것이 안전한 쪽인 이유는 이 신호가 **기각이 아니라 표식**이기 때문이다
    (`_polarity_conflict` 독스트링). 과하게 달린 표식은 사람이 출처와 대조하고 넘기면 그만이고,
    안 달린 표식은 허구를 정본에 저장한다 — 두 오류의 비용이 다르다."""
    signs = set()
    for start, end in _spans(word, haystack):
        # 뒤쪽 작용역이 문자 체계마다 다르다 — 한국어는 낱말에 붙어 인접에서 끝나고,
        # 영어는 수동태로 절 오른쪽까지 간다 (POLARITY_POST_CLAUSE 주석).
        after = _clause_after(haystack, end) if word.isascii() else haystack[end : end + POLARITY_POST]
        negated = (
            bool(_NEG_AFTER.search(after))
            or bool(_NEG_BEFORE_ADJACENT.search(haystack[max(0, start - POLARITY_PRE) : start]))
            or bool(_NEG_BEFORE.search(_clause_before(haystack, start)))
        )
        signs.add(-1 if negated else 1)
    if len(signs) == 1:
        return signs.pop()
    return -1 if (signs and assertion) else None


def _polarity_conflict(title: str, text: str, sources: list[tuple[dict, str]]) -> tuple[str, str] | None:
    """통찰이 출처의 주장을 **뒤집었는가** — (낱말, 사유) 또는 None.

    근거 점수로는 못 잡는 거짓말의 모양이 하나 있다: 출처의 어휘를 그대로 쓰면서 부정만
    떼거나 붙이는 것. 그런 문장은 근거 점수가 오히려 **높다** (낱말이 전부 출처에서 왔으니까).

    표식은 만장일치일 때만 단다 — 그 낱말을 언급한 모든 출처가 통찰과 반대 극성일 때.
    한 출처라도 통찰 편이면 그건 모순이 아니라 출처들 사이의 이견이고, 이견의 해소는
    contradiction op가 사람에게 넘길 일이다.

    **왜 기각이 아니라 표식인가** (26-07-28 측정으로 정해졌다). 이 신호는 어휘만 보므로
    진짜 뒤집기와 우연한 극성 반전을 못 가른다. 둘은 형상이 같다:

        거짓말  통찰 "테스트 **없이** 배포" ↔ 출처 "테스트를 전부 돌린다"
        참      통찰 "문제 **없이** 배포"   ↔ 출처 "문제를 즉시 해결한다"

    가르려면 "테스트는 하는 일이고 문제는 겪는 상태"라는 세계 지식이 필요하다 — 어휘
    정련으로 닿지 않는 자리다. 충돌 앵커 수로도 안 갈렸다(진짜 거짓말 4건 중 2건이 앵커
    1개, 오탐 후보도 1~2개 — 완전히 겹친다).

    그래서 이 신호는 **자동 승격을 막는 데만** 쓴다: 되돌리기 어려운 쪽(정본화)에는 이
    정밀도로 충분하고, 후보 지식을 없애는 쪽에는 부족하다. 사람에게는 표식이 붙어 간다 —
    "이 낱말을 확인하라"는 말이 "이 통찰은 없다"보다 언제나 더 쓸모 있다."""
    claim = f"{title} {text}".lower()
    haystacks = [f"{meta.get('title', '')} {body}".lower() for meta, body in sources]
    # 긴 낱말부터 본다 — 기각 사유에 들어가는 것은 처음 걸린 낱말이고, 사람이 판단하려면
    # 그 낱말이 "on"이 아니라 "fridays" 여야 한다.
    for word in sorted(_anchors(claim), key=lambda w: (-len(w), w)):
        # 통찰은 단언이고 출처는 문서다 — 혼재를 같은 기준으로 읽으면 제목의 되풀이가 게이트를
        # 침묵시킨다 (`_polarity` 독스트링의 실측).
        mine = _polarity(word, claim, assertion=True)
        if mine is None:
            continue
        theirs = [p for p in (_polarity(word, hay) for hay in haystacks) if p is not None]
        if theirs and all(p == -mine for p in theirs):
            side = "출처는 부정하는데 통찰은 긍정한다" if mine > 0 else "출처는 긍정하는데 통찰은 부정한다"
            return word, side
    return None
