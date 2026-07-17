# map: orchestrator

- `src/asgard/agent/heimdall/` — 네이티브 Trinity 오케스트레이터 패키지 (구 heimdall.py 단일 모듈의 분해)
- `src/asgard/agent/heimdall/__init__.py` — 파사드 — 구 단일 모듈 공개 표면(밑줄 이름 포함) 전부 재수출
- `src/asgard/agent/heimdall/core.py` — Heimdall 클래스 — 세션·모델·메모리 표면과 DIRECT/Trinity 라우팅, 협력자 위임 파사드
- `src/asgard/agent/heimdall/trinity.py` — TrinityRun 퀘스트 상태기계 — 역할별 턴 메서드(thinker/worker/verifier/done/baseline)
- `src/asgard/agent/heimdall/waves.py` — WaveRunner — 배정 단위 wave 병렬 실행, 티켓 lease·격리 workspace·패치 병합
- `src/asgard/agent/heimdall/dispatch.py` — DeliveryDispatch — 딜리버리 위임, freyja/thor 편대 fan-out, 시각 게이트
- `src/asgard/agent/heimdall/roles.py` — 역할 프롬프트 본문·모델 티어·스킬 리졸버·노트 주입 (순수 조회)
- `src/asgard/agent/heimdall/classify.py` — 요청 휴리스틱 분류·API 오류 판정·게이트 시그니처 (순수 함수)
- `src/asgard/agent/heimdall/planning.py` — Thinker 계획 units 파싱·wave 위상 정렬·재개 스냅샷
- `src/asgard/agent/heimdall/toolspec.py` — 네이티브 세션 툴 스키마 선언 (verdict/dispatch/편대)
- `src/asgard/agent/heimdall/journal.py` — .asgard/state 텔레메트리·write sentinel 기록 IO
- `src/asgard/agent/session.py` — AgentSession — provider 트랜스포트별 역할 세션 실행, ql/gate 서브프로세스 진입점
- `src/asgard/agent/unit_workspace.py` — UnitWorkspace — Git 기반 단위 격리 공간, capture/apply 패치 왕복
- `src/asgard/agent/repl.py` — 네이티브 REPL 표면 — Heimdall 생성·턴 루프·슬래시 커맨드
- `tests/test_architecture.py` — 5계층(foundation→providers→domain→application→interface) 의존 규칙·훅 자립 계약 강제
