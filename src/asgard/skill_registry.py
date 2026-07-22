"""Asgard-owned skill/plugin catalog and progressive skill loader.

Clients only receive discovery metadata and thin loaders.  Policy bodies stay here so Claude
Code, Cursor, Codex, and the native Heimdall loop share one source of truth.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from .settings import global_dir, load_project, save_project, section
from .skill_bank import learned_skills, record_use, resolve_learned

_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_PLUGIN_SCHEMA = 1
_PLUGIN_CAP = 6
_PLUGIN_FILE_CAP = 4_096
_PLUGIN_BYTE_CAP = 64 * 1024 * 1024
_RESOLVED_BODY_BUDGET = 16_000
_BUNDLED_PLUGINS_DIR = Path(__file__).with_name("assets") / "skill_plugins"
_ASSIGNABLE_AGENTS = frozenset(("worker", "freyja", "thor", "thor-lead", "eitri", "mimir"))


def _description(text: str) -> str:
    match = re.search(r"^description:\s*(.+)$", text.split("---", 2)[1], re.M)
    return match.group(1).strip() if match else ""


def _implicit(text: str) -> bool:
    """Whether a skill may enter model discovery context (Agent Skills convention)."""
    if not text.startswith("---"):
        return True
    match = re.search(r"^disable-model-invocation:\s*(.+)$", text.split("---", 2)[1], re.M)
    return not match or match.group(1).strip().lower() not in ("true", "yes", "1", "on")


def _file_skill(text: str) -> tuple[dict[str, str], str] | None:
    """Parse standard SKILL.md metadata; routing may live in plugin.json."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return (meta, parts[2].lstrip()) if meta.get("name") else None


def _items(value) -> list[str]:
    raw = value if isinstance(value, list) else str(value or "").split(",")
    return [str(item).strip() for item in raw if str(item).strip()]


def _builtin_plugins() -> dict[str, dict]:
    """Built-ins are imported lazily; several skill bodies are intentionally large."""
    from .templates import BRIDGE_SKILL_MD, SEAL_SKILL_MD, SELFTEST_MD
    from .templates.eitri import EITRI_SKILLS
    from .templates.freyja import FREYJA_SKILLS, freyja_core_skill
    from .templates.lagom import LAGOM_SKILLS
    from .templates.memory import MEMORY_SKILL_MD
    from .templates.mimir import MIMIR_SKILLS, mimir_core_skill
    from .templates.thor import THOR_SKILLS, eitri_core_skill, thor_core_skill
    from .templates.worker import WORKER_SKILLS

    return {
        "asgard-core": {
            "description": "Asgard bridge, self-test, seal, and memory contracts",
            "skills": [
                ("asgard-provider", BRIDGE_SKILL_MD),
                ("asgard-test", SELFTEST_MD),
                ("asgard-seal", SEAL_SKILL_MD),
                ("asgard-memory", MEMORY_SKILL_MD),
            ],
        },
        "worker": {
            "description": "Common Worker debugging and testing policy",
            "skills": WORKER_SKILLS,
            "agents": ("worker",),
            "resolver": "worker",
        },
        "freyja": {
            "description": "Freyja UI/UX and frontend delivery contract",
            "skills": [("asgard-freyja", freyja_core_skill()), *FREYJA_SKILLS],
            "agents": ("freyja",),
            "resolver": "freyja",
        },
        "thor": {
            "description": "Backend, data, API, and runtime policy",
            "skills": [("asgard-thor", thor_core_skill()), *THOR_SKILLS],
            "agents": ("thor", "thor-lead"),
            "resolver": "thor",
        },
        "eitri": {
            "description": "Build, CI, packaging, and release automation",
            "skills": [("asgard-eitri", eitri_core_skill()), *EITRI_SKILLS],
            "agents": ("eitri",),
            "resolver": "eitri",
        },
        "mimir": {
            "description": "Code walkthrough and onboarding policy",
            "skills": [("asgard-mimir", mimir_core_skill()), *MIMIR_SKILLS],
            "agents": ("mimir",),
            "resolver": "mimir",
        },
        "lagom": {"description": "Lagom review, debt, and compression modes", "skills": LAGOM_SKILLS},
    }


