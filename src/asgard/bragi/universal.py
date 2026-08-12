"""언어 무관 패턴 — 등록되지 않은 언어에서도 이것만은 돈다."""

from __future__ import annotations

import re

from .tell import Tell, _t

# ── 언어 무관 패턴 — 문자 체계와 무관하게 성립하는 서식·대화 잔재 흔적.
_UNIVERSAL: list[Tell] = [
    _t(
        # blader §16은 이걸 강한 신호로 보지만, 명세·체크리스트에서는 정당한 서식이다
        # (26-07-26 실측: 저장소 자체 .md에서 최다 오탐 원인). S3 = 군집일 때만 보고.
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
