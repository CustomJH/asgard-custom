# 항목 5 — tutor 의 git 팬아웃 (2026-08-14)

증가 축이 끊겼다. tutor 한 번의 `surface` git 호출이 저장소의 미커밋 `.py` 수와 무관하게
상수가 됐다 — 실측 103회 → 2회 (N=50).

## 무엇이 틀려 있었나

진단은 씨앗보다 한 자리 더 나왔다. `surface.diff(root, base)` 를 부르는 자리가 **둘**이고,
둘 다 결과를 나중에 버린다.

1. `src/asgard/tutor/lesson.py:40 review()` → `tutor/contracts.py:_surface_points()` — 나무
   전체를 대조한 뒤 `review` 가 40~47행에서 `scope = set(named)` 로 잘라낸다.
2. `src/asgard/tutor_teach.py:481 _symbol_terms()` — 나무 전체를 대조한 뒤 쓰는 것은 전부
   `path in scope` 로 거른 뒤다. 게다가 `diff.obligations` 를 한 번도 안 읽는데
   `with_candidates=True` 라, 파괴적 변화가 있으면 나무의 `.py` 를 전부 여는 순회가 한 벌 더 돌았다.

그래서 호출 수가 `2N + 3` 이었다(N = 미커밋 표면 `.py`). 훅은 언제나 `--path` 로 세션 경로만
넘기므로(`hooks/tutor_note.py:134`), 그 밖의 파일에 대한 `git show` 는 전부 버려질 값이었다.
`_unstaged_gaps` 의 `changed_python` 재호출은 같은 답을 두 번 사 오는 세 번째 자리였다.

## 고친 것 — 사다리 ① (필요 없는 호출을 안 한다)

- `src/asgard/surface.py` — `changed_python(root, base, scope=())` 이 `scope` 를 git pathspec 으로
  넘긴다. `diff(..., scope=())` 가 그대로 전달하고, 고른 대상 목록을 `SurfaceDiff.paths` 로
  싣는다(기본값 있는 새 칸이라 기존 호출부는 그대로).
- `src/asgard/tutor_teach.py` — `_symbol_terms` 가 `scope=tuple(sorted(scope)), with_candidates=False`
  로 부른다. `_unstaged_gaps(scope, seen, tracked)` 는 `diff.paths` 를 받아 쓰고 자기 `git diff`
  를 안 부른다.
- `src/asgard/tutor/contracts.py` · `src/asgard/tutor/lesson.py` — `_surface_points(root, base, scope)`
  로 지목 경로를 내려보낸다. `review` 의 사후 필터는 남겼다 — 값이 싸고, `_surface_points` 가
  나중에 diff 밖에서 경로를 얻어 오더라도 이 턴의 물음이 지목 밖으로 새지 않는다는 불변식을
  거기서 지킨다.

  > 정정: 이 절의 첫 판은 필터를 남긴 이유를 "git 은 pathspec 을 줘도 이름이 바뀐 짝을 양쪽
  > 경로로 돌려준다"고 적었다. **반대다.** 이 저장소의 rename 커밋 `14689bf` 로 확인했다 —
  > `git diff --name-only 14689bf^ 14689bf -- '*delivery.py'` 는 `delivery.py` 만,
  > `-- '*dispatch.py'` 는 `dispatch.py` 만 돌려준다. pathspec 을 주면 지목한 쪽만 나오므로
  > 짝이 섞이는 일이 없다. 필터는 무해하지만 그 이유는 사실이 아니었다.
- `tests/test_surface.py` — `test_scope_keeps_the_fan_out_off_untouched_files` 하나 추가.
  지운 시험 없음.

캐시는 안 만들었다. 사다리 ①로 중복이 사라져서 ②·③이 필요 없어졌다.

## 실측

`asgard tutor --json` 경로에는 모델 호출이 없다(전 구간 결정론). 그래서 벽시계가 그대로 비교
가능하고 분리할 20초대 구간도 없다. 기계는 조용하지 않아 번갈아 재고 min/med 를 둘 다 싣는다.
측정은 이 저장소의 **사본**에서 했고 원본 작업 트리는 안 건드렸다.

