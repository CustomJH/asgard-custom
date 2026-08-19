# 코드 형상 문턱 — 결정표

이 저장소가 함수 길이·중첩 깊이·분기 수·파일 길이에 걸어 둔 숫자의 정본이다. 값마다 유지·변경·신설 판정과 근거를 적는다.

**이번 결정에서 값은 하나도 안 바뀐다.** 바뀌는 것은 두 가지다 — 각 값이 서 있는 근거의 서술, 그리고 저장소가 자기 값을 정하는 설정 문을 여는 일.

## 조사가 확인한 것 중 가장 중요한 사실

린터·정적 분석 도구의 기본값은 그 숫자를 고른 이유를 밝히지 않는다. 이번에 도구 여섯(SonarQube·CodeScene·ESLint·Checkstyle·PMD·radon)의 기본값을 함수 길이·중첩 깊이·파일 길이·복잡도 네 축에서 전수로 열어 봤고, 읽은 것은 둘이다.

같은 축에서 도구끼리 세 배까지 벌어진다 — 함수 길이는 50에서 150 사이에, 중첩 깊이는 1에서 4 사이에 흩어진다. 그리고 **열어 본 값 중 그 숫자를 고른 근거를 적은 곳이 하나도 없다 — 0곳이다.** 전부 관례이고 근거는 미공개다. 가장 뚜렷한 자리가 인지복잡도다. SonarSource의 백서(v1.7)에는 "threshold"라는 낱말이 한 번도 안 나오는데, 도구가 쓰는 기본값 15는 백서가 아니라 `sonar-java` 소스 코드의 상수다.

도구 쪽 주소는 이 문서에 싣지 않는다. 아래 「근거」에 서는 것은 저자·발표처·연도가 있는 문헌뿐이고, 도구 기본값은 위 관측으로만 남긴다.

우리 숫자도 성격이 같다. 아래 표의 근거는 "왜 다른 값이 아니라 이 값인가"를 증명하지 않는다 — 그런 증명은 어느 도구도 못 내놓았다. 대신 각 값이 **무엇을 재는 대리 지표인지**와 **틀렸을 때 무엇이 일어나는지**를 적는다.

## 결정표

| 값 | 지금 | 판정 |
|---|---|---|
| `UNIT_LINES_WARN` | 70 | 유지 · 근거 교체 |
| `DEPTH_WARN` | 4 | 유지 · 근거가 가장 약함을 명시 |
| `BRANCH_BUDGET` | 15 | 유지 · 권위 호소 철회 |
| `FILE_LINES_WARN` | 400 | 유지 |
| `FILE_LINES_SEVERE` | 1000 | 유지 |
| `DATA_STMT_MAX` | 10 | 유지 |

기본값은 `src/asgard/health.py`에 모여 있다 — `UNIT_LINES_WARN`·`DEPTH_WARN`·`BRANCH_WARN`·`FILE_LINES_WARN`·`FILE_LINES_SEVERE`. `src/asgard/craft_rules.py`는 앞의 셋을 `UNIT_LINES_BUDGET`·`DEPTH_BUDGET`·`BRANCH_BUDGET`이라는 이름으로 받고 `DATA_STMT_MAX`만 자기가 든다. 분기 예산을 실제로 세는 곳은 `craft_rules.shape_findings`이고, 기본값이 `health` 쪽에 있는 것은 저장소 선언을 푸는 `health.budgets()` 하나만 표를 읽게 하기 위해서다.

### `UNIT_LINES_WARN` = 70 — 유지, 근거 교체

지금 주석은 "CodeScene 계열 god method 관례"라고 적는다. 사실 관계는 맞다 — CodeScene의 Python 함수 기본값이 정확히 70이다. 다만 관례를 근거로 대면 앞 절에서 적은 문제를 그대로 물려받는다.

