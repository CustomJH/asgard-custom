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

Installs `asgard` to `~/.local/bin`. Then:

```bash
asgard doctor    # verify
asgard --help
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
asgard skills show review-animations --resource STANDARDS.md
asgard skills assign ui-ux-pro-max --agent freyja
asgard skills disable ui-ux-pro-max
```

A local resource plugin is installed with `asgard plugins install <path>`. Asgard ships
`ui-ux-pro-max` for Freyja, including its searchable data and Python helper, so users do not need a
separate Claude Marketplace or Codex install. It also ships a Python port of Google Labs Code
`design.md` lint/spec as `design-md-review` for Freyja design-system audits, plus Emil Kowalski's
design-engineering and motion skills. These skills are available to Freyja but none is forced on
every task; the model selects from their descriptions. A plugin contains `plugin.json` and declared `skills/<name>/`
directories:

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
asgard memory obsidian
asgard memory path --reset  # restore ~/.asgard/memory
```

`ASGARD_MEMORY_DIR` remains the session-level override. Obsidian must open the configured folder as
a vault once before its URI can focus `index.md`. Avoid writing from multiple machines at the same
time; cloud storage synchronizes the files but does not provide a cross-machine lock.

Use `asgard memory connect` to configure a backend and `asgard doctor` to verify its binding and readiness.
