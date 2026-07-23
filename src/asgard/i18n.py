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
    "welcome": ("Welcome to Asgard, Odin.", "오딘, Asgard에 오신 걸 환영해요."),
    "welcome_hint": ("Ask anything, or type /help.", "무엇이든 물어보세요. 도움이 필요하면 /help를 입력하면 돼요."),
    "tip": (
        "Tip — ! for bash, / for commands, Ctrl-C to interrupt a turn.",
        "Tip — !로 bash 실행 · /로 커맨드 · Ctrl-C로 턴 중단",
    ),
    "cmd_hints": (
        "/help · /new · !bash · Tab complete · ↑↓ history",
        "/help · /new · !bash · Tab 자동완성 · ↑↓ 히스토리",
    ),
    "bye": ("Bifrost sealed. Farewell, Odin.", "비프로스트를 봉인했어요. 다음에 또 만나요, 오딘."),
    "ready": ("Heimdall is ready. Ask anything.", "Heimdall이 준비됐어요. 무엇이든 물어보세요."),
    # provider·온보딩
    "provider_unset": (
        "no provider — connect with /provider set",
        "아직 연결된 provider가 없어요 — /provider set으로 연결해 주세요",
    ),
    "not_connected": ("not connected — /provider set", "연결 안 됨 — /provider set"),
    "connect_needed": (
        "provider not connected — run /provider set to connect, then resend",
        "provider가 아직 연결되지 않았어요 — /provider set으로 연결한 뒤 다시 보내 주세요",
    ),
    "connect_cancel": (
        "connection cancelled — try /provider set again",
        "연결을 취소했어요 — /provider set으로 다시 시도할 수 있어요",
    ),
    "connected": ("connected", "연결됨"),
    "pick_provider": ("select a provider", "사용할 provider를 선택해 주세요"),
    "pick_model": ("select a model", "사용할 모델을 선택해 주세요"),
    # 인터랙티브 선택 패널 (picker)
    "picker_filter_ph": ("type to filter", "입력하면 바로 걸러져요"),
    "picker_hint": (
        "↑↓ move · type to filter · enter select · esc cancel",
        "↑↓ 이동 · 입력해 필터 · enter 선택 · esc 취소",
    ),
    "picker_more": ("… {n} more", "… {n}개 더"),
    "picker_no_match": ("no match", "일치하는 항목이 없어요"),
    "picker_manual_model": ('use "{q}" as model ID', '"{q}"를 모델 ID로 사용'),
    # 턴 종료 recap — 자연어 한 문장 (딤)
    "recap_created": ("created {f}", "{f} 생성"),
    "recap_patched": ("patched {f}", "{f} 수정"),
    "recap_ran": ("ran {c}", "{c} 실행"),
    "recap_agents": ("agents {a}", "에이전트 {a}"),
    # recap 메타 이벤트 — 기억·자가발전 부수 작업 (표시 1순위). 기억 체계 = 위그드라실(세계수),
    # 개인 기억은 줄기에 새기고 프로젝트 기억은 프로젝트 가지 — 승인권자는 오딘(사용자).
    "recap_ev_memory_saved": ("carved into Yggdrasil: {s}", "위그드라실에 새겼어요: {s}"),
    "recap_ev_retained": (
        "preserved this turn on Yggdrasil's project branch",
        "이 턴을 위그드라실 프로젝트 가지에 보존했어요",
    ),
    "recap_ev_proposed": (
        "proposed an update to Yggdrasil's project branch (awaiting Odin's approval)",
        "위그드라실 프로젝트 가지 갱신을 제안했어요 (오딘 승인 대기)",
    ),
    "recap_ev_distill": (
        "suggested distilling this exploration into Yggdrasil",
        "이번 탐색을 위그드라실로 증류하도록 제안했어요",
    ),
    "api_key_prompt": ("{p} API key (hidden)", "{p} API 키 (입력한 키는 화면에 보이지 않아요)"),
    "rpm_prompt": ("rpm limit (requests/min · -1 = off)", "rpm 상한 (분당 요청 수 · -1이면 제한 없음)"),
    "rpm_invalid": ("invalid rpm — keeping current", "rpm 값이 올바르지 않아요 — 기존 값을 그대로 둘게요"),
    "saved_cred": (
        "saved to ~/.asgard/credentials.json (mode 600)",
        "~/.asgard/credentials.json에 저장했어요 (권한 600)",
    ),
    "cancelled": ("(cancelled)", "(취소했어요)"),
    "no_key": ("(no key — cancelled)", "(키가 입력되지 않아 취소했어요)"),
    # 상태·턴
    "busy": ("working…", "작업하고 있어요…"),
    "interrupt_hint": ("Ctrl-C to stop", "Ctrl-C로 중단"),
    "turn_interrupted": ("(turn interrupted)", "(턴을 중단했어요)"),
    "turn_kept": ("(turn interrupted — session kept)", "(턴을 중단했어요 — 세션은 그대로 이어져요)"),
    "session_error": ("session error: {e}", "세션에 문제가 생겼어요: {e}"),
    "no_quest": ("no active quest", "진행 중인 퀘스트가 없어요"),
    "unknown_cmd": ("unknown command {c} — /help", "{c}는 모르는 커맨드예요 — /help에서 전체 목록을 볼 수 있어요"),
    "unknown_cmd_suggest": (
        "unknown command {c} — did you mean {suggestion}?",
        "{c}는 모르는 커맨드예요 — 혹시 {suggestion} 아닌가요?",
    ),
    # help 항목
    "h_help": ("this help", "이 도움말 보기"),
    "h_skills": ("list explicitly invocable skills", "직접 부를 수 있는 스킬 목록"),
    "h_new": ("new session (reset context & screen)", "새 세션 시작 (컨텍스트·화면 초기화)"),
    "h_quest": ("active quest log status", "진행 중인 퀘스트 로그 보기"),
    "h_sessions": (
        "child agent sessions · '/sessions stop' cancels the active tree",
        "하위 에이전트 세션 목록 · '/sessions stop'으로 실행 트리 취소",
    ),
    "no_sessions": ("no child sessions", "하위 세션이 없어요"),
    "sessions_stopping": ("cancelling the active session tree", "실행 중인 세션 트리를 취소할게요"),
    "h_provider": (
        "show current provider·model connection",
        "현재 provider·모델 연결 상태 보기",
    ),
    "h_provider_set": (
        "connect or change provider (interactive)",
        "provider 연결·변경 (대화형)",
    ),
    "h_model": ("select a model for the current provider", "현재 provider에서 쓸 모델 고르기"),
    "h_clear": ("clear the screen", "화면 지우기"),
    "h_exit": ("end the session (same as Ctrl-D)", "세션 종료 (Ctrl-D와 같아요)"),
    "h_lang": ("switch language: /lang en | ko", "언어 바꾸기: /lang en | ko"),
    "h_update": ("update asgard to the latest release", "asgard를 최신 릴리스로 업데이트"),
    "update_restart": (
        "new version applies after restart — /exit then `asgard start`",
        "새 버전은 다시 시작하면 적용돼요 — /exit 후 asgard start",
    ),
    "lang_set": ("language → {lang}", "언어를 바꿨어요 → {lang}"),
    "lang_usage": ("usage: /lang en | ko", "사용법: /lang en | ko"),
    "h_bash": ("run a bash command", "bash 명령 바로 실행"),
    "help_footer": ("Tab complete · ↑↓ history", "Tab 자동완성 · ↑↓ 히스토리"),
    "cancel_notice": (
        "⚠ Cancelled by user — turn stopped.",
        "⚠ 요청하신 대로 턴을 중단했어요.",
    ),
    "cancel_notice_quest": (
        " Quest {qid} remains ACTIVE — re-request to continue verification, or close it with quest-log close.",
        " 퀘스트 {qid}는 아직 ACTIVE 상태예요 — 다시 요청하면 이어서 검증하고, quest-log close로 닫을 수도 있어요.",
    ),
    "continue_restored": (
        "Restored the last conversation ({n} turns) — context only; quests and evidence are unaffected.",
        "이전 대화 {n}턴을 복원했어요 — 대화 맥락만 이어지고, 퀘스트·증거 상태는 그대로예요.",
    ),
    "needs_base_url": ("base_url required", "base_url이 필요해요"),
    "thought": ("Runes read", "룬 해독"),
    "thinking": ("reading the runes…", "룬을 읽는 중…"),
    "ph_input": (
        "Ask anything — / commands · ! bash · \\⏎ newline",
        "무엇이든 입력하세요 — / 커맨드 · ! bash · \\⏎ 줄바꿈",
    ),
    "number": ("number", "번호"),
    "model_id_prompt": ("model ID", "모델 ID"),
    "invalid_model_id": ("invalid model ID", "모델 ID가 올바르지 않아요"),
    "model_catalog_fallback": (
        "live model catalog unavailable — showing offline fallback models",
        "실시간 모델 목록을 불러오지 못했어요 — 내장 목록을 대신 보여드릴게요",
    ),
    # trinity 배치·브릿지
    "h_trinity": (
        "role providers and host models · '/trinity set' or '/trinity model …' to configure",
        "역할별 provider·호스트 모델 보기 · '/trinity set' 또는 '/trinity model …'로 설정",
    ),
    "h_bridge": (
        "per-tool CLI bridge · '/bridge <tool> on|off'",
        "도구별 CLI 브릿지 · '/bridge <도구> on|off'",
    ),
    # lagom
    "h_lagom": (
        "minimalism contract (just-enough code & replies) — '/lagom' shows the modes",
        "미니멀리즘 계약 (딱 적당한 코드·응답) — '/lagom'으로 모드 확인",
    ),
    "lagom_what": (
        "just enough — unwritten code is the best code, unspent tokens the best explanation.\n"
        "safety (input validation · error handling · security) is never trimmed, in any mode.",
        "딱 적당한 만큼만 — 안 쓴 코드가 최고의 코드, 안 쓴 토큰이 최고의 설명이에요.\n"
        "안전(입력 검증·에러 처리·보안)은 어떤 모드에서도 줄이지 않아요.",
    ),
    "lagom_mode_off": (
        "plain — no output compression, no efficiency ladder",
        "평소대로 — 산출 압축도, 효율 사다리도 없어요",
    ),
    "lagom_mode_lite": (
        "build as asked, add one lazier-alternative line; trim only filler",
        "요청대로 만들고 더 간단한 대안을 한 줄 제안해요 · 군더더기만 덜어내요",
    ),
    "lagom_mode_full": (
        "efficiency ladder enforced · shortest diff · shortest reply",
        "효율 사다리 적용 · 가장 짧은 diff · 가장 짧은 설명",
    ),
    "lagom_usage": (
        "usage: /lagom [default] off|lite|full · /lagom stats",
        "사용법: /lagom [default] off|lite|full · /lagom stats",
    ),
    "lagom_set": ("lagom → {mode} (this session)", "lagom → {mode} (이번 세션만)"),
    "lagom_persisted": (
        "lagom default → {mode} (asgard-setting-project.json)",
        "lagom 기본값 → {mode} (asgard-setting-project.json)",
    ),
    "lagom_session": ("session override", "이번 세션 값"),
    "lagom_default": ("default", "기본값"),
    "lagom_fixing": ("polishing the reply — style check…", "응답 문체를 다듬는 중…"),
    "lagom_corrected": (
        "⠶ style check rewrote the reply — the version below is canonical",
        "⠶ 문체 검사로 응답을 다듬었어요 — 아래가 정본이에요",
    ),
    "lagom_stats_tokens": (
        "session spend {tok} tokens (input+output)",
        "이번 세션에서 {tok} 토큰을 썼어요 (입력+출력)",
    ),
    "lagom_stats_note": (
        "savings need measured coefficients — pending a measurement bench; no telemetry, local only",
        "절감량은 실측 계수를 얻은 뒤에 보여드릴게요 — 텔레메트리 없이 로컬에서만 집계해요",
    ),
    "pick_role": ("select a role", "역할을 선택해 주세요"),
    "pick_host": ("select where the agent runs", "에이전트를 실행할 환경을 선택해 주세요"),
    "current_tag": ("current", "현재"),
    "recommended_tag": ("recommended", "추천"),
    "model_override_clear": (
        "clear project override (use global/default)",
        "프로젝트 설정 해제 (글로벌/기본값 사용)",
    ),
    "placement_clear": ("default (clear placement)", "기본값 (배치 해제)"),
    "placement_saved": (
        "placement saved — applied to new turns",
        "배치를 저장했어요 — 새 턴부터 적용돼요",
    ),
    "placement_cleared": (
        "placement cleared — back to the default provider",
        "배치를 해제했어요 — 기본 provider로 돌아가요",
    ),
    "default_tag": ("(default)", "(기본)"),
    "trinity_hint": (
        "'/trinity models' lists all models · '/trinity model …' sets one · '/trinity dual on|off' toggles two-model planning",
        "'/trinity models'로 전체 확인 · '/trinity model …'로 개별 설정 · '/trinity dual on|off'로 두 모델 계획 전환",
    ),
    "trinity_model_usage": (
        "usage: /trinity model <host> <role> <model> [Claude/Codex effort | native provider] · /trinity model reset <host> <role>",
        "사용법: /trinity model <host> <role> <model> [Claude/Codex effort | native provider] · /trinity model reset <host> <role>",
    ),
    "trinity_model_saved": (
        "{host}.{role} → {value} (this project)",
        "{host}.{role} → {value} (이 프로젝트)",
    ),
    "trinity_model_reset": (
        "{host}.{role} override cleared → {value}",
        "{host}.{role} 사용자 설정 해제 → {value}",
    ),
    "trinity_dual_usage": (
        "usage: /trinity dual [default] on|off",
        "사용법: /trinity dual [default] on|off",
    ),
    "trinity_dual_same": (
        "dual mode needs a distinct thinker_alt model ({model}) — configure it with '/trinity set'",
        "dual 모드에는 지금과 다른 thinker_alt 모델이 필요해요 ({model}) — '/trinity set'으로 배치해 주세요",
    ),
    "trinity_dual_set": ("dual thinker → {mode} (this session)", "dual thinker → {mode} (이번 세션만)"),
    "trinity_dual_persisted": (
        "dual thinker default → {mode} (this project)",
        "dual thinker 기본값 → {mode} (이 프로젝트)",
    ),
    "bridge_usage": (
        "usage: /bridge <claude-code|codex|cursor> on|off — lets that tool delegate placed roles via `asgard role`",
        "사용법: /bridge <claude-code|codex|cursor> on|off — 해당 도구가 배치된 역할을 `asgard role`로 위임해요",
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
