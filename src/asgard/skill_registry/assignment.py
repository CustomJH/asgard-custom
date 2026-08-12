"""배정 쓰기 — 프로젝트 설정에 결속·해제와 사용 여부를 남긴다."""

from __future__ import annotations

from ..settings import load_project, save_project
from .builtin import _builtin_plugins
from .bundles import bundled_plugins, installed_plugins
from .catalog import show_skill
from .manifest import _ASSIGNABLE_AGENTS


def _compatible_agents(name: str) -> set[str]:
    for plugin in _builtin_plugins().values():
        if any(skill == name for skill, _ in plugin["skills"]):
            return set(plugin.get("agents") or _ASSIGNABLE_AGENTS)
    for plugin in [*bundled_plugins().values(), *installed_plugins().values()]:
        if name not in plugin["skills"]:
            continue
        return set(plugin["routing"][name]["agents"])
    return set()


def assign_skill(root: str, name: str, agent: str, *, assigned: bool) -> None:
    """Set one project-local assignment override; global defaults remain untouched."""
    if agent not in _ASSIGNABLE_AGENTS:
        raise ValueError(f"invalid assignable agent: {agent}")
    if show_skill(root, name) is None:
        raise ValueError(f"skill not found: {name}")
    compatible = _compatible_agents(name)
    if assigned and agent not in compatible and "any" not in compatible:
        raise ValueError(f"skill is not compatible with agent: {name} -> {agent}")
    config = dict(load_project(root).get("skills") or {})
    assign_config = config.get("assign")
    unassign_config = config.get("unassign")
    raw_positive = assign_config if isinstance(assign_config, dict) else {}
    raw_negative = unassign_config if isinstance(unassign_config, dict) else {}
    positive = {str(key): list(value) for key, value in raw_positive.items() if isinstance(value, list)}
    negative = {str(key): list(value) for key, value in raw_negative.items() if isinstance(value, list)}
    target, opposite = (positive, negative) if assigned else (negative, positive)
    target[agent] = sorted({*target.get(agent, []), name})
    if agent in opposite:
        opposite[agent] = [item for item in opposite[agent] if item != name]
        if not opposite[agent]:
            opposite.pop(agent)
    config["assign"], config["unassign"] = positive, negative
    save_project(root, "skills", config)


def set_skill_enabled(root: str, name: str, *, enabled: bool) -> None:
    if show_skill(root, name) is None:
        raise ValueError(f"skill not found: {name}")
    config = dict(load_project(root).get("skills") or {})
    disabled = {str(item) for item in config.get("disabled", [])}
    if enabled:
        disabled.discard(name)
    else:
        disabled.add(name)
    config["disabled"] = sorted(disabled)
    save_project(root, "skills", config)
