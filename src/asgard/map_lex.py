"""질의 어휘 다리 — 한국어 질문과 라틴 식별자 사이.

지도의 노드 id·명령 이름·경로는 전부 라틴 식별자인데 이 프로젝트의 질문은 한국어로 온다.
"커밋 게이트"와 `command:seal`은 한 글자도 겹치지 않아, 부분문자열 매칭 하나로는 도움이 필요할
때 도움이 안 나온다 — 실측으로 질의 12개 중 5개만 시드가 떴고, 그 5개는 전부 질문에 이미 명령
이름이 들어 있던 경우였다 (26-08-01).

**닫힌 사전만 쓴다.** 어간 추출·조사 분리 같은 형태 규칙은 여기서 안 쓴다: 한국어 어미는 낱말과
글자가 겹쳐(`깨진 파일`의 `진 파일`) 규칙이 조용한 오탐을 낳는다 — craft 판정기에서 형태 규칙이
306건을 잘못 잡은 것과 같은 병이다. 대신 도메인 명사만 손으로 골라 적고, 조사가 붙어도 걸리도록
질의 문자열 **안에서** 찾는다(`티켓을`·`티켓의`가 모두 `티켓`에 걸린다).

여기 없는 낱말은 확장되지 않을 뿐 검색을 막지 않는다 — 확장은 질의 어휘를 늘리기만 한다.
"""

from __future__ import annotations

import math
import re

_TOKEN = re.compile(r"[\w./-]{2,}", re.UNICODE)
Groups = tuple[tuple[str, ...], ...]
# 이름에 걸린 개념의 배수. 2.6인 이유는 경로 히트 8 대 역할 히트 3이라는 옛 고정 가중의 비율을
# 그대로 옮겼기 때문이다 — 그 비율은 쓸 만했고, 바뀐 것은 가중치가 고정이 아니게 된 쪽이다.
_FOCUS_BOOST = 2.6

# 한국어 도메인 명사 → 이 코드베이스가 쓰는 라틴 토큰.
# 넣는 기준: (1) 지도 표면(명령 이름·경로·역할)에 실제로 있는 토큰일 것, (2) 일상어와 겹쳐
# 아무 데나 걸리지 않을 것. `것`·`곳`·`부분` 같은 낱말은 그래서 없다.
_KO: dict[str, tuple[str, ...]] = {
    "건강": ("health", "doctor"),
    "검사": ("check", "verify", "doctor"),
    "검색": ("search", "query", "recall"),
    "게이트": ("gate", "guard", "verifier"),
    "계획": ("plan",),
    "관문": ("gate", "guard"),
    "관계": ("relation",),
    "권한": ("permission", "auth"),
    "그래프": ("graph",),
    "기억": ("memory", "recall"),
    "기획": ("plan",),
    "동기화": ("sync",),
    "라우트": ("route", "router"),
    "래칫": ("ratchet",),
    "로그": ("log",),
    "로그인": ("login", "auth"),
    "메모리": ("memory", "recall"),
    "모델": ("model", "provider"),
    "목록": ("list",),
    "문서": ("doc", "document", "docs"),
    "벤치": ("bench", "benchmark"),
    "보드": ("board",),
    "봉인": ("seal", "commit"),
    "부하": ("load",),
    "비용": ("cost", "budget", "spend"),
    "사이클": ("cycle",),
    "삭제": ("delete", "remove", "uninstall"),
    "상태": ("status", "state"),
    "생성": ("create", "generate", "new"),
    "설정": ("config", "settings", "setup"),
    "설치": ("install", "setup"),
    "세션": ("session",),
    "소비": ("spend", "cost", "usage"),
    "시험": ("test", "bench"),
    "스캔": ("scan",),
    "스킬": ("skill",),
    "스튜디오": ("studio",),
    "승인": ("approve",),
    "시작": ("start",),
    "실행": ("run", "start"),
    "업데이트": ("update", "upgrade"),
    "에이전트": ("agent", "einherjar"),
    "역할": ("role",),
    "영향": ("impact",),
    "예산": ("budget", "cost"),
    "워크스페이스": ("workspace",),
    "인증": ("auth", "login"),
    "제공자": ("provider",),
    "점검": ("check", "doctor", "health"),
    "주입": ("context", "inject", "activate"),
    "지도": ("map",),
    "진화": ("evolve", "evolution"),
    "질의": ("query", "search"),
    "채널": ("channel",),
    "초기화": ("init", "reset"),
    "추적": ("trace",),
    "커밋": ("commit", "seal"),
    "타임라인": ("timeline",),
    "테스트": ("test", "pytest"),
    "팀": ("team",),
    "티켓": ("ticket", "issue"),
    "표면": ("surface",),
    "프로바이더": ("provider",),
    "프로젝트": ("project",),
    "회수": ("recall", "retrieve"),
    "훅": ("hook", "hooks"),
    # 한 음절인 유일한 표제어. `훑`으로 시작하는 낱말은 훑다·훑어보다뿐이고 뜻이 모두 같아서,
    # 여기서는 짧게 적는 편이 훑기·훑어·훑는을 한 번에 잡는다. 어간을 규칙으로 떼는 것과는
    # 다르다 — 손으로 고른 표제어 하나고, 나머지 표제어와 같은 방식으로 질의 안에서 찾는다.
    "훑": ("scan",),
}

