"""요청 분류 + 오류·게이트 시그니처 — 순수 판정 계층 (LLM·IO 없음).

pre-LLM 휴리스틱 분류, API 오류 재시도 판정, 게이트 차단 사유 시그니처/수리 매핑.
전부 순수 함수 — 부작용 있는 텔레메트리는 journal 모듈이 진다.
"""

from __future__ import annotations

import re

# ── 게이트 차단 사유 시그니처 — 정본은 [gate:<code>] 태그 직독 (failures 카탈로그).
# 문장 니들 표는 구버전 훅 사본(태그 없는 문장)이 남긴 사유의 폴백 전용 — 신규 니들 추가 금지. ──
_GATE_SIGS = (
    ("판정(PASS/ESCALATE) 레코드가 없", "no-verdict"),
    ("stale PASS", "stale-pass"),
    ("성공 기준(criteria)", "no-criteria"),
    ("검증 명령 증거", "no-evidence"),
    ("베이스라인 체크 red", "baseline-red"),
    ("full-verify 필요", "micro-pass"),
    ("퀘스트 로그가 없", "orphan-write"),
)


def _gate_sig(reason: str) -> str:
    from ...failures import parse_gate_code

    return parse_gate_code(reason) or next((sig for needle, sig in _GATE_SIGS if needle in reason), "other")


def _gate_repair(sig: str) -> tuple[str, str]:
    """차단 사유별 수리 턴 — 코드→전이 표는 failures 카탈로그가 정본 (동일 시그니처 2회 = 수리 불가 → ESCALATE)."""
    from ...failures import repair_for

    return repair_for(sig)


