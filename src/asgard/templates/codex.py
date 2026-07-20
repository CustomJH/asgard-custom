"""Codex project config, custom-agent adapters, and native command rules."""

import json

from ..platform import hook_python
from .roles import role_document

_CODEX_CONFIG = """\
# Codex project config — overrides ~/.codex/config.toml, loaded only in trusted projects.
# Docs: https://developers.openai.com/codex/config-reference · https://developers.openai.com/codex/hooks
#
# model = "<your-model>"
# approval_policy = "on-request"    # untrusted | on-request | never
# sandbox_mode = "workspace-write"  # read-only | workspace-write | danger-full-access
#
# Project MCP servers:
# [mcp_servers.example]
# command = "npx"
# args = ["-y", "@some/mcp-server"]

# Asgard lead roles may create one child squad; their children cannot delegate again.
[agents]
max_depth = 2

# Canon enforcement — deterministic PreToolUse guard. Same stdin schema as Claude Code, so
# the guard is the same git-guard.py. Trust once via the /hooks CLI (or --dangerously-bypass-hook-trust).
[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/git-guard.py"'

[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/release-guard.py"'

# Canon Law 9 — soft 3-strike loop tracker. Codex PostToolUse carries tool_name + tool_response
# (Claude's schema), so it runs the SAME failure-tracker.py and shares the .asgard/ state cross-tool.
[[hooks.PostToolUse]]
matcher = ".*"

[[hooks.PostToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/failure-tracker.py"'

[[hooks.PostToolUse]]
matcher = "^(apply_patch|Write|Edit)$"

[[hooks.PostToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/write-sentinel.py" codex'

# Trinity role receipts and completion gate. Codex exposes custom agents as Agent tool calls.
[[hooks.PreToolUse]]
matcher = "^Agent$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/subagent-gate.py" codex'

[[hooks.SubagentStart]]
matcher = "^asgard-(thinker|worker|verifier)$"

[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/subagent-gate.py" codex'

[[hooks.SubagentStop]]
matcher = "^asgard-(thinker|worker|verifier)$"

[[hooks.SubagentStop.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/subagent-gate.py" codex'

[[hooks.Stop]]

[[hooks.Stop.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/verifier-gate.py" codex'
"""

_CODEX_RULES = """\
# Asgard Canon — Codex command-execution rules (Law 3/6). Trust-gated; most-restrictive wins.
# Docs: https://developers.openai.com/codex/rules  ·  prefix_rule matches the command's leading tokens.
prefix_rule(pattern=["git", "push", "--force"], decision="forbidden", justification="Asgard Canon Law 3/6 — force-push needs Odin's explicit consent")
prefix_rule(pattern=["git", "push", "-f"], decision="forbidden", justification="Asgard Canon Law 3/6 — force-push")
prefix_rule(pattern=["git", "reset", "--hard"], decision="prompt", justification="Asgard Canon Law 3/6 — irreversible; confirm first")
prefix_rule(pattern=["git", "clean", "-f"], decision="prompt", justification="Asgard Canon Law 3/6 — deletes untracked files")
prefix_rule(pattern=["git", "clean", "-fd"], decision="prompt", justification="Asgard Canon Law 3/6 — deletes untracked files/dirs")
prefix_rule(pattern=["git", "branch", "-D"], decision="prompt", justification="Asgard Canon Law 3/6 — force-deletes a branch")
prefix_rule(pattern=["git", "rebase"], decision="prompt", justification="Asgard Canon Law 3/6 — history rewrite")
"""


def codex_config() -> str:
    # 인터프리터만 플랫폼 분기 — $(git rev-parse) 명령치환은 Codex 훅 셸 계약을 따른다.
    return _CODEX_CONFIG.format(py=hook_python())


def codex_agent(content: str) -> str:
    """Adapt one canonical role file to Codex's standalone custom-agent TOML."""
    metadata, body = role_document(content)
    lines = [
        f"name = {json.dumps(str(metadata['name']), ensure_ascii=False)}",
        f"description = {json.dumps(str(metadata['description']), ensure_ascii=False)}",
    ]
    if "Write" not in str(metadata.get("tools") or ""):
        lines.append('sandbox_mode = "read-only"')
    if "'''" in body:
        lines.append("developer_instructions = " + json.dumps(body, ensure_ascii=False))
    else:
        lines.append("developer_instructions = '''\n" + body.rstrip() + "\n'''")
    return "\n".join(lines) + "\n"


def codex_rules() -> str:
    return _CODEX_RULES