더 나은 근거가 있다. Alves 외(ICSM 2010)는 시스템 100개·11,996 KLOC의 코드 물량 분포에서 문턱을 유도했고, 메서드 LOC의 90분위가 **74**로 나왔다. 즉 70은 결함이 시작되는 선이 아니라 **코드 물량 상위 10% 구간의 표시**다. 이 값을 넘는 함수가 결함을 품는다는 뜻이 아니라, 이 저장소에서 드문 크기라는 뜻이다.

그래서 이 값은 막지 않고 알린다. `craft`의 `unit-oversize` 판정은 래칫이라 **이번 변경이 더 나쁘게 만든 것**만 알린다.

### `DEPTH_WARN` = 4 — 유지, 근거가 가장 약함을 명시

우리 축 넷 중 문헌 지지가 가장 약하다. 숨기지 않고 적는다.

현업 개발자 222명을 대상으로 이해 시간을 잰 Ajami 외(ICPC 2017)에서, 중첩된 `if`는 평탄하게 편 판보다 **오히려 조금 빨랐고 그 차이는 유의하지 않았다**. 중첩과 결함의 관계를 잰 연구는 1학년 학생 54명짜리 하나뿐이다(Huang & Liu 2013, r≈0.3).

그래도 값을 두는 이유는 규칙의 모양에 있다. `unit-deep`은 래칫이라 물려받은 깊이를 안 막고 **악화만** 막는다. 문턱이 틀렸어도 비용은 "이미 깊은 함수를 더 깊게 만들 때 한 줄 알림"에서 끝난다.

**오탐이 실제로 관측되면 이 값이 첫 강등 후보다.** 넷 중 이 축을 먼저 내리거나 끈다.

### `BRANCH_BUDGET` = 15 — 유지, 권위 호소 철회

지금 주석은 "McCabe의 원 권고는 순환복잡도 10이고 흔한 린터 기본값은 10~15다"라고 적는다. 이 문장을 근거에서 뺀다.

McCabe의 1976년 논문에서 저자 본인이 10을 *"a reasonable, but not magical, upper limit"*이라고 적었다. 그 값을 뒷받침하는 실증은 Fortran 서브루틴 24개를 프로젝트 구성원이 주관적으로 순위 매긴 것 하나다. 반세기 동안 인용된 숫자지만 인용이 증거는 아니다.

권위를 빼고 남는 근거는 둘이다.

**① 이 저장소의 실측.** `src/asgard` 아래 함수 4,883개 중 95.4%가 결정점 15 이하다(26-08-19 측정). 재는 법은 이렇다 — `git ls-files src/asgard`가 내는 `.py` 중 `/assets/` 아래를 뺀 468개 파일을 `craft_rules.units()`로 단위로 쪼개고, 각 단위의 `craft_rules._branches` 결정점이 15 이하인 비율을 소수 첫째 자리까지 센다.

이 비율 자체는 근거가 아니다. 트리가 자라면 함수 수도 비율도 움직이므로, 이 수가 말하는 것은 "예산 15가 지금 이 저장소에서 상위 몇 %를 무는가"라는 관측치 하나다. 다시 재면 다시 적는다.

**② 함수 단위에서는 분기 수가 길이의 되풀이가 아니다.** "순환복잡도는 SLOC의 대리 지표일 뿐"이라는 비판이 있고, 근거로 드는 Jay 외(2009)의 R²≈0.90은 세다. 그런데 그 상관은 **파일 단위 합산**에서 나온 값이다. Landman 외(2016)가 Java 메서드 1,760만 개·C 함수 626만 개를 **함수 단위로** 다시 재자 R²는 0.40으로 떨어지고, 문턱이 실제로 판정하는 상위 1% 구간에서는 0.21–0.28까지 더 갈라진다. 우리 판정기는 함수 하나를 보므로 그 비판에 안 걸린다.

`_branches`는 순환복잡도에서 1을 뺀 결정점을 센다. 중첩 함수와 클래스는 자기 단위로 따로 세므로 바깥 함수가 헬퍼의 분기를 뒤집어쓰지 않는다.

