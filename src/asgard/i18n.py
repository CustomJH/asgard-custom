"""경량 i18n — 기본 영어, config/env 로 한국어 전환.

문자열은 (en, ko) 튜플 테이블. t(key, **kw) 가 현재 언어로 렌더한다. 언어 해석 우선순위:
프로젝트 .asgard/config.toml [ui] lang → ~/.asgard/config.toml → env ASGARD_LANG → 기본 "en".
(시스템 로케일은 보지 않는다 — "기본 영어, 명시 설정 시 한국어" 규칙.)

UI 문자열만 다룬다. 역할 에이전트 프롬프트(heimdall)는 모델 대상이라 대상 아님.
"""

from __future__ import annotations

import os

LANGS = ("en", "ko")
_LANG = "en"

# key: (english, korean)
_M: dict[str, tuple[str, str]] = {
    # 배너·환영
    "tagline": ("Bifrost's watchman · Trinity orchestrator", "비프로스트의 수호자 · Trinity 오케스트레이터"),
    "welcome": ("Welcome to Asgard, Odin.", "Asgard 에 오신 것을 환영합니다, 오딘."),
    "welcome_hint": ("Ask anything, or type /help.", "무엇이든 물으시거나 /help 를 입력하세요."),
    "tip": (
        "Tip — ! for bash, / for commands, Ctrl-C to interrupt a turn.",
        "Tip — ! 로 bash, / 로 커맨드, Ctrl-C 로 턴 중단.",
    ),
    "cmd_hints": (
        "/help · /new · !bash · Tab complete · ↑↓ history",
        "/help · /new · !bash · Tab 자동완성 · ↑↓ 히스토리",
    ),
    "bye": ("Bifrost sealed. Farewell, Odin.", "비프로스트 봉인. 안녕히, 오딘."),
    "ready": ("Heimdall is ready. Ask anything.", "Heimdall 대기 중. 무엇이든 물으세요."),
    # provider·온보딩
    "provider_unset": ("no provider — connect with /provider set", "provider 미설정 — /provider set 으로 연결하세요"),
    "not_connected": ("not connected — /provider set", "미연결 — /provider set"),
    "connect_needed": (
        "provider not connected — run /provider set to connect, then resend",
        "provider 미연결 — /provider set 으로 연결한 뒤 다시 보내세요",
    ),
    "connect_cancel": ("connection cancelled — try /provider set again", "연결 취소 — /provider set 으로 다시 시도"),
    "connected": ("connected", "연결"),
    "pick_provider": ("select a provider", "provider 선택"),
    "pick_model": ("select a model", "model 선택"),
    "api_key_prompt": ("{p} API key (hidden)", "{p} API 키 (입력 숨김)"),
    "saved_cred": ("saved to ~/.asgard/credentials.json (mode 600)", "~/.asgard/credentials.json 저장 (권한 600)"),
    "cancelled": ("(cancelled)", "(취소)"),
    "no_key": ("(no key — cancelled)", "(키 없음 — 취소)"),
    # 상태·턴
    "busy": ("working…", "처리 중…"),
    "interrupt_hint": ("Ctrl-C to stop", "Ctrl-C 중단"),
    "turn_interrupted": ("(turn interrupted)", "(턴 중단)"),
    "turn_kept": ("(turn interrupted — session kept)", "(턴 중단 — 세션 유지)"),
    "session_error": ("session error: {e}", "세션 오류: {e}"),
    "no_quest": ("no active quest", "진행 중 퀘스트 없음"),
    "unknown_cmd": ("unknown command {c} — /help", "미지의 커맨드 {c} — /help"),
    "unknown_cmd_suggest": (
        "unknown command {c} — did you mean {suggestion}?",
        "미지의 커맨드 {c} — 혹시 {suggestion}?",
    ),
    # help 항목
    "h_help": ("this help", "이 도움말"),
    "h_skills": ("list explicitly invocable skills", "직접 호출 가능한 스킬 목록"),
    "h_new": ("new session (reset context & screen)", "새 세션 (컨텍스트·화면 리셋)"),
    "h_quest": ("active quest log status", "진행 중 퀘스트 로그 상태"),
    "h_sessions": (
        "child agent sessions · '/sessions stop' cancels the active tree",
        "하위 에이전트 세션 · '/sessions stop' 으로 실행 트리 취소",
    ),
    "no_sessions": ("no child sessions", "하위 세션 없음"),
    "sessions_stopping": ("cancelling the active session tree", "실행 중인 세션 트리를 취소합니다"),
    "h_provider": (
        "show provider·model · '/provider set' to reconnect",
        "provider·model 표시 · '/provider set' 으로 재설정",
    ),
    "h_model": ("select a model for the current provider", "현재 provider의 모델 선택"),
    "h_clear": ("clear the screen", "화면 지우기"),
    "h_exit": ("end the session (same as Ctrl-D)", "세션 종료 (Ctrl-D 동일)"),
    "h_lang": ("switch language: /lang en | ko", "언어 전환: /lang en | ko"),
    "h_update": ("update asgard to the latest release", "asgard 최신 릴리스로 업데이트"),
    "update_restart": (
        "new version applies after restart — /exit then `asgard start`",
        "새 버전은 재시작 후 적용 — /exit 후 asgard start",
    ),
    "lang_set": ("language → {lang}", "언어 → {lang}"),
    "lang_usage": ("usage: /lang en | ko", "사용법: /lang en | ko"),
    "h_bash": ("run a bash command", "bash 직접 실행"),
    "help_footer": ("Tab complete · ↑↓ history", "Tab 자동완성 · ↑↓ 히스토리"),
    "input_placeholder": (
        "Type a message…  ( /help · !bash · Ctrl-Q quit )",
        "메시지를 입력하세요…  ( /help · !bash · Ctrl-Q 종료 )",
    ),
    "cancel_notice": (
        "⚠ Cancelled by user — turn stopped.",
        "⚠ 사용자 취소 — 턴 중단.",
    ),
    "cancel_notice_quest": (
        " Quest {qid} remains ACTIVE — re-request to continue verification, or close it with quest-log close.",
        " 퀘스트 {qid} 는 ACTIVE 로 남아 있음 — 재요청 시 이어서 검증하거나 quest-log close 하세요.",
    ),
    "continue_restored": (
        "Restored the last conversation ({n} turns) — context only; quests and evidence are unaffected.",
        "이전 대화 {n}턴 복원 — 대화 맥락만이며 퀘스트·증거 상태는 그대로입니다.",
    ),
    "needs_base_url": ("base_url required", "base_url 필요"),
    "thought": ("Runes read", "룬 해독"),
    "thinking": ("reading the runes…", "룬을 읽는 중…"),
    "ph_input": (
        "Ask anything — / commands · ! bash · \\⏎ newline",
        "무엇이든 입력 — / 커맨드 · ! bash · \\⏎ 줄바꿈",
    ),
    "number": ("number", "번호"),
    "model_id_prompt": ("model ID", "모델 ID"),
    "invalid_model_id": ("invalid model ID", "유효하지 않은 모델 ID"),
    "model_catalog_fallback": (
        "live model catalog unavailable — showing offline fallback models",
        "live 모델 catalog를 사용할 수 없어 offline fallback 모델을 표시합니다",
    ),
    # trinity 배치·브릿지
    "h_trinity": (
        "role placements · '/trinity set' to place a role on a provider",
        "역할별 provider 배치 · '/trinity set' 으로 설정",
    ),
    "h_bridge": (
        "per-tool CLI bridge · '/bridge <tool> on|off'",
        "도구별 CLI 브릿지 · '/bridge <도구> on|off'",
    ),
    # lagom
    "h_lagom": (
        "minimalism contract (just-enough code & replies) — '/lagom' shows the modes",
        "미니멀리즘 계약 (딱 적당한 코드·응답) — '/lagom' 로 모드 확인",
    ),
    "lagom_what": (
        "just enough — unwritten code is the best code, unspent tokens the best explanation.\n"
        "safety (input validation · error handling · security) is never trimmed, in any mode.",
        "딱 적당한 만큼만 — 안 쓴 코드가 최고의 코드, 안 쓴 토큰이 최고의 설명.\n"
        "안전 예외(입력 검증·에러 처리·보안)는 어느 모드에서도 안 깎는다.",
    ),
    "lagom_mode_off": ("plain — no output compression, no efficiency ladder", "평소대로 — 산출 압축·효율 사다리 없음"),
    "lagom_mode_lite": (
        "build as asked, add one lazier-alternative line; trim only filler",
        "요청대로 구현 + 더 게으른 대안 한 문장, 군더더기만 제거",
    ),
    "lagom_mode_full": (
        "efficiency ladder enforced · shortest diff · shortest reply",
        "효율 사다리 강제 · 최단 diff · 최단 설명",
    ),
    "lagom_usage": (
        "usage: /lagom [default] off|lite|full · /lagom stats",
        "사용법: /lagom [default] off|lite|full · /lagom stats",
    ),
    "lagom_set": ("lagom → {mode} (this session)", "lagom → {mode} (세션 한정)"),
    "lagom_persisted": (
        "lagom default → {mode} (asgard-setting-project.json)",
        "lagom 기본값 → {mode} (asgard-setting-project.json)",
    ),
    "lagom_session": ("session override", "세션 전환값"),
    "lagom_default": ("default", "기본값"),
    "lagom_stats_tokens": ("session spend {tok} tokens (input+output)", "세션 지출 {tok} 토큰 (입력+출력 합산)"),
    "lagom_stats_note": (
        "savings need measured coefficients — pending a measurement bench; no telemetry, local only",
        "절감량은 실측 계수 필요 — 측정 벤치 후 표시. 텔레메트리 없음, 로컬 집계만",
    ),
    "pick_role": ("select a role", "역할 선택"),
    "placement_clear": ("default (clear placement)", "기본값 (배치 해제)"),
    "placement_saved": (
        "placement saved — applied to new turns",
        "배치 저장 — 새 턴부터 적용",
    ),
    "placement_cleared": ("placement cleared — back to the default provider", "배치 해제 — 기본 provider 로 복귀"),
    "default_tag": ("(default)", "(기본)"),
    "trinity_hint": (
        "'/trinity set' to place a role on another provider",
        "'/trinity set' 으로 역할을 다른 provider 에 배치",
    ),
    "bridge_usage": (
        "usage: /bridge <claude-code|codex|cursor> on|off — lets that tool delegate placed roles via `asgard role`",
        "사용법: /bridge <claude-code|codex|cursor> on|off — 해당 도구가 배치 역할을 `asgard role` 로 위임",
    ),
    "bridge_set": ("bridge.{tool} = {v}", "bridge.{tool} = {v}"),
}


