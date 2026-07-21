# Codebase Map — .asgard/map/

팀 공유(git 추적) 코드베이스 지도. `PROJECT.md`는 `asgard map update`가 현재 디스크 증거로
그리는 프로젝트 방향·랜드마크다. 심층 지식은 영역별 `<area>.md` (예: `cli.md`, `frontend.md`)에
기록하고, 영역 파일은 에이전트가 탐사하며 만든다.

## 지도 문법 (위반 시 doctor 가 경고)

1. **엔트리 문법 고정** — ``- `경로` — 1줄 역할``. 그 외 서술 금지.
2. **지도 ≠ 이력** — 날짜·사건·변경 이력 서술 금지. 이력은 퀘스트 로그(`.asgard/quest/`)와 git 몫.
3. **실재만 기재** — 디스크에 존재하는 파일만. 만들 예정인 파일의 선기재 금지 (ghost 방지).
4. **소유권 분리** — `PROJECT.md`는 Asgard 전용(수동 편집 금지), 영역 지도는 사람/에이전트 전용(Asgard 덮어쓰기 금지).
5. **fog-of-war** — 심층 영역 지도는 탐사한 영역만 증분으로 채운다. 전체 재작성·일괄 생성 금지.
6. **읽기 우선, 신뢰는 검증** — 탐색 전 지도를 먼저 읽되, 계획이 딛는 경로는 Read 로 재확인.
7. **크기·주입 안전** — 영역 파일은 8 KiB 이하. 문법 밖 산문·프롬프트 제어 문구는 자동 컨텍스트에서 제외.

## 검증

`asgard map check`와 `asgard doctor`가 managed drift·유령 엔트리·문법·크기 위반을 탐지한다.
메인 요청·서브에이전트 시작과 Verifier hash 계산 전에 `PROJECT.md`를 자동 갱신하므로 지도 변경도
같은 PASS에 포함된다. `asgard map context --query "<task>"`로 실제 제한 주입 내용을 확인할 수 있다.

## 영역 파일 예시

```markdown
# map: cli

- `src/app/cli.py` — CLI 엔트리, 서브커맨드 라우팅
- `src/app/commands/` — 서브커맨드 구현 (파일당 1커맨드)
```
