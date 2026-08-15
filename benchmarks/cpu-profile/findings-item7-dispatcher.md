# 항목 7 — 주입 훅 디스패처 (2026-08-14)

주입 훅 13종을 이벤트당 한 프로세스로 합쳤다. 가드 8종과 증거 훅 3종은 제자리에 둔다.
**출력 동일성을 먼저 증명하고 그 다음에 배선했다.**

## 출력 동일성 — 배선의 선행 조건

`benchmarks/cpu-profile/dispatch_check.py` 로 이벤트마다 지금의 훅들을 각각 돌린 출력과 디스패처
한 번의 출력을 대조했다. 6회차, 전/후를 번갈아, 순서까지 번갈아 뒤집어서.

대조 축을 와이어 형식이 아니라 **채널**로 잡았다. 한 이벤트 안에서 훅마다 형식이 다르기
때문이다 — `map-activate` 는 `hookSpecificOutput.additionalContext`, `lagom-tracker` 는 평문
stdout, `tutor-note` 는 `systemMessage` 를 낸다. 합칠 때 보존해야 하는 것은 봉투가 아니라
**채널별 텍스트와 그 순서**이고, 그 둘이 바이트로 같다. 컨텍스트 8.5~17KB 규모라 빈 대조가 아니다.

## 실측 — 구현했으므로 전후를 잰다

전/후를 번갈아, 최솟값과 중앙값을 둘 다 싣는다. 이 기계는 조용하지 않다(다른 세션의 pytest 가
돈다).

| 이벤트 | 프로세스 | CPU 최소/중앙 (ms) | 벽시계 합 최소 (ms) | RSS 합 (MB) |
|---|---|---|---|---|
| `UserPromptSubmit` | 10 → 1 | 707.5/723.4 → 465.1/478.5 | 751.2 → 184.8 | 292.0 → 50.8 |
| `SubagentStart` | 7 → 1 | 315.5/320.0 → 132.6/134.6 | 344.6 → 137.9 | 164.4 → 35.8 |
| `SubagentStart` (thinker) | 8 → 2 | 410.2/413.5 → 228.0/232.4 | 441.9 → 238.3 | 198.6 → 70.1 |
| `SessionStart` | 6 → 1 | 331.4/346.2 → 197.8/213.5 | 355.4 → 142.1 | 155.8 → 36.0 |
| `Stop` | 3 → 1 | 327.5/346.7 → 272.7/284.1 | 343.7 → 282.6 | 92.1 → 46.4 |

가드까지 세면 이벤트당 프로세스는 `UserPromptSubmit` 11→2, `SubagentStart` 10→4,
`SessionStart` 6→1, `Stop` 5→3 이다 (`hook_tax.py --reps 5` 가 배선을 읽어 확인).

### RSS 는 버는 쪽이었다

임포트가 합쳐져 한 프로세스가 커질 것을 걱정했는데 안 커졌다 — 합친 프로세스가 지는
값(35.8~50.8MB)이 **전에 가장 컸던 훅 하나와 같다.** 설계 문서가 "방향이 자명하지 않다"고 열어
뒀던 축인데, 재 보니 한쪽이었다.

이유는 "훅 본문의 임포트가 작다"가 아니라 **무거운 임포트가 애초에 훅 프로세스에 없다**는 것이다.
앞선 계측이 `asgard.memory`+`asgard.project_memory` 가 16MB 를 얹는다고 쟀는데, `memory-activate`
는 그 모듈들을 임포트하지 않는다 — `shutil.which("asgard")` 로 CLI 를 찾아 자식 프로세스로
넘긴다(`memory-activate.py:229`, `:246-256`). 그 16MB 는 손자 프로세스에 살고, 이 표가 쓰는
`ru_maxrss(RUSAGE_CHILDREN)` 는 합이 아니라 **최댓값**이라 합치기 전후가 같은 값으로 접힌다.
`SessionStart` 실측: before 6 프로세스 합 156.3MB · 가장 큰 하나 36.2MB, after 35.8MB 한 프로세스.

### 벽시계는 조금 냈다

이 호스트는 한 이벤트의 훅을 **병렬로** 띄운다(아래 관측 ①). 순차 디스패처였다면 벽시계를
합으로 늘렸을 것이라, 디스패처는 훅마다 스레드를 쓴다. 병렬로 가정한 before 벽시계(가장 느린
훅 하나)는 `UserPromptSubmit` 150.2ms · `SubagentStart` 125.5ms 이고 after 가 184.8 / 137.9ms 다
— **12~35ms 늘었다.** CPU 183~242ms 을 벌고 벽시계 수십 ms 를 낸 교환이다.

