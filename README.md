# Asgard

Make anything, your way — a portable setup system with a self-contained install (no Node, Bun, or git required to run it).

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/CustomJH/asgard-custom/main/install.sh | bash
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/CustomJH/asgard-custom/main/install.ps1 | iex
```

Neither installer needs a system Python, Node, or git — `uv` fetches a standalone CPython 3.14 of its
own. Both draw the same screen: the brand lockup, three numbered phases, and a spinner on every step
that takes a while (the toolchain download and the one-time memory search model are the slow ones).
Re-running either line updates an existing install.

On Windows the glyph set follows the terminal. Windows Terminal, VS Code and ConEmu get the full
Unicode look; the legacy console, which draws boxes instead of braille, gets an ASCII wordmark and an
ASCII spinner. Force that plainer set anywhere with `ASGARD_ASCII=1`, drop colour entirely with
`NO_COLOR=1`, or keep the full UI when output is redirected with `ASGARD_FORCE_UI=1`.

If the Windows install does fail, it stops on a message instead of closing the terminal: the
reason, what to try, an environment table, and a full transcript written to
`%TEMP%\asgard-install-<timestamp>.log`. Set `ASGARD_NO_PAUSE=1` to skip the keypress in automation.

If the `irm` line itself fails with an SSL/TLS error, the fetch died before the installer could run —
older Windows PowerShell 5.1 hosts still default to TLS 1.0. Enable TLS 1.2 for the session first:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
irm https://raw.githubusercontent.com/CustomJH/asgard-custom/main/install.ps1 | iex
```

Installs `asgard` to `~/.local/bin`. Then:

```bash
asgard doctor    # verify
asgard --help
asgard open studio  # native app when installed, browser fallback otherwise
```

The installer manages a standalone CPython 3.14. Running from source or importing Asgard as a library
also requires Python 3.14 or newer; older interpreters cannot parse its PEP 758 syntax.

## Local or isolated execution

`asgard start` asks where Heimdall should run when attached to a terminal. Local mode is fastest.
The cross-platform container modes use the current Docker-compatible engine: OrbStack/Docker/Podman on
macOS and Docker Desktop/Podman Desktop on Windows. `container` works from a persistent private copy;
`container-shared` deliberately mounts the host checkout read-write for immediate edits. Neither mode
requires a Docker Sandboxes account. Windows engines must be configured for Linux containers.

```bash
asgard start --execution local
asgard start --execution container         # macOS + Windows; private workspace
asgard start --execution container-shared  # macOS + Windows; live host working tree
asgard start --execution sandbox           # Docker microVM + private Git clone
asgard start --execution sandbox-shared    # Docker microVM + live host working tree
```

The standard container passes only API-key environment variables that are already set on the host; those
keys are readable inside the container. Do not mount the Docker socket. Private workspaces persist under
`~/.asgard/sandboxes/` so changes can be reviewed without touching the original checkout. Host Git
credentials and SSH agents are not mounted, and a private clone's original remote is removed.

For the stronger Docker Sandbox modes, install Docker's `sbx` CLI and run `sbx login`. Private-clone sessions
start from committed `HEAD`; commit inside the sandbox and fetch the generated `sandbox-<name>` remote
before removing it. Asgard does not mount the host Docker socket or copy raw provider keys into the VM;
the bundled sandbox kit uses Docker's host-side credential proxy. Register the provider once with
`sbx secret set -g openai`, `sbx secret set -g anthropic`, or `sbx secret set -g nvidia`.
The first kit supports those API-key providers; host OAuth sessions, Claude CLI state, Ollama localhost,
and host `--provider`/`--model`/`--continue` flags are intentionally not copied across the boundary.
Docker currently marks custom sandbox kits as Early Access, so Asgard fails closed with install guidance
when `sbx` is unavailable instead of silently falling back to local execution.

During a turn, the status area shows the active role and concurrent child count. `/sessions` lists recent
Thinker, Worker, Verifier, and delivery sessions; Ctrl-C cooperatively cancels the active child tree, and
`/sessions stop` exposes the same cancellation boundary as a command.

