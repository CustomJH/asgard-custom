# 항목 3 — budget-guard 트랜스크립트 증분 스캔 (2026-08-14)

`read_ledger()` 가 매 호출 세션 트랜스크립트를 전량 재스캔하던 것을 **바이트 오프셋
체크포인트**로 바꿨다. 이어받기 읽기는 파일 크기와 무관하게 0.04ms 로 평평하다.

꼬리 N줄 읽기는 쓰지 않았다 — 앞부분을 놓치면 누계가 작아지고 게이트가 막아야 할 때 안 막는
쪽으로 틀린다.

## 무엇을 바꿨나

마지막으로 센 오프셋과 그때까지의 누계를 `.asgard/state/budget-<세션>.json` 에 적고, 다음
호출은 그 뒤에 붙은 바이트만 읽는다.

바꾼 파일:
- `src/asgard/hooks/budget_guard.py` (+246/−36, 653줄)
- `.claude/hooks/budget-guard.py` (배포본, 패키지본과 byte-identical)
- `tests/test_budget_guard.py` (+151, 새 클래스 `TestIncrementalScan` 8건)

`src/asgard/commands/budget.py:180` 은 안 건드렸다. `read_ledger(path, root="")` 로 root 가
선택 인자라 그 호출은 예전대로 전량 스캔이고, 사람이 한 번 부르는 화면이라 값이 안 붙는다.

## 배포본 동기화

관계는 **그대로 복사**다. `src/asgard/hooks/__init__.py` 의 `script()` 가 패키지 소스를 글자
그대로 읽어 배포하고, `asgard_hooklib/` 는 `library_files()` 가 훅 옆에 따로 깐다 — 훅 파일
자체는 변형이 없다. 근거로 변경 전 커밋본끼리 대조했다:
`git show HEAD:src/asgard/hooks/budget_guard.py` == `.claude/hooks/budget-guard.py`. 그래서
`cp` 로 맞추고 `diff -q` 로 확인했다. `asgard sync` 는 안 썼다 — 훅 28개와 AGENTS.md 를 함께
다시 깔아 이 항목 밖으로 diff 가 번진다.

동기화 뒤 배포본에 payload 를 먹여 확인했다 (임시 뿌리, 저장소 상태는 안 건드림):

```
[prompt] exit=0   stdout: [asgard budget] [gate:budget-ceiling] Session spend 60,000,000 ...
[task]   exit=2   stderr: Asgard budget-guard — [gate:budget-ceiling] ...
checkpoint: {"version":1,"offset":120,"head":"15796b06","broken":0,"main":{...,"output":12000000},...}
transcript size: 120  committed offset: 120
```

`.claude/hooks/budget-guard.py` 는 `.gitignore:237` 의 `.claude` 에 걸려 **커밋 diff 에 안
잡힌다**. 판정자가 배포본을 diff 로 못 보니 위 확인이 그 증거다.

## 측정

기계는 조용하지 않았다 — 재는 내내 load average 4.6~11.9, 다른 세션의 pytest 가 돌고 있었다.
세 번 돌려(run2·run3·final) 방향이 같은지 봤고 아래는 final 이다. 트랜스크립트는 **실물 세
개**를 제자리에서 읽었다(`~/.claude/projects/…`, 이미 닫힌 세션이라 재는 동안 안 자란다).
한 크기당 7라운드, 라운드마다 레인 순서를 돌려 순서 효과를 상쇄했다.

### 층 A — `read_ledger()` 한 번, 인프로세스 (min/median ms)

| 크기 | 전 벽시계 | 전 CPU | 후·첫 호출 | 후·이어받기 |
|---|---|---|---|---|
| 99,768 B | 0.19/0.20 | 0.19/0.20 | 0.25/0.28 | **0.03/0.04** |
| 1,378,700 B | 4.02/4.15 | 4.02/4.13 | 3.77/3.83 | **0.04/0.05** |
| 20,928,056 B | 29.07/30.45 | 28.96/30.17 | 31.50/31.80 | **0.05/0.05** |

이어받기 값이 크기와 무관하게 0.04ms 로 평평하다 — 그게 이 변경의 요점이다. 첫 호출은 전량
스캔 + 체크포인트 쓰기라 전과 비슷하거나 20MB 에서 1.4ms 비싸다.

### 층 B — 배포본 훅 한 프로세스, 인터프리터 시작 포함 (min/median ms)

| 크기 | 전 벽시계 | 전 CPU | 후 벽시계 | 후 CPU |
|---|---|---|---|---|
| 99,768 B | 37.36/39.47 | 34.41/35.90 | 39.04/39.31 | 35.55/36.12 |
| 1,378,700 B | 40.86/43.13 | 37.77/40.35 | 39.43/40.04 | 36.16/36.89 |
| 20,928,056 B | 70.36/71.09 | 66.43/67.26 | **39.40/40.47** | **35.93/37.19** |

**작은 트랜스크립트에서는 후가 1~2ms 느리다.** 원인은 스캔이 아니라 **소스 컴파일**이다 —
훅은 호출마다 새 프로세스로 뜨고 `__main__` 스크립트는 매번 컴파일된다: 18,755B 0.97/1.07ms
→ 25,777B 1.60/1.71ms (+0.6ms). 여기에 체크포인트 읽기와 `import zlib` 이 얹힌다. 100KB 에서
아끼는 스캔이 0.16ms 뿐이라 손익이 뒤집힌다. 손익분기는 대략 200~300KB 이고, 트랜스크립트는
줄지 않으므로 세션은 그 지점을 한 번 지나면 안 돌아온다.

