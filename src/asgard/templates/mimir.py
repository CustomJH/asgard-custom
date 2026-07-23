"""미미르 전용 스킬 2종 — 코드 설명·워크스루·온보딩 심화 지식.

프로그램 이해·학습과학 문헌의 검증된 결론을 우리 용어로 재서술한 자체 캐논이다 — 외부 텍스트
재배포 없음. 근거 축: 실행 흐름 읽기(Busjahn 2015)·단계적 정제(Wirth 1971)·작업기억 청크 상한
(Cowan 2001)·인출 연습(Adesope 2017)·자기설명(Bisra 2018)·Brain-first 순서(Kosmyna 2025,
Anthropic RCT 2026)·안내 줄이기(인지적 도제, Collins 1989).

CC(.claude/skills/)와 Cursor·Codex 공용(.agents/skills/) 양 스코프에 스캐폴드되어 모드
A/B/네이티브 전부에서 로드 가능하다. 코어 계약 스킬은 mimir_core_skill (role 파일 단일 소스)
— 이 모듈은 심화 층만 담당한다. 네이티브 DIRECT 턴(설명 과업의 실제 경로)은 dispatch 툴이
없는 read-only 단일 세션이므로 mimir_note 가 모드 A 처럼 계약을 인라인 주입한다."""

import re

_BRUNNR = """\
---
name: asgard-mimir-brunnr
description: Mimir's well Mimisbrunnr — deep knowledge of walkthrough design. Load before code tours, flow explanations, or architecture guidance work.
---

# asgard-mimir-brunnr — 🕳️ Walkthrough Design

The well is deep, but the water comes one sip at a time — hold the whole, yet draw up only one layer per pull.

## Reconnaissance (observe before explaining)

- Pin down the entry point first: CLI entry, route, handler, event subscription — where execution begins. If you cannot find one, tests are the second entry point.
- Fix the path you will walk before starting: build the call-chain list via definition → usage tracing (Grep), then begin — never improvise route changes on mid-walk discoveries. Side paths go to the omissions list.
- Skip re-exploring areas already covered by `.asgard/map/`; propose structures missing from the map as `Map candidate:`.
- Dead code and unused branches are findings to report, not material to explain — only living paths enter the narrative.

## Narrative structure (the shape of one case)

- Layer 1 = one-sentence overview + a map of the participating files (`` `path` — one-line role ``, 3–7 entries) — the reader always knows where they are walking.
- From layer 2, work section by section: [prediction question] → flow explanation (`file:line` evidence) → [retrieval question]. 3–7 sections — overflow means there is more than one case, so propose a split.
- Follow one value's journey to the end: pick one representative input and show how it changes in each section — one concrete value anchors an abstract explanation.
- Fork discipline: for a branch, say only "why it forks" and walk one side. Announce the unwalked side in the omissions list.

## Depth control (fit the reader)

- New to the codebase: start with the execution model (what runs, when, in what order) — the model comes before the code.
- New to this area: start from the boundaries and contracts with adjacent areas the reader already knows — attach to the known.
- Familiar reader: only where things differ from expectation — re-explaining the known wastes trust, not just time.
- No line-by-line recitation: skip what the code says for itself (syntax, self-evident assignments) — explanation's share is what the code cannot say (why, boundaries, invariants).

## Measurement (verifying the narrative)

- If the explained flow is executable, measure once: run one test or observe logs to confirm the narrative matches reality (Canon 8) — read-only execution only.
- If the environment cannot execute, state that limitation in the deliverable — an unmeasured narrative must declare itself "based on the code."

## Tour deliverable (reusable format)

- A walkthrough is a reusable document, not a one-off conversation: step = `file:line` anchor + 1–3 sentence narrative + question. Storage location and registration are the dispatcher's share.
- Where frequent change would break line anchors, anchor by symbol name (function, class) instead of line.
"""

_HOFUD = """\
---
name: asgard-mimir-hofud
description: Mimir's head Mimishofud — deep knowledge of question design. Load before onboarding, handover, or comprehension-check work.
---

# asgard-mimir-hofud — 🗣️ Question Design

The severed head cannot walk on its own — the one who walks is always the one who asks.

## Order is the switch

- Prediction before the explanation, retrieval after — this one ordering decides whether knowledge sticks. An explanation started without a prediction is a failure of this skill.
- In conversational form, actually wait for the prediction answer. In document form, preserve the order structurally as question → collapsed answer.

## Four question types

- Prediction (before a section): "From the name and signature alone — what do you expect it to do?"
- Retrieval (after a section): "Without looking — the flow you just saw, in one sentence."
- Connection (between sections): "Why does X from section 1 reappear here?"
- Transfer (closing): "If you added Y, where would you make the change?" — the walkthrough succeeds only if the transfer question can be answered.
- Low-stakes discipline: one question per section — it is a handrail, not an exam. A wrong answer is not a deduction but a signal that sets the angle of the next explanation.

## Eliciting self-explanation

- "If you had to explain this to the colleague beside you in one sentence?" — a self-generated explanation lasts longer than a provided one.
- Even when the reader's explanation is wrong, do not correct everything — point out the one broken link and let them regenerate it.

## Fading guidance (across continuing sessions)

- First flow: I walk and demonstrate. Second flow: the reader walks, I only confirm. From the third on: I answer questions only.
- If the amount I say does not shrink each round, the design has failed — the goal of guidance is to make guidance unnecessary.
- Beginner-level guidance for a familiar reader is not redundancy but obstruction — depth control is shared with the brunnr canon.

## Comprehension dashboard (no gut feel)

- "I understood" as a feeling is not a metric — reading fluently and being able to reconstruct are different things.
- The only progress metrics are retrieval successes: summarizing the flow without looking, pinpointing the change site, answering connection questions correctly.
- Where retrieval fails, never repeat the same explanation — change the angle (control flow ↔ data flow ↔ concrete value journey).
"""

