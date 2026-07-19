---
name: asgard-skillcraft
description: Predictable agent-skill design and pruning. Use when writing or refactoring SKILL.md, choosing user/model invocation, reducing context load, splitting references, or testing prompt no-ops.
agent: worker
---

# Skillcraft

A skill makes a stochastic model follow the same **process**, not emit the same answer.

1. Trace the real invocation and loaders before editing. Choose **user-invoked** when only a human should start it; choose **model-invoked** only when autonomous discovery or skill-to-skill reuse earns permanent description load.
2. Map the skill's branches. Keep universal steps and their checkable completion criteria in `SKILL.md`; move branch-only reference behind a precise relative-file pointer.
3. Replace repeated explanation with one established **leading word** the model can reuse. State the desired behavior positively.
4. Prune duplication and sediment. A sentence is a no-op only after a **deletion test** shows equivalent behavior; static dislike is not evidence.
5. Verify both surfaces: frontmatter/parser/client discovery, then the canonical body/resource loader. Measure catalog and loaded-body size before and after.

For the full rubric, deletion-test protocol, and Asgard compatibility checks, load `CHECKLIST.md` with the current skill resource loader.
