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
description: 🔏 Seal — classify and seal working-tree changes into independent, revertible gitmoji case files (commits). Includes quality gates (one seal one case · 50/72 · reasoned body · secret blocking · staged re-verification). NEVER Co-Authored-By/Signed-off-by.
allowed-tools: Bash(git status *) Bash(git diff *) Bash(git log *) Bash(git branch --show-current) Bash(git add *) Bash(git commit *)
---

# asgard-seal — Case Sealing (gitmoji commit)

Heimdall inspects the on-site changes and **seals them into the commit history (git log)**. Each
commit is one **case file** — the smallest unit that can be independently tracked and reverted.
(Invoke — Claude Code/Cursor: `/asgard-seal` · Codex: `$asgard-seal`.)

> Language mirroring: reports and tables in Odin's language. Commit subject/body follow the
> dominant language of `git log --oneline -15`; if mixed, use Odin's language. Within one commit,
> subject and body language must match.
> Priority: Odin's instruction > this skill's rules > gitmoji spec > repo log style (tone reference only).

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

- **subject** — one line, **imperative mood**. Test: it should read naturally as "If this seal is
  applied → <subject>" (e.g. "add chart component" ✓ / "added" ✗).
  **Target 50 chars, hard cap 72** (emoji excluded), no trailing period, capitalize the first
  letter if in English. scope is the module/package/area name (required in a monorepo).
- **body** — **what and why**: the motivating problem → the approach taken (including rejected
  alternatives) → the impact, in that order. Don't repeat how — the diff already says that. Back
  performance/improvement claims with numbers. **Wrap at 72 chars**.
  The body may be omitted only for one-line changes (typos etc.) where the diff alone makes the
  why obvious — otherwise it is required.
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
| Past-tense or third-person subject ("added", "fixes") | Unify to imperative mood (the "If applied..." test) |
| Unsubstantiated "performance improvement" claim in the body | Back it with numbers, or drop the claim |

## Report Format

**Case classification table** (before approval): `| # | Code | Case name (draft subject) | Evidence (files) | ⚠️ |`

**Completed-seals table** (after sealing): `| Commit | Case name |`

First response is a one-line framing, completion report is one line — narrative follows the
identity contract (not overdone).
"""
