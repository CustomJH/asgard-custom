# 항목 4 — 기억 명령 파사드 임포트 지연 (2026-08-14)

`scope-activate` 는 이제 `project_memory` 를 안 탄다 — **항목 2 가 그 사슬을 이미 끊었다.**
남은 지렛대는 파사드 하나였고, SessionStart 의 `memory-activate` 를 3.7MB 낮췄다.

## 먼저 물은 것: `scope-activate` 가 왜 `project_memory` 까지 타는가

지금은 안 탄다. 실측(현재 작업 트리):

```
skills resolve --scope-only   project_memory=False memory_bridge=False memory=False  out=791B
```

`asgard skills resolve` 를 `-X importtime` 으로 돌리면 `asgard.memory*` 이름이 한 줄도 안
나온다. 씨앗 표의 `scope-activate 50.23MB` 는 항목 2 이전 값이고 지금은 41.5MB 다. 원인은
`asgard.cli` 가 13개 그룹을 매 호출마다 등록하던 것이었고, 항목 2 의 지연 등록이 그중 `memory`
그룹을 안 열게 만들면서 같이 사라졌다.

남은 41.5MB 의 정체는 `import typer` 하나다 — 새 인터프리터 15.94MB 위에 typer 가 25.09MB 를
얹는다. `asgard.cli` 전체가 26.30MB 이므로 CLI 임포트 값의 거의 전부가 typer 다. 이건
`src/asgard/cli/` 표면이라 이번에 손대지 않았다.

## 실제로 끊은 것

`src/asgard/commands/memory/__init__.py` 가 하위 7개 모듈을 최상위에서 전부 임포트하는
파사드였다. 그중 `autosave`·`project` 두 개만 `asgard.project_memory`·`asgard.memory_bridge`
를 끌고 오는데, `memory snapshot`(SessionStart 훅)·`memory query` 같은 개인 기억 명령은 그 둘을
안 쓴다.

`src/asgard/cli/__init__.py:149` 에 이미 있는 PEP 562 `__getattr__` 형태를 그대로 썼다 — 이름
하나를 물으면 그 이름을 정의한 모듈까지만 등록하고, 돌려준 값을 전역에 적어 둔다(두 번째
조회부터 `__getattr__` 이 안 불리고, `mock.patch` 의 되돌림 자리도 예전과 같다).

## 줄어든 것 / 그대로인 것

before/after 를 3회 번갈아 재고 최솟값·중앙값을 같이 싣는다 (load average 3.4~4.0).

| 축 | before (min/med) | after (min/med) |
|---|---|---|
| `import asgard.commands.memory` RSS | 31.92 / 31.94 MB | **18.12 / 18.16 MB** |
| `memory snapshot` 프로세스 RSS | 36.52 / 36.53 MB | **32.62 / 32.73 MB** |
| `memory-activate.py (SessionStart)` 최대 RSS | 36.31 / 36.41 MB | **32.66 / 32.67 MB** |
| `memory-activate.py (SessionStart)` 벽시계 | 0.12 / 0.12 s | 0.10 / 0.10 s |
| `memory-activate.py (UserPromptSubmit)` | 48.59 / 48.61 MB | 48.30 / 48.39 MB |
| `scope-activate.py (UserPromptSubmit)` | 41.47 / 41.50 MB | 41.50 / 41.61 MB |

**무엇이 옮겨 갔나 — 아무것도 안 옮겨 갔다.** 벽시계가 오른 구간이 없고 스냅샷은 오히려
0.09→0.07초로 내렸다. 항목 2 와 다른 이유는, 여기서 지연시킨 모듈들이 그 명령 경로에서
**나중에도 안 불리기** 때문이다. 반대로 `memory recall`·`sync-turn`·`tick` 은 지연된 모듈을
여전히 부르고, 그 셋은 before/after 가 오차 범위 안이다(예: tick 44.66→44.25).

## 직접 증거 — 훅이 부르는 명령마다 `sys.modules`

```
memory snapshot --provider claude-code  (SessionStart)     project_memory=False memory_bridge=False memory=True  out=3231B
memory recall --provider claude-code    (UserPromptSubmit) project_memory=True  memory_bridge=True  memory=True  out=979B
memory sync-turn --mode claude-code     (Stop)             project_memory=True  memory_bridge=True  memory=True  out=64B
memory tick                             (Stop)             project_memory=True  memory_bridge=True  memory=True  out=0B
skills resolve --scope-only             (scope-activate)   project_memory=False memory_bridge=False memory=False out=791B
```

`recall` 이 `True` 인 것은 결함이 아니라 **진짜 쓰는 것**이다. `run_recall` 은 함수 안에서
`asgard.memory_context` 를 부르고, 그것이 프로젝트 레인을 조립하려고 `project_memory` 를
임포트한다. 임포터 추적으로 확인했다: `asgard.project_memory <- ['asgard.memory_context', ...]`.
그래서 UserPromptSubmit 훅은 안 줄어든다.

