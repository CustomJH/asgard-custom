# i2-audit-S.md — Iteration 2 (persona S walk-through)

**Date:** 2026-04-27
**Persona:** S — Senior dev (10+yr), side-project tinkering on a 25-component prototype with husky/lint-staged. Reads patches line-by-line. Will not accept platitudes.
**Method:** Walked the 7-step scenario against actual v4 source (master.md / harness/SKILL.md / code-introspect.ts / memory.ts / critic.md / post-edit-watch.cjs / session-end-foldin.cjs). No mocks, just close reading + flow simulation.

---

## Step 1 — INTAKE on existing repo (25 components + husky)

### What v4 does
`vanadis-master.md` §1 INTAKE branch: "existing code → CONTEXT_DETECT brief, then SLOT_GATE." Reads `.vanadis/context.json`. Persona detected via heuristic in signal-classifier (i1 fixed it).

### Verdict for S
**Acceptable, with caveats.**

- S has husky + lint-staged already → context-detect *should* notice and adjust tone (no need to lecture about quality bar). I see **no signal** in master.md or context.json schema that "existing tooling" is a slot — only `is_frontend` / token inventory. **MINOR:** persona-S should get an early acknowledgment ("husky 보이네요, 그쪽 톤 맞춰서 빠르게 갈게요") instead of generic onboarding. Currently the master will treat S the same as F if intake heuristic mis-classifies.
- Persona detection at INTAKE time relies entirely on the *first user message word/char count*. S writes long opinionated messages → likely classified `S` correctly. But if S opens with "audit this" (3 words), classifier flips to `V`. **MAJOR design gap:** persona is sticky-on-first-message, not re-evaluated at turn 3 once more text accumulates. master.md §0 doesn't mention re-classification; classifier only runs per-turn for *response style mirroring*, not for budget cap re-pegging.

---

## Step 2 — code-introspect on 25-component repo

### What it actually finds
Reading `code-introspect.ts` line-by-line:

- `HEX_RE = /#[0-9a-f]{3,8}\b/gi` — collects every hex literal in any file scanned, frequency-weighted. CSS-var hexes weighted ×3. **OK.**
- `PX_RE = /\b(\d+(?:\.\d+)?)px\b/g` — collects **every px value**, no filter. Then `topN(spacing, 10)`.
- `RADIUS_KW = /\brounded(?:-(?:sm|md|...))?\b/gi` — Tailwind class scan only.

### CRITICAL bug — "1px borders detected as spacing tokens"
Confirmed. `harvestFromText` adds **every** `Npx` match to `acc.spacing` with no semantic filter. In a 25-component repo with `border` / `border-t` / `outline-1` / `ring-1` / shadow offsets, **`1px` will dominate the frequency table**. Scenario walk:

- 25 components × ~5 borders each = ~125 hits of `1px` → dominates topN.
- Real spacing tokens (`p-4` Tailwind = 16px, `gap-2` = 8px) are **Tailwind classes, not raw px**, so they won't even land in the `PX_RE` bucket. The regex only catches raw `Npx` strings (CSS files, inline styles, arbitrary values like `p-[12px]`).
- Net result: `summarizeInventory` will tell the master `spacing scale: 1px/2px/4px/16px/...` — **the 1px and 2px are border widths, not spacing**.

**Worse:** master then shows S "spacing scale starts at 1px" in its acknowledgment prose. S will close the laptop. This is exactly the "noise output" failure mode S anticipated.

**Required fix:** distinguish *border-width-context* vs *spacing-context* via PostCSS AST walk on CSS, or AST scan on Tailwind classes (`p-N`, `gap-N`, `m-N`, `space-x-N`) for components — **not** raw `Npx` regex on tsx text. Cheap heuristic interim: ignore `1px` and `2px` when their occurrence cluster correlates with the words `border`/`outline`/`ring`/`divide` within ±15 chars.

### CRITICAL bug — radius/spacing inconsistency detection: missing
The interface `TokenInventory` has no `inconsistencies` field. `summarizeInventory` reports the *dominant* values but never flags "you have 6 different radius keywords (rounded-sm/md/lg/xl/2xl/full) — 6 is high; consider trimming to 3." **For S, this is the entire reason to run code-introspect.** A 10yr dev doesn't need to be told "you have these colors"; they need to be told **"you have 11 unique blues that don't form a scale."** Currently no such logic exists.