def _plugins_dir() -> str:
    return os.path.join(global_dir(), "plugins")


def _safe_tree(root: str) -> None:
    """Reject links, special files, and unbounded resource bundles before copying or running."""
    count = total = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            path = os.path.join(current, name)
            if os.path.islink(path):
                raise ValueError(f"plugin resources cannot contain symlinks: {os.path.relpath(path, root)}")
        for name in files:
            path = os.path.join(current, name)
            if not os.path.isfile(path):
                raise ValueError(f"plugin resource must be a regular file: {os.path.relpath(path, root)}")
            count += 1
            total += os.path.getsize(path)
            if count > _PLUGIN_FILE_CAP or total > _PLUGIN_BYTE_CAP:
                raise ValueError("plugin resource bundle exceeds safety cap")


def _entrypoints(manifest: dict, skills: list[str]) -> dict[str, str]:
    raw = manifest.get("entrypoints") or {}
    if not isinstance(raw, dict):
        raise ValueError("plugin entrypoints must be an object")
    result: dict[str, str] = {}
    for skill, entrypoint in raw.items():
        path = str(entrypoint)
        if skill not in skills or os.path.isabs(path) or Path(path).parts[:1] == ("..",):
            raise ValueError(f"invalid plugin entrypoint: {skill}")
        normalized = os.path.normpath(path)
        if normalized == ".." or normalized.startswith(".." + os.sep) or not normalized.endswith(".py"):
            raise ValueError(f"plugin entrypoint must be a relative Python file: {skill}")
        result[str(skill)] = normalized
    return result


