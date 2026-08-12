"""노른 상태 파일 — 트리거 판정과 latch가 읽고 쓰는 `norn-state.json` 한 자리.

세 쪽이 같은 파일을 본다: 트리거(`auto.norn_due`), 자율 런(`auto.run_auto`), 적용
(`apply.apply_norn`). 어느 한쪽에 두면 나머지 둘이 그 모듈을 임포트하게 되므로 따로 둔다.
"""

from __future__ import annotations

import contextlib
import json
import os

from ..store import LOG, _atomic_write

STATE_FILE = "norn-state.json"


def _state_path(d: str) -> str:
    return os.path.join(d, STATE_FILE)


def _load_state(d: str) -> dict:
    try:
        with open(_state_path(d), encoding="utf-8") as handle:
            state = json.load(handle)
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _save_state(d: str, state: dict) -> None:
    with contextlib.suppress(Exception):
        _atomic_write(_state_path(d), json.dumps(state, ensure_ascii=False, indent=1))


def _log_lines(d: str) -> int:
    """log.md 누적 연산 행 수 — 노른 트리거의 결정적 활동 신호 (LLM·중요도 점수 불필요)."""
    try:
        with open(os.path.join(d, LOG), encoding="utf-8") as handle:
            return sum(1 for line in handle if line.startswith("- "))
    except Exception:
        return 0
