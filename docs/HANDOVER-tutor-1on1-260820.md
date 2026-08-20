# 인수인계 — 튜터 1:1 학습 체계 (2026-08-20)

코드는 다 섰고 시험도 초록인데 **판정이 FAIL로 서 있다**. 막은 것은 코드가 아니라 앞 세션이
퀘스트를 열 때 적은 검증 계약 한 줄이고, 기준은 개봉 뒤 고정이라 편집으로는 못 푼다. 남은 것은
그 장부를 어떻게 마무리할지 하나다.

## 무엇을 만든 것인가

오딘의 요청: "튜터를 강화할거야 나를 강화해주고 나를 1:1해주는 시스템으로 [영상] 분석하고
튜터를 모두 강화해줘 필요하면 스킬이나 커맨드도 준비하고 — 디폴트로 나의 레벨이나 어떤걸
파악을 스스로 진행하면서 같이 커가는 컨셉을 원해 기준을 제시하고 업그레이드하고"

영상은 YouTube `lF8_DX2NxjI` (Tech Bridge), **ALTER** 다섯 역할이다 — Advisor(목적지·현재
수준·순서·안 볼 것·이정표 다섯 결정을 한 번에 하나씩 묻는다) · Librarian(자료 추리기) ·
Tutor(설명이 아니라 **이 사람의 막힌 자리를 진단**한다, "한 번에 하나만 물어라, 강의하지 마라") ·
Editor(논리를 공격) · Roommate(딴 분야의 렌즈). 근거는 Bloom의 two-sigma — 1:1 지도를 받은
평균 학생이 일반 교실 상위 2% 안에 들었다.

**이번 범위는 튜터와 조언자 둘뿐이다.** 사서는 `asgard map`, 에디터는 `craft`/`bragi`,
룸메이트는 `asgard-roundtable`과 겹쳐 같은 것을 두 벌 만들지 않았고 퀘스트 가정으로 적었다.
셋을 마저 하고 싶으면 별도 퀘스트다.

## 설계를 정한 실측 — 이게 이 작업의 전부다

착수 시점 `.asgard/tutor/growth.json`:

```
asked 36 · answered 0 · deep 0 · skipped 10 · 9건 만료(reason=gone)
```

조절(fading)·재방문 사다리(1·3·7·21일)·각도 회전이 전부 구현돼 있고 **한 번도 실입력 위에서
돈 적이 없었다.** 종류 다섯이 전부 `level 1`에 고정, 하나는 이미 스스로 접혔다. 닫힌 9건은 답을
받아서가 아니라 코드가 먼저 사라져서 닫혔다.

원인은 동기가 아니라 구조다. 답을 적으려면 `asgard tutor --answer <표식> --note "..."` 라는
별도 왕복이 필요한데 일하는 도중에 그걸 치는 사람은 없고, 오딘과 한 방에 있는 유일한 상대인
에이전트에게는 그 세션을 진행하라는 지시가 어디에도 없었다 — **튜터 스킬 자체가 없었다.**
그래서 수리 방향은 층을 더 얹는 것이 아니라 **왕복을 에이전트에게 넘기는 것**이었다.

## 선 것 넷

**① `src/asgard/tutor_track.py` (신규) — 학습자 축.** 기존 `tutor_growth.level(data, kind)`는
물음의 *종류*를 재지 사람을 안 잰다. 이쪽은 트랙(코드 영역)×단계로 사람을 잰다. 트랙 이름은
`tutor_teach._area(rel)`(`tutor_teach.py:362`)가 이미 만들고 있어 새 분류를 안 만들었고, 증거는
`growth.json`의 물음에 붙은 `path`를 그 영역으로 접어서 얻는다. 설문은 없다 — 오딘에게 아무것도
안 묻고 디스크에 있는 것만 읽는다.