### `FILE_LINES_WARN` = 400 — 유지

알림 전용이라 아무것도 막지 않는다.

파일 크기와 결함 밀도의 관계는 방향조차 뒤집힌다. Hatton(1997)은 U 자 곡선을, Koru 외(2008)는 단조 감소를 보고했는데, 파일 38,809개로 복제한 Syer 외(TSE 2015)는 밀도 봉우리를 35–116행 구간에 두고 **둘 다 부정했다**. Fenton & Ohlsson(2000)은 크기가 결함 밀도를 예측한다는 증거를 아예 못 찾았다.

이 반증이 우리 값을 흔들지 않는 이유는 우리가 이 값에 붙인 뜻이 결함 예측이 아니기 때문이다. 400은 **되돌리는 비용의 추세를 볼 대상**을 고르는 경계다. 이 저장소에서 831줄짜리 파일 하나가 3주 만에 11개 파일·1,000행 초과로 되감긴 적이 있고, 그 추세를 놓치지 않으려고 세는 것이지 결함을 예측하려고 세는 것이 아니다.

### `FILE_LINES_SEVERE` = 1000 — 유지

막는 둘 중 하나다(다른 하나는 순환 의존). 그런데 막는 것은 절대값이 아니라 **기준선 대비 증가**다. `pyproject.toml`의 `[tool.asgard.health-gate]`에 `severe_files = 0`이 적혀 있고, 게이트는 이 수를 넘길 때만 알린다. 내려가는 것은 조용히 통과한다.

위 반증은 전부 "N행 넘는 파일을 막는 것"을 겨냥한다. 우리는 그걸 안 한다. 1000은 차단선이 아니라 **세는 단위**이고, 실제 차단선은 `pyproject.toml`에 적힌 0이다.

### `DATA_STMT_MAX` = 10 — 유지

문턱이 아니라 **면제 확장기**다. `unit-oversize`는 길이와 문장 수를 함께 봐서, 문장이 10개 이하인 함수는 아무리 길어도 판정에 안 걸린다.

설정 리터럴 하나를 돌려주는 함수가 그 대상이다. 실측: `src/asgard/templates/claude.py`의 `cc_settings`는 373행인데 문장 4개·분기 0개다(26-08-19). 길이 예산은 "한 자리에서 너무 많은 일이 벌어진다"의 대리 지표인데 이런 함수에서는 그 대리가 틀린다.

외부 근거가 겨냥하는 대상이 아니다 — 문헌은 문턱을 다루고 이 값은 면제를 다룬다. 근거는 우리 실측 하나다.

## 신설하지 않기로 한 축 셋

여기가 이 문서의 절반이다. 안 만든 이유를 안 적으면 다음 사람이 같은 조사를 다시 한다.

### ① 줄당 식별자 수 — 안 만든다

문헌 지지가 우리가 본 축 중 가장 강한데도 안 만든다. 그래서 근거를 넷 다 적는다.

**(a) 지지 증거는 세다.** Buse & Weimer(TSE 2010)는 주석자 120명·판정 12,000건으로 가독성 모델을 학습했고, 줄당 식별자 수에 상대 세기 **100%**를 매겼다. 줄 길이가 96%, 주석이 33%, 식별자 **길이**는 0%다.

**(b) 그런데 그 모델은 함수 크기로 못 늘린다.** Posnett 외(MSR 2011)가 Lucene에 그 모델을 돌려 보고한 것은, 4–11줄 조각으로 학습한 모델이 **200행 넘는 함수를 예외 없이** 안 읽히는 것으로 찍는다는 사실이다. 조각에서 잰 규칙을 함수 전체에 외삽하면 무너진다.

