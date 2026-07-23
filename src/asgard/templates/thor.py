"""토르 전용 스킬 7종 + 코어 계약 스킬 — 백엔드(연산·API·런타임·데이터 안전·진단·무결·편대) 심화 지식.

표준 엔지니어링 관행을 우리 용어로 재서술한 자체 캐논이다 — 외부 텍스트 재배포 없음. 스킬들은
CC(.claude/skills/)와 Cursor·Codex 공용(.agents/skills/) 양 스코프에 스캐폴드되어 모드 A/B/네이티브
전부에서 로드 가능하다. 코어 스킬은 role 파일이 단일 소스(roles.role_core_skill).

리졸버는 프레이야식 순수 부분 일치가 아니라 단어 경계 + 동반어 조건을 쓴다 — 26-07-16 Codex
교차검증에서 오발 반례(RESTORE→rest, capital→api, alternative→alter, healthcare→health,
drag-and-drop→drop) 가 실증됐다. 짧은 ASCII 용어는 \\b, 중의어(index·cache·schema·drop)는
도메인 동반어가 있을 때만 발화한다."""

import re

_MJOLLNIR = """\
---
name: asgard-thor-mjollnir
description: Thor's hammer Mjölnir — deep guidance on core computation, transactions, batch, and messaging reliability. Load before business-logic, high-volume-processing, background-job, or queue-consumer work.
---

# asgard-thor-mjollnir — 🔨 Core Computation, Transactions, Batch

Thrown, it must hit (correct); it must always return (recoverable) — correctness comes before performance.

## Transaction Canon

- The boundary is the use case — one transaction = one consistency unit. Owned by the domain operation, not the entry surface (handler) or the persistence layer.
- No external I/O (HTTP calls, mail, queue publishing) inside a transaction — side effects before commit cannot be undone by rollback. If you must publish, use an outbox.
- No long transactions: never wait on user input or external responses inside a transaction.
- Consistent lock ordering: update multiple resources in a globally fixed order — crossed orders are a deadlock factory.
- Consistency beyond the atomicity boundary needs an explicit strategy: outbox (event publishing) / compensating transactions (distributed) / upsert + unique constraint (absorb duplicates).
- Check the default isolation level and raise it only where needed — a global bump is not a fix, it is a throughput incident.

## Idempotency & Retries

- Retryable paths (queue consumption, webhook receipt, batch re-runs) are idempotent by default — absorb duplicates with an idempotency key, a processed marker, or a unique constraint.
- Assume at-least-once delivery — "exactly once" is achieved in processing (idempotent consumers), not in delivery.

## Batch Durability Contract (without this it is not a batch)

- **Checkpoint**: record how far processing has gone, in a location a restart can read.
- **Re-entry point**: declare whether a re-run after interruption resumes or starts over; if it resumes, make the boundary overlap idempotent.
- **Partial failure**: declare the isolation policy for failed items (skip+record vs abort-all) along with its criteria. No structure where failures silently vanish — leave a failure table or a DLQ.
- **Progress observability**: throughput and remaining-work estimates show up in logs — a silent long-running batch is indistinguishable from a dead one.

## High-Volume Processing

- No loading everything into memory — streaming, cursors, chunking. Set chunk size by measurement.
- N+1 detection: queries inside loops become batched lookups or joins. Measure and report query counts before and after the fix.
- Throughput claims are measurement-only — never report "it got faster" without before/after numbers (items/time) (Canon 8).

## Messaging Reliability

- Publishing: atomicity between DB commit and publish goes through an outbox — publish failing after commit and rollback after publish are both incidents.
- Consumption: idempotent consumer + explicit ack. Poison messages go to a DLQ after a retry cap — infinite requeueing stalls the pipeline.
- Backpressure: if consumption < production persists, it is a design problem, not a buffer-size problem — observe queue depth and cap it.

## Concurrency

- Minimizing shared mutable state is the opening move. Suspected races get no speculative fixes — reproduction first (repeated runs, forced interleaving) (role pre-diagnosis gate).
"""

