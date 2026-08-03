"""asgard-seal 스킬 — 변경사항을 독립 철회 가능한 gitmoji 사건 파일(commit)로 봉인하는 커밋 규율.

프로젝트 전용 절차(체크포인트 DB, QA 게이트, 다국어 phrasebook)는 담지 않는다 — 프로젝트에
의존하지 않는 것이 목표고, 언어 미러링은 AGENTS.md identity 섹션이 이미 계약한다 (사다리 1단).

품질 규칙의 출처 (26-07-14 자료조사):
  • gitmoji 규격 + semver 매핑(💥=major, ✨=minor, 🐛=patch): gitmoji.dev /
    carloscuesta/gitmoji gitmojis.json의 semver 필드.
  • Conventional Commits 1.0.0: type(scope)!: subject + BREAKING CHANGE footer 규약.
  • cbeams "How to Write a Git Commit Message" 7규칙 + Tim Pope 50/72: 명령형 판별
    테스트 "If applied, this commit will ___", body는 what/why (how는 diff).
  • Linux kernel submitting-patches: 동기(문제) 선행 서술, 성능 주장엔 수치,
    "separate each logical change into a separate patch".
  • 에이전트 커밋 스킬 실물(rburmorrison/agent-skills, vekzz-dev/opencode-skills):
    inspect-first, 명시 경로 staging + staged 재검증 게이트, secrets 스캔,
    빈 repo 🎉 단독 예외, fail-closed 엣지 케이스.
  • 국립국어원 「쉬운 공공언어 쓰기 길잡이」(26-08-01 추가) — 읽는 사람이 한 번에 알아듣는
    쉬운 말로 쓴다. 커밋 본문의 문체 규칙은 templates/comments.py의 주석 계약과 같다:
    비유로 설명하지 않고, 사전에 있는 말을 쓴다.

lagom·selftest와 같은 패턴으로 단일 본문을 .claude/skills/ 와 .agents/skills/ (Cursor·Codex
공용 스코프) 두 곳에 배포한다 — 툴별 렌더링 없음.

allowed-tools 는 쉼표로 나눈다 (26-08-04 수리). 공백으로 이으면 목록 전체가 항목 **하나**로
파싱되고, 그 하나는 `Bash(git status *) Bash(git diff *) …` 라는 없는 명령과의 정확 일치라
어느 호출도 안 맞힌다. 그래서 사전 승인이라고 적힌 `git status`·`git diff`·`git add`·`git
commit` 이 전부 승인 프롬프트를 띄웠고, 커밋 하나가 승인 열몇 번짜리 일이 됐다 (사용자 실측
5분 이상). 규칙 형태 자체는 종전대로 `Bash(git add *)` — 끝의 ` *` 는 단어 경계가 붙은
접두 와일드카드라 `git add src/x.py` 를 맞힌다 (`:*` 도 같은 뜻이다). skill_router 의
`direct_skill` 이 어댑터를 만들 때 쉼표로 잇는 것과 같은 계약이다.

완화는 이 줄이 하고 강제는 git-guard 훅이 하므로, 여기를 넓게 적어도 `git add -A` 금지 같은
하드룰은 그대로 집행된다."""

