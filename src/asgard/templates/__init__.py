"""Content templates for `asgard setup` — pure, stateless emitters (no shared state / UX / IO).

Ported from src/templates.ts (CUS-108). Generated content stays byte-identical to the TS version;
only the hook scripts change from Node (.mjs) to Python (.py) and the wiring flips node → python3.
"""

from .agents import agents_md
from .claude import CC_FOLDERS, cc_settings
from .codex import codex_config, codex_rules
from .cursor import CURSOR_FOLDERS, cursor_git_guard, cursor_hooks_json, cursor_rule
from .guards import git_guard, secret_guard

__all__ = [
    "agents_md",
    "cc_settings",
    "CC_FOLDERS",
    "codex_config",
    "codex_rules",
    "cursor_rule",
    "cursor_git_guard",
    "cursor_hooks_json",
    "CURSOR_FOLDERS",
    "git_guard",
    "secret_guard",
]