For two-model planning, assign a distinct `thinker_alt` with `/trinity set`, then run
`/trinity dual on`. Both read-only Thinkers plan independently in parallel; one Worker synthesizes
their plans, and the normal Verifier gate remains unchanged. Use `/trinity dual default on` to make
it the project default for future `asgard start` sessions. Headless runs use `asgard run --dual`.
Automatic policy tier-to-model mapping and situational tier bumps apply only to Anthropic/Claude CLI;
other providers keep the selected model unless each Trinity role is explicitly placed.

Generated host subagents have role-specific model defaults. Override only the roles you want in
`.asgard/asgard-setting-project.json` (or the same `agent_models` section in the global settings).
Project values override global values; omitted roles keep Asgard's defaults. The CLI writes project
overrides and immediately refreshes an already-scaffolded host:

```bash
asgard role model
asgard role model cursor worker gpt-5.6-terra-medium
asgard role model codex thinker gpt-5.6-sol --effort xhigh
asgard role model claude-code verifier opus --effort high
asgard role model cursor worker --reset
asgard role model native worker gpt-5.6-terra --provider openai-native
```

Inside `asgard start`, enter `/trinity model` for a guided host → role → recommended-model picker.
`/trinity models` lists everything; the direct forms `/trinity model cursor worker
gpt-5.6-terra-medium` and `/trinity model reset cursor worker` remain available. Run `asgard role list`
to inspect bridge state alongside resolved native placements and hosted-agent models.

```json
{
  "agent_models": {
    "claude-code": {"worker": {"model": "sonnet", "effort": "high"}},
    "cursor": {"worker": {"model": "gpt-5.6-terra-medium"}},
    "codex": {"worker": {"model": "gpt-5.6-terra", "effort": "medium"}}
  }
}
```

Native Heimdall remains provider-aware: configure it with `trinity.<role>.provider/model`, `/trinity set`,
or the `native` form above.

## Tool Kernel

Asgard resolves tools from one role-scoped capability policy for both the native
agent loop and generated Claude Code agents. Inspect the frozen surfaces with:

```bash
asgard tools list --role thinker
asgard tools list --role worker --json
asgard tools list --role verifier
```

Native tools are registered as `ToolSpec` values in
`asgard.agent.tool_kernel.ToolRegistry`. A spec binds its model schema, handler,
capability, availability check, and source so schema exposure and execution
cannot drift. `AgentSession(extra_tools=..., tool_handlers=...)` remains
supported and is adapted into a session-scoped registry. Claude Code role files
use explicit least-privilege `tools:` allowlists validated against the same
policy contract; write tools are absent from Thinker, Verifier, Loki, and Ullr.
Their Bash surface is restricted to allowlisted inspection and verification
commands, while all roles retain pre-execution destructive Git/filesystem guards.

## Skill and Plugin Registry

Asgard owns the canonical catalog and bodies. Claude Code, Cursor, and Codex receive thin
per-skill discovery adapters: the host indexes each name and description, chooses relevant skills,
then the selected adapter loads one canonical body. Native Heimdall uses the same two-stage flow
through its read-only `load_skill` tool. `skills resolve` remains an explicit diagnostic command,
not a phase-start injection path.

```bash
asgard plugins list
asgard skills list
asgard skills resolve --agent thor "database migration API"
asgard skills show asgard-thor-jarngreipr
asgard skills disable asgard-worker-testing
```

A local resource plugin is installed with `asgard plugins install <path>`. Freyja ships its core
delivery contract plus separately bundled specialist plugins — `freyja-design`, `freyja2`,
`freyja4`, `freyja-3d`, `freyja-fjadrhamr`, and `freyja-sjonhverfing` — each disabled or enabled on
its own with `asgard skills disable|enable`. A plugin contains `plugin.json` and declared
`skills/<name>/` directories:

```json
{"schema": 1, "name": "acme", "version": "1.0.0", "skills": ["acme-db"], "entrypoints": {"acme-db": "scripts/search.py"}}
```

The skill list reports `model` or `user` invocation. Standard `disable-model-invocation: true`
skills remain manually loadable but stay out of model discovery; Codex adapters also receive the
matching `agents/openai.yaml` policy. The bundled `asgard-skillcraft` skill applies the same
trigger/structure/steering/pruning discipline when authoring or reducing skills.