_LIGHTNING = """\
---
name: asgard-thor-lightning
description: Thor's lightning — deep guidance on APIs, realtime, server security, and external integrations. Load before endpoint-design, streaming, latency-budget, auth-boundary, or third-party-call work.
---

# asgard-thor-lightning — ⚡ API, Realtime, Security, External Integrations

When a request arrives, be lightning — fast, but by the contract.

## API Contract First

- Consistent error model: the same failure gets the same shape (code, structure). Never expose internal exception strings or stack traces in responses.
- Versioning: breaking changes (field removal, meaning changes) go in a new version — never break existing consumers without warning.
- Pagination by default: no unbounded list responses. Cursors first (offsets for shallow pages only), explicit page-size cap.
- Server-side validation is final — client-side validation is UX, not defense.

## Latency Numbers Canon

- Layered timeouts: outer longer than inner (client > gateway > service > DB/external calls). Inverted, you get ghost failures where the inner layer is alive but the outer one hangs up.
- Retries: idempotent requests only, exponential backoff + jitter, explicit cap — retrying non-idempotent requests is a duplicate-execution incident.
- Circuit breaker: open after a consecutive-failure threshold + half-open probes — never let every request hang until timeout on a dead dependency.
- Numeric budgets are mandatory on hot paths only (role performance-surface separation) — validate budgets by measurement and report.

## Realtime Ladder (stop at the lowest rung that suffices)

① Polling (interval fetch — usually enough) → ② SSE/long-polling (one-way server→client push) → ③ WebSocket (bidirectional, stateful — only when you can afford the reconnection, fan-out, and backpressure costs). No climbing rungs without evidence. If WebSocket, design the reconnection strategy and undelivered-message handling together.

## Caching

- If you cannot write the invalidation strategy first, do not introduce a cache — "just TTL for now" is not a strategy, it is a deferred bug.
- Reflect every parameter and auth scope in the cache key — serving someone else's data is the worst cache bug.
- Stampede: block simultaneous-expiry recomputation with locking or early refresh.

## Server Security Boundary

- State authentication (who are you) and authorization (what may you do) separately — check object ownership on every resource access (IDOR defense).
- No hardcoded secrets — environment/secret store. Never log tokens or personal data.
- A server fetching a user-supplied URL is SSRF — internal-network blocking and allowlist validation are mandatory. Session-cookie auth needs CSRF tokens/SameSite.

## External Integrations (without timeouts, partial-failure handling, and compensation it is not an external call)

- Explicit timeout on every external call — library defaults of infinite wait are a common trap.
- Declare the on-failure strategy: retry (idempotent only)? fallback? propagate the failure? — "assume it will work" is not a strategy.
- External responses are unvalidated input — validate against a schema before use (same principle as Canon 5).

> Source: layered timeouts, circuit breakers, top OWASP categories — standard practice restated in our own words.
"""

