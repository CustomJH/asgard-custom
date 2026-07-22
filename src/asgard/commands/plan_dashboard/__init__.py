"""Asgard Plan — 생각을 구조화하는 로컬 기획 워크스페이스.

`asgard plan`은 127.0.0.1 전용 표준 라이브러리 HTTP 서버를 띄운다. 현재 슬라이스는
기획 UX를 검증하는 동작 목업이며, 정본 스키마와 파일 저장 계약은 후속 구현에서 확정한다.
프론트엔드는 `assets/plan_dashboard.html` 단일 에셋으로 유지한다.
"""

from .server import (
    _LOOPBACK_HOSTS,
    _PAGE,
    _bind,
    _Handler,
    _open,
    dispatch,
    host_allowed,
    render_html,
    run_dashboard,
)

__all__ = [
    "_LOOPBACK_HOSTS",
    "_PAGE",
    "_Handler",
    "_bind",
    "_open",
    "dispatch",
    "host_allowed",
    "render_html",
    "run_dashboard",
]