단계 넷은 `tutor_teach.DEPTHS`를 그대로 쓰고 `unseen`만 더했다. 각 단계가 **화면에 뜨는 기준
문장**과 **기계가 재는 조건**을 둘 다 가진다: `unseen` → `first`(물음이 닿음) →
`familiar`(자기 문장으로 답함 2건) → `owned`(깊은 답 5건 **그리고** 승급 시험 통과). 단계는
자동으로 오르고 **자동으로 안 내려간다** — 흔들리는 값은 사람이 끄기 때문이고, 회귀는 이력에만
적는다.

승급 시험은 `surface.candidates()`와의 집합 대조다: 답한 자리의 함수를 주고 부르는 곳을 대라고
묻고, 재현율 2/3 이상 그리고 없는 이름 0개면 통과. **분모에 상한 5**(`EXAM_CAP`)를 뒀고 호출부
넷 미만인 함수는 아예 안 묻는다(`EXAM_MIN`) — 40곳 중 27곳을 대라는 건 이해가 아니라 암기고,
그러면 `owned`가 아무도 못 닿는 등급이 되어 지금 고치는 병을 시험 쪽에 새로 만드는 셈이다.
고르는 규칙은 결정론이다(정의 파일 제외 → 경로 정렬 → 앞에서 다섯). 물은 다섯은 `track.json`에
적어 두고 채점 때 그것과 대조한다 — 안 그러면 사이에 파일이 하나 생겨 시험이 도중에 바뀐다.

**저장 대상이 growth와 다른 이유**가 이 모듈을 따로 둔 근거다. `tutor_growth.expire()`(`:434`)가
코드 사라진 물음을 닫고 `CLOSED_CAP = 300`(`:48`)이 오래된 기록을 자른다. 등급을 growth에서 매번
다시 계산하면 코드가 움직일 때마다 등급이 저 혼자 지워진다. 그래서 `track.json`은 growth가 못
말하는 셋만 갖는다 — 승급 시각, 시험 결과, 오딘이 직접 선언한 트랙.

**② `src/asgard/templates/tutor.py` (신규) + `skill_registry/builtin.py` — `asgard-tutor` 스킬.**
0답 문제를 실제로 고치는 자리다. 한 줄로: **에이전트는 학생이 아니라 서기다.** 한 턴에 하나만
묻고, 강의하지 않고, 오딘의 문장을 요약 없이 그대로 `--answer`로 적는다(요약하면
`tutor_growth._depth`가 길이로 재므로 남의 글이 오딘의 답으로 셈된다). 모르겠다고 하면 답을 주지
말고 각도를 바꾸고, 두 번 안 닿으면 그때 좌표를 준다. 오탐이면 `--dismiss`로 닫는다. 조언자
다섯 결정도 같은 방식으로 한 번에 하나씩 묻는다. 어댑터 파일은 손으로 안 적었다 —
`commands/setup.py`가 생성한다.

**③ `src/asgard/hooks/tutor_note.py` — 통로 둘.** 사람에게는 카드 첫 줄에 지금 단계와 다음
기준이 간다. 모델에게는 **표식과 받아 적는 방법만** 간다 — 물음 문장은 한 글자도 안 보낸다.
물음을 읽은 모델은 그 물음에 대신 답하고, 그러면 이 층이 막으려던 일이 그대로 일어난다.
`_marks` 정규식이 16진수 8자만 뽑아서 최악의 경우에도 새는 것은 표식뿐이다. stdout에 객체를
하나만 쓰는 것도 계약이다 — 두 줄을 쓰면 호스트 파서가 실패하고 카드가 통째로 평문으로 모델에
들어간다.

**④ `commands/tutor/*` + `cli/root.py` — `--track`·`--exam` 갈래와 payload의 `track` 칸.**
기본 갈래가 `_payload(..., track=_placement(root))`를 넘기므로(`entry.py:148`) 훅이 부르는
`asgard tutor --json`에 단계가 실린다. 이것이 "디폴트로"가 성립하는 사슬이다.

