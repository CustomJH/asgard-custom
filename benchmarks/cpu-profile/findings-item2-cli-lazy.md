# 항목 2 — CLI 명령 그룹 지연 로딩 (2026-08-14)

서브커맨드 하나를 부르면 그 그룹 모듈 하나만 등록된다. 나머지 12개는 임포트되지 않는다.
훅이 부르는 명령 셋의 총 벽시계가 15~18% 줄었고, `asgard --help`의 목록은 글자까지 그대로다.

바꾼 파일은 `src/asgard/cli/__init__.py` 하나다.

## 무엇을 했나

`_GROUPS` 13개를 무조건 `import_module` 하던 자리를 없애고, 루트 Typer 앱의 Click 그룹
클래스를 `_LazyGroup`으로 바꿔 끼웠다(`app.info.cls`). 갈림은 `commands` 속성 하나다.

- **이름 하나를 물을 때** — `get_command(ctx, name)`이 `_table`을 직접 본다. 없으면
  `_register`가 이름과 같은 모듈부터, 없으면 `_GROUPS` 차례로 등록하면서 그 이름을 매다는
  모듈이 나올 때까지만 간다. `_declares`가 Click 객체를 짓지 않고 typer 등록부만 읽어
  판정하므로, 모듈을 하나 더 등록할 때마다 표면을 다시 짓지 않는다.
- **명령표를 통째로 달랄 때** — `commands` 속성이 `_load_all()`로 13개를 다 등록하고 표를
  다시 짓는다. `--help`의 `list_commands`, `completions`가 읽는 표면, 표면 시험의
  `commands["completions"]`가 전부 이 하나를 지나므로 훑는 쪽은 예전 표를 그대로 본다.

매핑 연산(`[]`·`in`·`.get`·`.items()`·`len`)을 하나씩 세어 가로채는 dict 상속판을 먼저
썼다가 버렸다. `__getitem__`을 빠뜨려 `tests/test_cli_surface.py` 4건이 깨졌다 — 세다
빠뜨린 하나가 그대로 구멍이었다. 속성 하나로 옮기면 셀 것이 없다.

`_load_all()`은 등록 차례를 `_GROUPS`로 되돌린다. 한 프로세스가 명령을 두 번 지나는 경우
(시험의 CliRunner)에 필요하다 — 먼저 지나간 `asgard memory ...`가 memory를 아홉째가 아니라
첫째로 등록해 두기 때문이다. 실측:

    부분 로드 직후: ['memory', 'yggdrasil', 'k6', 'automations', 'root']
    _load_all 뒤   : ['root', 'review', 'agent', 'einherjar', 'auth']

## 기준선과 변경 후

측정: 변경 전/후 파일을 **번갈아** 바꿔 끼우며 15회씩, 새 프로세스마다 1회.

이 기계는 측정 내내 조용하지 않았다 — Spotlight 색인(`mds_stores` 104% CPU), Chrome, 그리고
같은 저장소의 pytest-xdist 워커가 계속 돌아 load average가 9~34 사이를 오갔다. 그래서
**최솟값**을 같이 싣는다. 배경 부하는 시간을 더하기만 하므로 최솟값이 간섭이 가장 적은
표본이고, 번갈아 재서 두 판본이 같은 부하 구간을 겪게 했다. 처음에 전/후를 붙여서 잰
회차는 순서 효과로 `work_ms`가 반대 방향으로 나왔고, 번갈아 재자 그 어긋남이 사라졌다.

### 총 벽시계 — 콘솔 스크립트 한 번 (`.venv/bin/asgard`, 인터프리터 기동 포함)

| 명령 | 전 min | 후 min | Δ | 전 med | 후 med | Δ |
|---|---|---|---|---|---|---|
| `asgard map context --query x` | 118.8ms | 99.3ms | **−19.6ms (−16.5%)** | 143.2ms | 122.4ms | −20.9ms (−14.6%) |
| `asgard memory snapshot --provider claude-code` | 101.9ms | 84.2ms | **−17.7ms (−17.4%)** | 120.7ms | 103.3ms | −17.5ms (−14.5%) |
| `asgard skills resolve --agent worker x` | 153.7ms | 126.6ms | **−27.1ms (−17.6%)** | 181.1ms | 163.9ms | −17.2ms (−9.5%) |
| `asgard --help` | 109.5ms | 103.2ms | −6.3ms (−5.8%) | 130.2ms | 131.3ms | +1.1ms (+0.9%) |

