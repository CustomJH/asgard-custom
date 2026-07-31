"""기획 화면의 표면 — 루프백 HTTP 계약과 창을 여는 문.

정본 데이터와 규칙은 `asgard.plan` 도메인이 진다. 여기 있는 것은 그 도메인을 창(`?view=plan`)
과 `asgard plan` 에 이어 주는 얇은 계층뿐이다 — 기획 표면은 하나다.
"""

from .server import (
    _LOOPBACK_HOSTS,
    _bind,
    _Handler,
    dispatch,
    host_allowed,
    origin_allowed,
    plan_view,
    run_dashboard,
)

__all__ = [
    "_LOOPBACK_HOSTS",
    "_Handler",
    "_bind",
    "dispatch",
    "host_allowed",
    "origin_allowed",
    "plan_view",
    "run_dashboard",
]
