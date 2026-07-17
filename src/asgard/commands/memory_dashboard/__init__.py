"""memory dashboard — 개인 1차 메모리(Tier0 로컬 위키)의 읽기 전용 관측 창.

`asgard memory dashboard` 가 127.0.0.1 에 표준 라이브러리 http.server 만으로 일회성
프로세스를 띄운다(신규 의존성 0, Ctrl-C 종료). 상주 데몬·다포트가 아니다.

계약:
  · 읽기 전용 — 쓰기 엔드포인트 없음. 검색만 파라미터를 받는 GET. 쓰기는 기존 CLI 승인
    게이트가 담당한다 (대시보드는 창이지 손이 아니다).
  · 실데이터 — 모든 패널은 asgard.memory 의 실제 함수(query·lint·_pages·usage_stats 등)에서
    읽는다. 목업 없음.
  · 관측 무해 — 대시보드 검색은 track=False 로 usage 를 변조하지 않는다. 대시보드가 표시하는
    바로 그 decay/회수 통계를 자기 관측으로 왜곡하지 않기 위함이다.

디자인(관문 콘솔 · Gate Console): 나이트+골드 다크 단일 테마. 앱 구성은 agentmemory 뷰어의
셸을 이식 — 상단 탭 바(개요·성좌·서고·연대기·활동) + URL 해시 라우팅(#성좌 딥링크·뒤로가기)
+ 탭별 lazy-load + 전역 data-action 위임 + IME-safe 검색·포커스 보존. 오프닝 = 로고 스플래시
점등 씬(세션 1회, 상단 고정 로고 없음). 성좌 = 물리 시뮬 Canvas 그래프(링크 실선·의미 점선·
죽은 링크 절단선 삼중 엣지 언어), 서고 = 카탈로그+질의 스트림 프리즘(FTS/스캔/시맨틱 레인),
연대기 = 좌우 교차 타임라인(/api/log 서버 페이지네이션·op/day 필터), 활동 = 52주 열지도
(셀 클릭 → 연대기 해당 일자 딥링크). 자동 새로고침 30s — 활성 탭만, document.hidden 정지,
성좌는 데이터 서명 불변이면 재시드하지 않는다(드래그 배치 보존). 자기완결 단일 HTML(외부 CDN 0).
"""

from __future__ import annotations

from .data import (
    _LOG_LINE,
    _LOGO_URI,
    SEM_EDGE_FLOOR,
    SEM_EDGE_TOP,
    _desc_of,
    _local_day,
    _logo_data_uri,
    _packaged_logo,
    _repo_logo,
    _semantic_edges,
    _semantic_status,
    activity_data,
    catalog_data,
    graph_data,
    health_data,
    log_data,
    log_query,
    page_data,
    search_data,
    snapshot_data,
)
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
    "SEM_EDGE_FLOOR",
    "SEM_EDGE_TOP",
    "_LOG_LINE",
    "_LOGO_URI",
    "_LOOPBACK_HOSTS",
    "_PAGE",
    "_Handler",
    "_bind",
    "_desc_of",
    "_local_day",
    "_logo_data_uri",
    "_open",
    "_packaged_logo",
    "_repo_logo",
    "_semantic_edges",
    "_semantic_status",
    "activity_data",
    "catalog_data",
    "dispatch",
    "graph_data",
    "health_data",
    "host_allowed",
    "log_data",
    "log_query",
    "page_data",
    "render_html",
    "run_dashboard",
    "search_data",
    "snapshot_data",
]
