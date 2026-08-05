"""슬래시 명령 차례표 — 완성 메뉴와 `/help` 가 같이 읽는다.

입력면과 명령면 어느 쪽에도 두지 않은 이유는 둘 다 이것을 읽기 때문이다. 한쪽에 두면
나머지가 그쪽을 임포트하고, 그쪽은 다시 이쪽을 불러 순환이 된다."""

from __future__ import annotations

from ...i18n import t

_COMMAND_HELP = {
    "/help": "h_help",
    "/skills": "h_skills",
    "/new": "h_new",
    "/quest": "h_quest",
    "/sessions": "h_sessions",
    "/sessions stop": "h_sessions",
    "/provider": "h_provider",
    "/provider set": "h_provider_set",
    "/trinity": "h_trinity",
    "/trinity set": "h_trinity",
    "/trinity models": "h_trinity",
    "/trinity model": "h_trinity",
    "/trinity model reset": "h_trinity",
    "/trinity dual": "h_trinity",
    "/trinity dual on": "h_trinity",
    "/trinity dual off": "h_trinity",
    "/trinity dual default": "h_trinity",
    "/trinity dual default on": "h_trinity",
    "/trinity dual default off": "h_trinity",
    "/bridge": "h_bridge",
    "/manual": "h_manual",
    "/manual show": "h_manual",
    "/lagom": "h_lagom",
    "/lagom off": "h_lagom",
    "/lagom lite": "h_lagom",
    "/lagom full": "h_lagom",
    "/lagom default": "h_lagom",
    "/lagom stats": "h_lagom",
    "/model": "h_model",
    "/lang": "h_lang",
    "/lang en": "h_lang",
    "/lang ko": "h_lang",
    "/update": "h_update",
    "/clear": "h_clear",
    "/exit": "h_exit",
}


def _help_items():
    return [(command, t(key)) for command, key in _COMMAND_HELP.items() if " " not in command]


def _completion_matches(text: str) -> list[str]:
    """최상위 명령을 먼저 보여주고, 인자 후보는 사용자가 공백을 입력한 뒤 펼친다."""
    return [c for c in _COMMAND_HELP if c.startswith(text) and (" " in text or " " not in c)]


def _completer(text: str, state: int):
    """Tab 자동완성 — 슬래시 커맨드 (/ 트리거). readline 콜백."""
    if not text.startswith("/"):
        return None
    matches = [c + " " for c in _completion_matches(text)]
    return matches[state] if state < len(matches) else None
