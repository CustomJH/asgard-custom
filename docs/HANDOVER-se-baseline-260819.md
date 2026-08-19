# 인수인계 — 엔지니어링 기본 세팅 (2026-08-19)

앞 세션이 예산 상한에 닿아 판정 한 바퀴를 못 돌리고 넘긴다. 코드와 문서는 다 섰고, 남은 것은
판정과 정리 둘이다.

## 지금 상태

퀘스트 `se-baseline-research-260819` 가 **열린 채**다. 워커 세 단위가 전부 `done` 이고
`next_role` 은 `VERIFIER` 다. 앞 세션이 직접 돌린 것:

- `uv run --no-project python -m pytest tests/test_craft.py tests/test_thor_corpus.py -q` → exit 0 (62 passed)
- `uv run --no-project ruff check .` → exit 0
- `uv run --no-project ty check` → exit 0
- `uv run --no-project python -c "import asgard.health as h; b=h.budgets('.'); print((b.unit_lines,b.depth,b.branches))"` → `(70, 4, 15)`
- `uv run --no-project python -m asgard humanize docs/engineering-baseline.md` → naturalness A

## 이번 변경이 한 것

값 여섯(함수 70행·중첩 4·결정점 15·파일 400/1000행·데이터 문장 10)은 **하나도 안 바꿨다**.
바뀐 것은 둘이다.

**근거 서술.** 문헌 조사 결과 우리 숫자들이 실증이 아니라 관례라는 것이 확인됐고, 그 사실을
주석과 문서에 적었다. 함수 70행은 근거가 더 나아졌고(코드 물량 90분위 74), 결정점 15는
McCabe 권위 호소를 지우고 이 저장소 실측만 남겼고, 중첩 4는 근거가 가장 약한 축이라고 적었다.

**문.** `pyproject.toml` 의 `[tool.asgard.craft-budget]` 로 `unit_lines`·`depth`·`branches`
셋을 저장소가 정할 수 있게 열었다. 리졸버는 `health.budgets(root)` 하나뿐이고, 게이트와 계측이
같은 값을 보는지를 `tests/test_craft.py::BudgetTableTest` 의 양방향 불변식이 문다.

그리고 우리 문서가 대던 arXiv 2605.06445 해설의 과장을 다섯 자리에서 걷어냈다. 논문과 30점
수치는 맞지만 그 30점은 제약 개수가 아니라 상태를 가진 외부 의존이 물어간 값이다.

## 만진 파일 열셋

신규 `docs/engineering-baseline.md`.
수정 `src/asgard/health.py` · `craft_rules.py` · `craft.py` · `loop.py` · `commands/health.py` ·
`hooks/craft_gate.py` · `hooks/tutor_note.py` · `thor_rules.py` · `templates/thor.py` ·
`assets/skill_plugins/asgard-thor-thrudvangr/skills/asgard-thor-thrudvangr/SKILL.md` ·
`pyproject.toml` · `tests/test_craft.py`.

## 할 일 셋

### ① 오딘이 새로 시킨 것 — 논문 아닌 출처를 걷어낸다

이번 변경으로 들어간 인용 중 **논문(학술 문헌)만 남기고 나머지는 다 걷어내라.** 걷어낼 것은
도구 문서 URL, 벤더 보고서, 블로그, 상용 제품 기본값 표 같은 것이다. 대상은 이번 변경이 만진
열셋과 특히 `docs/engineering-baseline.md` 다.

가르는 선은 이렇다. 남기는 것은 저자·학회·연도가 있는 문헌이다(예: Alves ICSM 2010,
Landman 2016, Ajami ICPC 2017, Syer TSE 2015, Fenton & Ohlsson 2000, Buse & Weimer TSE 2010,
Posnett MSR 2011, Yamashita QRS 2016, McCabe TSE 1976, arXiv 프리프린트). 걷어내는 것은
SonarQube·CodeScene·ESLint·Checkstyle·PMD·radon 의 문서 링크와 기본값 표, GitClear·DORA·Qodo
같은 업계 보고서, 그 밖의 블로그다.

**사실 자체를 지우라는 뜻이 아니다.** "도구 기본값 11개 중 근거를 밝힌 곳이 0곳"이라는 관찰은
이 문서의 핵심이라 남긴다. 지우는 것은 그 링크 목록과 도구별 URL 표다. 문장은 남기고 주소만
걷어낸다고 읽으면 된다.

### ② 판정

`asgard-verifier` 를 한 번 세운다. 판정 전에 `docs/engineering-baseline.md` 와
`docs/HANDOVER-se-baseline-260819.md` 를 `git add` 해라 — 미추적이라 물리 diff 에 안 잡힌다.

판정자에게 특히 물릴 자리 넷:
- 값 여섯이 정말 하나도 안 바뀌었는가 (`git diff` 로 직접)
- `craft.judge` 와 `health.scan` 과 `commands/health.py` 의 화면 라벨이 **같은 값**을 보는가.
  `BudgetTableTest` 를 양방향으로 변이시켜 둘 다 빨개지는지 확인
- 리졸버가 나쁜 값(bool·음수·문자열·깨진 TOML·파일 부재)을 `gate_baseline` 과 같은 계약으로
  다루는가. 작성자가 둘을 `_toml_table()` 로 합쳤으니 `tests/test_health_gate.py` 로 확인
- 작성자가 자기 게이트에 걸려서 한 손질 셋(`shape_findings` 의 `_limits()` 추출,
  `scan`·`run_health` 의 래칫 상쇄)이 자기가 만든 차단을 푸는 최소 변경인가

### ③ 미추적 파일이 남긴 부작용

`src/asgard/code_style.py` 계열(앞선 퀘스트 산출물)이 미추적이라 `craft` 가 HEAD 판이 없는
파일의 내용 전부를 "이번에 신설"로 읽는다. 그래서 상속 부채가 엉뚱한 단위의 종료를 문다.
커밋하면 풀리지만 앞 세션은 커밋 지시를 못 받아 손대지 않았다. 오딘의 결정이다.

## 앞 세션이 남긴 함정 둘 (되풀이하지 마라)

**팬아웃 전에 단위를 선언해라.** 표식 없이 워커 셋을 한 번에 보내면 `subagent-gate` 가 둘을
거절한다. `quest-log.py append` 로 `role=thinker`·`ticket_status=todo`·`unit=<id>` 를 먼저
적고, `ticket-claim` 한 뒤, 프롬프트 첫 줄에 `[ASGARD_UNIT:<id>]` 를 달아야 한다. 선언 전에
나간 단위는 나중에 **물리 배차 영수증이 없어서 판정자 배차까지 막는다** — 앞 세션이 그걸로
한 번 더 막혔다.

**시험 종료 코드를 파이프로 받지 마라.** `pytest ... | tail` 의 종료 코드는 `tail` 것이라
실패가 초록으로 보고된다. 앞 세션이 이 함정에 한 번 빠져 "전체 통과"를 잘못 보고했다.