def set_lang(lang: str | None) -> None:
    global _LANG
    _LANG = lang if lang in LANGS else "en"


def current() -> str:
    return _LANG


def load_lang(root: str | None = None) -> str:
    """설정 ui.lang → env ASGARD_LANG → 'en'. set_lang 도 함께 수행하고 결과를 반환.
    설정 파일 = asgard-setting-{project,global}.json (settings.py — 구 config.toml 폴백 내장)."""
    lang = None
    try:
        from .settings import load_global, load_project

        root = root or os.getcwd()
        for cfg in (load_global(), load_project(root)):  # 프로젝트가 글로벌을 덮는다
            v = (cfg.get("ui") or {}).get("lang")
            if v:
                lang = v
    except Exception:
        pass
    lang = lang or os.environ.get("ASGARD_LANG")
    set_lang(lang)
    return _LANG


def save_lang(lang: str, root: str | None = None) -> bool:
    """언어를 프로젝트 asgard-setting-project.json 의 ui.lang 에 저장하고 즉시 적용."""
    if lang not in LANGS:
        return False
    try:
        from .settings import save_project

        save_project(root or os.getcwd(), "ui", {"lang": lang})
    except Exception:
        return False
    set_lang(lang)
    return True


def t(key: str, **kw) -> str:
    en, ko = _M.get(key, (key, key))
    s = ko if _LANG == "ko" else en
    return s.format(**kw) if kw else s
