# shape — decide the boundaries before the first line

The cheapest edit is the one you do not make twice. This verb produces a shape you can defend, and
it produces it **in text**, before any file changes.

## Procedure

1. **State the change as one sentence** naming the observable difference. If you cannot, you do not
   yet have a task — you have a topic. Go back and ask.
2. **Trace the path that exists today**: entry point → business rule → value-definition site → store.
   Use Read/Grep, not memory (Canon 5). Write the path down; later verbs reuse it.
3. **Place the change on that path.** Name the single layer that owns it. If your change wants to
   live in two layers, that is two changes — say so.
4. **Declare the contract** before writing the implementation:
   - **Input** — what is accepted, what is rejected, and where validation happens (server-side is
     final; client-side is UX).
   - **Output** — the exact shape, including the failure shape. Same cause = same code. Use the
     repo's existing catalog; if there is none, a minimal one is part of this change.
   - **Transaction boundary** — which operation is the consistency unit.
   - **Idempotency** — for anything retryable, name the key that absorbs a duplicate. "It probably
     won't be retried" is not an answer.
5. **Architecture gate.** The default is `asgard-thor-bilskirnir`'s four layers. Load
   `asgard-thor-clean-hexagonal` **only** when the user explicitly named Clean Architecture,
   Hexagonal, or Ports and Adapters. Do not apply it on your own initiative.
6. **Name the blast radius** — the callers you will affect. `asgard surface --base HEAD` reports
   public-signature changes and the call sites that owe an update.

## Litmus before you leave this verb

- Can you name what the failure response looks like? If not, you have designed the happy path only.
- Can you name what grows as input grows? If not, you do not yet know what the code does.
- Is any part of this irreversible? If yes, it does not belong in `implement` — it belongs in
  `migrate`, which has an approval gate.

## Hand back

    Shape: <layer> owns <operation>; contract <in → out|failure>; tx <boundary>; idempotency <key|n/a>

## Next

`implement` · `migrate` if schema or irreversible data is involved · `integrate` if an external
service is on the path.
