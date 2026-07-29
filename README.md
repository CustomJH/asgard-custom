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
asgard desktop   # native app when installed, browser fallback otherwise
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
asgard map check                            # read-only drift and area-map validation
asgard map context --query "worker routing" # inspect bounded agent context
```

The team-shared map lives in `.asgard/map/`. `PROJECT.md` is a compact, deterministic
orientation map built from paths, manifests, verification commands, public symbols, and
local import relations observed on disk; Asgard owns and regenerates it. Human/agent-authored
area maps such as `cli.md` or `frontend.md` are bounded fog-of-war notes and are never
overwritten. Main requests and subagents receive only task-relevant map entries within a
fixed context budget. Each start refreshes structural drift, and quest verification refreshes
again before computing the Verifier diff hash, so automatic map changes are covered by the
same PASS instead of creating an unverified post-close write. `asgard setup map` remains a
backward-compatible alias.

Maps are navigation hints, not completion evidence. Thinker/Worker must still read the
definitions and usages that a plan depends on, while `asgard doctor` checks managed-map
drift plus stale, malformed, oversized, or unsafe entries in manual area maps.

## Desktop

```bash
asgard desktop            # native app when installed, browser fallback otherwise
asgard desktop --browser  # skip the native shell
```

A loopback workspace over the same ownership the CLI uses: `asgard run` executes the work,
`settings.py` persists configuration, and the central registry stays the catalog source of truth.
Tasks are **kept on disk** under `<project>/.asgard/desktop/tasks.jsonl`, so recent work and its
artifacts survive closing the window; a task that was still running when the process died is
re-read as `interrupted` rather than reported as live. Tasks belong to the project they ran in —
switching the open project swaps the history with it, and the machine-level list of projects lives
in `~/.asgard/desktop/projects.json` (`ASGARD_DESKTOP_HOME` relocates it).

Changed files open in place: the inspector reads the file or its `git diff` through endpoints that
resolve every path with `realpath` and refuse anything outside the project root, including symlinks
that point out. `⌘K` searches tasks, projects, skills, and screens. The surface shares one
night-and-gold token set with `asgard map` and the memory dashboard, so the three windows read as
one product.

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
