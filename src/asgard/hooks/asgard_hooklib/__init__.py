"""훅이 함께 지고 다니는 공용 라이브러리 — 훅 옆에 그대로 깔린다.

**왜 이 패키지가 있는가.** 훅은 `.claude/hooks/`(또는 `.cursor/`·`.codex/`)로 복사돼 사용자
저장소에서 도는 자립 스크립트다. 그 계약 때문에 한동안 "한 훅 = 한 파일"이었고, 판정 기반이
필요한 훅이 셋이 되자 같은 코드가 세 벌로 복사됐다. 26-08-06 실측: quest-log ↔ verifier-gate
공유 정의 49개 중 9개가 이미 의미까지 갈라져 있었고 (`trivial_evidence`·`pass_evidence`·
`unmet_contracts`·`current_tree_ref`·`ignored_state`·`unbound_artifacts`·`artifact_scope`·
`inspection_evidence`·`git`), 그 파일들의 주석은 그때도 "동일 유지 (단일 출처 원칙)"이라고
적고 있었다. 주석은 사본을 묶어 두지 못한다.

**어떻게 자립을 유지하는가.** 이 패키지는 훅과 **같은 폴더에** 함께 깔린다. 스크립트로 실행될
때 `sys.path[0]` 이 이미 그 폴더이므로 `import asgard_hooklib` 이 배포본에서 그대로 선다 —
`asgard` 를 임포트하지 않으므로 자립 계약(test_hooks_are_self_contained)은 그대로다. 저장소
안에서 `asgard.hooks.quest_log` 로 임포트될 때를 위해 각 훅이 자기 폴더를 `sys.path` 에 한 줄로
얹는다. 그래서 두 얼굴이 같은 코드를 집는다.

**모듈 지도** (아래가 위를 모른다 — 이 순서가 곧 임포트 방향이다):

- `paths`      파일·git 원시 연산. 판정 없음, 표준 라이브러리만.
- `integrity`  이벤트 해시 연결과 정체성.
- `evidence`   실행된 명령이 증거인가 (trivial·inspection·pass).
- `scope`      귀속 범위 — 무시 파일·심링크·결속 불가 산출물.
- `contracts`  criteria 의 verify/artifacts 계약 파싱과 충족 판정.
- `policy`     기본 정책과 검증 강도.
- `tree`       워킹트리를 트리 객체로 떠서 내는 물리 해시.
- `runners`    베이스라인 체크 감지 (무엇이 실제로 도는 명령인가).
- `baseline`   그 체크의 실행.
- `session`    세션 식별과 ACTIVE 포인터.
- `ledger`     퀘스트 로그의 스키마·정규화·append·재생.
- `summary`    로그 상태 관측 하나 + 정리 + 라우팅 prior.
- `transition` 전이 함수 — 다음 역할을 코드가 정한다.
- `tickets`    병렬 단위의 소유권과 lease.

재수출은 하지 않는다. 소비처가 `asgard_hooklib.evidence.pass_evidence` 라고 적으면 그 이름이
어디 사는지가 호출부에 남고, 파사드가 이름을 모아 주면 그 자리가 사라진다 — 이 저장소에서
실제로 오패치를 조용히 통과시킨 형상이다.
"""
