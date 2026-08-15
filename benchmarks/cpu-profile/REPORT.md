# Asgard CPU·메모리 소비 — 계측과 점검 (2026-08-14)

CPU 를 먹는 것은 훅이 아니라 **훅이 부르는 `asgard` 자식 프로세스**이고, 그 안에서 가장 큰
단일 항목은 서브커맨드 하나를 부르든 명령 트리 전체를 다시 짓는 CLI 부트스트랩이다
(`src/asgard/cli/__init__.py:30`, 실측 90~220ms 고정).

훅 코드 자신의 실행 시간은 넷 다 **1ms 미만**이다. 벽시계의 97% 이상이 `subprocess.run` 이
자식을 기다리는 시간이다. 그래서 훅 파일을 아무리 다듬어도 숫자가 안 움직인다.

## 규모 — 한 턴이 태우는 값

도구 호출 횟수별, 훅으로만 뜨는 프로세스 수와 그 CPU 시간 (Bash 를 대표 도구로):

| 도구 호출 | 프로세스 | CPU 초 |
|---:|---:|---:|
| 10 | 66 | 3.80 |
| 30 | 166 | 8.30 |
| 60 | 316 | 15.05 |

같은 하네스를 부하 34.4 인 시점에 돌린 실행은 같은 지점에서 23.11초를 냈다. 자릿수는 같고
배율이 부하를 탄다. 이벤트별로는 프롬프트 1회당 `UserPromptSubmit` 11개가 CPU 967ms,
서브에이전트 1회당 `SubagentStart` 10개가 843ms, 턴 종료마다 `Stop` 5개가 582ms 다.

도구 종류가 프로세스 수를 가른다 — `Bash` 5개, `Write`·`Edit` 5개, `Agent` 3개,
`Read`·`Grep`·`Glob` 2개. `PreToolUse` 에 `secret-guard` 가 3회, `readonly-guard` 가 2회
등록돼 있지만 matcher 가 서로 배타적이라 **중복 아니다** — 한 도구 호출에 최대 1회만 발화한다.

## 층별로 어디가 비싼가

**층 1 — 프로세스 경계.** `uv run --no-project python -c pass` 가 30ms, RSS 바닥이 약 20MB.
훅 하나가 뜰 때마다 이만큼을 먼저 낸다. 콜드와 웜의 차가 거의 없다 — 매번 새 인터프리터를
올리므로 바이트코드 캐시로 벌 몫이 원래 작다.

**층 2 — `asgard` CLI 부트스트랩.** 계측 시점의 `src/asgard/cli/__init__.py:30` 은 13개 명령
그룹을 무조건 전부 `import_module` 했다. 등록 명령 204개 + `add_typer` 22곳을 typer 가 매
호출마다 Click 객체로 다시 만들었고, `asgard --help` 만 불러도 158.8ms 였다. 지연 임포트
경로는 없었다.

> **고쳤다 (항목 2).** 지금은 `_LazyGroup` 이 부른 서브커맨드의 그룹 하나만 등록한다 —
> 그룹 모듈 13→1, 지어지는 리프 Click 객체 265→10~86. `findings-item2-cli-lazy.md` 참조.
> 아래 층 3의 수치는 **고치기 전** 값이다.

**층 3 — 서브커맨드 자체.** `memory snapshot` 148ms(그중 97ms 가 부트스트랩),
`map context` 274ms, `tutor --json` 352ms, `skills resolve` 836ms(재실행 554ms).

**층 4 — 주기 경로.** `map-activate` 는 6시간 신선도 마커가 만료되면 전체 맵 재구축을 탄다.
팀 기록의 실측치가 4.7초 — 층 3의 밀리초 값들과 자릿수가 다르다. 6시간 넘게 쉬었다 여는 세션은
첫 프롬프트에서 초 단위 지연을 겪는다.

훅 넷이 이 사슬을 탄다: `memory-activate`(SessionStart), `scope-activate`·`map-activate`
(UserPromptSubmit), `tutor-note`(Stop).

## 메모리

훅 프로세스 RSS 는 20.4~52.6MB. 임포트가 계단을 만든다:

