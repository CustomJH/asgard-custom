"""Content templates for `asgard init` — pure, stateless emitters (no shared state / UX / IO).

Config + rules + folder scaffolding only. Hook SCRIPTS live in `asgard.hooks` (loaded via its
`script()`), so hook code is managed as real files there, not embedded strings here.
"""

from .agents import agents_md
from .claude import CC_FOLDERS, cc_settings
from .codex import codex_config, codex_rules
from .cursor import CURSOR_FOLDERS, cursor_hooks_json, cursor_rule

__all__ = [
    "agents_md",
    "cc_settings",
    "CC_FOLDERS",
    "codex_config",
    "codex_rules",
    "cursor_rule",
    "cursor_hooks_json",
    "CURSOR_FOLDERS",
]