_MEGINGJORD = """\
---
name: asgard-thor-megingjord
description: Thor's belt of strength Megingjörð — deep guidance on runtime infrastructure, scaling, and observability. Load before work on post-deploy behavior (probes, resources, autoscaling, logs, metrics). Image builds and CI belong to eitri.
---

# asgard-thor-megingjord — 🜃 Runtime Infrastructure, Scaling, Observability

The belt doubles your strength — the system holds even when traffic surges. Scope is the runtime behavior and policy values of what is deployed. Build graphs, CI, and packaging belong to asgard-eitri — mixed files (image tags in a k8s manifest, HEALTHCHECK in a Dockerfile) are edited by the owner of the primary surface, but runtime values are written against this canon.

## Stateless First (the precondition for scale-out)

- Process-local sessions, uploaded files, or consistency-bearing in-memory caches make horizontal scaling impossible — externalization (store, object storage) comes before scaling.
- Litmus: does it survive running on 2 instances?

## Health Checks

- Distinguish liveness (alive? — restart on failure) ≠ readiness (can it accept? — remove from traffic on failure).
- No dependency cascades: propagating a DB outage into liveness failure triggers a fleet-wide restart storm — dependency state goes to readiness at most.
- Keep checks light — the health check itself must not become a load source.

## graceful shutdown

- Receive termination signal → stop accepting new work (drop readiness) → wait for in-flight completion (bounded) → release resources → exit. Cutting in-flight work is data loss for clients without retries.
- Set the shutdown wait cap shorter than the infrastructure's forced-kill grace period.

## Scaling

- Horizontal first — vertical (a bigger machine) requires measured evidence (a single-process CPU/memory bottleneck).
- Autoscale on real bottleneck signals (queue depth, p99, concurrent work count) — CPU alone misses I/O-bound workloads.
- Scale policies state upper bound, lower bound, and cooldown — uncapped autoscaling is a cost incident and a cascading-failure amplifier.

## Config Externalization

- No per-environment branches in code — inject configuration values. Code is the same artifact in every environment.
- Defaults lean safe (local/dev) — production values by explicit injection only.

## Observability Minimum Contract

- Structured logs (searchable fields) + request correlation-ID propagation.
- Four core metrics: traffic, error rate, latency (p50/p99), saturation. SLOs on hot paths only (role performance-surface separation).
- Litmus: "If this code dies in the middle of the night, can logs alone narrow the cause candidates?"

> Source: probe separation, graceful shutdown, core metrics — standard practice restated in our own words.
"""

_JARNGREIPR = """\
---
name: asgard-thor-jarngreipr
description: Thor's iron gauntlets Járngreipr — data and schema safety overlay. For tasks involving schema changes, migrations, indexes, or irreversible data operations, load this layered on top of the other skills.
---

# asgard-thor-jarngreipr — 🧤 Data & Schema Safety (overlay)

You do not grip a red-hot Mjölnir bare-handed. This skill is not standalone but an **overlay** — when data risk is involved, layer it on top of Mjölnir and Lightning. It covers not just RDBs but every stateful store: search indexes, file data, cache stores.

## Safety Grade Matrix (environment × side effect — the data-specific form of the role approval model)

| Grade | Target | Action |
|---|---|---|
| 🟢 | All reads / all local·ephemeral environments | Execute immediately |
| 🟡 | Data changes (DML) in shared environments | Report impact scope, estimated row count, and the undo method as deliverables — execute only when the assignment says so |
| 🔴 | Schema changes, migrations | expand-contract + rollback plan required; include the plan in the report |
| ⚫ | Direct execution in production / destructive ops without backup (drop, truncate, irreversible updates) | No direct execution — return a plan; approval belongs to Odin |

## Migrations (expand-contract)

- Forward and backward compatibility: survive the deploy window where old and new code coexist — ① expand (new columns/tables, nullable/defaults) ② migrate (dual writes or backfill) ③ contract (remove the old path), as separate steps and separate deploys.
- Destructive changes (column removal, type narrowing, adding NOT NULL) happen only in the contract step — after confirming zero usages.
- Backfills follow the batch durability contract (Mjölnir) — no one-shot mass UPDATE (locks, replication lag); chunk + throttle.
- A migration without a rollback plan is unfinished — "fix by rolling forward" counts as a plan only if stated explicitly.

## Indexes

- Evidence is a measured query plan — no "it might be slow" indexes. Attach before/after plans and execution times to the report.
- State the write cost: indexes are not free — describe the trade-off for write-heavy tables.
- Create indexes on large tables online (where supported) — no execution without a lock-duration estimate.

## Consistency & Irreversibility

- Litmus before any irreversible operation: "If I regret this immediately, is there a way back?" — if not, it is grade ⚫.
- Unique and foreign-key constraints are the last line of defense, not a substitute for application validation — only constraints close the race window.
- Derived data (search indexes, caches) may be destroyed only when the rebuild procedure has been confirmed.

> Source: expand-contract — standard practice restated in our own words.
"""

