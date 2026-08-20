"""asgard-tutor 스킬 — 오딘과의 1:1 왕복을 에이전트가 지는 계약.

이 스킬을 낸 이유는 층이 없어서가 아니라 **왕복이 끊겨서**다. `.asgard/tutor/growth.json` 실측:
물음 36건, 답 0건, 그중 9건은 코드가 먼저 움직여 만료(`gone`)됐다. 페이딩도, 1·3·7·21일 재방문
사다리도, 각도 회전도 전부 지어 놓고 한 번도 실입력 위에서 안 돌았다. 물음이 나빠서가 아니다 —
답을 적는 일이 `asgard tutor --answer <표식> --note "…"` 라는 **따로 치는 명령**이고, 작업 도중에
그것을 치는 사람은 없었다. 그리고 방 안에서 오딘과 같이 있는 유일한 쪽인 에이전트에게는 그 왕복을
지라는 말이 어디에도 안 적혀 있었다 (정찰 실측: `.claude/skills/`·`.agents/skills/`·레지스트리
어디에도 튜터 스킬 0건).

그래서 본문 전체를 한 줄이 조직한다 — **에이전트는 학생이 아니라 서기다**. 물음을 오딘에게 옮기고,
오딘의 문장을 기록으로 옮긴다. 양쪽 끝을 자기가 채우지 않는다. 자기가 답해서 닫은 물음은 기록에
없는 이해도를 적고, 재방문 사다리가 그것을 영영 안 되돌린다.

요약 금지를 본문이 굵게 지는 이유는 판정 방식이다. `tutor_growth._depth`(`tutor_growth.py:333`)는
길이(`THIN_CHARS = 12`)와 상투구만 본다 — 내용은 안 본다. 그래서 오딘의 한 마디를 에이전트가
매끄럽게 다듬어 넣으면 그 문장은 `full` 로 세어지고, 남의 글이 오딘의 깊은 답이 된다.

리졸버가 라틴 `tutor` 를 낱말 경계로 잡는 것이 핵심이다. 부분 일치로 두면 `tutorial` 이 걸려
README 작업이 전부 이 본문을 끌어온다. 반대로 한국어 쪽은 넓게 잡는다 — 이 층에서 실측된 실패는
과선택이 아니라 **한 번도 안 닿은 것**이고(36문 0답), 이 저장소는 카드 설명이 좁아 배차가 0으로
떨어지는 사고를 두 번 겪었다. 그래도 조사 없이 흔한 낱말은 안 넣는다: `짚어`("이 버그 짚어줘"),
`1:1`("criteria 를 1:1로 매핑"), `질문`("질문 목록 테이블") 셋은 전부 평범한 코드 작업 문장이라
빠져 있고, 그 세 문장이 시험의 부정 사례로 박혀 있다."""

import re

TUTOR_SKILL_MD = """\
---
name: asgard-tutor
description: Conduct Odin's one-on-one tutor session and write his own sentence back into the record — one question per turn, no lecture, and never his answer supplied by you. Load when he asks to be tutored, quizzed, or walked through what just changed (튜터, 나한테 물어봐 줘, 시험해줘, 가르쳐줘, tutor me, quiz me), and when `asgard tutor` leaves an open question after a change.
allowed-tools: Bash(asgard tutor *)
---

# asgard-tutor — the one-on-one session, and who writes it down

`asgard tutor` opens a question about the change that just landed and waits for Odin's own
sentence. On this repository it asked 36 times and was answered 0 times, and nine of those
questions expired because the code moved on first. Nothing was wrong with the questions. The round
trip was never made: recording an answer is a separate command, and the only party in the room with
Odin — you — was never told to make it.

**에이전트는 학생이 아니라 서기다** — you are the scribe, not the student. You carry one question to
Odin and his sentence back to the record. You fill neither end yourself.

## The turn order

1. **Read the open questions; do not compose one.** `asgard tutor --quiz` prints them with their
   marks, and `asgard tutor --track --json` gives the same record as data. Put **exactly one** back
   in the wording the record holds, then end the turn. Two questions in one turn returns zero
   answers — Odin answers the last one, or neither.
2. **When he answers in prose, write it down word for word.**

       asgard tutor --answer <mark> --note "<Odin's sentence, unchanged>"

   The mark is the eight-character tag printed beside the question (`[7c968810]`); its first few
   characters are enough to find it. Do not summarise, tidy, translate, or complete his sentence.
   Depth here is graded by length and stock phrases alone, so a tidied sentence is *your* writing
   counted as *his* answer, and the record then says he owns a surface he never explained.
3. **When the reply is a new instruction instead of an answer, write nothing and work.** Do not
   re-ask in the same turn. The revisit ladder brings the question back on its own at one, three,
   seven, and twenty-one days.
4. **When he says he does not know, change the angle.** Ask the same gap from a different side —
   what breaks without it, what he would check first, who else reads this value. After two misses
   hand him the coordinates (`file:line`) and let him read. That is the last help before the answer
   itself, and the answer itself is never yours to give.
5. **When the question was wrong, close it as wrong.**

       asgard tutor --dismiss <mark> --note "<why it was a false alarm>"

   A false alarm left open decays into a skip, and four skips quieten the probe for a kind of
   question that was never actually wrong. `--dismiss` also takes a file path, or `all`, when one
   place has collected a pile.

## You never answer the tutor's question

Not to be helpful, not to save Odin a turn, not to clear a stale mark. The question exists to find
where his understanding stops; an answer you supply measures nothing, and the record then reports a
level he does not hold. The mid-session channel hands you the **mark only, never the question
text**, for exactly this reason — a model that reads a question answers it.

## When to conduct at all

This is a tutor, not a quiz-master. Silence is the ordinary outcome: a rename, a typo, a
mechanical sweep leaves nothing worth asking, and asking anyway is what teaches Odin to skip.

- One question per turn, and never a list.
- On a track already at rung 3 or above, ask less. Re-asking a surface he owns is nagging.
- "가르쳐줘" is a request to be shown, not a question to put back — `asgard tutor --explain`.
  "시험해줘" is `asgard tutor --quiz`. Both lanes already exist; do not invent a parallel verb.
- Say nothing about the tutor layer itself while conducting. The session is about his code.

## Why one question, and why no lecture

A teacher explains the material; a tutor diagnoses *this* person's confusion. Bloom measured the
average one-on-one tutored student ahead of 98% of a conventional classroom, and the part that
works is the diagnosis rather than the extra hours. Diagnosis needs one precisely aimed question
with no lecture attached, and it has to be hard to fake — a list of five questions is the easiest
thing in the world to answer around.

## The advisor branch — five decisions, one at a time

A track starts with `destination`, `cut`, and `milestones` empty on purpose. Those are Odin's
decisions, and a generated answer there is worse than a blank because it reads as his. When he
opens one, interview it the same way — one question per turn, in this order:

1. **Destination** — what he will be able to do once this is done.
2. **Baseline** — what he can already do today.
3. **Sequencing** — what comes first, and what it unlocks.
4. **Cut list** — what he is deliberately not learning yet.
5. **Milestones** — what output proves he can move on.

Record his words, leave the rest blank, and stop asking the moment he stops answering.
"""