증가값은 모두 **바로 윗 행 대비**다.

| 지점 | RSS | 증가 |
|---|---:|---:|
| `python -c pass` | 16.11MB | — |
| `import asgard` | 15.88MB | −0.23MB (오차 범위) |
| `+ asgard.memory` | 24.39MB | +8.51MB |
| `+ asgard.project_memory` | 31.91MB | +7.52MB |

`import asgard` 진입점 자체는 RSS 를 안 올린다. 올리는 것은 하위 모듈 둘이다.

`tracemalloc` 이 잡는 파이썬 할당은 훅당 1.6~2.3MB 로 관측 RSS 의 5% 미만이다. 나머지는
인터프리터와 C 확장 기동이라 파이썬 프로파일러에 안 보인다 — **훅 안에서 할당을 줄이는 최적화는
여기서 거의 효과가 없다**는 뜻이다. 지렛대는 프로세스 수와 임포트 표면이다.

상주 쪽은 CPU 가 아니라 메모리를 쥔다. `asgard memory mcp` 가 열어 둔 편집기 세션 하나당 한
쌍(uv 실행기 + python)으로 뜬다 — 계측 시점에 세션이 11개 열려 있어 **22개 프로세스가 RSS
778MB** 였다. 전부 시간당 CPU 1.2초 이하라 폴링이 아니라 요청이 올 때만 깨는 유휴 서버의
모양이다. **쌓이는 값이 아니다** — 세션이 닫히면 쌍도 사라진다(항목 6 에서 재측정: 세션 2개일
때 프로세스 4개, 132.8MB). 세션 하나가 약 66MB 를 쥔다는 것만 남는다. docker 컨테이너
둘(Hindsight 2.57GiB, postgres 78MB)은 CPU 0.3% 아래다.

디스크 상태는 작다 — `.asgard/orchestration.db` 176KB(388행), 퀘스트 로그 54개 1.23MB,
`.asgard/` 전체 4.58MB. `~/.asgard/` 9.26GiB 는 이 저장소가 아니라 이 기기의 모든 저장소가
공유하는 개인 기억 계층이라 여기를 정리해도 줄지 않는다.

## 최적화 후보

순서는 (근거 확실성 × 절감 × 위험 낮음) 이다. 이 목록은 계측 퀘스트(`cpu-profile-260814`)가
세운 것이고, 각 절의 본문은 **그때의 진단**이다. 뒤이은 구현 퀘스트(`cpu-optimize-260814`)가
2·3·4·5 를 고쳤고 1·6·7 은 고치지 않았다 — 절마다 붙은 인용문이 그 결과이며, 인용문이 본문과
어긋나면 **인용문이 현재 상태**다.

### 1. 영구 무출력 훅 — 단독으로는 고칠 자리가 없다 (7번으로 넘김)

`charter-activate` 는 이 저장소에서 **항상** 무출력이다. 원인은 `.asgard/asgard-setting-project.json`
에 `charter` 키가 없다는 것이고(최상위 키는 `agent_models`·`budget`·`lagom`·`paths`·
`project_memory`·`trinity_policy` 뿐), 훅은 그 키를 못 찾으면 `load_charter()` 가 `None` 을 내고
조용히 exit 0 한다(`.claude/hooks/charter-activate.py:39-56`). 그런데도 SessionStart·
UserPromptSubmit·SubagentStart 세 이벤트에 걸려 매번 인터프리터를 새로 올린다 — 프롬프트당 약
50ms, 서브에이전트 시작당 약 50ms.

**고치지 않았다.** 이 50ms 는 훅 안에 없다. 훅 자신의 몫은 약 15ms 이고 나머지는 프로세스 기동이라,
줄이려면 **프로세스를 안 띄우는 수밖에 없다.** 그건 배선을 지우는 일이고, 그러면 나중에 `charter`
를 설정했을 때 주입이 조용히 안 되는 함정이 생긴다 — 지금보다 나쁜 상태다. 배선을 조건부로 다시
쓰는 장치를 만드는 건 50ms 를 위해 새 동기화 규칙을 들이는 것이라 사다리 ①에 걸린다.

