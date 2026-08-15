---
name: asgard-provider
description: Bridge for projects where a Trinity role (THINKER/WORKER/VERIFIER) is placed on an external provider via [trinity.<role>] — run that role through the asgard CLI instead of a subagent. Use right after quest-log next assigns the role.
disable-model-invocation: true
allowed-tools: Bash(asgard role *), Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show asgard-provider` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
