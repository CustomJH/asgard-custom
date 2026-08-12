"""한국어 코퍼스 — KatFishNet 3대 자질 + 번역투·결말 코퍼스 + 비유 사전.

`KO_METAPHOR` 는 이 모듈 밖에서도 읽힌다 (`craft_note` 가 같은 사전으로 주석을 판정한다).
"""

from __future__ import annotations

from .tell import Tell, _t

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
        # 이 문장에서 의는 조사로 쓰인 것이 아니라 언급된 것이다 — 영어 문장의 목적어 자리에
        # 선 인용 토큰이라 앞말에 붙이면 오히려 안 읽힌다. 규칙이 자기 힌트를 지우지 않게 둔다.
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
    _t(
        # 한글 맞춤법 제41항 — 조사는 앞말에 붙여 쓴다. 앞말이 라틴 낱말·숫자·코드 조각이어도
        # 앞말은 앞말이다. 앞말을 라틴·숫자·닫는 기호로 한정해 (마침표는 뺀다 — "1. 이 값은"
        # 같은 번호 목록이 걸린다) 한국어 낱말 뒤 띄어쓰기가 정상인 의존명사와 갈라 둔다.
        "KO-josa-spacing",
        "grammar",
        "S1",
        # 앞머리 [^\s]{0,20}은 판정이 아니라 표본용이다 — 보고에 조사 한 글자만 들어가는 대신
        # 앞말째로 실려 고칠 자리가 보인다. 앞말의 마지막 글자에서 마침표를 빼는 조건은 그대로다.
        # 사이 공백은 줄바꿈을 뺀 [ \t]다 — 줄이 바뀐 뒤의 "이"는 조사가 아니라 관형사인 쪽이
        # 흔하고("...lru_cache\n이 값은"), S1을 그런 자리에 물리면 게이트가 사람 글을 막는다.
        r"[^\s]{0,20}[0-9A-Za-z_`\)\]\*\"'][ \t]"
        r"(?:은|는|이|가|을|를|의|에서|에게|에|으로|로|와|과|도|만|부터|까지|보다|처럼"
        r"|밖에|조차|마저|이나|이라고|라고|이라|라)"
        r"(?![0-9A-Za-z가-힣])",
        "Detached Korean particle. Attach it to the word before it, even when that word is Latin, "
        "a number, or a code span (`config.py를`, not `config.py 를`).",
    ),
    _t(
        # 긴 낱말에서 음절을 잘라 만든 조어 — 한 글자를 아끼고 사전에 없는 낱말을 남긴다.
        # 표준 파생어는 넣지 않는다: 무관·불변·미지정·비활성은 사전에 있고, 무응답·무결성처럼
        # 무(無)+한자어 합성도 정상 조어다. 여기 남긴 것은 표준어를 밀어내고 들어선 자리다 —
        # `불요`는 한국어로 `불필요`고, 나머지는 라틴 낱말에 무/비를 붙여 만든 임시어다.
        "KO-coined-clipping",
        "vocabulary",
        "S2",
        r"(?:불요(?!불급)|무임포트|무매칭|비의존|무보정|무검증)",
        "Clipped coinage. Write the standard word (불필요, 일치 없음, 의존하지 않는다).",
    ),
]


# 코드를 사람이나 사물에 빗댄 서술어 → 표준 서술. 두 번째 칸은 그대로 치환할 말이 아니라
# "이 뜻으로 다시 쓰라"는 안내다. 여기 오른 것은 전부 이 저장소에서 실제로 걸린 표현이고,
# 짐작으로 넣은 항목은 없다.
#
# 사전이 문체 모듈에 사는 이유는 이것이 어느 판정기의 소유물이 아니라 한국어 문체 사실이어서다.
# 같은 규칙이 주석과 보고문에 함께 걸린다 — 읽는 사람이 비유부터 풀어야 한다는 문제는 `#` 뒤에
# 있든 보고서에 있든 같다. `craft_note` 가 여기서 읽어 주석을 판정하고, 아래 `KO-metaphor` 가
# 같은 사전으로 산문을 판정한다. 사본을 두면 한쪽만 자라고 그 어긋남은 판정이 갈릴 때까지
# 안 보인다 (26-08-06 실측: 공유되던 정의 49개 중 9개가 이미 뜻이 갈려 있었다).
KO_METAPHOR: tuple[tuple[str, str, str], ...] = (
    # `진`·`지는` 앞의 `(?<![가-힣])`는 조사와 어미를 가른다. 이것이 없으면 `깨진 파일`이나
    # `사라지는 쪽`의 어미가 승부의 은유로 걸린다.
    ("이김", r"이긴다|이긴 (쪽|것|편)|(?<![가-힣])(지는 쪽|진 (쪽|파일|것))", "우선한다 · 우선순위가 높다"),
    ("섬", r"[가이] 선다|서는 것으로|선다는 것", "준비된다 · 동작한다 · 뜬다"),
    ("실림", r"싣는다|실린다|싣지|실으면|실어 |안 실(린|는)", "넣는다 · 포함한다 · 들어간다"),
    ("듦", r"[을를] 든다|드는 것과|드는 것이|들고 있는 것", "쓴다 · 가진다"),
    ("먹힘", r"먹힌다|먹은 줄|잡아먹", "가려진다 · 묻힌다"),
    ("삶", r"[에가] 산다|살지 않는다|사는 자리", "있다 · 저장된다"),
    ("나름", r"나른다|실어 나", "전달한다 · 옮긴다"),
    ("문지기", r"문지기|파수", "접근 제어 · 검사"),
    ("사슬", r"사슬", "연결 · 체인"),
    ("못박음", r"못 박", "명시한다 · 고정한다"),
    ("값치름", r"치른다|값을 치", "부담한다 · 비용을 낸다"),
    ("걷어냄", r"걷어낸|걷어내|걷힌|걷어 ", "제거한다 · 지운다"),
    ("앉힘", r"앉힌다|앉는다|앉혀", "저장한다 · 배치한다"),
    ("자", r"같은 자[로 ]|한 자로|자를 (들이|세우|세워)|다른 자로", "같은 기준 · 척도"),
    ("한벌", r"한 벌", "한 곳 · 한 묶음 · 공용"),
)

# 산문 쪽 판정. 지금까지는 `asgard craft` 가 주석만 봐서 보고문의 비유는 아무도 안 잡았다.
#
# lagom: 사전이 해라체로 적혀 있어(`산다`·`선다`) 해요체·합쇼체 보고문(`삽니다`·`서요`)은
# 안 걸리고, 해라체 안에서도 조사에 따라 새는 자리가 있다 (11개 표본에서 9개 검출). 주석이
# 해라체라서 그렇게 적힌 것이고, 어미를 손으로 하나씩 넓히면 오탐과 구멍이 번갈아 난다
# (26-08-05 실측: 가드 정규식이 같은 방식으로 세 턴 연속 실패했다). 넓히려면 어미마다 대안을
# 더하는 대신 어간과 어미 목록을 나눠 사전을 다시 세워야 한다. 그때까지 나머지는 계약
# (`Explain, do not liken`)이 맡는다.
_KO.append(
    _t(
        "KO-metaphor",
        "vocabulary",
        "S2",
        "|".join(f"(?:{pattern})" for _, pattern, _ in KO_METAPHOR),
        "Metaphor for what the code does. Write the mechanism (준비된다 · 저장된다 · 전달한다).",
    )
)
