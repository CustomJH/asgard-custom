#!/usr/bin/env python3
"""배차받은 쪽에 가는 입력 — 자기 배차의 주소, 못 정할 결정을 남기는 자리, 실패를 적는 명령.

호스트 모드에서 배차는 돌아오기만 하면 `succeeded` 로 접힌다. 그래서 목표에 못 닿은 시도와
끝낸 시도가 코디네이터에게 똑같이 보였고, 막힌 워커에게는 물을 자리가 아예 없었다 — 워커 계약이
`ask_coordinator` 를 네이티브 전용으로 못박고 있었기 때문이다. 이 시험이 잡는 것은 그 두 통로가
세 호스트에서 실제로 열리는가다.
"""

import json
import os
import unittest

from hookscaffold import deploy_library
from trinity_base import DCONTEXT, TrinityBase, run

from asgard.orchestration import board


class TestDispatchContext(TrinityBase):
    def payload(self, agent="asgard-worker", **extra):
        return json.dumps(
            {
                "agent_type": agent,
                "session_id": "s1",
                "cwd": self.root,
                "hook_event_name": "SubagentStart",
                **extra,
            }
        )

    def fire(self, agent="asgard-worker", **extra):
        """훅을 배포본 배치에서 돌린다 — 훅 파일 하나만 두면 그 배치는 실사가 아니다."""
        hooks = os.path.join(self.root, "hooks")
        os.makedirs(hooks, exist_ok=True)
        deploy_library(hooks)
        target = os.path.join(hooks, "dispatch-context.py")
        with open(DCONTEXT, encoding="utf-8") as src, open(target, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        return run(target, ["claude-code"], stdin=self.payload(agent, **extra), cwd=self.root)

    def block(self, proc):
        """주입된 본문 — 호스트가 실제로 읽는 칸에서 꺼낸다."""
        if not proc.stdout.strip():
            return ""
        return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_worker_is_told_where_its_attempt_lives(self):
        self.open_quest("--write-expected")
        body = self.block(self.fire())
        self.assertIn("<asgard-dispatch>", body)
        self.assertIn("quest  q1", body)
        self.assertIn("agent  asgard-worker", body)

    def test_failure_report_is_always_offered(self):
        """실패를 적는 명령은 Run 유무와 무관하다 — 그 자리가 없으면 실패가 성공으로 접힌다."""
        self.open_quest("--write-expected")
        body = self.block(self.fire())
        self.assertIn("siege done --quest q1 --agent asgard-worker --outcome failed", body)

    def test_question_line_appears_only_with_a_run(self):
        """`siege ask` 는 run id 를 요구한다. 없는 id 를 적어 주면 그 명령은 반드시 거절당한다."""
        self.open_quest("--write-expected")
        self.assertNotIn("siege ask", self.block(self.fire()))
        run_id = board.run_bind(self.root, "q1", "objective")["id"]
        body = self.block(self.fire())
        self.assertIn("siege ask %s" % run_id, body)
        self.assertIn("run    %s" % run_id, body)

    def test_verifier_is_not_addressed(self):
        """판정자의 이 자리는 verifier-context 가 쓴다. 판정 대상 Run 을 스스로 정산하게 두지 않는다."""
        self.open_quest("--write-expected")
        self.assertEqual(self.block(self.fire("asgard-verifier")), "")

    def test_silent_outside_asgard_and_without_a_quest(self):
        """퀘스트가 없으면 장부에 이 배차의 자리도 없고, 남의 에이전트에게는 할 말이 없다."""
        self.assertEqual(self.block(self.fire()), "")  # 아직 퀘스트를 안 열었다
        self.open_quest("--write-expected")
        self.assertEqual(self.block(self.fire("general-purpose")), "")

    def test_specialists_are_addressed_too(self):
        """딜리버리 전문가는 역할 이벤트를 안 남긴다 — 이 명령이 그쪽의 유일한 실패 보고 경로다."""
        self.open_quest("--write-expected")
        for agent in ("asgard-thor", "asgard-freyja", "asgard-eitri", "asgard-thor-lead"):
            self.assertIn("--agent %s --outcome failed" % agent, self.block(self.fire(agent)))


class TestDispatchContextIsWiredEverywhere(unittest.TestCase):
    """세 호스트에 다 걸려야 한다 — 한 곳이라도 빠지면 그 모드에서만 배차가 말없이 성공한다."""

    def test_every_host_template_mounts_it_on_subagent_start(self):
        from asgard.templates.claude import cc_settings
        from asgard.templates.codex import codex_config
        from asgard.templates.cursor import cursor_hooks_json

        claude = json.loads(cc_settings())
        mounted = [
            hook["command"]
            for block in claude["hooks"]["SubagentStart"]
            for hook in block["hooks"]
            if "dispatch-context" in hook["command"]
        ]
        self.assertEqual(len(mounted), 1, claude["hooks"]["SubagentStart"])
        self.assertNotIn("matcher", str(mounted))  # 매처는 안 건다 — 훅이 판정자를 스스로 거른다

        cursor = json.loads(cursor_hooks_json())
        self.assertTrue(
            any("dispatch-context" in row.get("command", "") for row in cursor["hooks"]["subagentStart"]),
            cursor["hooks"]["subagentStart"],
        )
        self.assertIn("dispatch-context.py", codex_config())

    def test_the_deployment_table_carries_it(self):
        from asgard.commands.setup import hook_files

        names = [os.path.basename(path) for path, _body in hook_files("/hooks", "claude-code")]
        self.assertIn("dispatch-context.py", names)


if __name__ == "__main__":
    unittest.main()
