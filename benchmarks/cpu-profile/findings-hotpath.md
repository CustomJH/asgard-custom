# 훅 4종 지배항 — cProfile + importtime 실측 (2026-08-14)

측정: `benchmarks/cpu-profile/hotpath.py --all --mode both --json`, 저장소 루트 실행,
`CLAUDE_PROJECT_DIR` 설정(실제 호스트와 동일 — `paths.repo_root()`의 git 폴백을 안 타게).
각 훅은 `.claude/settings.json`에 등록된 실제 이벤트로 트리거했다 — 어느 이벤트였는지는 아래
훅별 소제목에 적었다.
cProfile은 파이썬 함수 호출만 잰다 — 인터프리터 기동·모듈 재적재 같은 프로세스 경계 비용은
안 잡힌다(과제 지시대로 명시). 그 비용은 `uv run --no-project python -c pass` 바닥값
(30ms, 이미 잰 값)에 들어 있고, 아래 숫자는 그 위에 얹히는 "훅 자신의" 비용이다.

## 결과 표

| 훅 | import (실측) | exec (cProfile 벽시계) | 지배항 |
|---|---|---|---|
| tutor-note | 19.7ms | 719.1ms | subprocess 2회 (git cat-file + `asgard tutor`) |
| memory-activate | 20.3ms | 189.9ms | subprocess 1회 (`asgard memory snapshot`) |
| scope-activate | 20.1ms | 304.9ms | subprocess 1회 (`asgard skills resolve`) |
| map-activate | 24.2ms | 241.2ms | subprocess 1회 (`asgard map context`) |

import는 `python -X importtime`으로 훅마다 따로 뽑은 값이고(하위 `--mode importtime`),
exec는 in-process cProfile 실측(`--mode exec`)이다 — 두 값은 다른 실행이라 단순 합이
바닥값+270ms 같은 등식이 되지는 않는다(재실행 편차, cProfile 계측 오버헤드 포함).
`python -c pass`의 importtime 총합은 6.7ms — 훅 4종의 20~24ms 중 13~17ms만 훅 자신이
새로 부르는 stdlib(`subprocess`·`shutil`·`hashlib`·`re`)이고, 나머지는 인터프리터가 어차피
싣는 `site`·`encodings` 등이다. import는 지배항이 아니다 — 어느 훅도 20ms대를 못 넘는다.

## 훅별 상위 함수 5개 (cProfile, cumtime 기준)

### tutor-note (Stop, 실제 write 저널 2건 — 존재 파일 1 + 삭제 파일 1)

| cumtime | function |
|---|---|
| 719.0ms | `<frozen runpy>:269 run_path` |
| 710.9ms | `asgard_hooklib/firing.py:111 run` |
| 709.3ms | `tutor-note.py:545 main` |
| 708.2ms | `subprocess.py:513 run` (2회) |
| 702.4ms | `subprocess.py:1177 communicate` |

지배항 위치: `.claude/hooks/tutor-note.py:106-115 _reviewable()`(삭제 파일 확인용
`git cat-file -e HEAD:<path>` 1회) + `.claude/hooks/tutor-note.py:137-140 _lesson()`
(`asgard tutor --json --record --report ...` 1회). 두 호출 다 `subprocess.run`이고 회수 2회.

### memory-activate (SessionStart)

| cumtime | function |
|---|---|
| 189.8ms | `<frozen runpy>:269 run_path` |
| 182.8ms | `asgard_hooklib/firing.py:111 run` |
| 181.7ms | `memory-activate.py:221 main` |
| 181.5ms | `subprocess.py:513 run` (1회) |

지배항 위치: `.claude/hooks/memory-activate.py:295-307` — `event`가 `"Stop"`도
`"UserPromptSubmit"`도 아니면(= `SessionStart` 포함, 사실상 대부분의 실제 호출)
곧장 `else` 분기로 떨어져 `asgard memory snapshot --provider claude-code` 1회를 무조건 부른다.

### scope-activate (UserPromptSubmit, 실제 개발 요청 문장)

