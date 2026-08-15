# 메모리 실측 — Asgard 훅·프로세스 (u3-memory, cpu-profile-260814)

측정 도구: `benchmarks/cpu-profile/memprofile.py`. 머신: macOS aarch64, Python 3.14.5, `.claude/settings.json`
등록 커맨드를 그대로 파싱해 훅 43개 조합(파일×argv×이벤트, 중복 제거)을 재현했다. RSS는
`RUSAGE_CHILDREN.ru_maxrss`(macOS는 바이트 단위)를 훅마다 새 래퍼 프로세스에서 재 오염을 막았고,
할당은 `tracemalloc` + `runpy.run_path` 인프로세스로 훅 본문만 골라 쟀다.

## 핵심 숫자 5줄

- 훅 43개 조합 중 최댓값 `memory-activate.py`(UserPromptSubmit) 52.56MB, 최솟값 `charter-activate.py`(SubagentStart) 20.39MB — 격차 32MB.
- 임포트 계단: `python -c pass` 16.11MB → `+asgard.memory` 24.39MB(+8.28MB) → `+asgard.project_memory` 31.91MB(+7.52MB) → `+asgard.hooks.quest_log` 25.25MB(project_memory 대비 -6.66MB, 별도 프로세스라 비교치).
- `tracemalloc` 상위 지점은 훅 6종 전부 `<frozen importlib._bootstrap_external>:511`(모듈 바이트코드 로드)이 1위 — 훅 자체 로직이 아니라 매 프로세스 재기동의 임포트 기계 비용.
- 상주 `asgard-serve.mjs`(PID 44444, 9일 22시간 가동) RSS 3표본 46688KB 고정 — 127초 구간에서 증가 없음, 표본 3개로 장기 누수는 판정 불가.
- 퀘스트 로그 전량 파싱이 3개 호출부에 중복 구현, 현재 최대 파일 176KB(가장 큰 퀘스트 로그 기준).

## 1. 훅별 최대 RSS (RUSAGE_CHILDREN, macOS 바이트→MB)

상위 10 / 하위 5, 전체 43건은 `uv run python benchmarks/cpu-profile/memprofile.py rss --json` 재현.

| 순위 | 훅 (argv) (이벤트) | RSS(MB) |
|---|---|---|
| 1 | memory-activate.py (UserPromptSubmit) | 52.56 |
| 2 | scope-activate.py (UserPromptSubmit) | 50.23 |
| 3 | memory-activate.py (SessionStart) | 39.53 |
| 4 | map-activate.py (SessionStart) | 37.61 |
| 5 | map-activate.py (UserPromptSubmit) | 37.53 |
| 6 | map-activate.py (SubagentStart) | 37.34 |
| 7 | tutor-note.py claude brief (UserPromptSubmit) | 33.98 |
| 8 | verifier-gate.py (Stop) | 27.73 |
| 9 | verifier-context.py (SubagentStart) | 24.81 |
| 10 | subagent-gate.py (SubagentStart / SubagentStop / PreToolUse) | 24.44–24.47 |
| … | … | … |
| 39 | charter-activate.py (SessionStart) | 20.45 |
| 40 | manual-activate.py (SessionStart) | 20.44 |
| 41 | dispatch-context.py (SubagentStart) | 20.44 |
| 42 | lagom-activate.py (SessionStart) | 20.41 |
| 43 | charter-activate.py (SubagentStart) | 20.39 |

바닥값(20.4MB 부근)은 `uv run --no-project python`이 인터프리터를 새로 올리는 고정비다 — 43건 중
32건이 20~24MB 구간에 몰려 있고, 상위 8건만 `asgard.memory`/`asgard.project_memory` 임포트 체인을
타면서 30~53MB로 벌어진다. `git-guard.py`(23.2MB)·`budget-guard.py`(22.4~22.6MB)는 `transcript.py`의
`tail_rows`(deque maxlen)만 쓰거나 아예 안 써서 중간값에 머문다.

## 2. 임포트 표면 RSS 계단 (RUSAGE_SELF, 단계마다 새 인터프리터)

| 단계 | RSS(MB) | 증분 |
|---|---|---|
| `python -c pass` | 16.11 | — |
| `import asgard` | 15.88 | -0.23 (오차 범위) |
| `import asgard.memory` | 24.39 | +8.51 |
| `import asgard.project_memory` | 31.91 | +7.52 |
| `import asgard.hooks.quest_log` | 25.25 | (project_memory 안 거치는 별도 경로, project_memory 대비 -6.66) |
| `readonly-guard.py` 실행 완료 (RUSAGE_CHILDREN) | 21.42 | — |

