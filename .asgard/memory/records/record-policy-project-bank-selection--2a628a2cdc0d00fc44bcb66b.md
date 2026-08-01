---
schema: asgard-project-memory-v1
record_id: policy.project-bank-selection
kind: policy
title: Each project selects one bank on the shared memory service
source: src/asgard/memory_bridge/config.py
source_revision: HEAD=464ada93f7c200865ff3bba9f9fa2b9686793227;WORKTREE=cdc42c823d7222be650367a752706a8889c3e7b2ae20ef10cf4893c6bd9bf8e5
importance: critical
confidence: verified
status: active
scope: project
relations:
- type: dependsOn
  target: contract.memory-two-tier-boundary
---

A Hindsight deployment is a shared service that may host multiple banks. Each repository selects its stable bank through project_memory.project_id in .asgard/asgard-setting-project.json; endpoint and engine are stored beside it. The project_uid and binding_id ownership marker remains in the managed sidecar and must match the selected bank, preventing accidental use of a foreign project namespace.
