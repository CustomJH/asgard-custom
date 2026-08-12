"""배정 정책 읽기 — 어떤 스킬이 어느 역할에게 열려 있는지 판정한다."""

from __future__ import annotations

from ..settings import section
from ..skill_bank import learned_skills
from .builtin import _builtin_plugins
from .bundles import bundled_plugins, installed_plugins
from .manifest import _ASSIGNABLE_AGENTS


def _skill_policy(root: str) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    config = section("skills", root)

    def names(value) -> set[str]:
        return {str(item) for item in value} if isinstance(value, list) else set()

    def mapping(value) -> dict[str, set[str]]:
        return {str(agent): names(items) for agent, items in value.items()} if isinstance(value, dict) else {}

    return names(config.get("disabled")), mapping(config.get("assign")), mapping(config.get("unassign"))


def _assigned(skill: str, agent: str, defaults: tuple[str, ...], policy) -> bool:
    disabled, assigned, unassigned = policy
    if skill in disabled or skill in unassigned.get(agent, set()):
        return False
    return agent in defaults or "any" in defaults or skill in assigned.get(agent, set())


def _skill_routes(root: str) -> dict[str, tuple[tuple[str, ...], set[str]]]:
    """Return assignment metadata without enumerating every role's canonical bodies."""
    routes: dict[str, tuple[tuple[str, ...], set[str]]] = {}
    core_contracts = {"asgard-freyja", "asgard-thor", "asgard-eitri", "asgard-mimir"}
    for plugin in _builtin_plugins().values():
        defaults = tuple(plugin.get("agents") or ())
        compatible = set(defaults or _ASSIGNABLE_AGENTS)
        for name, _ in plugin["skills"]:
            if name not in core_contracts:
                routes[name] = defaults, compatible
    for plugin in [*bundled_plugins().values(), *installed_plugins().values()]:
        for name in plugin["skills"]:
            route = plugin["routing"][name]
            routes.setdefault(name, (tuple(route["defaults"]), set(route["agents"])))
    for name, skill in learned_skills(root).items():
        default = str(skill.get("agent") or "worker")
        routes.setdefault(name, ((default,), {default}))
    return routes
