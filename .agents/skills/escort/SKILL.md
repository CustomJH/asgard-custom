---
name: escort
description: Generate an interactive script that walks a human through steps only they can take. Use when provisioning infrastructure, obtaining credentials or setting CI secrets, walking an unfamiliar third-party dashboard, or running a one-off migration or cutover. Do not reach for it for steps an agent can perform itself.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show escort` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