`import asgard` 자체는 RSS를 거의 안 올린다(진입점 모듈이 가볍다는 씨앗의 importtime 6.1ms 관측과 일치).
RSS를 올리는 건 하위 모듈 `asgard.memory`(+8.5MB)와 `asgard.project_memory`(+7.5MB) 두 임포트다 —
1번 표의 상위 8개 훅이 30MB를 넘는 것과 정확히 이 두 임포트 체인을 타는지 여부가 겹친다.

## 3. tracemalloc 상위 할당 지점 (인프로세스, 훅 본문만)

`memory-activate.py`·`scope-activate.py`·`map-activate.py`·`tutor-note.py`·`verifier-gate.py` 5종을
쟀다. 다섯 모두 1~2위가 동일하다:

1. `<frozen importlib._bootstrap_external>:511` — 787~1226KB (모듈 바이트코드 컴파일/캐시)
2. `<frozen runpy>:266` — 294~363KB (`runpy.run_path` 자체의 실행 프레임)

훅 로직이 직접 만드는 객체(3위 이하)는 30~40KB 수준(`abc`·`re`·`json.decoder`·`enum`)으로, 추적된
총합(`total_traced_bytes`)이 1.6~2.3MB — 실측 RSS(20~53MB)의 5% 미만이다. **차이의 정체**:
`tracemalloc.start()`는 인터프리터가 이미 뜬 뒤(코드 실행 시작 지점)에 걸리므로, 인터프리터
초기화·C 확장 모듈 로드·`uv` 자체의 메모리는 애초에 추적 대상이 아니다. 즉 RSS 20MB 바닥값의
대부분은 파이썬 레벨 객체가 아니라 **인터프리터 기동 자체**이고, 30MB를 넘는 구간은 순수하게
"어떤 임포트를 타는가"의 문제다 — 훅 본문이 만드는 데이터 구조는 어느 훅에서도 지배항이 아니다.

## 4. 상주 프로세스 (`asgard-serve.mjs`, PID 44444)

| 표본 | 시각(epoch) | RSS(KB) | 가동 |
|---|---|---|---|
| 1 | 1786639393 | 46688 | 9일 22:17:49 |
| 2 | 1786639453 | 46688 | 9일 22:18:49 |
| 3 | 1786639520 | 46688 | 9일 22:19:56 |

127초 구간에서 RSS가 바이트 단위로 완전히 고정 — 이 구간엔 증가 추세가 없다. 다만 표본 3개·127초는
9일 가동 전체의 0.015%도 안 되는 창이라, 느린 누수(주 단위로 수 MB씩)가 있는지는 이 측정으로는
**판정 불가** — 프로세스를 재시작하지 않고 잴 수 있는 범위(Canon 3)의 상한이다.

## 5. 런타임 상태의 전체 로드 경로

퀘스트 로그·트랜스크립트·프로젝트 문서 인덱스 세 갈래를 소스에서 확인했다(경로는 저장소 루트
기준 상대경로 — 훅 코드는 `src/asgard/hooks/` 아래, 프로젝트 메모리는 `src/asgard/project_memory/` 아래).

| 위치 | 패턴 | 현재 파일 크기 | 비고 |
|---|---|---|---|
| `hooks/asgard_hooklib/ledger.py:74` `load_events()` | 퀘스트 로그(`.jsonl`)를 줄마다 `json.loads`해 `list[dict]`로 전량 적재 | 최대 176KB (가장 큰 퀘스트 로그 파일 기준) | `quest-log.py`의 `open`/`append`/`state`/`next`/`close` 전부가 매 호출마다 이 경로를 다시 연다 |
| `hooks/memory_activate.py:168-169` | 같은 전량-적재 패턴을 별도로 재구현(`[json.loads(line) for line in handle if line.strip()]`) | 위와 동일 | LAST 퀘스트 포인터 확인용 — `ledger.load_events()`와 공유하지 않는 중복 구현 |
| `hooks/verifier_context.py:102-117` `quest_events()` | 같은 패턴 세 번째 재구현 | 위와 동일 | 판정 구간 앵커 계산용 |
| `hooks/budget_guard.py:220-260` `read_ledger()` | 세션 트랜스크립트(`.jsonl`)를 줄 단위로 스트리밍(리스트로 안 쌓음)하되 **매 PreToolUse/UserPromptSubmit 호출마다 파일 처음부터 끝까지 재스캔** — 상한 없음 | 서브에이전트 트랜스크립트 실측 최대 1.38MB(이번 세션 기록 디렉터리) | 메모리 피크보다 **누적 I/O·CPU**가 문제 — 세션이 길어질수록 매 호출 비용이 O(그 시점 파일 크기)로 커진다(세션 전체로는 대략 O(n²)) |
| `hooks/asgard_hooklib/transcript.py:123-143` `tail_rows()` | 대조군 — `collections.deque(handle, maxlen=TAIL)`로 꼬리만 유지, 전체 라인은 순회하되 메모리는 상수 | — | `read_ledger()`와 달리 이미 상한이 있다 — 같은 파일을 두 가지 정책으로 읽는 두 함수가 공존 |
| `project_memory/documents.py:343-368` `_candidates()` | `total <= MAX_SCAN_CHUNKS(4000)`일 때만 문서 본문(`body`) 전 컬럼을 조건 없이 `fetchall()` | 문서 인덱스 DB 164KB, 조각 수는 4000 미만으로 추정(직접 쿼리는 안 함) | 이미 상한이 설계돼 있다 — 코퍼스가 커져 4000 조각을 넘기 전까지는 문제가 아니다 |
| siege 원장 DB(오케스트레이션) | `orchestration/store.py` 조회는 전부 파라미터 바인딩 + `fetchone()`/특정 컬럼 — 전량 덤프 없음 | 176KB | `SELECT * FROM {table}` 전량 덤프는 `studio/*.py`(티켓 보드, 별개 표면)에서만 발견 — 이번 스코프(훅 경로) 밖 |

