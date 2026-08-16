# 인수인계 — 대형 파일 리팩토링 (2026-08-17)

앞 세션이 예산 상한에 닿아 넘긴다. **릴리즈 실패 방지는 끝났고**(아래 ①), 대형 파일
리팩토링은 시작하지 않았다 — 반만 하고 남기는 것보다 계측과 우선순위를 넘기는 쪽을 골랐다.

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
맞추지 않으므로 CI 에 한 단이 늘면 그 순간 빨개진다 (뮤테이션으로 확인: 레시피에서
`ty check` 를 빼면 대조가 죽는다). 레시피는 Justfile 의 **관리 구역 밖**에 있다 — 안에 두면
다음 `asgard just sync` 가 조용히 지운다.

**남은 구멍 하나.** `src/asgard/hooks/release_guard.py:148-150` 은 `--tags`·`--follow-tags`·
`refs/tags/` 가 붙은 push 만 "git tag push" 로 잡는다. `git push origin v0.10.17` 처럼 태그
이름을 그대로 쓰는 꼴은 그물 밖이다. 막는 것이 목적이면 그 자리를 넓혀야 하고, 넓힐지는
오딘이 정할 문제다.

## ② 안 한 것 — 대형 파일

### 게이트가 0을 내는데 실제는 27개다

`asgard health --gate` 는 `severe_files 현재 0 · 기준선 0` 을 낸다. 같은 트리를 직접 세면
**1000행 초과 27개, 800행 초과 60개** (전체 파이썬 863개, 26-08-17 실측). 게이트의 축이
벤더링 자산과 테스트를 안 보기 때문이다. 즉 오딘이 보는 것과 게이트가 재는 것이 다르다.

**첫 결정은 그 축을 넓힐지다.** 넓히면 기준선 0 이 즉시 깨지므로, 기준선을 현재 수로 올리고
래칫만 거는 방식이 현실적이다 (`pyproject.toml` 의 `severe_files`, 그 옆 주석이 근거를 요구한다).

### 실제 대상 — 우리가 쓴 테스트

1000행 초과 27개 중 벤더링(`src/asgard/assets/skill_plugins/**`)은 손대지 않는다. 상류
바이트를 보존하는 스냅샷이고 pyproject 가 이미 그렇게 선언한다. 남는 것이 오딘이 말한 자리다.

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

이 수와 위 표를 곱해 상위 셋만 먼저 가른다. 한 번에 여섯을 건드리면 판정 diff 가 커져
검증이 통째로 느려진다.

### 가르는 규율

- 클래스 경계가 이미 있다. `tests/test_architecture.py` 는 `TestLayeredArchitecture`·
  `TestRoleContract`·`TestPackageInternals`·`TestStudioPackage` 넷이라 파일 넷이 자연스럽다.
- 공유 픽스처는 `tests/<area>_base.py` 로 (선례: `tests/memory/memory_base.py`,
  `tests/trinity_base.py`).
- **시험 개수와 이름이 안 바뀌어야 한다.** 가른 뒤 `pytest --collect-only -q | wc -l` 이
  가르기 전과 같은지로 잰다 — 그게 이 작업의 유일한 완료 증거다.
- `tests/test_architecture.py` 는 자기 자신이 계층 표라 특히 조심할 것. 그 파일을 나누면
  `LAYERS`·`SUBTIERS`·`PACKAGE_TIERS` 를 어디 둘지가 곧 설계 결정이다.

## 시작하는 법

```
cd /Users/yun/develop/personal_space/project/asgard-custom
git log --oneline -5          # 이 인수인계 직전 커밋이 릴리즈 게이트다
just gate                     # 초록에서 출발하는지 먼저 확인
```
