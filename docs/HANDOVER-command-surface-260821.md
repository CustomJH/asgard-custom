# 인수인계 — 명령 표면 점검과 수리 (2026-08-21)

## 지금 상태

퀘스트 둘이 PASS 로 닫혔고 **40개 파일이 커밋 전**이다 (이 문서 포함). 게이트 `just check` 는 종료 코드 0,
6,213개 통과. 오딘이 커밋을 지시하지 않아 하지 않았다.

- `command-surface-check-260821` — 점검 (물리 diff 0). PASS 후 닫힘.
- `command-surface-fixes-260821` — 결함 열둘 수리. PASS 후 닫힘.
- `policy-merge-and-async-gate-260821` — 그 수리가 실제로 닿게 하는 후속 셋. PASS 후 닫힘.

## 무엇을 잰 것인가

asgard CLI 의 명령 경로 298개(그룹 25 + 리프 273)를 설치본 v0.10.19 와 소스본 v0.10.22
양쪽에서 돌렸다. 별칭 60개(`yggdrasil`=`memory` 43, `einherjar`=`agent` 16, `upgrade`=`update` 1)를
빼면 실제 명령은 **213개**다. 단위 일곱으로 나눠 **1,011행**을 계측했고 트레이스백·타임아웃·
멈춤 0건이었다. 계측기와 원자료는 세션 스크래치패드에 있고 세션이 끝나면 사라진다.

**명령 자체는 안 깨져 있었다. 깨진 것은 "괜찮은지 판정하는 명령"들이었다.**

## 고친 것 열다섯

판정하는 명령 셋:

1. `doctor` 가 배포된 훅이 **더 새 판**일 때도 "판본 뒤처짐"이라 적고 `asgard sync --here` 를
   권했다 — 되감는 조언이다. 이제 `sync` 가 자기 판을 `.asgard/state/scaffold.json` 에 남기고
   `wiring._engine_is_older` 가 그 도장으로 방향을 가른다. 도장이 없으면 방향을 주장하지 않고
   문구도 "이 판의 템플릿과 다름"으로 바뀌었다.
2. `wiring.py` 가 안내 경로에서 `hooks/` 마디를 빠뜨려 `.claude/asgard_hooklib/baseline.py`
   라는 없는 경로를 찍었다.
3. `k6 doctor` 가 도커 데몬이 죽었는데 `ready pass` · 종료 코드 0 을 냈다. `runner_version` 이
   `returncode` 를 안 보고 실패 프로브의 stderr 를 판 문자열로 돌려줬기 때문이다. 같은 값이
   `report.json` 의 `k6_version` 으로 새겨져 `k6_gate` 비교 축까지 흘렀다. 덧붙여
   `resolve_runner` 가 바이너리 존재로만 도커를 골라 native k6 로 폴백하지 않았다.
4. `map check` 와 `doctor` 의 `codebase map` 행이 `GRAPH.md` 드리프트를 못 봤고, 권고인
   `map update` 는 그래프를 안 건드려서 시키는 대로 해도 화면에서만 사라졌다. 고치는 문은
   `map scan` 하나다. 아직 안 그린 그래프는 드리프트로 안 센다(fog-of-war).

표면 결함 넷: `trinity` 가 맨몸에서 날 JSON 을 뱉고 `--json` 을 무시하던 것, `siege` 목록이
장부 110개 중 20개만 보여 주고 잘렸다는 표시도 손잡이도 없던 것(`--limit` 신설, `--json` 은
배열 형상 유지하며 전수), `skills resolve --agent` 도움말이 허용값 8개 중 5개만 적던 것
(`skill_scope.RESOLVE_AGENTS` 로 어휘 단일화), `budget` 이 부른 세션이 아니라 mtime 최댓값
트랜스크립트를 재던 것(`--session` 신설, 추측일 때는 "가장 최근 세션"이라 적고 형제 세션 수를
경고).

메모리 둘: `project-recall` 이 backend 관련도 점수를 버려 맞는 질의와 무의미한 질의가 같은
출력을 내던 것, `memory query` 도움말이 "plain text search, no model" 인데 기본 설정에서
로컬 임베더가 도는 것.

하네스 여섯: 티켓 기본 lease 300초 → 1800초(실측 구간 486~804초), `ticket-recover` 에 유예
300초와 `--older-than`·`--unit`, 퀘스트 로그 `subtask` 상한 1000자 → 8000자에 절단 표시,
`verifier-gate` 가 배정 단위가 도는 턴과 판정이 날아오는 중인 턴을 안 막게, `load_policy` 의
최상위 얕은 병합을 재귀로, `doctor` 가 설정에 얼어붙은 기본값을 이름 대게.

## 할 일 넷

