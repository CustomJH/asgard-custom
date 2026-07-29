"""위그드라실 관측 창 (memory dashboard) — 개인 1차 메모리(Tier0 로컬 위키)의 읽기 전용 관측 창.

`asgard memory dashboard` 가 127.0.0.1 에 표준 라이브러리 http.server 만으로 일회성
프로세스를 띄운다(신규 의존성 0, Ctrl-C 종료). 상주 데몬·다포트가 아니다.

계약:
  · 읽기 전용 — 쓰기 엔드포인트 없음. 검색만 파라미터를 받는 GET. 쓰기는 기존 CLI 승인
    게이트가 담당한다 (대시보드는 창이지 손이 아니다).
  · 실데이터 — 모든 패널은 asgard.memory 의 실제 함수(query·lint·_pages·usage_stats 등)에서
    읽는다. 목업 없음.
  · 관측 무해 — 대시보드 검색은 track=False 로 usage 를 변조하지 않는다. 대시보드가 표시하는
    바로 그 decay/회수 통계를 자기 관측으로 왜곡하지 않기 위함이다.

디자인(관문 콘솔 · Gate Console): 나이트+골드 다크 단일 테마 — `asgard map` 과 같은 토큰·같은
브랜드 마크를 쓴다(두 창을 한 제품으로 읽히게 하는 공통 앵커). 셸은 상단 탭 바
(개요·성좌·서고·전달·정리·연대기·활동) + URL 해시 라우팅(#성좌 딥링크·뒤로가기) + 탭별
lazy-load + 전역 data-action 위임 + IME-safe 검색·포커스 보존. 오프닝 = 로고 스플래시 점등 씬
(세션 1회). 셸 폭은 사용자 소유다 — 좁게·기본·넓게·전체 4모드가 `--shell-max` 한 토큰만 갈아
끼우고 localStorage 에 남는다. 본문은 컨테이너라 레이아웃 분기가 화면이 아니라 **껍데기 실폭**을 본다 —
그래서 스위치가 실제로 열 수를 바꾼다. 넓힌 폭은 '더 긴 줄'이 아니라 '더 많은 열'로 간다
(글 칸은 `--measure` 상한을 따로 갖는다).

탭:
  · 개요 = 벤또 격자(1x1·2x1·1x2·2x2 혼합) — 분량 게이지·전달 요약·의미 검색 준비 /
    건강 진단·연대기 발췌·자주 꺼내 쓴 기억 + 원본/파생 경계
  · 성좌 = 물리 시뮬 Canvas 그래프(직접 링크 실선·뜻 비슷함 점선·끊어진 링크 절단선)
  · 서고 = 카탈로그 + 검색 경로 표시(글자 검색 / 본문 훑기 / 뜻 검색)
  · 전달 = **저장된 것과 AI 에게 가는 것의 차이** — snapshot_note() 원문·종류별 한도·밀려난
    행·오염 제외분·킬스위치. 페이로드가 커서 /api/injection 으로 분리(탭 진입 시에만 요청).
  · 정리 = 노른 자가 진화 — 통찰 출처·충돌(사람이 정할 일)·기록·보관함·백업·사용자 요약 카드
  · 연대기 = 좌우 교차 타임라인(/api/log 서버 페이지네이션·op/day 필터)
  · 활동 = 52주 열지도(셀 클릭 → 연대기 해당 일자 딥링크)

표면 어휘는 사람 말로 쓴다 — '주입/손질/프리즘/정본' 같은 내부 용어는 코드에 남기고,
화면에는 '전달/정리/검색 경로/원본'으로 적는다. 세계관 이름(위그드라실·성좌·서고·연대기)은
제품 정체성이라 그대로 두되, 옆에 무엇인지 한 줄로 풀어 준다.

자동 새로고침 30s — 활성 탭만, document.hidden 정지, 성좌는 데이터 서명 불변이면 재시드하지
않는다(드래그 배치 보존). 갱신 때 전달 탭 캐시도 같이 버린다 — 낡은 블록을 진짜라고 말하지
않기 위해서다. 자기완결 단일 HTML(외부 CDN 0).
"""

from __future__ import annotations

from .data import (
    _LOG_LINE,
    _LOGO_URI,
    _MARK_URI,
    SEM_EDGE_FLOOR,
    SEM_EDGE_TOP,
    _contradictions,
    _desc_of,
    _local_day,
    _logo_data_uri,
    _mark_data_uri,
    _norn_insight_auto,
    _packaged_logo,
    _packaged_mark,
    _repo_logo,
    _semantic_edges,
    activity_data,
    archive_data,
    backup_data,
    catalog_data,
    derived_data,
    graph_data,
    health_data,
    injection_data,
    log_data,
    log_query,
    norn_data,
    page_data,
    pattern_reports,
    peer_card_data,
    search_data,
    semantic_data,
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
    "_MARK_URI",
    "_PAGE",
    "_Handler",
    "_bind",
    "_contradictions",
    "_desc_of",
    "_local_day",
    "_logo_data_uri",
    "_mark_data_uri",
    "_norn_insight_auto",
    "_open",
    "_packaged_logo",
    "_packaged_mark",
    "_repo_logo",
    "_semantic_edges",
    "activity_data",
    "archive_data",
    "backup_data",
    "catalog_data",
    "derived_data",
    "dispatch",
    "graph_data",
    "health_data",
    "host_allowed",
    "injection_data",
    "log_data",
    "log_query",
    "norn_data",
    "page_data",
    "pattern_reports",
    "peer_card_data",
    "render_html",
    "run_dashboard",
    "search_data",
    "semantic_data",
    "snapshot_data",
]
