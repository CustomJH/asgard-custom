---
name: asgard-skills
description: Before ordinary Codex or Cursor work, select and load the matching Asgard skill or plugin policy; also manage the central catalog.
allowed-tools: Bash(asgard skills *)
---

# asgard-skills — central router

For ordinary Codex or Cursor work, use this router once before task-specific decisions. Pass only
one of these exact lowercase CLI roles. `MAIN_WORKER` and agent names are not valid role values;
classify their task instead:

- `freyja` — UI, design, UX, motion, browser, 3D, or video
- `thor` — backend, data, API, security, or runtime infrastructure
- `eitri` — build, CI, packaging, or release
- `mimir` — code explanation, walkthrough, or onboarding
- `worker` — debugging, testing, and everything else

Then run:

    asgard skills resolve --agent <role> "<current task>"

Run the installed `asgard` executable directly from `PATH`. Do not prefix the command with
`python`, and do not resolve `asgard` relative to this skill directory.

Apply only the returned policies. Empty output means no extra policy. Do not also auto-select an
individual `.agents/skills` adapter; those remain available as explicit overrides, and the syntax
differs by host: Cursor takes `/name`, Codex takes `$name`. Codex answers `/name` with
`Unrecognized command` — its slash menu is reserved for session control, and `/skills` only opens
the picker (openai/codex#11817, closed as not planned).

The output ends with a `Work shape` block whenever the request implies a change. It states the
deterministic size of the work — `slice`, `feature`, or `expedition` — the planning discipline that
shape requires, and the names of any discipline skills whose triggers this request matched. Load
each named skill with `asgard skills show <name>` before deciding; the match is deterministic, so it
is not a suggestion to re-evaluate. Hold to the shape: do not inflate a slice into a feature to look
thorough, and do not compress a feature into one sweep to look fast.

For catalog management, use:

    asgard skills
    asgard plugins
