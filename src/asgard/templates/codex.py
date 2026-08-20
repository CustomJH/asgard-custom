"""Codex project config, custom-agent adapters, and native command rules."""

import json

from ..platform import hook_python, preflight_command
from .agent_models import agent_model
from .roles import role_document

# Codex 훅은 저장소 뿌리를 이 명령치환으로 찾는다 — 배선 문법이라 경로 계산이 아니다.
_CODEX_HOOKS = "$(git rev-parse --show-toplevel)/.codex/hooks"

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

# Memory v3 — session snapshot, prompt-specific recall, Thinker-only context, verified turn sync.
# Lagom (output restraint) and the Charter north star ride the same events — one contract per mode.
[[hooks.SessionStart]]

# 환경 프리플라이트 — 아래 줄들이 부르는 인터프리터가 이 기계에 있는지부터 본다. 파이썬 없이
# 도는 sh 라서, 없을 때 말할 수 있는 유일한 자리가 여기다 (templates/env.py).
[[hooks.SessionStart.hooks]]
type = "command"
command = '{preflight}'

[[hooks.SessionStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/lagom-activate.py" codex'

[[hooks.SessionStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/memory-activate.py" codex'

[[hooks.SessionStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/charter-activate.py" codex'

[[hooks.SessionStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/manual-activate.py" codex'

[[hooks.SessionStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/agent-activate.py" codex'

[[hooks.SessionStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/map-activate.py" codex'

[[hooks.UserPromptSubmit]]

# Spend ceiling — judged before the turn starts. The heaviest sessions never spawn a subagent,
# so the main lane needs its own checkpoint (see budget_guard.py for the measurement).
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/budget-guard.py" codex prompt'

# Canon 8 — an unattended session is detected from permission_mode, which only a hook can see.
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/unattended-context.py" codex'

[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/lagom-tracker.py" codex'

[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/memory-activate.py" codex'

[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/charter-activate.py" codex'

[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/manual-activate.py" codex'

[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/agent-activate.py" codex'

[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/map-activate.py" codex'

# Work shape and the delivery surface this request belongs to. The judgement is deterministic and
# already existed; until now only the native loop and a hand-typed CLI call could reach it.
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/scope-activate.py" codex'

# Dispatch-ledger mailbox — mail another session or a `siege serve` process addressed to this one.
# An empty mailbox costs one read-only sqlite query; the CLI is spawned only when mail is waiting.
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/siege-inbox.py" codex'

# Tutor, forward half — before touching the same place again, put the questions still open there
# in front of the human. User-facing only: a model that reads them answers them on the user's behalf.
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/tutor-note.py" codex brief'

# Canon enforcement — deterministic PreToolUse guard. Same stdin schema as Claude Code, so
# the guard is the same git-guard.py. Trust once via the /hooks CLI (or --dangerously-bypass-hook-trust).
[[hooks.PreToolUse]]
matcher = "^Bash$"

# Canon Law 4, read half — a shell that dumps credentials (cat .env, env, keychain reads) puts them
# in the transcript, and the transcript is re-sent to the model provider on every later turn.
[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/secret-guard.py" codex'

[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/git-guard.py"'

[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/release-guard.py"'

# Control-surface protection. PreToolUse carries no agent identity here, so this lane enforces only
# the identity-free rules (writes into .codex/.claude/.asgard, paths outside the repo); read-only
# roles are held by each agent's own `sandbox_mode = "read-only"`.
[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/readonly-guard.py" codex'

[[hooks.PreToolUse]]
matcher = "^(apply_patch|Write|Edit)$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/readonly-guard.py" codex'

# Canon Law 4 — a secret is blocked at the moment it would be written to a file.
[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/secret-guard.py" codex'

# Canon Law 4, read half — credential stores are judged by name, because by the time their content
# could be inspected they have already been read. Templates (.env.example) stay exempt.
[[hooks.PreToolUse]]
matcher = "^(Read|Grep|Glob)$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/secret-guard.py" codex'

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

# tutor tip — the mid-work reach point. UserPromptSubmit/Stop only see the turn boundaries;
# the stretch where review actually thins out is between them. Counts writes itself and only
# shells out every Nth one, so the per-call cost here is a file read.
[[hooks.PostToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/tutor-note.py" codex tip'

# Trinity role receipts and completion gate. Codex exposes custom agents as Agent tool calls.
[[hooks.SubagentStart]]

[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/lagom-subagent.py" codex'

[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/charter-activate.py" codex'

[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/manual-activate.py" codex'

[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/agent-activate.py" codex'

[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/map-activate.py" codex'

# The dispatched role's planning discipline. The hook excludes the judging surfaces itself.
[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/scope-activate.py" codex'

# Verifier input — the harness-observed record of what ran since the last verdict. No matcher here:
# this block has none, so the hook checks the agent name itself and exits for everyone else.
[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/verifier-context.py" codex'

# What a dispatched agent needs to reach the ledger it is already on: its own address, where to leave
# a question it cannot settle, and how to report a failure. Without the last one every attempt is
# recorded as succeeded. The hook excludes the Verifier, whose seat here is verifier-context.
[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/dispatch-context.py" codex'

[[hooks.PreToolUse]]
matcher = "^Agent$"

# Judged before the spawn — SubagentStop is after the money is already spent.
[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/budget-guard.py" codex task'

[[hooks.PreToolUse.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/subagent-gate.py" codex'

# 역할 셋 매처를 안 건다 — SubagentStop 과 같은 이유다. 단위를 받는 손은 워커만이 아니라 딜리버리 전문가(thor·thor-lead·freyja·eitri)도이고, 시작 훅이 안 불리면 그 단위는 완료 영수증이 없어 아무도 안 돈 것으로 읽혀 판정자 배차가 막힌다 (26-08-20 실측: thor 로 띄운 단위 둘이 배차 영수증만 남고 완료 영수증 0건). 게이트가 스스로 agent_type 을 걸러 모르는 종류는 fail-open 으로 빠지므로, 목록을 배선에 손으로 적을 이유가 없다.
[[hooks.SubagentStart]]

[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/subagent-gate.py" codex'

[[hooks.SubagentStart]]
matcher = "^asgard-thinker$"

[[hooks.SubagentStart.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/memory-activate.py" codex'

# Unmatched: role discipline covers the three roles, but closing the siege ledger row covers every
# agent that was called — a matcher would leave specialists standing as "still running" forever.
[[hooks.SubagentStop]]

[[hooks.SubagentStop.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/subagent-gate.py" codex'

# Micro-shape ratchet — unmatched, because the discipline follows the writing, not the role.
[[hooks.SubagentStop]]

[[hooks.SubagentStop.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/craft-gate.py" codex'

# Code style the repository itself declared — the rules live in checkstyle.xml / eslint.config.js,
# this hook only holds the files this session wrote to them. No declaration, no child process.
[[hooks.SubagentStop]]

[[hooks.SubagentStop.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/style-gate.py" codex'

[[hooks.Stop]]

[[hooks.Stop.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/verifier-gate.py" codex'

[[hooks.Stop.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/style-gate.py" codex'

[[hooks.Stop.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/memory-activate.py" codex'

[[hooks.Stop.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/map-activate.py" codex'

# Tutor — hand this turn's code back to the human as questions. Never blocks (health-grade).
[[hooks.Stop.hooks]]
type = "command"
command = '{py} "$(git rev-parse --show-toplevel)/.codex/hooks/tutor-note.py" codex'
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
    return _CODEX_CONFIG.format(
        py=hook_python(_CODEX_HOOKS),
        preflight=preflight_command(_CODEX_HOOKS, "codex"),
    )


def codex_agent(content: str, root: str) -> str:
    """Adapt one canonical role file to Codex's standalone custom-agent TOML."""
    metadata, body = role_document(content)
    selected = agent_model(root, "codex", metadata["name"])
    lines = [
        f"name = {json.dumps(str(metadata['name']), ensure_ascii=False)}",
        f"description = {json.dumps(str(metadata['description']), ensure_ascii=False)}",
        f"model = {json.dumps(selected['model'])}",
        f"model_reasoning_effort = {json.dumps(selected['effort'])}",
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
