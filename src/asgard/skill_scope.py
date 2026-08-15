"""작업 범위(work shape) 결정론 판정 — 지시 텍스트 → 형상·규율 렌즈·결속 스킬.

트리니티는 `task_class`(trivial/standard/deep)로 **턴 예산과 게이트 레벨**만 정한다. 그 축은
"얼마나 오래 도느냐"를 답하지 "어떤 규율로 접근하느냐"는 답하지 않는다. 이 모듈이 후자를 진다:
같은 write 요청이라도 한 조각짜리 수직 슬라이스인지, 스펙 표면을 먼저 고정해야 하는 기능인지,
결정이 아직 스펙을 막고 있는 원정인지에 따라 계획 규율이 달라야 한다.

왜 결정론인가 — 스킬 카탈로그는 이미 설명만 노출하고 모델이 `load_skill`로 고르는 구조인데,
파일 플러그인의 트리거 매칭이 `trigger in task` 부분 문자열이라 한국어 지시에는 사실상 불발한다
("소셜 로그인 버튼 추가해줘"는 어느 영어 트리거에도 안 걸린다). 범위를 코드가 먼저 재고 결속
스킬을 **이름으로** 지목해 주면, 모델의 자율 선택은 그대로 두면서 발견 실패만 제거한다.

`work_shape`는 순수 함수 (LLM·IO 없음). `scope_note`만 레지스트리를 조회해 실제로 그 역할에
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
# 기능 표식 — 슬라이스 하나로 안 끝나는 신설 표면. cls 축(deep/parallel)이 이미 잡으면 불필요.
#
# 영어 갈래가 둘인 이유 (26-08-13 실측). `new` 바로 뒤에 표면 명사가 붙은 형태는 그대로 잡는다
# ("we need a new page", "spin up a new service"). 그 사이에 수식어가 끼면 `new` 는 "새로 만든다"가
# 아니라 명사에 붙은 형용사로 읽히는 쪽이 훨씬 흔해서("fix the new login page bug", "the new
# payment service is down"), 그 자리에서만 **생성 동사**를 추가로 요구한다. 수식어 허용만 하고
# 동사를 안 물었을 때는 슬라이스 요청이, 동사만 물고 인접 형태를 버렸을 때는 신설 요청이 각각
# 반대로 틀렸다 — 두 갈래를 함께 둬야 양쪽이 맞는다. 문장은 benchmarks/skill-uptake 에 있다.
_SURFACE_KO = r"(?:기능|화면|페이지|엔드포인트|모듈|서비스|api)"
# 단수만 — 복수형까지 받으면 "the new pages are slow", "document the new modules" 처럼 이미 있는
# 여러 표면을 가리키는 문장이 신설 요청으로 읽힌다. 신설을 부탁하는 말은 거의 언제나 한 개를
# 가리킨다.
_SURFACE_EN = r"(?:feature|page|screen|endpoint|module|service|flow)"
_MAKE_EN = r"(?:build|create|add|make|ship|scaffold|introduce|stand\s+up|spin\s+up|set\s+up|write|need|want)"
# 관사는 부정관사만 — `a new page` 는 신설이지만 `the new page` 는 그것이 이미 있다는 뜻이라,
# need·want·make 처럼 뜻이 넓은 동사와 붙으면 유지보수 요청이 신설로 읽힌다
# ("I want the new export page fixed", "make the new login page load faster").
_ARTICLE_EN = r"(?:a|an)?"
# 한국어에 `{표면}을 새로 {만들|추가|…}` 갈래는 두지 않는다. 26-08-13 에 넣었다가 판정 셋이
# 연속으로 같은 결함을 잡아 지웠다: 신설을 **거절하는** 문장이 어간까지 글자가 같아서 신설
# 요청으로 읽힌다 ("페이지를 새로 만들지 말고 기존 걸 고쳐줘", "만들라고 한 적 없어",
# "만들자는 게 아니라 고치자는 거야"). 거절 어형을 열거해도, 뒤집어서 요청 어미를 요구해도
# 샜다 — `자`·`야`·`라` 가 요청 전용이 아니라 내포절의 첫 글자이기도 해서다. 요청인지 거절인지는
# 어간 뒤 두세 어절에서 갈리는데 이 층은 한 글자를 본다.
#
# 종결 위치까지 보는 규칙도 돌려 봤다. 비요청문은 다 떨어지지만 뒤에 절이 붙는 진짜 요청
# ("페이지를 새로 만들자 그리고 배포도 해줘")이 함께 떨어져, 이번엔 미탐 쪽으로 같은 일이 난다.
# 그래서 이 축은 이 층이 지지 않는다 — `task_class=deep`·`parallel_requested` 가 문구와 무관하게
# 승격하고, 트리거 낱말이 없는 요청은 모델이 카탈로그 설명을 읽고 고른다. 남은 구멍은
# benchmarks/skill-uptake 의 `shape_gap` 축이 매 실행 찍는다.
_FEATURE_PAT = re.compile(
    rf"신규\s*{_SURFACE_KO}|기능\s*(?:추가|개발|구현|신설)"
    r"|화면\s*(?:추가|신설)|페이지\s*(?:추가|신설)|엔드포인트\s*(?:추가|신설)"
    rf"|\bnew\s+{_SURFACE_EN}\b"
    rf"|\b{_MAKE_EN}\s+{_ARTICLE_EN}\s*new\s+(?:\w+\s+){{1,2}}{_SURFACE_EN}\b"
    r"|\bfeature\s+(?:request|work)\b",
    re.IGNORECASE,
)

# ── 규율 렌즈 — 형상과 독립. 여러 개가 동시에 참일 수 있다 (회귀 버그 + 회귀 테스트) ──
_LENS_PAT: dict[str, re.Pattern[str]] = {
    # 버그는 대개 어휘가 아니라 **증상**으로 신고된다 ("다크 모드가 깨졌다", "목록이 안 나온다",
    # "dark mode is broken"). 어휘만 잡으면 가장 흔한 신고 형태를 통째로 놓친다 — 26-07-26 실측:
    # 증상 문장 15개 배터리에서 5/15만 걸렸다. 증상 표현을 1급 신호로 편입한다.
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

# 렌즈 → 결속 스킬. 존재 여부는 scope_note가 레지스트리로 확인한다 (없는 이름은 지목하지 않음).
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
# 자율 턴이 docs/specs·docs/quests를 임의로 낳으면 범위 밖 산출물이다 (Canon 7).
#
# `/council` 도 사용자 호출이지만 이유가 다르다 — 산출물이 아니라 **오딘의 답**을 기다리며 멈춘다.
# 자율 턴에는 그 답이 도착할 수 없으므로(Canon 8) 부르지 않고 이름만 댄다. 이름을 여기서 대야
# 하는 것은 사용자 호출 스킬이 `available_skills` 에 안 들어가 `bound_skills` 가 원리상 못 집기
# 때문이다. 이 줄이 없으면 **턴에 주입되는 표면** 중 council 을 대 주는 것이 0개다. README 와
# `asgard start` 의 `/skills` 목록에는 전부터 있지만, 둘 다 오딘이 찾아가야 보이는 자리다.
#
# `--ambiguous` 축에는 걸지 않는다: 실제 호출 265건 중 그 플래그를 선언한 것이 1건이라
# (26-08-14 세션 기록 실측) 거기 걸면 부르는 손이 없는 관문이 하나 더 생긴다. 형상 축은 같은
# 배터리에서 100% 라 이쪽에 건다.
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
        " `/blueprint` writes that spec surface and `/quests` cuts the slices; both are Odin's to"
        " invoke, so name them as the offer and keep working — producing those artifacts unasked is"
        " out of scope (Canon 7). When the spec cannot be pinned because the decisions behind it are"
        " still open, `/council` settles them one answerable round at a time and comes before"
        " `/blueprint`; offer it the same way."
    ),
    "expedition": (
        "This exceeds one quest: decisions still block a durable spec. Name the destination — the"
        " concrete state that ends this effort — and plan the **decision frontier only**. Resolve just"
        " the decisions precise enough to answer now, each with the cheapest sufficient instrument"
        " (repository facts, one focused observation, a throwaway prototype); leave the rest as fog"
        " instead of guessing. The decisions only Odin can settle go to `/council`, which puts one"
        " answerable round in front of them at a time — name it rather than guessing the answers."
        " Do not convert unresolved decisions into implementation units, and"
        " report to Odin that `/expedition` will hold the shared map across sessions."
    ),
}


def work_shape(request: str, cls: dict | None = None, facts: dict | None = None) -> dict:
    """지시 + 분류 (+ 변경 사실) → {shape, lenses, why}. 순수 함수 — LLM·IO 없음.

    cls가 없으면 텍스트만으로 판정한다 (외부 호스트 어댑터 경로). write 의도가 없으면 direct —
    범위 규율을 붙일 대상 자체가 없다.

    `facts`는 `change_facts()` 산출물이다. 구조 형상이 관측되면 요청 문구와 무관하게
    architecture 렌즈를 켠다 — 침식은 아키텍처를 입에 담지 않는 변경에서 일어나므로."""
    text = " ".join((request or "").split())
    cls = cls or {}
    lenses = tuple(name for name, pattern in _LENS_PAT.items() if pattern.search(text))
    if (facts or {}).get("structural") and "architecture" not in lenses:
        lenses = (*lenses, "architecture")
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


# ── 변경 형상 사실 — 지시 텍스트가 아니라 **손댄 것**에서 구조 규율을 켠다 ──
# 왜: architecture 렌즈가 요청 문구에만 걸려 있으면 "엔드포인트 하나 추가해줘"는 영원히 안
# 걸린다. 그런데 침식은 정확히 그런 요청에서 일어난다 — 아키텍처를 말하지 않는 변경이
# 경계를 넘고, 이미 큰 파일을 더 키운다. 그래서 관측된 변경 집합에서 사실을 뽑아 켠다.
_STRUCTURAL_DIRS = 3  # 서로 다른 디렉터리 이상을 건드리면 산탄 수정 형태
_STRUCTURAL_FILES = 5  # 한 슬라이스로 보기 어려운 파일 수


def change_facts(root: str, changed: object) -> dict:
    """관측된 변경 파일 집합 → 구조 규율 판정 사실. IO는 크기 확인뿐 (지목 파일만 읽는다).

    반환은 사실만 — 판정(렌즈 결속)은 `work_shape` 몫이다. 빈 입력은 빈 사실이고, 사실이
    없으면 렌즈를 켜지 않는다 (fail-open: 모르는 것으로 규율을 강요하지 않는다).
    """
    paths = [str(p).strip().replace("\\", "/") for p in changed] if isinstance(changed, (list, tuple, set)) else []
    paths = [p for p in paths if p]
    if not paths:
        return {"files": 0, "dirs": 0, "oversized": (), "structural": False, "why": ""}
    dirs = {p.rsplit("/", 1)[0] if "/" in p else "." for p in paths}
    try:
        from .health import oversized as _oversized

        big = _oversized(root, paths)
    except Exception:  # 크기 확인 실패는 신호 부재로 취급 — 판정을 막지 않는다
        big = ()
    reasons = []
    if len(dirs) >= _STRUCTURAL_DIRS:
        reasons.append(f"{len(dirs)} directories touched")
    if len(paths) >= _STRUCTURAL_FILES:
        reasons.append(f"{len(paths)} files changed")
    if big:
        reasons.append(f"already-large file touched ({big[0]})")
    return {
        "files": len(paths),
        "dirs": len(dirs),
        "oversized": big,
        "structural": bool(reasons),
        "why": "; ".join(reasons),
    }


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
    changed: object = None,
) -> str:
    """역할 프롬프트에 붙일 범위 블록. 매칭이 없으면 빈 문자열 (토큰 회귀 없음).

    결속 스킬은 레지스트리에서 그 역할에 실제로 열린 이름만 남긴다 — 비활성·미배정 스킬을
    지목하면 모델이 존재하지 않는 것을 로드하려다 턴을 태운다 (fail-open: 조회 실패 = 무필터).

    `changed`가 오면 그 변경 집합의 형상까지 판정에 넣는다 (관측된 구조 변경 → 구조 규율)."""
    facts = change_facts(root, changed) if changed else None
    result = work_shape(request, cls, facts)
    shape = result["shape"]
    if shape == "direct":
        return ""  # read-only 턴에는 붙일 계획 규율이 없다 (형상 사실이 있어도 마찬가지)
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
    if facts and facts.get("structural"):
        # 근거를 함께 넣는다 — "구조 규율을 켰다"만 있으면 모델이 왜인지 되짚느라 턴을 쓴다
        lines.append(
            f"Observed change shape is structural ({facts['why']}), so the architecture discipline is in scope"
            " regardless of how the request was worded. This is an observation about the change, not a"
            " licence to widen scope (Canon 7): keep the change minimal and report structural findings"
            " outside scope instead of fixing them."
        )
        if "asgard-hlidskjalf" not in skills:
            # 판정자는 스킬 배정 대상이 아니다 (검증 독립성 — skill_registry._ASSIGNABLE_AGENTS).
            # 그래서 결속 목록으로는 못 주고, 역할 md가 이미 쓰는 CLI 읽기 경로로 지목한다.
            lines.append(
                "This assigns the system-level architecture axis for this diff: load the canonical procedure"
                " with `asgard skills show asgard-hlidskjalf` and judge layering/dependency direction,"
                " coupling, and module boundaries with file:line evidence."
            )
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
    if agent == "worker" and (specialists := _matching_specialists(root, request)):
        lines.append(
            "This request also matches a delivery specialist's canon: "
            + ", ".join(f"{role} ({', '.join(names)})" for role, names in specialists)
            + ". The Worker does not read a specialist's canon — it dispatches, and the specialist loads its"
            " own. Hand the matching surface over rather than working it here."
        )
    lines.append(
        "The shape sets the planning discipline, not the turn budget. Do not inflate a slice into a"
        " feature to look thorough, and do not compress a feature into one unit to look fast."
    )
    return "\n".join(lines)


# Worker 가 넘길 수 있는 배달 전문가 — AGENTS.md 의 위임 그래프와 같은 집합이다.
_DISPATCHABLE = ("freyja", "thor", "eitri", "mimir")


def _matching_specialists(root: str, request: str) -> list[tuple[str, list[str]]]:
    """이 요청이 어느 전문가의 정본에 걸리는가.

    워커로 물으면 전문가 스킬은 하나도 안 나온다 — 배정 대상이 그 전문가라서고, 그건 설계대로다
    (워커는 디스패치하고 전문가가 자기 정본을 읽는다). 다만 그 결과가 **"아무것도 안 걸렸다"와
    화면에서 구분되지 않아**, 계획하는 손이 넘길 자리를 못 보고 직접 손대는 쪽으로 기운다.
    이름만 돌려준다 — 본문은 넘겨받은 쪽이 읽는다 (26-08-05).

    조회가 실패하면 빈 목록이다: 이 줄이 없다고 잘못되는 것은 없고, 틀린 지목은 턴을 태운다."""
    out: list[tuple[str, list[str]]] = []
    try:
        from .skill_registry import resolve_skills
    except Exception:
        return out
    for role in _DISPATCHABLE:
        try:
            names = [name for name, _ in resolve_skills(root, request, role, include_learned=False)]
        except Exception:
            continue
        if names:
            out.append((role, names[:3]))
    return out
