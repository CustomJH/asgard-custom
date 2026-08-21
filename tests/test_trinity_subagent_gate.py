#!/usr/bin/env python3
"""서브에이전트 게이트 — 위임 사다리 경계와 역할별 기록 의무."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from trinity_base import (
    SUBGATE,
    TrinityBase,
    jout,
    run,
)


class TestSubagentGate(TrinityBase):
    """SubagentStop 역할 로그 규율 — 미기록 종료 block, 신선도는 앵커(마지막 상대 이벤트) 기준."""

    def sg(
        self,
        agent,
        session="s1",
        event="SubagentStop",
        agent_id="agent-1",
        tool_input=None,
        tool_use_id="tool-1",
    ):
        return run(
            SUBGATE,
            stdin=json.dumps(
                {
                    "agent_type": agent,
                    "agent_id": agent_id,
                    "session_id": session,
                    "cwd": self.root,
                    "hook_event_name": event,
                    "tool_name": "Agent" if event == "PreToolUse" else "",
                    "tool_input": tool_input or {},
                    "tool_use_id": tool_use_id,
                }
            ),
            cwd=self.root,
        )

    def blocked(self, p):
        out = jout(p)
        return out.get("decision") == "block", out.get("reason", "")

    def work(self, **extra):
        body = {"role": "worker", "event": "work", "commands": [{"cmd": "python3 app.py", "exit_code": 0}], **extra}
        return self.qlog("append", stdin=json.dumps(body))

    def test_every_role_has_a_delegation_entry(self):
        """판정이 `agent in AGENT_TARGETS` 라, 표에 없는 역할은 검사를 안 받고 무엇이든 띄운다."""
        from asgard.hooks.subagent_gate import AGENT_TARGETS
        from asgard.templates.roles import ROLE_AGENTS

        for fname, _ in ROLE_AGENTS:
            name = fname.removesuffix(".md")
            self.assertIn(name, AGENT_TARGETS, f"{name} 이 위임 표에 없어 무제한이다")

    def test_the_delegation_table_satisfies_its_two_invariants(self):
        """표가 아니라 불변식이 경계다 — 항목을 손으로 넓히면 오탐과 구멍이 번갈아 난다.

        층위 단조가 재귀·순환·무한 깊이를 한꺼번에 막고, 읽기 봉인이 검증 독립성을 진다."""
        from asgard.hooks.subagent_gate import closure_violations

        self.assertEqual(closure_violations(), [])

    def test_every_specialist_can_open_its_own_dispatch(self):
        """ "각 서브에이전트가 스스로 에이전트를 부른다" 는 계약 — ullr 만 종점이다."""
        from asgard.hooks.subagent_gate import AGENT_RANK, AGENT_TARGETS

        terminal = [name for name, targets in AGENT_TARGETS.items() if not targets]
        self.assertEqual(terminal, ["asgard-ullr"])
        # 사슬 길이는 층위 수가 못박는다 — 깊이 카운터가 없는 것이 여기서 안전한 이유다.
        self.assertEqual(max(AGENT_RANK.values()) - min(AGENT_RANK.values()), 4)

    def test_a_specialist_dispatches_downward_but_never_sideways(self):
        """thor → loki 는 통과, thor → thor 는 거절 — 같은 층끼리 못 부르는 것이 재귀를 끊는다."""
        self.open_quest()
        for agent, target in (
            ("asgard-thor", "asgard-loki"),
            ("asgard-freyja", "asgard-ullr"),
            ("asgard-eitri", "asgard-mimir"),
            ("asgard-loki", "asgard-ullr"),
            ("asgard-mimir", "asgard-ullr"),
        ):
            p = self.sg(agent, event="PreToolUse", tool_input={"subagent_type": target, "prompt": "go"})
            self.assertEqual(p.returncode, 0, f"{agent} → {target} 이 막혔다: {p.stderr}")
        for agent, target in (
            ("asgard-thor", "asgard-thor"),
            ("asgard-thor", "asgard-thor-lead"),
            ("asgard-freyja", "asgard-freyja"),
            ("asgard-loki", "asgard-loki"),
            ("asgard-ullr", "asgard-ullr"),
            ("asgard-ullr", "asgard-loki"),
            ("asgard-mimir", "asgard-thor"),
        ):
            p = self.sg(agent, event="PreToolUse", tool_input={"subagent_type": target, "prompt": "go"})
            self.assertEqual(p.returncode, 2, f"{agent} → {target} 이 통과했다")

    def test_read_only_roles_cannot_dispatch_a_write_capable_hand(self):
        """검증 독립성은 판정자가 고치는 손을 못 부르는 데서 나온다 — 계획자도 같다."""
        self.open_quest()
        for agent, target in (
            ("asgard-verifier", "asgard-worker"),
            ("asgard-verifier", "asgard-thor"),
            ("asgard-verifier", "asgard-freyja"),
            ("asgard-thinker", "asgard-worker"),
            ("asgard-thinker", "asgard-thor"),
        ):
            p = self.sg(agent, event="PreToolUse", tool_input={"subagent_type": target, "prompt": "go"})
            self.assertEqual(p.returncode, 2, f"{agent} → {target} 이 통과했다")

    def test_worker_cannot_pick_its_own_judge(self):
        """자기 일을 심판할 손을 자기가 고르면 판정은 판정이 아니다."""
        self.open_quest()
        for target in ("asgard-verifier", "asgard-thinker", "asgard-planner"):
            p = self.sg("asgard-worker", event="PreToolUse", tool_input={"subagent_type": target, "prompt": "go"})
            self.assertEqual(p.returncode, 2, f"worker → {target} 이 통과했다")

    def test_the_boundary_holds_without_an_open_quest(self):
        """퀘스트를 안 여는 것만으로 역할 경계가 사라지면 경계가 아니다.

        종전에는 활성 퀘스트 조회가 이 검사보다 먼저 빠져나갔다 (26-08-05 감사)."""
        p = self.sg(
            "asgard-verifier", event="PreToolUse", tool_input={"subagent_type": "asgard-worker", "prompt": "go"}
        )
        self.assertEqual(p.returncode, 2, p.stderr)
        # 허용된 짝은 퀘스트가 없어도 그대로 통과한다 (DIRECT·탐사 존중).
        ok = self.sg("asgard-verifier", event="PreToolUse", tool_input={"subagent_type": "asgard-loki", "prompt": "go"})
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_claude_settings_wire_mode_b_gate_at_start_dispatch_and_stop(self):
        from asgard.templates.claude import cc_settings

        hooks = json.loads(cc_settings())["hooks"]
        commands = {
            event: [hook["command"] for group in hooks[event] for hook in group["hooks"]]
            for event in ("SubagentStart", "PreToolUse", "SubagentStop")
        }
        self.assertTrue(any("subagent-gate.py" in command for command in commands["SubagentStart"]))
        self.assertTrue(any("subagent-gate.py" in command for command in commands["PreToolUse"]))
        self.assertTrue(any("subagent-gate.py" in command for command in commands["SubagentStop"]))

    def ticket(self, unit, access=None):
        return self.qlog(
            "append",
            stdin=json.dumps(
                {
                    "role": "thinker",
                    "event": "ticket",
                    "unit": unit,
                    "ticket_status": "todo",
                    "subtask": f"unit {unit}",
                    "changed_files": [f"u{unit}.txt"],
                    "access": access or [],
                }
            ),
        )

    def finish_ticket(self, unit):
        claim = jout(self.qlog("ticket-claim", "--unit", str(unit), "--worker", f"worker-{unit}"))
        return self.qlog(
            "ticket-finish",
            "--unit",
            str(unit),
            "--claim-token",
            claim["claim_token"],
            "--status",
            "done",
        )

    def test_subagent_start_records_hook_owned_distinct_agent_receipt(self):
        self.open_quest()
        self.sg("asgard-worker", event="SubagentStart", agent_id="worker-a")
        self.sg("asgard-worker", event="SubagentStart", agent_id="worker-b")
        receipts = os.path.join(self.root, ".asgard", "quest", "receipts", "q1")
        records = [json.load(open(os.path.join(receipts, name))) for name in sorted(os.listdir(receipts))]
        self.assertEqual({record["agent_id"] for record in records}, {"worker-a", "worker-b"})
        self.assertTrue(all(record["started_at"] for record in records))

    def test_subagent_stop_closes_only_its_started_receipt(self):
        self.open_quest()
        self.sg("asgard-worker", event="SubagentStart", agent_id="worker-a")
        self.sg("asgard-worker", event="SubagentStart", agent_id="worker-b")
        self.work(unit=1)
        self.sg("asgard-worker", event="SubagentStop", agent_id="worker-a")
        receipts = os.path.join(self.root, ".asgard", "quest", "receipts", "q1")
        a = json.load(open(os.path.join(receipts, "agent-worker-a.json")))
        b = json.load(open(os.path.join(receipts, "agent-worker-b.json")))
        self.assertGreater(a["stopped_at"], a["started_at"])
        self.assertIsNone(b["stopped_at"])

    def test_cursor_start_and_stop_bind_receipt_without_stop_id(self):
        self.open_quest()
        started = {
            "subagent_id": "cursor-worker-1",
            "subagent_type": "asgard-worker",
            "task": "implement unit",
            "parent_conversation_id": "conversation-1",
            "cwd": self.root,
        }
        self.assertEqual(run(SUBGATE, ["start"], stdin=json.dumps(started), cwd=self.root).returncode, 0)
        self.work()
        stopped = {
            "subagent_type": "asgard-worker",
            "task": "implement unit",
            "cwd": self.root,
        }
        result = run(SUBGATE, ["stop"], stdin=json.dumps(stopped), cwd=self.root)
        self.assertFalse(result.stdout.strip(), result.stdout)
        path = os.path.join(
            self.root,
            ".asgard",
            "quest",
            "receipts",
            "q1",
            "agent-cursor-worker-1.json",
        )
        receipt = json.load(open(path))
        self.assertEqual(receipt["session_id"], "cursor")
        self.assertIsNotNone(receipt["stopped_at"])

    def test_cursor_pretool_uses_explicit_permission_protocol(self):
        self.open_quest()
        payload = {
            "agent_type": "asgard-verifier",
            "tool_name": "Task",
            "tool_input": {"subagent_type": "asgard-worker"},
            "cwd": self.root,
        }
        denied = run(SUBGATE, ["pre"], stdin=json.dumps(payload), cwd=self.root)
        self.assertEqual(denied.returncode, 0)
        self.assertEqual(jout(denied).get("permission"), "deny")
        payload["tool_input"] = {"subagent_type": "asgard-loki"}
        allowed = run(SUBGATE, ["pre"], stdin=json.dumps(payload), cwd=self.root)
        self.assertEqual(jout(allowed), {"permission": "allow"})

    def test_agent_pretool_records_worker_dispatch_bound_to_unit(self):
        self.open_quest()
        result = self.sg(
            "",
            event="PreToolUse",
            tool_use_id="call-worker-7",
            tool_input={"subagent_type": "asgard-worker", "prompt": "[ASGARD_UNIT:7] implement isolated unit"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        path = os.path.join(self.root, ".asgard", "quest", "receipts", "q1", "dispatch-call-worker-7.json")
        dispatch = json.load(open(path))
        self.assertEqual(dispatch["unit"], 7)
        self.assertEqual(dispatch["agent_type"], "asgard-worker")

    def test_a_single_worker_dispatch_needs_no_unit_marker(self):
        """단위 티켓이 없는 퀘스트는 병렬 배정이 아니다 — 마커를 요구하면 워커를 못 띄운다.

        26-08-12 까지 이 호출이 exit 2 였고, 그래서 퀘스트를 연 세션에는 조율자가 직접
        편집하는 길밖에 남지 않았다 (워커 역할이 화면에 한 번도 안 떴다)."""
        self.open_quest()
        result = self.sg(
            "",
            event="PreToolUse",
            tool_use_id="call-solo",
            tool_input={"subagent_type": "asgard-worker", "prompt": "implement the whole quest"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_second_unmarked_worker_is_refused_while_the_first_still_runs(self):
        """단일 위임의 면제가 팬아웃까지 열면 티켓 없이 같은 파일을 둘이 고칠 수 있다.

        단위를 안 적었으니 파일 분리를 증명할 것도, `physical_worker_problem` 이 볼 것도 없다."""
        self.open_quest()
        first = self.sg(
            "",
            event="PreToolUse",
            tool_use_id="call-a",
            tool_input={"subagent_type": "asgard-worker", "prompt": "first"},
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.sg("asgard-worker", event="SubagentStart", agent_id="worker-a")
        second = self.sg(
            "",
            event="PreToolUse",
            tool_use_id="call-b",
            tool_input={"subagent_type": "asgard-worker", "prompt": "second"},
        )
        self.assertEqual(second.returncode, 2)
        self.assertIn("ASGARD_UNIT", second.stderr)
        # 앞선 워커가 끝나면 다음 단일 위임은 다시 열린다 — 막는 것은 겹침이지 재위임이 아니다.
        # work 이벤트가 있어야 종료 규율을 통과해 영수증이 닫힌다 (안 닫히면 계속 도는 것으로 읽힌다).
        self.work()
        self.sg("asgard-worker", event="SubagentStop", agent_id="worker-a")
        third = self.sg(
            "",
            event="PreToolUse",
            tool_use_id="call-c",
            tool_input={"subagent_type": "asgard-worker", "prompt": "third"},
        )
        self.assertEqual(third.returncode, 0, third.stderr)

    def test_a_worker_dispatch_needs_the_marker_once_units_exist(self):
        """티켓이 선언된 순간부터 영수증은 티켓에 묶여야 한다 — 모드 B 규율은 그대로다."""
        self.open_quest()
        self.ticket(1)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_use_id="call-unmarked",
            tool_input={"subagent_type": "asgard-worker", "prompt": "implement without a marker"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("ASGARD_UNIT", result.stderr)

    def test_verifier_pretool_blocks_until_every_ticket_is_done(self):
        self.open_quest()
        self.ticket(1)
        self.ticket(2)
        self.finish_ticket(1)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify the completed work"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unfinished ticket", result.stderr)

    def test_verifier_pretool_rejects_done_tickets_without_physical_worker_receipts(self):
        self.open_quest()
        self.ticket(1)
        self.ticket(2)
        self.finish_ticket(1)
        self.finish_ticket(2)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("physical worker", result.stderr.lower())

    def test_a_delivery_specialist_unit_leaves_a_completion_receipt(self):
        """단위를 thor 가 받아도 워커와 똑같이 세어져야 한다 — 안 그러면 판정자 배차가 막힌다.

        26-08-20 실측: 티켓 일곱이 전부 done 인데 판정자 디스패치가
        `physical worker receipts missing: expected 7 distinct completed agents, got 5` 로 거절됐다.
        빠진 둘은 `asgard-thor` 로 띄운 단위였고, 배차 영수증은 일곱 다 있는데 완료 영수증만 다섯이었다.
        `record_executor_lifecycle` 은 그때도 thor 를 알고 있었다 — 시작 훅이 안 불렸을 뿐이다."""
        self.open_quest()
        self.ticket(1)
        self.ticket(2)
        for unit, target in ((1, "asgard-worker"), (2, "asgard-thor")):
            self.sg(
                "",
                event="PreToolUse",
                tool_use_id=f"call-{unit}",
                tool_input={"subagent_type": target, "prompt": f"[ASGARD_UNIT:{unit}] implement"},
            )
        self.sg("asgard-worker", event="SubagentStart", agent_id="worker-a")
        self.sg("asgard-thor", event="SubagentStart", agent_id="thor-a")
        self.work(unit=1)
        self.sg("asgard-worker", event="SubagentStop", agent_id="worker-a")
        self.work(unit=2)
        self.sg("asgard-thor", event="SubagentStop", agent_id="thor-a")

        receipts = os.path.join(self.root, ".asgard", "quest", "receipts", "q1")
        records = [
            json.load(open(os.path.join(receipts, name)))
            for name in sorted(os.listdir(receipts))
            if name.startswith("agent-")
        ]
        thor = [record for record in records if record["agent_type"] == "asgard-thor"]
        self.assertEqual(len(thor), 1, "thor 의 완료 영수증이 없다 — 그 단위는 아무도 안 돈 것으로 읽힌다")
        self.assertTrue(thor[0]["started_at"] and thor[0]["stopped_at"])

        self.finish_ticket(1)
        self.finish_ticket(2)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_verifier_pretool_allows_distinct_overlapping_workers_for_parallel_wave(self):
        self.open_quest()
        self.ticket(1)
        self.ticket(2)
        for unit in (1, 2):
            self.sg(
                "",
                event="PreToolUse",
                tool_use_id=f"call-{unit}",
                tool_input={"subagent_type": "asgard-worker", "prompt": f"[ASGARD_UNIT:{unit}] implement"},
            )
        self.sg("asgard-worker", event="SubagentStart", agent_id="worker-a")
        self.sg("asgard-worker", event="SubagentStart", agent_id="worker-b")
        self.work(unit=1)
        self.sg("asgard-worker", event="SubagentStop", agent_id="worker-a")
        self.work(unit=2)
        self.sg("asgard-worker", event="SubagentStop", agent_id="worker-b")
        self.finish_ticket(1)
        self.finish_ticket(2)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def _handover_wave(self, session="s1"):
        """단위 둘을 겹쳐 돌린 웨이브 하나 — 로그와 영수증 양쪽이 같은 세션 이름을 쓴다.

        기본 헬퍼(`ticket`·`work`·`finish_ticket`)는 `--session` 을 안 넘겨 로그가 `host_session_id()`
        의 부재 표시를 적는다. 인수인계 축은 로그의 세션과 영수증의 세션이 만나는 자리라 여기서만
        둘을 붙여 쓴다."""
        self.qlog("open", "q1", "--criteria", "app.py prints ok", "--session", session)
        for unit in (1, 2):
            self.qlog(
                "append",
                "--session",
                session,
                stdin=json.dumps(
                    {
                        "role": "thinker",
                        "event": "ticket",
                        "unit": unit,
                        "ticket_status": "todo",
                        "subtask": f"unit {unit}",
                        "changed_files": [f"u{unit}.txt"],
                        "access": [],
                    }
                ),
            )
            self.sg(
                "",
                session=session,
                event="PreToolUse",
                tool_use_id=f"call-{unit}",
                tool_input={"subagent_type": "asgard-worker", "prompt": f"[ASGARD_UNIT:{unit}] implement"},
            )
        self.sg("asgard-worker", session=session, event="SubagentStart", agent_id="worker-a")
        self.sg("asgard-worker", session=session, event="SubagentStart", agent_id="worker-b")
        for unit, agent_id in ((1, "worker-a"), (2, "worker-b")):
            self.qlog(
                "append",
                "--session",
                session,
                stdin=json.dumps({"role": "worker", "event": "work", "unit": unit}),
            )
            self.sg("asgard-worker", session=session, event="SubagentStop", agent_id=agent_id)
            claim = jout(self.qlog("ticket-claim", "--session", session, "--unit", str(unit), "--worker", f"w{unit}"))
            self.qlog(
                "ticket-finish",
                "--session",
                session,
                "--unit",
                str(unit),
                "--claim-token",
                claim["claim_token"],
                "--status",
                "done",
            )

    def test_a_session_that_took_the_quest_over_reads_the_previous_owner_receipts(self):
        """인수인계 — 앞 세션이 남긴 물리 영수증으로 이어받은 세션이 판정자를 세울 수 있어야 한다.

        영수증은 세션에 묶이는데 `quest-log attach` 는 퀘스트를 다른 세션에 넘긴다. 결속의 열쇠가
        터미널 세션이면 넘겨받은 쪽은 앞 세션의 영수증을 못 읽어, 워커가 물리적으로 다 돌았는데도
        그 퀘스트는 어느 세션에서도 판정을 못 받는다."""
        self._handover_wave(session="s1")
        self.qlog("attach", "q1", "--session", "s2")
        result = self.sg(
            "",
            session="s2",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_receipts_from_a_session_outside_the_quest_lineage_do_not_count(self):
        """반대 방향 — 로그가 이름을 안 적은 세션의 영수증은 그대로 안 센다.

        이 짝이 없으면 위 시험은 세션 결속을 통째로 지워도 초록이라, 아무 세션의 영수증이나
        빌려 쓸 수 있게 된다."""
        self.qlog("open", "q1", "--criteria", "app.py prints ok", "--session", "s1")
        for unit in (1, 2):
            self.qlog(
                "append",
                "--session",
                "s1",
                stdin=json.dumps(
                    {
                        "role": "thinker",
                        "event": "ticket",
                        "unit": unit,
                        "ticket_status": "todo",
                        "subtask": f"unit {unit}",
                        "changed_files": [f"u{unit}.txt"],
                        "access": [],
                    }
                ),
            )
        directory = os.path.join(self.root, ".asgard", "quest", "receipts", "q1")
        os.makedirs(directory, exist_ok=True)
        for unit, agent_id in ((1, "stranger-a"), (2, "stranger-b")):
            with open(os.path.join(directory, "agent-%s.json" % agent_id), "w") as handle:
                json.dump(
                    {
                        "schema": 1,
                        "quest_id": "q1",
                        "session_id": "s9",
                        "agent_type": "asgard-worker",
                        "agent_id": agent_id,
                        "started_at": 1,
                        "stopped_at": 2,
                    },
                    handle,
                )
            with open(os.path.join(directory, "dispatch-call-%s.json" % unit), "w") as handle:
                json.dump(
                    {
                        "schema": 1,
                        "quest_id": "q1",
                        "session_id": "s9",
                        "agent_type": "asgard-worker",
                        "unit": str(unit),
                        "quest_turn": 1,
                    },
                    handle,
                )
        for unit in (1, 2):
            claim = jout(self.qlog("ticket-claim", "--session", "s1", "--unit", str(unit), "--worker", f"w{unit}"))
            self.qlog(
                "ticket-finish",
                "--session",
                "s1",
                "--unit",
                str(unit),
                "--claim-token",
                claim["claim_token"],
                "--status",
                "done",
            )
        result = self.sg(
            "",
            session="s1",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("physical worker", result.stderr.lower())

    def test_verifier_pretool_rejects_sequential_workers_for_parallel_wave(self):
        self.open_quest()
        self.ticket(1)
        self.ticket(2)
        for unit, agent_id in ((1, "worker-a"), (2, "worker-b")):
            self.sg(
                "",
                event="PreToolUse",
                tool_use_id=f"call-{unit}",
                tool_input={"subagent_type": "asgard-worker", "prompt": f"[ASGARD_UNIT:{unit}] implement"},
            )
            self.sg("asgard-worker", event="SubagentStart", agent_id=agent_id)
            self.work(unit=unit)
            self.sg("asgard-worker", event="SubagentStop", agent_id=agent_id)
            self.finish_ticket(unit)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("overlap", result.stderr.lower())

    def test_verifier_pretool_unit_marker_allows_early_verification_of_disjoint_done_unit(self):
        self.open_quest()
        self.ticket(1)
        self.ticket(2)
        self.finish_ticket(1)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "[ASGARD_UNIT:1] verify unit 1 now"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_verifier_pretool_unit_marker_denies_when_unit_not_done(self):
        self.open_quest()
        self.ticket(1)
        self.ticket(2)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "[ASGARD_UNIT:1] verify unit 1 now"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("not done", result.stderr.lower())

    def test_verifier_pretool_unit_marker_denies_when_overlapping_unit_still_open(self):
        self.open_quest()
        self.qlog(
            "append",
            stdin=json.dumps(
                {
                    "role": "thinker",
                    "event": "ticket",
                    "unit": 1,
                    "ticket_status": "todo",
                    "subtask": "unit 1",
                    "changed_files": ["shared.py"],
                }
            ),
        )
        self.qlog(
            "append",
            stdin=json.dumps(
                {
                    "role": "thinker",
                    "event": "ticket",
                    "unit": 2,
                    "ticket_status": "todo",
                    "subtask": "unit 2",
                    "changed_files": ["shared.py"],
                }
            ),
        )
        self.finish_ticket(1)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "[ASGARD_UNIT:1] verify unit 1 now"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("overlap", result.stderr.lower())

    def test_the_unit_executor_set_is_the_workers_write_capable_ladder(self):
        """단위를 끝낼 수 있는 손 = 워커 + 워커가 부를 수 있는 쓰기 가능한 딜리버리.

        표를 손으로 넓히면 오탐과 구멍이 번갈아 나므로, 집합이 아니라 이 성질을 시험한다."""
        from asgard.hooks.subagent_gate import (
            AGENT_TARGETS,
            READ_ONLY_AGENTS,
            UNDISPATCHABLE,
            UNIT_EXECUTORS,
        )

        self.assertIn("asgard-worker", UNIT_EXECUTORS)
        # 읽기 전용은 트리를 안 고치니 단위를 끝낼 수 없고, 판정자·사고자는 배차 대상이 아니다.
        self.assertEqual(UNIT_EXECUTORS & READ_ONLY_AGENTS, frozenset())
        self.assertEqual(UNIT_EXECUTORS & UNDISPATCHABLE, frozenset())
        # 워커가 못 부르는 손은 단위를 받을 길이 없다.
        self.assertEqual(UNIT_EXECUTORS - ({"asgard-worker"} | AGENT_TARGETS["asgard-worker"]), frozenset())
        # 워커가 부를 수 있는 쓰기 가능한 손은 전부 들어 있다 (표면별 위임이 계약이다).
        self.assertEqual((AGENT_TARGETS["asgard-worker"] - READ_ONLY_AGENTS) - UNIT_EXECUTORS, frozenset())

    def test_a_unit_run_by_a_delivery_specialist_counts_as_a_physical_receipt(self):
        """워커는 변경 표면에 따라 thor·freyja·eitri 로 내려간다 — 그 단위도 실제로 돈 단위다.

        영수증 검사가 `asgard-worker` 만 세던 동안, thor 에게 보낸 단위는 배차 영수증이 없는 것으로
        읽혀 판정자 배차가 통째로 막혔다 (26-08-12)."""
        self.open_quest()
        self.ticket(1)
        self.ticket(2)
        for unit, target in ((1, "asgard-worker"), (2, "asgard-thor")):
            dispatch = self.sg(
                "",
                event="PreToolUse",
                tool_use_id=f"call-{unit}",
                tool_input={"subagent_type": target, "prompt": f"[ASGARD_UNIT:{unit}] implement"},
            )
            self.assertEqual(dispatch.returncode, 0, dispatch.stderr)
        with open(os.path.join(self.root, ".asgard", "quest", "receipts", "q1", "dispatch-call-2.json")) as handle:
            self.assertEqual(json.load(handle)["agent_type"], "asgard-thor")
        self.sg("asgard-worker", event="SubagentStart", agent_id="worker-a")
        self.sg("asgard-thor", event="SubagentStart", agent_id="thor-b")
        self.work(unit=1)
        self.sg("asgard-worker", event="SubagentStop", agent_id="worker-a")
        self.sg("asgard-thor", event="SubagentStop", agent_id="thor-b")
        self.finish_ticket(1)
        self.finish_ticket(2)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_redispatched_unit_does_not_retroactively_break_its_successor(self):
        """선행이 끝난 **뒤** 배차된 후행이 나중 재배차 때문에 위반으로 읽히면 안 된다.

        배차 영수증의 턴은 배차 시점에 이미 적혀 있던 마지막 턴이라, 선행의 done 직후 배차하면
        두 값이 같아진다 — 실측 asgard-coherence-refactor-260812 (tier-table 배차 21 ·
        recall-split done 21) 에서 판정자 배차가 그렇게 막혔다."""
        self.open_quest()
        self.ticket(1)
        self.ticket(2, access=[1])
        for unit, agent_id in ((1, "worker-a"), (2, "worker-b")):
            self.sg(
                "",
                event="PreToolUse",
                tool_use_id=f"call-{unit}",
                tool_input={"subagent_type": "asgard-worker", "prompt": f"[ASGARD_UNIT:{unit}] implement"},
            )
            self.sg("asgard-worker", event="SubagentStart", agent_id=agent_id)
            self.work(unit=unit)
            self.sg("asgard-worker", event="SubagentStop", agent_id=agent_id)
            self.finish_ticket(unit)
        # 끝난 단위를 다시 배차한다 (재검증·후속 수리).
        again = self.sg(
            "",
            event="PreToolUse",
            tool_use_id="call-1-again",
            tool_input={"subagent_type": "asgard-worker", "prompt": "[ASGARD_UNIT:1] re-check unit 1"},
        )
        self.assertEqual(again.returncode, 0, again.stderr)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_late_redispatch_cannot_hide_an_early_first_dispatch(self):
        """막아야 할 것은 그대로 막힌다 — 이른 첫 배차는 나중 재배차로 덮이지 않는다."""
        self.open_quest()
        self.ticket(1)
        self.ticket(2, access=[1])
        self.sg(
            "",
            event="PreToolUse",
            tool_use_id="call-2-early",
            tool_input={"subagent_type": "asgard-worker", "prompt": "[ASGARD_UNIT:2] implement too early"},
        )
        for unit, agent_id in ((1, "worker-a"), (2, "worker-b")):
            if unit == 1:
                self.sg(
                    "",
                    event="PreToolUse",
                    tool_use_id="call-1",
                    tool_input={"subagent_type": "asgard-worker", "prompt": "[ASGARD_UNIT:1] implement"},
                )
            else:
                self.sg(
                    "",
                    event="PreToolUse",
                    tool_use_id="call-2-again",
                    tool_input={"subagent_type": "asgard-worker", "prompt": "[ASGARD_UNIT:2] implement again"},
                )
            self.sg("asgard-worker", event="SubagentStart", agent_id=agent_id)
            self.work(unit=unit)
            self.sg("asgard-worker", event="SubagentStop", agent_id=agent_id)
            self.finish_ticket(unit)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("dependency", result.stderr.lower())

    def test_verifier_pretool_rejects_dependent_worker_dispatched_before_fan_in(self):
        self.open_quest()
        self.ticket(1)
        self.ticket(2, access=[1])
        self.sg(
            "",
            event="PreToolUse",
            tool_use_id="call-2-early",
            tool_input={"subagent_type": "asgard-worker", "prompt": "[ASGARD_UNIT:2] implement too early"},
        )
        for unit, agent_id in ((1, "worker-a"), (2, "worker-b")):
            if unit == 1:
                self.sg(
                    "",
                    event="PreToolUse",
                    tool_use_id="call-1",
                    tool_input={"subagent_type": "asgard-worker", "prompt": "[ASGARD_UNIT:1] implement"},
                )
            self.sg("asgard-worker", event="SubagentStart", agent_id=agent_id)
            self.work(unit=unit)
            self.sg("asgard-worker", event="SubagentStop", agent_id=agent_id)
            self.finish_ticket(unit)
        result = self.sg(
            "",
            event="PreToolUse",
            tool_input={"subagent_type": "asgard-verifier", "prompt": "verify"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("dependency", result.stderr.lower())

    def test_no_active_quest_allows(self):
        b, _ = self.blocked(self.sg("asgard-verifier"))
        self.assertFalse(b)

    def test_non_trinity_agent_allows(self):
        self.open_quest()
        self.work()
        b, _ = self.blocked(self.sg("asgard-loki"))
        self.assertFalse(b)

    def test_verifier_agent_dispatch_is_readonly_only(self):
        self.open_quest()
        allowed = self.sg(
            "asgard-verifier", event="PreToolUse", tool_input={"subagent_type": "asgard-loki", "prompt": "review"}
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        for target in ("asgard-freyja", "asgard-thor", "asgard-eitri", ""):
            denied = self.sg(
                "asgard-verifier", event="PreToolUse", tool_input={"subagent_type": target, "prompt": "mutate"}
            )
            self.assertEqual(denied.returncode, 2, target)
            self.assertIn("role boundary", denied.stderr)

    def test_thor_lead_depth_and_target_boundary(self):
        self.open_quest()
        for target in ("asgard-thor", "asgard-loki"):
            allowed = self.sg(
                "asgard-thor-lead", event="PreToolUse", tool_input={"subagent_type": target, "prompt": "unit"}
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
        for target in ("asgard-thor-lead", "asgard-freyja", "asgard-eitri", ""):
            denied = self.sg(
                "asgard-thor-lead", event="PreToolUse", tool_input={"subagent_type": target, "prompt": "nested"}
            )
            self.assertEqual(denied.returncode, 2, target)

    def test_sub_thor_cannot_form_a_squad_of_its_own(self):
        """sub-Thor 는 아래층 읽기 전용만 연다 — 편대의 편대도, 옆 표면의 쓰기 손도 못 부른다."""
        self.open_quest()
        for target in ("asgard-loki", "asgard-ullr", "asgard-mimir"):
            allowed = self.sg(
                "asgard-thor", event="PreToolUse", tool_input={"subagent_type": target, "prompt": "nested"}
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
        for target in ("asgard-thor", "asgard-thor-lead", "asgard-freyja", "asgard-eitri", ""):
            denied = self.sg(
                "asgard-thor", event="PreToolUse", tool_input={"subagent_type": target, "prompt": "nested"}
            )
            self.assertEqual(denied.returncode, 2, target)

    def test_verifier_without_verify_blocks(self):
        self.open_quest()
        self.work()
        b, reason = self.blocked(self.sg("asgard-verifier"))
        self.assertTrue(b)
        self.assertIn("verify", reason)

    def test_verifier_with_evidence_pass_allows(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.work()
        self.verify("PASS")
        b, _ = self.blocked(self.sg("asgard-verifier"))
        self.assertFalse(b)

    def test_verifier_trivial_evidence_pass_blocks(self):
        self.open_quest()
        self.work()
        self.verify("PASS", commands=[{"cmd": "echo ok", "exit_code": 0}])
        b, reason = self.blocked(self.sg("asgard-verifier"))
        self.assertTrue(b)
        self.assertIn("evidence", reason)

    def test_verifier_fail_verdict_allows(self):
        # FAIL 판정은 증거 요건 없이도 유효한 역할 수행 — 이 게이트는 기록 규율만 본다
        self.open_quest()
        self.work()
        self.verify("FAIL", commands=[])
        b, _ = self.blocked(self.sg("asgard-verifier"))
        self.assertFalse(b)

    def test_worker_without_work_blocks(self):
        self.open_quest()
        b, reason = self.blocked(self.sg("asgard-worker"))
        self.assertTrue(b)
        self.assertIn("work", reason)

    def test_worker_with_work_allows(self):
        self.open_quest()
        self.work()
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertFalse(b)

    def test_worker_stale_work_before_verify_blocks(self):
        # 앵커 신선도 — 직전 판정(verify) 이후의 work만 이번 턴 기록으로 인정
        self.open_quest()
        self.work()
        self.verify("FAIL")
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertTrue(b)
        self.work()
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertFalse(b)

    def test_thinker_replan_freshness(self):
        # open의 plan 기록으로 첫 thinker는 통과, verify 이후 재계획 미기록은 block
        self.open_quest()
        b, _ = self.blocked(self.sg("asgard-thinker"))
        self.assertFalse(b)
        self.work()
        self.verify("FAIL")
        b, _ = self.blocked(self.sg("asgard-thinker"))
        self.assertTrue(b)
        self.qlog("append", stdin=json.dumps({"role": "thinker", "event": "plan", "criteria": ["fix"]}))
        b, _ = self.blocked(self.sg("asgard-thinker"))
        self.assertFalse(b)

    def test_two_block_cap_then_fail_open(self):
        self.open_quest()
        for _ in range(2):
            b, _ = self.blocked(self.sg("asgard-worker"))
            self.assertTrue(b)
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertFalse(b)  # 3번째 = 통과 (최종 담보는 verifier-gate)

    def test_pass_resets_block_counter(self):
        self.open_quest()
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertTrue(b)
        self.work()
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertFalse(b)  # 통과 → 카운터 리셋
        self.verify("FAIL")
        b, _ = self.blocked(self.sg("asgard-worker"))
        self.assertTrue(b)  # 리셋 후 새 위반은 다시 계수

    def test_the_recorded_failure_survives_normalization(self):
        """계약이 가리키는 경로가 실제로 이어지는가 — 이벤트를 정규화가 통과시켜야 읽는 쪽이 본다.

        `_role_outcome` 은 저장된 JSONL 만 읽는다. `normalize` 의 화이트리스트에 이 칸이 없던
        동안, 계약 네 자리(워커 계약·AGENTS.md·모드 B 절·이 훅의 도크스트링)가 죽은 경로를
        가리키고 있었고 단위 시험은 정규화를 안 거친 dict 를 넣어 초록이었다."""
        from asgard.hooks.subagent_gate import _role_outcome

        self.open_quest("--write-expected")
        self.assertEqual(
            self.qlog("append", stdin=json.dumps({"role": "worker", "event": "work", "outcome": "failed"})).returncode,
            0,
        )
        log = os.path.join(self.root, ".asgard", "quest", "q1.jsonl")
        events = [json.loads(line) for line in open(log, encoding="utf-8") if line.strip()]
        work = [event for event in events if event.get("event") == "work"]
        self.assertEqual(_role_outcome(work[-1]), "failed")

    def test_an_unknown_outcome_is_refused_instead_of_dropped(self):
        """오타를 받아 주면 그 칸이 정규화에서 사라져 배차가 succeeded 로 접힌다 — 실패를 적었다고
        믿는 쪽과 성공을 읽는 쪽이 갈린다. `verdict` 와 같은 규약으로 쓰는 자리에서 거절한다."""
        self.open_quest("--write-expected")
        for value in ("faild", "FAILURE", "done"):
            proc = self.qlog("append", stdin=json.dumps({"role": "worker", "event": "work", "outcome": value}))
            self.assertEqual(proc.returncode, 2, value)
            self.assertIn("outcome must be", proc.stdout + proc.stderr)
        # 아는 값 둘은 그대로 받는다. 성공은 기본값이라 칸을 안 남긴다.
        for value in ("succeeded", "failed"):
            self.assertEqual(
                self.qlog("append", stdin=json.dumps({"role": "worker", "event": "work", "outcome": value})).returncode,
                0,
                value,
            )
        log = os.path.join(self.root, ".asgard", "quest", "q1.jsonl")
        events = [json.loads(line) for line in open(log, encoding="utf-8") if line.strip()]
        self.assertEqual([e.get("outcome") for e in events if e.get("event") == "work"], [None, "failed"])

    def test_a_role_that_recorded_a_failure_is_settled_as_one(self):
        """돌아왔다는 것과 목표에 닿았다는 것은 다른 사실이다 — 종료 훅이 보는 것은 앞의 하나뿐이라,
        뒤의 하나는 역할이 자기 이벤트에 적고 이 함수가 그것만 읽는다."""
        from asgard.hooks.subagent_gate import _role_outcome

        self.assertEqual(_role_outcome({"event": "work", "outcome": "failed"}), "failed")
        self.assertEqual(_role_outcome({"event": "work", "outcome": "FAILED"}), "failed")
        # 안 적은 것·모르는 값·판정 결과는 전부 성공으로 접는다 (실패로 접으면 회로 차단을 먹는다).
        for event in ({"event": "work"}, {"event": "work", "outcome": "faild"}, {"event": "verify", "verdict": "FAIL"}):
            self.assertEqual(_role_outcome(event), "succeeded", event)

    def test_the_close_call_only_names_an_outcome_when_it_is_not_the_default(self):
        """기본값을 매번 적으면 장부 명령이 길어지기만 한다 — 다른 값일 때만 얹힌다."""
        from asgard.hooks import subagent_gate

        seen: list[list[str]] = []
        original = subagent_gate.ledger_call
        subagent_gate.ledger_call = lambda root, argv: seen.append(argv) or True  # ty: ignore[invalid-assignment]
        try:
            subagent_gate.siege_close(self.root, "q1", "asgard-worker")
            subagent_gate.siege_close(self.root, "q1", "asgard-worker", outcome="failed")
        finally:
            subagent_gate.ledger_call = original
        self.assertNotIn("--outcome", seen[0])
        self.assertEqual(seen[1][-2:], ["--outcome", "failed"])

    def test_malformed_stdin_fail_open(self):
        p = run(SUBGATE, stdin="not-json", cwd=self.root)
        self.assertEqual(p.returncode, 0)

    def test_subagent_gate_runs_under_host_python3_named_by_shebang(self):
        p = subprocess.run(["python3", SUBGATE], input="not-json", capture_output=True, text=True, cwd=self.root)
        self.assertEqual(p.returncode, 0, p.stderr)


class TestBlockCapClosesTheLedger(unittest.TestCase):
    """상한을 넘겨 통과시키는 종료도 배차 장부에서 접힌다.

    그 경로는 `main` 의 `siege_close` 앞에서 프로세스를 끝낸다. 안 접으면 그 시도가 `ready` 로
    남고, 26-08-21 에 이 저장소에서 센 안 끝난 판정자 배차 37건과 같은 자리가 된다 — `siege` 는
    영영 "도는 중"이라 말하고 `verifier-gate` 는 그것을 "판정이 오는 중"으로 읽는다."""

    def setUp(self):
        from asgard.hooks import subagent_gate as sg

        self.sg = sg
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        self.closed = []
        for name, fake in (
            ("siege_close", lambda root, qid, agent, **kw: self.closed.append((qid, agent, kw))),
            ("heal_ledger", lambda *args: True),
        ):
            patcher = mock.patch.object(sg, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed_counter(self, agent, count):
        with open(os.path.join(self.root, ".asgard", "subgate-s1.json"), "w", encoding="utf-8") as handle:
            json.dump({agent: count}, handle)

    def call_block(self, agent, qid="q1"):
        with self.assertRaises(SystemExit) as caught:
            self.sg.block(self.root, "s1", agent, "reason", qid=qid)
        return caught.exception.code

    def test_the_turn_that_exceeds_the_cap_settles_its_dispatch(self):
        self.seed_counter("asgard-verifier", self.sg.MAX_BLOCKS)
        self.assertEqual(self.call_block("asgard-verifier"), 0)
        self.assertEqual(len(self.closed), 1, "상한 초과 통과가 장부를 안 접었다")
        qid, agent, kwargs = self.closed[0]
        self.assertEqual((qid, agent), ("q1", "asgard-verifier"))
        self.assertEqual(kwargs["outcome"], "failed", "역할 이벤트 없이 끝난 시도는 목표에 안 닿았다")

    def test_a_block_under_the_cap_leaves_the_dispatch_open(self):
        """아직 안 끝난 역할이다 — 여기서 접으면 뒤따르는 종료가 접을 것을 못 찾는다."""
        self.assertEqual(self.call_block("asgard-verifier"), 0)
        self.assertEqual(self.closed, [])

    def test_without_a_quest_there_is_nothing_to_close(self):
        """퀘스트가 없으면 이 종료는 장부에 없는 디스패치다 — 없는 것을 접으면 안 된다."""
        self.seed_counter("asgard-verifier", self.sg.MAX_BLOCKS)
        self.assertEqual(self.call_block("asgard-verifier", qid=""), 0)
        self.assertEqual(self.closed, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
