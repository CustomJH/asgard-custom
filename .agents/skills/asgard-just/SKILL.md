---
name: asgard-just
description: The run surface — in a repository that has a Justfile, every command it can run lives there, written from the manifests and extended by hand. Load before running a project command in such a repository, before adding or changing a recipe, and when a task mentions a justfile, a task runner, or where the run commands live. Adoption is opt-in (`asgard just init`); a repository without a Justfile is not missing anything.
disable-model-invocation: true
allowed-tools: Bash(just *), Bash(asgard just *), Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show asgard-just` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
