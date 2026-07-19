# Skillcraft checklist

Sources: Matt Pocock's *Building Great Agent Skills: The Missing Manual* and the `writing-great-skills` reference in `mattpocock/skills` at revision `9603c1c`. This file is a distilled Asgard adaptation, not a copy.

## 1. Trigger

- Decide who bears the load. Model invocation spends context on every turn; user invocation spends the operator's memory.
- A model-facing description names the job and distinct trigger branches. Synonyms for one branch are duplication.
- A user-facing description is a short picker label. Set `disable-model-invocation: true`; Codex also needs `agents/openai.yaml` with `policy.allow_implicit_invocation: false`.
- If manual commands become hard to remember, add one user-invoked router rather than making every command model-invoked.

Done when the chosen mode matches both Claude/Cursor `SKILL.md` discovery and Codex metadata, and the opposite mode cannot load it implicitly.

## 2. Structure

- Separate ordered steps from supporting reference.
- Every step ends in a checkable completion criterion.
- Inline material every branch needs. Put branch-only templates, glossaries, examples, and large rule tables in a sibling file.
- The context pointer says when to read a resource, not merely where it exists.
- Keep one source of truth. Cross-skill copies drift; invoke the owning skill or load its resource.

Done when a normal run loads only the common path and each optional branch can retrieve its own resource without path escape.

## 3. Steering

- Prefer a pretrained leading word such as `red-green`, `vertical slice`, `tight loop`, or `fog of war` over a paragraph that restates it.
- Reuse the same word in description, process, tests, and project vocabulary where it is genuinely the same concept.
- Positive target behavior beats a list of prohibited alternatives; retain explicit negatives only for safety guardrails.
- If a visible future step causes premature completion, first sharpen the current completion criterion. Split the sequence only when observed rushing remains.

Done when the behavior appears in outputs or tool choices; private reasoning text is not a required test oracle.

## 4. Pruning and deletion tests

Run the test sentence by sentence for behavior-bearing prose:

1. Pick 3-5 representative prompts, including one non-trigger and one edge branch.
2. Capture observable process signals: selected skill, tool sequence, artifacts, validation command, and final constraint compliance.
3. Run the canonical skill, then a temporary variant with one sentence removed under the same model/settings where practical.
4. Delete the sentence only when the observable process remains equivalent across the cases. Keep it when the sample is inconclusive or the sentence is a safety boundary.
5. Remove the temporary variant. Record the eval cases as the smallest regression that can catch future drift.

Do not claim that prose is a no-op because it sounds generic. A deletion test is behavioral evidence, not word-count preference.

## 5. Asgard checks

- `asgard skills list` reports `model` or `user` invocation.
- A user-invoked skill remains available through `asgard skills show <name>` but is absent from native `<available_skills>` and deterministic `skills resolve` results.
- Resource reads use `asgard skills show <name> --resource <relative-path>` or native `load_skill`; absolute paths, symlinks, and `..` escapes fail closed.
- Client adapters contain no policy body. `asgard sync` updates generated adapters without overwriting user-owned files.
- Compare catalog characters and canonical body characters before/after. Smaller is a result only when trigger recall and process checks still pass.
