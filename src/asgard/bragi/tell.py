"""흔적 하나의 자료형과 심각도 눈금 — 코퍼스 모듈이 전부 이것으로 패턴을 적는다."""

from __future__ import annotations

import re
from typing import NamedTuple

SEVERITIES = ("S1", "S2", "S3")
_S2_MIN_HITS = 3  # S2 = 빈도 기반 — 1~2회는 사람 글에서도 흔하다
_GRADES = ("A", "B", "C", "D")


class Tell(NamedTuple):
    """AI 작문 흔적 하나. rx는 검사 사본에 적용되는 컴파일된 패턴."""

    id: str
    category: str
    severity: str
    rx: re.Pattern[str]
    hint: str  # 사람·모델이 읽는 교정 지시 — 무엇으로 바꿔야 하는지


class Finding(NamedTuple):
    """탐지 결과 하나."""

    id: str
    severity: str
    category: str
    hint: str
    sample: str  # 원문에서 잡힌 첫 표본 (교정 대상 지시용)
    hits: int


def _t(tid: str, category: str, severity: str, pattern: str, hint: str, flags: int = 0) -> Tell:
    return Tell(tid, category, severity, re.compile(pattern, flags), hint)
