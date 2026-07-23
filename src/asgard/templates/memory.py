"""Memory v3 — Claude Code 저장 계약 스킬 (감사 권고: "파일 직접 편집 금지, ingest 승인 경유").

스킬 하나가 읽기(query)와 쓰기(ingest 승인 게이트) 계약을 모두 싣는다. 훅(memory-activate)이
스냅샷을 주입하고, 상세 회수·저장은 이 계약대로 CLI 를 경유한다 — 로직 재구현 금지."""

MEMORY_SKILL_MD = """---
name: asgard-memory
description: The two usage contracts of Yggdrasil (Asgard's memory system) — personal memory is a local wiki; shared project knowledge lives in the Git canon plus one selected backend. Use when the user says "remember/save/memory/Yggdrasil" or when details beyond the memory context are needed.
---

# asgard-memory — Yggdrasil (personal/project memory) usage contract

Personal memory is **Odin's (the user's) memory** — the agent borrows it as if it were its own (Odin owns it; the agent uses it). When introducing or explaining the system, always attribute it to Odin.

The `<memory-context>` injected into the session is a **catalog (titles only)**. Search when you need details.

## Reading (zero-LLM)

```bash
asgard memory query "<query>" --json   # FTS + word + semantic (opt-in) + explicit-link PPR
asgard memory show <slug>               # full page text
```

## Writing — always through the approval gate

**Never edit or create** files under `~/.asgard/memory/` directly (no Write/Edit). Saving has exactly one path:

```bash
asgard memory ingest "<one self-contained fact>" --kind <note|user|decision|insight|reference|feedback>
```

1. ingest prints a plan (create / merge into an existing page) and an `approval-id`
2. Show the plan to the user and get approval (ask-before-save)
3. Only on approval, re-run with the **same body, kind, and ID**:
   `asgard memory ingest "<same body>" --kind <same kind> --yes --plan-id <approval-id>`
4. The ID is bound to the approved action, target, and revision, and is consumed exactly once. On a stale error, re-plan from the start

## Invariants

- Memory is a **hint** — it can never serve as completion evidence or verification criteria (the gate never trusts memory)
- Do not save facts discoverable from the code/repo within a minute
- Personal scope only — shared project knowledge does not go here (terminology firewall)
- Maintenance: when `asgard memory lint` reports decay, duplication, or contamination, clean up with merge/remove

## Project shared memory — Git canon + one selected backend

`<memory-recall scope="project">` comes from the current project backend approved by machine-local trust.
Never inject or merge Hindsight/Cognee/RedisVL results at the same time. For explicit search, use the MCP
`memory_recall`. Preview any significant code/doc bootstrap first:

```bash
asgard memory project-scan --all
asgard memory project-sync --all       # plan only, no external writes
asgard memory project-sync --all --yes --plan-id <preview-plan-id> # run only after approving the same snapshot
```

Saving project facts uses only the two-step flow: MCP `memory_retain` → user approval → `memory_retain_commit`.
commit writes the canonical record to the repo's `.asgard/memory/records/` first, then reflects it to the backend. Backend
restore runs only via `asgard memory project-rehydrate` preview → `--yes --plan-id`.
Always fill `record_id`, `kind`, `title`, `content`, `source`, `source_revision`, `importance`,
`confidence`, `status`. Allowed kinds: decision/policy/contract/component/incident/
experiment/migration/runbook.

Do record: long-lived team decisions, policies, public contracts, key component boundaries, incident causes/recovery,
verified experiments, migrations, runbooks. Do not record: personal preferences, transient progress/TODOs, raw logs,
trivial facts immediately visible in the code, generated artifacts, unverified speculation, secrets/credentials.
For changes, replace the existing record_id or keep history via a `supersedes` relation; never save a fact
without a source revision.
"""