지문을 `hashlib.sha1` 로 짰다가 `zlib.crc32` 로 바꾼 것도 이 축에서 잰 값이다 —
`import hashlib` 이 실측 0.9~1.2ms, `import zlib` 이 0.03ms. 매 도구 호출에 붙는 값이라 바꿨다.

### 증분 증거 (1.38MB 사본에 168B 한 줄을 덧붙인 뒤 두 번째 호출)

```
first_call_line_bytes  1,378,700     ← 첫 호출은 전량
second_call_line_bytes       168     ← 덧붙인 만큼만 (appended_bytes 168 과 일치)
second_call_other_reads    4,096     ← 동일성 지문뿐
output_before 210,956 → after 210,990  (delta 34 = 덧붙인 줄의 output_tokens)
```

`builtins.open` 을 세는 껍데기로 감싸 실제로 읽은 줄 바이트를 셌다. 같은 계수를 시험에도 넣었다
(`test_the_second_call_reads_only_the_appended_bytes`).

## 집계 동일성 — 이 항목의 안전 조건

실물 셋에서 변경 전 전량 스캔과 변경 후(첫 호출·이어받기 둘 다)의 집계를 통째로 대조했다 —
main 4성분·역할별 usage·호출 수·모델 수·read_error·cost_units 전부:

```
small  99,768 B    cold_matches true  warm_matches true   cost_units 93,102.15
mid  1,378,700 B   cold_matches true  warm_matches true   cost_units 5,646,959.35
large 20,928,056 B cold_matches true  warm_matches true   cost_units 11,993,353.55
```

시험으로도 고정했다 (`TestIncrementalScan`, 8건):

- `test_totals_match_a_full_scan_as_the_transcript_grows` — 두 레인이 다 든 파일을 세 번 키우며 매번 전량 스캔과 대조
- `test_the_second_call_reads_only_the_appended_bytes` — 증분 증거
- `test_a_shrunken_transcript_is_rescanned_whole` · `test_a_replacement_of_the_same_size_is_not_resumed` · `test_a_corrupt_checkpoint_is_discarded` — 되돌아가는 조건
- `test_an_unterminated_last_line_is_counted_but_not_committed` — 쓰는 중인 줄
- `test_a_tree_without_asgard_gets_no_checkpoint` · `test_a_broken_line_stays_broken_across_calls`

## 되돌아가는 조건 (전량 재스캔)

파일이 줄었거나 저장된 오프셋이 파일 크기를 넘는다 · 앞 4096바이트의 검사합이 다르다(회전·교체)
· 상태 파일이 없거나 JSON 이 깨졌다 · `version` 이 다르다 · 성분에 음수·비정수가 있다.
의심스러운 판은 고쳐 쓰지 않고 통째로 버린다. `.asgard` 가 없는 트리에는 체크포인트를 아예
안 만든다.

확정 규칙 하나 더: **개행으로 끝나지 않은 마지막 줄은 이번 판정에 넣되 체크포인트에는 안
넣는다.** 호스트가 쓰는 중일 수 있어서, 확정하면 다음 호출이 나머지를 새 줄로 읽어 반쪽만
세거나 두 번 센다. 빼면 과소 집계라 안 넣는 쪽도 안전하지 않다.

## 돌린 것과 exit code

| 명령 | 결과 | exit |
|---|---|---|
| `uv run --no-project python -m pytest tests/test_budget_guard.py -q` | 61 passed, 16 subtests | 0 |
| `… tests/test_budget_guard.py tests/test_architecture.py tests/test_mode_parity.py -q` | 101 passed | 0 |
| `… tests/test_openai_api.py tests/heimdall/test_recovery.py tests/test_trinity_baseline.py -q` | 62 passed | 0 |
| `ruff check` / `ruff format --check` (두 파일) | 통과 | 0 |
| `asgard craft` | budget_guard.py 알림 1건 (460행, 문턱 400) — 막지 않음 | 0 |
| `asgard thor gate` | 알림 [2] | 0 |

`thor gate` 는 처음에 `_write_checkpoint` 의 삼킨 예외를 [1] 회귀로 잡았다. 근거 주석을 `pass`
줄에 붙여 내렸다 — 판정기는 주석을 **문 안 statement 의 줄 범위**에서만 찾는다
(`src/asgard/thor_rules.py:236 _justified`), 블록 위에 적으면 못 본다.

## 못 잰 것

- **에이전트 레인이 실물에서 안 잡혔다.** 고른 실물 셋에 `toolUseResult.agentType` 이 든 행이
  하나도 없어 `agent_roles: 0` 이다. 역할별 누계·호출 수의 동일성은 합성 트랜스크립트를 쓰는
  시험에서만 확인했다.
- **실제 세션의 절감 총량.** 한 세션이 훅을 몇 번 부르는지는 이 벤치가 안 잰다. 위 표는 호출
  하나의 값이다.
- **동시 호출.** 훅 두 개가 같은 세션 상태 파일을 겹쳐 쓰는 경우는 안 재 봤다. temp+rename 이라
  찢어진 파일은 안 남고 늦은 쪽이 이기지만, 그 경합을 실측하지는 않았다.
- **Codex·Cursor 실물.** `rollout-*.jsonl` 과 Cursor 기록으로는 안 돌렸다 — 이름짓기는 파일
  이름 기준이라 동작하지만 실측은 Claude Code 기록뿐이다.
- 상태 파일이 세션당 하나씩 쌓인다 — `craftgate-`·`tutor-`·`writes-` 와 같은 규약이라 청소
  책임도 같은 자리에 있고, 이번에 새 청소 경로를 만들지 않았다.
