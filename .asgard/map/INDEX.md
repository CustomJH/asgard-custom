# Codebase Map — .asgard/map/

Team-shared (git-tracked) codebase map. `PROJECT.md` holds the project's directions and landmarks,
drawn by `asgard map update` from current on-disk evidence. `GRAPH.md` projects source-grounded
relations plus named coverage boundaries from `asgard map scan`; its complete derived state lives
outside Git at `.asgard/state/map-graph.json`. Deep knowledge lives in per-area `<area>.md` files
(e.g. `cli.md`, `frontend.md`), created by agents as they explore.

`PEER-<repo>.md` is the same managed drawing for a repository declared with `asgard root add` — code this
project works on that lives outside it. Its rows carry the path you open from here (`../product/src/app.ts`),
it is written here rather than in that repository, and the relation graph does not cross into it.

## Map Grammar (doctor warns on violations)

1. **Fixed entry grammar** — ``- `path` — one-line role``. No other narration.
2. **Map ≠ history** — No dates, incidents, or change-history narration. History belongs to the quest log (`.asgard/quest/`) and git.
3. **Existing files only** — List only files that exist on disk. No pre-listing files you plan to create (ghost prevention).
4. **Ownership split** — `PROJECT.md` is Asgard-only (no manual edits); area maps are human/agent-only (Asgard never overwrites them).
5. **fog-of-war** — Fill deep area maps incrementally, only for explored areas. No full rewrites or bulk generation.
6. **Read first, verify to trust** — Read the map before exploring, but re-confirm every path your plan stands on with Read.
7. **Size and injection safety** — Area files stay at 8 KiB or less. Prose outside the grammar and prompt-control phrasing are excluded from automatic context.
8. **Named absence boundary** — A missing graph edge proves nothing by itself. Check scanner coverage limits and candidate evidence before a no-impact claim.

## Verification

`asgard map check` and `asgard doctor` detect managed drift, ghost entries, grammar, and size violations.
`asgard map scan --json` names unsupported files, excluded tests, parser bounds, and ambiguous joins;
`asgard map impact <node-id> --json` binds the two-way evidence and remaining frontier to a stable revision.
`PROJECT.md` auto-refreshes at main-request/subagent start and before Verifier hash computation, so map
changes are included in the same PASS. Inspect the actual bounded injection with `asgard map context --query "<task>"`.

## Area File Example

```markdown
# map: cli

- `src/app/cli.py` — CLI entry, subcommand routing
- `src/app/commands/` — subcommand implementations (one command per file)
```
