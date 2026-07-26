"""Bragi — 다국어 휴먼체 엔진. 보고문이 사람이 쓴 글로 읽히는지 결정론으로 판정한다.

브라기는 시가(詩歌)와 언변의 신 — 아스가르드가 결과를 보고할 때 쓰는 문장을 맡는다.
Lagom 이 "얼마나 적게 쓰는가"(압축·근거)를 보는 축이라면, 브라기는 "사람처럼 읽히는가"를 본다.
두 축은 겹치지 않는다: Lagom 은 근거 없는 효용 주장을 잡고, 브라기는 LLM 특유의 문장 습관을 잡는다.

계층: domain (settings 만 lazy 임포트). 프롬프트 계약은 templates/bragi.py.

판정 구조
  탐지기(tells)   언어별 패턴 + 언어 무관 패턴을 원문의 검사 사본에 적용
  심각도          S1 = 1회로 결정적 · S2 = 3회 이상이거나 다른 흔적과 동반될 때 · S3 = 군집일 때만
  등급(grade)     A/B/C/D — 상류 korean-skills 의 자연도 등급 경계를 그대로 계승

임계는 취향이 아니라 실측으로 정했다. benchmarks/bragi-humanvoice/ 가 상류 라벨 코퍼스(Part A),
이 저장소가 쌓아 온 사람 글 677건(Part B), 로컬 모델 A/B(Part C)로 채점한다. 쉼표 밀도 0.70,
굵은 머리말 S3 강등, 어미 단조 한·일 한정은 전부 Part B 오탐을 보고 되돌린 결정이다.

근거 (패턴마다 verified 필드로 표기)
  ✅ KatFishNet (ACL 2025, arXiv 2503.00032) — 한국어 쉼표 94.88 · 품사 82.99 · 띄어쓰기 79.51 AUC
  ✅ Kobak et al., Science Advances 2025 (arXiv 2406.07016) — 영어 초과 어휘 (2024 초록 13.5% LLM 처리)
  ✅ Juzek & Ward, COLING 2025 — ChatGPT 초점어 21종 (delve/intricate/pivotal …)
  ✅ Wikipedia:Signs of AI writing (WikiProject AI Cleanup) — blader/humanizer 31k★ 의 근거 문서
  📊 언어별 커뮤니티 코퍼스 — vi(longhang2004) · ja(gonta223) · zh(op7418) · ko(DaleSeo)

언어 확장은 register() 한 줄이면 된다 — 코어를 건드리지 않는다. 등록되지 않은 언어도
언어 무관 패턴만으로 동작한다 (탐지력은 낮지만 침묵하지 않는다).
"""

from __future__ import annotations

import os
import re
from typing import NamedTuple

# ── 지원 언어. "generic" 은 미등록 언어의 폴백 신원 — 언어 무관 패턴만 돈다.
LANGS = ("en", "ko", "ja", "zh", "vi", "es", "fr", "ru", "generic")
# 라틴 문자권 — 엠대시·타이틀 케이스처럼 라틴 조판에서만 성립하는 규칙의 적용 대상.
# 한국어·일본어·중국어 조판에서 줄표는 AI 신호가 아니다 (KatFishNet 의 한국어 신호는 쉼표다).
LATIN_LANGS = frozenset({"en", "es", "fr", "vi"})

SEVERITIES = ("S1", "S2", "S3")
_S2_MIN_HITS = 3  # S2 = 빈도 기반 — 1~2회는 사람 글에서도 흔하다
_GRADES = ("A", "B", "C", "D")


class Tell(NamedTuple):
    """AI 작문 흔적 하나. rx 는 검사 사본에 적용되는 컴파일된 패턴."""

    id: str
    category: str
    severity: str
    rx: re.Pattern[str]
    hint: str  # 사람·모델이 읽는 교정 지시 — 무엇으로 바꿔야 하는지


class Finding(NamedTuple):
    """탐지 결과 하나."""

    id: str
    severity: str
    category: str
    hint: str
    sample: str  # 원문에서 잡힌 첫 표본 (교정 대상 지시용)
    hits: int


def _t(tid: str, category: str, severity: str, pattern: str, hint: str, flags: int = 0) -> Tell:
    return Tell(tid, category, severity, re.compile(pattern, flags), hint)


