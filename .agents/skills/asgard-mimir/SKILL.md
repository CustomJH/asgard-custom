---
name: asgard-mimir
description: Mimir core contract — the inline execution baseline for code explanation, walkthroughs, and onboarding (execution-flow narrative + cognitive-debt defense). Load for code-comprehension quests in tools without subagents.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show asgard-mimir` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