_GRIDARVOL = """\
---
name: asgard-thor-gridarvol
description: Thor's staff Gríðarvölr — backend diagnosis overlay. For root-causing server defects, API misbehavior, and hard-to-reproduce failures, load this layered on top of the common debugging skill.
---

# asgard-thor-gridarvol — 🦯 Backend Diagnosis (overlay)

Crossing rapids, you probe the riverbed with a staff — step only where it touches, never on guesses. The common discipline (reproduce → observe → one hypothesis at a time → minimal fix) belongs to `asgard-worker-debugging` — this skill layers the diagnosis specific to servers, APIs, and distributed boundaries on top of it.

## Reproduction Loop Ladder (build a red→green command before fixing)

Before any theory of cause, secure one command that is red at the symptom and turns green after the fix. From the lowest rung:
① failing test → ② request-reproduction script (record status code, headers, body) → ③ capture replay (failing request body, queue message, webhook payload as fixtures) → ④ bisect judge (git bisect run — keep the judge command narrow: unrelated breakage misleads the search) → ⑤ report reproduction failure (last resort — with the angles attempted; role pre-diagnosis gate).
- Tighten the loop: faster runs, sharper assertions, pinned nondeterminism (time, seeds, network).
- For intermittent failures, raise the reproduction rate first — 50% is diagnosable, 1% effectively is not.

## Layer Isolation (slice the request path into layers)

First isolate which layer the symptom lives in, then dig only there: connection (DNS, routing) → timeout (distinguish connect latency vs response latency — measure each stage) → TLS → authn/authz (token expiry, scopes, environment mismatch) → request format (Content-Type, serialization mismatch) → response parsing (check content-type before deserializing) → semantics (contract violation).
- Status-code playbook: 401=expiry/scheme, 403=scope/ownership, 404=path/beware resource enumeration, 409=contention/idempotency key, 422=schema drift, 429=Retry-After+backoff, 5xx=grab the correlation ID then trace upstream.
- Some protocols carry errors inside a 200 body (GraphQL and kin) — never trust the status code alone.

## Multi-Component Instrumentation

- With 2+ services involved, instrument every boundary before hypothesizing: record in/out values and config propagation at each boundary, measure "at which boundary does the value go wrong", and trace the wrong value upstream to fix it at the source — no patching at the symptom site.
- Temporary logs use a unique prefix (`[DBG-xxxx]`) — cleanup ends with a single search.

## Premise Verification (before calling it a bug)

- Do not mistake intended design for a defect — check the original intent in history (`git log -p -S "<symbol>"`). Sometimes "it is isolated" is itself the design.
- If you cannot pinpoint where the defect manifests, your premise is unverified: you must be able to name the exact line where the bug manifests and whether the fix changes that line's behavior.
- Sometimes absence bears load — restoring "seemingly missing" code can break existing behavior: find the consumers of the absence first.

## Structural Signal (rule of three)

- If 3 substantially different approaches fail, it is not a local defect but a structural problem — stop stacking risk and return with the attempts and elimination evidence.
- The same bug recurring in new forms, or a simple change touching many files, is a structural signal — put a minimal structural fix proposal and a blast-radius estimate in the report.

> Source: layer isolation, bisect judges, premise verification — standard practice restated in our own words.
"""

