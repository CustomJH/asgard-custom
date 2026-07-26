"""작업 범위(work shape) 결정론 판정 — 지시 텍스트 → 형상·규율 렌즈·결속 스킬.

트리니티는 `task_class`(trivial/standard/deep)로 **턴 예산과 게이트 레벨**만 정한다. 그 축은
"얼마나 오래 도느냐"를 답하지 "어떤 규율로 접근하느냐"는 답하지 않는다. 이 모듈이 후자를 진다:
같은 write 요청이라도 한 조각짜리 수직 슬라이스인지, 스펙 표면을 먼저 고정해야 하는 기능인지,
결정이 아직 스펙을 막고 있는 원정인지에 따라 계획 규율이 달라야 한다.

왜 결정론인가 — 스킬 카탈로그는 이미 설명만 노출하고 모델이 `load_skill` 로 고르는 구조인데,
파일 플러그인의 트리거 매칭이 `trigger in task` 부분 문자열이라 한국어 지시에는 사실상 불발한다
("소셜 로그인 버튼 추가해줘" 는 어느 영어 트리거에도 안 걸린다). 범위를 코드가 먼저 재고 결속
스킬을 **이름으로** 지목해 주면, 모델의 자율 선택은 그대로 두면서 발견 실패만 걷어낸다.

`work_shape` 는 순수 함수 (LLM·IO 없음). `scope_note` 만 레지스트리를 조회해 실제로 그 역할에
열려 있는 스킬로 이름을 걸러 낸다 — 없는 스킬을 지목하는 노트는 거짓말이므로.
"""

from __future__ import annotations

import re

# ── 형상 — 규율의 축. 예산 축(task_class)과 직교한다 ──
SHAPES = ("direct", "slice", "feature", "expedition")

# 원정 표식 — 한 퀘스트에 담기지 않는 규모/결정 밀도. 명시 표현만 잡는다 (승격 전용).
_EXPEDITION_PAT = re.compile(
    r"전면\s*(?:재설계|개편|교체|이관)|아키텍처\s*(?:재설계|개편)|대규모\s*(?:개편|이관|마이그레이션)"
    r"|마이그레이션|이관\s*작업|로드맵|원정|여러\s*세션|처음부터\s*다시|밑바닥부터"
    r"|\bmigrat(?:e|ion|ing)\b|\brewrite\b|\boverhaul\b|\bre-?architect|\bepic\b|\broadmap\b"
    r"|multi-?session|\bgreenfield\b|from\s+scratch|ground\s+up",
    re.IGNORECASE,
)
# 기능 표식 — 슬라이스 하나로 안 끝나는 신설 표면. cls 축(deep/parallel)이 이미 잡으면 불요.
_FEATURE_PAT = re.compile(
    r"신규\s*(?:기능|화면|페이지|엔드포인트|모듈|서비스|api)|기능\s*(?:추가|개발|구현|신설)"
    r"|화면\s*(?:추가|신설)|페이지\s*(?:추가|신설)|엔드포인트\s*(?:추가|신설)"
    r"|\bnew\s+(?:feature|page|screen|endpoint|module|service|flow)\b|\bfeature\s+(?:request|work)\b",
    re.IGNORECASE,
)