## 6. 메모리 최적화 순위 (근거 숫자 포함)

1. **훅당 새 프로세스 기동 자체 (~20MB 바닥)** — PreToolUse만 Bash 호출 1회당 4개(`secret-guard`·`git-guard`·`release-guard`·`readonly-guard`)가 뜬다(`.claude/settings.json` 실측). 4개 × 20MB대 바닥 = 툴 호출 1회당 80MB대 순간 상주가 뜨고 진다. 가장 큰 지렛대지만 고치려면 훅을 한 디스패처 프로세스로 합치거나 상주화하는 구조 변경이 필요하다 — 이 단위의 범위 밖(고치지 말라는 지시), Odin 판단 필요 항목으로 보고.
2. **`asgard.memory`/`asgard.project_memory` 임포트 체인 (+8.5MB, +7.5MB)** — `memory-activate.py`(52.56MB)·`scope-activate.py`(50.23MB)·`map-activate.py`(37MB대)가 상위 6위 중 5개를 차지하는 이유가 이 체인이다. `scope-activate.py`가 왜 `project_memory`까지 타는지가 가장 먼저 볼 지점 — 임포트를 지연시키거나(함수 내부 lazy import) 실제 쓰는 서브모듈만 골라 임포트하면 이 5개 훅의 바닥을 20MB대로 낮출 여지가 있다.
3. **`budget_guard.read_ledger()`의 무제한 전체 재스캔** — 메모리 피크가 아니라 세션이 길어질수록 누적되는 I/O·CPU. 이미 상한이 있는 `transcript.tail_rows()`와 같은 파일을 다른 정책으로 읽는 두 함수가 공존한다는 것 자체가 구조적 신호. 체크포인트(마지막으로 읽은 바이트 오프셋)나 `tail_rows`류 상한 재사용이 다음 후보.
4. **퀘스트 로그 전량 파싱의 3중 재구현** — 지금은 176KB로 무해하지만(2번 항목의 30~50%도 안 되는 크기), 세 곳이 같은 로직을 따로 구현하고 있어 상한을 걸 때 세 곳을 다 고쳐야 한다. `ledger.load_events()`로 통일하고 필요하면 거기에 크기 상한을 얹는 편이 다음 리팩터 대상.
5. **`documents.py`의 `MAX_SCAN_CHUNKS=4000` 전량 스캔** — 이미 캡이 있고 현재 164KB로 캡에서 한참 멀다. 지금은 손댈 이유가 없고, 프로젝트 메모리 문서 코퍼스가 커질 때만 다시 볼 항목.

## 못 잰 것

- `asgard-serve.mjs`의 장기 누수 여부(9일치 추세) — 3표본·127초로는 판정 불가, 재시작 없이 잴 수 있는 상한.
- 문서 인덱스 DB의 실제 조각(`doc`) 행 수 — DB 파일에 직접 쿼리하지 않아 `MAX_SCAN_CHUNKS` 대비 여유를 정확한 숫자로는 못 냈다(파일 크기 164KB로 추정만).
- Node 쪽(`asgard-serve.mjs`) 내부 V8 힙 분포 — 이번 측정은 OS RSS만, V8 heap snapshot은 범위 밖.

## 파일

- `benchmarks/cpu-profile/memprofile.py` — `rss`/`alloc`/`staircase`/`list` 서브커맨드, `--json` 지원.
- `benchmarks/cpu-profile/findings-memory.md` — 이 문서(배정된 산출 파일명).