| cumtime | function |
|---|---|
| 304.7ms | `<frozen runpy>:269 run_path` |
| 302.2ms | `asgard_hooklib/firing.py:111 run` |
| 301.1ms | `scope-activate.py:85 main` |
| 300.9ms | `subprocess.py:513 run` (1회) |

지배항 위치: `.claude/hooks/scope-activate.py:108-116` — `asgard skills resolve --agent worker
--scope-only <task>` 1회.

### map-activate (UserPromptSubmit, 6h 신선도 마커 갱신 후 — 아래 "부록" 참조)

| cumtime | function |
|---|---|
| 241.1ms | `<frozen runpy>:269 run_path` |
| 239.0ms | `asgard_hooklib/firing.py:111 run` |
| 238.0ms | `map-activate.py:96 main` |
| 237.7ms | `subprocess.py:513 run` (1회) |

지배항 위치: `.claude/hooks/map-activate.py:119-121` — `asgard map context --query <task>` 1회.
`maintain()`(83-92행)은 신선도 마커가 6시간 이내면 건너뛴다 — 부록에 별도 실측.

## 4개 모두 공통 — 훅이 아니라 asgard CLI 자체가 무겁다

네 훅 다 own-time은 1ms 미만이다 — 훅별 표의 `main`부터 `subprocess.run`까지가 cumtime 으로는
전부 그 훅의 총합에 가깝지만, 각 프레임이 자기 몫으로 쓴 시간은 0.02~0.09ms 였다(cProfile 의
tottime, 표에는 안 실었다). 훅 코드 자체는 파일 읽기·JSON 파싱·조건 분기뿐이라 가볍고, 벽시계의 97%
이상은 자식 프로세스(`asgard <subcmd>`)를 기다리는 `subprocess.py:2093 _communicate`다.
그래서 "왜 느린가"의 답은 훅 파일이 아니라 그 자식 프로세스 안에 있다 — 4개 서브커맨드를
직접 cProfile로 뜯었다(`from asgard.cli import main; main()`, 동일 인자).

| 서브커맨드 | 총 벽시계 | typer 부트스트랩 | 서브커맨드 자체 로직 |
|---|---|---|---|
| `memory snapshot` | 148ms | 97ms (`_find_and_load` 258/5회) | ~50ms |
| `map context` | 274ms | ~130ms (get_group/get_command_from_info) | ~130ms (map/commands/map.py:489) |
| `skills resolve` | 836ms | ~220ms (get_group/get_command_from_info) | 460ms (`skill_scope.scope_note`) |
| `tutor --json` | 352ms | ~90ms | 225ms (`commands/tutor/entry.py:98 _run_review`) |

`skills resolve` 의 460ms 안에서 정규식 컴파일이 차지하는 몫은 40.7ms 다(아래 지배항 2의 실측).
나머지 약 420ms 가 `scope_note` 안의 무엇인지는 이번 계측이 함수 단위까지 못 갈랐다 — 미해결로
남긴다. 재실행 편차도 크다: 같은 경로를 뒤에 다시 재니 554ms 였다.

### 지배항 1 — 모든 서브커맨드가 공통으로 내는 CLI 부트스트랩 세금

`src/asgard/cli/__init__.py:16-30` — `_GROUPS`(13개: root·roots·review·agent·map·role·siege·
skills·memory·ticket·evolve·office·k6)를 `from asgard.cli import main` 시점에 무조건 전부
`import_module`한다. 어느 서브커맨드 하나만 부르든 13개 그룹 모듈이 전부 로드되고, 그 안에서
`@app.command()`로 등록된 함수가 총 204개(`grep -c '@.*\.command('` 실측) + `add_typer` 22곳
— 합쳐 typer가 `get_group_from_info`/`get_command_from_info`(외부 라이브러리,
`typer/main.py:1163`/`1283`/`1392`)로 그 전부를 Click Command 객체로 변환한다. 이 변환은
호출된 서브커맨드 하나가 아니라 트리 전체를 매번 다시 만든다 — `asgard skills resolve`의
cProfile에서 `get_command_from_info`가 265회 불렸다(스킬 명령 하나만 실행했는데도).
`python -X importtime -c "from asgard.cli import main"` 단독 실측: `asgard.cli` self 4.6ms /
cumulative 33.1~46.9ms — 이건 import 문 자체 비용이고, 위 표의 "typer 부트스트랩" 90~220ms는
그 뒤 `app()` 호출 시점에 추가로 드는 Click 트리 구성 비용이다. 네 서브커맨드 전부에서
90ms 밑으로 안 내려간다 — 이게 "훅 4개가 전부 최소 ~150~250ms인 이유"의 공통 분모다.

