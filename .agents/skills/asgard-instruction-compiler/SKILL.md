---
name: asgard-instruction-compiler
description: Interpret vague, colloquial, or poorly structured user intent and compile it into an executable prompt or delegation packet using current repository evidence and approved Asgard memory. Use for ambiguous requests, system prompts, reusable templates, few-shot examples, constraints, tone, or instructions to subagents, team agents, Freyja/Thor squads, and other delegated workers.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show asgard-instruction-compiler` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
