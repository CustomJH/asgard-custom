# 항목 6·7 — 위험 분석과 설계 (2026-08-14)

이 둘은 구현하지 않았다. 6번은 **고칠 결함이 없다**는 것이 실측으로 드러났고, 7번은 가드 계층을
fail-open 으로 바꾸는 변경이라 스위치가 오딘의 것이다. 아래는 오딘이 한 번 읽고 결정할 수 있게
만든 근거다.

## 항목 6 — MCP 세션 프로세스는 새지 않는다 (앞선 판단 정정)

`benchmarks/cpu-profile/README.md` 는 `asgard memory mcp` 프로세스 22개가 RSS 778MB 를 쥐고
있고 "세션을 안 닫으면 쌓이기만 한다"고 적었다. **뒷부분이 틀렸다.**

지금 이 기계의 실측:

```
열려 있는 claude 세션: 2
pid=3083 ppid=2894 rss=31.0MB   ← claude --resume e3210845-…  (이 세션)
pid=3117 ppid=3083 rss=35.4MB
pid=7034 ppid=6838 rss=30.7MB   ← claude --resume dfd33182-…
pid=7060 ppid=7034 rss=35.7MB
합계: 4개 프로세스, 132.8MB
```

세션 하나에 정확히 한 쌍(uv 실행기 + python 자식)이고, 그 쌍의 조상이 세션 프로세스
(`claude --resume <세션 id>`)다. 세션이 닫히면 쌍도 사라진다 — 22개였던 것은 그때 편집기 세션이
11개 동시에 열려 있었기 때문이고, 그 세션들이 닫히면서 프로세스도 같이 갔다. 회수 규칙을 새로
만들 자리가 없다.

**남는 사실 하나**: 열린 세션 하나가 약 66MB 를 쥔다. 그건 MCP 서버 하나의 값이고 결함이 아니다.
세션을 열 개 열어 두는 사용 방식이면 660MB 가 되지만, 그건 회수 문제가 아니라 동시성 선택이다.

`README.md` 의 그 문장은 이 문서가 정정한다 — 원문은 스냅샷 시점의 관측으로는 맞았고, 추세
주장("쌓이기만 한다")만 틀렸다.

## 항목 7 — 훅 디스패처 통합

### 실측된 바닥값

프로세스 하나를 띄우는 데 드는 값 (10회 최솟값):

| 방법 | 벽시계 | CPU |
|---|---:|---:|
| `uv run --no-project python -c pass` | 17.6ms | 15.8ms |
| `python3 -c pass` | 10.5ms | 9.3ms |
| `.venv/bin/python3 -c pass` | 9.7ms | 8.6ms |

훅은 전부 첫 줄로 뜬다. **`uv run` 이 인터프리터 직접 호출보다 CPU 7.2ms 비싸다.** 이 값은
호출 하나의 값이고, 한 세션에서 몇 번 곱해지는지는 안 쟀다.

### 이벤트별 현재 값 (실측, `findings-hooktax.md`)

| 이벤트 | 등록 수 | 그중 가드 | CPU 합 |
|---|---:|---:|---:|
| `UserPromptSubmit` | 11 | 1 (`budget-guard`) | 967ms |
| `SubagentStart` | 10 | 1 (`subagent-gate`) | 843ms |
| `Stop` | 5 | 1 (`verifier-gate`) | 582ms |
| `SessionStart` | 6 | 0 | 520ms |
| `PreToolUse` | 9 | 9 (전부) | 409ms |
| `PostToolUse` | 3 | 0 | 218ms |
| `SubagentStop` | 2 | 2 | 93ms |

### 갈라야 하는 세 종류

**① 가드.** 통합의 큰 위험은 여기 있다. 지금은 훅마다 프로세스가 따로라, 하나가 죽어도 나머지
가드는 판정을 계속한다. 한 프로세스로 합치면 인터프리터 수준의 실패(임포트 오류·메모리
부족·세그폴트) 하나가 **그 이벤트의 가드를 전부** 조용히 없앤다. `secret-guard`·
`readonly-guard`·`git-guard`·`release-guard`·`subagent-gate`·`budget-guard`·`verifier-gate` 는
신뢰 경계 판정이라 Lagom 의 안전 예외에 해당하고, "막아야 할 때 안 막는" 방향의 실패는 절감과
바꿀 것이 아니다.

**② 증거 훅.** 가드는 아닌데 조언도 아닌 것이 **셋** 있다. 이 갈래는 첫 판이 아예 놓쳤고,
둘까지는 판정이 잡았고, 셋째는 그 다음 판정이 잡았다.

- `verifier-context` (SubagentStart, matcher `^asgard-verifier$`) — 판정자에게 하네스가 관측한
  실행 기록을 넣는다. 내는 것이 조언이 아니라 **판정의 입력 자체**다. 그 입력이 없던 26-08-12 에
  한 라운드가 통째로 안 판정된 채 지나갔고, 그 사건이 훅 머리말에 적혀 있다
  (`src/asgard/hooks/verifier_context.py:4-16`).
