# 인수인계 — 대형 파일 리팩토링 (2026-08-17)

**릴리즈 실패 방지(①)와 대형 파일 리팩토링 상위 셋(②)이 끝났다.** 남은 대상과 아직 오딘에게
열려 있는 결정 셋(① 의 정규식 확장·`release_guard` 그물, ② 의 게이트 축)은 각 절 안에 있다.

이 문서를 연 세션은 ① 만 끝내고 예산 상한에 닿아 ② 는 계측과 우선순위만 넘겼다. 다음 세션이
churn×lines 상위 셋을 갈랐고, 여기 그 결과까지 적었다.

## ① 끝난 것 — 릴리즈가 다시 실패하지 않게

`just gate` 가 `release.yml` 의 `quality` 잡과 **같은 여섯 단을 같은 순서로** 돈다.

```
uv sync --group dev
uv run ruff check
uv run ruff format --check
uv run ty check
uv run asgard health --gate
uv run pytest -q -n auto
```

태그를 붙이기 전에 이것을 돌린다. `quality` 가 `release` 잡을 막으므로, 빨간 채로 태그하면
휠이 안 나간다 — v0.10.15·v0.10.16 이 그렇게 릴리즈 없는 태그로 남았다.

`tests/test_release_gate.py` 가 워크플로와 레시피를 양쪽에서 파싱해 대조한다. 목록을 손으로
맞추지 않으므로 CI 에 `- run:` 한 줄짜리 단이 늘면 그 순간 빨개진다 (뮤테이션으로 확인:
레시피에서 `ty check` 를 빼면 대조가 죽는다). 레시피는 Justfile 의 **관리 구역 밖**에 있다 —
안에 두면 다음 `asgard just sync` 가 조용히 지운다.

대조가 못 보는 단이 하나 있다. 파싱이 `^\s*- run: (.+)$` 만 읽으므로 `- name:` 과 `run:` 을
두 줄로 나눠 쓴 단은 세지 않는다. `release.yml` 은 다른 잡에서 이미 그 꼴을 쓰고 있어
(`:24-27`, `:67-68`) 나중 편집이 손을 뻗을 만한 모양이다. quality 잡(`:44-57`)에는 지금 그런
단이 없어 대조는 유효하지만, 그 꼴로 한 단이 늘면 시험은 초록인 채 `just gate` 만 CI 와
갈린다. 정규식을 들여쓴 `run:` 까지 받도록 넓히는 것이 한 줄 수리이고, 넓힐지는 오딘이 정한다.

**남은 구멍 하나.** `src/asgard/hooks/release_guard.py:148-150` 은 `--tags`·`--follow-tags`·
`refs/tags/` 가 붙은 push 만 "git tag push" 로 잡는다. `git push origin v0.10.17` 처럼 태그
이름을 그대로 쓰는 꼴은 그물 밖이다. 막는 것이 목적이면 그 자리를 넓혀야 하고, 넓힐지는
오딘이 정할 문제다.

## ② 대형 파일 — churn×lines 상위 셋 완료 (26-08-17)

### 게이트가 0을 내는데 실제는 24개다

`asgard health --gate` 는 `severe_files 현재 0 · 기준선 0` 을 낸다. `src/`·`tests/` 의 git
추적 파이썬을 직접 세면 **1000행 초과 24개, 800행 초과 57개** (② 를 가른 뒤 실측). 가르기
전에는 27개·60개였고, 줄어든 셋이 이번에 가른 그 셋이다. 게이트의 축이 벤더링 자산과
테스트를 안 보기 때문에 그 24개가 게이트에는 0으로 보인다 — 오딘이 보는 것과 게이트가 재는
것이 다르다.

**첫 결정은 그 축을 넓힐지다.** 넓히면 기준선 0 이 즉시 깨지므로, 기준선을 현재 수로 올리고
래칫만 거는 방식이 현실적이다 (`pyproject.toml` 의 `severe_files`, 그 옆 주석이 근거를 요구한다).

### 실제 대상 — 우리가 쓴 테스트

1000행 초과분 중 벤더링(`src/asgard/assets/skill_plugins/**`)은 손대지 않는다. 상류 바이트를
보존하는 스냅샷이고 pyproject 가 이미 그렇게 선언한다. 남는 것이 오딘이 말한 자리다 — 지금
기준으로 24개 중 10개다.

아래는 **가르기 전** 실측이고, 축이 행수뿐이라 실제로 고른 셋과는 다르다. 이 표의 둘
(`test_map_graph.py`·`test_architecture.py`)이 갈렸고, 갈린 셋째(`test_agent.py`)는 1,195행이라
여기 없다. 새 자리는 아래 "가른 것" 표에 있다.

| 행수 | 파일 |
| --- | --- |
| 2112 | `tests/test_map_graph.py` |
| 1810 | `tests/test_project_memory.py` |
| 1715 | `tests/test_architecture.py` |
| 1662 | `tests/test_evolution.py` |
| 1498 | `tests/test_memory_bridge.py` |
| 1422 | `tests/test_memory_dashboard.py` |

