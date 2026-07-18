"""asgard-seal 스킬 — 변경사항을 독립 철회 가능한 gitmoji 사건 파일(commit)로 봉인하는 커밋 규율.

프로젝트 전용 절차(체크포인트 DB, QA 게이트, 다국어 phrasebook)는 담지 않는다 — 프로젝트
비의존이 목표고, 언어 미러링은 AGENTS.md identity 섹션이 이미 계약한다 (사다리 1단).

품질 규칙의 출처 (26-07-14 자료조사):
  • gitmoji 규격 + semver 매핑(💥=major, ✨=minor, 🐛=patch): gitmoji.dev /
    carloscuesta/gitmoji gitmojis.json 의 semver 필드.
  • Conventional Commits 1.0.0: type(scope)!: subject + BREAKING CHANGE footer 규약.
  • cbeams "How to Write a Git Commit Message" 7규칙 + Tim Pope 50/72: 명령형 판별
    테스트 "If applied, this commit will ___", body 는 what/why (how 는 diff).
  • Linux kernel submitting-patches: 동기(문제) 선행 서술, 성능 주장엔 수치,
    "separate each logical change into a separate patch".
  • 에이전트 커밋 스킬 실물(rburmorrison/agent-skills, vekzz-dev/opencode-skills):
    inspect-first, 명시 경로 staging + staged 재검증 게이트, secrets 스캔,
    빈 repo 🎉 단독 예외, fail-closed 엣지 케이스.

lagom·selftest 와 같은 패턴으로 단일 본문을 .claude/skills/ 와 .agents/skills/ (Cursor·Codex
공용 스코프) 두 곳에 배포한다 — 툴별 렌더링 없음."""

