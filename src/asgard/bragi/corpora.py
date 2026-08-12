"""나머지 언어 코퍼스 — 베트남어·일본어·중국어와 슬림 3종(es·fr·ru).

영어와 한국어는 항목이 많아 자기 모듈로 나가 있다 (`english`·`korean`).
"""

from __future__ import annotations

import re

from .tell import Tell, _t

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

# ── 슬림 코퍼스 — 하이프·대화 잔재만. 확장은 register()로.
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