MIMIR_SKILLS: list[tuple[str, str]] = [
    ("asgard-mimir-brunnr", _BRUNNR),
    ("asgard-mimir-hofud", _HOFUD),
]

# 네이티브 디스패치 task → 전용 스킬 매칭 (파일 스킬 로더가 없는 asgard start 세션용 통로 —
# 모드 A/B 는 파일 스킬이 담당). 단순 사실 질의("반환 타입이 뭔가")는 무매칭 fail-open —
# role 본문만으로 충분하다. "학습"·"안내" 단독은 오발원(학습률·안내 문구)이라 트리거에 넣지 않는다.
_SUBSTR: dict[str, tuple[str, ...]] = {
    "asgard-mimir-brunnr": (
        "워크스루",
        "walkthrough",
        "walk through",
        "코드 투어",
        "code tour",
        "흐름 설명",
        "실행 흐름",
        "동작 원리",
        "어떻게 동작",
        "어떻게 돌아가",
        "how does",
        "how it works",
        "구조 설명",
        "아키텍처 설명",
        "설명해",
        "따라가",
        "코드 리딩",
        "전체 그림",
    ),
    "asgard-mimir-hofud": (
        "온보딩",
        "onboarding",
        "신규 입사",
        "새 팀원",
        "주니어",
        "인수인계",
        "handover",
        "가르쳐",
        "이해도",
        "퀴즈",
        "문답",
        "멘토링",
        "인지부채",
        "cognitive debt",
    ),
}
# 짧은 ASCII 용어는 단어 경계 필수 — 부분 일치면 detour→tour, quizzical→quiz 류 통제 불가.
_WORD_RE: dict[str, tuple[str, ...]] = {
    "asgard-mimir-brunnr": (r"\btour\b", r"\bexplain\b"),
    "asgard-mimir-hofud": (r"\bteach\b", r"\bquiz\b", r"\bmentor\b"),
}


def resolve_mimir_skills(task: str) -> list[tuple[str, str]]:
    """디스패치 task → 매칭된 전용 스킬 (이름, frontmatter 제거 본문) — 0-LLM 휴리스틱.

    네이티브 미미르 자식 세션·DIRECT 턴의 system 에 직접 주입할 본문을 고른다.
    무매칭 = 빈 리스트 (fail-open — role 본문 기준으로 진행, role 이 이미 그 폴백을 선언한다).
    복수 매칭은 전부 주입 — 온보딩용 아키텍처 워크스루처럼 두 표면이 겹치는 과업이 실재한다."""
    t = task.lower()

    def hit(name: str) -> bool:
        return any(k in t for k in _SUBSTR.get(name, ())) or any(re.search(p, t) for p in _WORD_RE.get(name, ()))

    return [(name, body.split("---", 2)[2].lstrip()) for name, body in MIMIR_SKILLS if hit(name)]


def mimir_note(task: str) -> str:
    """네이티브 DIRECT 턴용 미미르 코어 계약 — 설명 요청 매칭 시에만.

    DIRECT 는 dispatch 툴이 없는 read-only 단일 세션이라(write 에이전트 혼입 금지) 미미르를
    부를 수 없다 — 코어 역할만 활성화하고 전용 스킬 본문은 load_skill 로 지연 로드한다.
    무매칭 = 빈 문자열 — 일반 DIRECT 문답은 그대로 둔다."""
    hits = resolve_mimir_skills(task)
    if not hits:
        return ""
    from .roles import ROLE_AGENTS

    core = dict(ROLE_AGENTS)["asgard-mimir.md"].split("---", 2)[2].lstrip()
    return "\n\n# Mimir — Code Guide Contract\n\n" + core


def mimir_core_skill() -> str:
    """모드 A용 미미르 코어 계약 스킬 — role 파일 단일 소스 (roles.role_core_skill 파생)."""
    from .roles import role_core_skill

    return role_core_skill(
        "asgard-mimir.md",
        "Mimir core contract — the inline execution baseline for code explanation, walkthroughs, and onboarding "
        "(execution-flow narrative + cognitive-debt defense). Load for code-comprehension quests in tools without subagents.",
    )