## 지금 도는 모습

```
$ asgard tutor --track
  ⠶ asgard tutor · 지금 어디까지 왔나
  → ▸ tests — first (물음을 받았어요)
  →     물음 10건 · 자기 문장으로 답한 것 0건
  →     다음 칸 — 답해 봤어요
  →     아직 — 자기 문장으로 답한 물음이 2건 더 필요해요
  ... (트랙 9개, 전부 first — 답이 0건이라 정직한 배치다)
```

`--exam`은 지금 이 저장소에서 "낼 시험이 없어요"를 낸다. 깊은 답이 0건이라 시험 대상이 없는 게
맞다. 오딘이 답을 몇 개 하면 그때부터 시험이 나온다.

## 판정 상태 — 여기가 인계의 핵심

퀘스트 `tutor-alter-1on1-260820` 이 **열린 채 FAIL**이다. `contracts_unmet` 에 이렇게 남아 있다:

```
verify: python -m pytest tests/test_tutor_level.py -q
```

그 파일은 없다. 앞 세션이 퀘스트를 열 때 모듈 이름을 `tutor_level`로 예상하고 적었는데, 작업
도중 `tutor_track`으로 개명했다 — `tutor_growth.level(data, kind)`가 이미 `level`을 쓰고 있어
사람 축과 물음 종류 축이 한 이름에 얹히기 때문이다. 개명은 옳았고 실제 시험은
`tests/test_tutor_track.py`다. 그러나 **기준은 개봉 뒤 고정**이고 `quest-log.py`에 수정 동사가
없다(verbs: open·attach·append·state·replay·next·close·verify-baseline·ticket-*).

**앞 세션이 이미 시도하고 막힌 길 하나 — 되풀이하지 마라.** 기준을 바로잡은 새 퀘스트
`tutor-alter-1on1-260820b`를 열어 봤는데, `open`이 그 시점의 작업 트리를 스냅샷 커밋
(`8b5c8b60 Asgard quest snapshot`)으로 잡아 base로 쓴다. 작업이 끝난 뒤에 열었으니 base가 이미
훅과 CLI 변경을 담고 있어서, 거기서 나오는 diff는 추적 안 되던 새 파일 둘과 동기화 산출물뿐이다.
**부분 diff 위에서 받은 PASS는 전체를 판정했다는 뜻으로 읽히므로 정직한 FAIL보다 나쁘다.**
그래서 그 퀘스트는 사유를 적고 닫았다(BASELINE_VERIFY PASS, closed). 원 퀘스트의 FAIL이 정본이다.

### 진짜 원인은 파일이 아니라 러너다 (이 절이 결론이다)

**앞 세션이 여기를 두 번 틀리게 읽었고, 옆 세션(`asgard-custom-b7`)이 잡았다.** 파일을 만든
**뒤에도** 계약 명령은 여전히 실패한다. 파이프 없이 종료 코드를 직접 잰 값:

```
python    -m pytest tests/test_tutor_level.py -q   → exit 4
uv run python -m pytest tests/test_tutor_level.py -q → exit 0
python -c "import xdist"                            → ModuleNotFoundError
pyproject.toml:82                                   → addopts = ["-n", "auto"]
```

맨 `python`(mise 3.14.5)에 xdist가 없는데 `addopts`가 `-n auto`를 강제하므로 pytest가 인자
파싱에서 죽는다. **exit 4는 pytest의 usage error라 "파일 없음"과 "인자 파싱 실패"가 같은 코드로
나온다** — 그래서 원 판정자도 앞 세션도 두 번 다 파일 탓으로 읽었다.

체인은 코드에서 확인했다. `unmet_contracts`(`contracts.py:112-117`)는 **선언 문자열 그대로**의
`exit_code == 0`만 충족으로 세고, `_run_check`(`baseline.py:139-143`)는 xdist 재작성형을 먼저
돌려 초록일 때만 그 0을 쓰고 아니면 선언 원문을 다시 돌린다. 맨 `python`은 둘 다 실패한다.