# ── 언어 무관 패턴 — 문자 체계와 무관하게 성립하는 서식·대화 잔재 흔적.
_UNIVERSAL: list[Tell] = [
    _t(
        # blader §16 은 이걸 강한 신호로 보지만, 명세·체크리스트에서는 정당한 서식이다
        # (26-07-26 실측: 저장소 자체 .md 에서 최다 오탐 원인). S3 = 군집일 때만 보고.
        "U-bold-header-list",
        "structure",
        "S3",
        r"^\s*[-*]\s+\*\*[^*\n]{1,40}\*\*\s*:",
        "Bolded inline headers with colons are an LLM formatting habit. Write it as prose or drop the header.",
        re.M,
    ),
    _t(
        "U-emoji-decoration",
        "structure",
        "S3",
        r"[\U0001f000-\U0001faff✅❌❗✨⭐⚡]",
        "Drop decorative emoji. They carry no information.",
    ),
    _t(
        "U-curly-quote",
        "punctuation",
        "S3",
        r"[“”‘’]",
        "Use straight quotes. Weak on its own, but it counts inside a cluster.",
    ),
    _t(
        "U-chat-artifact",
        "communication",
        "S1",
        r"(?:I hope this helps|Let me know if|Would you like me to|Want me to|Should I continue"
        r"|도움이 되었으면|더 궁금한 (?:점|것)이 있으면|필요하시면 말씀|추가로 원하시면"
        r"|Hy vọng (?:bài viết |thông tin )?(?:này )?(?:sẽ )?(?:hữu ích|giúp)"
        r"|お役に立て(?:ば|れば)|ご不明な点が|希望(?:这|對你)(?:对您|對您)?有(?:所)?帮助)",
        "Chat residue. Delete it from a report.",
        re.I,
    ),
    _t(
        "U-sycophancy",
        "communication",
        "S1",
        r"(?:Great question|Excellent point|You'?re absolutely right|Certainly!|Of course!"
        r"|좋은 (?:질문|지적)이(?:에요|네요|십니다)|말씀하신 대로(?:입니다|예요)"
        r"|Câu hỏi (?:rất )?hay|素晴らしい(?:質問|ご指摘))",
        "Drop the flattering opener and start with the fact.",
        re.I,
    ),
]