# ── 결정론 pre-LLM 분류 — 명백 케이스만, 모호하면 None → LLM 폴백 ──
_DESTRUCTIVE_PAT = re.compile(
    r"rm\s+-rf|git\s+push\s+--force|git\s+reset\s+--hard|git\s+clean\s+-[a-z]*f"
    r"|drop\s+(table|database)|truncate\s+table|mkfs|dd\s+if=|전부\s*(삭제|지워)|다\s*지워|싹\s*지워",
    re.IGNORECASE,
)
# 재구성 계열 동사(정리·통합·분리·개선)는 실측으로 뒤늦게 들어왔다: "모듈 경계를 정리해서 공통
# 로직을 한 곳으로 모아줘"가 어느 항목에도 안 걸려 LLM 폴백으로 넘어갔고, 거기서 read-only로
# 오분류돼 Write 도구 없는 DIRECT 세션이 붙었다 (26-07-26 helios 실측). 오분류의 두 방향은
# 대칭이 아니다 — write를 read로 읽으면 게이트를 통째로 우회하고, 반대는 불필요한 Trinity
# 세금에 그친다. 그래서 이 표는 넓게 잡는 쪽으로 기운다.
_WRITE_VERBS = (
    "만들", "생성해", "제작해", "수정해", "고쳐", "추가해", "구현해", "작성해", "바꿔", "변경해", "리팩터", "빼줘",
    "삭제해", "지워", "적용해", "옮겨", "설치해", "완성해", "정리해", "통합해", "합쳐", "분리해", "개선해",
    "모아줘", "모아서", "없애", "교체해", "fix ", "implement", "refactor", "rename ", "install ",
    "create ", "write ", "modify ", "change ", "edit ", "add ", "update ", "delete ", "remove ", "move ", "copy ",
    "consolidate", "extract ", "deduplicate", "clean up", "rewrite", "replace ",
)  # fmt: skip
_READ_VERBS = (
    "설명해", "알려", "뭐야", "무엇", "어떻게 동작", "왜 ", "읽", "답해", "분석해줘", "보여줘", "요약해", "조회",
    "explain", "what is", "what does", "how does", "why does", "describe", "summarize", "read ", "show ", "몇 개", "몇개", "?",
)  # fmt: skip
_NEGATED_WRITE_PAT = re.compile(
    r"(?:수정|변경|편집|고치)\s*(?:하지\s*(?:마(?:라|세요)?|말|않)|금지)"
    r"|(?:do\s+not|don't|without)\s+(?:modify|modifying|change|changing|edit|editing|write|writing)\b",
    re.IGNORECASE,
)
_PARALLEL_WORK_PAT = re.compile(
    r"병렬|동시에|독립\s*(?:worker|작업|단위)|서브\s*에이전트|sub[ -]?agents?|fan[ -]?out|"
    r"todo\s*(?:list)?|작업\s*목록|티켓|task\s*graph",
    re.IGNORECASE,
)
# 인사·감사·수긍·작별 — 요청 전체가 이 토큰들로만 이루어질 때만 매치 (한 단어라도 벗어나면 불발).
# "안녕"이 LLM 분류로 넘어가면 분류기가 JSON 대신 인사로 응답 → 파싱 실패 폴백이 Trinity를
# 태우는 최악 경로가 된다 (26-07-21 실측: 인사 하나가 deep 예산 소진) — 결정론으로 선차단.
_SMALLTALK_TOKEN = (
    r"(?:안녕(?:하세요|하십니까)?|하이|헬로+|ㅎㅇ|방가|반갑(?:다|네요|습니다)|반가워요?"
    r"|고맙(?:다|네|습니다)|고마워요?|감사(?:요|해요?|합니다|드려요|드립니다)?|땡큐"
    r"|수고(?:요|해|했어요?|하세요|하셨습니다|많으셨습니다)?|잘\s*가요?|잘\s*자요?|굿모닝|굿나잇|굿밤"
    r"|응|네|넵|넹|예|옙|ㅇㅇ|좋아요?|좋네요?|굿|오케이?|오키|ㅇㅋ|ㅋ+|ㅎ+"
    r"|h(?:i|ello|ey)|yo|howdy|thanks?|thank\s+you|thx|ty|bye|goodbye|see\s+ya"
    r"|good\s+(?:morning|afternoon|evening|night)|ok(?:ay)?|cool|nice|great"
    r"|how\s+are\s+you|what'?s\s+up)"
)
_SMALLTALK_PAT = re.compile(
    rf"^{_SMALLTALK_TOKEN}(?:[\s,.!?~^…]*{_SMALLTALK_TOKEN})*[\s,.!?~^…]*$",
    re.IGNORECASE,
)
# 기억 지시 — 사용자가 명시적으로 개인 메모리 저장을 요구하는 명령형만 (질문 "기억해?"/"기억하고
# 있어?"는 회상 요청이라 제외). 26-07-21 실측: "기억해줘"가 어느 동사 표에도 없어 LLM 폴백
# trivial DIRECT로 흘렀고, 모델이 저장 없이 "기억했다" 허위 확답 — 이 의도는 결정론으로 잡아
# DIRECT의 memory_save 계약(core._direct)으로 배선한다.
_MEMORY_WRITE_PAT = re.compile(
    r"기억해\s*(?:줘|둬|두|놔|다오|주세요|주라|라)"  # 명령형 보조 어미 ("기억해두고" 포함)
    r"|기억해[\s.!~]*$"  # 문말 명령형 "…기억해" — 물음표는 불매치 (회상 질문)
    r"|기억하라|잊지\s*마|잊지\s*말"
    r"|(?:메모리|위그드라실)에\s*(?:저장|기록|넣|올려|남겨)"
    r"|(?:^|[.!?]\s|please\s)remember\s+(?:this|that|it|my)\b"  # 명령형 위치 한정 — "do you remember my…" 회상 질문 제외
    r"|don'?t\s+forget\b|\bmemorize\b",
    re.IGNORECASE,
)
# 지속형 사용자 사실 — "기억해" 라는 말 없이도 다음 세션까지 살아야 하는 선언. 26-07-26 실측:
# "이제부터 썬더오브갓이라 불러라"가 위 표 어디에도 없어 memory_save 도구가 열리지 않았고,
# 모델이 셸아웃(asgard memory ingest)으로 우회하려다 read-only 레인에 막혀 "세션에서만 기억"
# 으로 끝났다. 명시 명령만 잡는 축으로는 이 부류를 영원히 놓친다 — 축을 하나 더 세운다.
#
# 정밀도 장치 둘: ① 의문문은 전부 제외 (선언이 아니라 회상 질문이다), ② 지속 부사(이제부터·
# 항상)만으로는 안 잡고 지시·선호 표지가 같이 있어야 한다 ("이제부터 시작하자"는 사실이 아니다).
_IDENTITY_DECL_PAT = re.compile(
    r"(?:내|제|나의|저의|사용자|유저)\s*(?:의)?\s*(?:[^\s,.]{1,12}\s+)?"
    r"(?:이름|성함|닉네임|별명|호칭)(?:\s*[/·,]\s*(?:이름|성함|닉네임|별명|호칭))*\s*(?:은|는|이|가)"
    r"|(?:나|저)(?:를|는)\s+[^\s?]{1,20}\s*(?:이?라고?|이?라)\s*(?:불러|부르)"
    r"|(?:이제부터|앞으로|앞으론|지금부터)\s+[^?]{1,30}?(?:이?라고?|이?라)\s*(?:불러|부르)"
    r"|[^\s?]{1,20}\s*(?:이?라고?|이?라)\s*(?:불러|부르)(?:줘|라|주세요|세요|주라)"
    r"|\bmy\s+name\s+is\b"
    r"|\bcall\s+me\b(?!\s+(?:when|if|back|after|before|at|on|in|later|tomorrow|asap|once))",
    re.IGNORECASE,
)
_STANDING_PAT = re.compile(
    r"(?:이제부터|앞으로|앞으론|지금부터|항상|늘|언제나|매번|웬만하면|되도록)\s"
    r"[^?]{0,60}?"
    r"(?:하지\s*마|하지\s*말|쓰지\s*마|말고|금지|선호|좋아해|싫어해|불러|부르"
    r"|(?:으로|로|게|처럼)\s*(?:해|답|써|쓰|말)|해\s*줘|해라|하라|하세요|해야|써\s*줘|사용해|유지해)"
    r"|(?:^|[.!?]\s)(?:from\s+now\s+on|going\s+forward)\b"
    r"|\balways\s+(?:use|call|write|answer|respond|reply|prefer|include|avoid|keep)\b"
    r"|\bnever\s+(?:use|call|write|include|mention|do)\b"
    r"|\bi\s+(?:prefer|always\s+use)\b",
    re.IGNORECASE,
)
# 회상 질문 배제 — "내 이름이 뭐야?"는 _IDENTITY_DECL_PAT의 주어부를 그대로 만족한다.
_RECALL_QUESTION_PAT = re.compile(
    r"\?\s*$|뭐(?:야|지|니|예요|에요|였)|뭔(?:가|지|데)|무엇|어떻게\s*(?:되|돼)|맞(?:아|나|지)|인가요|일까",
)


