---
schema: asgard-project-memory-v1
record_id: contract.memory-two-tier-boundary
kind: contract
title: Personal and project memory stay canonically separate
source: README.md
source_revision: HEAD=464ada93f7c200865ff3bba9f9fa2b9686793227;WORKTREE=cdc42c823d7222be650367a752706a8889c3e7b2ae20ef10cf4893c6bd9bf8e5
importance: critical
confidence: verified
status: active
scope: project
relations: []
---

Asgard has exactly two durable memory scopes. Personal memory is canonical only under ~/.asgard/memory/pages and must never be retained in Hindsight. Project knowledge is canonical under .asgard/memory/records in the repository; Hindsight is a replaceable derived retrieval and learning backend. Recall may combine both scopes, but storage, provenance, and approval remain separate.
