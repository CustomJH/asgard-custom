---
name: asgard-thor-thrudvangr
description: Þrúðvangr, Thor's field — the procedure engine for backend work. Routes a backend task to one of eleven verbs (survey, shape, diagnose, implement, migrate, integrate, harden, scale, sweep, evidence, squad), each a playbook that names which canon to load, which deterministic gate judges it, and what evidence closes it. Load at the start of any backend task, and whenever you are unsure which Thor skill applies.
---

# asgard-thor-thrudvangr — 🌾 The Procedure Engine

Thor's canon skills say **what is true**. This one says **what to do next, and in what order**.

That split matters because the canons are selected by judgment, and judgment is the thing that
degrades: instruction-following drops monotonically across turns (Multi-IF 2410.15553, 0.877 → 0.707
by turn 3), and structural requirements decay the more of them you hold at once (2605.06445). A
procedure survives that decay because each step names the next one — you do not have to remember the
arc, only where you are on it.

## Rule zero — the machine carries the rules

Two deterministic gates exist. Neither is advisory, and neither is something you score yourself:

    asgard craft        # 형상 — unit size, nesting, resource lifetime, cost curve
    asgard thor gate    # 정확성 — SQL interpolation, swallowed exceptions, missing timeouts,
                        #          hardcoded secrets, external I/O inside a transaction, float money

Both ratchet: they judge only what **this change** made worse, so inherited debt never blocks you.
Both print what they could **not** measure — silence there means "not judged", never "clean". When a
gate blocks, you fix it or you return the reason the shape is right, with evidence. You do not
re-run it hoping for a different answer, and you do not summarise a finding away.

Clearing both gates is the **floor, not the verdict.** Neither can see cross-file lifetime, whether
an input is externally controlled, or whether your idempotency story is real. Those stay yours.

## The verbs

Run `asgard thor <verb>` to load a playbook. With no argument, `asgard thor` reads the working tree
**and the survey record** and recommends the next two or three — including `survey` itself when this
repository has never been surveyed, when the manifests have changed since it was, or when judgement
fields are still blank.

| Verb | Take it when | Canon it loads | Gate |
|---|---|---|---|
| `survey` | first backend task in this repo, or the stack is unstated | — | persists to `.asgard/thor/` |
| `shape` | before writing: boundaries, contracts, failure shape | bilskirnir · clean-hexagonal (opt-in) | — |
| `diagnose` | a defect, regression, or incident — **before** any edit | gridarvol | — |
| `implement` | writing the change | magni · thjalfi · mjollnir/lightning | craft |
| `migrate` | schema, index, or irreversible data change | jarngreipr | thor gate |
| `integrate` | an external service, or a wire protocol | lightning · vimur | thor gate |
| `harden` | failure paths, timeouts, retries, idempotency | mjollnir · lightning | thor gate |
| `scale` | post-deploy runtime behavior | megingjord | — |
| `sweep` | before returning — integrity pass | tanngrisnir · magni | craft + thor gate |
| `evidence` | writing the report | tanngrisnir | — |
| `squad` | 2+ separable surfaces / 3+ files | einherjar | — |

## Routing — pick the entry verb, then follow the handoffs

1. **Is it broken?** → `diagnose`. Never `implement` first; a speculative fix is a new defect.
2. **Do you know this repo's conventions?** No → `survey`. Yes → next.
3. **Is the change bigger than one surface?** → `squad`, then each member enters at `implement`.
4. **Otherwise** → `shape`, and take the surface verb it hands you.

Each playbook ends by naming its successor. Follow that chain rather than re-deciding at every step —
re-deciding is where the arc gets dropped. Every path ends at `sweep` → `evidence`.

Skipping a verb is allowed and often right; **silently** skipping one is not. If you skip `harden` on
a path that calls an external service, say so and say why.

## What this engine will not do

- It does not replace the canons — it selects them. A playbook that names `jarngreipr` means load it,
  not paraphrase it from memory.
- It does not lift the role contract: assigned scope only, no completion claims, side-effect approval
  belongs to Odin.
- It does not self-score. "Gates clear" is a fact about the gates; whether the work is done is a
  verdict, and the verdict belongs upstream (Canon 10).