**(c) 문턱을 어디에 둬도 이 저장소에서 켜지는 줄이 수백에서 수천이다.** 26-08-19 실측 — `src/asgard` 아래 Python 파일에서 파이썬 `tokenize`의 `NAME` 토큰 중 예약어를 뺀 것을 물리적 줄마다 셌다. 식별자가 하나 이상 있는 줄이 67,955개이고 분포는 이렇다.

| 문턱 | 이하 | 켜지는 줄 |
|---|---|---|
| 8 | 95.70% | 2,922 |
| 10 | 98.37% | 1,105 |
| 12 | 99.51% | 332 |
| 15 | 99.94% | 40 |

한 줄 최대는 19다. 문턱을 8에 두면 2,922줄이, 10에 두면 1,105줄이 켜진다. **그 줄들이 결함이라는 근거가 없다.** 12나 15로 올리면 켜지는 줄이 수십 개로 줄지만, 그건 문턱이 아무 일도 안 한다는 뜻이다.

**(d) 문턱 자체를 검증한 유일한 연구가 문턱을 말린다.** Yamashita 외(QRS 2016)는 문턱으로 나눈 고위험군의 결함 **밀도가 오히려 낮았다**고 보고하고, 문턱은 조심해서 쓰거나 아예 쓰지 말라고 적는다.

### ② 이름 규칙 — 안 만든다

식별자 **길이**의 가독성 예측력은 0%다(Buse & Weimer, 위 (a)).

한 글자 이름은 예외가 아니라 관용이다. Beniamini 외(ICPC 2017)가 GitHub 프로젝트 1,000개를 세어 보니 한 글자 이름이 전체 이름의 **10–20%**이고, `s`=string, `t`=time, `i`·`j`=loop index처럼 뜻이 뚜렷하다. 이름이 원래 나쁘면 지워도 이해 시간에 차이가 없다 — Avidan & Feitelson(ICPC 2017)에서 메서드 6개 중 3개에서 효과가 사라졌다.

반대 증거도 있다. Hofmeister 외(EMSE 2019)는 직업 개발자 72명에서 낱말 이름이 비낱말보다 **19% 빨랐다**(dz=0.32).

세 연구를 동시에 만족시키는 읽기는 하나다. 이름의 효과는 실재하되 작고, 개인차에 묻히며, 관용어에는 안 걸린다. 그 크기의 효과를 문턱으로 강제하면 관용어부터 잡는다.

### ③ `E501`(줄 길이) — 지금대로 `ignore` 유지

문헌은 이 축을 지지한다(줄 길이 상대 세기 96%). 그런데 이 저장소에서는 켜도 잡히는 게 없다.

`pyproject.toml`이 `line-length = 120`을 두고 `ruff format`을 병용한다(CI는 `ruff format --check`). 포매터가 접는 줄은 이미 접혀 있고, 남는 것은 **포매터도 못 접는 장문 템플릿 문자열**뿐이다. 켜면 잡히는 게 전부 오탐이다. 지금 `ignore = ["E501"]` 옆에 적힌 "포매터 병용 시 공식 권장"이 그대로 유효하다.

## Lint Leakage 감사

에이전트 설정 파일 스멜을 조사한 연구에서, 인기 저장소 100개 중 91개가 스멜을 갖고 1위가 **Lint Leakage 62건**이었다. 린터가 이미 강제하는 규칙을 프롬프트에 다시 적는 것을 말한다. 우리도 그러는지 직접 셌다.

**대상 — 38개 파일.** `AGENTS.md` 1개, `src/asgard/templates/` 아래 `.py` 26개와 `roles/*.md` 11개. `src/asgard/assets/skill_plugins/`는 벤더링이라 제외했다(`ruff`의 `extend-exclude`와 같은 이유).

**방법 — grep 두 벌.**

1. `ruff`의 `select = ["E", "F", "W", "I"]`(단 `E501`은 `ignore`) + `ruff format` + `ty check`가 이미 강제하는 항목의 이름을, 한국어와 영어 양쪽으로: 줄 길이, 후행 공백·쉼표, 들여쓰기, import 순서, 미사용 import, 따옴표, 타입 힌트, PEP 8, 80·100·120자.
2. 도구 이름 자체: `ruff`, `black`, `flake8`, `ty check`, 린터, 포매터, lint.

