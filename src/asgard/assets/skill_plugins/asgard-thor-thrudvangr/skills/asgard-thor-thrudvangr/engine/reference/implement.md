# implement — write it, in the shape it will be read in

Load `asgard-thor-magni` (micro-craft) and, for a language whose conventions you have not
established here, `asgard-thor-thjalfi`. Add the surface canon: `mjollnir` for computation,
transactions, batch, and messaging; `lightning` for API, realtime, and external calls.

## The ordering — when these conflict, higher wins

1. **Correct** — a fast, small, leak-free wrong answer is still wrong.
2. **Bounded** — nothing you allocate may grow without a stated limit.
3. **Shaped** — one function states one level of abstraction.
4. **Cheap** — the cost curve, not the constant factor.

Never trade 1 for 4. Trading 3 for 2 is allowed and sometimes correct — say so in the report.

## Procedure

1. **Write the failing case first** when there is one to write. From `diagnose` you already have the
   red→green command; make it part of the change.
2. **Write the smallest diff that satisfies the shape** you declared. Assigned scope only. Defensive
   code you add is in scope too — over-defensiveness foreign to the area's conventions is a defect,
   not caution.
3. **Three reflexes while writing** (these are Magni's, in order):
   - Every acquisition names its release **in the same breath** — `with`/`try-with-resources` if the
     scope owns it, an explicit handoff if the caller does. Assume the process runs for weeks.
   - Handle failure conditions first and return. Nesting is a failure of ordering, not of
     complexity — every guard clause you hoist drops the body one level.
   - Name the growing quantity before you write the loop. A query inside a loop, a scan inside a
     loop, concatenation per iteration, insertion at the front: these have unconditionally better
     forms. Use them from the start.
4. **Never take these trades** (from the role's correctness canon — they have no valid form):
   parameter binding not string interpolation · integer minor units or decimal not float for money ·
   domain owns the transaction boundary, not the handler · idempotency key before any retry ·
   UTC stored, converted at display boundaries · propagate with context, never swallow ·
   stable error code + catalog, never an improvised message string.
5. **Verify the library against current docs, not memory** (Canon 12). Translate reference patterns
   into this project's idioms; do not paste them.

## Gate

    asgard craft

It judges only what this diff made worse. Findings are repair targets, not suggestions. If a shape
is right despite a finding, return the reason with evidence — do not raise the budget, and do not
split a function at the line count. Find where it changes subject, and cut there.

Agents converge on degraded structures and then reinforce them (SlopCodeBench 2603.24755); the
mechanism is the edit that lengthens an already-long function. Refuse that edit specifically.

## Next

`harden` if this path can fail in production (it can) · `migrate` for schema · `sweep` when the
behavior is right.