이 항목의 진짜 해법은 7번(디스패처 하나가 무엇을 낼지 한 프로세스 안에서 정한다)이다. 거기서
같이 없어진다. 같은 payload 에서 무출력으로 끝난 훅이 이것 말고도 있고
(`agent-activate`·`budget-guard`·`unattended-context`), 가드류가 막을 게 없을 때 조용한 건
정상이라 무출력 자체는 결함이 아니다 — 세금인 것은 **그걸 알아내려고 매번 프로세스를 띄운다**는
점이다.

### 2. CLI 부트스트랩 지연 임포트 — 절감 가장 큼, 위험 중간

`src/asgard/cli/__init__.py:30` 을 요청된 그룹만 임포트하도록 바꾼다. 근거는 90~220ms 가
어느 서브커맨드에서나 나온다는 실측이고, 훅이 이 세금을 매 턴 최소 4번 낸다. 절감 추정은
턴당 400~800ms. 위험: typer 명령 트리를 지연 구성하면 `asgard --help` 의 전체 목록과 셸
자동완성이 깨질 수 있고, 명령 등록 순서에 기대는 테스트가 있으면 같이 고쳐야 한다. 먼저
`--help` 와 자동완성만 전체 트리를 짓는 경로로 분리하는 것이 최소 변경이다.

> **고쳤다 (항목 2).** `_LazyGroup` 이 부른 서브커맨드의 그룹 하나만 등록한다 —
> `map context` −16.5%, `memory snapshot` −17.4%, `skills resolve` −17.6%. `--help` 화면
> 17개와 completion 스크립트 4종이 바이트 동일. `findings-item2-cli-lazy.md` 참조.

### 3. `budget_guard.read_ledger()` 에 상한 걸기 — 위험 중간

`src/asgard/hooks/budget_guard.py:220` 이 세션 트랜스크립트 전체를 상한 없이 재훑고,
`budget_guard.py:455` 에서 매 호출 무조건 불린다(캐시 없음). 관측된 트랜스크립트는 1.38MB 이고
세션이 길수록 자란다. 같은 종류의 파일을 `asgard_hooklib/transcript.py:123 tail_rows()` 는
이미 `deque(maxlen=TAIL)` 로 자른다 — 한 파일 종류에 두 정책이 공존한다. 위험: 예산 집계가
앞부분을 놓치면 상한 판정이 틀리므로 단순 tail 로는 안 되고, 마지막으로 읽은 바이트 오프셋을
저장하는 체크포인트로 가야 한다.

> **고쳤다 (항목 3).** 체크포인트 증분 스캔으로 바꿨다 — 이어받기 읽기가 크기와 무관하게
> 0.04ms 로 평평하고, 20MB 트랜스크립트에서 훅 프로세스가 70.4→39.4ms. 100KB 미만에서는
> 소스 컴파일이 커진 만큼 1~2ms 손해이고 손익분기가 200~300KB 다. 집계 동일성은 실물 3개
> 전 성분 대조와 시험 8건으로 고정했다. `findings-item3-budget-cap.md` 참조.

### 4. `asgard.project_memory` 임포트 지연 — 메모리 절감

`memory-activate`(52.56MB)·`scope-activate`(50.23MB)·`map-activate`(37MB대)의 RSS 가 높은
이유가 이 임포트 체인이다. 먼저 볼 지점은 `scope-activate` 가 왜 `project_memory` 까지 타는가다.
절감은 이 훅들의 바닥을 20MB대로. 위험: 임포트 시점 부작용에 기대는 코드가 있으면 깨진다.

> **고쳤다 (항목 4).** 물었던 질문의 답이 먼저 나왔다 — `scope-activate` 가 `project_memory`
> 를 타던 이유는 그 훅이 기억을 써서가 아니라 `asgard.cli` 가 매 호출 13개 그룹을 다 열어서였다.
> **항목 2 가 그 사슬을 이미 끊었고** 이 절 본문의 50.23MB 는 그 이전 값이다(현재 41.5MB, 남은 값의
> 정체는 `import typer` 25.09MB). 남은 지렛대였던 `commands/memory/__init__.py` 파사드를 PEP
> 562 로 지연시켜 임포트 RSS 31.92→18.12MB, SessionStart `memory-activate` 36.31→32.66MB.
> UserPromptSubmit 쪽은 `recall` 이 프로젝트 기억을 진짜 쓰기 때문에 안 줄었다.
> `findings-item4-import-defer.md` 참조.

