---
name: asgard-skillcraft
description: Writing any document an agent reads. Use when creating or editing a skill, changing AGENTS.md / CLAUDE.md / MANUAL.md or a doc the harness injects, choosing user or model invocation, cutting context load by disclosing reference, or pruning prose that changes no behavior.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show asgard-skillcraft` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