_TANNGRISNIR = """\
---
name: asgard-thor-tanngrisnir
description: Thor's goat Tanngrisnir — output integrity sweep and completion-evidence contract. Load when finishing backend changes (pre-return self-check, report writing) and before error-handling, fallback, or refactoring work.
---

# asgard-thor-tanngrisnir — 🐐 Output Integrity & Completion Evidence

The goat revives only if its bones are intact — output qualifies for return only with an integrity sweep and evidence.

## Masking-Fallback Ban (the #1 defect in error handling)

Classify all fallback/bypass code into two kinds:
- **Masking fallback (banned)** — hides a real defect: swallowed errors, silent defaults, bypassed validation, untested alternate paths, downgraded diagnostics. Treat on sight as a defect — a repair target, not completion.
- **Justified fallback (allowed)** — confined to a known external or version boundary, both paths tested, failure evidence preserved, rationale left in the code.
- Never render missing data as OK or 0 — "insufficient data" is itself what gets displayed.

## Slop Sweep (pre-return self-check)

- Remove debug residue, dead code, temporary logs (one bulk search for the diagnostic prefix — the counterpart of Gríðarvölr's instrumentation discipline).
- No unnecessary abstraction: preemptively extracted single-use helpers, pass-through wrappers, speculative indirection — each must justify the diff it adds.
- Remove over-defensiveness foreign to that area's conventions (re-validating trusted paths, blanket try/catch) — defensive code is part of the assignment scope too (Canon 7).
- Boundary violations (wrong-layer imports, hidden coupling) are sweep targets — if the fix is out of scope, report the finding at minimum.

## Completion Evidence Contract (what qualifies a report)

- Assert on artifacts: not response text or one hopeful log line but the actual effect — confirm the written row, the created file, the endpoint's real response.
- Test evidence in a failure-preserving form: `set -o pipefail && <test command> 2>&1 | tail -n 100` — the left-side failure survives even when the filter succeeds.
- Running ≠ evaluating: that a command ran and that the criteria were met are different things — state which evidence maps to each criterion, and leave uncovered criteria as unevaluated. Never smear them into "done" (Canon 10).
- Kind check: is the artifact the requested kind (working code, not a document)? Did verification prove the requested behavior (not merely that a file exists)?
- A bug caught live pairs a fix with a regression case — a fix without a case is a scheduled recurrence (authoring discipline in `asgard-worker-testing`).

> Source: pipefail evidence format, two-way fallback classification — standard practice restated in our own words.
"""