Inside `asgard start`, `/skills` lists only explicit user workflows and
`/<skill-name> [arguments]` loads exactly that canonical body for the current turn. Built-in
commands keep priority, disabled skills cannot be invoked through this path, and user workflows
never enter model discovery. The bundled `/grill-me`, `/to-spec`, `/to-tickets`, and `/wayfinder`
flows cover decision clarification, work sizing, and durable multi-session handoffs; the
model-invoked `domain-modeling` and `prototype` skills carry reusable domain vocabulary and
throwaway design-question artifacts into any of them.

Routing can be declared centrally under `plugin.json`'s `routing` object, or with the legacy
`triggers`, `agent` (default assignment), and optional `agents` fields in frontmatter. Resource
files are copied intact and text references are available through `asgard skills show --resource`.
Only Python entrypoints explicitly listed in the manifest can run, through
`asgard skills run <name> ...`; arbitrary hooks and shell commands are never registered.

A skill listed in `plugin.json`'s `anchored` array is delivered as a location instead of a body.
Asgard unpacks its tree into `<project>/.asgard/skills/<name>/` and returns a short pointer naming
that directory, so the client reads the original `SKILL.md` from disk. This is for packs that carry
their own runtime and resolve paths against the directory holding their `SKILL.md` — a body long
enough to be truncated by a host's command-output ceiling would otherwise arrive half-read, and
paths relative to the skill directory would have no anchor at all. The unpacked tree is derived
state: it is git-ignored, refreshed when the shipped version changes, and falls back to the
installed copy when the project cannot be written to. The bundled `last30days` research skill —
Reddit, X, YouTube, TikTok, Hacker News, Polymarket, GitHub, and the web over a 30-day window — is
delivered this way and is available in every mode after install, with no extra setup.

## Documents (Sága)

```bash
asgard office outline                                  # 23 document and deck genres
asgard office outline design-doc -o spec.md            # a build-ready skeleton
asgard office build docx spec.md -o design.docx        # also: pptx, xlsx
asgard office verify design.docx --strict              # the static delivery gate
asgard office fill form.docx --values v.json -o out.docx
asgard office template list|show|new|adopt|check|render
asgard office render design.docx                       # PDF + page images (needs LibreOffice)
```

Documents are built from a spec, not typed into a binary: Markdown with YAML front matter for
Word and PowerPoint, YAML for Excel. Build, read, fill, and verify are pure Python — no Word,
LibreOffice, or pandoc is needed, so a one-command install has the whole lane. `verify` proves
what a machine can prove without a renderer: text past its box, shapes off the canvas, contrast
under the WCAG floor, dangling package relationships, unfilled `{{placeholders}}`, and
spreadsheet formulas that would open as `#NAME?`. Rendering to PDF is the one external gate,
and it exits non-zero rather than skipping the visual check quietly.

Templates are directories, discovered from `.asgard/office/templates/` (project),
`~/.asgard/office/templates/` (user), and the bundled set, nearest scope winning by name. A
template carries a field schema, so `template check` fails on a missing required value before
the build rather than inside the delivered document. `template adopt --from FILE` turns a
document somebody else designed — a letterhead, a client shell, a government form — into one by
scanning its placeholders. The same `{{field}}` and `{{#rows}}…{{/rows}}` grammar works in a
Markdown skeleton, a `.docx`, a `.pptx`, and an `.xlsx`. Korean `.hwp`/`.hwpx` stays with the
bundled `hwpx` skill. Agents reach the same engine through
`asgard skills run asgard-office -- …`.

## Project Map

```bash
asgard map generate                         # initialize the deterministic shared map
asgard map update                           # refresh structural facts
asgard map scan                             # rebuild source-grounded relation evidence and named gaps
asgard map trace --from route:GET_/users    # walk one bounded graph direction/slice
asgard map impact route:GET_/users --json   # revision-bound two-way impact evidence
asgard map check                            # read-only drift and area-map validation
asgard map context --query "worker routing" # inspect bounded agent context
```