**Required:**
- Detect 8pt grid violation: spacing values not divisible by 4 or 8.
- Detect color drift: cluster colors by ΔE; flag when count > 5 in same hue.
- Flag radius scale length > 4.

None of this is in `code-introspect.ts`. The file is purely a frequency census, not an *inconsistency report*.

### MINOR
- `harvestFromTailwindConfig` regex-extracts hexes from the config source text. If the config does `colors: { ...stoneShades }` referencing an imported palette, the hex extraction silently misses it. No warning emitted. S will notice the mismatch immediately.
- `cssFiles` capped at 30, `componentFiles` at 60. With 25 components S is fine, but cap is silent if components > 60 — only a `warnings[]` entry that nothing surfaces to the user.

---

## Step 3 — Master proposes plan (PROPOSE_PLAN → Vanadis-PLAN.md)

### What I can read
master.md §6 says: build `PlanInputs` → `node -e "..."` or write inline → emit Vanadis-PLAN.md. The schema is in `src/core/plan-emitter.ts` (not read here). master.md §0.persona promises "spec-grade output."

### Verdict
**Cannot fully verify without reading plan-emitter.ts**, but signals from master.md:

- §12 "Output discipline" forbids marketing prose: "tight, direct sentences. ... no marketing fluff." Good.
- §0 promises "cite a token for every visual claim; cite a reference URL for every persona claim." If plan-emitter actually enforces this, S is happy.
- **Risk (MAJOR):** plan-emitter is not bound by the master's persona rules — it's a deterministic emitter. If the template has lines like "이 디자인은 사용자에게 따뜻한 경험을 제공합니다" baked in, S will see boilerplate. Need to read plan-emitter.ts to confirm; flagging as **unknown / probably suspect** based on the volume of Korean prose templates I see referenced elsewhere.
- **Risk (MAJOR):** §11–13 (success metrics / personas / principles) — master rule 999 says "Never fabricate §11–13 facts. Use `[FILL IN]` placeholder." Good rule on paper. But Vanadis-PLAN.md is generated *before* DESIGN.md.patch — does plan-emitter respect [FILL IN] on these slots? Unclear from master.md alone.

---

## Step 4 — Push back on §11–13 placeholder strategy

### Scenario
S says: "I don't want `[FILL IN]` in §13 personas — give me a draft I can edit, even if speculative. The placeholder makes the doc look unfinished and I'll forget."

### What master should do
master.md rule 999: "Never fabricate §11–13 facts. Use `[FILL IN]` placeholder."

This is a **hard rule with no escape hatch**. master will refuse, citing the rule. **For persona S this is correct behavior** — S explicitly said "spec-grade, will read line by line" → fabricated personas would be noise. But:

- master.md gives no scripted response for this pushback. Rule 8 (Escalation hierarchy) covers "user keeps correcting" but not "user explicitly asks to violate hard rule."
- Likely outcome: master either (a) violates rule 999 to please S, (b) refuses with platitude ("죄송하지만 정확성을 위해..."). Neither is great.
- **Required:** rule 999 should be paired with a *bounded fabrication* mode: "draft persona with `[SPECULATIVE]` tag, user must approve before §13 is final." This gives S a starting draft without polluting the doc with hard claims.

**Verdict: MAJOR gap.** Hard rule without negotiation protocol.

---

## Step 5 — critic spawn between iterations

### Reading vanadis-critic.md
- Tools: `Read, Write, Glob, Grep` only — **no Edit/Bash**. The constraint is intentional and correct. ✅
- Output: `critique.md` with §1 root cause / §2 decision tree / §3 mandatory re-do scope / §4 vanadis remember / §5 fragility / §6 severity. ✅
- "Diagnostic frame ... Trace back to a specific decision the master made. Do NOT stop at the surface." ✅
- Examples list correct vs wrong root causes — concrete and grounded. ✅

### Will it actually do root-cause?
The structure forces it to. The §1 template literally has fields `Symptom phase` / `Root cause phase` / `Evidence (verbatim)`. Critic has to fill them or produce malformed markdown. **Strong scaffold.**