## 도중에 드러난 것 셋

**① 지금의 주입 순서는 배선 순서가 아니었다.** 이 세션이 받은 SubagentStart 주입 블록이
`lagom → dispatch → manual → map` 순서로 왔는데 배선은
`lagom → charter → manual → agent → map → scope → dispatch` 다. 호스트가 완료 순서로 이어
붙인다는 뜻이고, 주입 사이의 구분자가 정확히 개행 하나라는 것도 같은 블록에서 읽었다.
디스패처는 배선 순서로 고정하므로 이 축이 결정론이 된다 — 회귀가 아니라 그 반대다.

**② `doctor` 의 인터프리터 검사에 결함이 있었다.** `_wired_hook_argv` 가 훅 경로만 걸러내고
나머지를 전부 인터프리터 인자로 넘겨서, 묶어 부르는 줄에서 `python -- -c pass` 가 되어 빨간
줄이 났다. 첫 훅 경로 앞에서 자르도록 고쳤고(원래 도크스트링이 적어 둔 계약 그대로),
`tests/test_doctor_shape.py` 에 못을 박았다.

**③ 사람 표면(`systemMessage`) 합치기는 실물 훅으로 한 번도 못 봤다 — 다섯 이벤트 전부.**

첫 판은 이것을 Stop 한 이벤트의 문제로 적었다. 판정이 채널별 바이트를 뽑아 더 넓다는 것을
보였다: 컨텍스트 채널은 `UserPromptSubmit` 8,461 · `SubagentStart` 11,220 · thinker 17,184 ·
`SessionStart` 16,936 바이트가 실려 대조됐지만, **`message_bytes` 는 다섯 이벤트 모두 0** 이다.
Stop 은 두 채널 다 0 이라 그 이벤트만 통째로 빈 대조였다.

즉 `hook_dispatch.py:59` 의 `MSG_JOIN = "\n\n"` 과 `emit()` 의 사람 표면 분기
(`hook_dispatch.py:209-215`)를 고정하는 것은 **합성 훅을 쓴 단위 시험**(`tests/test_hook_dispatch.py:111-127`)
뿐이다. 실물로 못 본 이유는 두 훅이 합성 세션에서 침묵하기 때문이다 — `tutor-note` 는 이 세션의
쓰기 목록이 필요하고, `memory tick` 의 넛지는 한 번만 나오는 래치다. 첫 5회차에서 Stop 이
"다름"으로 나왔던 것도 그 래치였고(먼저 돈 쪽이 넛지를 먹었다), 순서를 번갈아 뒤집자 6회차 연속
동일이 나왔다.

이 구멍이 배선을 막지 않은 근거: `systemMessage` 는 모델 컨텍스트가 아니라 **사람 화면 전용**이라
주입이 조용히 바뀌는 사고를 만들지 못하고, 합치는 규칙 자체는 디스패처를 실제 하위 프로세스로
띄우는 단위 시험이 고정하며, 텍스트는 보존되고 봉투 개수만 바뀐다. 그래도 실물 대조는 아직
빚이다 — 하네스가 사람 표면을 내는 실물 상태를 만들 수 있게 되면 그때 갚아야 한다.

## 배선 표와 다르게 한 것 하나

**thinker 의 SubagentStart 를 8→1 이 아니라 8→2 로 두었다.** `memory-activate` 를 디스패처에
넣으려면 `^asgard-thinker$` matcher 를 지워야 하는데, 그 matcher 가 격리 매트릭스(Verifier·Loki
영구 무주입)의 바깥 겹이다. 지우면 "Thinker 한정" 선언이 훅 안의 검사 하나만 남는다. 아끼는
것은 Thinker 배차 한 번당 프로세스 하나뿐이라 저울이 안 맞는다고 판단했고, 근거를 템플릿
주석에 남겼다. 위 표의 thinker 행은 이 배선된 모양을 그대로 잰 값이다.

## fail-open — 합치면 공짜가 아니다

프로세스가 따로일 때는 한 훅이 죽어도 나머지가 사는 것이 공짜였다. 합치면 설계로 들어가야 한다.
훅마다 `try/except` 로 감쌌고 세 갈래를 시험으로 고정했다 — 본문이 예외를 던지는 훅, 문법
오류로 임포트조차 안 되는 훅과 아예 없는 파일, 0 이 아닌 코드로 끝나는 훅. 셋 다 나머지 주입이
온전히 나오고 디스패처는 0 으로 끝난다.

상한(60초)에 걸린 스레드가 늦게 깨어나 합쳐진 JSON 뒤에 자기 조각을 덧붙이는 일이 없도록,
`main()` 안에서는 통로를 되돌리지 않는다.

