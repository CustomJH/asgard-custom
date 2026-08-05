# Conductor 대조 + trinity-orchestrator.html §8 재검증 — 2026-08-06

두 가지를 함께 잰다.

1. **Conductor 대조** — arXiv 2512.04388 (Sakana AI, ICLR 2026) 의 평가 축을 Asgard 조율
   계층에 적용. 논문의 절대 수치가 아니라 **축**을 옮긴 것이다 (축 대응표는 `README.md`).
2. **문서 재검증** — `ref/docs/trinity-orchestrator.html` v1.4.1 §8 의 수치를 HEAD 에서 다시 잰다.
   그 표의 전제는 2026-07-02 측정 + 2026-07-10 3군 벤치였고, 07-13 에 한 번 재측정됐다.

환경: Apple Silicon · python 3.14 · HEAD `a9fb3224` · Claude Code 2.1.222 · 코디네이터 모델
`claude-opus-5[1m]` (문서의 3군 벤치는 opus-4-8).

---

## 1. 정책 롤아웃 — 0-LLM (`policy_rollout.py`)

배포 형태의 훅 CLI 를 격리 git 저장소에서 그대로 돌려, 과업 프로필 12종의 역할 시퀀스를
관측했다. LLM 호출 0회, 결정론 (반복 2회 전건 동일).

| profile | tier | steps | llm | verify_level | 시퀀스 |
| --- | --- | --- | --- | --- | --- |
| readonly | 0 | 0 | 0 | — | `DIRECT_DONE` |
| tiny-tested | 1 | 2 | 1 | micro | `WORKER → BASELINE_VERIFY → DONE` |
| small | 2 | 2 | 2 | micro | `WORKER → VERIFIER → DONE` |
| medium | 3 | 2 | 2 | micro | `WORKER → VERIFIER → DONE` |
| large (8파일·400줄) | 4 | 2 | 2 | micro | `WORKER → VERIFIER → DONE` |
| sensitive (`.claude/hooks/`) | 4 | 2 | 2 | micro | `WORKER → VERIFIER → DONE` |
| ambiguous | 3 | 2 | 2 | micro | `WORKER → VERIFIER → DONE` |
| parallel | 4 | 3 | 3 | micro | `THINKER → WORKER → VERIFIER → DONE` |
| research | 4 | 4 | 4 | micro | `WORKER → THINKER → WORKER → VERIFIER → DONE` |
| fail-1 | 3 | 4 | 4 | micro | `WORKER → VERIFIER → WORKER_RETRY → VERIFIER → DONE` |
| fail-3 | 5 | 9 | 9 | micro | `… WORKER_RETRY ×3 → THINKER_REPLAN → … → DONE` |
| destructive | 5 | 0 | 0 | — | `ESCALATE_ODIN` |

전체 평균 **2.67 스텝 / 2.58 LLM 호출**, 쓰기 과업만 **2.91 / 2.82**, 최대 9.
→ 논문이 보고한 Conductor 평균 **3 스텝(상한 5)** 과 같은 구간이다.

### 발견 — 적응의 축이 다르다

논문 Fig 8 의 핵심은 **어려운 과업에 스텝을 더 쓴다** (MMLU 1~2 → LiveCodeBench 3~4). Asgard 는
다르다:

- **사전 적응이 스텝 축에는 없다.** `large`(8파일·400줄)·`sensitive`·`ambiguous` 가 `small`
  과 똑같이 2스텝이다. 난이도 tier 별 평균은 0 → 2.0 → 2.0 → 2.67 → 2.75 → 4.5 로 오르지만,
  그 상승분은 **전부 실패 이후의 재시도**(fail-1, fail-3)에서 온다.
- **사전 적응은 검증 강도 축에 있다.** `VERIFY_LEVEL=high` 로 다시 돌리면 medium·large·
  sensitive·parallel 이 `full` 로 올라간다 (스텝 수는 그대로 2). 기본 설정
  `verify_level: "low"` 에서는 `full_verify_required` 가 항상 False 라 **전 프로필이 micro** 다.

즉 Asgard 의 조율은 **반응형**(관측된 FAIL 뒤에 깊어짐)이고, Conductor 는 **예측형**(문제를 보고
미리 깊게 짬)이다. 스텝 예산을 사전에 배분하는 자리가 비어 있다.