### Concerns
- **MINOR:** §2 decision-tree audit table has no minimum-row requirement. A lazy critic could write 1 row and call it done. Should require ≥3 rows (or N = number of phases that ran).
- **MAJOR:** "Always quote evidence verbatim from artifacts. No paraphrase." — critic only has Read/Glob/Grep. If artifact is a binary (e.g., `eval/screenshots/*.png`), critic cannot quote it. The rule will silently break for visual regressions. Need an explicit fallback ("for image evidence, cite filename + reason for inferred issue").
- **MINOR:** No anti-platitude clause. Master.md §12 forbids marketing fluff; critic.md should mirror with "no 'overall the design has potential' style hedging."
- **CRITICAL risk:** "if you could patch surface symptoms, the master would never have to re-think its decisions" — this is great philosophy, but the iteration loop in master.md §8 says critic-spawn → "re-enter at lowest broken phase (cap 3 iterations total)." If critic identifies Phase 3 (IA) as root cause, master re-runs Phase 3 *and all downstream phases*. Three iterations × 6 downstream phases = 18 phase-re-runs in worst case. No de-dup or memoization mentioned. S will run out of patience and budget at iteration 2.

---

## Step 6 — Week-long use, preferences accumulate, session-end-foldin

### Reading session-end-foldin.cjs
Algorithm (verbatim from hook):

```
score = entries.length × importanceAvg × recency × 10
recency = exp(-daysSince/7)
threshold default = 60
recurrence = entries.length >= 3
window = 7 days
```

### CRITICAL bug — score formula is wrong
Walk the math:

- 3 entries, importance=3 (default), all today → score = 3 × 3 × 1.0 × 10 = **90 → fires**.
- 3 entries, importance=3, 4 days ago → recency = exp(-0.57) ≈ 0.566 → score = 3 × 3 × 0.566 × 10 = **51 → does NOT fire**.
- 5 entries, importance=2, today → 5 × 2 × 1 × 10 = **100 → fires**.
- 10 entries, importance=1 (opinions), today → 10 × 1 × 1 × 10 = **100 → fires**.

**Problem 1:** importance=1 ("opinion") accumulating freely promotes to a §-level rule. S casually saying "I prefer rounded over square" 10 times in a week → fold-in proposal as if it were a hard principle. **This is the "false promotion" failure mode S explicitly flagged.**

**Problem 2:** the `entries.length` is *raw count*, no de-duplication of near-identical notes. If S says "shadows feel heavy" 5 times across 5 sessions on the same component, fold-in counts 5 — but it's one signal repeated. Algorithm should be `unique_clusters * importanceAvg * recency` where clusters are computed via note-similarity (even cheap n-gram). Currently `synthesizeRule` just joins last 3 notes verbatim — which means promoted rule is "- shadows feel heavy / - shadows feel heavy / - shadows feel heavy". Useless.

**Problem 3:** the `byScope` grouping uses *exact scope string*. If S logs preferences with scope `components.button` once and `component.button` once and `voice.button` once, no group reaches 3. Conversely a single bug in agent code that always writes scope `unknown` will cluster everything into one super-group.

**Problem 4:** windowMs filter discards anything older than 7 days, but `entries.length >= 3` *recurrence* threshold is only checked **inside the window**. So a slow-burn signal (1/week × 6 weeks) will never fold in. S working on a side project = exactly this profile.

### Will it fire even once for S in a week?
- Day 1-2: S logs 2-3 prefs, mostly importance=2-3 → window has 2-3 → no fold-in.
- Day 3-4: 1-2 more → window now 4-5 entries, but spread across scopes → per-scope likely <3 → no fold-in.
- Day 5-7: realistically S writes 1 pref per session, 1 session per day. If 3 land in `voice` scope by day 7 with importance=3, today → score = 3×3×1×10 = 90 → **fires once**.