# ── 영어 — Kobak et al. 초과 어휘 + Juzek & Ward 초점어 + Wikipedia:Signs of AI writing.
_EN: list[Tell] = [
    _t(
        "EN-excess-vocab",
        "vocabulary",
        "S2",
        r"\b(?:delve|intricate|intricacies|pivotal|tapestry|testament|underscore[sd]?|showcas(?:e|es|ing)"
        r"|realm|multifaceted|meticulous|commendable|garner(?:ed|s)?|foster(?:ing|s|ed)?|bolster"
        r"|myriad|plethora|elevat(?:e|es|ing)|resonat(?:e|es|ing)|interplay|nuanced)\b",
        "Excess vocabulary (Kobak 2025). Replace with a plain verb or noun.",
        re.I,
    ),
    _t(
        "EN-significance-inflation",
        "content",
        "S1",
        r"(?:plays? a (?:vital|crucial|pivotal|key|significant) role|mark(?:s|ing) a (?:pivotal|significant|key) "
        r"(?:moment|milestone|shift)|stands? as a testament|underscor(?:es|ing) the (?:importance|significance)"
        r"|reflect(?:s|ing) (?:a )?broader|setting the stage for|evolving landscape|indelible mark)",
        "Inflated significance. Replace with a measurable fact or cut the sentence.",
        re.I,
    ),
    _t(
        "EN-promotional",
        "content",
        "S1",
        r"\b(?:nestled|in the heart of|breathtaking|must-visit|boasts a|groundbreaking|game[- ]?chang(?:er|ing)"
        r"|revolutionary|cutting[- ]edge|state[- ]of[- ]the[- ]art|unparalleled|seamlessly integrat)",
        "Advertising voice. State the verified number or what it does.",
        re.I,
    ),
    _t(
        "EN-participle-analysis",
        "grammar",
        "S2",
        r",\s+(?:highlighting|underscoring|emphasizing|showcasing|reflecting|symbolizing|ensuring"
        r"|fostering|contributing to|allowing for|enabling|paving the way|cementing)\b",
        "Tacked-on -ing clause faking depth. Split the sentence or cut the clause.",
        re.I,
    ),
    _t(
        "EN-negative-parallelism",
        "grammar",
        "S2",
        r"(?:not (?:just|only|merely)\b[^.!?\n]{0,120}\b(?:but|it'?s)\b|it'?s not (?:a|just|about))",
        "Negative parallelism (not just X but Y). State the claim directly.",
        re.I,
    ),
    _t(
        "EN-copula-avoidance",
        "grammar",
        "S2",
        r"\b(?:serves as|stands as|represents a|boasts|offers a range of)\b",
        "Copula avoidance. Go back to plain is/are/has.",
        re.I,
    ),
    _t(
        "EN-filler",
        "filler",
        "S2",
        r"(?:it is important to note that|it'?s worth noting that|in order to\b|due to the fact that"
        r"|at this point in time|has the ability to|in the event that|when it comes to)",
        "Filler construction. Use the short equivalent.",
        re.I,
    ),
    _t(
        "EN-hedge-stack",
        "filler",
        "S2",
        r"(?:could potentially|may possibly|might possibly|it could be argued that|somewhat of a"
        r"|relatively (?:speaking|straightforward))",
        "Stacked hedging. Commit, or state the actual condition.",
        re.I,
    ),
    _t(
        "EN-generic-conclusion",
        "content",
        "S1",
        r"(?:the future looks bright|exciting times (?:lie |are )ahead|a step in the right direction"
        r"|continues? to (?:thrive|evolve|shape)|remains? to be seen how)",
        "Generic upbeat ending. Stop at the last concrete fact.",
        re.I,
    ),
    _t(
        "EN-signposting",
        "communication",
        "S1",
        r"(?:let'?s (?:dive|explore|break (?:this|it) down|take a look)|here'?s what you need to know"
        r"|without further ado|in this (?:article|section), we(?:'ll| will))",
        "Signposting. Do not announce it, just write it.",
        re.I,
    ),
    _t(
        "EN-vague-attribution",
        "content",
        "S2",
        r"(?:experts? (?:say|argue|believe|suggest)|industry reports?|observers have|many believe"
        r"|studies (?:show|suggest) that|it is (?:widely )?believed that)",
        "Vague appeal to authority. Name the source or cut the claim. Never invent a source.",
        re.I,
    ),
    _t(
        "EN-authority-trope",
        "content",
        "S2",
        r"(?:the real question is|at its core|what really matters|the heart of the matter|the deeper issue)",
        "Pseudo-insight opener. Write the claim that follows it instead.",
        re.I,
    ),
    _t(
        "EN-aphorism",
        "content",
        "S2",
        r"\b(?:is|becomes) the (?:language|currency|architecture|backbone|foundation) of\b",
        "Aphorism formula. Replace it with the concrete claim it gestures at.",
        re.I,
    ),
    _t(
        "EN-unsupported-benefit",
        "claim",
        "S1",
        r"\b(?:guarantee[sd]?|ensures? (?:reliability|security|stability)|production[- ]ready|battle[- ]tested"
        r"|future[- ]proof|zero[- ]configuration|significantly (?:improv|reduc|enhanc)\w*)\b",
        "Unsupported benefit claim. Keep only what the input or the verified results say.",
        re.I,
    ),
    _t(
        "EN-notability",
        "content",
        "S2",
        r"(?:active social media presence|independent coverage|(?:local|regional|national) media outlets"
        r"|written by a leading expert|has been (?:featured|cited) in [A-Z][^.\n]{0,40},)",
        "Notability listing. Keep the one citation that has context and drop the list.",
        re.I,
    ),
    _t(
        "EN-false-range",
        "content",
        "S2",
        r"from [^.!?\n]{5,60} to [^.!?\n]{5,60}, from ",
        "False range (from X to Y, from A to B). List the actual items.",
        re.I,
    ),
    _t(
        "EN-cutoff-disclaimer",
        "content",
        "S1",
        r"(?:as of my (?:last )?(?:training|knowledge)|up to my last training update"
        r"|while specific details (?:about|are|remain)|based on (?:the )?available information"
        r"|(?:is|are) not publicly available|maintains a low profile|prefers to stay out of the spotlight)",
        "Knowledge-cutoff disclaimer or speculative gap-filling. Say what is unknown, or cut the sentence.",
        re.I,
    ),
    _t(
        "EN-challenges-section",
        "structure",
        "S1",
        r"(?:faces? (?:several|numerous|its share of|a number of) challenges|despite (?:these|those) challenges"
        r"|challenges and (?:future|legacy)|future (?:outlook|prospects))",
        "Formulaic 'challenges and outlook' section. Write only the problems you confirmed.",
        re.I,
    ),
    _t(
        "EN-conversational-opener",
        "communication",
        "S2",
        r"(?:^|\n|\. )(?:Honestly\?|Look,|Here'?s the thing|The thing is,|Let'?s be honest|Real talk)",
        "Staged candour opener. Just say the thing.",
        re.I,
    ),
    _t(
        "EN-hyphen-predicate",
        "grammar",
        "S3",
        r"\b(?:is|are|was|were|be)\s+(?:high-quality|data-driven|cross-functional|end-to-end|real-time"
        r"|long-term|well-known|client-facing|decision-making)\b",
        "Hyphenated compound in predicate position. People drop the hyphen there.",
        re.I,
    ),
    _t(
        # blader §14 는 하드 금지지만, 이 저장소의 사람 글이 엠대시를 상시 쓴다 (26-07-26 실측
        # held-out 코퍼스). 상류 자신의 오탐 지침도 "엠대시 단독은 증거가 아니다"라고 못박는다
        # → S3 로 둔다: 다른 흔적과 함께일 때만 보고되고, 혼자서는 절대 게이트를 울리지 않는다.
        "EN-em-dash",
        "punctuation",
        "S3",
        r"\s[—–]\s|\w[—–]\w",
        "Em dash overuse in Latin script. Use a period, comma, or colon.",
    ),
    _t(
        "EN-title-case-heading",
        "structure",
        "S3",
        r"^#{1,6}\s+(?:[A-Z][a-z]+\s+){2,}[A-Z][a-z]+\s*$",
        "Title Case heading. Use sentence case.",
        re.M,
    ),
]