def memory_write_intent(request: str) -> bool:
    """저장해야 할 사용자 사실 여부 — 분류 소스(휴리스틱/LLM/폴백)와 무관한 결정론 판정.

    두 축의 합집합이다. ① 명시적 기억 명령("기억해줘"), ② 명령 없이도 지속되는 사용자 사실
    선언(호칭·정체성·지속 지시). ②가 없으면 사용자는 매번 "기억해"를 붙여야 하고, 붙이지
    않은 지시는 조용히 세션과 함께 사라진다 (26-07-26 실측).

    이 판정이 곧 저장 동의다: ingest의 ask-before-save 게이트는 모델 자의 저장을 막는 장치이고,
    사용자가 발화로 직접 지시한 저장은 그 발화가 승인이다 (core의 memory_save 계약이 소비)."""
    scan = " ".join(request.split())
    if _MEMORY_WRITE_PAT.search(scan):
        return True
    if _RECALL_QUESTION_PAT.search(scan):
        return False
    return bool(_IDENTITY_DECL_PAT.search(scan) or _STANDING_PAT.search(scan))


# 봉인(커밋) 의도 — 워킹트리를 git 이력으로 옮기는 것만 하는 요청. 소스 파일은 한 줄도 안 바뀌므로
# Trinity 가 검증할 대상 자체가 없다: 계획할 변경도, 돌릴 베이스라인도, 대조할 diff-hash 도 없다.
# 그런데 라우터는 "커밋해줘"를 write 로 읽고 퀘스트를 열었고, 단순 커밋 한 번이 thinker 계획 →
# worker 웨이브 → 테스트 스위트 → verifier 판정까지 갔다 (실측 5분 이상). 이 축이 그 경로를 끊는다.
_COMMIT_INTENT_PAT = re.compile(
    r"커밋|봉인(?:해|하)|\bcommit\b|\bseal\b|\bstage\s+(?:and|the)\b",
    re.IGNORECASE,
)
# 판정을 좁히는 세 조건: ① 파일을 만지는 write 동사가 같이 있으면 아니다 ("커밋 규칙 문서 작성해줘"),
# ② 묻는 문장은 아니다 ("commit 규칙이 뭐야?"는 답을 원하는 것이지 봉인 지시가 아니다),
# ③ 길이 상한 — 긴 명세문이 본문 어딘가에서 커밋을 언급하는 것은 봉인 요청이 아니다.
_VCS_ONLY_CAP = 200


def vcs_only_intent(request: str) -> bool:
    """git 이력만 건드리는 요청 여부 — 소스 write 가 없는 봉인·커밋 전용 턴."""
    scan = " ".join(request.split())
    if len(scan) > _VCS_ONLY_CAP or not _COMMIT_INTENT_PAT.search(scan):
        return False
    if any(v in scan.lower() for v in _READ_VERBS):
        return False
    return not has_write_verbs(scan)


