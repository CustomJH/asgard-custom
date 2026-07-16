# Asgard

Make anything, your way — a portable setup system, shipped as a self-contained binary (no Node, Bun, or git required to run it).

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
