# Conductor 대조 — arXiv 2512.04388 의 평가 축을 Asgard 에 적용

논문: Nielsen, Cetin, Schwendeman, Sun, Xu, Tang. *Learning to Orchestrate Agents in
Natural Language with the Conductor* (Sakana AI, ICLR 2026). RL 로 학습한 7B Conductor 가
문제마다 **워크플로**(자연어 서브태스크 · 배정 worker · 접근 리스트)를 새로 짜서 프런티어
모델 풀을 조율한다.

Asgard 는 학습된 조율기가 아니라 **결정 테이블**(`asgard_hooklib/transition.py`)이다. 그래서
논문의 결과값(GPQA 87.5 같은 것)은 비교 대상이 아니고, **평가 축**만 옮겨올 수 있다.

| 논문 축 | 여기서 재는 것 |
| --- | --- |
| workflow steps (§4.3 — 평균 3 / 상한 5) | DONE 까지의 역할 배정 수 |
| agent calls (Fig 5 비용축) | LLM 턴이 필요한 배정 수 · 실측 서브에이전트 디스패치 수 |
| task adaptivity (Fig 8) | 과업 난이도별 스텝 분포 |
| agent selection (Fig 7) | 배정된 역할·서브에이전트 분포 |
| reward (§3.1 — 0 / 0.5 / 1.0) | 형식 조건(워크플로 성립) → 정답 조건(숨긴 pytest 전건) |
| 베이스라인 (§4.3) | plain 단일 에이전트 · self-reflection 5턴 · Asgard Trinity |

## 두 층

**정책 롤아웃 (0-LLM)** — `policy_rollout.py`. 배포 형태의 훅 CLI 를 격리 git 저장소에서
그대로 돌려, 과업 프로필 12종의 역할 시퀀스를 관측한다. LLM 을 한 번도 안 부르므로 무비용·
결정론이고, 조율 **정책**이 무엇을 배정하는지만 잰다.

```
uv run python benchmarks/conductor/policy_rollout.py            # 기본 정책
REPS=1 VERIFY_LEVEL=high uv run python benchmarks/conductor/policy_rollout.py
```

**라이브 대조 (실 세션)** — `live_run.py` + `batch.sh`. 과업마다 pristine 저장소를
`workspace/bench-conductor/runs/` 에 새로 깔고 (이 저장소는 개발 코드라 세션이 여기서 안 돈다)
`claude -p` 무인 세션을 돌린 뒤 숨긴 pytest 로 채점한다.

```
bash benchmarks/conductor/batch.sh 2       # 3아암 × 3과업 × 2반복 = 18세션
uv run python benchmarks/conductor/aggregate.py
```

과업은 `workspace/bench-cus168/tasks` 를 재사용한다 (숨긴 채점 테스트 포함).

## 못 재는 것

- 논문의 절대 성능(LiveCodeBench·GPQA)은 코딩 하네스 과업과 축이 다르다 — 여기 수치는
  같은 과업·같은 코디네이터 모델에서 조율 계층만 바꾼 상대 비교다.
- plain 아암은 퀘스트 로그가 없어 워크플로 스텝을 관측할 표면이 없다. `agent_calls`(트랜스크립트
  기반)만 세 아암 공통으로 비교 가능하다.
- 반복 수가 작다(아암·과업당 2). 논문은 최대 16회 반복해 평균±표준오차를 낸다.

결과: `REPORT.md`
