"""Memory v3 — Claude Code 저장 계약 스킬 (감사 권고: "파일 직접 편집 금지, ingest 승인 경유").

스킬 하나가 읽기(query)와 쓰기(ingest 승인 게이트) 계약을 모두 싣는다. 훅(memory-activate)이
스냅샷을 주입하고, 상세 회수·저장은 이 계약대로 CLI 를 경유한다 — 로직 재구현 금지."""

MEMORY_SKILL_MD = """---
name: asgard-memory
description: 개인 메모리(LLM wiki) 사용 계약 — 검색은 asgard memory query, 저장은 ingest 승인 게이트 경유. 사용자가 "기억해/저장해/메모리" 를 말하거나, 세션 컨텍스트의 <memory-context> 카탈로그에서 상세가 필요할 때 사용.
---

# asgard-memory — 개인 메모리 사용 계약

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

1. ingest 가 계획(create / 기존 페이지 merge)을 출력한다
2. 계획을 사용자에게 보여주고 승인을 받는다 (ask-before-save)
3. 승인 시에만 `--yes` 로 재실행한다 — 계획이 바뀌면(stale plan 오류) 처음부터 다시

## 불변식

- 메모리는 **힌트**다 — 완료 증거·검증 criteria 로 쓸 수 없다 (게이트는 메모리를 신뢰하지 않는다)
- 코드/저장소에서 1분 내 파악 가능한 사실은 저장하지 않는다
- 개인 스코프 전용 — 프로젝트 공유 지식은 여기 넣지 않는다 (용어 방화벽)
- 유지관리: `asgard memory lint` 가 부패·중복·오염을 보고하면 merge/remove 로 정리
"""
