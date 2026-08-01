"""기획의 HTTP 계약 — 루프백 전용.

정본 데이터와 규칙은 `asgard.plan` 도메인이 진다. 여기 있는 것은 그 도메인을 스튜디오 창의
기획 화면에 이어 주는 얇은 계층뿐이다. **문은 없다**: 기획은 스튜디오 안에서만 쓴다
(`asgard open studio` → 기획). 그래서 이 패키지 이름도 `plan_dashboard`가 아니라 `plan_api`다 —
대시보드가 아니라 계약이다.
"""

from .server import (
    _LOOPBACK_HOSTS,
    _bind,
    _Handler,
    dispatch,
    host_allowed,
    origin_allowed,
    plan_view,
)

__all__ = [
    "_LOOPBACK_HOSTS",
    "_Handler",
    "_bind",
    "dispatch",
    "host_allowed",
    "origin_allowed",
    "plan_view",
]