### 발견 — 문서 §6 전이 결정 테이블이 코드와 어긋난다

`ref/docs/trinity-orchestrator.html` §6 의 9행 중 3행이 현재 코드와 다르다.

| 문서 §6 행 | 실제 (`transition.py` + 기본 정책) |
| --- | --- |
| `ambiguous_scope + has_write` → THINKER | **WORKER** — 단일 Worker 가 같은 도구 문맥에서 계획·실행 (코드 주석에 근거 명시) |
| `sensitive_path / 큰 diff` → THINKER → WORKER → **FULL_VERIFIER** | **WORKER → VERIFIER(micro)** — THINKER 없음. full 은 `verify_level` 이 high/full 일 때만 |
| 작은 write → WORKER → MICRO_VERIFIER | 게이트-우선 조건(≤25줄·비민감·테스트 있음)이면 **BASELINE_VERIFY** (0-LLM) — 문서에 없는 경로 |

나머지 6행(destructive·3-실패·write 없음·FAIL 경미·FAIL 구조적·PASS)은 일치한다.

---

## 2. 결정론 마이크로벤치 — HEAD 재확인

문서 §8 "결정론 마이크로벤치" 행의 after 측 수치를 HEAD 에서 그대로 다시 냈다.

| 문서 주장 (after) | HEAD 실측 | 판정 |
| --- | --- | --- |
| sensitive 오탐 0/8 | synth FP **0/8** (TP 6/6 유지) | 일치 |
| classify LLM-free 19/20 | **19/20** | 일치 |
| FAIL→재계획 3턴 | **3턴** | 일치 |
| ESCALATE 전이 즉시 표면화 | `next_role=ESCALATE_ODIN` | 일치 |

---

## 3. 라이브 대조 — 3아암 × 3과업 × 2반복 (18세션)

논문 §4.3 의 대조 구성. 아암은 `plain`(단일 에이전트) · `reflect`(자기 반성 5턴, 논문의
self-reflection 베이스라인) · `asgard`(Trinity 조율). 과업은 t6-pagination(쉬움, off-by-one) ·
t5-dates(중간, 타임존 버그) · t3-config(어려움, 숨은 caller 리팩터). 채점은 숨긴 pytest.

### 품질 — 세 아암 전부 만점, 변별 없음

| arm | t6 | t5 | t3 | Avg reward |
| --- | --- | --- | --- | --- |
| plain | 1.00 | 1.00 | 1.00 | **1.00** |
| reflect | 1.00 | 1.00 | 1.00 | **1.00** |
| asgard | 1.00 | 1.00 | 1.00 | **1.00** |

18/18 세션이 숨긴 테스트를 전건 통과했다 (r=1.0). **이 과업 집합은 opus-5 에서 더 이상
변별하지 못한다.** 문서 §8 이 근거로 삼은 "t3 숨은-caller plain 0/4 vs trinity 2/2" 는
opus-4-8 시점 수치이고, 지금 plain 은 t3 를 2/2 로 통과한다. 조율의 품질 이득을 이 벤치로는
더 못 잰다 — 변별하려면 더 어려운 과업이 필요하다.

### 비용 — 여기서만 아암이 갈린다

| arm | n | reward | agent_calls | cost(중앙값) | wall(중앙값) | turns |
| --- | --- | --- | --- | --- | --- | --- |
| plain | 6 | 1.00 | 0.00 | $0.55 | 86s | 16 |
| reflect | 6 | 1.00 | 0.00 | $1.02 | 188s | 24 |
| asgard | 6 | 1.00 | 0.67 | $1.87 | 308s | 22 |

plain 대비 세금: reflect **1.88× 비용 / 2.20× 시간**, asgard **3.43× 비용 / 3.60× 시간**.

### 조율 노력이 난이도와 반대로 간다

| 과업 | 난이도 | workflow steps | 서브에이전트 호출 | 검증 명령 |
| --- | --- | --- | --- | --- |
| t6-pagination | 쉬움 | 3.0 | 1.0 | 9.0 |
| t5-dates | 중간 | 3.5 | 1.0 | 12.0 |
| t3-config | **어려움** | 3.0 | **0.0** | **1.5** |