**발견 — 0건.**

첫 벌이 건 자리는 하나이고 린트 규칙과 무관하다. `src/asgard/templates/skill_router.py:75`는 상류 프론트매터의 따옴표가 사용자에게 보이는 문장의 첫 글자가 되는 문제를 다룬다.

둘째 벌이 건 자리는 전부 방향이 반대다 — 규칙을 되적지 않고 도구를 가리킨다.

- `src/asgard/templates/thor.py:392` — 언어별 표의 도구 칸에 `ruff`와 프로젝트 타입 체커를 적는다.
- `src/asgard/templates/codex.py:261`, `src/asgard/templates/claude.py:371`, `src/asgard/templates/trinity.py:53` — 코드 스타일 규칙은 `checkstyle.xml`·`eslint.config.js` 쪽에 있고 훅은 그 규칙을 이 세션이 쓴 파일에만 적용한다고 적는다.

**후속으로 지목할 파일 없음.**

키워드 목록으로 누수를 잡는 시험은 만들지 않는다. 나쁜 모양을 열거하는 규칙은 이 저장소에서 이미 세 번 샜다 — 열거는 매번 빠뜨린 갈래로 새고, 세 번째 규칙을 더하는 대신 지우는 쪽이 맞다. 이 감사는 재현 가능한 명령으로 남기고 판정기로는 안 만든다.

## 저장소가 값을 정하는 문

`pyproject.toml`의 `[tool.asgard.craft-budget]`에 세 손잡이를 연다.

```toml
[tool.asgard.craft-budget]
unit_lines = 70
depth = 4
branches = 15
```

셋 다 생략 가능하고, 없으면 위 결정표의 값이 그대로 선다. `health.budgets()`가 이 표를 풀고, 참·거짓·음수·정수가 아닌 값은 조용히 버리고 기본값을 쓴다 — 잘못 적은 한 줄로 예산이 0이 되면 이 저장소의 모든 함수가 한꺼번에 위반이 된다.

**파일 문턱(400·1000)은 안 연다.** 이유가 둘이다. 그 축에는 `[tool.asgard.health-gate]`라는 다른 문이 이미 있어서 저장소는 거기서 기준선을 정한다. 그리고 `health`의 파일 크기 추세는 저장소끼리 견주는 값인데, 세는 기준을 저장소마다 바꾸면 비교가 끊긴다.

**자리를 `pyproject.toml`로 고른 이유: 추적되는 파일이라 게이트를 푸는 행위가 diff에 남는다.** `.asgard/` 아래에 두면 그 디렉터리를 통째로 `gitignore` 하는 클론에서 값이 조용히 사라지고, 다른 클론과 CI가 서로 다른 기준으로 잰다. 같은 이유로 `[tool.asgard.k6-gate]`의 허용 오차도 이 파일에 있다.

## 근거

