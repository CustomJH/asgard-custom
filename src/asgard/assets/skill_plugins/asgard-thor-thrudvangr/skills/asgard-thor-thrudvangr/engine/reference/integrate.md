# integrate — everything across a boundary you do not control

Load `asgard-thor-lightning`. If the boundary is a wire protocol (Modbus, serial, fieldbus, any
byte-framed device link) load `asgard-thor-vimur` as well — that domain fails silently and needs a
reference oracle, not a review.

## Without these three it is not an external call

1. **An explicit timeout.** Library defaults are frequently infinite. Layer them: outer longer than
   inner (client > gateway > service > this call). Inverted timeouts produce ghost failures where
   the inner layer is alive and the outer one has already hung up.
2. **A declared failure strategy.** Retry (idempotent requests only, exponential backoff + jitter,
   an explicit cap), fall back, or propagate. "Assume it works" is not a strategy. Retrying a
   non-idempotent request without an idempotency key is a duplicate-execution incident.
3. **Compensation or containment for partial failure.** Name what happens to state already written
   when the second call fails.

## Treat the response as unvalidated input

An external response is input from a system you do not control. Validate it against a schema before
use — the same rule as any request body (Canon 5). Check the content type before deserialising; some
protocols return errors inside a 200 body.

Never let an external call sit inside a transaction. Side effects before commit cannot be undone by
a rollback — publish through an outbox instead. `asgard thor gate` blocks this one statically.

## Circuit breaking

Open after a consecutive-failure threshold, probe half-open. Without it, every request against a
dead dependency waits for its full timeout, and your thread pool becomes the outage.

## Server-fetches-a-URL is SSRF

If any part of the destination comes from user input, internal-network blocking and allowlist
validation are mandatory, not hardening for later.

## For wire protocols specifically

Validate against something that is not yourself — testing your decoder against your own encoder
proves only that you were consistent. Establish the published check value first (CRC-16/MODBUS of
`123456789` is `0x4B37`); if that does not match, nothing else you measure means anything. The
bundled oracle runs without hardware:

    python3 scripts/modbus_ref.py selftest
    python3 scripts/modbus_ref.py serve --port 15020

## Gate

    asgard thor gate

Catches the missing timeout and external I/O inside a transaction. It cannot tell whether your
retry is idempotent — that stays a judgment, and you state it.

## Hand back

    Integration: <service>; timeout <value, layered under X>; on failure <retry|fallback|propagate>;
    response validated <how>; partial failure <compensation>

## Next

`harden` — the failure paths you just declared now need to be exercised, not just described.