# ── 규율 렌즈 — 형상과 독립. 여러 개가 동시에 참일 수 있다 (회귀 버그 + 회귀 테스트) ──
_LENS_PAT: dict[str, re.Pattern[str]] = {
    # 버그는 대개 어휘가 아니라 **증상**으로 신고된다 ("다크 모드가 깨졌다", "목록이 안 나온다",
    # "dark mode is broken"). 어휘만 잡으면 가장 흔한 신고 형태를 통째로 놓친다 — 26-07-26 실측:
    # 증상 문장 15개 배터리에서 5/15 만 걸렸다. 증상 표현을 1급 신호로 편입한다.
    "bug": re.compile(
        r"버그|디버깅|디버그|크래시|스택\s*트레이스|재현|원인\s*(?:규명|분석|찾|파악)|회귀|오류\s*(?:수정|해결)"
        r"|안\s*(?:되|돼)|깨졌|깨져|깨진|망가|먹통|안\s*(?:나오|나온|나와|보이|보인|먹)|나오지\s*않|보이지\s*않"
        r"|반응이\s*없|이상하게|잘못\s*(?:나오|표시|계산|동작)|틀리게|틀린\s*값|갱신되지\s*않|반영되지\s*않"
        r"|작동(?:하지|되지)\s*않|동작(?:하지|되지)\s*않|실패(?:한다|해|합니다|하는)|누락되(?:고|는|어)"
        r"|\bbugs?\b|\bdebug|\bcrash|traceback|stack\s*trace|reproduc|root[\s-]*cause|\bregress"
        r"|\bbroken\b|\bbreaks?\b|(?:doesn't|does\s+not|isn't|is\s+not|no\s+longer)\s+"
        r"(?:work|working|render|load|update|show|appear|fire|run)"
        r"|not\s+working|fails?\s+(?:to|silently|with)|\bfailing\b|find\s+the\s+cause"
        r"|wrong\s+(?:value|result|total|number|order|state)|\bincorrect\b|misbehav",
        re.IGNORECASE,
    ),
    "test": re.compile(
        r"테스트|커버리지|픽스처|단언|모킹|스냅샷\s*테스트"
        r"|\btests?\b|\btesting\b|\btdd\b|coverage|fixture|\bmock|flaky|assertion",
        re.IGNORECASE,
    ),
    "architecture": re.compile(
        r"아키텍처|계층|레이어|결합도|응집도|의존성\s*(?:방향|역전)|모듈\s*경계|순환\s*(?:참조|의존)"
        r"|구조\s*(?:개선|정리|재편)|리팩터"
        r"|architect|layering|\blayers?\b|coupling|cohesion|module\s+boundar|circular\s+dependenc"
        r"|\brefactor",
        re.IGNORECASE,
    ),
    "design-question": re.compile(
        r"프로토타입|시안|스파이크|어느\s*(?:쪽|것)이\s*(?:나은|좋은)|비교\s*해\s*보|느낌\s*을\s*보"
        r"|\bprototyp|\bspike\b|throwaway|which\s+(?:one|approach)\s+(?:is\s+)?better|mock\s*-?up",
        re.IGNORECASE,
    ),
    "domain": re.compile(
        r"도메인\s*(?:모델|용어)|용어\s*(?:정리|통일|정의)|네이밍\s*(?:규칙|정리)|개념\s*정리|용어집"
        r"|결정\s*기록|의사\s*결정\s*기록"
        r"|domain\s+model|ubiquitous\s+language|glossary|\badrs?\b|naming\s+convention",
        re.IGNORECASE,
    ),
    "merge": re.compile(
        r"머지\s*충돌|병합\s*충돌|리베이스\s*충돌|충돌\s*(?:해결|해소)"
        r"|merge\s+conflict|rebase\s+conflict|conflict\s+marker|<{7}\s|\bgit\s+(?:merge|rebase)\b",
        re.IGNORECASE,
    ),
}

# 렌즈 → 결속 스킬. 존재 여부는 scope_note 가 레지스트리로 확인한다 (없는 이름은 지목하지 않음).
_LENS_SKILLS: dict[str, tuple[str, ...]] = {
    "bug": ("asgard-worker-debugging",),
    "test": ("asgard-worker-testing",),
    "architecture": ("codebase-design", "asgard-hlidskjalf"),
    "design-question": ("prototype",),
    "domain": ("domain-modeling",),
    "merge": ("merge-resolution",),
}

# 형상별 계획 규율 — 상류 공개 스킬군(정렬→스펙→슬라이스→구현→리뷰)의 우리 말 재서술.
# 산출물을 만드는 오케스트레이터(`/blueprint`·`/quests`·`/expedition`)는 사용자 호출로 남긴다:
# 자율 턴이 docs/specs·docs/quests 를 임의로 낳으면 범위 밖 산출물이다 (Canon 7).
_SHAPE_CONTRACT: dict[str, str] = {
    "direct": ("Read-only turn — answer from what you observe. No plan artifacts, no files."),
    "slice": (
        "One tracer-bullet vertical slice: it cuts only the layers it needs, is independently"
        " verifiable, and finishes in one fresh context. Confirm one public seam's failure, make the"
        " minimal change that passes it, then stop — do not widen into neighbouring surfaces."
    ),
    "feature": (
        "More than one slice. Pin the spec surface **before** cutting: the problem, the user-visible"
        " behaviour, acceptance criteria, and what is explicitly out of scope. Then cut tracer-bullet"
        " slices with their blocking edges declared, and prefer an unblocked frontier over a"
        " layer-by-layer split — a horizontal unit that bundles a whole layer is not independently"
        " verifiable. Reuse the vocabulary already fixed in the repository instead of coining new terms."
    ),
    "expedition": (
        "This exceeds one quest: decisions still block a durable spec. Name the destination — the"
        " concrete state that ends this effort — and plan the **decision frontier only**. Resolve just"
        " the decisions precise enough to answer now, each with the cheapest sufficient instrument"
        " (repository facts, one focused observation, a throwaway prototype); leave the rest as fog"
        " instead of guessing. Do not convert unresolved decisions into implementation units, and"
        " report to Odin that `/expedition` will hold the shared map across sessions."
    ),
}


