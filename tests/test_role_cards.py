#!/usr/bin/env python3
"""역할 카드의 프런트매터 — 호스트가 서브에이전트를 고를 때 실제로 읽는 한 줄."""

import unittest

from asgard.hooks.subagent_gate import AGENT_TARGETS
from asgard.templates.roles import ROLE_AGENTS, role_document

# 이름으로 대조할 수 있는 호출자 — Trinity 세 역할. 딜리버리 계층은 카드마다
# `any delivery specialist` 같은 포괄어로 적어 문자열 대조가 성립하지 않는다.
TRINITY_CALLERS = {
    "asgard-worker": "Worker",
    "asgard-thinker": "Thinker",
    "asgard-verifier": "Verifier",
}


class TestRoleCardDescriptions(unittest.TestCase):
    """카드 설명이 위임 표와 같은 명단을 들고 있는가."""

    def test_a_card_names_every_trinity_role_the_table_lets_dispatch_it(self):
        """위임 표가 여는 길과 카드 설명이 부르는 사람 명단은 같아야 한다.

        호스트는 서브에이전트를 고를 때 프런트매터의 `description` 만 읽는다 — 본문도, 위임 표도
        안 본다. 그래서 표에는 있는데 설명에 이름이 없는 호출자는 그 길을 영영 안 쓴다.
        26-08-20 실측: 판정자 배차 41건 중 asgard-ullr 은 0건이고 asgard-loki 는 2건인데,
        두 카드의 차이는 loki 설명에만 `Verifier` 가 적혀 있다는 것뿐이었다."""
        bodies = {fname.removesuffix(".md"): content for fname, content in ROLE_AGENTS}
        for target, content in sorted(bodies.items()):
            callers = sorted(
                TRINITY_CALLERS[caller]
                for caller, targets in AGENT_TARGETS.items()
                if target in targets and caller in TRINITY_CALLERS
            )
            if not callers:
                continue
            description = role_document(content)[0].get("description", "")
            missing = [name for name in callers if name not in description]
            self.assertEqual(
                missing,
                [],
                f"{target} 카드 설명이 {missing} 을 안 적어, 그 역할은 표가 연 길을 못 고른다",
            )


if __name__ == "__main__":
    unittest.main()
