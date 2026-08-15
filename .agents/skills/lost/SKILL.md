---
name: lost
description: Stop. That last message did not land — pitch it again.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show lost` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