1. **커밋.** 40개 파일이 커밋 전이다 — 수정 37 + 미추적 3, `docs/` 아래 이 문서 포함.
2. **이 저장소의 `lease_seconds: 300` 을 지울지 결정.** 설정 파일은 제어 표면이라 손으로 안
   고쳤다. 그대로 두면 병렬 단위가 매번 한 번씩 헛되이 만료된다. `asgard doctor` 의
   `trinity policy` 행이 지금 이 저장소에서 12개를 이름 댄다 — 그 키들은 코드 기본값을 베낀
   것이고 진짜 선택은 `baseline_checks`·`baseline_timeout` 둘뿐이다.
3. **안 끝난 판정자 배차 37건** (`ready` 35 · `outcome_unknown` 2, 35개 퀘스트, 가장 오래된 것 15.7일).
   `outcome_unknown` 은 실패가 아니다 — 워커가 보고를 안 남겼을 뿐 프로세스와 파일은 살아 있을 수 있다.
   그래서 그 35개 퀘스트에서는 `verifier_gate._verdict_in_flight` 가 "판정이 오는 중"이 아니라
   "판정자를 부른 적 있다"로 읽혀 `no-verdict` 차단이 사실상 꺼진다. 배차를 언제 settle 할지가
   별개 문제로 남아 있다.
4. **`tests/test_doctor_shape.py` 의 `_guarded_by_ok` 술어 조이기.** `"ok" not in ast.dump(...)`
   가 글자 부분일치라 `hook` 같은 이름이 우연히 통과할 창이 있다. 지금 그 파일에서는 재현되지
   않는다(207행을 감싸는 `if` 가 하나뿐). 고치면 방금 PASS 받은 diff 가 달라져 재판정이 필요해
   손대지 않았다.

## 이 세션이 밟은 함정 다섯 — 되풀이하지 마라

**① 문자 수를 바이트라고 적었다.** 파일을 `utf-8` 로 디코드한 뒤 `len(str)` 로 잰 값을 `B` 로
옮겨 적었다. 한글이 3바이트라 42,395자 = 51,021바이트다. 크기를 말할 때는
`git cat-file -s` 나 `wc -c` 로 재라.

**② 잰 대상이 계약과 달랐다.** lease 가 덮는 구간은 티켓 `claim`→`finish` 인데 서브에이전트가
자기 안에서 돈 시간(`duration_ms`)을 적었다. 후자가 항상 짧아서 lease 를 그 값으로 잡으면
매번 모자란다. 실측: 배차 소요 485.7~803.3초, 티켓 구간 486~804초.

**③ 주석에 적은 근거가 사실이 아니었다.** "정책의 dict 값은 전부 평평한 표"라고 써 놓고
한 겹 병합을 정당화했는데, `roles` 와 `budget_priors` 가 두 겹이었다. 근거를 적을 때는 그
근거 자체를 재라.

**④ 시험 둘이 초록인 채로 아무것도 안 쟀다.** AST 시험이 `ch["fix"]`(`ast.Subscript`)를
`ast.Attribute` 로 찾아 0건을 매칭했고, 빈 제너레이터의 `any()` 는 False 라 `assertFalse` 가
무조건 통과했다. 두 겹 시험은 `if len(inner) < 2: continue` 에 `budget_priors.trivial` 이
걸려 조용히 빠졌다. **새 시험은 반드시 변이로 재라** — 고치기 전으로 되돌려 빨개지는지.
매칭 기반 시험은 매칭 수가 0 이면 실패하게 써라.

**⑤ 셸 반복문이 계기를 망쳤다.** `for tag in ...; do printf "$(git show ... | wc -c)"; done` 이
3,547 을 냈고 같은 명령을 반복문 밖에서 돌리니 47,530 이었다. 숫자가 이상하면 계기를 먼저
의심하고 두 가지 방법으로 교차 확인해라(`wc -c` 와 `git cat-file -s`).

## 알아 둘 것 셋

- **가드는 연산이 아니라 글자를 본다.** 명령문에 `.asgard/state` 같은 문자열이 있으면 읽기여도
  `readonly-guard` 가 막는다. 패치 스크립트를 스크래치패드 파일로 두고 실행하면 지나간다.
- **파이프가 종료 코드를 가린다.** `asgard doctor | head; echo $?` 는 `head` 의 코드다. `doctor`
  는 경고가 있으면 2 를 내고 그것이 정상이다(`commands/doctor/__init__.py` 의 0/1/2 정의).
- **배포본 훅은 소스와 따로 산다.** `src/asgard/hooks/` 를 고쳤으면 `.venv/bin/asgard sync --here`
  로 `.claude/`·`.codex/` 에 반영해야 실제로 도는 것이 바뀐다. 설치본으로 sync 하면 그 판이
  깔린다.

## 검증

`just check` (fmt-check → lint → typecheck → test). 이 저장소의 계약 명령이다. 첫 실행에서
`tests/test_studio_terminal.py` 의 PTY 시험 하나가 흔들릴 수 있다 — 단독 실행과 재실행에서
통과하고 이번 변경과 닿는 경로가 없다.
