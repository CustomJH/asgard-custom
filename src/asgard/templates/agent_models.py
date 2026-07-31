"""Role-model defaults and user overrides for hosted coding-agent clients."""

from __future__ import annotations

from ..settings import load_global, load_project

AGENT_MODEL_DEFAULTS = {
    # 사고·구현·판정하는 손은 세션 모델을 물려받는다(inherit) — thinker·verifier 와 Write 권한을
    # 가진 전부(worker·planner·thor-lead·thor·eitri·freyja). 아래로 고정하면 위임된 손이 품질 하한이 되고
    # (숨은 caller 추적처럼 코디네이터가 하는 일을 못 한다), 위로 고정하면 가벼운 세션에서도 비싼
    # 손이 불려 나온다. 읽기 전용 정찰·안내(loki·ullr·mimir)만 의도된 저비용 고정으로 남긴다.
    # effort 는 모델과 독립 축이라 역할별 선언을 그대로 유지한다.
    "claude-code": {
        "thinker": {"model": "inherit", "effort": "high"},
        "worker": {"model": "inherit", "effort": "high"},
        "planner": {"model": "inherit", "effort": "high"},
        "verifier": {"model": "inherit", "effort": "high"},
        "freyja": {"model": "inherit", "effort": "high"},
        "thor-lead": {"model": "inherit", "effort": "high"},
        "thor": {"model": "inherit", "effort": "high"},
        "eitri": {"model": "inherit", "effort": "high"},
        "loki": {"model": "opus", "effort": "low"},
        "ullr": {"model": "haiku"},
        "mimir": {"model": "sonnet", "effort": "high"},
    },
    "cursor": {
        "thinker": {"model": "claude-fable-5-thinking-xhigh"},
        "worker": {"model": "gpt-5.6-terra-medium"},
        "planner": {"model": "gpt-5.6-terra-medium"},
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
        "planner": {"model": "gpt-5.6-terra", "effort": "medium"},
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