SEAL_SKILL_MD = """\
---
name: asgard-seal
description: 🔏 Seal — 워킹트리 변경을 독립 철회 가능한 gitmoji 사건 파일(commit)로 분류·봉인. 품질 게이트(한 봉인 한 사건·50/72·이유 본문·시크릿 차단·staged 재검증) 포함. NEVER Co-Authored-By/Signed-off-by.
allowed-tools: Bash(git status *) Bash(git diff *) Bash(git log *) Bash(git branch --show-current) Bash(git add *) Bash(git commit *)
---

# asgard-seal — 사건 봉인 (gitmoji commit)

Heimdall 이 현장의 변경사항을 감식해 **과업 기록부(git log)에 봉인**한다. 각 커밋은 하나의
**사건 파일** — 독립적으로 추적·철회(revert) 가능한 최소 단위여야 한다.
(호출 — Claude Code/Cursor: `/asgard-seal` · Codex: `$asgard-seal`.)

> 언어 미러링: 보고·표는 Odin 의 언어로. commit subject/body 는 `git log --oneline -15`
> 의 우세 언어를 따르고, 혼합이면 Odin 언어. 한 커밋 안에서 subject·body 언어는 일치.
> 우선순위: Odin 지시 > 이 스킬의 규칙 > gitmoji 규격 > repo 로그 스타일(톤 참고용).

## 봉인 철칙 (절대 금지)

- **`Co-Authored-By` / `Signed-off-by` / `Generated with ...` 등 어떤 author·signature·AI
  attribution footer 도 금지.** 메시지는 subject + body 로 끝난다.
- **`git add -A` / `git add .` 금지** — 사건별로 파일을 지정해 스테이징한다. 유일한 예외는
  빈 repo 의 `🎉 init` 최초 커밋. ignored 파일 `git add -f` 금지.
- **시크릿 봉인 금지 (Canon 4)** — `.env`·자격증명·private key 헤더·API key 패턴
  (`AKIA…`, `sk-…`, `ghp_…` 류)이 diff 에 보이면 즉시 중단하고 Odin 에게 보고.
  이미 스테이징됐으면 `git restore --staged` 로 내린다.
- **`--no-verify` 금지** — 프로젝트 훅(pre-commit)은 품질 게이트다. 우회하지 않는다.
- **push 된 히스토리 수정 금지 (Canon 3/6)** — amend·rebase 는 로컬 미push 커밋에도
  Odin 동의 없인 하지 않는다.

## 증거 분류 코드 (Gitmoji)

핵심 코드 — 실사건 대부분을 덮는다. 목록 밖 사건만 gitmoji.dev 전체 규격에서 고른다.

| 코드 | Type | 사건 유형 | 버전 | | 코드 | Type | 사건 유형 | 버전 |
|------|------|-----------|------|-|------|------|-----------|------|
| ✨ | feat | 신규 기능 | minor | | 🔒️ | security | 보안 취약점 봉쇄 | patch |
| 🐛 | fix | 결함 수정 | patch | | ⬆️/➕/➖ | deps | 의존성 업/추가/제거 | patch |
| 🚑️ | hotfix | 프로덕션 긴급 수정 | patch | | 🚚 | move | 파일 이동·이름변경 | — |
| 🩹 | fix | 자잘한 비긴급 수정 | patch | | 🔥 | remove | 코드·파일 폐기 | — |
| ♻️ | refactor | 구조 재편 (행동 불변) | — | | 🚀 | deploy | 배포 | — |
| ⚡️ | perf | 성능 개선 | patch | | 👷/💚 | ci | CI 구성/수정 | — |
| 🎨 | style | 코드 구조·포맷 정비 | — | | 🔖 | release | 릴리스·버전 태그 | — |
| 💄 | ui | 사용자 보이는 UI·스타일 | patch | | 🎉 | init | 프로젝트 최초 커밋 전용 | — |
| 📝 | docs | 문서 | — | | 🗃️ | db | 저장소·스키마 | patch |
| ✅ | test | 테스트 추가·수정 | — | | 💥 | breaking | **호환성 파괴 변경** | **major** |
| 🔧 | config | 설정 파일 | patch | | 🚨 | lint | 린터 경고 해소 | — |

혼동 페어 판별 — 애매하면 **지배적 의도** 하나로:
- 🎉 는 최초 커밋 전용, 기능은 ✨. / 🐛 일반 결함 · 🚑️ 프로덕션 급한 불 · 🩹 자잘한 수정.
- ♻️ 행동 불변 재편 · 🎨 구조/포맷 · 💄 사용자에게 보이는 스타일. / 🚧(WIP) 는 공유 브랜치 금지.

## 봉인 형식 (Commit Format)

```
<gitmoji> <type>(<scope>): <subject>

<body>
```

- **subject** — 한 줄, **명령형**. 판별: "이 봉인을 적용하면 → <subject>" 로 읽어 자연스러워야
  한다 ("차트 컴포넌트 추가" ✓ / "추가했음" ✗, "add chart" ✓ / "added" ✗).
  **50자 목표·72자 상한**(이모지 제외), 끝 마침표 없음, 영어면 첫 글자 대문자.
  scope 는 모듈·패키지·영역명 (모노레포면 필수).
- **body** — **무엇을·왜**: 동기가 된 문제 → 접근(기각한 대안 포함) → 영향 순. how 는 diff
  가 이미 말하므로 반복하지 않는다. 성능·개선 주장에는 수치를 동반한다. **72자 wrap**.
  diff 만으로 why 가 자명한 한 줄 변경(오타 등)만 body 생략 가능 — 그 외는 필수.
- **breaking change** — 💥 코드 + type 뒤 `!` (`💥 feat(api)!: ...`) + body 끝에
  `BREAKING CHANGE: <마이그레이션 경로>` (이 토큰은 항상 대문자 — 릴리스 도구가 읽는다).
- 실행: `git commit -m "<subject>" -m "<body>"` — footer 서명 일절 없음.
- 예시:
  - ko: `✨ feat(fe): 대시보드 차트 컴포넌트 추가`
  - en: `🐛 fix(auth): reject expired refresh tokens`
  - vi: `♻️ refactor(core): tách logic phân loại khỏi router`

## 사건 분류 규칙 — 한 봉인 한 사건

**1 커밋 = 1 논리 변경.** subject 에 "및/그리고/and" 가 필요하면 쪼갠다.

| 기준 | 판정 |
|------|------|
| 독립 revert 테스트 — 이 커밋만 되돌려도 무해한가 | 불가능하면 경계 재조정 |
| 다른 모듈·패키지 / 다른 성격 (feat·fix·style·config·test·docs) | 별건 분리 |
| 리팩터 vs 행동 변경 | **반드시 분리** — 리뷰어가 "행동 불변" 커밋을 빠르게 스킵, bisect 정밀도 |
| 포맷팅 vs 로직 | 반드시 분리 — 포맷 노이즈가 로직 diff 를 가리면 안 된다 |
| 한 파일에 두 사건 혼재 | hunk 단위 분리(`git add -p` 상당). 비대화형이라 불가하면 Odin 에게 분리안 질의 |

단, 과분할도 결함이다: 각 커밋은 그 시점에서 **스스로 완결**(빌드 가능, 테스트 녹색)이어야
한다 — 컴파일이 깨지는 중간 상태로 쪼개지 않는다.

## 절차

0. **예외 현장 — 막히면 봉인하지 않는다** — git repo 아님 / 변경 없음 → 한 줄 보고 후 중단.
   빈 repo → `🎉 init: <프로젝트명>` 단독 봉인(이때만 `git add -A` 허용).
   같은 파일에 staged+unstaged 혼재 → 봉인 전 Odin 에게 처리 방침 질의.
1. **과업 라인 검증** — `git branch --show-current` 가 규약(`feature/*`, `bugfix/*`,
   `hotfix/*`, `release/*`, `main`/`master`/`develop`, `local_*`)에 맞는지 확인.
   불일치 시 경고 + 사건 내용 기반 이름 제안 → Odin 승인(rename 또는 생략) 후 진행.
2. **현장 감식** — `git status --short` · `git diff HEAD --stat` → 관련 diff
   정독 · `git log --oneline -15` (subject 언어·톤 참고). 안 읽고 분류하지 않는다 (Canon 5).
3. **품질 사전점검** — diff 에서 스캔, 발견 시 분류표에 ⚠️ 표기 + 처리 방안 제시:
   - 시크릿·자격증명 (발견 = 즉시 중단, 봉인 철칙)
   - 디버그 잔재 (`console.log`·`print`·실험 주석), 대용량 바이너리·생성물(.gitignore 후보)
   - 무관 파일 (요청 범위 밖 변경 — Canon 7)
4. **사건 분류표 제시** — 논리 그룹을 표로 제시하고 **Odin 승인 대기**. 승인 전 커밋 금지.
   무인 세션(Canon 8)이면: 분류 기본안으로 진행하되 가정을 기록하고 최종 보고에 명기.
5. **순차 봉인** — 사건별 `git add <파일 지정>` → **staged 재검증**: `git diff --cached --stat`
   이 분류표의 증거물과 일치하는지 확인(불일치 = 재스테이징) → `git commit`.
6. **기록부 제출** — `git log --oneline -10` 과 봉인 완료표로 보고.

## 봉인 반려 사유

| 반려 사유 | 교정 |
|----------|------|
| `WIP`·`fix`·`misc`·`update`·`수정` 단독 subject | diff 없이도 변경을 특정할 수 있게 재작성 |
| how 만 나열한 body ("A를 B로 바꿈") | why — 문제·이유·트레이드오프를 쓴다 |
| 여러 사건 한 봉인 ("로그인 수정 및 리팩터 및 문서") | 분류 규칙대로 분리 |
| subject 와 diff 불일치 | diff 가 진실 — subject 를 diff 에 맞춘다 |
| 과거형·3인칭 subject ("added", "fixes") | 명령형 통일 ("If applied..." 테스트) |
| 근거 없는 "성능 개선" body | 수치 동반 또는 주장 제거 |

## 보고 형식

**사건 분류표** (승인 전): `| # | 코드 | 사건명(subject 초안) | 증거물(파일) | ⚠️ |`

**봉인 완료표** (봉인 후): `| Commit | 사건명 |`

첫 응답 한 줄 프레이밍, 완료 보고 한 줄 — 내러티브는 identity 계약(과하지 않게)을 따른다.
"""
