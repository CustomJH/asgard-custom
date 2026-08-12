"""plugin.json 검증과 자원 트리 검사 — 복사·실행 전에 지나는 신뢰 경계."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .frontmatter import _file_skill, _implicit, _items, _read_text

_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_PLUGIN_SCHEMA = 1
_PLUGIN_FILE_CAP = 4_096
_PLUGIN_BYTE_CAP = 64 * 1024 * 1024
_ASSIGNABLE_AGENTS = frozenset(("worker", "freyja", "thor", "thor-lead", "eitri", "mimir"))


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


def _skill_md(plugin: dict, name: str) -> str:
    """플러그인의 SKILL.md 본문. 같은 경로 조립이 여섯 곳에 흩어져 있어 한 자리로 모은다."""
    return _read_text(os.path.join(plugin["root"], "skills", name, "SKILL.md"))


def _validate_manifest(root: str, *, deep: bool = True) -> dict:
    """플러그인 매니페스트를 읽고 검증한다. `deep=False` 면 자원 트리 순회(`_safe_tree`)를 건너뛴다.

    순회는 신뢰 경계를 지키는 검사다 — 링크·특수 파일·상한 초과를 **복사하거나 실행하기 전에**
    막는다. 그 경계가 없는 자리가 하나 있다: 휠에 함께 배송되는 번들 플러그인은 이 파이썬
    코드와 출처가 같아서, 거기 링크를 심을 수 있는 자는 이 파일도 심을 수 있다. 그 자리에서
    순회는 보호가 아니라 값이다 — 26-08-04 실측으로 `bundled_plugins()` 47.2ms 의 89% 이고,
    resolve 3회에 os.walk 4,485회·lstat 21,319회를 낸다.

    그래서 읽기 경로만 얕게 본다. 실제 경계는 그대로 남는다: 제3자 번들을 읽는
    `installed_plugins()` 와 설치하는 `install_plugin()` 은 깊게 보고, 디스크로 복사하는
    `anchor_skill()` 은 복사 직전에 스스로 `_safe_tree` 를 부른다."""
    try:
        manifest = json.loads(_read_text(os.path.join(root, "plugin.json")))
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
        text = _read_text(path)
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
    # 앵커 스킬 — 본문이 자기 디렉터리를 기준으로 경로를 푸는 스킬(엔진 스크립트를 데리고 다니는
    # 벤더링 팩)은 카탈로그로 본문을 흘려보내면 그 경로가 전부 끊긴다. 선언한 스킬만 디스크에
    # 풀고 위치를 넘긴다 — 선언 안 한 스킬은 지금까지처럼 본문 그대로다.
    anchored = _items(manifest.get("anchored"))
    if set(anchored).difference(normalized):
        raise ValueError("plugin anchored must list declared skills")
    if deep:
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
        "anchored": anchored,
        "routing": routing,
        "entrypoints": entrypoints,
        "source": str(manifest.get("source") or ""),
        "revision": str(manifest.get("revision") or ""),
        "license": str(manifest.get("license") or ""),
    }