The team-shared map lives in `.asgard/map/`. `PROJECT.md` is a compact, deterministic
orientation map built from paths, manifests, verification commands, public symbols, and
local import relations observed on disk. `GRAPH.md` is the source-derived relation catalog;
its complete machine-readable state lives in the derived, untracked
`.asgard/state/map-graph.json`. Every graph location carries a bounded source span and every
known omission — unsupported source, excluded tests, parser bounds, or ambiguous convergence —
is retained as a named coverage limit instead of disappearing as an empty edge. `map impact`
returns confirmed and candidate rows separately, the remaining frontier, next exact reads,
the source revision, and a deterministic `impact_revision`.

Asgard owns and regenerates both managed projections. Human/agent-authored area maps such as
`cli.md` or `frontend.md` are bounded fog-of-war notes and are never overwritten. Main requests
and subagents receive only task-relevant map entries within a fixed context budget, including a
warning whenever relation coverage is partial. Each start refreshes structural drift, and quest
verification refreshes again before computing the Verifier diff hash, so automatic map changes
are covered by the same PASS instead of creating an unverified post-close write. `asgard setup
map` remains a backward-compatible alias.

Maps are navigation hints, not completion evidence. Thinker/Worker must still read the
definitions and usages that a plan depends on, while `asgard doctor` checks managed-map
drift plus stale, malformed, oversized, or unsafe entries in manual area maps.

## Studio

Every local window opens through one verb — `asgard open`. The command groups (`asgard map`,
`asgard memory`) stay what they are: hands that operate the data, not doors.

```bash
asgard open studio                 # native app when installed, browser fallback otherwise
asgard open studio --browser       # skip the native shell
asgard open studio --root ~/work/x # open standing in a specific workspace
asgard open studio --view tickets  # deep-link a screen (tickets|plan|projects|artifacts|…)

asgard open map                    # relation-graph view
asgard open memory                 # Yggdrasil dashboard (read-only)
```

A loopback workspace over the same ownership the CLI uses: `asgard run` executes the work,
`settings.py` persists configuration, and the central registry stays the catalog source of truth.

**The window belongs to the machine, not to a folder.** Wherever you launch it from — a repo, your
home, the dock — it opens standing in the same place: a personal workspace at
`~/.asgard/studio/workspace`. Only an explicit `--root` or `ASGARD_STUDIO_ROOT` puts it somewhere
else. The cwd never decides, and a plain directory is never registered as a project by being the
cwd, so launching from the dock leaves no `.asgard/` in your home.

Projects are not lost by this — they are **chosen**, in the window, per task. And the two surfaces
that are not about code do not move at all: **planning and the work board live in the workspace**
(`~/.asgard/studio/`, relocated together by `ASGARD_STUDIO_HOME`), so the same plans and the same
tickets are there from every repo and from none. A plan can *point at* a folder, but it never lives
inside one — an idea usually arrives before the repo does.

Which folder a task runs in is a property of **that task**, not of the window — the dock has a
workspace picker, so you can dispatch work into another project without swapping the screen you are
on, and following up on a task always re-enters the workspace it started in. Task bodies stay in
`<workspace>/.asgard/studio/tasks.jsonl`, so recent work and its artifacts survive closing the
window; a task that was still running when the process died is re-read as `interrupted` rather than
reported as live. Task **headers** are additionally indexed machine-wide in
`~/.asgard/studio/index.jsonl`, which is what lets the sidebar, the home screen, and `⌘K` answer
"what was I working on" across every project at once. That index is convenience, not canon — delete
it and it rebuilds from the per-workspace records. The list of projects lives in
`~/.asgard/studio/projects.json` (`ASGARD_STUDIO_STATE` relocates all three).

Changed files open in place: the inspector reads the file or its `git diff` through endpoints that
resolve every path with `realpath` and refuse anything outside the workspace root, including symlinks
that point out. `⌘K` searches tasks across projects, plus tickets, workspaces, skills, and screens.
The surface shares one night-and-gold token set with the map view and the memory dashboard, so the
three windows read as one product.

### Work board

The studio's **업무** screen is a work tracker in the shape the industry already agreed on — the
one Linear settled: a **workspace** holds teams, and teams hold tickets.

```
workspace ── team ── ticket          the team owns the numbering (NOR-12)
     │        └─ workflow states · cycles · triage inbox · labels
     ├─ project ── milestones        dated work that cuts across teams
     └─ initiative ── projects       the goal several projects serve
```

