---
schema: asgard-project-memory-v1
record_id: policy.hindsight-approved-learning
kind: policy
title: Hindsight learns only from approved project records
source: src/asgard/project_memory/learning.py
source_revision: HEAD=464ada93f7c200865ff3bba9f9fa2b9686793227;WORKTREE=cdc42c823d7222be650367a752706a8889c3e7b2ae20ef10cf4893c6bd9bf8e5
importance: critical
confidence: verified
status: active
scope: project
relations:
- type: dependsOn
  target: contract.memory-two-tier-boundary
- type: implements
  target: policy.project-bank-selection
---

Hindsight observations are enabled, but automatic bank-wide consolidation is disabled because the bank also contains deterministic documents and artifacts. Approved Git-canonical records carry the record tag and use the concise retain strategy; successful approval schedules consolidation only for that tag. Three strict record-scoped delta mental models maintain architecture, decisions and risks, and delivery operations.
