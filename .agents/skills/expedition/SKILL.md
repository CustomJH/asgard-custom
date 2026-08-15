---
name: expedition
description: Map a decision-heavy effort that cannot fit in one agent session.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show expedition` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
