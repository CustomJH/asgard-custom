---
name: asgard-seal
description: Commit current working-tree changes with a required gitmoji and Conventional Commit type in one session. NEVER add author, signature, or AI attribution footers.
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(git status *), Bash(git diff *), Bash(git add *), Bash(git commit *), Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show asgard-seal` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
