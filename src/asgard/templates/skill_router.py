"""Thin client discovery adapters for the Asgard-owned skill catalog."""

from __future__ import annotations

import re


def _field(skill_md: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", skill_md.split("---", 2)[1], re.M)
    return match.group(1).strip() if match else ""


def _plain(value: str) -> str:
    """YAML 인용부호를 벗긴 사람 표면용 값 — 프론트매터로 되돌려 쓰는 자리엔 쓰지 않는다."""
    return value[1:-1].strip() if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" else value


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


def direct_skill(skill_md: str, *, implicit: bool = True) -> str:
    """Keep canonical bodies in Asgard; optionally reserve the adapter for explicit invocation."""
    name = _field(skill_md, "name")
    description = _field(skill_md, "description")
    allowed = _field(skill_md, "allowed-tools")
    explicit = not implicit or _field(skill_md, "disable-model-invocation").lower() in ("true", "yes", "1", "on")
    explicit_line = "disable-model-invocation: true\n" if explicit else ""
    # 인자 힌트는 사용자 표면이다 — 상류가 적어 뒀으면 어댑터에서도 살려야 `/name <args>` 안내가 제대로 나온다.
    hint = _field(skill_md, "argument-hint")
    hint_line = f"argument-hint: {hint}\n" if hint else ""
    # 쉼표로 잇는다 — 공백으로 이으면 상류 목록의 마지막 항목이 `WebSearch Bash(asgard skills *)`
    # 한 덩어리가 돼 그 도구와 우리 통로가 함께 사라진다 (allowed-tools는 쉼표 구분 목록).
    tools = ", ".join(part for part in (allowed, "Bash(asgard skills *)") if part)
    return f"""---
name: {name}
description: {description}
{hint_line}{explicit_line}allowed-tools: {tools}
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
    # 상류 프론트매터가 인용된 설명을 쓰면 그 따옴표가 사용자에게 보이는 문장 첫 글자가 된다.
    description = _plain(_field(skill_md, "description"))
    display = " ".join(part.capitalize() for part in name.split("-"))
    return (
        "interface:\n"
        f'  display_name: "{display}"\n'
        f'  short_description: "{description[:120].replace(chr(34), chr(39))}"\n'
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )


def _router_skill(*, explicit: bool) -> str:
    explicit_line = "disable-model-invocation: true\n" if explicit else ""
    return f"""\
---
name: asgard-skills
description: Before ordinary Codex or Cursor work, select and load the matching Asgard skill or plugin policy; also manage the central catalog.
{explicit_line}allowed-tools: Bash(asgard skills *)
---

# asgard-skills — central router

For ordinary Codex or Cursor work, use this router once before task-specific decisions. Pass only
one of these exact lowercase CLI roles. `MAIN_WORKER` and agent names are not valid role values;
classify their task instead:

- `freyja` — UI, design, UX, motion, browser, 3D, or video
- `thor` — backend, data, API, security, or runtime infrastructure
- `eitri` — build, CI, packaging, or release
- `mimir` — code explanation, walkthrough, or onboarding
- `worker` — debugging, testing, and everything else

Then run:

    asgard skills resolve --agent <role> "<current task>"

Run the installed `asgard` executable directly from `PATH`. Do not prefix the command with
`python`, and do not resolve `asgard` relative to this skill directory.

Apply only the returned policies. Empty output means no extra policy. Do not also auto-select an
individual `.agents/skills` adapter; those remain available as explicit `/name` or `$name`
overrides.

The output ends with a `Work shape` block whenever the request implies a change. It states the
deterministic size of the work — `slice`, `feature`, or `expedition` — the planning discipline that
shape requires, and the names of any discipline skills whose triggers this request matched. Load
each named skill with `asgard skills show <name>` before deciding; the match is deterministic, so it
is not a suggestion to re-evaluate. Hold to the shape: do not inflate a slice into a feature to look
thorough, and do not compress a feature into one sweep to look fast.

For catalog management, use:

    asgard skills
    asgard plugins
"""


# Claude Code already selects the right project skill reliably; keep its manager user-invoked.
ROUTER_SKILL_MD = _router_skill(explicit=True)

# Codex and Cursor share .agents/skills and route through one implicit manager.
MANAGED_ROUTER_SKILL_MD = _router_skill(explicit=False)