`--help`는 두 추정치의 부호가 갈린다 — 이 잡음 폭 안에서는 변화 없음으로 읽는 것이 맞다.
축을 나눠 보면 왜 그런지가 보인다: 임포트에서 빠진 값이 `--help` 구간으로 옮겨 갔을 뿐이다.

### 축별 (in-process, 같은 15회)

| 축 | 대상 | 전 min | 후 min | Δ |
|---|---|---|---|---|
| `from asgard.cli import main` | — | 23.4ms | 20.8ms | −2.6ms |
| 그 뒤 `--help`까지 | — | 50.3ms | 56.5ms | +6.1ms |
| 임포트+트리 짓기 | `map context` | 34.5ms | 19.6ms | **−14.9ms (−43%)** |
| 임포트+트리 짓기 | `memory snapshot` | 34.3ms | 19.8ms | **−14.5ms (−42%)** |
| 임포트+트리 짓기 | `skills resolve` | 34.2ms | 19.9ms | **−14.3ms (−42%)** |

`--help`의 두 축을 합치면 전 73.7ms · 후 77.3ms(min), 전 91.4ms · 후 91.1ms(median)다.
그룹 13개의 임포트가 임포트 구간에서 `--help` 구간으로 옮겨 갔을 뿐이다. 두 추정치가
+3.6ms 와 −0.3ms 로 부호가 갈리므로 **새로 생긴 값은 이 잡음 폭 안에서 분리되지 않는다** —
`--help` 경로가 빈 그룹을 한 번 더 짓기는 하지만 그 비용은 안 쟀다.

훅 넷이 매 턴 이 세금을 각각 낸다(`findings-hotpath.md` 지배항 1). 위 셋만 세도 한 턴에
약 −65ms다. 네 번째 훅(`asgard tutor --json`)은 재지 않았다 — 그 명령은 diff를 읽고
모델을 부르므로 한 번이 20초였고, CLI 세금이 그 안에서 분리되지 않는다. 지연 로딩 자체는
그 경로에도 걸린다(아래 실측에서 `tutor`는 그룹 1개만 등록했다).

## 지연이 실제로 먹었는가 — 직접 증거

`sys.modules`에 남은 `asgard.cli.<그룹>`의 수와, `typer.main.get_command_from_info` 호출을
세어 실제로 지어진 리프 Click 객체의 수.

| 명령 | 그룹 모듈 (전→후) | 지어진 리프 명령 (전→후) |
|---|---|---|
| `map context --query x` | 13 → **1** (`map`) | 265 → **10** |
| `memory snapshot --provider claude-code` | 13 → **1** (`memory`) | 265 → **86** |
| `skills resolve --agent worker x` | 13 → **1** (`skills`) | 265 → **11** |
| `tutor --json` | 13 → **1** (`root`) | — |
| `--help` | 13 → 13 | 265 → 265 |
| `completions bash` | 13 → 13 | 530 → 305 |

`memory`가 86인 것은 그 그룹 하나가 명령 86개를 매달기 때문이다 — 지연이 덜 먹은 것이
아니라 그 그룹이 크다.

## `--help` 대조

`asgard --help`와 하위 그룹 16개의 `--help`를 변경 전/후 각각 파일로 저장해 `diff`했다.
`COLUMNS=80`·`TERM=dumb`으로 고정(Rich가 폭에 따라 줄바꿈을 바꾼다).

**17개 화면 전부 바이트 단위로 같다.** 최상위 목록 41개 명령의 차례와 내용, 각 한 줄
설명까지 포함한다.

대조한 화면: 최상위, `map` `memory` `siege` `skills` `ticket` `agent` `k6` `k6 baseline`
`office` `evolve` `role` `review` `root` `setup` `automations`, 그리고 존재하지 않는 이름
(`roots`)의 오류 화면.

마지막 것이 결함 하나를 잡았다. 첫 판에서 없는 이름은 `RecursionError`로 끝났다 —
`dict.update`가 `__iter__`를 손댄 매핑을 보고 `keys()`를 거쳐 읽는데 그 `keys()`가 다시
채우기로 돌아왔다. 지금은 `No such command 'roots'. Did you mean 'root', 'tools'?`까지
전과 같은 글자다.

**차례가 어그러지는 경로**도 따로 봤다. 한 프로세스에서 `memory` → `k6` → `setup` →
`ticket`을 먼저 지난 뒤 `--help`를 부른 화면이 기준선과 바이트 단위로 같다.

## 재수출

`from asgard.cli import app, main, _main, _version, _agent, k6_app, k6_baseline_app` 전부
닿는다. `k6_app`·`k6_baseline_app`은 모듈 `__getattr__`(PEP 562)이 물을 때 `k6`를 등록해
돌려주므로, 다른 명령을 부를 때는 `k6`가 임포트되지 않는다. 없는 이름은 `AttributeError`
(`module 'asgard.cli' has no attribute 'nope'`).

