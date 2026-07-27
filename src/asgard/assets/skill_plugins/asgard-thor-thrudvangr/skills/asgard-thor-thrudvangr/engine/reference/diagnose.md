# diagnose — earn the right to edit

Load `asgard-thor-gridarvol` with this. The rule that makes this verb worth having: **you do not
edit until you can name the line where the defect manifests.** A speculative fix is a new defect
wearing the old one's clothes.

## The gate (from the role contract — it blocks, it is not advice)

Do not edit while any of these is still true. Report the diagnosis and return instead:

- reproduction failed
- the actual call path is unconfirmed
- conflicting evidence is unresolved

## Procedure

1. **Build a red→green command first.** Before any theory of cause, secure one command that is red
   at the symptom and will turn green after the fix. Climb only as far as you need:

   ① a failing test → ② a request-reproduction script (status, headers, body) → ③ a capture replay
   (the failing payload as a fixture) → ④ `git bisect run` with a *narrow* judge command →
   ⑤ report reproduction failure, with the angles you tried.

   For intermittent failures, raise the reproduction rate before diagnosing. 50% is diagnosable; 1%
   effectively is not. Pin the nondeterminism you can: time, seeds, network, ordering.

2. **Isolate the layer** before digging. Slice the request path and find which slice the symptom
   lives in: connection → timeout (connect latency vs response latency are different measurements) →
   TLS → authn/authz → request format → response parsing → semantics.

   Status-code playbook: 401 expiry/scheme · 403 scope/ownership · 404 path · 409 contention or
   idempotency key · 422 schema drift · 429 Retry-After + backoff · 5xx take the correlation ID and
   trace upstream. Some protocols carry errors inside a 200 body — never trust the status alone.

3. **Form up to three hypotheses, each with its evidence. Pick one.** Test that one. Do not stack
   changes; a fix that works for an unknown reason is not a fix.

4. **Verify the premise before calling it a bug.** Check the original intent
   (`git log -p -S "<symbol>"`). Sometimes the isolation *is* the design. Sometimes absence bears
   load — restoring "obviously missing" code can break existing behavior, so find the consumers of
   the absence first.

5. **Instrument boundaries, not the symptom site.** With two or more components involved, record in
   and out values at every boundary, find where the value first goes wrong, and fix it there.
   Temporary logs carry a unique prefix (`[DBG-xxxx]`) so cleanup is one search — `sweep` will
   check that the search comes back empty.

## Rule of three

If three substantially different approaches fail, this is not a local defect but a structural one.
Stop stacking risk. Return with the attempts and the elimination evidence, plus a minimal structural
proposal and a blast-radius estimate.

## Hand back

    Diagnosis: <line where it manifests>; repro: <command, red→green>; cause: <one sentence>

## Next

`implement` — carrying the red→green command with you. A fix without a regression case is a
scheduled recurrence, so the case is part of the change, not a follow-up.
