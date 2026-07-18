#!/usr/bin/env python3
"""asgard-provider 브릿지 스킬 자가 검증 — 스캐폴드 배선 + 게이트·승인 계약이 본문에 실존하는지.

실행: uv run pytest tests/test_bridge.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.templates import BRIDGE_SKILL_MD  # noqa: E402


class TestScaffold(unittest.TestCase):
    def test_plan_contains_bridge_skill_both_scopes(self):
        from asgard.commands.setup import plan_files

        for flags in ({"cc": True, "cursor": False, "codex": False}, {"cc": False, "cursor": True, "codex": False}):
            files, _ = plan_files(root="/tmp/x", **flags)
            self.assertTrue(any(p.endswith(os.path.join("asgard-provider", "SKILL.md")) for p, _ in files), flags)


class TestSkillBody(unittest.TestCase):
    def test_frontmatter(self):
        self.assertTrue(BRIDGE_SKILL_MD.startswith("---\nname: asgard-provider\n"))

    def test_allowed_tools_preapproval(self):
        """브릿지의 일은 `asgard role` 실행뿐 — 디스패치 루프가 권한 프롬프트로 멈추지 않게 사전
        승인. on/off 게이트는 여전히 런타임(`asgard role list`, 기본 꺼짐)."""
        self.assertIn("allowed-tools: Bash(asgard role *)", BRIDGE_SKILL_MD)

    def test_runtime_gate_contract(self):
        self.assertIn("asgard role list", BRIDGE_SKILL_MD)
        self.assertIn("asgard role run", BRIDGE_SKILL_MD)
        self.assertIn("Canon 10", BRIDGE_SKILL_MD)  # 브릿지된 Verifier verdict 번복 금지


if __name__ == "__main__":
    unittest.main(verbosity=1)