def work_shape(request: str, cls: dict | None = None) -> dict:
    """지시 + 분류 → {shape, lenses, why}. 순수 함수 — LLM·IO 없음.

    cls 가 없으면 텍스트만으로 판정한다 (외부 호스트 어댑터 경로). write 의도가 없으면 direct —
    범위 규율을 붙일 대상 자체가 없다."""
    text = " ".join((request or "").split())
    cls = cls or {}
    lenses = tuple(name for name, pattern in _LENS_PAT.items() if pattern.search(text))
    if cls and not cls.get("write_expected"):
        return {"shape": "direct", "lenses": lenses, "why": "read-only request"}
    if _EXPEDITION_PAT.search(text):
        return {"shape": "expedition", "lenses": lenses, "why": "explicit multi-session / re-architecture marker"}
    if cls.get("task_class") == "deep" or cls.get("parallel_requested"):
        why = "explicit fan-out" if cls.get("parallel_requested") else "deep task class (multi-file / risky)"
        return {"shape": "feature", "lenses": lenses, "why": why}
    if _FEATURE_PAT.search(text):
        return {"shape": "feature", "lenses": lenses, "why": "new surface marker (feature/page/endpoint)"}
    return {"shape": "slice", "lenses": lenses, "why": "single verifiable slice"}


def bound_skills(shape_result: dict, available: set[str] | None = None) -> tuple[str, ...]:
    """감지된 렌즈가 요구하는 스킬 중 실제로 열려 있는 것만. available=None 이면 필터 없음."""
    names: list[str] = []
    for lens in shape_result.get("lenses") or ():
        for name in _LENS_SKILLS.get(lens, ()):
            if name not in names and (available is None or name in available):
                names.append(name)
    return tuple(names)


def scope_note(
    root: str,
    request: str,
    cls: dict | None = None,
    *,
    agent: str = "worker",
    loader: str = "load_skill",
) -> str:
    """역할 프롬프트에 붙일 범위 블록. 매칭이 없으면 빈 문자열 (토큰 회귀 없음).

    결속 스킬은 레지스트리에서 그 역할에 실제로 열린 이름만 남긴다 — 비활성·미배정 스킬을
    지목하면 모델이 존재하지 않는 것을 로드하려다 턴을 태운다 (fail-open: 조회 실패 = 무필터)."""
    result = work_shape(request, cls)
    shape = result["shape"]
    if shape == "direct":
        return ""
    available: set[str] | None = None
    try:
        from .skill_registry import available_skills

        available = {row["name"] for row in available_skills(root, agent)}
    except Exception:
        available = None
    skills = bound_skills(result, available)
    lines = [
        "\n\n## Work shape (harness-sized, deterministic)",
        f"shape: **{shape}** — {result['why']}",
        _SHAPE_CONTRACT[shape],
    ]
    if skills:
        verbs = {
            "load_skill": "Load each with the `load_skill` tool before deciding",
            "cli": "Load each with `asgard skills show <name>` before deciding",
            "none": "Name each one in the assignment unit that needs it, so its executor loads it",
        }
        lines.append(
            f"Disciplines this request matched: {', '.join(skills)}."
            f" {verbs.get(loader, verbs['load_skill'])} — the match is deterministic, so these are not"
            " suggestions to re-evaluate."
        )
    lines.append(
        "The shape sets the planning discipline, not the turn budget. Do not inflate a slice into a"
        " feature to look thorough, and do not compress a feature into one unit to look fast."
    )
    return "\n".join(lines)