# ── 한국어 — KatFishNet 3대 자질(쉼표·품사·띄어쓰기) + korean-skills 번역투/결말 코퍼스.
_KO: list[Tell] = [
    _t(
        "KO-hype",
        "vocabulary",
        "S2",
        # 한국어 형용사는 활용한다 (강력한·강력하고·강력히) — 어간으로 잡지 않으면 대부분 샌다
        r"(?:혁신적|획기적|압도적|비약적|눈부시|괄목할|전례 없는|차별화|강력하|강력한|탁월"
        r"|효과적|지속가능|핵심적|필수적|극대화|대폭|적극적)",
        "Hype adjective. Replace it with the measured number.",
    ),
    _t(
        "KO-three-beat",
        "structure",
        "S2",
        # 3박자 나열 — "제공하고, 경감시키며, 가능하게" / "환경 보호, 경제 성장, 사회적 형평성을"
        r"(?:하고|되고|이고|하며|되며),\s*[^,\n]{1,30}(?:하며|되며|시키며|이며)"
        r"|[가-힣]{2,}\s*,\s*[가-힣]{2,}\s*,\s*[가-힣]{2,}(?:을|를|이|가|은|는|의)\s",
        "Rule-of-three listing. Write the number of items there actually are.",
    ),
    _t(
        "KO-translationese-particle",
        "translationese",
        "S2",
        r"(?:에 대해서?|에 대한|를 통해서?|을 통해서?|에 있어서|와 관련하여|에 의해서?)",
        "Translationese particle. State it directly in native Korean word order.",
    ),
    _t(
        "KO-passive-overuse",
        "translationese",
        "S1",
        r"(?:되어지|지게 되|되어진다|보여진다|생각되어)",
        "Double passive. Put it back in the active voice.",
    ),
    _t(
        "KO-verb-redundancy",
        "translationese",
        "S2",
        r"(?:가지고 있|갖고 있|을 가진다|를 가진다|하고 있는 중)",
        "Redundant verb phrase. Reduce it to 있다/이다.",
    ),
    _t(
        "KO-closing-formula",
        "content",
        "S1",
        # 주격 조사는 받침 유무로 이/가 가 갈린다 — 둘 다 받는다 ("행보가 기대된다"가 실제 표면형)
        r"(?:주목할 만하다|주목할 만합니다|앞으로의 (?:행보|전망)[이가] (?:기대|주목)|중요한 시사점"
        r"|귀추가 주목|한 걸음 더 나아가|더욱 발전할 것으로)",
        "Machine closing formula. End on the last fact.",
    ),
    _t(
        "KO-abstract-chain",
        "vocabulary",
        "S2",
        r"[가-힣]{1,4}적(?:\s|인\s)[가-힣]{1,6}적(?:\s|인\s)",
        "Chain of ~적 abstractions. Use concrete nouns.",
    ),
    _t(
        "KO-possessive-chain",
        "grammar",
        "S2",
        r"[가-힣]{2,}의\s+[가-힣]{2,}의\s+[가-힣]{2,}",
        "Noun phrase built from stacked 의. Unpack it into verbs.",
    ),
    _t(
        "KO-plural-suffix",
        "grammar",
        "S3",
        r"[가-힣]{2,}들(?:을|이|은|의|에게|과|와|,|\s)",
        "Overused plural 들. Korean reads more naturally without marking plurals.",
    ),
    _t(
        "KO-possibility-overuse",
        "grammar",
        "S2",
        # 'ㄹ 수 있다'의 앞 음절은 동사마다 다르다 (할·볼·높일·줄일) — 어간을 고정하지 않는다
        r"(?:[가-힣] 수 있(?:다|습니다|어요|는)|가능하게 한다)",
        "Overused ~할 수 있다. State what was actually done.",
    ),
    _t(
        "KO-future-assertion",
        "grammar",
        "S2",
        r"(?:것이다|것입니다|일 것으로 (?:보인다|예상)|리라 (?:본다|기대))",
        "Future assertion ~것이다. Report only confirmed results.",
    ),
    _t(
        "KO-pronoun-overuse",
        "grammar",
        "S3",
        r"(?:그것|이것|저것|그들|이들)(?:은|는|이|을|의|에)",
        "Too many demonstratives. Korean reads more naturally when the subject is dropped.",
    ),
    _t(
        "KO-chat-closing",
        "communication",
        "S1",
        r"(?:무엇이든 물어보세요|언제든 말씀해\s?주세요|도와드리겠습니다|기꺼이 도와)",
        "Conversational sign-off. Delete it from a report.",
    ),
]