TUTOR_SKILLS: list[tuple[str, str]] = [("asgard-tutor", TUTOR_SKILL_MD)]

# 1:1 세션을 부르는 말. 한국어 쪽을 넓게 잡는 이유는 이 층의 실측 실패가 과선택이 아니라 미선택
# 이어서다(36문 0답). 다만 조사 없이 흔한 낱말은 안 넣는다 — `짚어`·`질문`·`1:1` 은 평범한 코드
# 작업 문장이고, 그 셋은 시험의 부정 사례로 박혀 있다.
#
# `물어봐 줘` 를 맨 꼴로 안 잡는 것이 그 부류다: "확인 대화상자로 물어봐 줘" 는 화면 기능 요청이고
# 튜터와 아무 관계가 없다. 물음의 **대상이 오딘 자신**이라고 적힌 꼴만 남긴다.
# `시험해줘` 는 반대로 알면서 남긴다 — 이 저장소에서 `시험` 은 테스트를 뜻하기도 해서 "이 함수
# 시험해줘" 가 함께 걸리지만, 오딘이 실제로 쓰는 튜터 호출이 그 말이고 본문이 그 갈래를
# `--quiz` 로 보내 준다. 미탐 쪽 손해가 이 층에서 실측된 손해다.
_SUBSTR: tuple[str, ...] = (
    "튜터",
    # `줘` 는 `주`+`어` 가 아니라 한 음절이라 축약형과 존대형이 부분 문자열로 안 겹친다.
    "나한테 물어",
    "저한테 물어",
    "내게 물어",
    "되물어",
    "되짚어",
    "시험해 줘",
    "시험해줘",
    "퀴즈",
    "가르쳐",
    "이해했는지",
    "이해하고 있는지",
    "알고 있는지",
    "일대일로",
    "asgard tutor",
    "tutor me",
    "quiz me",
    "one question at a time",
)
# 라틴 트리거는 낱말 경계 필수 — `tutor` 를 부분 일치로 잡으면 `tutorial` 이 걸려 README 작업이
# 전부 이 본문을 끌어온다. `\btutors?\b` 는 tutorial 을 안 잡는다.
_WORD_RE: tuple[str, ...] = (
    r"\btutors?\b",
    r"\btutoring\b",
    r"\bsocratic\b",
)


def resolve_tutor_skills(task: str) -> list[tuple[str, str]]:
    """1:1 어휘가 있는 과업 → 지휘 계약 (이름, frontmatter 제거 본문) — 0-LLM 휴리스틱.

    일치가 없으면 빈 목록이다 (fail-open). 튜터를 안 부르는 작업에 이 본문이 붙으면 값 없이
    컨텍스트만 먹는다."""
    text = task.lower()
    if any(key in text for key in _SUBSTR) or any(re.search(pattern, text) for pattern in _WORD_RE):
        return [(name, body.split("---", 2)[2].lstrip()) for name, body in TUTOR_SKILLS]
    return []
