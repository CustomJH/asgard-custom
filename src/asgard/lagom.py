"""Lagom (CUS-205) — 미니멀리즘 사다리(코드 축) + 산출 압축(산출 축)의 모드 계층.

2계층 상태 (26-07-15 설정 통합):
  영속 기본값  asgard-setting-{project,global}.json 의 lagom.mode (구 config.toml 폴백)
              + LAGOM_MODE env
  세션 런타임  .asgard/state/lagom-mode.json — 훅 3종·네이티브 루프가 공유하는 유일한 접점

resolve 우선순위: 플래그 > LAGOM_MODE env > 프로젝트 설정 > 글로벌 설정 > 기본 full.
review 는 세션 한정 스킬 모드 — 영속 기본값으로 저장 불가 (원본 설계 계승).
훅은 standalone(무임포트)이라 이 모듈을 쓰지 못한다 — 같은 규칙을 각 훅이 내장하며
"동일 유지 (단일 출처 원칙)" 주석으로 이 파일을 가리킨다.
"""

from __future__ import annotations

import json
import os

MODES = ("off", "lite", "full")
DEFAULT_MODE = "full"  # default-on — asgard init 프로젝트는 별도 설정 없이 full 로 돈다
STATE_FILE = "lagom-mode.json"  # <root>/.asgard/state/ 아래 — 런타임 상태 격리 (설정 아님)
# 레거시 (읽기 호환 → 다음 쓰기에서 제거): .asgard/ 직하 json(0.4.x 말) / 단일 문자열(0.4.1 이하)
LEGACY_STATE_FILES = ("lagom-mode.json", "lagom-mode")


def normalize(mode: object) -> str | None:
    """대소문자 무시·공백 트림. 유효 모드가 아니면 None (review 포함 — 영속·상태 대상 아님)."""
    m = str(mode or "").strip().lower()
    return m if m in MODES else None


def default_mode(root: str | None = None, flag: str | None = None) -> str:
    """영속 기본값 해석 — 플래그 > env > 프로젝트 설정 > 글로벌 설정 > full (settings.py 경유)."""
    m = normalize(flag) or normalize(os.environ.get("LAGOM_MODE"))
    if m:
        return m
    try:
        from .settings import load_global, load_project

        root = root or os.getcwd()
        for cfg in (load_project(root), load_global()):  # 프로젝트가 글로벌을 이긴다
            m = normalize((cfg.get("lagom") or {}).get("mode"))
            if m:
                return m
    except Exception:
        pass  # 없거나 깨진 설정 = 이 계층 침묵 (fail-open)
    return DEFAULT_MODE


def state_path(root: str | None = None) -> str:
    return os.path.join(root or os.getcwd(), ".asgard", "state", STATE_FILE)


def _legacy_state_paths(root: str | None = None) -> list[str]:
    base = os.path.join(root or os.getcwd(), ".asgard")
    return [os.path.join(base, name) for name in LEGACY_STATE_FILES]


def read_state(root: str | None = None) -> str | None:
    """세션 런타임 모드 — state/ JSON 우선, 레거시(.asgard/ 직하 json·단일 문자열) 읽기 호환."""
    try:
        with open(state_path(root), encoding="utf-8") as f:
            return normalize(json.load(f).get("mode"))
    except Exception:
        pass
    for p in _legacy_state_paths(root):
        try:
            with open(p, encoding="utf-8") as f:
                raw = f.read()
            try:
                return normalize(json.loads(raw).get("mode"))
            except Exception:
                return normalize(raw)
        except Exception:
            continue
    return None


def write_state(root: str | None = None, mode: str = DEFAULT_MODE) -> bool:
    """상태를 ``{"mode": ...}`` JSON으로 기록 — best-effort. 반환 = 성공 여부."""
    m = normalize(mode)
    if not m:
        return False
    try:
        p = state_path(root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"mode": m}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        for old in _legacy_state_paths(root):  # 쓰기 시점에 레거시 이관 완료 (이원화 방지)
            try:
                os.remove(old)
            except FileNotFoundError:
                pass
        return True
    except Exception:
        return False


def clear_state(root: str | None = None) -> None:
    for path in (state_path(root), *_legacy_state_paths(root)):
        try:
            os.remove(path)
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
