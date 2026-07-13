"""Lagom (CUS-205) — 미니멀리즘 사다리(코드 축) + 산출 압축(산출 축)의 모드 계층.

2계층 상태:
  영속 기본값  config.toml [lagom].mode (글로벌 → 프로젝트, 키 단위 덮어쓰기) + LAGOM_MODE env
  세션 런타임  .asgard/lagom-mode 상태파일 — 훅 3종·네이티브 루프가 공유하는 유일한 접점

resolve 우선순위: 플래그 > LAGOM_MODE env > 프로젝트 config > 글로벌 config > 기본 full.
review 는 세션 한정 스킬 모드 — 영속 기본값으로 저장 불가 (원본 설계 계승).
훅은 standalone(무임포트)이라 이 모듈을 쓰지 못한다 — 같은 규칙을 각 훅이 내장하며
"동일 유지 (단일 출처 원칙)" 주석으로 이 파일을 가리킨다.
"""

from __future__ import annotations

import os
import tomllib

MODES = ("off", "lite", "full", "ultra")
DEFAULT_MODE = "full"  # default-on — asgard init 프로젝트는 별도 설정 없이 full 로 돈다
STATE_FILE = "lagom-mode"  # <root>/.asgard/ 아래 — 런타임 상태라 .asgard/.gitignore 가 커버


def normalize(mode: object) -> str | None:
    """대소문자 무시·공백 트림. 유효 모드가 아니면 None (review 포함 — 영속·상태 대상 아님)."""
    m = str(mode or "").strip().lower()
    return m if m in MODES else None


def default_mode(root: str | None = None, flag: str | None = None) -> str:
    """영속 기본값 해석 — 플래그 > env > 프로젝트 > 글로벌 > full."""
    m = normalize(flag) or normalize(os.environ.get("LAGOM_MODE"))
    if m:
        return m
    root = root or os.getcwd()
    for path in (
        os.path.join(root, ".asgard", "config.toml"),  # 프로젝트가 글로벌을 이긴다
        os.path.join(os.path.expanduser("~"), ".asgard", "config.toml"),
    ):
        try:
            with open(path, "rb") as f:
                m = normalize((tomllib.load(f).get("lagom") or {}).get("mode"))
            if m:
                return m
        except Exception:
            continue  # 없거나 깨진 config = 이 계층 침묵 (fail-open)
    return DEFAULT_MODE


def state_path(root: str | None = None) -> str:
    return os.path.join(root or os.getcwd(), ".asgard", STATE_FILE)


def read_state(root: str | None = None) -> str | None:
    """세션 런타임 모드 — 상태파일이 없거나 값이 깨졌으면 None."""
    try:
        return normalize(open(state_path(root), encoding="utf-8").read())
    except Exception:
        return None


def write_state(root: str | None = None, mode: str = DEFAULT_MODE) -> bool:
    """상태파일 기록 — best-effort (실패해도 세션은 계속). 반환 = 성공 여부."""
    m = normalize(mode)
    if not m:
        return False
    try:
        p = state_path(root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(m + "\n")
        return True
    except Exception:
        return False


def clear_state(root: str | None = None) -> None:
    try:
        os.remove(state_path(root))
    except Exception:
        pass


def current_mode(root: str | None = None, flag: str | None = None) -> str:
    """유효 모드 — 세션 전환(상태파일)이 영속 기본값을 이긴다."""
    return read_state(root) or default_mode(root, flag)


def note(root: str | None = None, flag: str | None = None) -> str:
    """네이티브 루프 프롬프트 주입분 — off 면 빈 문자열 (프롬프트 무변화, 토큰 회귀 없음)."""
    mode = current_mode(root, flag)
    if mode == "off":
        return ""
    from .templates.lagom import render_lagom

    body = render_lagom(mode)
    return "\n\n" + body if body else ""