So yes, **it can fire once** — but only if S's prefs happen to cluster on one scope, and only if they're recent. The threshold is set assuming "8h work day, multiple corrections per scope." For a **side-project user** (S's profile), the threshold is too high and the window too narrow. **MAJOR misalignment with stated persona.**

### Fold-in algorithm in memory.ts
`computeFoldInProposals` mirrors the hook (good — single source of truth conceptually, though the hook re-implements it inline rather than importing — **CRITICAL drift risk:** any fix to one needs duplicate fix to the other). I see they're already drifted in subtle ways — hook hardcodes default config inline (`fold_in_score_threshold: 60, recurrence_window_days: 7`) and uses `now = Date.now()` while ts.lib uses `now = new Date()` parameter. Functionally equivalent here, but the duplication will rot.

`mapScopeToSection`: heuristic prefix matching. `scope = "color.dark-mode"` → matches `startsWith('color')` → §2. `scope = "voice.error.spec"` → matches `startsWith('voice')` → §10. OK. But `scope = "spacing.button.cta"` → §5 Layout? Should be §4 Component Stylings. The mapping is too coarse. **MINOR for S** (S can fix the section in plan review).

### Hook fires?
- Hook is `Stop` event. Will it actually run? Depends on settings.json registration — not visible from this audit. **Cannot verify without `.claude/settings.json`.** Assuming registered: yes the file logic itself is sound (parses pref blocks, writes timeline.md, exits cleanly).
- One real bug: line 93 `process.stdout.write(JSON.stringify({}) || '')` — `JSON.stringify({})` returns `"{}"` (truthy string), so the `|| ''` is dead code. Cosmetic. **MINOR.**

---

## Step 7 — post-edit-watch hook on Tailwind file

### Scenario
S edits `tailwind.config.ts` and adds a new hex `#3a86ff` in `theme.extend.colors.brand`.

### Reading post-edit-watch.cjs
- Filters: `tsx|jsx|ts|js|css|scss` — `tailwind.config.ts` matches via `.ts`. ✅
- Reads `payload.toolInput.content` or `new_string`. For an `Edit` of tailwind.config.ts, `new_string` will contain the inserted hex. ✅
- Extracts hexes, dedups, lowercases.
- Reads DESIGN.md, scans hex set.
- Reports introduced = hexes minus design set.

### Bugs

**MAJOR bug — case-sensitivity asymmetry:**
- New text scan: `(newText.match(/#[0-9a-f]{3,8}\b/gi) || []).map((h) => h.toLowerCase())` — matches both cases, lowercases.
- DESIGN.md scan: `text.toLowerCase()` first, then `text.match(/#[0-9a-f]{3,8}\b/g)` — **non-`i` regex on already-lowercased text**. Works but fragile.
- This *happens to work* but the asymmetry is a code smell — one of these will get touched and break the other.

**MAJOR bug — false positives on hex-like numerics:**
`#3a86ff` matches. But so does `#abc` and `#fff`. The regex `[0-9a-f]{3,8}` is correct for hex but **also matches `#decade` (a CSS comment "#decade") or random strings like `#abcdef` in code comments**. For S editing a config file with comments like `// see issue #1234abc`, **wait — `\b` after `[0-9a-f]{3,8}` requires a word boundary**, so `#abcdef` followed by `g` wouldn't match. OK, that's actually safe for length 3/4/6/8. But length-5 matches like `#decade` (length 6, valid hex chars, valid hex) **would** be picked up as a "color." False positive.

**MAJOR bug — DESIGN.md token coverage assumption:**
The hook flags any hex *not in DESIGN.md*. But DESIGN.md uses `oklch()` or CSS-var references in modern projects (Tailwind v4 / shadcn). If DESIGN.md says `--color-brand: oklch(0.62 0.19 256)` and never literally writes `#3a86ff`, the new hex will *always* be flagged "introduced" — even though it's the literal of the canonical token. **Net:** every hex edit gets flagged. S will silence the hook by day 2.

**MINOR bug — message is borderline noise:**
The output is "방금 X 에 DESIGN.md에 없는 색이 들어갔어요: #abc, #def, ...". For a config edit that adds 12 hexes (a palette import), the user gets a 3-hex truncated list with no scope on whether these are intentional palette extensions or accidental drift. Should differentiate: "1 hex added in `theme.colors.*` (likely intentional palette extension) — preference capture optional" vs "1 hex added in `Button.tsx` className=[#fff] (likely surface-patch) — preference capture **recommended**".

**MINOR bug — exit code:**
Hook exits 0 in all paths. Hook contract for Claude Code surfacing `additionalContext` is via stdout JSON. Confirmed correct on line 71. ✅

### Will it fire?
On `Edit` of `tailwind.config.ts` with `new_string` containing `#3a86ff` and DESIGN.md not containing it: **yes, fires, message displays.** Useful? **Marginally** — message is a one-liner suggestion, not a noise wall. But the false-positive rate (oklch projects, palette imports, comment hex-likes) will erode S's trust within days.

---

## Cross-cutting findings

### CRITICAL
- **C1.** `code-introspect.ts` reports `1px` border widths as top spacing tokens (Step 2). Spec violation: "spacing" semantically excludes border widths. Fix required before v4 ships.
- **C2.** `code-introspect.ts` does **not** detect inconsistencies (radius scale length, color cluster count, 8pt grid violations) — only frequency. For S the headline value is missing. Either rename to `code-census.ts` or actually add the inconsistency detector.
- **C3.** Fold-in score formula promotes opinion-importance entries (importance=1) freely once count×recency clears the bar (Step 6). False promotion failure mode confirmed. Fix: weight by `(importance - 1)` so opinions need higher count to clear; or hard floor `importanceAvg >= 2.5`.
- **C4.** Fold-in algorithm duplicated between `memory.ts` and `session-end-foldin.cjs` with subtle config drift (Step 6). Source-of-truth violation.
- **C5.** post-edit-watch.cjs cannot reconcile `oklch()` / CSS-var DESIGN.md with literal-hex code edits → every Tailwind v4 project will see 100% false-positive flags (Step 7).

### MAJOR
- **M1.** Persona classification is sticky-on-first-message; long-form S who opens with "audit this" misclassifies (Step 1).
- **M2.** Rule 999 (`[FILL IN]` for §11–13) has no negotiation protocol when user pushes back (Step 4).
- **M3.** Critic.md lacks anti-platitude clause; can quietly hedge in §6 severity verdict.
- **M4.** Critic re-do-scope can cascade into 18 phase-re-runs over 3 iterations with no memoization (Step 5).
- **M5.** post-edit-watch.cjs case-sensitivity asymmetry between new-text scan and DESIGN.md scan (Step 7).

### MINOR
- **m1.** No "existing tooling acknowledgment" slot — husky/lint-staged user gets generic onboarding.
- **m2.** `harvestFromTailwindConfig` silently misses imported palettes.
- **m3.** Component/CSS file caps emit warnings nobody reads.
- **m4.** `mapScopeToSection` too coarse (`spacing.button` → §5 instead of §4).
- **m5.** session-end-foldin.cjs dead code on line 93.
- **m6.** Critic.md §2 has no minimum-row requirement; lazy critic can pass with 1-row table.
- **m7.** post-edit-watch message doesn't differentiate "intentional palette extension" vs "drift in component file."
- **m8.** Opinion vocab in signal-classifier may still be thin for English (i1 expanded Korean only — would need to verify but English opinionated dev vocabulary like "honestly / frankly / hate / love / not having it" likely under-covered).

---

## Verdict

**v4 is not yet S-ready. Two CRITICAL must-fix before a senior dev would tolerate a daily-driver loop:**

1. `code-introspect` outputs noise (border widths as spacing, no inconsistency detection). S will dismiss the system after the first inventory readout.
2. Fold-in algorithm allows opinion-tier entries to promote into §-level rules with mere recency/recurrence. False promotion is the single failure mode S flagged in advance — and the formula does it by default.

The critic scaffolding is genuinely strong (template forces verbatim evidence and root-cause traceback), and the file-handoff architecture between master and harness is clean. But the *measurement layer* (code-introspect + fold-in score) needs a rebuild, not a tweak. Currently the system is **honest about its rules but wrong in its math**.

Recommend i3 = focused fix of C1/C2/C3/C4/C5 with unit tests on (a) realistic 25-component fixture (real border + spacing mix) and (b) week-long synthetic preference log validating the score formula doesn't promote opinions. M-tier items are deferrable; minors can wait until post-v4.

**Severity: CRITICAL.**