def _validate_manifest(root: str) -> dict:
    try:
        manifest = json.load(open(os.path.join(root, "plugin.json"), encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("plugin.json is missing or invalid") from exc
    name = str(manifest.get("name") or "")
    skills = manifest.get("skills")
    if manifest.get("schema") != _PLUGIN_SCHEMA:
        raise ValueError(f"plugin schema must be {_PLUGIN_SCHEMA}")
    if not _SLUG.fullmatch(name):
        raise ValueError("plugin name must match [a-z0-9][a-z0-9._-]{0,63}")
    if not isinstance(skills, list) or not skills or len(skills) != len(set(map(str, skills))):
        raise ValueError("plugin skills must be a non-empty unique list")
    skills_root = os.path.join(root, "skills")
    if os.path.islink(skills_root) or not os.path.isdir(skills_root):
        raise ValueError("plugin skills must be a regular directory")
    normalized: list[str] = []
    skill_meta: dict[str, dict[str, str]] = {}
    skill_implicit: dict[str, bool] = {}
    for raw in skills:
        skill = str(raw)
        if not _SLUG.fullmatch(skill):
            raise ValueError(f"invalid skill name: {skill}")
        directory = os.path.join(skills_root, skill)
        path = os.path.join(directory, "SKILL.md")
        if os.path.islink(directory) or os.path.islink(path) or not os.path.isfile(path):
            raise ValueError(f"skill must be a regular file: {skill}")
        text = open(path, encoding="utf-8").read()
        parsed = _file_skill(text)
        if not parsed or parsed[0].get("name") != skill:
            raise ValueError(f"skill frontmatter is invalid or name differs: {skill}")
        normalized.append(skill)
        skill_meta[skill] = parsed[0]
        skill_implicit[skill] = _implicit(text)
    raw_routing = manifest.get("routing") or {}
    if not isinstance(raw_routing, dict) or set(raw_routing).difference(normalized):
        raise ValueError("plugin routing must be an object keyed by declared skill")
    routing: dict[str, dict] = {}
    allowed_agents = {*_ASSIGNABLE_AGENTS, "any"}
    for skill in normalized:
        raw_route = raw_routing.get(skill) or {}
        if not isinstance(raw_route, dict):
            raise ValueError(f"plugin routing must be an object: {skill}")
        triggers = [item.lower() for item in _items(raw_route.get("triggers") or skill_meta[skill].get("triggers"))]
        defaults = _items(
            raw_route.get("defaults")
            or raw_route.get("agent")
            or raw_route.get("agents")
            or skill_meta[skill].get("agent")
            or "worker"
        )
        compatible = _items(raw_route.get("agents") or skill_meta[skill].get("agents") or defaults)
        if not triggers or not defaults or not compatible:
            raise ValueError(f"plugin routing is incomplete: {skill}")
        if set(defaults).difference(allowed_agents) or set(compatible).difference(allowed_agents):
            raise ValueError(f"plugin routing has an invalid agent: {skill}")
        if set(defaults).difference(compatible):
            raise ValueError(f"plugin routing defaults must be compatible: {skill}")
        routing[skill] = {
            "triggers": triggers,
            "defaults": defaults,
            "agents": compatible,
            "implicit": skill_implicit[skill],
        }
    _safe_tree(root)
    entrypoints = _entrypoints(manifest, normalized)
    for skill, relative in entrypoints.items():
        path = os.path.join(skills_root, skill, relative)
        if os.path.islink(path) or not os.path.isfile(path):
            raise ValueError(f"plugin entrypoint is missing or unsafe: {skill}")
    return {
        "schema": _PLUGIN_SCHEMA,
        "name": name,
        "version": str(manifest.get("version") or "0"),
        "description": str(manifest.get("description") or ""),
        "skills": normalized,
        "routing": routing,
        "entrypoints": entrypoints,
        "source": str(manifest.get("source") or ""),
        "revision": str(manifest.get("revision") or ""),
        "license": str(manifest.get("license") or ""),
    }


def bundled_plugins() -> dict[str, dict]:
    found: dict[str, dict] = {}
    if not _BUNDLED_PLUGINS_DIR.is_dir():
        return found
    for child in sorted(_BUNDLED_PLUGINS_DIR.iterdir()):
        if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
            continue
        try:
            manifest = _validate_manifest(str(child))
        except ValueError:
            continue
        if manifest["name"] == child.name:
            found[child.name] = {**manifest, "root": str(child)}
    return found


def installed_plugins() -> dict[str, dict]:
    found: dict[str, dict] = {}
    base = _plugins_dir()
    if not os.path.isdir(base):
        return found
    for name in sorted(os.listdir(base)):
        root = os.path.join(base, name)
        if name.startswith(".") or os.path.islink(root) or not os.path.isdir(root):
            continue
        try:
            manifest = _validate_manifest(root)
        except ValueError:
            continue
        if manifest["name"] == name:
            found[name] = {**manifest, "root": root}
    return found


def install_plugin(source: str) -> dict:
    """Install one local skill bundle; only declared Python skill entrypoints are executable."""
    source = os.path.abspath(source)
    if os.path.islink(source) or not os.path.isdir(source):
        raise ValueError("plugin source must be a regular directory")
    manifest = _validate_manifest(source)
    builtins = _builtin_plugins()
    if manifest["name"] in builtins or manifest["name"] in bundled_plugins():
        raise ValueError(f"plugin name collides with built-in: {manifest['name']}")
    builtin_skills = {name for plugin in builtins.values() for name, _ in plugin["skills"]} | {
        skill for plugin in bundled_plugins().values() for skill in plugin["skills"]
    }
    existing_skills = {
        skill
        for plugin in installed_plugins().values()
        for skill in plugin["skills"]
        if plugin["name"] != manifest["name"]
    }
    collisions = builtin_skills.intersection(manifest["skills"]) | existing_skills.intersection(manifest["skills"])
    if collisions:
        raise ValueError("skill name collision: " + ", ".join(sorted(collisions)))
    base = _plugins_dir()
    destination = os.path.join(base, manifest["name"])
    if os.path.lexists(destination):
        raise ValueError(f"plugin already installed: {manifest['name']}")
    os.makedirs(base, mode=0o700, exist_ok=True)
    temp = tempfile.mkdtemp(prefix=f".{manifest['name']}.", dir=base)
    try:
        Path(os.path.join(temp, "plugin.json")).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for skill in manifest["skills"]:
            shutil.copytree(os.path.join(source, "skills", skill), os.path.join(temp, "skills", skill))
        for name in ("LICENSE", "LICENSE.md", "NOTICE", "NOTICE.md"):
            path = os.path.join(source, name)
            if os.path.isfile(path):
                shutil.copy2(path, os.path.join(temp, name))
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            shutil.rmtree(temp)
    return manifest


def plugins() -> list[dict]:
    rows = [
        {
            "name": name,
            "version": "bundled",
            "description": plugin["description"],
            "skills": [skill for skill, _ in plugin["skills"]],
            "origin": "bundled",
        }
        for name, plugin in _builtin_plugins().items()
    ]
    rows.extend({**manifest, "origin": "bundled"} for manifest in bundled_plugins().values())
    rows.extend({**manifest, "origin": "installed"} for manifest in installed_plugins().values())
    return rows


def skills(root: str) -> list[dict]:
    rows = [
        {
            "name": name,
            "description": _description(text),
            "plugin": plugin_name,
            "origin": "bundled",
            "invocation": "model" if _implicit(text) else "user",
        }
        for plugin_name, plugin in _builtin_plugins().items()
        for name, text in plugin["skills"]
    ]
    seen = {row["name"] for row in rows}
    for plugin_name, plugin in bundled_plugins().items():
        for name in plugin["skills"]:
            if name in seen:
                continue
            text = open(os.path.join(plugin["root"], "skills", name, "SKILL.md"), encoding="utf-8").read()
            rows.append(
                {
                    "name": name,
                    "description": _description(text),
                    "plugin": plugin_name,
                    "origin": "bundled",
                    "invocation": "model" if _implicit(text) else "user",
                }
            )
            seen.add(name)
    for name, skill in learned_skills(root).items():
        if name in seen:
            continue
        rows.append(
            {
                "name": name,
                "description": str(skill.get("description") or ""),
                "plugin": "learned",
                "origin": "project" if str(skill.get("path", "")).startswith(os.path.realpath(root)) else "global",
                "invocation": "model" if _implicit(open(str(skill["path"]), encoding="utf-8").read()) else "user",
            }
        )
        seen.add(name)
    for plugin_name, plugin in installed_plugins().items():
        for name in plugin["skills"]:
            if name in seen:
                continue
            text = open(os.path.join(plugin["root"], "skills", name, "SKILL.md"), encoding="utf-8").read()
            rows.append(
                {
                    "name": name,
                    "description": _description(text),
                    "plugin": plugin_name,
                    "origin": "installed",
                    "invocation": "model" if _implicit(text) else "user",
                }
            )
            seen.add(name)
    return sorted(rows, key=lambda row: row["name"])


def show_skill(root: str, name: str) -> str | None:
    for plugin in _builtin_plugins().values():
        for skill, text in plugin["skills"]:
            if skill == name:
                return text
    for plugin in bundled_plugins().values():
        if name in plugin["skills"]:
            return open(os.path.join(plugin["root"], "skills", name, "SKILL.md"), encoding="utf-8").read()
    learned = learned_skills(root).get(name)
    if learned:
        return open(str(learned["path"]), encoding="utf-8").read()
    for plugin in installed_plugins().values():
        if name in plugin["skills"]:
            return open(os.path.join(plugin["root"], "skills", name, "SKILL.md"), encoding="utf-8").read()
    return None


def invocable_skills(root: str) -> list[dict]:
    """Catalog rows reachable by at least one configured runtime role."""
    policy = _skill_policy(root)
    allowed = set()
    for name, (defaults, compatible) in _skill_routes(root).items():
        if any(
            (agent in compatible or "any" in compatible) and _assigned(name, agent, defaults, policy)
            for agent in _ASSIGNABLE_AGENTS
        ):
            allowed.add(name)
    return [row for row in skills(root) if row["name"] in allowed]


def invoked_skill_prompt(root: str, command: str) -> str | None:
    """Expand an exact ``/skill-name`` invocation without exposing hidden skills to discovery."""
    head, _, arguments = command.strip().partition(" ")
    name = head.removeprefix("/")
    if not name or name not in {row["name"] for row in invocable_skills(root)}:
        return None
    text = show_skill(root, name)
    if text is None:
        return None
    body = text.split("---", 2)[2].lstrip() if text.startswith("---") else text
    return (
        f'<user_invoked_skill name="{escape(name)}">\n{body.rstrip()}\n</user_invoked_skill>\n\n'
        "The user explicitly invoked this skill. Follow its interaction contract; an explicit HITL skill may pause "
        "for the user's next decision even though ordinary unattended work should choose a safe default.\n\n"
        f"Arguments: {arguments.strip() or '(none)'}"
    )


def show_skill_resource(root: str, name: str, relative: str) -> str:
    """Read one text resource next to a file-backed skill without allowing path escape."""
    if not relative or os.path.isabs(relative):
        raise ValueError("skill resource must be a relative path")
    normalized = os.path.normpath(relative)
    if normalized in (".", "..") or normalized.startswith(".." + os.sep):
        raise ValueError("skill resource escapes its skill directory")
    for plugin in [*bundled_plugins().values(), *installed_plugins().values()]:
        if name not in plugin["skills"]:
            continue
        skill_root = Path(plugin["root"], "skills", name).resolve()
        candidate = Path(skill_root, normalized)
        resolved = candidate.resolve()
        try:
            resolved.relative_to(skill_root)
        except ValueError as exc:
            raise ValueError("skill resource escapes its skill directory") from exc
        if candidate.is_symlink() or not resolved.is_file():
            raise ValueError(f"skill resource not found: {name}/{relative}")
        try:
            return resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"skill resource is not UTF-8 text: {name}/{relative}") from exc
    if show_skill(root, name) is None:
        raise ValueError(f"skill not found: {name}")
    raise ValueError(f"skill has no bundled resource: {name}/{relative}")


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


def _builtin_resolver(name: str):
    if name == "worker":
        from .templates.worker import resolve_worker_skills

        return resolve_worker_skills
    if name == "freyja":
        from .templates.freyja import resolve_freyja_skills

        return resolve_freyja_skills
    if name == "thor":
        from .templates.thor import resolve_thor_skills

        return resolve_thor_skills
    if name == "eitri":
        from .templates.eitri import resolve_eitri_skills

        return resolve_eitri_skills
    if name == "mimir":
        from .templates.mimir import resolve_mimir_skills

        return resolve_mimir_skills
    return None


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


def _resolve_bundled(root: str, task: str, agent: str) -> list[tuple[str, str]]:
    policy = _skill_policy(root)
    hits: list[tuple[str, str]] = []
    for plugin in _builtin_plugins().values():
        resolver = _builtin_resolver(str(plugin.get("resolver") or ""))
        if resolver is None:
            continue
        defaults = tuple(plugin.get("agents") or ())
        selected = resolver(task)
        hits.extend((name, body) for name, body in selected if _assigned(name, agent, defaults, policy))
    return hits


def _resolve_file_plugins(root: str, task: str, agent: str, sources: dict[str, dict]) -> list[tuple[str, str]]:
    task = task.lower()
    hits: list[tuple[int, str, str]] = []
    policy = _skill_policy(root)
    for plugin in sources.values():
        for name in plugin["skills"]:
            text = open(os.path.join(plugin["root"], "skills", name, "SKILL.md"), encoding="utf-8").read()
            parsed = _file_skill(text)
            if not parsed:
                continue
            if not plugin["routing"][name]["implicit"]:
                continue
            _, body = parsed
            route = plugin["routing"][name]
            defaults = tuple(route["defaults"])
            compatible = tuple(route["agents"])
            if agent not in compatible and "any" not in compatible:
                continue
            if not _assigned(name, agent, defaults, policy):
                continue
            matched = sum(1 for trigger in route["triggers"] if trigger in task)
            if matched:
                hits.append((-matched, name, body))
    hits.sort()
    return [(name, body) for _, name, body in hits[:_PLUGIN_CAP]]


def resolve_installed(task: str, agent: str, root: str | None = None) -> list[tuple[str, str]]:
    return _resolve_file_plugins(root or os.getcwd(), task, agent, installed_plugins())


def resolve_skills(root: str, task: str, agent: str, *, include_learned: bool = True) -> list[tuple[str, str]]:
    """Legacy explicit resolver; automatic runtimes use metadata discovery plus on-demand load."""
    if agent in ("verifier", "loki"):
        return []
    hits = [
        *_resolve_bundled(root, task, agent),
        *_resolve_file_plugins(root, task, agent, bundled_plugins()),
        *(resolve_learned(root, task, agent) if include_learned else []),
        *_resolve_file_plugins(root, task, agent, installed_plugins()),
    ]
    disabled, _, unassigned = _skill_policy(root)
    seen: set[str] = set()
    selected: list[tuple[str, str]] = []
    used = 0
    for name, body in hits:
        if name in disabled or name in unassigned.get(agent, set()) or name in seen:
            continue
        text = show_skill(root, name) or ""
        if not _implicit(text):
            continue
        seen.add(name)
        if name.endswith("-deferred"):
            selected.append((name, body))
            continue
        if used + len(body) > _RESOLVED_BODY_BUDGET:
            description = _description(text)[:140] if text.startswith("---") else ""
            selected.append(
                (
                    name,
                    "# Matched skill — lazy body\n\n"
                    f"`{name}` matched this task, but its full body exceeded the aggregate inline budget. "
                    "Before making decisions in this domain, run the command below and apply its output.\n\n"
                    f"    asgard skills show {name}\n\n"
                    "If that body references a sibling file, load only the needed file with "
                    f"`asgard skills show {name} --resource <relative-path>`.\n\n"
                    f"Catalog description: {description}",
                )
            )
            continue
        selected.append((name, body))
        used += len(body)
    return selected


def client_skill_bodies(agent: str, root: str | None = None, *, include_learned: bool = True) -> list[tuple[str, str]]:
    """Return the canonical skills visible to one agent, before any task is known."""
    root = root or os.getcwd()
    policy = _skill_policy(root)
    hits: dict[str, str] = {}
    core_contracts = {"asgard-freyja", "asgard-thor", "asgard-eitri", "asgard-mimir"}
    for plugin in _builtin_plugins().values():
        defaults = tuple(plugin.get("agents") or ())
        for name, body in plugin["skills"]:
            if name not in core_contracts and _assigned(name, agent, defaults, policy):
                hits.setdefault(name, body)
    for plugin in [*bundled_plugins().values(), *installed_plugins().values()]:
        for name in plugin["skills"]:
            text = open(os.path.join(plugin["root"], "skills", name, "SKILL.md"), encoding="utf-8").read()
            parsed = _file_skill(text)
            if not parsed:
                continue
            route = plugin["routing"][name]
            compatible = set(route["agents"])
            if (agent in compatible or "any" in compatible) and _assigned(
                name, agent, tuple(route["defaults"]), policy
            ):
                hits.setdefault(name, text)
    if include_learned:
        for name, skill in learned_skills(root).items():
            defaults = (str(skill.get("agent") or "worker"),)
            if _assigned(name, agent, defaults, policy):
                text = show_skill(root, name)
                if text:
                    hits.setdefault(name, text)
    return sorted(hits.items())


def available_skills(
    root: str,
    agent: str,
    *,
    include_learned: bool = True,
    exclude: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """Compact discovery tier: names and descriptions only, filtered by agent policy."""
    hidden = set(exclude)
    return [
        {"name": name, "description": _description(text)}
        for name, text in client_skill_bodies(agent, root, include_learned=include_learned)
        if name not in hidden and _implicit(text)
    ]


def skill_catalog(
    root: str,
    agent: str,
    *,
    include_learned: bool = True,
    exclude: tuple[str, ...] = (),
    loader: str = "load_skill",
    matched: set[str] | None = None,
) -> str:
    """Render only the metadata needed for model-native autonomous selection."""
    rows = available_skills(root, agent, include_learned=include_learned, exclude=exclude)
    if not rows:
        return ""
    if matched is not None:
        rows.sort(key=lambda row: (row["name"] not in matched, row["name"]))
        instruction = (
            "Call `load_skill` for every `[task-match]` skill before working. Then scan the remaining "
            "descriptions and load any additional skill that fits the task."
        )
    elif loader == "load_skill":
        instruction = "Call `load_skill` with the exact name only when a description matches the task."
    else:
        instruction = (
            "Run `asgard skills show <exact-name>` only when a description matches the task, "
            "then follow the returned body."
        )
    items = "\n".join(
        f"  - {'[task-match] ' if matched is not None and row['name'] in matched else ''}"
        f"{escape(row['name'])}: {escape(row['description'])}"
        for row in rows
    )
    return (
        "\n\n## Available skills (progressive disclosure)\n"
        f"{instruction} Do not preload every skill.\n"
        "<available_skills>\n"
        f"{items}\n"
        "</available_skills>"
    )


def load_skill_for_agent(
    root: str,
    agent: str,
    name: str,
    resource: str | None = None,
    *,
    include_learned: bool = True,
    exclude: tuple[str, ...] = (),
) -> str:
    """Load one assigned canonical body/resource; arbitrary catalog access stays closed."""
    allowed = {row["name"] for row in available_skills(root, agent, include_learned=include_learned, exclude=exclude)}
    if name not in allowed:
        raise ValueError(f"skill is not available to agent: {name} -> {agent}")
    if resource:
        loaded = show_skill_resource(root, name, resource)
        if name in learned_skills(root):
            record_use(root, [name])
        return loaded
    text = show_skill(root, name)
    if text is None:
        raise ValueError(f"skill not found: {name}")
    if name in learned_skills(root):
        record_use(root, [name])
    return text.split("---", 2)[2].lstrip() if text.startswith("---") else text


def run_skill(root: str, name: str, args: list[str]) -> int:
    """Run one declared Python helper without a shell; instruction-only skills are rejected."""
    for plugin in [*bundled_plugins().values(), *installed_plugins().values()]:
        relative = plugin.get("entrypoints", {}).get(name)
        if not relative:
            continue
        skill_root = os.path.join(plugin["root"], "skills", name)
        entrypoint = os.path.realpath(os.path.join(skill_root, relative))
        try:
            Path(entrypoint).relative_to(Path(skill_root).resolve())
        except ValueError as exc:
            raise ValueError("plugin entrypoint escapes its skill directory") from exc
        if os.path.islink(entrypoint) or not os.path.isfile(entrypoint):
            raise ValueError("plugin entrypoint is missing or unsafe")
        # ponytail: Python-only entrypoints; add another declared runtime when a real bundled skill needs it.
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, entrypoint, *args], cwd=root, env=env, check=False).returncode
    raise ValueError(f"skill has no runnable entrypoint: {name}")