- `failure-tracker` (Stop, PostToolUse matcher `*`) — Canon 9 의 3회 카운터를 잇는다.
- `write-sentinel` (PostToolUse matcher `Write|Edit|NotebookEdit`) — 이 세션이 쓴 경로를
  `.asgard/state/writes-<sid>.json` 에 남긴다. 자기 머리말이 "verifier-gate 보강"이라고 적고
  (`.claude/hooks/write-sentinel.py:2-10`), 게이트가 Stop 에서 그걸 읽어 "기록된 경로가 지금도
  dirty 한데 퀘스트 로그가 없다"를 차단 사유로 쓴다. 기록이 없으면 `verifier-gate.py:370` 이
  조용히 `return` 한다 — 이 훅이 죽으면 게이트가 못 거는 것이 아니라 **안 걸린다**.

셋 다 디스패처 안에서 조용히 죽으면 **게이트는 초록인 채 판정의 증거만 사라진다.** 가드처럼
"막히지 않는" 실패가 아니라 "판정이 얕아지는" 실패라 화면에 아무것도 안 뜬다. 가드와 같은 칸에
둔다.

### 전수 명단

`.claude/settings.json` 에 배선된 훅 24종이 세 갈래로 정확히 나뉘고 남는 것이 없다. 다음에 이
문서를 읽는 사람이 다시 세지 않도록 그대로 싣는다.

- **① 가드 8** — `budget-guard` `craft-gate` `git-guard` `readonly-guard` `release-guard`
  `secret-guard` `subagent-gate` `verifier-gate`
- **② 증거 3** — `failure-tracker` `verifier-context` `write-sentinel`
- **③ 주입 13** — `agent-activate` `charter-activate` `dispatch-context` `lagom-activate`
  `lagom-subagent` `lagom-tracker` `manual-activate` `map-activate` `memory-activate`
  `scope-activate` `siege-inbox` `tutor-note` `unattended-context`

이 명단은 배선을 읽어 만든 것이고, 훅이 늘거나 줄면 낡는다. 다시 세는 법:
`.claude/settings.json` 의 모든 이벤트에서 `hooks/<이름>.py` 를 뽑아 위 세 집합과 대조하면 된다.

**③ 주입 훅.** `*-activate` 계열, `siege-inbox`, `lagom-tracker`, `unattended-context`,
`tutor-note`, `lagom-subagent`, `dispatch-context`. 이미 전부 fail-open 으로 설계돼 있고(문제가
생기면 조용히 통과), 내는 것이 조언성 문맥이라 실패해도 판정이 뒤집히지 않는다. 여기를 합치는
데는 새 위험이 없다.

### 그래서 권고 — ③만 합친다

`PreToolUse` 와 `SubagentStop` 은 손대지 않는다(가드뿐이다). 나머지 네 이벤트에서 ①과 ②를
제자리에 두고 ③만 디스패처 하나로 묶는다:

**합칠 수는 등록 수가 아니라 실제로 뜨는 수다** — matcher 가 걸린 훅은 해당 서브에이전트에서만
뜬다. 아래는 그것까지 센 값이다.

| 이벤트 | 없어지는 프로세스 | 제자리에 남는 것 |
|---|---:|---|
| `UserPromptSubmit` | 10 → 1 | `budget-guard` |
| `SubagentStart` (일반) | 7 → 1 | `subagent-gate` (thinker·worker·verifier 한정) |
| `SubagentStart` (thinker) | 8 → 1 | 위 + `memory-activate` 가 여기서만 뜬다 |
| `SessionStart` | 6 → 1 | — |
| `Stop` | 3 → 1 | `verifier-gate`, `failure-tracker` |

`PostToolUse` 에는 행이 없다. 등록 셋 중 둘이 증거 훅(`failure-tracker`·`write-sentinel`)이고
남는 주입 훅이 `tutor-note` 하나뿐이라 합칠 것이 없다.

**절감을 숫자로 적지 않는다.** 이 퀘스트가 개봉하며 고정한 기준이 "재지 않은 절감은 적지
않는다"인데, 항목 7 은 구현하지 않았으므로 전후를 잴 대상 자체가 없다. 프로세스 수와 바닥값을
곱해 만든 값은 실측이 아니라 산수이고, 방향조차 자명하지 않다 — 디스패처가 여러 훅 본문을 한
프로세스에서 돌면 임포트가 공유돼 실제 절감이 산수보다 클 수도 있고, 반대로 한 프로세스가 모든
훅의 임포트를 다 지면 RSS 는 합쳐진 만큼 오른다. **재 봐야 안다.** 위 표가 이 문서가 댈 수 있는
전부다 — 없어지는 프로세스의 수.