def has_write_verbs(request: str) -> bool:
    """부정구("수정하지 마") 제거 후 write 동사 존재 — LLM 분류 실패 시 폴백 라우팅의 결정론 축."""
    scan = _NEGATED_WRITE_PAT.sub("", " ".join(request.split()).lower())
    return any(v in scan for v in _WRITE_VERBS)


def classify_heuristic(request: str) -> dict | None:
    """순수 함수 1차 분류 — LLM 토큰 0. 확실할 때만 판정하고 나머지는 None (안전 우선).

    read-only 판정은 write 동사가 전혀 없을 때만 — 오판 시 write가 게이트를 우회하므로
    (DIRECT), write 쪽 오판(불필요한 trinity 세금)보다 훨씬 보수적으로 잡는다."""
    low = " ".join(request.split()).lower()
    base = {
        "write_expected": False,
        "ambiguous": False,
        "destructive": False,
        "external_research": False,
        "shared": False,
        "parallel_requested": False,
        "criteria": [],
        "task_class": "standard",
    }
    if _DESTRUCTIVE_PAT.search(low):
        return {**base, "write_expected": True, "destructive": True, "task_class": "deep"}
    if _SMALLTALK_PAT.match(low):
        return base  # 인사·잡담 전체 매치 — DIRECT 무세금 (단순한 것은 단순하게)
    # 봉인 전용 턴 — write 이긴 하지만 git 이력만 쓴다. task_class 로 갈라 두면 라우터가
    # Trinity 대신 seal 레인을 고른다 (write_expected 를 내리면 read-only DIRECT 로 가서
    # 격리 워크스페이스에 커밋하게 되므로, 그쪽이 아니라 이쪽이다).
    if vcs_only_intent(request):
        return {**base, "write_expected": True, "task_class": "vcs"}
    # 순수 기억 지시(repo write 동사 없음)는 결정론 DIRECT — LLM 폴백이 trivial로 뭉개는 것을
    # 차단한다. 저장 자체는 라우팅이 아니라 core._direct의 memory_save 계약이 집행한다.
    # 혼합 요청("기억해두고 파일 수정해줘")은 write 분기로 계속 흘러 Trinity를 탄다.
    if memory_write_intent(request) and not has_write_verbs(request):
        return base
    # "파일을 수정하지 마"의 부정된 동사를 write 의도로 세면 read-only 질의가 Trinity로
    # 오분류된다. 부정구만 제거한 사본에서 write 동사를 찾되, 같은 문장에 실제 write 동사가
    # 따로 있으면 그대로 잡는다 (예: "기존 파일은 수정하지 말고 새 파일 만들어").
    write_scan = _NEGATED_WRITE_PAT.sub("", low)
    has_w = any(v in write_scan for v in _WRITE_VERBS)
    has_r = any(v in low for v in _READ_VERBS)
    if has_w and _PARALLEL_WORK_PAT.search(low):
        # 명시적 분해·병렬 요청은 Thinker가 dependency/file-overlap을 구조화해야 한다.
        # LLM 분류가 standard를 반환해도 명시적 fan-out은 Thinker의 access graph를 거쳐야 한다.
        return {**base, "write_expected": True, "parallel_requested": True, "task_class": "deep"}
    if has_r and not has_w:
        return base  # 명백 read-only — DIRECT 무세금
    if has_w and not has_r:
        # 명백 write — criteria는 못 뽑는다 (기본 criterion 사용). task_class는 LLM 없이 보수적 standard.
        return {**base, "write_expected": True}
    return None  # 모호 — LLM 폴백


def _pred_fields(d: dict) -> dict:
    return {k: d.get(k) for k in ("write_expected", "ambiguous", "destructive", "task_class")}


# ── API 오류 회복 (recovery-hint 최소판) ──
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
_FATAL_STATUS = {400, 401, 403, 404, 422}


def classify_api_error(e: Exception) -> str:
    """ "retryable" | "fatal" — 분류는 1회, 재시도 루프는 멍청하게."""
    if getattr(e, "_asgard_retries_exhausted", False):
        return "fatal"
    status = getattr(e, "status_code", None)
    if status in _RETRY_STATUS:
        return "retryable"
    if status in _FATAL_STATUS:
        return "fatal"
    name = e.__class__.__name__.lower()
    if "usagecap" in name:  # 구독 한도 도달 (claude_cli) — 재시도로 뚫지 않는다
        return "fatal"
    if any(k in name for k in ("timeout", "connection", "overloaded", "ratelimit", "internalserver")):
        return "retryable"
    return "retryable" if status is None else "fatal"  # 미상 = 일시 오류로 간주 (1회 재시도 가치)