_EINHERJAR = """\
---
name: asgard-thor-einherjar
description: Thor's einherjar squad — team-scale backend work orchestration. Load before tasks needing a large multi-surface change (2+ separate surfaces / 3+ files) or an N-version tournament for a hard problem. Read by the squad lead (asgard-thor-lead) and the superior (Worker) running the squad.
---

# asgard-thor-einherjar — 🛡 Einherjar Squad (Team Backend Work)

A Thor who does everything alone skips steps — measured: instruction-following drops monotonically as turns accumulate (Multi-IF: turn 1 at 0.877 → turn 3 at 0.707), long multi-turn context degrades by an average of −39% (Lost in Multi-Turn), and self-produced output gets graded generously by its own producer (self-preference bias). The split/verify procedure is enforced not by instructions but by **structure — organizing N subordinates**.

## Formation Verdict (delegation threshold — only when it justifies the token tax)

| Signal | Formation |
|---|---|
| Single file, atomic change | No squad — solo Thor. This is the correct call, not under-formation (multi-agent carries a ~15x token tax) |
| 2+ separable surfaces / 3+ files / roughly 200+ lines | Split squad, 2–4 members |
| Unfinished after 2 substantially different inline approaches / a hard problem where approach itself is contested | Tournament squad, 2–3 members |

## Two Squad Types

- **Split squad** — divides distinct units among members. A split is verified on three points: the union of children equals the parent's scope (nothing missing), the children are non-overlapping (no file overlap), and each is closer to atomic than the parent. A failed verification gets one repair pass; a second failure escalates — never accept it silently.
  - **Contracts first**: if one unit produces a contract (types, signatures, schema, API) that another consumes, they cannot run in parallel — finalize the contract output first and send the consuming unit to the next wave.
  - If two subordinates might touch the same file, the lead handles that file directly.
- **Tournament squad** — each subordinate tries the same hard problem via a different approach axis, in an isolated worktree, in parallel; only the one winner that passes verification (red→green command) is applied to the mainline, and the losers are discarded. N copies of the same brief cluster locally — force axis distribution instead.

## Subordinate Brief Contract (target · change · acceptance — an ambiguous brief is the #1 cause of duplication and gaps)

① **Target** — the exact files/symbols + explicit non-goals (what not to do, the boundary with other subordinates) ② **Change** — described step by step ③ **Acceptance** — an observable result + a unit-scoped verification command. Never assign a global build or full test suite to a subordinate — the global gate is the lead's job, run once after integration ④ **Shared contract duplication** — if units share an interface, attach the exact types/signatures to every brief that needs them ⑤ **Attach the domain skill verbatim** — for data-risk units include Jarngreipr, for diagnosis units include Gríðarvölr verbatim (or its load path). A lead's paraphrase is lossy compression.
- Subordinates always get a **fresh context** — do not hand down the lead's history or other units' details. A failed unit gets a fresh-context regeneration, not a same-context repair.
- Cap of 3–5 files per subordinate — never assign a glob or "update everything" scope.

## Handoff & Integration (deliverable is a diff, verdict is separate)

- Subordinate return format: list of changed files + decision summary + verification evidence (or a verification recommendation) + blockers. Never return the full work log.
- The lead keeps two ledgers separate: a **plan ledger** (facts, decisions, formation) and a **progress ledger** (per-unit status). More than 2 rounds without progress means **rewriting the plan itself**, not retrying the subordinate.
- **Integration and the global verification are the lead's job** — after all units converge, run lint/tests once against the union of changed files. A subordinate's summary is only a summary — run the verification commands yourself and record cmd and exit code.
- Verdict separation — never render the final verdict on output you yourself directed: run counterexample search on a read-only surface (loki). Review order is spec conformance → quality — reversing the order lets a well-written wrong answer pass.

## Invariants (what the squad must never break)

- **Depth 1** — subordinate Thors do not re-delegate. No squad of squads.
- **Verification independence** — the Verifier never invokes a squad. Verdict subordinates run on a read-only surface (loki, a separate session).
- Deliverables merge into the canonical work tree and pass the upstream gate (physical diff check) as-is — no bypass path.
- No declaring completion (Canon 10) — the lead's output is the formation record (who did what) + per-unit evidence + integration verification log + residual risk. The verdict belongs upstream.

**Solo fallback** (when a squad is not available): run the same procedure as a checklist gate — unit split (non-overlap verification), contracts-first, per-unit evidence, and final union verification, in the same order, leaving each step's output on file. Without structure, the procedure evaporates (per the measurements above).

> Source (figures restated): Anthropic multi-agent research system (lead-subordinate, ~15x token tax, brief format), Multi-IF (2410.15553), Lost in Multi-Turn (2505.06120), Magentic-One (2411.04468 — dual ledgers, stall replanning), MetaGPT (2308.00352 — standardized deliverable handoff), Cognition don't-build-multi-agents (component ownership boundaries), sample diversity (2502.11027 — axis distribution).
"""

THOR_SKILLS: list[tuple[str, str]] = [
    ("asgard-thor-mjollnir", _MJOLLNIR),
    ("asgard-thor-lightning", _LIGHTNING),
    ("asgard-thor-megingjord", _MEGINGJORD),
    ("asgard-thor-jarngreipr", _JARNGREIPR),
    ("asgard-thor-gridarvol", _GRIDARVOL),
    ("asgard-thor-tanngrisnir", _TANNGRISNIR),
    ("asgard-thor-einherjar", _EINHERJAR),
]

