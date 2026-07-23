"""codebase map — `.asgard/map/` 시드 (INDEX.md). INDEX 는 지도 '규칙'만 담는 asgard 소유 계약
문서(sync 가 최신으로 유지). PROJECT.md 는 결정론 스캐너가 관리하고, 지식(영역 지도
`<area>.md`)은 에이전트가 과업 중 증분으로 그린다 — asgard 는 영역 파일을 절대 수정하지 않는다. `.asgard` 하위에서 유일하게 git 추적되는
디렉토리 — 지도는 런타임 상태가 아니라 팀 공유 자산이다 (실패 교훈 2건 반영:
지도+체인지로그 혼합 비대화, 디스크 선기재 ghost)."""

MAP_INDEX_MD = """\
# Codebase Map — .asgard/map/

Team-shared (git-tracked) codebase map. `PROJECT.md` holds the project's directions and landmarks,
drawn by `asgard map update` from current on-disk evidence. Deep knowledge lives in per-area
`<area>.md` files (e.g. `cli.md`, `frontend.md`), created by agents as they explore.

## Map Grammar (doctor warns on violations)

1. **Fixed entry grammar** — ``- `path` — one-line role``. No other narration.
2. **Map ≠ history** — No dates, incidents, or change-history narration. History belongs to the quest log (`.asgard/quest/`) and git.
3. **Existing files only** — List only files that exist on disk. No pre-listing files you plan to create (ghost prevention).
4. **Ownership split** — `PROJECT.md` is Asgard-only (no manual edits); area maps are human/agent-only (Asgard never overwrites them).
5. **fog-of-war** — Fill deep area maps incrementally, only for explored areas. No full rewrites or bulk generation.
6. **Read first, verify to trust** — Read the map before exploring, but re-confirm every path your plan stands on with Read.
7. **Size and injection safety** — Area files stay at 8 KiB or less. Prose outside the grammar and prompt-control phrasing are excluded from automatic context.

## Verification

`asgard map check` and `asgard doctor` detect managed drift, ghost entries, grammar, and size violations.
`PROJECT.md` auto-refreshes at main-request/subagent start and before Verifier hash computation, so map
changes are included in the same PASS. Inspect the actual bounded injection with `asgard map context --query "<task>"`.

## Area File Example

```markdown
# map: cli

- `src/app/cli.py` — CLI entry, subcommand routing
- `src/app/commands/` — subcommand implementations (one command per file)
```
"""