# ── 베트남어 — longhang2004/vietnamese-humanizer 패턴 코퍼스에서 고신뢰 항목만.
_VI: list[Tell] = [
    _t(
        "VI-role-in-doing",
        "translationese",
        "S1",
        r"đóng vai trò.{0,35}trong việc",
        "'đóng vai trò ... trong việc'. Promote the real verb to the predicate.",
        re.I,
    ),
    _t(
        "VI-context-inflation",
        "content",
        "S1",
        r"trong bối cảnh[^.!?\n]{0,60}(?:không ngừng|ngày càng) phát triển",
        "Inflated context framing. Cut the sentence or replace it with a concrete fact.",
        re.I,
    ),
    _t(
        "VI-hype",
        "vocabulary",
        "S2",
        r"\b(?:đột phá|vượt trội|đẳng cấp|ấn tượng|tuyệt vời|toàn diện|mạnh mẽ|tối ưu hóa)\b",
        "Hype vocabulary. Replace it with the measured number.",
        re.I,
    ),
    _t(
        "VI-vague-attribution",
        "content",
        "S1",
        r"(?:các chuyên gia|nhiều nghiên cứu|giới quan sát|nhiều nguồn)\s+(?:cho rằng|chỉ ra|nhận định)",
        "Vague appeal to authority. Name the source or cut the claim.",
        re.I,
    ),
    _t(
        "VI-negative-parallelism",
        "grammar",
        "S2",
        r"không chỉ.{0,100}mà còn",
        "'không chỉ ... mà còn' parallelism. State the claim directly.",
        re.I,
    ),
    _t(
        "VI-connector-pileup",
        "structure",
        "S2",
        r"\b(?:đồng thời|qua đó|từ đó|bên cạnh đó|ngoài ra|hơn nữa)\b",
        "Piled-up connectives. Break the sentence.",
        re.I,
    ),
    _t(
        "VI-leverage",
        "translationese",
        "S1",
        r"tận dụng (?:sức mạnh|khả năng|nền tảng|công nghệ)",
        "Literal calque of English 'leverage'. Name the actual action.",
        re.I,
    ),
    _t(
        "VI-nominalized-verb",
        "translationese",
        "S2",
        r"(?:đưa ra|cung cấp) sự (?:hỗ trợ|cải thiện|thay đổi|đánh giá)",
        "Nominalized verb. Use the verb itself.",
        re.I,
    ),
    _t(
        "VI-closing-formula",
        "content",
        "S2",
        r"\b(?:tóm lại|nhìn chung|nói tóm lại|có thể thấy rằng)\b",
        "Closing formula. End on the last fact.",
        re.I,
    ),
    _t(
        "VI-passive-boi",
        "translationese",
        "S2",
        r"\bđược\b[^.!?\n]{1,80}?\bbởi\b",
        "'được ... bởi' passive. Make the actor the subject.",
        re.I,
    ),
    _t(
        "VI-we-all-know",
        "content",
        "S1",
        r"chúng ta (?:đều|ai cũng) (?:biết|hiểu|thừa nhận|đồng ý)",
        "'as we all know'. Do not assume the reader agrees.",
        re.I,
    ),
    _t(
        "VI-double-conjunction",
        "grammar",
        "S2",
        r"\bvì vậy\s*,?\s+nên\b|\bbởi vì\b[^.!?\n]{0,140}\bcho nên\b|\b(?:không những|không chỉ)\b[^.!?\n]{0,160}\bnhưng còn\b",
        "Doubled conjunction. Keep one.",
        re.I,
    ),
    _t(
        "VI-redundant-plural",
        "grammar",
        "S2",
        r"\bcác\s+những\b|\bnhững\s+các\b",
        "Doubled plural marker. Use one.",
        re.I,
    ),
]