A **ticket belongs to exactly one team** (that is what makes its number unique) and to **at most
one project** (that is what makes progress countable). Teams are yours to create; a folder never
becomes one on its own. Bind one when you want a repo to own its numbering
(`asgard ticket team --new "Nordic" --key NOR` then `--bind`), and everything filed elsewhere lands
in the workspace's default team. A team can stand with no folder at all, because planning starts
before code exists. Status *names* are the team's to choose; the five *categories*
(backlog · unstarted · started · completed · canceled) are fixed, because that is what lets anyone
count "how many are open". Priority sinks *none* to the bottom. Numbers are issued once and never
reissued — `NOR-12` stays that ticket even after it is deleted, because it is the name people use
in conversation.

```bash
asgard ticket                                  # the whole workspace, folded into status columns
asgard ticket board --team NOR                 # narrowed to one team (`--team .` = this folder's)
asgard ticket new "..." -p 2 --project "결제 개편"
asgard ticket move NOR-12 in_review            # status changes carry their timestamps
asgard ticket team --new "디자인" --key DES      # a team with no repo behind it
asgard ticket project --new "결제 개편" --teams NOR,DES --target 2026-09-30
asgard ticket milestone "결제 개편" --new "베타"
asgard ticket cycle --new "7월 5주"             # closing one rolls unfinished work forward
asgard ticket triage                           # the inbox: accept, decline, or snooze
asgard ticket import                           # bring an old per-folder board in, losslessly
```

**The board is not tied to the folder you are standing in.** Every read covers the whole workspace,
so "what should I work on" has one answer no matter where the command was typed or where the window
was opened — the same board, from any repo and from none. Narrowing is explicit: `--team NOR` for
one team, `--team .` for the team bound to this folder.

**The agent tracks its own work.** The `ticket` tool is in front of every role on every turn, and
the bundled `asgard-tickets` skill carries the procedure: open a ticket before work that is more
than a one-liner, `start` it when you begin, `finish` it when the change is ready for review —
plus file (without starting) anything you found and are *not* doing now. The tool is reachable from
read-only roles too, because the role that finds a defect is the one that should be able to record
it. When a team turns **triage** on, agent-filed tickets land in an inbox instead of the human's
backlog — a backlog that fills itself is a backlog nobody reads.

Tickets and runs are linked in both directions: 이 티켓 실행 starts an `asgard run` task from the
ticket and stamps `task_id` on it, and when that task exits 0 the ticket moves to *in review* —
not *done*, since a zero exit code is not a human accepting the work.

The store is a dedicated SQLite at `<agent home>/studio/workspace.db` (`ASGARD_STUDIO_HOME`
relocates it), separate from `tasks.jsonl` (a 200-row rolling history) and `plans.json` (replaced
whole per revision) because tickets must not age out, must be queried by status and assignee, and
are written concurrently by three writers. Inside a repo the only thing left behind is
`.asgard/studio/team.json` — the binding that survives renaming or moving the folder. Unlike the
derived indexes, the store is canonical: a corrupt file is **reported, never recreated**. Reading
an untouched workspace creates nothing at all. Boards written by the older per-folder layout are
imported on request, keeping their numbers, relations, and comments, and leaving the original file
untouched.

### Surface gate

```bash
asgard freyja-gate            # judge the visual surfaces this change touched
asgard freyja-gate --json     # same, machine-readable
```

