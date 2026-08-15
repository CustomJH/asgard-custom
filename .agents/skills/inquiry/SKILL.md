---
name: inquiry
description: Turn a decision the user cannot answer alone into a document for the one person who can.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show inquiry` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