### 5. tutor 의 git 팬아웃 — 절감 작음, 위험 작음

`asgard tutor --json` 의 git 호출 10회 중 8회가 `src/asgard/surface.py:207` 에서 나온다
(`tutor_teach.py:137` 은 2회). 늘어나는 축은 review 대상 파일 수가 아니라 **저장소의 미커밋
`.py` 파일 수**라 이 훅과 무관한 변수를 탄다. 위험: diff 기반 설명 품질이 떨어질 수 있다.

> **고쳤다 (항목 5).** 나무 전체를 대조한 뒤 버리던 자리가 둘이었다(`tutor/lesson.py:40`,
> `tutor_teach.py:481`). 지목 경로를 git pathspec 으로 내려보내 호출 수가 `2N+3` 에서
> **N과 무관한 2** 로 바뀌었다 — N=50 에서 103회 1,461ms → 2회 136ms. 출력은 6개 시나리오
> 전부 바이트 동일이라 설명이 얕아진 자리가 없다. `findings-item5-tutor-fanout.md` 참조.

### 6. MCP 세션 프로세스 회수 — 고칠 것이 없다 (정정)

첫 판은 22개 778MB 가 "세션을 안 닫으면 쌓이기만 하는" 값이라고 적었다. **그 추세 주장이
틀렸다.** 열린 세션이 2개일 때 재니 프로세스가 정확히 4개(쌍 2개, 132.8MB)이고 각 쌍의 조상이
그 세션 프로세스다 — 세션이 닫히면 쌍도 간다. 778MB 는 편집기 세션 11개가 동시에 열려 있던
순간의 값이다. 회수 규칙을 새로 만들 자리가 없고, 남는 사실은 열린 세션 하나가 약 66MB 를
쥔다는 것뿐이다. `findings-item67-design.md` 참조.

### 7. 훅을 한 디스패처 프로세스로 합치기 — Odin 판단 필요

가장 큰 지렛대다. 이벤트당 프로세스를 1개로 줄이면 기동 비용과 RSS 바닥이 훅 수만큼 줄어든다
(`PreToolUse` Bash 1회 = 프로세스 4개 = 순간 80MB대). 하지만 한 훅의 실패가 전체를 죽이는 단일
실패점이 생기고 fail-open 정책을 다시 설계해야 한다. 구조 변경이라 여기서 기본값을 고르지 않고
Odin 에게 남긴다.

> **설계까지 했다 (항목 7).** 훅이 세 갈래로 갈린다는 것이 요점이다. 가드는 합치면 한 실패가
> 그 이벤트의 판정을 전부 없앤다. **증거 훅** 셋(`verifier-context`·`failure-tracker`·
> `write-sentinel`)은 가드도 조언도 아닌데 죽으면 게이트가 초록인 채 판정의 증거만 사라져
> 화면에 안 뜬다 — 이 갈래는 첫 판이 놓쳤고 판정이 두 라운드에 걸쳐 채웠다. 나머지 주입 훅만
> 합치면 `UserPromptSubmit` 10→1, `SubagentStart` 7→1(thinker 는 8→1), `SessionStart` 6→1,
> `Stop` 3→1 이고 `PreToolUse`·`SubagentStop`·`PostToolUse` 는 손대지 않는다. **절감은 숫자로
> 적지 않았다** — 항목 7 은 구현하지 않아 전후를 잴 대상이 없고, 프로세스 수에 기동 바닥값을
> 곱한 값은 실측이 아니라 산수다. 이 문서가 대는 것은 없어지는 프로세스의 수까지다. 항목
> 1(charter 무출력)도 여기서 함정 없이 같이 없어진다. 오딘이 정할 세 갈래와 근거는
> `findings-item67-design.md` 에 있다.

## 이 계측이 못 잰 것

