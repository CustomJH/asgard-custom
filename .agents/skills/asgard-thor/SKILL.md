---
name: asgard-thor
description: Thor core contract — inline execution standard for backend work (service code, data, API, runtime policy). Loaded by the Worker phase on backend subtasks in tools without subagents.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show asgard-thor` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
