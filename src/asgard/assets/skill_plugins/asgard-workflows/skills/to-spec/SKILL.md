---
name: to-spec
description: Turn the current discussion into a durable implementation spec.
disable-model-invocation: true
---

# To spec

Synthesize the current conversation; do not restart the interview.

1. Inspect the repository and read relevant `CONTEXT.md` and ADRs. Reuse their vocabulary.
2. Identify the highest public seam that can prove the requested behavior and prefer existing seams.
3. Write the spec in the repository's existing convention, otherwise `docs/specs/<short-slug>.md`.
4. Include: problem, user-visible solution, acceptance criteria, implementation decisions, testing decisions, out of scope, and unresolved assumptions.
5. Do not implement the spec in this invocation.

Finish when another fresh-context Worker can execute the spec without reconstructing decisions from chat history.
