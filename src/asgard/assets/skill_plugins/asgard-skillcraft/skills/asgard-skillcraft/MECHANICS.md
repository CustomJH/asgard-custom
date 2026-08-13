# Skill mechanics

What changes when the document is a skill: the invocation choice, the packaging, and the Asgard
surfaces that carry it. Everything else about writing it is the universal reference in `SKILL.md`.

## Invocation

Two choices, trading the two loads against each other.

- **Model-invoked** keeps a `description`, so the agent can fire the skill on its own and other
  skills can reach it. The human keeps their reach either way — a description only ever adds agent
  discovery, it never removes the ability to type the name. That description is a top-level context
  pointer forced to stay loaded every turn: permanent context load bought with discoverability.
  A model-invoked skill that is all reference is also the one home for shared reference, because
  another skill can invoke it. Mechanics: omit `disable-model-invocation` and write a model-facing
  description carrying the trigger branches.
- **User-invoked** strips the description from the agent's reach. Only the human typing the name can
  start it, and no other skill can. Zero context load, paid for in cognitive load — the human is now
  the index that has to remember it exists. Mechanics: set `disable-model-invocation: true`, and the
  description becomes a human-facing picker label with the trigger list stripped.

Choose model invocation only when the agent must reach the skill on its own, or another skill must.
A skill that only ever fires by hand is user-invoked and costs nothing per turn.

Two user-invoked skills that need the same reference can share it through neither of themselves —
with no descriptions, neither can fire the other. Put that material in a plain resource file and
point both at it.

**Splitting by invocation** is the second cut (the sequence cut lives in `SKILL.md`): split off a
model-invoked skill when a distinct leading word should trigger it on its own — a word you actually
type — or when another skill must reach it. You pay for a new always-loaded description, so the
independent reach has to be worth it.

**Router skills** cure the cognitive load that piles up once user-invoked skills outnumber what a
person can hold: one user-invoked skill that names the others and says when to reach for each. It
can only hint, never fire them.

## Packaging in Asgard

- One frontmatter flag drives both harnesses. `disable-model-invocation: true` in `SKILL.md` is
  what `asgard sync` reads to emit Codex's `agents/openai.yaml` with
  `policy.allow_implicit_invocation: false`; there is no second place to keep in sync.
- `plugin.json` declares every skill in `skills`, and `routing` needs a non-empty `triggers` list
  for each one — the manifest refuses the plugin otherwise. Trigger matching is plain substring
  containment against the request text, so an English-only trigger list never fires on a Korean
  request. Give each skill both.
- `routing.<skill>.agents` is the set of roles the skill may open for, and `defaults` the roles it
  opens for without being assigned. Both are drawn from worker, freyja, thor, thor-lead, eitri,
  mimir.
- Client adapters (`.claude/skills/<name>/SKILL.md` and the `.agents/skills` twins) carry no policy.
  They run `asgard skills show <name>` and apply what comes back, so the body has exactly one home.
- Reach a sibling file with `asgard skills show <name> --resource <relative-path>`, or the native
  `load_skill` resource loader. Absolute paths, symlinks, and `..` escapes fail closed.
- A skill whose procedure is already bounded declares `lane:` in its frontmatter, so the native
  router reads the declaration instead of inferring a write quest from the verbs in its prose.
- Discovery does not depend on a trigger phrase landing: `asgard skills resolve --agent <role>
  "<request>"` sizes the work shape deterministically and names the disciplines it matched.