### 고르는 축은 행수가 아니다

이 저장소가 이미 기록해 둔 것이 있다 — 분해는 되감긴다(831줄이 3주 만에 11파일 1000줄 초과로).
그래서 **churn × lines** 로 고른다. 자주 안 바뀌는 큰 파일은 나눠도 값이 안 나온다.

```
git log --since=3.months --name-only --pretty=format: -- tests/ \
  | sort | uniq -c | sort -rn | head -20
```

이 수와 위 표를 곱해 상위 셋만 먼저 갈랐다. 한 번에 여섯을 건드리면 판정 diff 가 커져
검증이 통째로 느려진다.

### 가른 것

축을 행수에서 churn×lines 로 바꾸자 순서가 바뀌었다. `tests/test_agent.py` 는 1,195행이라
위 행수 표에 없지만 churn 37 이 붙어 2위로 올라오고, `tests/test_project_memory.py`
(1,810행·churn 15)는 뒤로 밀린다.

| churn×lines | churn | 가르기 전 행수 | 가른 결과 |
| --- | --- | --- | --- |
| 90,895 | 53 | 1,715 | `tests/architecture/` — 8파일, 최대 624행 |
| 44,215 | 37 | 1,195 | `tests/agent/` — 7파일, 최대 464행 |
| 40,128 | 19 | 2,112 | `tests/map_graph/` — 8파일, 최대 487행 |

형상은 `tests/heimdall/` 선례를 따랐다 — `__init__.py` 를 둔 패키지에 공용 모듈 하나,
`from <패키지>.<공용> import ...`. `tests/memory/` 의 flat-base 꼴(`from memory_base import`)은
pytest 의 rootdir sys.path 삽입에 기대므로 디렉터리가 늘면 이름이 부딪친다.

완료 증거는 시험 197건의 `Class::test` 이름 집합이 가르기 전과 **diff 0** 인 것이다. 개수만
세면 이름이 바뀌어도 통과하므로 이름 집합으로 잰다.

### 다음 셋 — 같은 축

| churn×lines | churn | 행수 | 파일 |
| --- | --- | --- | --- |
| 27,150 | 15 | 1,810 | `tests/test_project_memory.py` |
| 26,964 | 18 | 1,498 | `tests/test_memory_bridge.py` |
| 26,592 | 16 | 1,662 | `tests/test_evolution.py` |

### 가르면서 알게 된 것

- **클래스 경계가 답이 아닌 파일이 있다.** `test_architecture.py` 는 1,715행 중 1,192행이
  클래스 앞 서문이고 시험 클래스 넷은 464행뿐이었다. 클래스로만 갈랐으면 1,192행짜리 공용
  모듈 하나가 남아 아무것도 안 줄었다. 실제 경계는 서문 안에 있었다 — 표(`LAYERS`·`SUBTIERS`)
  와 표(`PACKAGE_TIERS`)와 AST 헬퍼가 각각 다른 것을 한다.
- **`__file__` 상대 상수는 한 층 깊어지면 깨진다.** `SRC` 가 그랬고 16건 중 9건이
  `FileNotFoundError` 로 죽었다. `".."` 하나를 더 넣어 고쳤다.
- **옮긴 파일을 이름으로 부르던 주석이 24곳 있었다.** `src/` 10곳, 배포된 훅 사본 12곳
  (`.claude/hooks`·`.codex/hooks`), `tests/` 2곳(`test_craft_gate_e2e.py`·
  `test_quest_log_standalone.py`). 배포 사본은 소스와 바이트 동일이어야 해서 같이 고쳤고,
  고친 뒤 12쌍 모두 다시 동일하다. `benchmarks/**` 의 네 곳은 날짜 박힌 실측 기록이라
  그때 돌린 명령 그대로 둔다 — 그중 하나(`findings-item5-tutor-fanout.md:81`)는 `tests/`
  접두어 없이 `test_architecture.py` 로만 적혀 있어 경로로 훑으면 안 잡힌다.
- **계층 시험은 자기 자신을 안 본다.** 16건 모두 `SRC` 아래만 훑고 `tests/` 를 훑지 않아
  이 가르기가 자기 판정을 흔들지 않았다.
- **`severe_files` 는 이 가르기로 안 움직인다.** 소스 파일만 세기 때문이다
  (`src/asgard/health.py:577`). 셋을 갈라 1000행 초과가 27개에서 24개로 줄었는데도 게이트는
  0을 유지한다 — 위 "게이트가 0을 내는데 실제는 24개다" 결정이 아직 열려 있는 이유가 그것이다.

## 시작하는 법

```
cd /Users/yun/develop/personal_space/project/asgard-custom
just gate                     # 초록에서 출발하는지 먼저 확인
```

이어서 가른다면 위 "다음 셋" 표부터다. 순서를 다시 재려면 churn 명령을 그대로 돌려
현재 행수와 곱한다 — 상위 셋이 갈린 뒤라 순위가 이미 한 번 바뀌었다.