논문 Fig 8 이 보인 것과 방향이 반대다. 가장 어려운 t3-config 에서 조율 계층이 **가장 적게**
움직였다 — 서브에이전트를 한 번도 안 부르고(모드 A 내재 순환), 검증 명령도 1~2회에 그쳤다.
쉬운 t6·t5 에서는 Verifier 를 독립 컨텍스트로 띄우고 9~12개 명령을 돌렸다.

원인은 로그에서 보인다: t3 세션은 criteria 에 `verify:` 계약 명령을 하나 달았고, 하네스가 그
명령 하나를 다시 돌려 exit 0 을 확인한 것으로 PASS 가 성립했다. 계약이 붙으면 검증 밀도가
**계약 명령 수로 수렴한다** — 어려운 과업일수록 계약을 한 줄로 쓰기 쉬우니, 검증이 얕아지는
쪽으로 압력이 걸린다.

문서 §8 "verifier 검증 명령 9~11/세션" 은 t6(9.0)·t5(12.0) 에서는 성립하고 t3(1.5) 에서는
깨진다.

### 배정 분포 (Fig 7 축)

라이브에서 실제로 뜬 서브에이전트는 `asgard-verifier` 4건이 전부다. Worker·Thinker 는 한 번도
독립 컨텍스트로 분리되지 않았다 — 코디네이터가 직접 실행했다.

---

## 4. DIRECT 무세금 — §8 S5 재측정

읽기 전용 질의(코드 설명 요청) 2반복. `direct_overhead.py`.

| arm | cost(중앙값) | wall(중앙값) | turns | quest 개설 | 소스 변경 |
| --- | --- | --- | --- | --- | --- |
| plain | $0.350 | 45s | 10 | 0 | 0 |
| asgard | $0.618 | 55s | 8 | 0 | 0 |

**오버헤드 1.77× 비용 / 1.22× 시간.**

- 루프 세금은 여전히 0 — quest 미개설, 게이트 미관여, 소스 변경 0 (dirty 는 훅이 만든
  `__pycache__` 뿐). 문서의 "read-only → 원장·게이트 미관여" 는 성립한다.
- 그러나 **컨텍스트 몫이 커졌다.** 문서 S5 는 $0.535 vs $0.479 = 1.12× 였고,
  `workspace/bench-cc/SPEC.md` 의 통과선 D1 은 ≤1.2× 다. 지금은 1.77× — **통과선 초과**.
  주입면(AGENTS.md·지도·기억 회수)이 그 사이 늘어난 만큼 읽기 전용 질의가 그대로 부담한다.

## 5. 하네스 레이턴시 — §8 표 재측정 (회귀)

`workspace/bench-cc/perfbench.py` 재실행. 훅을 배포 형태 그대로 매회 새 프로세스로,
median N=30 (풀루프 N=10). 다른 벤치가 전부 끝난 뒤 단독 실행.

| 항목 | 문서 07-02 | 07-13 재측정 | **08-06 실측** | 판정 |
| --- | --- | --- | --- | --- |
| verifier-gate allow | 87.0 ms | 78.8 ms | **248.0** (p95 264.4) | **3.1× 회귀** |
| verifier-gate (quest 미사용) | 24.3 ms | 18.8 ms | 24.7 (p95 25.9) | 문서 수준 복귀 |
| quest-log state | ~97 ms | 97.7 ms | **195.0** (p95 200.6) | **2.0× 회귀** |
| quest-log next | ~97 ms | 98.5 ms | **195.6** (p95 202.9) | **2.0× 회귀** |
| write-sentinel | 16.5 ms | 13.1 ms | 16.8 (p95 17.5) | 문서 수준 |
| 풀루프 (6콜) | 564 ms | 385.9 ms | **1734.4** (p95 1781) | **4.5× 회귀** |
| subagent-gate | — | 13.7 ms | 27.5 (p95 29.1) | 2.0× |

갈린 자리가 뚜렷하다. **git 을 부르는 경로만 2~3배**로 늘었고(gate allow · quest-log
state/next · 풀루프), 순수 python 경로(write-sentinel 16.8 · gate no-quest 24.7)는 문서
수치 그대로다. 풀루프 1734ms 는 콜당 195~248ms × 6 과 정합하므로 별도 원인이 아니라 콜
단가 상승의 합이다.

복잡도 주장은 유지된다:

| 규모 | gate | next |
| --- | --- | --- |
| 10×100 | 253.8 ms | 201.3 ms |
| 50×500 | 264.1 ms | 210.9 ms |
| 200×1000 | 312.8 ms | 289.6 ms |

20배 diff 에 gate +23% · next +44% — 문서의 "diff 크기에 사실상 상수" 는 07-13(+10%)보다
약해졌지만 여전히 상수급이다. 이벤트 축(10 → 100 → 1000)은 next 200.8 → 203.7 → 166.7 로
평평 — 실용 구간 O(1) 확인.

한계: 측정 중 이 세션(Claude Code)이 상주해 있었다. 07-13 측정도 같은 조건이었고 p95/median
간격이 좁아(248/264) 안정적인 관측이지만, 완전 무부하 기준선은 아니다.

---

## 6. 문서 §8 주장 대조표

| 문서 주장 (v1.4.1) | HEAD 실측 | 판정 |
| --- | --- | --- |
| verifier-gate allow 87.0 ms | **248.0 ms** | **3.1× 회귀** |
| quest-log state/next ~97 ms | **195 ms** | **2.0× 회귀** |
| 풀루프 564 ms | **1734 ms** | **3.1× 회귀** |
| write-sentinel 16.5 ms · gate no-quest 24.3 ms | 16.8 · 24.7 | 일치 |
| gate 는 diff 크기에 사실상 상수 | 20배 diff 에 +23% | 성립 |
| 세금 3.39× 비용 | **3.43×** | 일치 |
| 세금 6.90× 시간 | **3.60×** | 개선 (문서보다 낮음) |
| t3 숨은-caller plain 0/4 vs trinity 2/2 | plain **2/2** · trinity 2/2 | **무효** — 모델 세대 변화로 변별 소멸 |
| 성공 plain 4/6 vs 최종 5/6 | 세 아암 전부 6/6 | **무효** — 천장 |
| verifier 검증 명령 9~11/세션 | t6 9.0 · t5 12.0 · **t3 1.5** | 부분 성립 |
| 게이트 헛차단 0회 | 차단 1회(t5-dates-asgard-r1), 세션은 수리 후 PASS | 성립 (헛차단 아님) |
| S5 DIRECT 오버헤드 1.12× (통과선 ≤1.2×) | **1.77× 비용** / 1.22× 시간 | **초과** — 주입면 증가분 |
| sensitive 오탐 0/8 | 0/8 | 일치 |
| classify LLM-free 19/20 | 19/20 | 일치 |
| FAIL→재계획 3턴 | 3턴 | 일치 |
| ESCALATE 즉시 표면화 | `ESCALATE_ODIN` | 일치 |
| 멀티 검증 36/36 PASS | 트리니티 5파일 **367 passed** (+24 subtests) · 0 fail · 100.5s | 성립 (범위가 커짐) |
| §6 전이 테이블 9행 | 6행 일치 · **3행 드리프트** | 문서 갱신 필요 |

## 7. 결론

**Conductor 축에서 본 Asgard.** 스텝 예산은 논문과 같은 구간에 있다 (2.67 vs 3). 다른 것은
그 예산을 **언제** 쓰느냐다. Conductor 는 문제를 보고 미리 깊게 짜고(Fig 8), Asgard 는 실패를
보고 나서야 깊어진다. 정책 롤아웃에서 `large`·`sensitive`·`ambiguous` 가 `small` 과 같은
2스텝이었고, 라이브에서는 한 발 더 나가 **가장 어려운 과업에서 조율이 가장 얕았다**
(서브에이전트 0회·검증 명령 1.5회).

**빈 자리 하나.** 난이도를 사전에 읽어 스텝 예산을 배분하는 자리가 없다. 현재 사전 신호
(`sensitive_path`·diff 질량)는 **검증 강도**(micro/full)로만 흐르고, 그마저 기본
`verify_level: "low"` 에서 꺼져 있다. 논문이 보인 것은 이 자리를 학습으로 채우면 스텝 수가
난이도를 따라간다는 것이다.

**회귀 하나.** 조율 정책과 별개로 하네스 콜 단가가 07-13 이후 2~3배 올랐다 — git 을 부르는
경로만 그렇고 순수 python 경로는 그대로다. 과업당 지불하는 하네스 세금이 386ms → 1734ms 다.