McCabe 1976 (IEEE TSE SE-2(4):308–320) — https://masters.donntu.ru/2020/fknt/mazalov/library/article_08_min.pdf
NIST SP 500-235 — https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication500-235.pdf
Shepperd 1988 (Software Engineering Journal 3(2):30–36) — https://www.cs.du.edu/~snarayan/sada/teaching/COMP3705/lecture/p1/cycl-1.pdf
Jay 외 2009 (JSEA 2(3):137–143, 파일 약 120만) — https://content.scirp.org/pdf/jsea20090300001_74742661.pdf
Landman 외 2016 (JSEP 28(7):589–618) — https://aserebre.win.tue.nl/Landman2015-ccsloc-jsep2015-preprint.pdf · 정오표 https://pure.tue.nl/ws/portalfiles/portal/92047732/sloc_paper_erratum.pdf
Muñoz Barón·Wyrich·Wagner ESEM 2020 (조각 427개·약 24,000 평가) — https://arxiv.org/abs/2007.12520
Esposito 외 (개발자 216명) — https://arxiv.org/abs/2303.07722
Fenton & Ohlsson 2000 (IEEE TSE 26(8):797–814) — https://dl.acm.org/doi/10.1109/32.879815
Nagappan·Ball·Zeller ICSE 2006 (Microsoft 시스템 5개) — https://www.st.cs.uni-saarland.de/publications/files/nagappan-icse-2006.pdf
Radjenović 외 2013 (IST 55:1397–1418, 논문 106편) — https://torkar.github.io/pdfs/000d837774c3e143487d18be46c4a28e.pdf
Gil & Lalouche 2017 (EMSE 22(5):2585–2611) — https://link.springer.com/article/10.1007/s10664-017-9513-5
Yamashita 외 QRS 2016 — https://posl.ait.kyushu-u.ac.jp/~kamei/publications/Yamashita_QRS2016.pdf
Hatton 1997 (U자) — https://www.leshatton.org/Documents/Ubend_IS697.pdf
Koru 외 2008 (EMSE) — https://doi.org/10.1007/s10664-008-9080-x
Syer 외 TSE 41(2) 2015 (파일 38,809) — https://doi.org/10.1109/TSE.2014.2361131 · PDF http://sail.cs.queensu.ca/data/pdfs/TSE_ReplicatingAndRe-evaluatingTheTheoryOfRelativeDefect-Proneness.pdf
Tornhill & Borg, Code Red, TechDebt 2022 — https://arxiv.org/abs/2203.04374
Alves·Ypma·Visser ICSM 2010 — https://webarchive.di.uminho.pt/wiki.di.uminho.pt/twiki/pub/Personal/Joost/PublicationList/AlvesYpmaVisserICSM2010.pdf
Huang & Liu 2013 (JSE 7(3), 학생 54명) — https://scialert.net/fulltext/?doi=jse.2013.114.120
Ajami·Woodbridge·Feitelson ICPC 2017 (현업 222명) — https://www.cs.huji.ac.il/w~feit/papers/Complexity17ICPC.pdf · 확장판 https://link.springer.com/article/10.1007/s10664-018-9628-3
Peitek 외 ICSE 2021 (fMRI, 참가자 19명) — https://web.eecs.umich.edu/~weimerw/2024-481F/readings/peitek2021-metrics.pdf
Buse & Weimer TSE 2010 (주석자 120명·판정 12,000건) — https://web.eecs.umich.edu/~weimerw/p/weimer-tse2010-readability-preprint.pdf
Posnett·Hindle·Devanbu MSR 2011 — https://softwareprocess.es/pubs/posnett2011MSR-readability.pdf
Scalabrino 외 JSEP 2018 (조각 660개) — https://sscalabrino.github.io/files/2018/JSEP2018AComprehensiveModel.pdf
Hofmeister·Siegmund·Holt EMSE 2019 (개발자 72명) — https://brains-on-code.github.io/shorter-identifier-names.pdf
Avidan & Feitelson ICPC 2017 (개발자 9명) — https://www.cs.huji.ac.il/w~feit/papers/Names17ICPC.pdf
Beniamini 외 ICPC 2017 (학생 56명 + GitHub 1,000 프로젝트) — https://www.cs.huji.ac.il/w~feit/papers/SingleLetter17ICPC.pdf
Vitale 외 2025 (평가의 최대 1/3이 자기모순) — https://arxiv.org/abs/2503.07870
설정 파일 스멜 (저장소 100개 중 91개) — https://arxiv.org/abs/2606.15828
컨텍스트 파일 효과 +2.4% p=0.21 — https://arxiv.org/abs/2602.11988
정적 분석 되먹임 40–80%→11–13% — https://arxiv.org/abs/2508.14419
