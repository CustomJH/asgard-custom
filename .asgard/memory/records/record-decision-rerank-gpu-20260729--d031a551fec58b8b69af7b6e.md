---
schema: asgard-project-memory-v1
record_id: decision.rerank-gpu-20260729
kind: decision
title: 프로젝트 메모리 리랭커는 GPU litellm 경로를 쓴다
source: docker/asgard-project-memory/README.md
source_revision: 6478b08b7fa0077ca42d4c0a74ffb065dd4494d6
importance: critical
confidence: verified
status: active
scope: project
relations: []
---

한국어 회수에서 영어 전용 기본 리랭커(cross-encoder/ms-marco-MiniLM-L-6-v2)는 top-1 정답이 14문항 중 0건이었고 BAAI/bge-reranker-v2-m3 은 12건이었다. 같은 모델을 GPU(litellm wams-rerank)로 옮기면 hit@1 과 MRR 이 동일하고 p50 지연만 57.05s 에서 0.535s 로 줄어든다.
