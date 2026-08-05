"""asgard-seal 스킬 — 워킹트리 변경을 빠른 gitmoji commit으로 기록하는 규율."""

SEAL_SKILL_MD = """\
---
name: asgard-seal
description: Commit current working-tree changes with a required gitmoji and Conventional Commit type in one session. NEVER add author, signature, or AI attribution footers.
allowed-tools: Bash(git status *), Bash(git diff *), Bash(git add *), Bash(git commit *)
model: sonnet
lane: vcs
---

# asgard-seal

현재 변경을 확인하고 commit한다. 소스 파일은 수정하지 않는다.

이 호출 자체가 현재 변경을 commit하라는 승인이다. 추가 승인을 묻지 않는다.
분류표를 만들지 않는다. 브랜치 이름을 검사하거나 바꾸지 않는다. 테스트나 QA를 다시 실행하지 않는다. Trinity,
Quest, 계획, 서브에이전트도 시작하지 않는다. 프로젝트 hook은 `git commit`이 그대로 실행한다.

## Commit 형식

gitmoji와 Conventional Commits의 type 구조를 결합한다.

```
<gitmoji> <type>[(<scope>)][!]: <description>

[optional body]

[optional footer(s)]
```

- gitmoji는 필수다. 변경과 정확히 맞는 gitmoji를 먼저 고르고, 없으면 type 기본값을 쓴다:
  `feat` ✨, `fix` 🐛, `docs` 📝, `style` 🎨, `refactor` ♻️, `perf` ⚡️,
  `test` ✅, `build` 🔨, `ci` 👷, `chore` 🔧, `revert` ⏪️.
- 보안 🔒️, 의존성 ⬆️/➕/➖, 긴급 수정 🚑️처럼 더 구체적인 gitmoji가 맞으면 기본값보다 우선한다.
- 기본 type은 `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`,
  `chore`, `revert` 중 변경의 주된 목적 하나를 고른다.
- scope는 선택 사항이다. 저장소에서 바로 알아볼 수 있는 모듈이나 영역일 때만 쓴다.
- 한국어 description은 짧은 개조식 명사형으로 쓴다. 서술형 `-다` 종결인 `한다`, `된다`,
  `했다`, `였다`는 쓰지 않는다. 마침표도 붙이지 않는다.
- 영어 description은 짧은 명령형으로 쓴다. 첫 단어를 불필요하게 대문자로 쓰지 않는다.
- body는 선택 사항이다. 제목만으로 이유를 알 수 없을 때만 문제와 변경 이유를 적고, diff를
  문장으로 다시 풀어 쓰지 않는다.
- 호환성을 깨는 변경은 type 또는 scope 뒤에 `!`를 붙이고
  `BREAKING CHANGE: <migration>` footer를 적는다.
- `Co-Authored-By`, `Signed-off-by`, `Generated with ...` 등 작성자, 서명, AI attribution
  footer는 넣지 않는다.

예시:

```
✨ feat(seal): gitmoji 제목 형식 적용
🐛 fix(auth): 만료 토큰 거부
⚡️ perf(cli): 중복 분류 호출 제거
📝 docs: 설치 절차 정리
💥 feat(api)!: 응답 envelope 형식 변경
```

## Commit 경계

**1 commit = 1 logical change.** 서로 독립적으로 되돌릴 수 있을 때만 나눈다.
구현과 그 구현을 검증하는 테스트는 같은 commit에 둔다. 파일 수나 확장자가 다르다는 이유만으로 나누지 않는다.
서로 무관한 변경은 별도 commit으로 나눈다.

## 안전 규칙

- **No `git add -A` / `git add .`.** commit별 파일을 `git add -- <named paths>`로 명시한다.
- Canon 4: `git status --short`에 `.env`, credential, private key 등 민감한 경로가 보이면 그
  파일을 열거나 stage하지 말고 중단한다. diff에서 secret으로 의심되는 값이 보일 때도 중단한다.
- **No `--no-verify`.** hook 실패를 우회하거나 그 자리에서 소스 수정으로 고치지 않는다.
- amend, rebase, reset, stash, branch 변경, push는 이 스킬의 범위가 아니다.
- 이미 stage된 변경과 stage되지 않은 변경을 모두 확인한다. 현재 요청과 무관한 stage 항목을
  함께 commit하지 않는다.

## 빠른 절차

1. **한 번의 확인** — `git status --short`를 보고, 민감한 경로가 없을 때
   `git diff --cached`와 `git diff`를 읽는다. 변경이 없으면 한 줄로 알리고 끝낸다.
   트리가 커도 파일 묶음마다 `git diff`를 다시 부르지 않는다. 양이 부담되면 `git diff --stat`으로
   규모를 먼저 보고 `git diff -U1`처럼 문맥을 줄여 한 번에 읽는다 — 같은 바이트를 나눠 읽으면
   왕복만 늘어난다 (26-08-05 실측: `git diff` 호출 자체는 0.2초인데 호출 사이 왕복이 4~10초라,
   묶음별로 열다섯 번 부른 실행에서 왕복만 1분이 넘었다).
2. 변경을 최소 logical commit으로 묶는다. 경계가 명확하면 설명이나 승인 왕복 없이 계속한다.
3. 한 묶음을 **한 번의 호출로** 봉인한다:
   `git add -- <named paths> && git diff --cached --check && git commit -m "<subject>"`.
   `&&`는 앞이 실패하면 뒤를 안 돌려서, 검사에 걸린 묶음은 commit까지 못 간다. 필요한 body가
   있을 때만 두 번째 `-m`을 붙인다. 무엇이 담겼는지는 commit 출력의 `N files changed`가 알린다.
   호출을 add·check·stat·commit 넷으로 쪼개면 commit 한 건마다 왕복이 셋 더 붙는다.
   이 합침이 안전한 전제는 1번이다 — 이미 stage돼 있던 것을 거기서 이미 봤어야 한다.
4. 생성된 commit hash와 subject만 한 줄로 보고한다. `git log`를 다시 출력하지 않는다.

merge conflict, 민감한 파일, 분리할 수 없는 혼합 hunk, hook 실패만 정확한 원인과 함께 보고하고
멈춘다. 이 네 경우가 아니면 한 턴 안에 commit까지 끝낸다.
"""
