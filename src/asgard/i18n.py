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
    # help 항목
    "h_help": ("this help", "이 도움말"),
    "h_new": ("new session (reset context & screen)", "새 세션 (컨텍스트·화면 리셋)"),
    "h_quest": ("active quest ledger status", "진행 중 퀘스트 원장 상태"),
    "h_provider": (
        "show provider·model · '/provider set' to reconnect",
        "provider·model 표시 · '/provider set' 으로 재설정",
    ),
    "h_model": ("current model id", "현재 모델 ID"),
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
    "needs_base_url": ("base_url required", "base_url 필요"),
    "thought": ("Runes read", "룬 해독"),
    "thinking": ("reading the runes…", "룬을 읽는 중…"),
    "ph_input": ("Ask anything — / commands · ! bash", "무엇이든 입력 — / 커맨드 · ! bash"),
    "number": ("number", "번호"),
    "model_id_prompt": ("model id", "model ID"),
}


def set_lang(lang: str | None) -> None:
    global _LANG
    _LANG = lang if lang in LANGS else "en"


def current() -> str:
    return _LANG


def load_lang(root: str | None = None) -> str:
    """config [ui] lang → env ASGARD_LANG → 'en'. set_lang 도 함께 수행하고 결과를 반환."""
    import tomllib

    root = root or os.getcwd()
    lang = None
    for path in (
        os.path.join(os.path.expanduser("~"), ".asgard", "config.toml"),
        os.path.join(root, ".asgard", "config.toml"),
    ):
        try:
            with open(path, "rb") as f:
                ui = tomllib.load(f).get("ui") or {}
            if ui.get("lang"):
                lang = ui["lang"]  # 프로젝트가 글로벌을 덮는다
        except Exception:
            pass
    lang = lang or os.environ.get("ASGARD_LANG")
    set_lang(lang)
    return _LANG


def save_lang(lang: str, root: str | None = None) -> bool:
    """언어를 프로젝트 .asgard/config.toml [ui] lang 에 저장하고 즉시 적용. tomllib 는 읽기 전용
    이므로 [ui] 섹션만 최소 편집(있으면 교체, 없으면 append) — provider 등 다른 섹션 보존."""
    if lang not in LANGS:
        return False
    import re

    root = root or os.getcwd()
    d = os.path.join(root, ".asgard")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "config.toml")
    try:
        txt = open(path).read()
    except FileNotFoundError:
        txt = ""
    block = f'[ui]\nlang = "{lang}"\n'
    if re.search(r"^\[ui\]", txt, re.M):
        txt = re.sub(r"^\[ui\][^\[]*", block, txt, count=1, flags=re.M)
    else:
        txt = (txt.rstrip() + "\n\n" + block) if txt.strip() else block
    open(path, "w").write(txt)
    set_lang(lang)
    return True


def t(key: str, **kw) -> str:
    en, ko = _M.get(key, (key, key))
    s = ko if _LANG == "ko" else en
    return s.format(**kw) if kw else s