# 네이티브 디스패치 task → 전용 스킬 매칭 (파일 스킬 로더가 없는 asgard start 세션용 통로 —
# 모드 A/B 는 파일 스킬이 담당). 부분 일치 키워드 + 단어 경계 정규식 + 동반어 조건 3층.
_SUBSTR: dict[str, tuple[str, ...]] = {
    "asgard-thor-mjollnir": (
        "배치",
        "트랜잭션",
        "transaction",
        "집계",
        "aggregat",
        "대용량",
        "동시성",
        "concurren",
        "멱등",
        "idempoten",
        "메시징",
        "outbox",
        "dlq",
        "backpressure",
        "kafka",
        "rabbitmq",
        "비즈니스 로직",
        "business logic",
        "데드락",
        "deadlock",
        "레이스 컨디션",
        "race condition",
        "백그라운드 잡",
        "background job",
        "백필",
        "backfill",
    ),
    "asgard-thor-lightning": (
        "endpoint",
        "엔드포인트",
        "graphql",
        "grpc",
        "websocket",
        "웹소켓",
        "실시간",
        "realtime",
        "real-time",
        "스트리밍",
        "streaming",
        "지연",
        "latency",
        "rate limit",
        "레이트리밋",
        "폴링",
        "polling",
        "restful",
        "인증",
        "인가",
        "authent",
        "authoriz",
        "oauth",
        "웹훅",
        "webhook",
        "타임아웃",
        "timeout",
        "서킷",
        "circuit breaker",
        "외부 연동",
        "서드파티",
        "third-party",
    ),
    "asgard-thor-megingjord": (
        "스케일링",
        "오토스케일",
        "autoscal",
        "스케일 아웃",
        "scale-out",
        "로드밸런",
        "load balanc",
        "k8s",
        "kubernetes",
        "쿠버네티스",
        "오케스트레이션",
        "orchestrat",
        "무중단",
        "healthcheck",
        "health check",
        "헬스체크",
        "liveness",
        "readiness",
        "graceful",
        "드레이닝",
        "관측성",
        "observab",
        "메트릭",
        "metric",
        "트레이싱",
        "tracing",
        "무상태",
        "stateless",
    ),
    "asgard-thor-jarngreipr": (
        "마이그레이션",
        "migrat",
        "truncate",
        "정합성",
        "expand-contract",
        "롤백",
        "rollback",
        "백업",
        # ddl/dml/스키마/인덱스/drop 은 아래 정규식·동반어 조건이 담당 (오발 방지)
    ),
    # 진단 오버레이 — 토르 디스패치 표면 한정이라 도메인 동반어 불요 (백엔드 문맥이 전제)
    "asgard-thor-gridarvol": (
        "디버깅",
        "디버그",
        "버그",
        "크래시",
        "장애",
        "인시던트",
        "incident",
        "원인 규명",
        "원인 분석",
        "root cause",
        "재현",
        "reproduc",
        "오동작",
        "간헐",
        "traceback",
        "stack trace",
        "스택트레이스",
    ),
    "asgard-thor-tanngrisnir": (
        "폴백",
        "fallback",
        "에러 처리",
        "error handling",
        "예외 처리",
        "리팩터",
        "refactor",
        "죽은 코드",
        "dead code",
        "코드 품질",
        "code quality",
        "슬롭",
        "정리 스윕",
    ),
    # 편대 표면 — thor-lead 디스패치와 Worker 대장 역할 양쪽에서 매칭
    "asgard-thor-einherjar": (
        "편대",
        "에인헤랴르",
        "einherjar",
        "토너먼트",
        "tournament",
    ),
}
# 단어 경계 필수 — 부분 일치면 capital→api, batches 는 잡되 debatch 는 제외하는 식의 통제 불가.
_WORD_RE: dict[str, tuple[str, ...]] = {
    "asgard-thor-mjollnir": (r"\bbatch", r"\bqueue", r"\brace\b"),
    "asgard-thor-lightning": (r"\bapi\b", r"\bsse\b", r"\bauth\b", r"\bp99\b"),
    "asgard-thor-megingjord": (r"\bscal(e|es|ed|ing)\b", r"\bhpa\b", r"\bslo\b", r"\bdrain"),
    "asgard-thor-jarngreipr": (r"\bddl\b", r"\bdml\b"),
    "asgard-thor-gridarvol": (r"\bdebug", r"\bbugs?\b", r"\bcrash", r"\bbisect\b", r"\bflak(y|e)\b"),
    "asgard-thor-tanngrisnir": (r"\bcleanup\b", r"\bslop\b"),
}