> 정정: 첫 판은 그 통로가 보장이라고 적었다. 아니다 — 디스패처를 감싸는
> `asgard_hooklib/firing.py` 의 `run()` 이 `redirect_stdout` 을 쓰므로 `main()` 이 돌아오는
> 순간 통로는 어차피 풀린다. 늦게 깨어난 훅이 호스트가 읽는 JSON 을 못 깨뜨리는 진짜 근거는
> 통로가 아니라 **수명**이다: 스레드가 daemon 이고 `main()` 직후 프로세스가 끝난다.
> 주석도 같이 고쳤다(`hook_dispatch.py:255-259`).

fail-open 시험 하나는 판정이 강도를 지적해서 보강했다. `_run_one` 의 `except BaseException`
(`hook_dispatch.py:195`)을 빼도 **주입 결과는 그대로**라 출력만 보는 검사로는 회귀가 안 잡힌다.
돌연변이로 확인했다 — 원본과 돌연변이 둘 다 컨텍스트가 `'첫째\n셋째'` 로 같고, 갈리는 것은
stderr 다(원본 역추적 없음, 돌연변이 있음). `tests/test_hook_dispatch.py` 의 그 검사에
`assertNotIn("Traceback", err)` 를 더해 그 축을 잡는다.

## `asgard sync` 가 같이 깐 것 — 범위 밖으로 번졌다

`asgard sync --here` 는 7개를 갱신했고 그중 이 항목의 것은 `.claude/settings.json` 과
`.claude/hooks/hook-dispatch.py` 다. 나머지:

- `.codex/hooks/hook-dispatch.py` — 훅 표가 클라이언트별로 갈라지지 않는다는 기존 계약대로 파일만
  깔렸다. `.codex/config.toml` 에는 배선이 없어 동작은 그대로다 (`grep -c hook-dispatch` = 0).
- `.claude/agents/asgard-worker.md` — 내용 diff 는 비었고 mtime 만 갱신됐다.
- `.claude/skills/learned-learned-skill-host-adapter-drift/`, `.agents/skills/learned-*` 둘 —
  자율 진화 층이 스스로 설치한 학습 스킬의 호스트 어댑터다. 템플릿 변경의 산물이 아니다.

작업 트리에 다른 세션의 미완 변경이 여럿 있고(`skill_registry/`, `templates/siege.py`,
`commands/setup.py` 의 스킬 스캐폴딩 재편), sync 는 그 상태의 소스에서 깔았다.

## 회귀

| 대상 | 결과 |
|---|---|
| 필수 3종 + 손댄 파일 9개 | 202 passed |
| 전체 `pytest tests/` | 5623 passed, **1 failed** |
| `asgard craft` · `asgard thor gate` | 둘 다 exit 0 |
| `asgard doctor` | `uv run (hooks)`, `trinity hooks + Stop gate`, memory·map 배선 전부 초록 |
| 배포본 `diff -q` | `src/asgard/hooks/hook_dispatch.py` == `.claude/hooks/hook-dispatch.py` == `.codex/hooks/hook-dispatch.py` |

실패 1건은 `tests/test_thor.py::TestScaffold::test_plan_contains_thor_skills_cc` 이고 이 변경의
것이 아니다 — 다른 세션이 진행 중인 `invocable_skill_bodies` 재편이
`.claude/skills/asgard-thor/SKILL.md` 를 계획에 넣어 나는 실패다.

배선된 줄을 그대로 한 번 돌려 봤다 (`.claude/settings.json` 의 UserPromptSubmit 명령 + 실제
payload) → exit 0, 유효 JSON, 컨텍스트 6,588 바이트. `gate-firing.json` 도 합쳐진 뒤에 훅별로
계속 센다(`map-activate` 916회, `scope-activate` 274회…) — 디스패처가 훅마다 `record` 를 부르고
자기 몫도 `hook-dispatch` 로 센다.

## 가정

- 컨텍스트 구분자는 개행 하나다. 이 세션이 받은 주입 블록에서 읽은 값이지 호스트 문서가 아니다.
- `systemMessage` 구분자는 빈 줄 하나(`"\n\n"`)다. 관측이 아니라 `memory-activate` 가 자기
  메시지들을 잇는 값에 맞춘 것이다.
- Cursor 는 이 디스패처에 안 걸린다. 그쪽 `beforeSubmitPrompt` 에는 컨텍스트 통로가 없어 주입이
  `sessionStart` 에 서고, 통로가 하나뿐이라 사람 표면과 컨텍스트를 한 번에 못 낸다. `.cursor`
  배선은 손대지 않았다.
