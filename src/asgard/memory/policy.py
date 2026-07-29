"""설정·게이트 계층 — 메모리 위치·주입/provider 게이트·인젝션/credential 스캔."""

from __future__ import annotations

import os
import re

from ..settings import PROJECT_FILE

MEMORY_ENV = "ASGARD_MEMORY_DIR"

# 주입면 예산 — 부분(kind)별로 따로 건다.
#
# 총량 하나로 묶으면 수가 많은 칸이 값비싼 칸을 굶긴다: reference 가 쏟아지는 순간
# user·feedback 이 카탈로그에서 밀려나는데, 정작 사람이 같은 말을 두 번 안 하게 만드는 건
# 뒤쪽이다. 그래서 구분선을 kind 로 두고 칸마다 상한을 준다.
#
# 단위는 토큰이 아니라 문자다 — 토큰은 모델마다 변하지만 문자는 안 변한다.
# 그리고 이 값은 **저장을 막지 않는다**. 예산이 정하는 건 "프롬프트에 몇 자를 실을지"뿐이고,
# 지식은 예산과 무관하게 pages/ 에 남는다 (예산 밖 전체 목록은 maps/, 검색은 query 가 전부 본다).
KIND_BUDGETS: dict[str, int] = {
    "user": 1400,  # 오딘이 누구인가 — 수는 적고 값은 제일 비싸다
    "feedback": 1600,  # 일하는 방식 교정 — 두 번 말하지 않게 하는 값
    "decision": 1600,  # 확정된 판정 — 되묻지 않게
    "insight": 1400,  # 스스로 벼려낸 것
    "reference": 2000,  # 수가 가장 많은 칸
    "note": 1200,  # 미분류 catch-all — 제일 싸다
}
INDEX_BUDGET = sum(KIND_BUDGETS.values())  # 전 부분 합계 (표시·계산용)

# 주입 스캔 — 위협 문구 패턴 strict 축약판. 메모리는 프롬프트에 주입되므로
# 오염 엔트리는 세션 전체·세션 간 지속된다. 걸리면 저장 거부 (사람이 고쳐서 재시도).
_THREATS = (
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+(instructions|rules|prompts)",
    r"disregard\s+(the\s+)?(system|previous|above)",
    r"<\s*/?\s*(system|memory-context|assistant|user|tool)\b",  # 태그 경계 탈출·펜스 위조
    r"you\s+are\s+now\b",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"이전\s*지시(사항)?\s*(를|은|는)?\s*무시",
    r"시스템\s*프롬프트\s*(를|을)?\s*(공개|유출|출력)",
    r"\b(curl|wget)\s+https?://",
    r"[A-Za-z0-9+/]{120,}={0,2}",  # 장문 base64 블롭 — 은닉 페이로드 의심
)

# 비가시 문자 — 사람 눈에 안 보이지만 모델은 읽는다. 메모리는 프롬프트에 주입되므로
# 여기 심으면 사람이 페이지를 읽어봐도 아무것도 이상하지 않은데 지시는 전달된다
# (제로폭 문자로 낱말 사이에 문장을 숨기거나, BiDi override 로 화면에 보이는 순서를 뒤집는다).
# 정규식으로는 이걸 못 잡는다 — _THREATS 의 `이전 지시를 무시` 는 글자 사이에 U+200B 하나만
# 끼면 통과한다. 그래서 패턴이 아니라 문자 자체를 막는다.
_INVISIBLE = {
    "​",  # zero width space
    "‌",  # zero width non-joiner
    "‍",  # zero width joiner
    "⁠",  # word joiner
    "﻿",  # zero width no-break space (BOM)
    "­",  # soft hyphen
    "᠎",  # mongolian vowel separator
    "‪",  # LTR embedding
    "‫",  # RTL embedding
    "‬",  # pop directional formatting
    "‭",  # LTR override
    "‮",  # RTL override
    "⁦",  # LTR isolate
    "⁧",  # RTL isolate
    "⁨",  # first strong isolate
    "⁩",  # pop directional isolate
}
# 태그 변이 셀렉터(U+E0000~U+E007F) — 아스키 한 자씩을 비가시 코드포인트로 옮겨 적는 은닉 통로다.
# 범위라서 집합이 아니라 경계로 검사한다.
_TAG_RANGE = (0xE0000, 0xE007F)


