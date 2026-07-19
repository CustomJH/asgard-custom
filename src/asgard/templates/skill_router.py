"""Thin client discovery adapters for the Asgard-owned skill catalog."""

from __future__ import annotations

import re


def _field(skill_md: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", skill_md.split("---", 2)[1], re.M)
    return match.group(1).strip() if match else ""


def routed_skill(skill_md: str, agent: str) -> str:
    """Legacy deterministic wrapper retained so sync can recognize old generated files."""
    name = _field(skill_md, "name")
    description = _field(skill_md, "description")
    return f"""---
name: {name}
description: {description}
allowed-tools: Bash(asgard skills *)
---

# Asgard central skill adapter

This file is a discovery hint, not policy. Once per current `{agent}` phase, run:

    asgard skills resolve --agent {agent} \"<current task>\"

Apply only the returned policy. Empty output means no extra skill. Do not infer policy from this
wrapper's name, and do not resolve the same phase again through another client-native skill.
"""


def direct_skill(skill_md: str) -> str:
    """Explicit commands keep their native trigger, while their body remains Asgard-owned."""
    name = _field(skill_md, "name")
    description = _field(skill_md, "description")
    allowed = _field(skill_md, "allowed-tools")
    explicit = _field(skill_md, "disable-model-invocation").lower() in ("true", "yes", "1", "on")
    explicit_line = "disable-model-invocation: true\n" if explicit else ""
    tools = " ".join(part for part in (allowed, "Bash(asgard skills *)") if part)
    return f"""---
name: {name}
description: {description}
{explicit_line}allowed-tools: {tools}
---

# Asgard central skill adapter

Run `asgard skills show {name}` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
"""


def openai_skill_metadata(skill_md: str) -> str | None:
    """Codex needs an explicit policy file for user-invoked skills."""
    if _field(skill_md, "disable-model-invocation").lower() not in ("true", "yes", "1", "on"):
        return None
    name = _field(skill_md, "name")
    description = _field(skill_md, "description")
    display = " ".join(part.capitalize() for part in name.split("-"))
    return (
        "interface:\n"
        f'  display_name: "{display}"\n'
        f'  short_description: "{description[:120].replace(chr(34), chr(39))}"\n'
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )


ROUTER_SKILL_MD = """\
---
name: asgard-skills
description: Asgard 중앙 스킬·플러그인 목록, 할당, 활성화 상태를 조회하거나 관리할 때 사용.
disable-model-invocation: true
allowed-tools: Bash(asgard skills *)
---

# asgard-skills — central catalog

This is the management surface, not a mandatory task router. Inspect the catalog with:

    asgard skills
    asgard plugins

For ordinary work, let the runtime choose a specific skill from its name and description. The
selected skill adapter loads its canonical body with `asgard skills show <name>`.
"""