# ── 일본어 — gonta223/humanizer-ja 20 패턴 중 결정적 항목.
_JA: list[Tell] = [
    _t(
        "JA-significance-inflation",
        "content",
        "S1",
        r"(?:浮き彫りに|注目に値する|重要な示唆|計り知れない|極めて重要な役割)",
        "Inflated significance. Write what changed, with numbers.",
    ),
    _t(
        "JA-closing-formula",
        "content",
        "S1",
        r"(?:今後の展開が注目され|と言えるでしょう|ではないでしょうか|が期待されます)",
        "Machine closing formula. Commit to the claim or delete it.",
    ),
    _t(
        "JA-vague-adjective",
        "vocabulary",
        "S2",
        r"(?:多面的|包括的|画期的|革新的|さまざまな観点)",
        "Abstract adjective. Replace it with a concrete fact.",
    ),
    _t(
        "JA-verbose-verb",
        "grammar",
        "S2",
        r"(?:することができます|していきたいと思います|を行うことが可能)",
        "Verbose verb phrase. Use the short verb.",
    ),
]

# ── 중국어 — op7418/Humanizer-zh · qu-ai-wei 공통 항목.
_ZH: list[Tell] = [
    _t(
        "ZH-context-inflation",
        "content",
        "S1",
        r"(?:在[^。！？\n]{0,20}的背景下|随着[^。！？\n]{0,20}的不断发展|在当今[^。！？\n]{0,10}时代)",
        "Inflated context framing. Cut the sentence.",
    ),
    _t(
        "ZH-significance",
        "content",
        "S2",
        r"(?:至关重要|不可或缺|深远影响|重要的作用|值得注意的是|具有重要意义)",
        "Inflated significance. Replace it with a measured fact.",
    ),
    _t(
        "ZH-negative-parallelism",
        "grammar",
        "S2",
        r"不仅[^。！？\n]{0,30}(?:而且|还|也)",
        "'不仅…而且' parallelism. State the claim directly.",
    ),
    _t(
        "ZH-closing-formula",
        "content",
        "S2",
        r"(?:总而言之|综上所述|让我们一起|期待未来)",
        "Closing formula. End on the last fact.",
    ),
]

# ── 슬림 코퍼스 — 하이프·대화 잔재만. 확장은 register() 로.
_ES: list[Tell] = [
    _t(
        "ES-hype",
        "vocabulary",
        "S2",
        r"\b(?:revolucionari[oa]|innovador[a]?|vanguardia|sin precedentes|de última generación)\b",
        "Hype vocabulary. Replace it with the measured number.",
        re.I,
    ),
    _t(
        "ES-significance",
        "content",
        "S1",
        r"(?:juega un papel (?:fundamental|crucial|clave)|cabe (?:destacar|señalar) que|en el mundo actual)",
        "Inflated significance. Replace it with a confirmed fact.",
        re.I,
    ),
]
_FR: list[Tell] = [
    _t(
        "FR-hype",
        "vocabulary",
        "S2",
        r"\b(?:révolutionnaire|innovant[e]?|incontournable|sans précédent|de pointe)\b",
        "Hype vocabulary. Replace it with the measured number.",
        re.I,
    ),
    _t(
        "FR-significance",
        "content",
        "S1",
        r"(?:joue un rôle (?:essentiel|crucial|clé)|il convient de noter que|dans un monde en constante évolution)",
        "Inflated significance. Replace it with a confirmed fact.",
        re.I,
    ),
]
_RU: list[Tell] = [
    _t(
        "RU-hype",
        "vocabulary",
        "S2",
        r"\b(?:революционн\w+|инновационн\w+|беспрецедентн\w+|передов\w+)\b",
        "Hype vocabulary. Replace it with the measured number.",
        re.I,
    ),
    _t(
        "RU-significance",
        "content",
        "S1",
        r"(?:играет (?:важную|ключевую) роль|стоит отметить, что|в современном мире)",
        "Inflated significance. Replace it with a confirmed fact.",
        re.I,
    ),
]

_REGISTRY: dict[str, list[Tell]] = {
    "en": _EN,
    "ko": _KO,
    "ja": _JA,
    "zh": _ZH,
    "vi": _VI,
    "es": _ES,
    "fr": _FR,
    "ru": _RU,
    "generic": [],
}