Named alongside `asgard craft` (micro-shape) and `asgard thor gate` (backend correctness), and it
carries the same ratchet: **inherited debt never blocks; only what this change made worse does.**
It writes no rules of its own — it calls the judge each Freyja engine already ships (today that is
engine 4's `slop_gate.mjs`) and reports, by name, every engine it could *not* measure, so a clean
result never quietly means "nothing was checked".

Two of engine 4's gates exist because of a measured failure: an agent named the engine, ran only its
artifact judge, skipped the design flow, and shipped a screen a human called AI slop on sight.
`A3` now requires the pre-emit self-critique to be recorded in the stamp with all six axes at 3 or
above — the flow's own rule says anything lower triggers a revision pass before emit, so shipping
below it is a rule violation the tool can see. `A4` fails a grid of same-class cards on equal
tracks, the welcome-screen fingerprint that started it. The SubagentStop gate hook runs all three.

## Agents (Einherjar)

One install can host many agents. An agent owns its **identity** and its **tier-1
memory**; the project owns the shared world (map, charter, manual, quest log) and
only declares who works there. Raising an agent is not reinstalling Asgard —
credentials, the project registry, and caches stay machine-level.

```bash
asgard agent list                          # every agent, plus built-ins not yet raised
asgard agent create qa --from loki \
  -d "adversarial QA — counterexamples, regressions"
asgard agent use qa                        # this machine's active agent
asgard -A qa memory add "…"                # or one command as that agent
```

Built-in Asgard agents (freyja, thor, mimir, eitri, loki, …) are selectable by
name and are raised on demand, seeded with their own identity. Your own agents
start from a blank identity file you write yourself.

Inside a project, place agents instead of switching them:

```bash
asgard agent bind qa                       # this project's default agent
asgard agent bind saga-doc --mode codex    # that mode's sessions run as this agent
asgard agent bind qa --role verifier       # a Trinity role runs as this agent
asgard agent where                         # who works here, and which declaration won
```

Binding different agents to different roles gives you an **agent swarm**: each
role runs on its own tier-1 memory, so the Verifier cannot read the Worker's
log. That separation is a filesystem boundary, not a prompt instruction — it is
what keeps the verdict independent. Placements are declared per project and
fail open: an agent name this machine does not have falls back to the default
and is reported by `asgard doctor`, so a repo shared with a teammate never
blocks their session.

Identity and placement reach all four modes — inline in the native loop, and via
the `agent-activate` hook in Claude Code, Cursor, and Codex. An agent with
nothing written in its identity file stays silent: prompts are byte-identical to
an install that never used this layer.

To run one agent on its own — a container, a second machine, a CI runner — hand
it a home instead of a name:

```bash
docker run -e ASGARD_HOME=/data -v agent-vol:/data …   # /data/memory is that agent's tier-1 memory
```

That volume *is* the agent: `/data/memory` behaves exactly like the default
memory, `/data/AGENT.md` is its identity, and the host's `~/.asgard` is never
touched. Asgard names it after the directory, so several containers stay
distinguishable in logs.

## Memory

Asgard has exactly two memory types: personal local Markdown/SQLite memory and
shared project memory. Approved project records are Git-canonical under
`.asgard/memory/records/`; exactly one configured engine is their replaceable search
index (Hindsight is the legacy-compatible default; Cognee, RedisVL, and others can be installed as adapters).
Project records pass provenance, importance,
secret, prompt-injection, and approval gates before retain. The generated
`asgard-memory` skill carries the registration schema, and `asgard memory
project-scan` / `project-sync` preview and commit important artifacts into the
active project backend. `asgard memory project-rehydrate` previews and replays canonical
records after a backend replacement. Backend changes are bound to machine-local trust,
approval IDs, plan IDs, and projection manifests.

Personal memory is a Markdown wiki and can be used directly as an Obsidian vault. To keep its
canonical files in a dedicated cloud or external folder, configure it once on each machine:

```bash
asgard memory path --set "/path/to/cloud/Asgard Memory"
asgard memory obsidian            # scaffold the vault config, rebuild maps/, and open it
asgard memory obsidian --refresh  # prepare and rebuild without opening
asgard memory path --reset        # restore ~/.asgard/memory
```

### Semantic search

Personal memory searches by meaning as well as by letters, on by default. A multilingual static
embedder (`potion-multilingual-128M`, no torch, no API, no network after the first fetch) joins
the lexical streams as a third rank-fusion input.

```bash
asgard memory semantic          # status: mode, model, dimensions
asgard memory semantic warmup   # fetch the model now instead of mid-search
asgard memory semantic off      # back to the lexical two-stream path
```

Measured on 40 pages / 80 paraphrase queries: hit@1 0.750 → 0.850, missed queries 11 → 2, no
regressions; Korean 0.787 → 0.894. The cost is a ~1.2s model load per process, and the first
run fetches roughly 1GB. Turning it off restores the previous behaviour exactly — stored pages
are untouched, and every path fails open to lexical search if the embedder cannot load.

Smaller static models were measured and rejected: `potion-base-8M` and `potion-retrieval-32M`
score *negative* discrimination on Korean (they rank an unrelated sentence closer than a related
one), so the load time they save is not buyable quality. An ollama embedding path was also
measured and not built — `nomic-embed-text` lost on both quality and latency.

`ASGARD_MEMORY_DIR` remains the session-level override. `maps/` is a derived table of contents
(by kind, recent, orphans and dead links) that lives outside the `index.md` injection budget and
is rebuilt whenever the canonical pages change. Obsidian must open the configured folder as a
vault once before its URI can focus `index.md`.

### Durability and sync

Canonical pages are text, so backups and sync move files, never a database. Archives carry a
digest manifest and are verified before a restore replaces anything; the pre-restore state is
always kept.

```bash
asgard memory backup                      # snapshot pages/ + archive/ + SCHEMA.md + log.md
asgard memory backup list | verify | restore | prune
asgard memory sync --set-remote <path> --transport dir   # shared folder, NAS, cloud folder
asgard memory sync --set-remote <git-url> --transport git
asgard memory sync --dry-run              # three-way plan before it writes
asgard memory sync --status
```

Sync compares a saved baseline against both sides, so a deletion is never resurrected and a new
page is never silently dropped. When both sides edited the same page it keeps yours, stores
theirs under `conflicts/`, and keeps reporting the conflict until a human resolves it. The
append-only `log.md` merges by union instead of conflicting.

### Self-evolution

```bash
asgard memory norn                # consolidate the wiki (LLM proposes, code decides)
asgard memory pattern             # learn observations about you from past turns
asgard memory ask "<question>"    # answer from personal + episodic + project memory
asgard memory provider --set ollama:gemma4:12b   # who curates personal memory
asgard memory project-evolve      # stale, duplicate, contradictory project records
asgard memory project-learn       # Hindsight observations + living project mental models
```

`pattern` derives explicit and deductive observations from conversation turns, honcho-style.
Every explicit claim must be lexically grounded in the turn it cites, deductive ones need two
turns, and confidence comes from evidence count rather than the model's own claim; what survives
becomes wiki pages plus a compact peer card. `project-evolve` applies the same discipline to the
second tier and stages its deltas for approval instead of writing them.

By default the main provider curates personal memory. `asgard memory provider` points curation at
a different one (a local model for private data, a stronger one for better consolidation);
`ASGARD_MEMORY_MANAGER` overrides it for one session. Without any provider, storing, searching,
and recall keep working — only the LLM passes pause, and `asgard doctor` says so.

`asgard memory project-reflect` asks the backend's LLM first. When the server has none — a bank
running index-only, an expired gateway key — the local provider answers instead, using the
Git-canonical records as evidence, and the output always names which path answered. Set
`[project_memory].reflect` to `backend` or `local` to pin it.

Use `asgard memory connect` to configure a backend and `asgard doctor` to verify its binding and readiness.

### Learned skills

Quests that failed before they passed are the lessons worth keeping. At the end of every turn
Asgard mines the quest log for them — deterministically, no model involved — and writes each one
as an evidence card: the failure signature, the criteria, the command that finally exited 0.

```bash
asgard evolve list                # drafts waiting on you
asgard evolve approve <id>        # install one — the next dispatch can reach it, no restart
asgard evolve curate              # which learned skills have gone quiet
asgard evolve archive <name>      # put one away (asgard evolve restore <name> brings it back)
asgard evolve bench <name> --cmd "<command>" --metric wall   # A/B it with the skill off and on
```

How far it goes on its own is one setting, `[evolution].autonomy`, or `ASGARD_EVOLVE_AUTONOMY`:

| grade | what installs itself |
| --- | --- |
| `off` | nothing — every draft waits for `asgard evolve approve` |
| `safe` (default) | lessons mined from the quest log |
| `full` | those plus lessons mined from your own corrections |

Autonomy presses the same approval gate rather than bypassing it, so a draft still has to name a
trigger a future task could match, must not collide with an existing skill, and never carries an
environment-dependent failure. What went in on its own says so in its approval receipt, and
`asgard evolve archive` takes it back out. Learned skills reach workers and delivery specialists;
the Verifier and Loki never see them, at any grade.