def scan_invisible(*texts: str | None) -> str | None:
    """비가시 문자 검사 — 걸리면 코드포인트 요약, 없으면 None.

    \\t·\\n·\\r 은 통과시킨다 (정상 서식). 그 외 Cf(format) 계열과 태그 범위를 막는다."""
    for text in texts:
        if not text:
            continue
        for ch in text:
            code = ord(ch)
            if ch in _INVISIBLE or _TAG_RANGE[0] <= code <= _TAG_RANGE[1]:
                return f"invisible character U+{code:04X}"
    return None


_SECRET_PLACEHOLDERS = (
    "example",
    "placeholder",
    "changeme",
    "redacted",
    "dummy",
    "test-only",
    "your-",
    "your_",
    "****",
)
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|secret[_-]?key)\b\s*[:=]\s*[\"']?([^\s\"']{8,})"
    ),
    # Provider keys are hyphenated, not underscored (sk-ant-…, sk-proj-…, sk-…). Matching only
    # the `_` form let every Anthropic/OpenAI key through the scan and into an injected page.
    re.compile(r"\b(?:sk|gh[oprsu]|github_pat)[_-][A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"(?i)--(?:token|password|passwd|api-key|secret)[= ](?![$\{<])\S{8,}"),
    re.compile(r"://[^/\s:@]{1,64}:(?![$\{])[^@\s/]{6,}@"),
)


def memory_dir() -> str:
    path = os.environ.get(MEMORY_ENV) or ""
    if not path:
        configured = _own_memory_settings().get("directory")
        path = configured if isinstance(configured, str) else ""
    if path.strip():
        return os.path.abspath(os.path.expanduser(path))
    # 1차 기억은 **에이전트의 것**이다 (26-07-29 프로파일 계층). 기본 에이전트면 예전 그대로
    # ~/.asgard/memory, 이름 붙은 에이전트면 자기 홈 아래 — 같은 기계에 선 두 에이전트가
    # 서로의 일지를 못 본다. 명시 override(ASGARD_MEMORY_DIR·설정)는 여전히 위에 있다.
    from ..profiles import home

    return os.path.join(home(), "memory")


def _memory_settings() -> dict:
    """글로벌 [memory] 섹션 — asgard-setting-global.json 우선, 구 config.toml 폴백 (settings.py).

    예산·주입 게이트처럼 **물려받아도 되는** 값을 읽는다 (에이전트마다 다시 맞추게 하지 않는다)."""
    try:
        from ..settings import load_global

        return dict(load_global().get("memory") or {})
    except Exception:
        return {}


def _own_memory_settings() -> dict:
    """활성 에이전트가 자기 파일에 직접 적은 [memory] 만 — `directory` 전용 창구.

    경로는 상속되면 안 된다: 뿌리에 `memory.directory` 가 하나 있으면 병합 뷰에서는 모든
    에이전트가 그 디렉터리를 가리키고, 1차 기억 격리가 설정 한 줄에 조용히 무너진다.
    자기가 선언한 경로만 이긴다 (안 적었으면 자기 홈)."""
    try:
        from ..settings import own_global

        return own_global("memory")
    except Exception:
        return {}


def kind_budgets() -> dict[str, int]:
    """부분별 주입 예산 — config `[memory.index_budget]` 의 kind 키로 칸마다 조정한다.

    미지정 kind 는 기본값을 쓰고, 0 은 그 칸을 주입에서 통째로 뺀다 (저장은 계속 된다).
    알 수 없는 키는 무시한다 — 오타가 조용히 새 칸을 만들지 않는다."""
    budgets = dict(KIND_BUDGETS)
    try:
        table = _memory_settings().get("index_budget")
        if isinstance(table, dict):
            for kind, value in table.items():
                if kind in budgets and value is not None:
                    budgets[kind] = max(0, int(value))
    except Exception:
        return dict(KIND_BUDGETS)
    return budgets


def index_budget() -> int | None:
    """전 부분에 걸리는 총량 상한 (chars). None = 부분별 예산만 적용 (기본값).

    구 설정 `index_budget_chars` 가 여기로 들어온다 — 칸을 쪼갠 뒤에도 "블록 전체가
    이보다 커지지 않는다"를 한 줄로 보증해야 하는 자리(좁은 컨텍스트 창)가 있다."""
    try:
        value = _memory_settings().get("index_budget_chars")
        return max(0, int(value)) if value is not None else None
    except Exception:
        return None


def inject_enabled() -> bool:
    """프롬프트 주입 킬스위치 (2차 리뷰 ⑦) — env ASGARD_MEMORY_INJECT > 설정 memory.inject.
    off 면 snapshot_note 가 빈 문자열 = 어떤 provider 로도 메모리가 전송되지 않는다."""
    v = (os.environ.get("ASGARD_MEMORY_INJECT") or "").strip().lower()
    if v:
        return v not in ("off", "0", "false")
    try:
        return str(_memory_settings().get("inject", "on")).strip().lower() not in ("off", "0", "false")
    except Exception:
        return True


# 훅 배선 클라이언트 모드 — 오딘이 직접 실행하는 코딩 에이전트 호스트. 개인 메모리는 오딘의
# 기억이라 어느 호스트에서든 같은 기억을 본다 (오딘 결정 26-07-23). allowlist 는 네이티브 루프의
# 임의 원격 provider 통제 표면이므로 클라이언트 모드에는 적용하지 않는다 — 끄려면 킬스위치
# (memory.inject=off / ASGARD_MEMORY_INJECT=off).
CLIENT_MODES = frozenset({"claude-code", "codex", "cursor"})


def inject_allowed(provider: str | None = None, provider_source: str | None = None) -> bool:
    """provider별 전송 게이트 — 킬스위치 + `memory.providers` allowlist (배선 단계).
    클라이언트 모드(claude-code/codex/cursor)는 킬스위치만 적용 — 전 모드 동일 기억 (기본 동작).
    allowlist 부재/빈 리스트 = 사용자 선택 provider 는 허용하되 프로젝트 선택 provider 는 거부.
    개인 메모리가 임의 원격 모델로 새는 표면을 사용자가 직접 통제한다 (독립 리뷰 지적)."""
    if not inject_enabled():
        return False
    if not provider:
        return True
    if provider in CLIENT_MODES:
        return True
    try:
        allow = _memory_settings().get("providers")
        if isinstance(allow, list) and allow:
            return provider in [str(a).strip() for a in allow]
    except Exception:
        pass
    return provider_source != f".asgard/{PROJECT_FILE}"


def scan_threats(*texts: str | None) -> str | None:
    """인젝션/유출 패턴 검사 — 하나라도 걸리면 요약 반환, 전부 무해하면 None.
    본문만이 아니라 주입되는 모든 필드(title·links·meta)를 같이 넘긴다 (P0).

    비가시 문자를 먼저 본다: 패턴 검사보다 앞서야 한다. 글자 사이에 제로폭 하나만 끼면
    아래 정규식은 전부 헛돌고, 모델은 그걸 읽는다."""
    if invisible := scan_invisible(*texts):
        return invisible
    for text in texts:
        if not text:
            continue
        for pat in _THREATS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return f"blocked pattern: {m.group(0)[:60]!r}"
    return None


def redact_secrets(text: str) -> str:
    """credential 패턴 스팬만 [redacted-credential] 로 치환한다. placeholder 예시는 보존.

    scan_secrets 는 저장을 '거부'하는 표면(메모리 ingest)용이고, 이 함수는 거부가 불가능한
    표면 — 이미 발화된 세션 원문(turns.jsonl)처럼 통째 폐기가 손해인 기록 — 의 저장 전
    편집용이다. 원문의 나머지는 그대로 보존된다."""
    if not text:
        return text
    low = text.lower()
    spans: list[tuple[int, int]] = []
    for pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            nearby = low[max(0, match.start() - 30) : match.end() + 30]
            if any(marker in match.group(0).lower() or marker in nearby for marker in _SECRET_PLACEHOLDERS):
                continue
            spans.append((match.start(), match.end()))
    if not spans:
        return text
    spans.sort()
    out: list[str] = []
    pos = 0
    for start, end in spans:
        if start < pos:  # 겹치는 스팬 — 이미 편집된 구간에 흡수
            pos = max(pos, end)
            continue
        out.append(text[pos:start])
        out.append("[redacted-credential]")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def scan_secrets(*values: str | None) -> str | None:
    """저장·주입 전 명백한 credential 패턴을 차단한다. placeholder 예시는 허용한다."""
    text = "\n".join(str(value) for value in values if value)
    low = text.lower()
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        nearby = low[max(0, match.start() - 30) : match.end() + 30]
        if any(marker in match.group(0).lower() or marker in nearby for marker in _SECRET_PLACEHOLDERS):
            continue
        return "credential-like content"
    return None