def register(lang: str, tells_: list[Tell], *, latin: bool = False) -> None:
    """새 언어 코퍼스 등록 — 코어 수정 없이 언어를 늘리는 유일한 접점.

    같은 언어를 두 번 등록하면 뒤가 앞을 덮는다 (프로젝트 커스텀이 기본값을 이긴다)."""
    global LATIN_LANGS
    _REGISTRY[lang] = list(tells_)
    if latin:
        LATIN_LANGS = LATIN_LANGS | {lang}


def registered_langs() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


# ── 언어 판정 — 문자 체계 우선, 라틴권은 진단 글자·기능어로 가른다.
_HANGUL = re.compile(r"[가-힣]")
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_LATIN_CH = re.compile(r"[A-Za-zÀ-ɏḀ-ỿ]")
# 베트남어 진단 글자 — 다른 라틴 표기 언어에 거의 나오지 않는 조합.
_VI_CH = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯ]|[ạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]")
_ES_CH = re.compile(r"[ñ¿¡]|\b(?:que|para|con|los|las|del|una|este|más)\b", re.I)
_FR_CH = re.compile(r"[œçÇ]|\b(?:les|des|une|dans|pour|est|avec|cette|plus)\b", re.I)


def detect_lang(text: str) -> str:
    """지배 문자 체계로 언어를 고른다. 미상은 "generic" — 침묵하지 않고 무관 패턴만 돈다.

    코드·URL이 섞인 한국어 보고문처럼 라틴 문자가 함께 나오는 경우가 정상이므로,
    표의·음절 문자가 하나라도 우세하면 그쪽을 택한다 (라틴 다수결이 아니다)."""
    if not text or not text.strip():
        return "generic"
    hangul, kana, han = len(_HANGUL.findall(text)), len(_KANA.findall(text)), len(_HAN.findall(text))
    cyr, latin = len(_CYRILLIC.findall(text)), len(_LATIN_CH.findall(text))
    cjk = hangul + kana + han
    if cjk and cjk * 4 >= latin:  # 라틴이 4배를 넘게 압도할 때만 라틴으로 본다
        if hangul >= max(kana, han):
            return "ko"
        if kana:  # 가나가 하나라도 있으면 일본어 — 한자 단독이 중국어
            return "ja"
        return "zh"
    if cyr and cyr * 2 >= latin:
        return "ru"
    if not latin:
        return "generic"
    if len(_VI_CH.findall(text)) >= 2:
        return "vi"
    es, fr = len(_ES_CH.findall(text)), len(_FR_CH.findall(text))
    if max(es, fr) >= 3 and max(es, fr) > 2 * min(es, fr):
        return "es" if es > fr else "fr"
    return "en"


# ── 검사 사본 — 원문 보존 계약 대상(코드·인용·URL·경로)은 지운다. 원문은 바꾸지 않는다.
_PATH = re.compile(r"(?:[\w.-]+/){1,}[\w.-]+|\b\w+\.(?:py|js|ts|tsx|md|json|toml|yaml|yml|sh|rs|go|java)\b")
_DATA_LINE = re.compile(r"""^\s*(?:[{}\[\]]\s*,?\s*$|["'][^"']+["']\s*:|[\w.-]+\s*[:=]\s*["'{\[\d])""")


def lintable(text: str) -> str:
    """코드 블록·인용·인라인 코드·URL·링크 대상·파일 경로·구조화 데이터 행을 지운 검사 사본.

    데이터 행을 남기면 JSON 의 쉼표가 산문의 쉼표로 계산된다 (26-07-26 실측: 독스트링 안의
    예시 JSON 하나가 쉼표 밀도 자질을 통째로 오탐시켰다)."""
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or line.lstrip().startswith(">"):
            continue
        if _DATA_LINE.match(line):  # `"key": value,` · `{` · `- key: value` 같은 데이터 행
            continue
        line = re.sub(r"`[^`]*`", "", line)
        line = re.sub(r"https?://\S+", "", line)
        line = re.sub(r"\]\([^)]*\)", "]", line)
        line = _PATH.sub("", line)
        out.append(line)
    return "\n".join(out)


_SENT_SPLIT = re.compile(r"[.!?。！？\n]+")


def _sentences(body: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(body) if len(s.strip()) >= 10]


def _comma_density(body: str) -> tuple[float, int]:
    """쉼표를 포함한 문장의 비율. KatFishNet 최고 판별 자질(94.88% AUC)의 결정론 근사.

    논문 실측: LLM 한국어 61% vs 사람 26%. 임계는 0.70 — 논문의 LLM 평균보다 위다.
    논문 표본은 뉴스·에세이인데 이 게이트가 보는 글은 기술 산문이라, 쉼표로 열거하는
    사람 글이 정상적으로 더 많다 (26-07-26 실측: 이 저장소 커밋 본문 326건에서 0.55 임계는
    3.7% 를 오탐, 0.70 은 그 대부분을 걷어낸다). 분포 자질은 보수적으로 두고 군집에 맡긴다."""
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


