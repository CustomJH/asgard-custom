---
name: escort
description: Generate an interactive script that walks a human through steps only they can take. Use when provisioning infrastructure, obtaining credentials or setting CI secrets, walking an unfamiliar third-party dashboard, or running a one-off migration or cutover. Do not reach for it for steps an agent can perform itself.
---

# Escort

An **escort** is a shell script that walks a human, stage by stage, through a manual procedure —
tedious by hand and tedious to re-explain to an agent every time. It opens each URL, says exactly
what to click and copy, captures the values, writes them where they belong, confirms before anything
irreversible, and shows how many stages are left.

Work an agent can do, an agent should do. This is for the clicks, the approvals, and the dashboard
trips you would not hand to one — so when a build hits a step only the human can take, generate an
escort for it instead of dropping numbered instructions into the chat and hoping they get followed.

**It is also how a credential reaches a file without passing through the agent.** Canon 4 keeps
secrets out of the agent's reach; an escort honours that rather than working around it. The agent
authors the script and never sees a value: the human types it into the running script, `ask_secret`
keeps it off the screen, and it lands in `.env` or a CI secret without ever entering a transcript.
Never author a stage that prints a captured secret, and never read one back to check it.

Load the library with the resource loader before authoring:

    asgard skills show escort --resource template.sh

The UX is already solved there — stage progress, confirmation gates, cross-platform URL opening
(including WSL), hidden secret entry, idempotent `.env` upserts, `gh secret` / `gh variable` writes
that degrade gracefully, and a closing summary of what still needs doing by hand. **Your job is only
to scope the procedure and author its stages.** Everything above the `STAGES` marker is identical in
every escort; that consistency is the point.

An escort is ephemeral by default — built for one run, written to a scratch or `scripts/` path, gone
when the job is done. Commit it only when the user wants a repeatable setup path living in the repo.

It is a bash script: on Windows it runs under Git Bash or WSL, and the template already opens URLs
through `wslview` / `explorer.exe`. Say so when you hand it over on a Windows machine.

## 1. Scope the procedure

Work out every manual step the human must take and every value captured along the way. Read the
repository first — never ask cold:

- For setup: `.env.example` and `.env.*` templates, the README, `docker-compose*`, framework config,
  and every `secrets.*` / `vars.*` reference in `.github/workflows/`. Each reference is a value the
  escort must produce. Read the templates and the reference names, not the filled-in `.env` itself.
- For a migration or cutover: the current state, the target state, and the irreversible actions
  between them.

Then show the user the ordered stage list and the values each one produces, and confirm — they may
add, drop, or reorder. When the agent fired this mid-build, that confirmation doubles as the proposal.

Done when every stage is named in order, and for each captured value you know where the human gets
it, where it is written (`.env`, a CI secret, both, or nowhere — some stages are pure actions), and
whether it is secret.

## 2. Map each stage's journey

For each stage, write the precise path a human follows: which URL, what to do there, where the value
is shown, which variable it fills — "Dashboard → Developers → API keys → Reveal test key → copy".
Where you do not know the current UI or the exact command, say so and ask the user or check the
docs. An invented click path costs more than an admitted gap (Canon 11).

Done when every stage traces to concrete instructions a stranger could follow.

## 3. Author the stages

Copy `template.sh` to the target path. Replace the example stage with one `stage` per step, in
dependency order, and set `TOTAL_STAGES` to the number you wrote. Use the library helpers — `stage`,
`say` / `step`, `open_url`, `ask` / `ask_secret`, `write_env`, `set_secret` / `set_var`, `pause` /
`confirm` — and leave the library above the marker untouched.

Hold the bar the template sets: open the URL before asking for its value, `ask_secret` for anything
secret, `write_env` every persisted value, `set_secret` only what CI actually needs, and `confirm`
before any irreversible action. Each `stage` clears the screen, so keep a stage to one focused task
and nothing the human still needs scrolls away.

Done when every value from step 1 has a stage that captures it and a call that persists it.

## 4. Verify and hand off

- `bash -n <script>`, then `shellcheck` if it is available.
- `chmod +x <script>`.
- Do not run it end to end yourself — it opens browsers and blocks on human input. Trace it
  statically instead: every value from step 1 is captured and lands where step 1 said, and every
  `set_secret` name matches a `secrets.*` reference in CI exactly.
- Tell the user how to run it. If it is a repeatable setup path, commit it and link it from the
  README, so the next person runs the script instead of asking an agent.

Done when `bash -n` exits 0 and the static trace covers every value from step 1.