# 이 세계관의 고유명사 — 표면에서는 라틴 식별자고 대화에서는 한글로 부른다. 위 표와 같은 닫힌
# 사전이되 성격이 달라 나눠 둔다: 여기 있는 이름은 전부 이 저장소에 실재하는 명령·모듈·역할이다.
_NAMES: dict[str, tuple[str, ...]] = {
    "노른": ("norn",),
    "로키": ("loki",),
    "무닌": ("muninn",),
    "미미르": ("mimir",),
    "브라기": ("bragi",),
    "사가": ("saga", "office"),
    "에인헤랴르": ("einherjar", "agent"),
    "울르": ("ullr",),
    "위그드라실": ("yggdrasil", "memory"),
    "이트리": ("eitri",),
    "토르": ("thor",),
    "프레이야": ("freyja",),
    "하임달": ("heimdall",),
    "후긴": ("huginn",),
}


def query_groups(query: str) -> tuple[tuple[str, ...], ...]:
    """질의를 **개념** 단위로 쪼갠다 — 한 개념은 표기가 여럿이어도 한 번만 센다.

    토큰 단위로 세면 표기가 많은 개념이 높은 점수를 받는다: `상태`가 (status, state) 둘로 퍼지고 `티켓`이
    (ticket, issue) 둘로 퍼지면 셈은 사전이 몇 글자를 적어 뒀는지를 재게 된다. 개념 하나가 한 표다.

    한국어 명사는 라틴 확장과 **함께 자기 자신도** 표기로 남긴다 — 이 저장소의 help 문자열은
    절반이 한국어라(`asgard ticket board` — "상태 칸으로 접은 지금의 보드") 라틴으로만 펴면
    바로 그 한국어 근거를 못 읽는다. 조사는 떼지 않고 질의 안에서 찾으므로 `티켓을`도 걸린다.
    """
    lowered = query.casefold()
    groups: list[tuple[str, ...]] = []
    covered: set[str] = set()
    headwords: list[str] = []
    for noun, latin in (*_KO.items(), *_NAMES.items()):
        if noun in lowered:
            groups.append((noun, *latin))
            covered.update(latin)
            covered.add(noun)
            headwords.append(noun)
    for token in _TOKEN.findall(lowered):
        # 사전이 이미 낸 표기는 다시 개념으로 세지 않는다 — 같은 근거의 이중 계상이다.
        if token in covered:
            continue
        # 조사가 붙은 꼴도 같은 개념이다. `지도`와 `지도를`을 둘로 세면 그 개념이 두 표를 갖고,
        # 실제로 `지도를`을 품은 후보가 `git`+`지도`를 품은 후보를 이겼다 (26-08-01 실측).
        # 조사는 뒤에만 붙으므로 표제어로 **시작하는** 한국어 토큰만 접는다 — 라틴 토큰은
        # `map_context.py`처럼 더 좁은 뜻을 담고 있어 접으면 변별력을 잃는다.
        if any(token.startswith(head) and token != head for head in headwords):
            continue
        covered.add(token)
        groups.append((token,))
    return tuple(groups)


def group_terms(groups: Groups) -> set[str]:
    """개념 묶음을 평평한 표기 집합으로 — 개념 구분이 필요 없는 소비자(시드 매칭)용."""
    return {term for group in groups for term in group}


def idf(haystacks: list[str], groups: Groups) -> dict[str, float]:
    """역문서빈도 — 어느 행에나 있는 낱말은 방향을 못 가리킨다.

    `src`·`test`·`status` 처럼 후보 절반에 박힌 토큰이 희귀 토큰과 같은 값을 받으면, 질의의 실제
    변별력은 흔한 낱말에 묻힌다. 한 번만 세고 딕셔너리로 넘긴다 — 정렬 키 안에서 다시 세면
    후보 수의 제곱이 된다.
    """
    total = len(haystacks)
    # +1 평활 — 아무 데도 없는 표기(0)와 모든 곳에 있는 표기(total)가 모두 유한하게 끝난다.
    return {
        term: math.log((total + 1) / (sum(1 for h in haystacks if term in h) + 1)) + 1.0
        for group in groups
        for term in group
    }


def hits(haystack: str, focus: str, groups: Groups, weights: dict[str, float]) -> tuple[int, float]:
    """(맞은 개념 수, 가중 점수) — 한 개념은 표기가 몇이든 한 번만, 가장 변별력 있는 표기로 센다.

    `focus`(경로·명령 이름처럼 그 후보의 정체를 담은 짧은 쪽)에 걸린 개념은 더 세게 본다. 긴
    문장에 스친 낱말보다 이름에 박힌 낱말이 그 후보가 무엇인지에 가깝다.
    """
    covered = 0
    score = 0.0
    for group in groups:
        matched = [term for term in group if term in haystack]
        if not matched:
            continue
        covered += 1
        score += max(weights.get(term, 1.0) for term in matched) * (
            _FOCUS_BOOST if any(term in focus for term in matched) else 1.0
        )
    return covered, score