def tells(text: str, lang: str | None = None, source: str = "") -> list[Finding]:
    """AI 작문 흔적 목록 — 심각도 순(S1→S2→S3).

    source 에 이미 나온 표현은 새 추론이 아니라 인용이므로 잡지 않는다 (lagom 과 같은 규칙).

    판정 규칙은 Wikipedia:Signs of AI writing 의 **군집 원칙**을 그대로 옮긴 것이다 —
    "엠대시 하나는 아무것도 아니지만, 엠대시 + 3박자 + vibrant tapestry 는 자백이다".

      S1  단독으로 결정적 — 즉시 보고.
      S2  ① 같은 패턴이 _S2_MIN_HITS 회 이상(밀도 신호) 또는 ② 서로 다른 흔적이 둘 이상
          함께 나타남(군집 신호)일 때 보고. 한 종류가 한 번 나온 것만으로는 보고하지 않는다.
      S3  S1·S2 가 하나라도 보고된 뒤에만 보고 — 단독 판정은 구조적으로 불가능하다.

    ②가 없으면 짧은 글은 전부 빠져나간다: 세 문장짜리 문단에서 같은 흔적이 세 번 나올 수
    없기 때문이다 (26-07-26 실측 — 상류 라벨 코퍼스 재현율 19% → 군집 규칙 도입 후 회복)."""
    body = lintable(text)
    if not body.strip():
        return []
    lang = lang or detect_lang(body)
    evidence = lintable(source)
    pool = list(_UNIVERSAL) + _REGISTRY.get(lang, [])
    if lang not in LATIN_LANGS:  # 엠대시·타이틀 케이스는 라틴 조판 전용 규칙
        pool = [t for t in pool if not t.id.startswith("EN-em-dash") and not t.id.endswith("title-case-heading")]
    matched: list[Finding] = []
    for tell in pool:
        hits = tell.rx.findall(body)
        if not hits or tell.rx.search(evidence):  # 사용자가 먼저 쓴 표현 = 인용
            continue
        m = tell.rx.search(body)
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
    """자연도 등급 A/B/C/D — 상류 korean-skills 의 경계를 그대로 계승한다.

    A = S1 0 + S2 ≤2 · B = S1 1~2 또는 S2 3~5 · C = S1 3+ 또는 S2 6+ · D = S1 5+ 이고 S2 8+.

    경계는 패턴 종류가 아니라 **출현 횟수**로 센다. S2 는 정의상 빈도 신호라, 한 패턴이
    아홉 번 나온 글과 한 번 나온 글을 같은 등급에 둘 수 없다 (종류로 세면 전자가 A 가 된다)."""
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
    """게이트가 소비하는 문자열 형태 — lagom.style_violations 와 같은 계약."""
    return [
        f"{f.severity} {f.id}: {f.hint}" + (f' (e.g. "{f.sample}")' if f.sample else "")
        for f in tells(text, lang, source)
    ]


# ── 모드 — 기본 on. lagom 과 독립: `/lagom off` 는 압축을 끄는 것이지 사람 문체를 끄는 게 아니다.
MODES = ("on", "off")
DEFAULT_MODE = "on"


def normalize(mode: object) -> str | None:
    m = str(mode or "").strip().lower()
    return m if m in MODES else None


def current_mode(root: str | None = None, flag: str | None = None) -> str:
    """플래그 > ASGARD_BRAGI env > 프로젝트 설정 > 글로벌 설정 > on."""
    m = normalize(flag) or normalize(os.environ.get("ASGARD_BRAGI"))
    if m:
        return m
    try:
        from .settings import load_global, load_project

        for cfg in (load_project(root or os.getcwd()), load_global()):
            m = normalize((cfg.get("bragi") or {}).get("mode"))
            if m:
                return m
    except Exception:
        pass  # 없거나 깨진 설정 = 이 계층 침묵 (fail-open)
    return DEFAULT_MODE


def enabled(root: str | None = None, flag: str | None = None) -> bool:
    return current_mode(root, flag) == "on"


def note(root: str | None = None, flag: str | None = None) -> str:
    """네이티브 루프 프롬프트 주입분 — off 면 빈 문자열 (토큰 회귀 없음)."""
    if not enabled(root, flag):
        return ""
    from .templates.bragi import BRAGI_CANON

    return "\n\n" + BRAGI_CANON