## 회수가 실제로 되는가

before/after 출력이 **바이트 단위로 같다** (sha256 앞 16자 + 길이, 3회 전부 동일):

```
memory snapshot  sha=36d0e20f8f3c37fe len=3231  IDENTICAL
memory recall    sha=f9981987a5103ba2 len=963   IDENTICAL
memory query     sha=3590083b5f290b94 len=762   IDENTICAL
skills resolve   sha=5539bca7d3365af1 len=791   IDENTICAL
```

빈 결과를 잡는 검사는 **없었다.** 기존 회수 시험(`test_recall_budget.py`·`test_episodes.py`·
`test_project_memory.py`)은 전부 `memory_context.recall_note` 를 직접 부르고, CC 배선 시험
(`test_cc_user_prompt_submit_injects_query_recall`)은 가짜 `asgard` 셸 스크립트를 쓴다 —
파사드를 지나는 실제 CLI 회수 경로는 아무도 안 밟았다. 그래서
`tests/memory/test_memory_wiring.py` 에 `TestMemoryCommandFacade` 를 붙였다:

- `test_every_exported_name_resolves_to_its_defining_module` — `__all__` 50개 전부가 정의처 모듈의 **같은 객체**로 풀리는지
- `test_recall_command_returns_the_stored_page_body` — `memory recall --provider claude-code` 를 CliRunner 로 끝까지 돌려 저장한 페이지 제목이 나오는지

돌연변이 확인: `_SOURCE` 에서 `"run_recall"` 한 줄을 빼면 둘 다 빨개진다
(`AttributeError: module 'asgard.commands.memory' has no attribute 'run_recall'`).
통과만 하는 시험이 아니다.

## 검증

| 항목 | 결과 |
|---|---|
| `grep -rln` 이 고른 46개 + 새 파일 | 1647 passed, 3 skipped, 372 subtests (74.3초) |
| `tests/test_skill_scope.py` `tests/test_scope_activate.py` `tests/test_architecture.py` | 72 passed |
| `ruff check` / `ruff format --check` / `ty check` | 전부 통과 |
| `asgard craft` rc=0, `asgard thor gate` rc=0 | 막는 판정 0건 |

## 배포본

훅 파일을 하나도 안 고쳤으므로 배포본은 그대로다. 그래도 증거를 댄다 —
`src/asgard/hooks/*.py`(밑줄) 전부와 `.claude/hooks/*.py`(하이픈) 짝을 `diff -q` 로 돌려
`all deployed hook copies identical to source`, `asgard_hooklib` 도 `diff -rq` 로 동일.

## 범위 밖에서 나온 것 하나 — 훅보다 40배 큰 값

찾다가 걸린 것이라 그대로 남긴다. `asgard memory recall` 과 `memory query` 는 시맨틱 레인의
`model2vec` + `huggingface_hub` 를 올리면서 **RSS 1,951.7MB** 를 찍는다(`/usr/bin/time -l`
실측, 벽시계 1.35초). 훅은 `ASGARD_MEMORY_NO_DOWNLOAD=1` 을 걸고 부르기 때문에 같은 명령이
47.77MB 로 끝난다(`memory_activate.py:241`).

| 실행 | RSS |
|---|---:|
| `memory recall` (훅과 같은 `NO_DOWNLOAD=1`) | 47.77 MB |
| `memory recall` (사람이 터미널에서 그냥 침) | 1,951.70 MB |
| `memory snapshot` (`NO_DOWNLOAD=1`) | 32.80 MB |

씨앗의 20.4~52.6MB 표 전체가 이 한 프로세스 앞에서는 반올림 오차다. 다만 그 플래그를 끄는 것이
회수 품질에 무엇을 하는지는 재지 않았고, 손대면 회수 결과가 달라지는 자리라 건드리지 않았다.

## 바꾼 파일

- `src/asgard/commands/memory/__init__.py`
- `tests/memory/test_memory_wiring.py`

## 못 잰 것

- `import typer` 25.09MB 를 줄일 수 있는지 — `src/asgard/cli/` 가 이번 항목의 금지 범위라 확인 안 했다.
- `memory tick` 이 `project_memory` 를 함수 안에서 부르는지 최상위에서 부르는지 — 임포터 추적에 `asgard.commands.memory.backends` 가 찍혔는데 `backends.py` 최상위에는 그 임포트가 없다. 함수 본문 임포트로 보이지만 호출 지점까지 따라가진 않았다.
- 시맨틱 레인 1.95GB 가 실제 세션에서 몇 번 뜨는지 — 훅 경로에서는 `NO_DOWNLOAD=1` 로 안 뜬다는 것만 확인했고, 다른 진입점은 안 셌다.
