"""세스룸니르 (Sessrúmnir) — 프레이야 스튜디오 대시보드 · 스튜디오 표면의 첫 조각 (CUS-258/261/263).

`asgard studio` 가 127.0.0.1 에 표준 라이브러리 http.server 만으로 일회성 프로세스를
띄운다(신규 의존성 0, Ctrl-C 종료). memory dashboard(위그드라실 관문 콘솔)와는 별개의
독립 표면 — 별도 명령·별도 모듈이며 그것의 확장이 아니다 (CUS-263, 사용자 정정 26-07-18).

계약:
  · 정본 = ~/.asgard/studio/projects/<slug>/ — 아티팩트 파일 + project.json 메타.
    ASGARD_STUDIO_DIR 로 재지정 가능 (테스트 격리).
  · Host 가드(루프백 전용·DNS 리바인딩 방어)는 memory dashboard 와 같은 관례를 스튜디오
    소유 구현으로 적용. 아티팩트 응답은 CSP sandbox 로 격리(생성물 = 신뢰 경계 밖).
  · 프론트엔드 = assets/studio_dashboard.html (자기완결 단일 HTML, 외부 CDN 0) —
    ref/docs/studio-dashboard-mockup.html 편입본. 패널 실데이터 바인딩·내보내기는
    CUS-263 잔여, 생성 파이프라인(new/refine)은 CUS-261 소유.
  · API: /api/snapshot(프로젝트 목록)·/api/project?slug=(상세)·/artifact?slug=&path=
    (realpath 경계 검사 후 서빙) — 전부 GET, 쓰기 엔드포인트 없음.
"""

from __future__ import annotations

from .data import (
    BOOK,
    DEFAULT_ENGINE,
    ENGINES,
    META,
    PROJECTS,
    RUN_LOG,
    RUNS,
    SETTINGS,
    STATE,
    STUDIO_ENV,
    artifact_path,
    engine,
    ensure_home,
    project_data,
    projects_data,
    read_run_log,
    read_runs,
    read_settings,
    read_state,
    slug_ok,
    snapshot_data,
    studio_dir,
    template_file,
    template_meta,
    templates_data,
)
from .ops import run_list, run_path
from .server import (
    _LOOPBACK_HOSTS,
    _PAGE,
    _bind,
    _Handler,
    _open,
    dispatch,
    dispatch_post,
    host_allowed,
    origin_allowed,
    render_html,
    run_dashboard,
)

__all__ = [
    "BOOK",
    "DEFAULT_ENGINE",
    "ENGINES",
    "META",
    "PROJECTS",
    "RUNS",
    "RUN_LOG",
    "SETTINGS",
    "STATE",
    "STUDIO_ENV",
    "engine",
    "read_settings",
    "template_file",
    "template_meta",
    "templates_data",
    "_LOOPBACK_HOSTS",
    "_PAGE",
    "_Handler",
    "_bind",
    "_open",
    "artifact_path",
    "dispatch",
    "dispatch_post",
    "ensure_home",
    "host_allowed",
    "origin_allowed",
    "project_data",
    "projects_data",
    "read_run_log",
    "read_runs",
    "read_state",
    "render_html",
    "run_dashboard",
    "run_list",
    "run_path",
    "slug_ok",
    "snapshot_data",
    "studio_dir",
]