**결론: 선언된 계약은 워커가 무엇을 쓰든 못 채운다.** 별칭 파일을 만드는 길은 애초에 없었다.

### 계약 기전 두 가지 — 여기를 틀리게 읽으면 다음 사람도 같은 자리를 판다

**① 계약 원본은 "개봉 기록"이 아니라 "계약을 실은 첫 원본"이다.** `contract_criteria`
(`contracts.py:81-100`)는 `contract_criteria(ev.get("criteria"), *(e.get("criteria") for e in events))`
로 불리므로 **판정자 자신의 criteria가 먼저** 시도되고, 거기 `verify:`가 없을 때 이벤트 순서로
내려가다 개봉 기록이 잡힌다. 결과는 같다 — 나중 `append --criteria`로는 개봉 계약을 못 밀어낸다
— 지만 기전은 "개봉 우선"이 아니라 "계약을 실은 첫 원본"이다.

**② FAIL 퀘스트의 `contracts_unmet`은 "명령이 실패했다"는 뜻이 아니다.**
`quest-log.py:580`이 `if ev["verdict"] != "PASS": return`이라, **FAIL 판정에서는 하네스가
베이스라인도 계약 명령도 아예 안 돌린다.** 기록이 없으니 `contracts.py:106`이 "계약이 있는데
기록이 없으면 미충족"으로 센다. 그래서 FAIL 퀘스트의 미충족 줄을 보고 "명령이 빨갛다"고 읽으면
멀쩡한 명령을 고치러 간다. 원 퀘스트(`260820`)는 사람이 따로 돌려도 exit 4라 진짜 미충족이지만,
`260820c`의 미충족은 **안 돌린 것**이다(그 명령은 따로 돌리면 86 passed, exit 0).

### 세 번 시도했고 세 번 다 계약이 표류했다 — 뿌리는 하나다

`260820`은 계약이 **없는 파일**을 불렀고 러너도 틀렸다. `260820b`는 base가 작업 뒤라 부분
diff였다. `260820c`는 계약이 있는 파일을 부르는데 **다른 것을 쟀다** — 선언한
`uv run python -m pytest tests/test_tutor_track.py tests/test_tutor.py -q`가 exit 0(86 passed)이지만,
그 86건 중 `run_tutor(track=True)`나 `run_tutor(exam=...)`를 부르는 것이 0건이라 기준 4(CLI 표면)를
안 문다. 그 왕복을 무는 16개 호출은 전부 `tests/test_tutor_level.py`에 있다
(`grep -c 'track=True\|exam=' tests/test_tutor{,_track,_level}.py` → 0 · 0 · 16).

세 번의 공통 뿌리: **계약이 파일 경로로 적히는데 그 경로가 재는 대상과 함께 움직인다.** 그리고
`quest-log.py`에 기준 수정 동사가 없어서(open·attach·append·state·replay·next·close·
verify-baseline·ticket-*) 한 번 어긋나면 그 퀘스트 안에서는 못 고친다. 네 번째 퀘스트는 같은
가설의 네 번째 시도라 열지 않았다(캐논 9).

**계약을 파일 경로가 아니라 동작으로 적는 것**이 이 뿌리에 대한 수리 후보다 — 예를 들어
`uv run python -m pytest -k "track or exam" -q`처럼. 아직 안 해봤고, 별도 티켓이다.

### 남은 길 둘

- **강제 종료** `close --force` — Canon 3. 이 저장소는 강제 종료로 낡은 PASS가 정본으로 남은
  전례가 있고, 더 나쁜 것은 **닫힌 퀘스트에 `append`도 `attach`도 안 붙어 판정자가 뒤늦게
  판정을 남길 통로마저 사라진다**는 점이다(`force-close-erases-the-evidence-it-was-asked-for`).
  오딘의 명시적 동의가 필요하다.
