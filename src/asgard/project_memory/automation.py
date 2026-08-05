"""프로젝트 메모리 자동 관리 — 파생층은 돌보고 정본 쓰기는 승인에 남긴다."""

from __future__ import annotations

import contextlib
import datetime as _dt
from collections.abc import Mapping

from ..io_files import read_json, write_json
from ..memory.norn import spawn_pass
from ..memory_bridge import backend_target, find_config, is_backend_trusted
from ..settings import state_path

MODE_OFF = "off"
MODE_BALANCED = "balanced"
STATE_FILE = "project-memory-automation.json"
DEFAULT_INTERVAL_DAYS = 7
MAX_INTERVAL_DAYS = 365


def management_mode(cfg: Mapping[str, object]) -> str:
    """자동 관리 등급 — 기본 balanced, 명시적으로 끄거나 잘못 적으면 off."""
    value = cfg.get("auto_manage", MODE_BALANCED)
    if isinstance(value, bool):
        return MODE_BALANCED if value else MODE_OFF
    if isinstance(value, (int, float)):
        return MODE_BALANCED if value > 0 else MODE_OFF
    normalized = str(value).strip().lower()
    if normalized in {"balanced", "safe", "on", "true", "yes", "1", "50", "50%"}:
        return MODE_BALANCED
    return MODE_OFF


def interval_days(cfg: Mapping[str, object]) -> int:
    """파생 학습층 점검 간격. 잘못된 값은 기본값으로 닫는다."""
    value = cfg.get("auto_manage_interval_days", DEFAULT_INTERVAL_DAYS)
    if isinstance(value, bool):
        return DEFAULT_INTERVAL_DAYS
    try:
        return max(1, min(int(str(value)), MAX_INTERVAL_DAYS))
    except TypeError, ValueError:
        return DEFAULT_INTERVAL_DAYS


def _state_path(root: str) -> str:
    return state_path(root, STATE_FILE)


def _state(root: str) -> dict:
    value = read_json(_state_path(root), {})
    return value if isinstance(value, dict) else {}


def learning_due(
    root: str,
    cfg: Mapping[str, object],
    *,
    today: _dt.date | None = None,
) -> tuple[bool, str]:
    """mental model 유지보수 자격 — target 변경 또는 주기 경과만 본다."""
    current = today or _dt.date.today()
    fingerprint = backend_target(dict(cfg))["fingerprint"]
    state = _state(root)
    if state.get("target_fingerprint") != fingerprint:
        return True, "새 project-memory target"
    last = str(state.get("last_learning_started") or "")
    if not last:
        return True, "첫 점검"
    try:
        elapsed = (current - _dt.date.fromisoformat(last[:10])).days
    except ValueError:
        return True, "상태를 읽을 수 없음"
    if elapsed < 0:
        return True, "시계가 이전 점검보다 앞섬"
    interval = interval_days(cfg)
    if elapsed < interval:
        return False, f"최근 점검 {elapsed}일 전"
    return True, f"최근 점검 후 {elapsed}일"


def _mark_started(root: str, cfg: Mapping[str, object], today: _dt.date) -> dict:
    previous = _state(root)
    state = {
        **previous,
        "mode": MODE_BALANCED,
        "target_fingerprint": backend_target(dict(cfg))["fingerprint"],
        "last_learning_started": today.isoformat(),
    }
    write_json(_state_path(root), state)
    return previous


def wake(root: str, *, today: _dt.date | None = None) -> str | None:
    """연결된 trusted project의 파생 학습층을 비동기로 돌리고 한 줄을 반환한다.

    이 함수는 원격 요청을 하지 않는다. 실제 `project-learn --apply` 자식이 binding을 다시
    검증하고 observation 정책·mental model·로컬 synthesis만 갱신한다. 팀 정본 record의
    교정은 별도 project-evolve 제안과 project-approve 경계를 그대로 지난다.
    """
    try:
        found = find_config(root)
        if not found:
            return None
        project_root, cfg = found
        if management_mode(cfg) == MODE_OFF or not is_backend_trusted(cfg):
            return None
        current = today or _dt.date.today()
        due, reason = learning_due(project_root, cfg, today=current)
        if not due:
            return None

        # 먼저 latch를 적어 동시 turn의 중복 스폰 창을 줄인다. Popen 자체가 실패하면 되돌려
        # 다음 turn이 재시도하게 한다. 자식의 원격 실패는 현재 turn을 막지 않고 다음 주기에 재시도한다.
        previous = _mark_started(project_root, cfg, current)
        if not spawn_pass(project_root, "memory", "project-learn", "--apply", "--json"):
            with contextlib.suppress(Exception):
                write_json(_state_path(project_root), previous)
            return None
        return f"프로젝트 mental model 자동 유지보수 시작 — {reason} (balanced: 파생층 자동, 정본 교정은 승인 대기)"
    except Exception:
        return None  # 파생 메모리 장애가 작업 turn을 막지 않는다


__all__ = [
    "DEFAULT_INTERVAL_DAYS",
    "MODE_BALANCED",
    "MODE_OFF",
    "STATE_FILE",
    "interval_days",
    "learning_due",
    "management_mode",
    "wake",
]
