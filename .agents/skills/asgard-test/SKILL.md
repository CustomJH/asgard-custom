---
name: asgard-test
description: Asgard setup self-test — three-layer verification (wiring, harness, live) plus hook latency. Reports as a scorecard.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

Run `asgard skills show asgard-test` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
