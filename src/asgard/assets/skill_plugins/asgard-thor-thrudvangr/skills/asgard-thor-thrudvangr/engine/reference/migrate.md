# migrate — the verb with an approval gate

Load `asgard-thor-jarngreipr`. This verb exists because schema and data changes are the ones you
cannot take back, and the difference between a migration and an incident is written down in advance.

## Grade first — it decides whether you may execute at all

| Grade | Target | Action |
|---|---|---|
| 🟢 | reads · local/ephemeral environments | execute |
| 🟡 | DML in a shared environment | deliver impact scope, estimated row count, and the undo method; execute only if the assignment says so |
| 🔴 | schema changes, migrations | expand-contract + rollback plan required, included in the report |
| ⚫ | production, or destructive without backup (drop, truncate, irreversible update) | **do not execute** — return a plan; approval belongs to Odin |

A task assignment is not approval. Litmus: "if I regret this immediately, is there a way back?" If
not, it is ⚫.

## Expand–contract — three steps, three deploys

1. **Expand** — add the new column/table. Nullable, or with a default. Nothing reads it yet.
2. **Migrate** — dual-write or backfill. The backfill follows Mjölnir's batch durability contract:
   a checkpoint, a declared re-entry point, a partial-failure policy, and observable progress. No
   one-shot mass UPDATE — it takes locks and it lags replicas. Chunk and throttle.
3. **Contract** — remove the old path, only after confirming zero usages.

Destructive changes (column removal, type narrowing, adding NOT NULL) happen **only** in step 3.
Each step survives the deploy window where old and new code run at once — that is the whole point of
the split, so do not collapse it to save a deploy.

A migration without a rollback plan is unfinished. "We roll forward" counts only if you write it
down as the plan.

## Indexes

- The evidence is a measured query plan. There are no "it might be slow" indexes. Attach before and
  after plans and execution times.
- State the write cost — indexes are not free; say what it does to a write-heavy table.
- On a large table, create online where supported, and never execute without a lock-duration
  estimate.

## Derived data

Search indexes, caches, and materialised views may be destroyed **only** after the rebuild procedure
has been confirmed to work — not assumed to exist.

## Gate

    asgard thor gate

It catches value-slot SQL interpolation, transactions with external I/O inside them, and float
money. It cannot see lock duration, replication lag, or whether your backfill is restartable. Those
are yours.

## Hand back

    Migration: grade <🟢🟡🔴⚫>; steps <expand|migrate|contract>; rollback <plan>; plans <before/after>

## Next

`evidence`. If the grade is ⚫, `evidence` is where the plan is delivered — you stop before
executing.