**이번 벤치가 못 잰 것.** 품질 축이 천장에 닿아 조율의 이득을 못 쟀다. 세 아암 18세션 전부
만점이라 비용 차만 남았고, 그 상태에서 조율은 순수 비용이다 (3.43×). 조율이 값을 하는 구간을
보려면 지금 과업보다 어려운 집합이 필요하다 — 문서 §8 의 품질 우월 주장은 그 집합이 생길
때까지 **미검증**으로 두는 것이 맞다.

---

## 8. 보완 패치 — 깊은 변경의 증거 하한 (`thin-evidence`)

§3 이 찾은 구멍을 그대로 막았다. 증거를 "있는가"로만 물으면 계약 명령 한 줄이 어떤 크기의
변경도 닫는다 — 그리고 실패가 안 나면 3-실패 재계획도 안 돌므로, 안 깨진 깊은 변경은 얕은
채로 종결된다.

**바뀐 것**

| 자리 | 내용 |
| --- | --- |
| `evidence.evidence_items` | 성공 증거를 출처별로 모은다 — `baseline`(하네스가 프로젝트 체크 직접 실행) · `contract`(criteria 선언 → 하네스 재실행) · `adhoc`(Verifier 가 고른 명령). 같은 명령 문자열은 한 번만 센다 |
| `evidence.evidence_breadth` | 그 수 |
| `transition.completion_decision` | `full_verify_risk` 이면 증거 `MIN_DEEP_EVIDENCE`(=2) 미만은 `thin-evidence` 로 거부 → 전이는 VERIFIER 재검증으로 보낸다 |
| `verifier_gate` | Stop 에서 같은 기준으로 차단 (단일 출처) |
| `summary` | `pass_evidence_breadth` · `pass_evidence_kinds` 를 상태에 노출 — 무엇으로 통과했는지가 로그에 남는다 |

위험 축은 `full_required` 가 아니라 raw `full_verify_risk` 를 쓴다. `full_required` 는
`verify_level` 에 얹혀 있고 기본값이 `low` 라 항상 False 이므로, 거기에 걸면 이 하한이 기본
설정에서 통째로 꺼진다.

**작은 변경은 그대로.** 하한은 위험 축에만 걸린다 — 비민감 · non-test 2파일/80줄 이하 변경은
종전처럼 증거 하나로 닫힌다 (기본 low 의 속도 선택 유지).

**검증** — `tests/test_trinity.py::TestDeepEvidenceFloor` 5건 신규:
깊은 변경 + 증거 1 → 거부 · 증거 2 → 승인 · 같은 명령 2회 → 1개로 계산(복사로 못 넘김) ·
작은 변경 + 증거 1 → 승인 · 게이트가 같은 PASS 를 같은 코드로 차단.
기존 시험 9건이 함께 걸렸다 — 전부 깊은 변경(민감 경로 또는 다중 파일 웨이브)을 명령 하나로
통과시키던 픽스처다. 각 시험이 원래 보던 축(micro/full 라우팅 · 지도 갱신 · 웨이브 배선)을
계속 보도록 공용 픽스처 둘(`TrinityBase.verify`, `test_heimdall.verifier`)의 기본 증거를 둘로
넓혔다. 이 실패 9건 중 5건은 트리니티 5파일만 돌렸을 때 안 보였고 전체 스위트에서 드러났다.

**테스트 피라미드 / 관측 루프에서 가져온 것과 안 가져온 것.**
가져온 것은 "증거는 하나가 아니라 층"이라는 축이다 — `pass_evidence_kinds` 가 출처 세 층을
판정 입력이자 관측 표면으로 남긴다. 안 가져온 것 둘:
- **unit/integration/e2e 자동 분류로 게이팅.** 명령 문자열에서 층을 추정하려면 손으로 짠
  패턴 목록이 필요하고, 이 저장소에서 그 방식은 오탐과 구멍이 번갈아 나는 이력이 있다.
  층 이름을 붙이는 대신 출처(위조 난이도)로 갈랐다.
- **Metric · Trace 계층.** 지금 남는 건 Log(무슨 일이 있었나)뿐이다. "얼마나 걸렸나 ·
  어디서 느려졌나"는 §5 의 레이턴시 회귀와 함께 별도 작업으로 남긴다.