RSS 쪽도 같다: 지금 한 이벤트의 훅들이 동시에 뜨면 각 20MB 바닥이 겹쳐 순간 상주가 훅 수만큼이고
(`PreToolUse` Bash 1회 = 4개 = 80MB대, 실측), 통합하면 그 바닥이 한 번만 든다. 통합 프로세스가
실제로 얼마를 지는지는 안 쟀다.

### 항목 1 이 여기서 같이 없어진다

`charter-activate` 는 이 저장소에서 영구 무출력인데(`charter` 설정 키 부재) 세 이벤트에 걸려
매번 뜬다. 배선을 지우면 나중에 charter 를 설정했을 때 조용히 주입이 안 되는 함정이 생겨
단독으로는 못 고쳤다. 디스패처는 **한 프로세스 안에서** 전제를 확인하고 낼 것이 없으면 그냥
안 내면 되므로, 그 프로세스가 함정 없이 없어진다. 같은 형태로
`agent-activate`·`unattended-context` 의 무출력 회차도 프로세스를 안 띄운다.

### 결정이 필요한 것 — 오딘의 세 갈래

1. **범위.** ③만 합치는 위 권고로 갈 것인가, ①(가드)까지 포함할 것인가. 가드를 포함하면 절감이
   `PreToolUse` 만큼 더 커지지만(도구 호출당 4~5 프로세스), 위 실패 형상을 받아들이는 결정이다.
2. **② 증거 훅 셋을 어느 칸에 둘 것인가.** 이 문서는 가드와 같은 칸에 두는 쪽을 기본값으로
   골랐다 — 판정이 얕아지는 실패는 화면에 안 뜨므로 되돌리기가 가장 어렵다는 이유다.

   반대쪽에서 열리는 자리를 전부 적는다. 셋을 ③에 넣으면 프로세스가 이만큼 더 없어진다:

   | 자리 | 바뀌는 것 | 얼마나 자주 |
   |---|---|---|
   | `PostToolUse` (Write·Edit·NotebookEdit) | `failure-tracker`+`write-sentinel`+`tutor-note` 3 → 1 | 쓰기 도구 호출마다 |
   | `Stop` | 4 → 1 | 턴마다 |
   | `SubagentStart` (판정자 배차만) | 8 → 1 | 판정자를 부를 때마다 |

   **셋 중 `PostToolUse` 가 가장 자주 붙는다** — 쓰기 도구 호출마다이기 때문이다. 세 자리의
   빈도가 서로 달라 하나의 수로 합쳐지지 않고, 세션마다 쓰기 호출 수와 판정자 호출 수가 다르므로
   합쳤을 때의 값은 그 세션을 재 봐야 안다. 여기서도 절감을 숫자로 적지 않는 이유가 같다.

   `PostToolUse` 가 기본값에서 권고 표에 행이 없는 이유는 그 경우 합칠 주입 훅이 `tutor-note`
   하나뿐이기 때문이다. 증거 훅 둘이 ③으로 가야 비로소 합칠 것이 생긴다.

   교환 조건은 이렇다: 위 세 자리의 프로세스를 얻는 대신, 디스패처 하나가 죽을 때 판정 게이트가
   **초록인 채** 증거만 사라지는 창을 연다. 그 창은 화면에 아무것도 안 띄우므로 사후에 알아채기
   어렵다. 저울에 올리는 것은 오딘의 판단이다.
3. **디스패처 실패 시 정책.** ③만 합치면 fail-open 이 옳다(지금과 같다). ①이나 ②를 포함하면
   fail-closed(막고 사람에게 묻기)로 가야 하는데, 그건 훅 하나가 깨질 때 세션이 멈춘다는 뜻이다.

### 곁다리 — `uv run` 자체

위 표의 7ms 차이는 통합과 독립이다. 훅을 `.venv/bin/python3` 로 직접 부르면 호출마다 그만큼
빠지지만, `uv run --no-project` 는 인터프리터를 이식성 있게 고르는 자리라 경로를 박으면 다른
기계에서 깨진다. 이 저장소의 설치 경로가 항상 같은 자리에 venv 를 만드는지 확인한 뒤에야
검토할 수 있는 항목이고, 이번에 확인하지 않았다.

## 이 문서가 안 잰 것

- **절감 그 자체.** 디스패처를 안 만들었으니 전후를 잴 대상이 없다. 이 문서는 없어지는 프로세스의
  수까지만 대고, 그것이 몇 ms 인지는 만든 뒤에 재야 한다.
- 통합 프로세스의 RSS. 훅 본문들의 임포트가 합쳐지면 한 프로세스가 지는 값이 커진다 — 버는 쪽이
  프로세스 수에서 나오고 잃는 쪽이 임포트에서 나오므로 방향이 자명하지 않다.
- Claude Code 가 한 이벤트의 훅들을 병렬로 띄우는지 순차인지. 병렬이면 프로세스를 줄여도 벽시계는
  덜 줄고 CPU 만 줄어든다.
- 세션을 열 개 열어 두는 사용에서 MCP 660MB 가 실제로 문제가 되는지 — 기계의 메모리 여유를 안 쟀다.
