"""모드 — 기본 on. lagom과 독립: `/lagom off`는 압축을 끄는 것이지 사람 문체를 끄는 게 아니다."""

from __future__ import annotations

import os

# ── 모드 — 기본 on. lagom과 독립: `/lagom off`는 압축을 끄는 것이지 사람 문체를 끄는 게 아니다.
MODES = ("on", "off")
DEFAULT_MODE = "on"


def normalize(mode: object) -> str | None:
    m = str(mode or "").strip().lower()
    return m if m in MODES else None


def current_mode(root: str | None = None, flag: str | None = None) -> str:
    """플래그 > ASGARD_BRAGI env > 프로젝트 설정 > 글로벌 설정 > on."""
    m = normalize(flag) or normalize(os.environ.get("ASGARD_BRAGI"))
    if m:
        return m
    try:
        from ..settings import load_global, load_project

        for cfg in (load_project(root or os.getcwd()), load_global()):
            m = normalize((cfg.get("bragi") or {}).get("mode"))
            if m:
                return m
    except Exception:
        pass  # 없거나 깨진 설정 = 이 계층 침묵 (fail-open)
    return DEFAULT_MODE


def enabled(root: str | None = None, flag: str | None = None) -> bool:
    return current_mode(root, flag) == "on"


def note(root: str | None = None, flag: str | None = None) -> str:
    """네이티브 루프 프롬프트 주입분 — off 면 빈 문자열 (토큰 회귀 없음)."""
    if not enabled(root, flag):
        return ""
    from ..templates.bragi import BRAGI_CANON

    return "\n\n" + BRAGI_CANON