### 지배항 2 — skills resolve만의 추가 비용: 매 프로세스마다 정규식을 처음부터 다시 컴파일

`src/asgard/skill_registry/resolve.py:44-55 _trigger_pattern()`은 `functools.lru_cache
(maxsize=1024)`로 감싸 있어 같은 프로세스 안에서는 같은 트리거를 두 번 컴파일하지 않는다.
문제는 캐시가 프로세스 수명과 같다는 것 — 훅이 매번 새 `asgard` 프로세스를 fork하므로
(`scope-activate.py:108` subprocess.run) 이 캐시는 매 턴 빈 채로 시작한다.

실측(`re.compile` 자체를 감싸 세고, `_trigger_pattern.cache_info()` 로 교차 확인):

| 경로 | `re.compile` 실호출 | `_trigger_pattern` misses | 벽시계 |
|---|---:|---:|---:|
| `resolve_skills()` 단독 | 138 | 261 | 46.6ms |
| CLI 전체 (`skills resolve --agent worker --scope-only`) | 236 | 402 | 554ms |

같은 프로세스 안에서 `resolve_skills()` 를 다시 부르면 5.9ms 로 떨어진다 — 즉 **프로세스마다
캐시가 리셋돼 매번 다시 내는 몫은 40.7ms** 다(46.6 − 5.9). 스킬 라우팅 표의 트리거 낱말마다
낱말 경계 정규식을 새로 짜는 구조라 등록된 스킬 수에 선형으로 붙고, 각 패턴이
`(?<![a-z0-9]){escaped}(?:s|es|ing|ed|er|ers)?(?![a-z0-9])` 고정 형태라 입력 길이에 지수적으로
붙지는 않는다 — 비용은 순전히 컴파일 횟수다.

> 정정 이력: 이 절의 첫 판은 `re.compile` 1,239회·260ms 로 적었다. 두 수 다 재현되지 않는다.
> `_trigger_pattern` 은 `lru_cache` 로 감싸여 있어 호출 1회당 컴파일이 최대 1회이므로
> 컴파일 수가 `_trigger_pattern` 호출 수를 넘을 수 없고, 위 표가 실제 값이다. 40.7ms 는
> 이 절이 처음 주장한 260ms 의 6분의 1 이라, 최적화 후보로서의 순위도 그만큼 내려간다.

### 지배항 3 — tutor --json만의 추가 비용: git 서브프로세스 10회 팬아웃

`commands/tutor/entry.py:98 _run_review()` → `commands/tutor/engines.py:27 _explanation()` →
`tutor_teach.py:703 explain()` 경로가 git 서브프로세스를 팬아웃한다. 총합은 `subprocess.py:513
run` 209ms(전체 352ms의 59%)로 맞지만, **호출이 한 자리에서 나오지 않는다.** 두 모듈의 동명
함수를 각각 감싸 세었다(`explain(root, "HEAD", ("AGENTS.md",), "")`, 이 저장소 현재 상태):

| 출처 | 호출 수 | 무엇을 부르나 |
|---|---:|---|
| `src/asgard/tutor_teach.py:137 _git()` | 2 | `diff --name-only HEAD`, `ls-files --others --exclude-standard` (둘 다 `_changed()` 153·157행) |
| `src/asgard/surface.py:207 _git()` | 8 | `diff` ×2, `show HEAD:<path>` ×6 — `_symbol_terms()`→`surface.diff()`(293행), `_unstaged_gaps()`→`surface.changed_python()`(232행) |

