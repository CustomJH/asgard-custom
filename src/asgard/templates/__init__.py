"""Content templates for `asgard init` — pure, stateless emitters (no shared state / UX / IO).

Config + rules + folder scaffolding only. Hook SCRIPTS live in `asgard.hooks` and role AGENTS in
`asgard.templates.roles` — both managed as real files there, not embedded strings here.
"""

from .agents import agents_md
from .bridge import BRIDGE_SKILL_MD
from .claude import CC_FOLDERS, cc_settings
from .codex import codex_config, codex_rules
from .cursor import CURSOR_FOLDERS, cursor_hooks_json, cursor_rule
from .freyja import FREYJA_SKILLS, freyja_core_skill
from .lagom import LAGOM_CANON, render_lagom
from .map import MAP_INDEX_MD
from .seal import SEAL_SKILL_MD
from .selftest import SELFTEST_MD
from .trinity import trinity_policy

__all__ = [
    "agents_md",
    "BRIDGE_SKILL_MD",
    "cc_settings",
    "CC_FOLDERS",
    "codex_config",
    "codex_rules",
    "cursor_rule",
    "cursor_hooks_json",
    "CURSOR_FOLDERS",
    "FREYJA_SKILLS",
    "freyja_core_skill",
    "LAGOM_CANON",
    "MAP_INDEX_MD",
    "render_lagom",
    "SEAL_SKILL_MD",
    "SELFTEST_MD",
    "trinity_policy",
]
