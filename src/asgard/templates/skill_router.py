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
    tools = " ".join(part for part in (allowed, "Bash(asgard skills *)") if part)
    return f"""---
name: {name}
description: {description}
allowed-tools: {tools}
---

# Asgard central skill adapter

Run `asgard skills show {name}` and apply the returned body as the canonical policy for this skill.
The wrapper contains no client-specific policy.
"""


ROUTER_SKILL_MD = """\
---
name: asgard-skills
description: Asgard 중앙 스킬·플러그인 목록, 할당, 활성화 상태를 조회하거나 관리할 때 사용.
allowed-tools: Bash(asgard skills *)
---

# asgard-skills — central catalog

This is the management surface, not a mandatory task router. Inspect the catalog with:

    asgard skills
    asgard plugins

For ordinary work, let the runtime choose a specific skill from its name and description. The
selected skill adapter loads its canonical body with `asgard skills show <name>`.
"""
