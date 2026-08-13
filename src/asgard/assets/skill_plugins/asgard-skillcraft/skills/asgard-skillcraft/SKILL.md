---
name: asgard-skillcraft
description: Writing any document an agent reads. Use when creating or editing a skill, changing AGENTS.md / CLAUDE.md / MANUAL.md or a doc the harness injects, choosing user or model invocation, cutting context load by disclosing reference, or pruning prose that changes no behavior.
agent: worker
---

# Skillcraft

A document written for an agent makes a stochastic model follow the same **process** — not emit the
same answer. That is the whole target, and it is the same target for a skill, an `AGENTS.md`, a
`MANUAL.md`, and a reference file reached by a pointer. The packaging differs; the writing does not.

Trace the real loaders before editing: who injects this text, on which turn, and at what size. When
the document is a skill, load `MECHANICS.md` for frontmatter, the invocation choice, and routers.

## Context pointers

A **context pointer** is a reference held in the agent's context that names material sitting outside
it and encodes the condition for reaching it. A skill's description is one. A line in `AGENTS.md`
naming a doc is the same object. The pointer's *wording*, not its target, decides whether the agent
reaches the material — so a must-have target behind a vague pointer is a variance bug. Sharpen the
wording first; inline the material only when sharpening fails.

A pointer does two jobs: say what the material is, and list the **branches** that should trigger
reaching it. Because an always-loaded pointer costs on every turn, prune it harder than the body —
lead with the trigger word, keep one trigger per branch (synonyms are one branch written twice), and
cut identity the body already carries.

## The two loads

Every document and pointer spends one of two budgets.

- **Context load** — what always-loaded material costs the model's window: an `AGENTS.md` line, a
  skill description, anything present every turn whether or not it fires.
- **Cognitive load** — what it costs Odin: which documents exist, and when to reach for each. Not a
  cost to drive to zero. It is the price of human agency — spend it where human judgement decides
  the outcome, remove it where it does not.

Material behind a pointer escapes context load at the price of the pointer's own line. Material with
no pointer at all rides entirely on cognitive load.

## The information hierarchy

A document mixes two content types freely: **steps** (ordered actions the agent performs) and
**reference** (definitions, rules, and facts consulted on demand). The decision is where each piece
sits on a ladder ranked by how immediately the agent needs it.

1. **In-file step** — the primary rung: what the agent does, in order.
2. **In-file reference** — consulted on demand. A flat peer-set of rules on one rung is a legitimate
   arrangement, not a smell.
3. **Disclosed reference** — pushed into a separate file behind a pointer, loaded only when the
   pointer fires. Spans a sibling file through fully external material any document can point at.

**Progressive disclosure** is the move down that ladder. It is not primarily a token saving: it is
how the top of the document stays legible. Branching is the cleanest test — inline what every branch
needs, disclose what only some branches reach. In a document that has steps, undisclosed reference
buries them, and attending to them becomes a coin flip.

**Co-location** decides what sits beside a piece once the ladder has placed it: keep a concept's
definition, its rules, and its caveats under one heading, so reading one part brings its neighbours
along. Scattering fragments one meaning across many places; duplication repeats one meaning in two.

**Sprawl** is the failure this section exists to catch — a document simply too long, even when every
line is live and unique. Attention thins across the excess and every extra line is one more to keep
true. The cure is the ladder: disclose reference, and split by branch or by sequence so each path
carries only what it needs.

## Completion criteria

Every step ends on the condition that tells the agent the work is done. Two properties make that a
lever, not a formality.

- **Clarity** — can the agent tell done from not-done? A vague bound ("understanding reached")
  invites premature completion, with attention sliding toward *being done* while later steps are
  still visible. Sharpen the bound first; that is local and cheap. Split the sequence only when the
  bound is irreducibly fuzzy *and* you have observed the rush — and hiding later steps works only
  across a real context boundary (a handoff or a dispatched subagent), never an inline call.
- **Demand** — how much the criterion requires. "Every modified model accounted for" forces digging
  that "produce a change list" does not. Demand is not step-bound: "every rule applied" binds a body
  of flat reference exactly as "every step done" binds a sequence, which is how an all-reference
  document still carries an exhaustiveness bar.

The strongest criteria are both checkable and exhaustive.

## Leading words

A **leading word** is a compact concept already living in the model's pretraining that the agent
thinks with while running the document — *red-green*, *vertical slice*, *tight loop*, *fog of war*.
Repeated as a token and never as a sentence, it anchors a whole region of behaviour in the fewest
tokens by recruiting priors the model already holds. A coined word recruits none: you pay in
definition tokens what an existing word gives free, so reach for the existing word first.

It anchors twice — in the body the agent reaches for the same behaviour every time the word appears,
and in a pointer the shared vocabulary between your prompts, your docs, and your code makes the
material easier to find. Hunt for passages that collapse into one: "fast, deterministic,
low-overhead" is a *tight* loop; "a loop you believe in" is a loop that goes *red*.

Steer by the positive target. A prohibition drags the forbidden behaviour into context and makes it
more available, not less, and the negation is a weak modifier that the activated concept overruns.
Write "one-line comments" rather than a ban on long ones. Keep an explicit negative only as a safety
guardrail you cannot phrase positively, and pair even that with the positive target.

## Pruning

- Keep each meaning in one authoritative place, so changing the behaviour is a one-place edit.
  Duplication costs maintenance and tokens, and it inflates a meaning's rank on the ladder past
  what it deserves.
- The **environment** is a source of truth too — `pyproject.toml`, config files, the directory
  layout, `--help` output. A document restating it is a **cache** of a lookup, and it earns its load
  only when that lookup is expensive. Cache what the agent cannot find by looking: the unwritten
  convention, the reason behind a choice, the gotcha no config confesses. Leave one-file,
  one-command lookups to the environment, where they cannot go stale.
- Check every line for relevance. A line loses it by never bearing on the task, or by going stale as
  the world it describes moves. Without a pruning habit the default outcome is sediment: stale
  layers that settle because adding feels safe and removing feels risky.
- Hunt no-ops sentence by sentence. The test is whether the sentence changes behaviour against the
  default, which is model-relative rather than reader-relative — two people who disagree about a
  no-op disagree about the default, and they settle it by running the document. When a sentence
  fails, delete the whole sentence instead of trimming words from it. The same test grades leading
  words: one too weak to beat the default is a no-op, and the fix is a stronger word.

A sentence is a no-op only once evidence says so. For the full rubric, the deletion-test protocol,
and the Asgard surface checks, load `CHECKLIST.md` with the current skill resource loader.
