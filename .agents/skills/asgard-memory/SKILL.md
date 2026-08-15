---
name: asgard-memory
description: The two usage contracts of Yggdrasil (Asgard's memory system) — personal memory is a local wiki; shared project knowledge lives in the Git canon plus one selected backend. Use when the user says "remember/save/memory/Yggdrasil" or when details beyond the memory context are needed.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show asgard-memory` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
