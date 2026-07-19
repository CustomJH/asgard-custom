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

Routing can be declared centrally under `plugin.json`'s `routing` object, or with the legacy
`triggers`, `agent` (default assignment), and optional `agents` fields in frontmatter. Resource
files are copied intact and text references are available through `asgard skills show --resource`.
Only Python entrypoints explicitly listed in the manifest can run, through
`asgard skills run <name> ...`; arbitrary hooks and shell commands are never registered.

## Project Map

```bash
asgard setup map                 # inspect the current project and draw/refresh the map
asgard setup map --check         # read-only drift check (CI-friendly)
asgard setup map --dry-run       # preview
```

The team-shared map lives in `.asgard/map/`. `PROJECT.md` is a compact, deterministic
orientation map built only from paths and manifests observed on disk; Asgard owns and
regenerates it. Human/agent-authored area maps such as `cli.md` or `frontend.md` are
fog-of-war notes and are never overwritten. In a mapped project, quest verification
refreshes `PROJECT.md` before computing the Verifier diff hash, so automatic map changes
are covered by the same PASS instead of creating an unverified post-close write.

Maps are navigation hints, not completion evidence. Thinker/Worker must still read the
definitions and usages that a plan depends on, while `asgard doctor` checks managed-map
drift and ghost paths in manual area maps.

## Memory

Asgard has exactly two memory types: personal local Markdown/SQLite memory and
a shared project memory backed by exactly one configured engine (Hindsight is the
legacy-compatible default; Cognee, RedisVL, and others can be installed as adapters).
Project records pass provenance, importance,
secret, prompt-injection, and approval gates before retain. The generated
`asgard-memory` skill carries the registration schema, and `asgard memory
project-scan` / `project-sync` preview and commit important artifacts into the
active project backend. Backend changes are bound to machine-local trust,
approval IDs, plan IDs, and projection manifests.

Use `asgard memory connect` to configure a backend and `asgard doctor` to verify its binding and readiness.
