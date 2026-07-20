---
name: grill-me
description: Relentlessly clarify a plan or design, one decision at a time.
disable-model-invocation: true
---

# Grill

Resolve the decision tree before acting.

1. Inspect the environment for facts; never ask the user what tools or files can answer.
2. Ask exactly one decision question per turn. Give a recommended answer and its main tradeoff.
3. Resolve prerequisite decisions before dependent branches. Record assumptions explicitly.
4. Do not edit files, launch implementation, or declare agreement until the user confirms the shared understanding.

Finish when the important branches have explicit decisions and no answer depends on an unresolved term.