## 완성(completion)

지시대로 그대로 뒀다. `asgard completions <shell>`은 13개를 다 등록한다(위 표의 13→13).
`src/asgard/commands/completions.py`는 한 줄도 안 고쳤다 — `_surface()`가 읽는
`get_command(cli.app).commands`가 속성을 지나면서 알아서 다 채워진다.

생성된 스크립트 4종(bash·zsh·fish·powershell)을 변경 전/후로 뽑아 `diff` 했고
**전부 바이트 단위로 같다** (158·196·437·134행).

## 못 지연시킨 것

`asgard --help`와 `asgard completions`는 정의상 명령표 전체가 필요하므로 13개를 다 등록한다.
이 둘은 애초에 줄일 대상이 아니다.

이름과 모듈이 다른 최상위 이름은 `_GROUPS` 차례로 훑다가 자기 모듈에서 멈춘다. `_declares`가
Click 객체를 안 지으므로 이때 드는 값은 그 모듈들의 임포트뿐이다.

| 이름 | 매다는 모듈 | 등록되는 모듈 수 |
|---|---|---|
| `tutor` `doctor` `craft` `thor` `run` `health` 등 root.py의 최상위 명령 | `root` | 1 |
| `root` | `roots` | 2 |
| `auth` `einherjar` | `agent` | 4 |
| `setup` | `map` | 5 |
| `mode` | `role` | 6 |
| `tools` `plugins` | `skills` | 8 |
| `yggdrasil` | `memory` | 9 |
| `open` | `ticket` | 10 |
| `automations` | `k6` | 13 |

이름→모듈 표를 손으로 들지 않은 것은 의도다. 표를 적으면 명령이 옮겨 다닐 때 조용히
낡는다. 훑는 쪽은 최악이라도 13개를 다 등록해 예전 동작으로 돌아갈 뿐이고, 훅이 실제로
부르는 이름 넷은 전부 첫 번째 시도에서 멈춘다.

## 돌린 시험

| 명령 | 결과 | exit |
|---|---|---|
| `uv run --no-project python -m pytest tests/test_cli_surface.py tests/cli_boundary.py -q` | 24 passed, 52 subtests passed | 0 |
| 같은 명령으로 `cli`를 건드리는 시험 33개 전부 | 1136 passed, 6 skipped, 1371 subtests passed | 0 |
| `uv run --no-project ruff check src/asgard/cli/__init__.py` | All checks passed | 0 |
| `uv run --no-project ruff format --check src/asgard/cli/__init__.py` | 1 file already formatted | 0 |
| `asgard thor gate` | 막는 판정 없음 (지적 전부 다른 단위의 파일) | 0 |
| `asgard craft` | 내 파일엔 알림 1건, 막는 판정은 다른 단위의 파일 | 1 |

33개 목록은
`grep -rln "cli_boundary\|asgard.cli\|from asgard import cli\|run_cli" tests`로 뽑았다.

`asgard craft`의 알림은 `_REGISTERED`가 실행 중에 줄지 않는다는 것이다. 키가 `_GROUPS`의
이름뿐이라 13개를 넘지 못하고, 값은 typer가 `app`에 이미 매달아 둔 등록 정보를 가리키므로
이 표가 무엇의 수명도 늘리지 않는다. 그 근거를 코드 주석에 적어 뒀다.
`asgard craft`가 exit 1인 것과 `thor gate`의 지적은 전부
`benchmarks/cpu-profile/hotpath.py`·`resident.py`·`src/asgard/hooks/readonly_guard.py` —
이 항목이 손대지 않은 파일이다.

## 이 계측이 못 잰 것

- **`asgard tutor --json`** — 명령 자체가 20초대라 CLI 세금을 분리하지 못했다. 지연은
  걸리지만(그룹 1개) 절감 폭은 안 쟀다.
- **조용한 기계의 값** — 측정 내내 배경 부하가 있었고 같은 저장소의 다른 단위도 돌고 있었다.
  최솟값을 같이 실었고 번갈아 쟀지만, 절대값은 한가한 기계에서 다시 재야 한다. 방향과
  배율은 min·median 두 추정치가 같다.
- **훅 4종의 실제 턴 비용** — 여기서 잰 것은 명령 하나의 벽시계다. 훅 자신의 임포트와
  subprocess 왕복은 `findings-hooktax.md`의 축이고 이 변경이 건드리지 않았다.
