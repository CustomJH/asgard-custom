"""Tool catalog diagnostics for the canonical Asgard Tool Kernel."""

import json
import sys

from ..agent.tool_kernel import ROLE_CAPABILITIES, ToolContext, build_session_registry, cc_tools_for_role

_CLI_ROLES = ("thinker", "worker", "verifier", "freyja", "thor", "eitri", "loki", "ullr")


def run_tools_list(role: str, json_out: bool = False) -> int:
    if role not in _CLI_ROLES:
        print(json.dumps({"error": f"role must be one of: {', '.join(_CLI_ROLES)}"}), file=sys.stderr)
        return 2
    registry = build_session_registry()
    data = {
        "role": role,
        "capabilities": sorted(ROLE_CAPABILITIES[role]),
        "native": [spec.name for spec in registry.available_specs(ToolContext(root=".", role=role))],
        "claude_code": list(cc_tools_for_role(role)),
    }
    if json_out:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"role: {role}")
        print("capabilities: " + ", ".join(data["capabilities"]))
        print("native: " + ", ".join(data["native"]))
        print("claude-code: " + ", ".join(data["claude_code"]))
    return 0
