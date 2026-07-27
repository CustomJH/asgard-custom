# squad — when the change is bigger than one head

Load `asgard-thor-einherjar`. This verb is read by the squad lead (`asgard-thor-lead`) and by the
Worker running it. A solo Thor cannot take it — return the judgment that a squad is needed rather
than forming one.

## Formation verdict — only when it justifies the token tax

| Signal | Formation |
|---|---|
| single file, atomic change | **no squad.** This is the correct call, not under-formation — multi-agent carries roughly a 15× token tax |
| 2+ separable surfaces / 3+ files / ~200+ lines | split squad, 2–4 members |
| unfinished after two substantially different inline approaches, or the approach itself is contested | tournament squad, 2–3 members |

## Split squad

Verify the split on three points before dispatching: the union of the children equals the parent's
scope (nothing missing), the children do not overlap (no shared file), and each child is closer to
atomic than the parent. A failed verification gets one repair pass; a second failure escalates.
Never accept a bad split silently.

- **Contracts first.** If one unit produces a contract (types, signatures, schema, API) that another
  consumes, they cannot run in parallel. Finalise the producing unit, then send the consumer in the
  next wave.
- If two members might touch the same file, the lead takes that file directly.

## Tournament squad

Each member attacks the same problem on a **different axis**, in an isolated worktree, in parallel.
N copies of the same brief cluster on the same answer — force the axis distribution explicitly. Only
the one winner that passes verification (the red→green command) reaches the mainline; the losers are
discarded, not merged.

## The brief — an ambiguous brief is the top cause of duplication and gaps

1. **Target** — exact files and symbols, plus explicit non-goals and the boundary with other members.
2. **Change** — step by step.
3. **Acceptance** — an observable result and a **unit-scoped** verification command. Never assign a
   global build or the full suite to a member; the global gate is the lead's, run once after
   integration.
4. **Shared contract duplicated verbatim** into every brief that needs it.
5. **Domain skill attached verbatim** — Jarngreipr for a data-risk unit, Gríðarvölr for a diagnosis
   unit. A lead's paraphrase is lossy compression.

Members always get a **fresh context** — never the lead's history or another unit's details. A failed
unit gets a fresh-context regeneration, not a same-context repair. Cap 3–5 files per member; never a
glob, never "update everything".

## Integration is the lead's job

- Members return: changed files + decision summary + verification evidence + blockers. Not a work log.
- The lead keeps two ledgers apart: a **plan** ledger (facts, decisions, formation) and a **progress**
  ledger (per-unit status). More than two rounds without progress means rewriting the plan, not
  retrying the member.
- After convergence the lead runs the global gates once over the union of changed files — `asgard
  craft` and `asgard thor gate` included — and records command and exit code. A member's summary is
  a summary; the lead runs it.

## Invariants

**Depth 1** — members do not re-delegate. **Verification independence** — the Verifier never invokes
a squad, and verdict subordinates run read-only (loki, a separate session). No bypass path around
the upstream gate. No completion declarations: the lead's output is the formation record, per-unit
evidence, the integration log, and residual risk.

## Solo fallback

When no squad is available, run the same procedure as a checklist: unit split with non-overlap
verification, contracts first, per-unit evidence, final union verification — in that order, each
step's output left on file. Without the structure the procedure evaporates; that is the measured
result, not a caution.

## Next

Each member enters at `implement` (or `diagnose` if their unit is a defect). The lead ends at
`sweep` → `evidence`.
