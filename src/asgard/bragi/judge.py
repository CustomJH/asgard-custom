"""판정 — 흔적 목록(tells) → 등급(grade) → 게이트가 소비하는 문자열(violations)."""

from __future__ import annotations

from . import registry
from .clean import _SPAN_SENSITIVE, lintable, lintable_spans
from .detect import detect_lang
from .stats import _statistical
from .tell import _S2_MIN_HITS, Finding
from .universal import _UNIVERSAL


def tells(text: str, lang: str | None = None, source: str = "") -> list[Finding]:
    """AI 작문 흔적 목록 — 심각도 순(S1→S2→S3).

    source에 이미 나온 표현은 새 추론이 아니라 인용이므로 잡지 않는다 (lagom과 같은 규칙).

    판정 규칙은 Wikipedia:Signs of AI writing의 **군집 원칙**을 그대로 옮긴 것이다 —
    "엠대시 하나는 아무것도 아니지만, 엠대시 + 3박자 + vibrant tapestry는 자백이다".

      S1  단독으로 결정적 — 즉시 보고.
      S2  ① 같은 패턴이 _S2_MIN_HITS 회 이상(밀도 신호) 또는 ② 서로 다른 흔적이 둘 이상
          함께 나타남(군집 신호)일 때 보고. 한 종류가 한 번 나온 것만으로는 보고하지 않는다.
      S3  S1·S2가 하나라도 보고된 뒤에만 보고 — 단독 판정은 구조적으로 불가능하다.

    ②가 없으면 짧은 글은 전부 빠져나간다: 세 문장짜리 문단에서 같은 흔적이 세 번 나올 수
    없기 때문이다 (26-07-26 실측 — 상류 라벨 코퍼스 재현율 19% → 군집 규칙 도입 후 회복)."""
    body = lintable(text)
    if not body.strip():
        return []
    lang = lang or detect_lang(body)
    evidence = lintable(source)
    pool = list(_UNIVERSAL) + registry._REGISTRY.get(lang, [])
    if lang not in registry.LATIN_LANGS:  # 엠대시·타이틀 케이스는 라틴 조판 전용 규칙
        pool = [t for t in pool if not t.id.startswith("EN-em-dash") and not t.id.endswith("title-case-heading")]
    matched: list[Finding] = []
    spans: tuple[str, str] | None = None
    for tell in pool:
        if tell.id in _SPAN_SENSITIVE:
            if spans is None:
                spans = (lintable_spans(text), lintable_spans(source))
            subject, quote = spans
        else:
            subject, quote = body, evidence
        hits = tell.rx.findall(subject)
        if not hits or tell.rx.search(quote):  # 사용자가 먼저 쓴 표현 = 인용
            continue
        m = tell.rx.search(subject)
        matched.append(
            Finding(tell.id, tell.severity, tell.category, tell.hint, (m.group(0) if m else "").strip()[:60], len(hits))
        )
    matched += _statistical(body, lang)
    # 군집 크기 = 함께 나타난 서로 다른 결정적·빈도 흔적의 종류 수 (약신호는 세지 않는다)
    cluster = sum(1 for f in matched if f.severity in ("S1", "S2"))
    strong = [f for f in matched if f.severity == "S1" or (f.hits >= _S2_MIN_HITS or cluster >= 2)]
    strong = [f for f in strong if f.severity != "S3"]
    if not strong:
        return []
    weak = [f for f in matched if f.severity == "S3"]
    order = {"S1": 0, "S2": 1, "S3": 2}
    return sorted(strong + weak, key=lambda f: (order[f.severity], f.id))


def grade(findings: list[Finding]) -> str:
    """자연도 등급 A/B/C/D — 상류 korean-skills의 경계를 그대로 계승한다.

    A = S1 0 + S2 ≤2 · B = S1 1~2 또는 S2 3~5 · C = S1 3+ 또는 S2 6+ · D = S1 5+ 이고 S2 8+.

    경계는 패턴 종류가 아니라 **출현 횟수**로 센다. S2는 정의상 빈도 신호라, 한 패턴이
    아홉 번 나온 글과 한 번 나온 글을 같은 등급에 둘 수 없다 (종류로 세면 전자가 A가 된다)."""
    s1 = sum(f.hits for f in findings if f.severity == "S1")
    s2 = sum(f.hits for f in findings if f.severity == "S2")
    if s1 >= 5 and s2 >= 8:
        return "D"
    if s1 >= 3 or s2 >= 6:
        return "C"
    if s1 >= 1 or s2 >= 3:
        return "B"
    return "A"


def violations(text: str, source: str = "", lang: str | None = None) -> list[str]:
    """게이트가 소비하는 문자열 형태 — lagom.style_violations와 같은 계약."""
    return [
        f"{f.severity} {f.id}: {f.hint}" + (f' (e.g. "{f.sample}")' if f.sample else "")
        for f in tells(text, lang, source)
    ]
