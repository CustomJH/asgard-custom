# harden — make the failure paths real, not described

A path that has only ever been described is untested. This verb turns the failure story from
`shape`/`integrate` into something that has actually run.

## Exercise, do not assert

For each declared failure mode, produce evidence that it does what you said:

- **Timeout** — force it (an unroutable host, a stub that sleeps past the budget). Confirm the
  caller gives up at the stated time and returns the stated failure shape, not a hang.
- **Retry** — run the operation twice against the same idempotency key and confirm one effect, not
  two. This is the test that catches "we'll add the key later".
- **Partial failure** — fail the second of two writes and confirm the compensation or the containment
  actually leaves the system in the state you claimed.
- **Malformed response** — feed the parser something the vendor document says is impossible. It must
  be **rejected**, not ignored and not defaulted.
- **Empty and boundary inputs** — no rows, one row, the page cap, one past the cap.

## The masking-fallback rule

Every fallback is one of two kinds, and you classify each one you wrote:

- **Masking (banned)** — swallowed errors, silent defaults, bypassed validation, an untested alternate
  path, a downgraded diagnostic. On sight this is a defect and a repair target, not a completion.
  Never render missing data as `0` or OK — "insufficient data" is itself what gets displayed.
- **Justified (allowed)** — confined to a known external or version boundary, **both** paths tested,
  failure evidence preserved, and the rationale left in the code.

`asgard thor gate` enforces the mechanical half of this: a broad exception handler whose body is
silent blocks, unless the rationale is written at the handler. That comment is not a way past the
gate — it is the justification the canon already required.

## Concurrency, if this path has any

Minimising shared mutable state is the opening move, not the optimisation. A suspected race gets no
speculative fix — reproduce it first, with repeated runs or forced interleaving. A serial bus or any
half-duplex transport carries one conversation at a time; concurrency lives above it, in a queue
with one owner, never in two threads holding one port.

## Backpressure

If consumption lags production persistently, that is a design problem, not a buffer-size problem.
Observe queue depth and cap it. Poison messages go to a DLQ after a retry cap — infinite requeueing
stalls the whole pipeline.

## Gate

    asgard thor gate

## Hand back

    Hardened: <mode> → <how it was forced> → <observed result>    (one line per failure mode)

## Next

`sweep`.
