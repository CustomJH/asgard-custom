"""Codex templates: project config.toml (commented overrides + an active PreToolUse git-guard hook,
Python — Codex shares Claude Code's stdin schema) and native command rules (Starlark, node/python-free
defense-in-depth)."""

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

# Canon enforcement (CUS-93) — deterministic PreToolUse guard. Same stdin schema as Claude Code, so
# the guard is the same git-guard.py. Trust once via the /hooks CLI (or --dangerously-bypass-hook-trust).
[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = 'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/git-guard.py"'

# Canon Law 9 (CUS-97) — soft 3-strike loop tracker. Codex PostToolUse carries tool_name + tool_response
# (Claude's schema), so it runs the SAME failure-tracker.py and shares the .asgard/ state cross-tool.
[[hooks.PostToolUse]]
matcher = ".*"

[[hooks.PostToolUse.hooks]]
type = "command"
command = 'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/failure-tracker.py"'
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
    return _CODEX_CONFIG


def codex_rules() -> str:
    return _CODEX_RULES
