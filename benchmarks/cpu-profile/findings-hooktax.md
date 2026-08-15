# 훅 프로세스 세금 — 실측 (2026-08-14)

측정: `uv run --no-project python benchmarks/cpu-profile/hook_tax.py --reps 3 --json`.
파이썬 3.14.5, darwin. 이 표의 모든 수치는 그 JSON 에서 기계로 렌더링했다 — 손으로 옮겨 적은 값은 없다.

`%CPU` 는 배경 부하에 흔들려 쓰지 않았다. 대신 `resource.getrusage(RUSAGE_CHILDREN)` 를 호출 앞뒤로 차분해
자식 프로세스의 user+sys CPU 시간만 뽑았다. 측정 중 이 기기에서 다른 세션의 pytest 가 함께 돌고 있었다 —
벽시계는 그만큼 부풀고 CPU 시간은 비교적 견딘다.

## 이벤트별 합계 (웜 기준)

| 이벤트 | 등록 수 | 고유 스크립트 | CPU ms 합 | 벽시계 ms 합 |
|---|---:|---:|---:|---:|
| `SessionStart` | 6 | 6 | 520 | 559 |
| `UserPromptSubmit` | 11 | 11 | 967 | 1033 |
| `SubagentStart` | 10 | 10 | 843 | 901 |
| `PreToolUse` | 9 | 6 | 409 | 449 |
| `PostToolUse` | 3 | 3 | 218 | 233 |
| `SubagentStop` | 2 | 2 | 93 | 102 |
| `Stop` | 5 | 5 | 582 | 618 |

한 프롬프트가 `UserPromptSubmit` 만으로 967ms 의 CPU 를 태운다.

## 스크립트별 (콜드 = `__pycache__` 지운 뒤 첫 호출, 웜 = 그 뒤 반복의 중앙값)

| 훅 | 콜드 벽시계 ms | 콜드 CPU ms | 웜 벽시계 ms | 웜 CPU ms | 무출력 비율 |
|---|---:|---:|---:|---:|---:|
| `scope-activate` | 191 | 184 | 204 | 195 | 0% |
| `map-activate` | 239 | 198 | 194 | 183 | 0% |
| `memory-activate` | 214 | 194 | 169 | 161 | 0% |
| `tutor-note` | 138 | 131 | 134 | 128 | 100% |
| `verifier-gate` | 68 | 62 | 71 | 65 | 100% |
| `verifier-context` | 52 | 48 | 55 | 51 | 100% |
| `subagent-gate` | 53 | 48 | 55 | 50 | 100% |
| `lagom-activate` | 60 | 54 | 54 | 47 | 0% |
| `budget-guard` | 54 | 50 | 50 | 46 | 100% |
| `git-guard` | 51 | 47 | 51 | 46 | 100% |
| `failure-tracker` | 48 | 44 | 50 | 45 | 100% |
| `write-sentinel` | 47 | 43 | 49 | 45 | 100% |
| `charter-activate` | 48 | 44 | 50 | 45 | 100% |
| `release-guard` | 58 | 51 | 50 | 45 | 100% |
| `secret-guard` | 49 | 45 | 49 | 44 | 100% |
| `readonly-guard` | 49 | 44 | 48 | 44 | 100% |
| `siege-inbox` | 47 | 43 | 48 | 44 | 100% |
| `lagom-tracker` | 45 | 41 | 48 | 43 | 100% |
| `craft-gate` | 48 | 43 | 47 | 43 | 100% |
| `agent-activate` | 46 | 42 | 47 | 42 | 100% |
| `manual-activate` | 50 | 46 | 46 | 41 | 0% |
| `dispatch-context` | 40 | 36 | 42 | 39 | 100% |
| `unattended-context` | 43 | 39 | 43 | 38 | 100% |
| `lagom-subagent` | 40 | 37 | 39 | 35 | 0% |

콜드와 웜의 차가 작다. `uv run --no-project python` 이 매 호출 새 인터프리터를 올리므로
바이트코드 캐시로 벌 몫이 원래 작다 — 캐시를 데워도 세금은 거의 그대로다.

## 도구 호출 1회가 띄우는 프로세스

| 도구 | PreToolUse | PostToolUse | 프로세스 수 | CPU ms | 벽시계 ms |
|---|---:|---:|---:|---:|---:|
| `Bash` | 4 | 1 | 5 | 225 | 248 |
| `Write` | 2 | 3 | 5 | 307 | 330 |
| `Edit` | 2 | 3 | 5 | 307 | 330 |
| `NotebookEdit` | 2 | 3 | 5 | 307 | 330 |
| `Agent` | 2 | 1 | 3 | 141 | 154 |
| `Read` | 1 | 1 | 2 | 90 | 98 |
| `Grep` | 1 | 1 | 2 | 90 | 98 |
| `Glob` | 1 | 1 | 2 | 90 | 98 |
| `NotebookRead` | 1 | 1 | 2 | 90 | 98 |

`PreToolUse` 에 `secret-guard` 3회·`readonly-guard` 2회가 등록돼 있지만 **중복이 아니다** —
matcher 가 서로 배타적이라 한 도구 호출에는 최대 1회만 발화한다. 위 표의 `PreToolUse` 열이 그 실제 발화 수다.

## 턴 세금 (Bash 를 대표 도구로)

| 도구 호출 수 | 프로세스 수 | CPU 초 | 순차 벽시계 초 |
|---:|---:|---:|---:|
| 10 | 66 | 3.80 | 4.13 |
| 30 | 166 | 8.30 | 9.09 |
| 60 | 316 | 15.05 | 16.52 |

도구를 60번 부르는 턴이 훅으로만 프로세스 316개와 CPU 15초를 쓴다. 이 값은 부하에 따라 움직인다 —
같은 하네스를 부하 34.4 에서 돌린 앞선 실행은 같은 지점에서 23.11초를 냈다. 자릿수는 같고 배율이 다르다.

## 아무 출력 없이 끝나는 훅

18/24 스크립트가 payload 를 받고 무출력으로 종료한다: `agent-activate`, `budget-guard`, `charter-activate`, `craft-gate`, `dispatch-context`, `failure-tracker`, `git-guard`, `lagom-tracker`, `readonly-guard`, `release-guard`, `secret-guard`, `siege-inbox`, `subagent-gate`, `tutor-note`, `unattended-context`, `verifier-context`, `verifier-gate`, `write-sentinel`.

가드류는 막을 게 없으면 조용한 것이 정상이라 무출력 자체가 결함은 아니다. 세금인 것은 출력이 없다는 사실이
아니라 **그걸 알아내려고 매번 인터프리터를 새로 올린다**는 점이다. `charter-activate` 는 이 저장소에서
영구히 무출력인데도 모든 프롬프트·모든 서브에이전트 시작마다 뜬다 — `.asgard/asgard-setting-project.json`
에 `charter` 키가 없어 `load_charter()` 가 늘 `None` 을 낸다(`.claude/hooks/charter-activate.py:39-56`).

## 이 하네스가 못 재는 것

- Claude Code 가 훅을 병렬로 띄우는지 순차로 띄우는지. 위 벽시계 합계는 순차 상한이다.
- 훅이 부르는 `asgard` 자식 프로세스 안의 내역. 그건 `hotpath.py` 가 잰다.
- 활성 퀘스트가 있을 때의 `verifier-gate` 비용. 합성 세션으로는 그 경로에 들어가지 못한다.
