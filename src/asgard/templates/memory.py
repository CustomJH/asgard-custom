"""Memory v3 — Claude Code 저장 계약 스킬 (감사 권고: "파일 직접 편집 금지, ingest 승인 경유").

스킬 하나가 읽기(query)와 쓰기(ingest 승인 게이트) 계약을 모두 싣는다. 훅(memory-activate)이
스냅샷을 주입하고, 상세 회수·저장은 이 계약대로 CLI 를 경유한다 — 로직 재구현 금지."""

MEMORY_SKILL_MD = """---
name: asgard-memory
description: Asgard의 두 메모리 사용 계약 — 개인은 로컬 wiki, 프로젝트 공유 지식은 Hindsight. 사용자가 "기억해/저장해/메모리" 를 말하거나 memory context의 상세가 필요할 때 사용.
---

# asgard-memory — 개인/프로젝트 메모리 사용 계약

세션에 주입된 `<memory-context>` 는 **카탈로그(제목만)** 다. 상세가 필요하면 검색하라.

## 읽기 (zero-LLM)

```bash
asgard memory query "<검색어>" --json   # FTS + 한국어 단어 폴백, 오염 페이지 자동 제외
asgard memory show <slug>               # 페이지 전문
```

## 쓰기 — 반드시 승인 게이트 경유

`~/.asgard/memory/` 파일을 **직접 편집·생성하지 마라** (Write/Edit 금지). 저장은 단 한 경로:

```bash
asgard memory ingest "<자립적인 사실 한 건>" --kind <note|user|decision|insight|reference|feedback>
```

1. ingest 가 계획(create / 기존 페이지 merge)과 `approval-id`를 출력한다
2. 계획을 사용자에게 보여주고 승인을 받는다 (ask-before-save)
3. 승인 시에만 **같은 본문·kind와 ID**로 재실행한다:
   `asgard memory ingest "<동일 본문>" --kind <동일 kind> --yes --plan-id <approval-id>`
4. ID는 승인된 action·target·revision에 묶여 1회만 소비된다. stale 오류면 처음부터 다시 계획한다

## 불변식

- 메모리는 **힌트**다 — 완료 증거·검증 criteria 로 쓸 수 없다 (게이트는 메모리를 신뢰하지 않는다)
- 코드/저장소에서 1분 내 파악 가능한 사실은 저장하지 않는다
- 개인 스코프 전용 — 프로젝트 공유 지식은 여기 넣지 않는다 (용어 방화벽)
- 유지관리: `asgard memory lint` 가 부패·중복·오염을 보고하면 merge/remove 로 정리

## 프로젝트 공유 메모리 — Hindsight

`<memory-recall scope="project">`는 현재 프로젝트의 Hindsight bank에서 온다. 일반 조회는 자동이지만
명시 검색은 MCP `memory_recall`을 사용한다. 중요한 코드·문서 bootstrap은 먼저 미리본다:

```bash
asgard memory project-scan --all
asgard memory project-sync --all       # 계획만, 외부 쓰기 없음
asgard memory project-sync --all --yes --plan-id <preview-plan-id> # 동일 snapshot 승인 뒤 실행
```

프로젝트 사실 저장은 MCP `memory_retain` → 사용자 승인 → `memory_retain_commit`의 2단계만 사용한다.
반드시 `record_id`, `kind`, `title`, `content`, `source`, `source_revision`, `importance`,
`confidence`, `status`를 채운다. 허용 kind는 decision/policy/contract/component/incident/
experiment/migration/runbook이다.

등록한다: 장기 유효한 팀 결정·정책·공개 계약·핵심 컴포넌트 경계·장애 원인/복구·검증된 실험·
migration·runbook. 등록하지 않는다: 개인 선호, 임시 진행상태/TODO, raw 로그, 코드에서 즉시 알 수
있는 사소한 사실, 생성물, 미검증 추측, secret/credential. 변경은 기존 record_id를 replace하거나
`supersedes` 관계로 이력을 남기고, source revision 없는 사실은 저장하지 않는다.
"""