def _any(t: str, *patterns: str) -> bool:
    return any(re.search(p, t) for p in patterns)


_DB_CONTEXT = (
    r"\bsql\b|쿼리|query|테이블|\btable\b|\bdb\b|database|스키마|\bschema\b|postgres|mysql|mariadb|sqlite|mssql|oracle"
)


def _cache_hit(t: str) -> bool:
    """캐시 → lightning — 서버 응답 캐시 문맥만 (CI 캐시·docker layer·브라우저 캐시 제외)."""
    if not _any(t, r"캐시|\bcach"):
        return False
    if _any(t, r"\bci\b", r"docker", r"\blayer\b", r"브라우저", r"browser", r"빌드 캐시", r"build cache"):
        return False
    return _any(
        t,
        r"server",
        r"서버",
        r"응답",
        r"response",
        r"redis",
        r"memcach",
        r"\bcdn\b",
        r"\bapi\b",
        r"엔드포인트",
        r"endpoint",
        r"무효화",
        r"invalidat",
    )


def _index_hit(t: str) -> bool:
    """인덱스 → jarngreipr — DB 문맥 동반 시만 (index.ts·목차 오발 방지)."""
    return _any(t, r"인덱스", r"\bindex") and _any(t, _DB_CONTEXT)


def _schema_hit(t: str) -> bool:
    """스키마 → jarngreipr — 단 GraphQL 스키마는 API 계약(lightning 트리거가 별도 담당)."""
    return _any(t, r"스키마", r"\bschema\b") and not _any(t, r"graphql")


def _drop_hit(t: str) -> bool:
    """drop/alter → jarngreipr — DB 문맥 동반 시만 (drag-and-drop·alternative 오발 방지)."""
    return _any(t, r"\bdrop\b", r"\balter\b") and _any(t, _DB_CONTEXT, r"컬럼", r"\bcolumn\b")


_COMPANION: dict[str, tuple] = {
    "asgard-thor-lightning": (_cache_hit,),
    "asgard-thor-jarngreipr": (_index_hit, _schema_hit, _drop_hit),
}


def resolve_thor_skills(task: str) -> list[tuple[str, str]]:
    """디스패치 task → 매칭된 전용 스킬 (이름, frontmatter 제거 본문) — 0-LLM 휴리스틱.

    네이티브 토르 자식 세션의 system 에 직접 주입할 본문을 고른다 (파일 스킬 로더 부재 보완).
    무매칭 = 빈 리스트 (fail-open — role 본문 기준으로 진행, role 이 이미 그 폴백을 선언한다).
    복수 매칭은 전부 주입 — role 합성 규칙(야른그레이프르 = 오버레이)이 그것을 전제한다."""
    t = task.lower()

    def hit(name: str) -> bool:
        return (
            any(k in t for k in _SUBSTR.get(name, ()))
            or _any(t, *_WORD_RE.get(name, ()))
            or any(cond(t) for cond in _COMPANION.get(name, ()))
        )

    return [(name, body.split("---", 2)[2].lstrip()) for name, body in THOR_SKILLS if hit(name)]


def thor_core_skill() -> str:
    """모드 A용 토르 코어 계약 스킬 — role 파일 단일 소스 (roles.role_core_skill 파생)."""
    from .roles import role_core_skill

    return role_core_skill(
        "asgard-thor.md",
        "Thor core contract — inline execution standard for backend work (service code, data, API, runtime "
        "policy). Loaded by the Worker phase on backend subtasks in tools without subagents.",
    )


def eitri_core_skill() -> str:
    """모드 A용 에이트리 코어 계약 스킬 — role 파일 단일 소스 (roles.role_core_skill 파생)."""
    from .roles import role_core_skill

    return role_core_skill(
        "asgard-eitri.md",
        "Eitri core contract — inline execution standard for build, CI, packaging, and release work. Loaded "
        "by the Worker phase on build/CI subtasks in tools without subagents.",
    )
