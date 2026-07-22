# MIGRATION — 0.1.x → 1.9.x

The current release is a skill-driven, bin-only package. The CLI installs and diagnoses the Vanadis bundle; design work happens through natural-language prompts inside your coding agent. It ships 20 skills, 18 specialist roles, and a local catalog of 440+ `DESIGN.md` references.

This guide is for projects that used `vanadis-cli` 0.1.x. Existing project `DESIGN.md`, `.vanadis/preferences.md`, and `.vanadis/runs/` files remain useful; do not delete them.

## Upgrade each project

From the project root:

```bash
npx vanadis-cli@latest
```

Choose the project-local channels you actually use, restart those coding agents, and verify the installed files:

```bash
npx vanadis-cli@latest doctor
```

`doctor` reports the real channel paths, catalog/fingerprint coverage, specialist roles, hooks, and whether the project has a root `DESIGN.md`. If it finds an incomplete managed install, run the exact repair command it prints and then run `doctor` again. A stale managed Claude hook is repaired with the targeted `--repair-hooks` flag; unrelated unmarked files remain untouched.

For a user-level Claude Code, Codex, or OpenCode installation, use `install-skills --global` and verify it with `doctor --global`. Cursor rules are intentionally project-scoped and reject `--global`.

## The important break

The 0.1.x operational CLI commands were removed in 1.0.0. The supported CLI surface is now:

- `npx vanadis-cli@latest` — guided installer;
- `npx vanadis-cli@latest install-skills ...` — explicit/non-interactive installation; and
- `npx vanadis-cli@latest doctor` — health check and scoped repair instruction.

The package no longer exposes a programmatic TypeScript API. Code that imported `vanadis-cli` must migrate to the installed markdown skills/data or invoke the bin as an installer/doctor.

## 0.1.x command map

The following prompt-based replacements apply to **Claude Code, Codex, and OpenCode**, where Vanadis skills are installed:

| Removed 0.1.x command | Current workflow |
|---|---|
| `vanadis init recommend "..."` | Ask: `Set up our design system — Linear-style, for a B2B operations dashboard.` The agent uses `vanadis:init`, recommends a reference, asks for confirmation, and writes root `DESIGN.md`. |
| `vanadis init prepare --ref vercel ...` | Ask: `Create our DESIGN.md using Vercel as the reference; keep unverified facts absent.` |
| `vanadis remember "..."` | Say the correction naturally, for example: `Remember this preference: cards use borders, not decorative shadows.` The `vanadis:remember` skill records it. |
| `vanadis learn` | Ask: `Fold confirmed preferences into DESIGN.md.` The `vanadis:learn` skill presents the proposal before changing the system. |
| `vanadis sync` | Ask: `Sync DESIGN.md into the agent instruction shims.` The `vanadis:sync` skill updates managed blocks. |
| `vanadis harness "..."` | Run `/vanadis-harness <task>` or ask for the full Vanadis design harness. Mandatory user checkpoints remain in place. |
| `vanadis generate` | Removed. Create/download `DESIGN.md` in the [Builder](https://vanadis.kr/builder), or ask a skill-enabled agent to set it up. |
| `vanadis preview` | Removed. Ask the coding agent to build and open the actual product route. |
| `vanadis reference list/show` | Browse the [reference catalog](https://vanadis.kr/design-systems), read an installed channel catalog, or fetch `https://vanadis.kr/<id>/design.md`. |
| `vanadis context --internal` | Context discovery is part of the installed skills/harness. The deterministic helper remains bundled for internal skill use. |
| `vanadis setup-blender` | Removed from the public CLI. Asset workflows guide optional tooling only when it is actually needed. |

## Channel capabilities and paths

| Channel | Project installation | What can run |
|---|---|---|
| Claude Code | `.claude/{skills,agents,data}/` plus managed project hooks/settings | 20 skills, 18 specialist roles, local catalog |
| Codex | `.agents/skills/`, `.codex/agents/`, `.codex/data/` | 20 skills, 18 embedded specialist-role definitions, local catalog; the project must be trusted |
| OpenCode | `.opencode/{skills,agents,data}/` | 20 skills, 18 native agents, local catalog |
| Cursor | `.cursor/rules/vanadis-design.mdc` plus `.claude/data/` | One project rule and the local catalog; **no Vanadis skills or sub-agents** |

Codex's old Vanadis-managed `.codex/skills/` entrypoints are retired. A current reinstall migrates installer-owned files to `.agents/skills/` while preserving private, unowned files. OpenCode now uses its native `skills`, `agents`, and `data` directories.

### Cursor migration is different

Do not ask Cursor to run `vanadis:init`, `vanadis:feel`, or `/vanadis-harness`: the Cursor channel does not install those skills or specialist roles.

Use one of these supported paths instead:

1. Select/customize a reference in the [Builder](https://vanadis.kr/builder), download `DESIGN.md`, and save it at the project root; or
2. ask Cursor explicitly:

   ```text
   Read .claude/data/references/toss/DESIGN.md and create a root DESIGN.md
   for this product using confirmed values only. Keep unknown facts absent.
   ```

Then ask Cursor to build against `@DESIGN.md`. The installed rule's contract is intentionally small: read root `DESIGN.md` before UI work, apply pending `.vanadis/preferences.md` corrections, and use framework defaults only after those two sources.

## Managed upgrades and local edits

Current installs are idempotent:

- installer-owned skills, roles, catalog entries, and hooks carry managed markers/hashes and refresh when unchanged;
- same-ID reference edits, private references, and unmarked user files are preserved;
- retired installer-owned files can be cleaned up without deleting user sidecars;
- `--repair-hooks` refreshes the managed Claude hook bundle only; and
- `--force` is an explicit last resort for overwriting drift. Review local edits before using it.

After every bundle upgrade, restart the coding agent and run:

```bash
npx vanadis-cli@latest doctor
```

## Data retained from 0.1.x

- Root `DESIGN.md` remains the authoritative project design specification.
- `.vanadis/preferences.md` remains the preference/correction store and should be retained.
- Existing `.vanadis/runs/<id>/` directories remain learning artifacts; do not delete them.
- The npm package is bin-only. The removed `src/index.ts` exports have no replacement public API.

For the current first-run flow, see [docs/CLI_QUICKSTART.md](docs/CLI_QUICKSTART.md). For release-by-release changes, see [CHANGELOG.md](CHANGELOG.md).