- **원 base에 못박은 재판정** — `quest-log.py open --base-ref <원 base>`
  (`quest-log.py:248`, `argparse.SUPPRESS`라 `--help`에 안 보인다). 원 퀘스트와 같은 base를
  쓰므로 위에서 말한 부분 diff 문제가 안 난다. **옆 세션이 이미 `tutor-alter-1on1-260820c`를
  그렇게 열어 뒀다.** 이 길이 남은 정답이다.

**새 퀘스트의 verify 명령은 `uv run python -m pytest ...`로 적어라.** 맨 `python`으로 적으면
지금 이 함정을 그대로 다시 밟는다. 그리고 적기 전에 한 번 돌려 exit 0을 확인해라.

## 판정자가 직접 재서 통과시킨 것 (FAIL 근거가 아니다)

판정자가 반례를 찾으러 갔고 소득 없이 왔다. 모델 통로 유출 없음 · `growth.json` 쓰기 없음 ·
단계 하강 없음 · 일상 카드 채점 없음 · 승급 시험은 별개 갈래 · 배포본 세 사본 sha256 동일
(`ef1992561b7cfaf0`) · 스킬이 worker에는 닿고 verifier·loki에는 0건. 판정자가 돌린 시험 458건과
`tests/architecture` 17건이 전부 초록이다. 중앙 주장도 다시 셌다 — asked 38 / answered 0 /
deep 0 (36→38은 퀘스트 도중 두 건이 더 열린 것).

앞 세션이 돌린 것:

- `just test` → **6065 passed, 14 skipped**
- `just lint` → 통과 · `uv run ruff format --check .` → 통과
- `just typecheck` → **2건 실패**, 둘 다 `tests/map_graph/test_kind_vocabulary.py` /
  `src/asgard/map_graph/view.py`. 이 퀘스트가 안 건드린 파일이고 튜터 모듈 중 `map_graph`를
  임포트하는 것이 없다(의존으로 확인). 지도 종류 어휘 작업의 선재 실패다.

## 이 트리는 공유되고 있다 — 귀속을 조심하라

작업 도중 옆 세션이 같은 트리에서 메모리·doctor·환경 프리플라이트 쪽을 만졌다.
**이 퀘스트 것이 아닌 파일 열넷:** `src/asgard/cli/memory.py` · `commands/doctor/__init__.py` ·
`commands/doctor/wiring.py` · `commands/memory/backends.py` · `commands/setup.py` ·
`memory_bridge/__init__.py` · `memory_bridge/config.py` · `templates/selftest.py` ·
`tests/smoke.sh` · `tests/test_doctor_shape.py` · `tests/test_env_preflight.py` ·
`tests/test_manual.py` · `tests/test_memory_bridge.py` · `tests/test_sync.py`.
`.gitignore`의 변경은 `# <<< asgard <<<` 관리 구간 안이라 `asgard sync`가 쓴 것이다.

**이 퀘스트 것:** 신규 `src/asgard/tutor_track.py` · `src/asgard/templates/tutor.py` ·
`tests/test_tutor_track.py` · `tests/test_tutor_level.py`. 수정 `cli/root.py` ·
`commands/tutor/{entry,labels,lanes,payload}.py` · `hooks/tutor_note.py`(+ `.claude/`·`.codex/`
배포본 두 벌) · `skill_registry/builtin.py` · `tests/{test_tutor,test_tutor_note_hook,test_skill_registry}.py` ·
`tests/architecture/{layers,packages}.py`.

