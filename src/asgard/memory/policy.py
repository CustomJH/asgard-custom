"""설정·게이트 계층 — 메모리 위치·주입/provider 게이트·인젝션/credential 스캔."""

from __future__ import annotations

import os
import re

from ..settings import PROJECT_FILE

MEMORY_ENV = "ASGARD_MEMORY_DIR"
INDEX_BUDGET = 2200  # chars — 주입면 상한 검증값. config [memory].index_budget_chars 로 조정

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
    re.compile(r"\b(?:sk|gh[oprsu]|github_pat)_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"(?i)--(?:token|password|passwd|api-key|secret)[= ](?![$\{<])\S{8,}"),
    re.compile(r"://[^/\s:@]{1,64}:(?![$\{])[^@\s/]{6,}@"),
)


def memory_dir() -> str:
    path = os.environ.get(MEMORY_ENV) or ""
    if not path:
        configured = _memory_settings().get("directory")
        path = configured if isinstance(configured, str) else ""
    if path.strip():
        return os.path.abspath(os.path.expanduser(path))
    return os.path.join(os.path.expanduser("~"), ".asgard", "memory")


def _memory_settings() -> dict:
    """글로벌 [memory] 섹션 — asgard-setting-global.json 우선, 구 config.toml 폴백 (settings.py)."""
    try:
        from ..settings import load_global

        return dict(load_global().get("memory") or {})
    except Exception:
        return {}


def index_budget() -> int:
    try:
        value = _memory_settings().get("index_budget_chars")
        return max(0, int(value)) if value is not None else INDEX_BUDGET
    except Exception:
        return INDEX_BUDGET


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
    본문만이 아니라 주입되는 모든 필드(title·links·meta)를 같이 넘긴다 (P0)."""
    for text in texts:
        if not text:
            continue
        for pat in _THREATS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return f"blocked pattern: {m.group(0)[:60]!r}"
    return None


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
