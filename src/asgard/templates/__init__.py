"""Content templates for `asgard init` — pure, stateless emitters (no shared state / UX / IO).

Config + rules + folder scaffolding only. Hook SCRIPTS live in `asgard.hooks` and role AGENTS in
`asgard.templates.roles` — both managed as real files there, not embedded strings here.
"""

from .agents import agents_md
from .bridge import BRIDGE_SKILL_MD
from .claude import CC_FOLDERS, cc_settings
from .codex import codex_config, codex_rules
from .cursor import CURSOR_FOLDERS, cursor_hooks_json, cursor_rule
from .eitri import EITRI_SKILLS
from .freyja import FREYJA_SKILLS, freyja_core_skill
from .lagom import LAGOM_CANON, render_lagom
from .map import MAP_INDEX_MD
from .mimir import MIMIR_SKILLS, mimir_core_skill
from .seal import SEAL_SKILL_MD
from .selftest import SELFTEST_MD
from .thor import THOR_SKILLS, eitri_core_skill, thor_core_skill
from .trinity import project_settings, trinity_policy
from .worker import WORKER_SKILLS

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
    "EITRI_SKILLS",
    "FREYJA_SKILLS",
    "freyja_core_skill",
    "MIMIR_SKILLS",
    "mimir_core_skill",
    "WORKER_SKILLS",
    "THOR_SKILLS",
    "thor_core_skill",
    "eitri_core_skill",
    "LAGOM_CANON",
    "MAP_INDEX_MD",
    "render_lagom",
    "SEAL_SKILL_MD",
    "SELFTEST_MD",
    "project_settings",
    "trinity_policy",
]
