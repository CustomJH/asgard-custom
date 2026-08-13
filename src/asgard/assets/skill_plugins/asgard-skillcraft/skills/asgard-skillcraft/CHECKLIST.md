# Skillcraft checklist

How to prove the document does what `SKILL.md` asks of it. The rules live there; the packaging rules
live in `MECHANICS.md`. This file is the evidence pass.

## Before you return

- **Trigger** — the pointer names the job and one trigger per distinct branch, and the chosen
  invocation matches how the skill actually gets started.
- **Structure** — an ordinary run loads only the common path, every optional branch can retrieve its
  own resource, and each step ends on a criterion you could check from the outside.
- **Steering** — the behaviour you asked for shows up in outputs or tool choices. Private reasoning
  text is not a test oracle.
- **Size** — catalog characters and canonical body characters, before and after. Smaller counts as a
  result only when trigger recall and the process checks still pass.

## The deletion test

A sentence is a no-op only when behaviour says so. Run it sentence by sentence over prose that
claims to bear on behaviour:

1. Pick 3-5 representative prompts, including one non-trigger and one edge branch.
2. Capture observable process signals: which skill was selected, the tool sequence, the artifacts,
   the validation command, and whether the final output honoured the constraint.
3. Run the canonical skill, then a temporary variant with one sentence removed, under the same model
   and settings where practical.
4. Delete the sentence only when the observable process stays equivalent across the cases. Keep it
   when the sample is inconclusive, or when the sentence is a safety boundary.
5. Remove the temporary variant, and record the cases as the smallest regression that would catch
   this drift again.

For an approved learned skill, `asgard evolve bench` measures a whole skill OFF against ON.
Sentence-level work still needs the temporary variant, because that bench toggles a complete skill
rather than one line.

Prose is not a no-op because it sounds generic. That judgement is a preference about word count
until a run backs it.

## Surface checks

- `asgard skills list` reports the invocation as `model` or `user`, matching the frontmatter.
- A user-invoked skill still answers `asgard skills show <name>`, and is absent from the native
  `<available_skills>` block and from deterministic `asgard skills resolve` results.
- In `asgard start`, an exact `/<name> [arguments]` invocation expands the canonical body for that
  turn, and `/skills` lists the zero-context user-invoked choices.
- `asgard skills show <name> --resource <relative-path>` reads the sibling file; absolute paths,
  symlinks, and `..` escapes fail closed.
- `asgard sync` refreshes the generated adapters without overwriting user-owned files, and the
  adapters still carry no policy body.
