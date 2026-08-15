"""Asgard-owned skill/plugin catalog and progressive skill loader.

Clients only receive discovery metadata and thin loaders.  Policy bodies stay here so Claude
Code, Cursor, Codex, and the native Heimdall loop share one source of truth.
"""

from __future__ import annotations

# 파사드는 종전 모듈이 내놓던 이름을 전부 같은 경로에 다시 내놓는다 — 호출부와 시험이
# 밑줄 이름(`_BUNDLED_PLUGINS_DIR`·`_builtin_plugins`·`_ASSIGNABLE_AGENTS`)까지 여기서 찾는다.
import subprocess  # noqa: F401 — tests/test_document_tools.py 가 `asgard.skill_registry.subprocess.run` 을 갈아 끼운다

from .anchor import (  # noqa: F401
    _ANCHOR_DIR,
    _ANCHOR_STAMP,
    _anchor_md,
    _anchor_target,
    _delivered_md,
    _tree_files,
    anchor_skill,
)
from .assignment import _compatible_agents, assign_skill, set_skill_enabled  # noqa: F401
from .builtin import _builtin_plugins, _builtin_resolver  # noqa: F401
from .bundles import (  # noqa: F401
    _BUNDLED_PLUGINS_DIR,
    _plugins_dir,
    bundled_plugins,
    install_plugin,
    installed_plugins,
    plugins,
)
from .catalog import (  # noqa: F401
    _CATALOG_LINE_CAP,
    _INVOKED_ARGS,
    _INVOKED_HEAD,
    _catalog_line,
    available_skills,
    client_skill_bodies,
    invocable_skill_bodies,
    invocable_skills,
    invoked_skill_command,
    invoked_skill_prompt,
    load_skill_for_agent,
    show_skill,
    show_skill_resource,
    skill_catalog,
    skill_lane,
    skills,
)
from .frontmatter import (  # noqa: F401
    _description,
    _file_skill,
    _implicit,
    _items,
    _lane,
    _read_text,
)
from .manifest import (  # noqa: F401
    _ASSIGNABLE_AGENTS,
    _PLUGIN_BYTE_CAP,
    _PLUGIN_FILE_CAP,
    _PLUGIN_SCHEMA,
    _SLUG,
    _entrypoints,
    _safe_tree,
    _skill_md,
    _validate_manifest,
)
from .policy import _assigned, _skill_policy, _skill_routes  # noqa: F401
from .resolve import (  # noqa: F401
    _ASCII_TRIGGER,
    _PLUGIN_CAP,
    _RESOLVED_BODY_BUDGET,
    _TRIGGER_TAIL,
    _resolve_bundled,
    _resolve_file_plugins,
    _trigger_hits,
    _trigger_pattern,
    resolve_installed,
    resolve_skills,
)
from .runner import run_skill  # noqa: F401
