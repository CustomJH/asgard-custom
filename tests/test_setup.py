#!/usr/bin/env python3
"""Scaffold text that names a host's invocation syntax must match what that host accepts."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.templates.agents import agents_md  # noqa: E402
from asgard.templates.skill_router import MANAGED_ROUTER_SKILL_MD, ROUTER_SKILL_MD  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# Codex answers `/<skill>` with `Unrecognized command` and closed the request to change that
# (openai/codex#11817, not planned); file-based `~/.codex/prompts` stopped feeding the slash menu
# in 0.117 (#15941, also not planned). So a sentence that offers `/name` to a Codex reader sends
# them to a dead key — the two syntaxes have to stay attached to their host.
BLURRED = "`/name` or `$name`"


class InvocationSyntaxTest(unittest.TestCase):
    # (source name, body, the phrase that ties `$name` to Codex). Templates and the copies this
    # repository scaffolded from them are checked together — a fix that lands only in the template
    # leaves every already-initialised project reading the old sentence.
    def sources(self) -> list[tuple[str, str, str]]:
        guide = "`$name` in Codex"
        router = "Codex takes `$name`"
        sources = [
            ("agents_md", agents_md("demo"), guide),
            ("router (explicit)", ROUTER_SKILL_MD, router),
            ("router (managed)", MANAGED_ROUTER_SKILL_MD, router),
        ]
        # The copies this repository scaffolded are compared only when they are on disk: the root
        # AGENTS.md and .claude/ are both gitignored here, so a clean checkout has neither. When
        # they are present they must still agree, because a fix that lands only in the template
        # leaves every already-initialised project reading the old sentence.
        for label, rel, expected in (
            ("AGENTS.md", "AGENTS.md", guide),
            (".claude router", ".claude/skills/asgard-skills/SKILL.md", router),
        ):
            copy = REPO / rel
            if copy.exists():
                sources.append((label, copy.read_text(encoding="utf-8"), expected))
        return sources

    def test_no_host_agnostic_slash_offer(self):
        for name, body, _ in self.sources():
            with self.subTest(source=name):
                self.assertNotIn(BLURRED, body)

    def test_codex_syntax_is_named(self):
        for name, body, expected in self.sources():
            with self.subTest(source=name):
                self.assertIn(expected, body)


if __name__ == "__main__":
    unittest.main()