팬아웃이 **review 대상 파일 수에 비례하지 않는다.** `surface.changed_python()` 은 base 대비
저장소 전체에서 바뀐 `.py` 파일을 훑고 그 하나하나에 `git show` 를 부른다 — 즉 늘어나는 축은
tutor-note 가 넘긴 파일 수가 아니라 **저장소에 커밋 안 된 `.py` 파일 수**이고, 그건 이 훅과
무관한 변수다(측정 중 다른 세션의 미커밋 작업이 이 수를 움직였다).

> 정정 이력: 이 절의 첫 판은 9회 전부를 `tutor_teach.py:137` 로 돌렸고 "review 파일 수만큼
> 늘어난다"고 적었다. 둘 다 틀렸다 — 지배 지분은 `surface.py:207` 에 있고, 증가 축은
> 저장소의 미커밋 `.py` 수다. 고칠 자리가 달라지므로 순서가 아니라 대상이 바뀌는 정정이다.

## SQLite·파일 시스템 순회

4개 훅 어디에도 sqlite3·glob·os.walk 호출이 없다(grep 확인, 훅 4종 +
`asgard_hooklib/firing.py`·`inject.py`). 오케스트레이션 DB는 다른 훅(siege-inbox 등)이 쓰고,
이 4종과는 무관하다. JSON 파싱 대상도 전부 작다 — write 저널은 세션이 쓴 경로 목록(수십 항목
수준), transcript 파일 전체를 읽는 코드는 memory-activate의 `_transcript_turn`(97-119행)뿐이고
그건 Stop 이벤트에서만 돈다(이번 실측은 SessionStart라 안 탔다).

## 부록 — map-activate가 신선도 마커 없이 돌면 무엇이 잡히는가

측정 시점(2026-08-14 13:53 KST 부근) 실제 신선도 마커 타임스탬프는 1786596584(13:49:44) —
`REFRESH_SECONDS`(21,600초=6시간, `map-activate.py:71`)를 이미 넘겨 있었다. 그대로 뒀으면 위
실측이 아니라 `maintain()`의 전체 재구축 경로(`map-activate.py:92-97`)를 탔을 것이고, 이
저장소 실측 기록(팀 메모리 26-08-03 노트)이 그 값을 4.7초로 적어 뒀다 — 위 241ms 표와는
자릿수가 다른 별개의 지배항이다. `hotpath.py`는 프로파일 직전에 마커를 현재 시각으로 갱신하고
끝나면 원래 값으로 되돌린다(`_setup`/`_teardown`) — steady-state 수치와 6시간 주기 수치를
섞지 않기 위한 조치다. 이 저장소가 6시간 넘게 비어 있다가 다시 열리는 세션은 첫
UserPromptSubmit에서 초 단위 지연을 겪는다는 뜻이고, 이번 과제 범위(진단만, 고치지 않음)에서는
사실만 남긴다.

## 가장 큰 한 덩어리

네 훅 전부에서 가장 큰 단일 항목은 훅 자신의 코드가 아니라, `subprocess.run`이 기다리는
자식 `asgard` 프로세스가 매번 처음부터 다시 만드는 CLI 명령 트리다 — 위치는
`src/asgard/cli/__init__.py:30`(13개 그룹 무조건 전부 import)이고, 그 결과로 typer가
`get_group_from_info`/`get_command_from_info`(site-packages `typer/main.py:1163,1283,1392`)에서
등록된 명령 204개+를 Click 객체로 변환한다. 실측 90~220ms — `memory snapshot`(148ms)처럼
서브커맨드 자체 로직이 가벼운 경우엔 총 벽시계의 60% 이상을 이 부트스트랩이 차지하고,
`skills resolve`(836ms)처럼 서브커맨드 로직 자체가 무거운 경우에도 여전히 200ms 이상의
고정비로 얹힌다. 호출된 서브커맨드가 하나뿐이라는 사실이 이 비용에 전혀 반영되지 않는
구조라는 점이 이 덩어리의 성격이다 — 훅 4종이 매 턴 4번(SessionStart 1 + UserPromptSubmit 2
+ Stop 1) 이 세금을 각각 새로 낸다.
