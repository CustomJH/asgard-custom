"""영어 코퍼스 — Kobak et al. 초과 어휘 + Juzek & Ward 초점어 + Wikipedia:Signs of AI writing."""

from __future__ import annotations

import re

from .tell import Tell, _t

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
        # blader §14는 하드 금지지만, 이 저장소의 사람 글이 엠대시를 상시 쓴다 (26-07-26 실측
        # held-out 코퍼스). 상류 자신의 오탐 지침도 "엠대시 단독은 증거가 아니다"라고 못박는다
        # → S3로 둔다: 다른 흔적과 함께일 때만 보고되고, 혼자서는 절대 게이트를 울리지 않는다.
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