### 축 실험 — 임시 클론, `--path AGENTS.md` 하나 고정, 미커밋 `.py` 수 N만 바꿈, 회차 5

| N | surface git 호출 (전 → 후) | 총 git (전 → 후) | 벽시계 min ms | 벽시계 med ms |
|---:|---:|---:|---:|---:|
| 0 | 3 → 2 | 8 → 7 | 166 → 141 | 171 → 149 |
| 5 | 13 → 2 | 18 → 7 | 275 → 128 | 278 → 140 |
| 20 | 43 → 2 | 48 → 7 | 718 → 150 | 727 → 155 |
| 50 | 103 → 2 | 108 → 7 | 1461 → 136 | 1570 → 142 |

전은 N에 정확히 비례(`2N+3`), 후는 N과 무관하게 2다. 그것이 이 항목의 요점 — 절감 폭이 아니라
**축이 끊긴 것**이다.

### 실제 작업 트리를 얹은 사본 (미커밋 `.py` 18개), `--path AGENTS.md src/asgard/hooks/budget_guard.py`, 3쌍 번갈아

surface 호출 29 → 4, 총 git 39 → 14. 벽시계 min 1465·1517·1620 → 1053·1067·1152 ms,
med 1535·1532·1979 → 1072·1128·1286 ms. git 구간 min 745·779·818 → 384·372·409 ms.

## 출력 대조 — 설명이 얕아지지 않았나

6개 시나리오 전부 페이로드 **바이트 동일**:

- N=0/5/20/50 (`AGENTS.md`)
- 새 공개 심볼 + 계약 파괴 + 추적 안 되는 새 파일이 함께 있는 경우 (N=0, N=30)
- 이름 변경 + 파일 삭제를 지목한 경우 (57 → 6 호출, 1702 → 848 ms)
- `--path` 없는 나무 전체 호출 (29 → 28, 벽시계 min 3882 → 3876 — scope 가 어차피 나무 전체라 종전과 같음)

## 회귀

| 묶음 | 결과 |
|---|---|
| `test_tutor.py` `test_tutor_explain.py` `test_tutor_growth.py` `test_tutor_rationale.py` `test_tutor_note_hook.py` `test_tutor_debt.py` `test_tutor_teach.py` `test_surface.py` `test_cli_surface.py` `test_studio_tutor.py` | 294 passed |
| `surface` 의 다른 소비자(`commands/surface.py`, `agent/heimdall/trinity/verdict.py`)를 덮는 `test_architecture.py` `test_thor.py` `test_review_agent.py` `test_trinity_verifier_context.py` `tests/heimdall` | 273 passed |
| `test_mode_parity` `test_prompt_surface` `test_code_map` `test_doctor_shape` `test_errors` `test_completions` `test_evolution` | 291 passed |
| `ruff check` · `ruff format --check src/` | 통과 |
| `asgard craft` · `asgard thor gate` | 둘 다 exit 0, 이번 변경 책임 항목 0건 |

두 게이트가 `.asgard/` 아래 15건을 판정에서 뺐다고 스스로 적는다 — 그 자리는 미판정이다.

훅 파일(`src/asgard/hooks/*.py`)은 안 건드렸으므로 `.claude/hooks` 동기화는 필요 없다.

## 남는 것 — 이 항목 밖, 다음 후보

수리 후 실제 트리 사본의 벽시계 약 1.1초 중 **408ms 가 `surface.candidates()` 의 나무 전수
순회 2회**다(159.5ms + 248.3ms, 각각 이름 1개). 부르는 자리는 `tutor/contracts.py:42
_untested_points` 와 `tutor_teach.py:561 _checks` 다.

이건 축이 틀린 게 아니다 — 호출부는 나무 어디에나 있을 수 있어서 전수 순회가 맞는 질문이다.
다만 한 프로세스에서 같은 나무를 두 번 읽으므로 한 벌로 합칠 여지가 있고, 그건 모듈 둘을
가로지르는 변경이라 이 항목에서 손대지 않았다.
