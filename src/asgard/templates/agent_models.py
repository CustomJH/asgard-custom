"""Role-model defaults and user overrides for hosted coding-agent clients."""

from __future__ import annotations

from ..settings import load_global, load_project

AGENT_MODEL_DEFAULTS = {
    "claude-code": {
        "thinker": {"model": "fable", "effort": "high"},
        "worker": {"model": "sonnet", "effort": "high"},
        "verifier": {"model": "opus", "effort": "high"},
        "freyja": {"model": "sonnet", "effort": "high"},
        "thor-lead": {"model": "fable", "effort": "high"},
        "thor": {"model": "sonnet", "effort": "high"},
        "eitri": {"model": "sonnet", "effort": "high"},
        "loki": {"model": "opus", "effort": "low"},
        "ullr": {"model": "haiku"},
        "mimir": {"model": "sonnet", "effort": "high"},
    },
    "cursor": {
        "thinker": {"model": "claude-fable-5-thinking-xhigh"},
        "worker": {"model": "gpt-5.6-terra-medium"},
        "verifier": {"model": "claude-opus-4-8-thinking-high"},
        "freyja": {"model": "claude-sonnet-5-thinking-high"},
        "thor-lead": {"model": "gpt-5.6-sol-high"},
        "thor": {"model": "gpt-5.6-terra-high"},
        "eitri": {"model": "gpt-5.6-terra-high"},
        "loki": {"model": "claude-opus-4-8-thinking-high"},
        "ullr": {"model": "gpt-5.6-terra-low"},
        "mimir": {"model": "gpt-5.6-terra-medium"},
    },
    "codex": {
        "thinker": {"model": "gpt-5.6-sol", "effort": "xhigh"},
        "worker": {"model": "gpt-5.6-terra", "effort": "medium"},
        "verifier": {"model": "gpt-5.6-sol", "effort": "high"},
        "freyja": {"model": "gpt-5.6-sol", "effort": "high"},
        "thor-lead": {"model": "gpt-5.6-sol", "effort": "high"},
        "thor": {"model": "gpt-5.6-terra", "effort": "high"},
        "eitri": {"model": "gpt-5.6-terra", "effort": "high"},
        "loki": {"model": "gpt-5.6-sol", "effort": "high"},
        "ullr": {"model": "gpt-5.6-terra", "effort": "low"},
        "mimir": {"model": "gpt-5.6-terra", "effort": "medium"},
    },
}


def agent_model(root: str, host: str, role: str) -> dict[str, str]:
    """Resolve built-in default < global override < project override."""
    role = role.removeprefix("asgard-")
    resolved = dict(AGENT_MODEL_DEFAULTS[host][role])
    for config in (load_global(), load_project(root)):
        hosts = config.get("agent_models")
        host_models = hosts.get(host) if isinstance(hosts, dict) else None
        override = host_models.get(role) if isinstance(host_models, dict) else None
        if isinstance(override, str) and override.strip():
            resolved["model"] = override.strip()
        elif isinstance(override, dict):
            for key in ("model", "effort"):
                value = override.get(key)
                if isinstance(value, str) and value.strip():
                    resolved[key] = value.strip()
    return resolved