- Claude Code 가 한 이벤트의 훅들을 병렬로 띄우는지 순차로 띄우는지. 이 문서의 이벤트별 값은 CPU 시간이라 스케줄링과 무관하지만, 그것을 벽시계로 읽으면 순차 상한이다.
- `skills resolve` 의 서브커맨드 로직 460ms 중 정규식 컴파일 40.7ms 를 뺀 **나머지 약 420ms 의 정체**.
- `asgard-serve.mjs` 의 장기 누수 여부 — 127초 3표본은 가동시간의 0.015%라 판정 불가.
- 활성 퀘스트가 있을 때의 `verifier-gate` 비용. 사고로 1127ms 가 한 번 관측됐으나(무 퀘스트 103ms 대비 11배) 정식 측정이 아니다.
- `.asgard/state/gate-events.jsonl` 은 verifier 행에 세션 id 도 시각도 안 적는다(`asgard_hooklib/firing.py:100`) — 특정 사건의 건수를 이 파일로 재구성할 수 없다.
- **"훅 세금 말고 CPU 를 먹는 것은 없다"의 범위.** 이 판정은 프로세스별 누적 CPU ÷ 상주 시간에 기대므로 살아 있는 프로세스의 가동 구간 전체를 덮지만, **스냅샷 시점에 이미 끝난 프로세스**는 어느 표본에도 안 잡힌다. 짧게 떴다 사라지는 소비원이 있다면 이 계측은 못 본다.

## 정정 이력 — 판정자가 잡은 것

계측 넷 중 둘이 첫 판에서 FAIL 을 받았고, 둘 다 실제 결함이었다.

- `README.md` 의 "`.asgard/` 를 읽는 훅" 목록이 UserPromptSubmit 8개·SubagentStart 6개였다.
  하네스 자신의 `hook_read_frequency()` 는 9개·9개를 낸다 — `memory-activate`·`subagent-gate`·
  `verifier-context` 가 빠져 있었다. 손으로 옮겨 적다 생긴 결함이라, 지금은 그 함수의 실행
  결과를 그대로 싣는다.
- `findings-hotpath.md` 가 `re.compile` 1,239회·260ms 를 적었다. 실측은 236회이고 프로세스마다
  캐시가 리셋돼 다시 내는 몫은 **40.7ms** 다 — 주장의 6분의 1이라 최적화 순위가 내려갔다.
  같은 문서가 git 호출 9회를 전부 `tutor_teach.py:137` 로 돌렸는데, 실제로는 2회만 거기서 나오고
  8회는 `surface.py:207` 에서 나온다. 고칠 자리가 바뀌는 정정이다.

## 재현

```
uv run --no-project python benchmarks/cpu-profile/hook_tax.py --reps 3 --json
uv run --no-project python benchmarks/cpu-profile/hotpath.py --all --mode both --json
uv run --no-project python benchmarks/cpu-profile/memprofile.py --json
python3 benchmarks/cpu-profile/resident.py --json
```

넷 다 저장소 파일을 안 고친다. 훅은 실행되면서 `.asgard/state/` 에 자기 상태를 남기는데,
`hook_tax.py` 와 `hotpath.py` 는 종료할 때 `clear_synthetic_state()` 로 **자기 합성 세션 앞으로
남은 것만** 지운다(`hooktax-` 접두사, `cpu-profile-bench` — 둘 다 이 하네스가 만드는 이름이라
실제 세션 상태와 겹치지 않는다). `hook_tax.py` 는 자식 훅에
세션 식별 환경변수 4종을 물려주지 않는다(`hook_tax.py:44`). 이걸 안 하면 `verifier-gate` 가
합성 payload 대신 진짜 활성 퀘스트를 찾아 차단 카운터를 올린다 — 이번 계측 중 실제로 한 번
일어났고 원복했다.

측정 조건: macOS(darwin), 이 기기에서 다른 세션의 pytest 가 함께 돌던 시점. 벽시계는 그만큼
부풀고 CPU 시간은 비교적 견딘다. `%CPU` 는 쓰지 않았다 —
`resource.getrusage(RUSAGE_CHILDREN)` 차분으로 user+sys 만 뽑았다.
