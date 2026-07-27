# sweep — the pass that runs on everything, before returning

Load `asgard-thor-tanngrisnir`. The goat revives only if its bones are intact. Every path through
this engine ends here — this is not optional polish, it is the last thing between your diff and
someone else's afternoon.

## Run both gates, in this order

    asgard craft        # did this diff make the shape worse?
    asgard thor gate    # did this diff make the correctness worse?

Read the whole output, not the exit code. Three sections matter:

- **Blocking** — fix, or return the reason the shape is right with evidence.
- **Notices** — they do not block, and they are still real. Say what you did with each.
- **미판정 / unmeasured** — the files and rules that were **not** judged. This is the part you carry:
  a language the judge does not know is not a clean language.

## Then sweep by hand — what the gates cannot see

1. **Debug residue.** One bulk search for the diagnostic prefix you used in `diagnose`
   (`[DBG-xxxx]`). It must come back empty. Temporary logs, commented-out code, scratch files.
2. **Unnecessary abstraction.** A single-use helper extracted preemptively, a pass-through wrapper,
   speculative indirection. Each must justify the diff it adds; most cannot.
3. **Over-defensiveness foreign to the area.** Re-validating an already-trusted path, a blanket
   try/catch you added out of habit. Defensive code is inside the assignment scope, so it is
   reviewable like everything else (Canon 7).
4. **Boundary violations.** A wrong-layer import, hidden coupling introduced to make the change fit.
   If fixing it is out of scope, report the finding — do not leave it silent.
5. **Cross-file lifetime** — the thing no static judge here can reach. Registered listeners and
   subscriptions, timers and background tasks, callbacks captured in closures that outlive their
   subject, module-level state you appended to, anything attached per request or per turn. Name what
   removes each one.
6. **The diff itself.** Read it end to end as a reviewer would. Anything you cannot explain in one
   sentence does not belong in it.

## Scope discipline

If the sweep finds a defect outside your assigned scope, you do **not** fix it. Add it to the report
as a finding. Widening the diff to look thorough is how a reviewable change becomes an unreviewable
one.

## Hand back

    Sweep: craft <n blocking / n notes / n unmeasured>; gate <same>; residue <clean|list>;
    out-of-scope findings <list|none>

## Next

`evidence`.