SEAL_SKILL_MD = """\
---
name: asgard-seal
description: 🔏 Seal — classify and seal working-tree changes into independent, revertible gitmoji case files (commits). Includes quality gates (one seal one case · 50/72 · reasoned body · secret blocking · staged re-verification). NEVER Co-Authored-By/Signed-off-by.
allowed-tools: Bash(git status *), Bash(git diff *), Bash(git log *), Bash(git branch --show-current), Bash(git add *), Bash(git commit *), Bash(git restore --staged *)
---

# asgard-seal — Case Sealing (gitmoji commit)

Heimdall inspects the on-site changes and **seals them into the commit history (git log)**. Each
commit is one **case file** — the smallest unit that can be independently tracked and reverted.
(Invoke — Claude Code/Cursor: `/asgard-seal` · Codex: `$asgard-seal`.)

> Language mirroring: reports and tables in Odin's language. Commit subject/body follow the
> dominant language of `git log --oneline -15`; if mixed, use Odin's language. Within one commit,
> subject and body language must match.
> Priority: Odin's instruction > this skill's rules > gitmoji spec > repo log style (a reference for
> tone and vocabulary only — never copy its grammar or spacing, which the rules below decide).

## Sealing Rules (Absolutely Forbidden)

- **No `Co-Authored-By` / `Signed-off-by` / `Generated with ...` or any other author, signature,
  or AI attribution footer.** The message ends with subject + body.
- **No `git add -A` / `git add .`** — stage files explicitly, per case. The sole exception is the
  `🎉 init` first commit on an empty repo. Never `git add -f` an ignored file.
- **Never seal secrets (Canon 4)** — if `.env` files, credentials, private-key headers, or API-key
  patterns (`AKIA…`, `sk-…`, `ghp_…` and the like) show up in the diff, stop immediately and report
  to Odin. If already staged, unstage with `git restore --staged`.
- **No `--no-verify`** — project hooks (pre-commit) are quality gates. Never bypass them.
- **Never rewrite pushed history (Canon 3/6)** — do not amend or rebase, even unpushed local
  commits, without Odin's consent.

## Evidence Classification Codes (Gitmoji)

Core codes — cover the vast majority of real cases. Pick from the full gitmoji.dev spec only for
cases outside this list.

| Code | Type | Case Kind | Version | | Code | Type | Case Kind | Version |
|------|------|-----------|------|-|------|------|-----------|------|
| ✨ | feat | New feature | minor | | 🔒️ | security | Security vulnerability fix | patch |
| 🐛 | fix | Bug fix | patch | | ⬆️/➕/➖ | deps | Dependency upgrade/add/remove | patch |
| 🚑️ | hotfix | Critical production hotfix | patch | | 🚚 | move | File move/rename | — |
| 🩹 | fix | Minor non-urgent fix | patch | | 🔥 | remove | Remove code/files | — |
| ♻️ | refactor | Restructuring (behavior unchanged) | — | | 🚀 | deploy | Deployment | — |
| ⚡️ | perf | Performance improvement | patch | | 👷/💚 | ci | CI config/fix | — |
| 🎨 | style | Code structure/format cleanup | — | | 🔖 | release | Release/version tag | — |
| 💄 | ui | User-visible UI/style | patch | | 🎉 | init | Project's first commit only | — |
| 📝 | docs | Documentation | — | | 🗃️ | db | Storage/schema | patch |
| ✅ | test | Add/modify tests | — | | 💥 | breaking | **Breaking (compatibility-destroying) change** | **major** |
| 🔧 | config | Config file | patch | | 🚨 | lint | Resolve lint warnings | — |

Disambiguating confusable pairs — when ambiguous, pick a single **dominant intent**:
- 🎉 is for the first commit only; use ✨ for features. / 🐛 general bug · 🚑️ production emergency · 🩹 minor fix.
- ♻️ behavior-preserving restructuring · 🎨 structure/format · 💄 user-visible style. / 🚧 (WIP) is forbidden on shared branches.

## Seal Format (Commit Format)

```
<gitmoji> <type>(<scope>): <subject>

<body>
```

- **subject** — one line that **names what changed**. Test: it reads naturally as "If this seal is
  applied → <subject>". Use each language's own convention for that, not a translation of
  English's:
  - English — imperative mood ("add chart component" ✓ / "added" ✗ / "adds" ✗).
  - Korean — 개조식 명사형, or a plain declarative that names the change
    ("대시보드 차트 컴포넌트 추가" ✓ / "만료 토큰을 거부한다" ✓). Korean has no commit imperative;
    do not invent one, and do not replace the subject with an aphorism or a metaphor
    ("일감은 폴더에 살지 않는다" ✗ — that is a body opening, not a subject).
  **Target 50 chars, hard cap 72** (emoji excluded), no trailing period, capitalize the first
  letter if in English. scope is the module/package/area name (required in a monorepo).
- **body** — **what changed in the code, and what for**: the motivating problem → what you actually
  changed (named: files, functions, symbols, settings) → the impact, in that order. Back
  performance/improvement claims with numbers. **Wrap at 72 chars**.
  The body may be omitted only for one-line changes (typos etc.) where the diff alone makes the
  why obvious — otherwise it is required.
- **register — an engineering record, not an essay.** This is the single most common failure, and
  it survives every other rule: the message is grammatical, correctly scoped, correctly split, and
  still says nothing a maintainer can use. A commit message is read by someone bisecting a
  regression at 2 a.m. Write for that reader.
  - **Name the code.** Every claim in the body should point at something in the diff — a path, a
    function, a constant, a flag, a config key. A body with no identifier in it is a red flag.
  - **No aphorisms, metaphors, or narration.** Do not open with a maxim, close with a moral, or
    personify the code. "The ruler was wrong, not the surface", "a window belongs to a person, not
    a folder", "one missed nudge was one lesson lost forever" — all of these are essay sentences.
    They read well and they tell the 2 a.m. reader nothing.
  - **No rhetorical questions, no second person, no suspense.** State the finding first; do not
    build to it.
  - **Plain words inside the sentence too.** The maxim is the obvious form of this failure; the
    quieter one is a metaphor used as an ordinary predicate. Code does not win, stand, live, eat,
    carry, or pay: write `그쪽이 우선한다` not `그쪽이 이긴다`, `임베더가 준비된다` not
    `임베더가 선다`, `프롬프트에 들어간다` not `프롬프트에 실린다`. Use the word that is in the
    dictionary and never coin a term to save a syllable. This is the same contract the comment
    rules apply, and `asgard craft` checks it on the diff's comments with a closed dictionary.
  - **Cut any sentence that would survive unchanged in a different commit.** If it is true of the
    project in general rather than of this diff, it does not belong here.
  - Concision is not the point — a long body is fine when the change is subtle. Every sentence
    just has to carry a fact about *this* change.

  | Essay (✗) | Record (✓) |
  |---|---|
  | 창은 사람의 것이고, 일감은 폴더에 살지 않는다 | 스튜디오 시작 자리를 cwd 대신 개인 워크스페이스로 고정 |
  | 놓친 넛지 하나가 교훈 하나의 영구 소실이었다 | 퀘스트 종료 시 evolution.autoscan 으로 자동 채굴 (기본 on) |
  | 자를 세워 두고 자기 몸을 안 재면 그 자는 남에게만 들이대는 것이 된다 | 신설 규칙을 저장소에 적용 — 198파일의 주석·독스트링 교정 |
  | The ruler was wrong, not the surface | Reorder STATE_BITS alternatives so `focus-visible` matches before `focus` |
- **grammar** — subject and body follow the Bragi grammar contract. In Korean a particle attaches
  to the word before it, and a Latin word, number, or code span is still that word
  (`quest_log.py를`, `UTF-8로`, `HEAD와` — never `quest_log.py 를`); do not coin clipped words
  (불필요, not 불요; 일치 없음, not 무매칭). In English keep the articles, the subject, and a finite
  verb. The 50/72 limits are a line budget, never a licence to drop a particle or a word — if the
  subject does not fit, the case is too big, so split it.
- **breaking change** — the 💥 code + `!` after the type (`💥 feat(api)!: ...`) + at the end of the
  body, `BREAKING CHANGE: <migration path>` (this token is always uppercase — release tooling
  reads it).
- Execution: `git commit -m "<subject>" -m "<body>"` — no footer signature whatsoever.
- Examples:
  - ko: `✨ feat(fe): 대시보드 차트 컴포넌트 추가`
  - en: `🐛 fix(auth): reject expired refresh tokens`
  - vi: `♻️ refactor(core): tách logic phân loại khỏi router`

## Case Classification Rules — One Seal, One Case

**1 commit = 1 logical change.** If the subject needs "and"/"&", split it.

| Criterion | Verdict |
|------|------|
| Independent-revert test — is reverting just this commit harmless? | If not, redraw the boundary |
| Different module/package, or different nature (feat·fix·style·config·test·docs) | Split into separate commits |
| Refactor vs. behavior change | **Must be split** — lets reviewers quickly skip "behavior-unchanged" commits, and keeps bisect precise |
| Formatting vs. logic | Must be split — formatting noise must not obscure the logic diff |
| Two cases mixed in one file | Split at the hunk level (equivalent of `git add -p`). If non-interactive execution makes this impossible, ask Odin how to split |

That said, over-splitting is also a defect: each commit must be **self-contained** at that point
(buildable, tests green) — never split into an intermediate state that breaks compilation.

## Procedure

0. **Exception cases — when blocked, do not seal** — not a git repo / no changes → report in one
   line and stop. Empty repo → seal alone as `🎉 init: <project name>` (the only time `git add -A`
   is allowed). A file with both staged and unstaged changes mixed → ask Odin how to proceed before
   sealing.
1. **Verify the quest branch** — check that `git branch --show-current` matches convention
   (`feature/*`, `bugfix/*`, `hotfix/*`, `release/*`, `main`/`master`/`develop`, `local_*`).
   On mismatch: warn + propose a name based on the case content → proceed only after Odin approves
   (rename or skip).
2. **On-site inspection** — `git status --short` · `git diff HEAD --stat` → read the relevant diff
   in full · `git log --oneline -15` (for subject language/tone reference). Never classify without
   reading (Canon 5).
3. **Quality pre-check** — scan the diff; if found, mark ⚠️ in the classification table and
   propose how to handle it:
   - Secrets/credentials (found = stop immediately, per the sealing rules)
   - Debug leftovers (`console.log`, `print`, experimental comments), large binaries or build
     artifacts (`.gitignore` candidates)
   - Unrelated files (changes outside the requested scope — Canon 7)
4. **Present the case classification table** — present the logical groups as a table and **wait
   for Odin's approval**. No commits before approval. In an unattended session (Canon 8): proceed
   with the default classification, but record the assumption and state it in the final report.
5. **Seal in sequence** — per case: `git add <named files>` → **re-verify staged**: confirm
   `git diff --cached --stat` matches the evidence listed in the classification table (mismatch =
   restage) → `git commit`.
6. **Submit the record** — report with `git log --oneline -10` and the completed-seals table.

## Reasons a Seal Gets Rejected

| Rejection reason | Correction |
|----------|------|
| Bare subject like `WIP`/`fix`/`misc`/`update` | Rewrite so the change is identifiable without the diff |
| Body that only lists how ("changed A to B") | Write the why — problem, reason, trade-offs |
| Multiple cases in one seal ("fix login and refactor and docs") | Split per the classification rules |
| subject doesn't match the diff | The diff is the truth — fit the subject to the diff |
| Past-tense or third-person English subject ("added", "fixes") | Unify to imperative mood (the "If applied..." test) |
| A subject that is an aphorism or metaphor instead of the change ("일감은 폴더에 살지 않는다") | Name the change in the subject; move the line into the body if it earns its place |
| A body written as an essay — maxims, metaphors, personified code, a moral at the end | Rewrite as a record: problem → what changed (named files/functions/settings) → impact |
| A body with no identifier in it — no path, function, constant, flag, or config key | Name what you touched; a maintainer bisecting a regression cannot search prose |
| A sentence that would be equally true in another commit | Delete it — the body describes this diff, not the project |
| A metaphor used as an ordinary predicate (`그쪽이 이긴다`, `임베더가 선다`, `저장소가 나른다`) | Say what happens (`우선한다`, `준비된다`, `전달한다`) — the reader should not have to decode an image |
| Broken grammar in either language — a detached Korean particle (`config.py 를`), a coined clipping (불요), a verbless English fragment | Rewrite per the grammar rule; the 50/72 budget never justifies it |
| Unsubstantiated "performance improvement" claim in the body | Back it with numbers, or drop the claim |

## Report Format

**Case classification table** (before approval): `| # | Code | Case name (draft subject) | Evidence (files) | ⚠️ |`

**Completed-seals table** (after sealing): `| Commit | Case name |`

First response is a one-line framing, completion report is one line — narrative follows the
identity contract (not overdone).
"""