**앞 세션이 이 목록을 한 번 틀리게 적었다** — `commands/setup.py`·`tests/test_sync.py`·
`tests/smoke.sh`·`templates/selftest.py` 넷을 이 퀘스트 것으로 올렸다가 옆 세션 판정자가 잡았다.
확인 방법은 diff 내용이다: 그 넷의 변경에 `tutor` 문자열이 **0건**이고, 실제 내용은
`PREFLIGHT_PS1`/`PREFLIGHT_SH` 임포트·루트 gitignore 마커·`asgard:law` 마커 검사·하니스의
`asgard_hooklib` 복사다. 스킬 어댑터는 등록부에서 자동 생성되므로 `setup.py`가 `asgard-tutor`를
이름으로 들 필요가 없다(`grep -c 'asgard-tutor' src/asgard/commands/setup.py` → 0,
`.claude/skills/asgard-tutor/`는 존재). **공유 트리에서는 파일 이름이 아니라 diff 내용으로
귀속하라.**

## 남은 것 셋

1. **판정 장부 마무리** — 위 세 길 중 하나. 오딘이 정할 자리다.
2. **`run_tutor`의 craft 악화** — 결정점 18→20, 76행(예산 15/70). 예산 초과는 이번 변경
   전부터고, 표로 바꾸려면 열넷 갈래의 우선순위를 전부 옮겨야 해서 자기 검증을 가진 별도
   티켓이 맞다. craft는 exit 0이라 막지는 않는다.
3. **ALTER 나머지 셋** — 사서·에디터·룸메이트. 별도 퀘스트.

## 앞 세션이 밟은 함정 둘 — 되풀이하지 마라

**계획을 안 기다리고 병렬 단위를 쐈다.** 사색가가 안 돌아와서 조율자가 직접 쓴 계약으로 wave를
발사했고, 계획이 도착하니 그 계약이 네 곳 틀려 있었다(모듈 이름 충돌 · 트랙 씨앗을 지도에서
뽑으려 한 것 · 단계를 새로 발명한 것 · `expire`/`CLOSED_CAP`이 배치 근거를 지운다는 것을 못 본
것). 도는 에이전트 둘에게 `SendMessage`로 정정을 보내 수습했지만 이미 쓴 코드를 개명시키는 값을
냈고, **지금 FAIL의 뿌리가 바로 그 개명이다.**

**검증 명령을 돌려 보지 않고 기준에 적었다.** 그 한 줄이 퀘스트 전체를 못 닫게 만들었다. 계약을
적기 전에 그 명령을 한 번 돌려라 — 이 저장소에서는 `uv run` 없이 `python -m pytest`를 적으면
파일이 무엇이든 exit 4다.

**같은 종료 코드를 다른 원인으로 읽었다.** exit 4를 "파일 없음"으로 읽고 두 번(원 판정자 한 번,
앞 세션 한 번) 같은 진단을 냈다. 실제로는 인자 파싱 실패였다. 종료 코드 하나가 여러 원인을
가리킬 때는 **원인을 바꿔 가며 재현해 봐야** 한다 — 여기서는 파일을 만들어 놓고 다시 재는 것이
그 실험이었고, 그 한 번이 두 번의 오진을 끝냈다.

## 앞 세션이 트리에 더한 마지막 것

`tests/test_tutor_level.py`를 새로 만들고 `tests/test_tutor.py`에서 `TrackLaneTest`·`ExamLaneTest`
12건과 헬퍼 둘(`_track_module`·`_placed`)을 옮겼다. **계약을 채우려던 것이 아니다**(못 채운다는
것을 위에서 확인했다) — 축이 갈리는 게 맞아서다. 엔진 층(`place`·`grade`·`pick_exam`)은
`test_tutor_track.py`가 물고, 새 파일은 그 결론이 화면과 JSON까지 오는가만 본다. 한 파일에 두면
엔진을 고칠 때마다 화면 시험이 같이 빨개져 어느 쪽이 깨졌는지 못 가린다. 파일 머리에 이름이
모듈과 다른 이유를 적어 뒀다.

`python -m pytest tests/test_tutor.py tests/test_tutor_level.py tests/test_tutor_track.py
tests/test_tutor_note_hook.py -q -p no:cacheprovider -o addopts=""` → **122 passed**,
ruff check·format 초록.
