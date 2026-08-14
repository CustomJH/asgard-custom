#!/usr/bin/env python3
"""완료 증거 판정 — 증거 하한, 무변경 퀘스트, 기준 계약, 검증 비용 상한."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from trinity_base import (
    TrinityBase,
    jout,
)


class TestGoodhartEvidence(TrinityBase):
    """PASS 증거 trivial 필터 — `true`/`echo` 한 방이 증거로 성립하던 구멍 (게이트·전이 동일 기준)."""

    def test_trivial_only_pass_rejected_by_transition_and_gate(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "true", "exit_code": 0}, {"cmd": "echo ok", "exit_code": 0}])
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "VERIFIER")  # 재검증 강제
        out = jout(self.gate())
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("evidence", out.get("reason", ""))

    def test_real_command_pass_allowed(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "true", "exit_code": 0}, {"cmd": "python3 app.py", "exit_code": 0}])
        self.assertNotEqual(jout(self.gate()).get("decision"), "block")

    def test_observation_only_commands_are_not_completion_evidence(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify(
            "PASS",
            commands=[
                {"cmd": "pwd", "exit_code": 0},
                {"cmd": "git status --porcelain", "exit_code": 0},
                {"cmd": "ls -la app.py", "exit_code": 0},
                {"cmd": "cat app.py", "exit_code": 0},
                {"cmd": "xxd app.py", "exit_code": 0},
                {"cmd": "wc -c app.py", "exit_code": 0},
            ],
        )
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "VERIFIER")
        self.assertEqual(jout(self.gate()).get("decision"), "block")


class TestNoChangeEvidence(TrinityBase):
    """무변경(diff EMPTY) 퀘스트 — 트리 관측(git status/diff)이 곧 PASS 증거.

    trivial 필터가 관측 명령을 전부 걸러내면 무변경 퀘스트는 영원히 PASS 불가 교착이 된다
    (26-07-21 "안녕" 실측: Verifier PASS 5연속 무효화 → 예산 소진). diff가 있는 퀘스트는
    종전대로 관측-only PASS를 거부한다 (TestGoodhartEvidence가 회귀 쐐기)."""

    def test_inspection_evidence_classifier(self):
        from asgard.hooks.quest_log import inspection_evidence

        inspecting = [
            "git status --porcelain",
            "git diff --stat",
            'git -C "/tmp/some path" status --porcelain',
            "git log --oneline -5",
            "git -c core.pager=cat diff",
        ]
        not_inspecting = [
            "echo ok",
            "true",
            "python3 -c \"print('hi')\"",
            "ls -la",
            "git push",
            "git commit -m x",
            "git -C add",  # -C 인자 스킵 — add를 sub로 오인하지 않되 잘린 명령도 증거 아님
        ]
        for cmd in inspecting:
            self.assertTrue(inspection_evidence(cmd), cmd)
        for cmd in not_inspecting:
            self.assertFalse(inspection_evidence(cmd), cmd)

    def test_noop_quest_observational_pass_approves_and_closes(self):
        self.open_quest()
        self.qlog("append", "--role", "worker", "--event", "work")  # 무변경 work (no-op 과업)
        self.verify(
            "PASS",
            commands=[
                {"cmd": "git status --porcelain", "exit_code": 0},
                {"cmd": "git diff --stat", "exit_code": 0},
            ],
        )
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "DONE")
        closed = self.qlog("close")
        self.assertEqual(closed.returncode, 0, closed.stderr)

    def test_noop_quest_trivial_only_pass_still_rejected(self):
        # 무변경이어도 관측 명령이 없으면 무증거 — true/echo는 여전히 증거가 아니다 (Goodhart 유지)
        self.open_quest()
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "true", "exit_code": 0}, {"cmd": "echo ok", "exit_code": 0}])
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "VERIFIER")


class TestNoChangeBaselineVerify(TrinityBase):
    """명시적 쓰기 기대가 없는 무변경(diff EMPTY) work의 0-LLM 하네스 판정 출구 — 전이가 BASELINE_VERIFY를 배정하고
    verify-baseline이 트리 관측(git status)으로 판정을 기록한다. LLM Verifier가 반증 불가능한
    합성 기준을 재량 검증하던 잔여 낭비 경로 봉합 (26-07-23 감사)."""

    def events(self):
        path = os.path.join(self.root, ".asgard", "quest", "q1.jsonl")
        return [json.loads(line) for line in open(path, encoding="utf-8")]

    def test_transition_routes_unflagged_nochange_work_to_baseline_verify(self):
        self.open_quest()
        self.qlog("append", "--role", "worker", "--event", "work")
        nxt = jout(self.qlog("next"))
        self.assertEqual(nxt["next_role"], "BASELINE_VERIFY")
        self.assertIn("no-change", nxt["why"])

    def test_verify_baseline_nochange_passes_with_inspection_no_baseline_attach(self):
        self.open_quest()
        self.qlog("append", "--role", "worker", "--event", "work")
        vb = jout(self.qlog("verify-baseline"))
        self.assertEqual(vb["verdict"], "PASS")
        last_verify = [e for e in self.events() if e.get("event") == "verify"][-1]
        self.assertNotIn("baseline", last_verify)  # 무변경은 red 원인 불가 — 베이스라인 미부착
        self.assertEqual(last_verify["commands"][0]["cmd"], "git status --porcelain")
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_nochange_quest_not_hostage_to_red_baseline(self):
        # 전 트리 체크 red(타 세션 잔여물 등)가 무변경 퀘스트를 인질로 잡지 않는다
        self.policy(baseline_checks=["false"])
        self.open_quest()
        self.qlog("append", "--role", "worker", "--event", "work")
        vb = jout(self.qlog("verify-baseline"))
        self.assertEqual(vb["verdict"], "PASS")
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_nochange_llm_pass_append_skips_baseline_attach(self):
        self.policy(baseline_checks=["false"])
        self.open_quest()
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "git status --porcelain", "exit_code": 0}])
        last_verify = [e for e in self.events() if e.get("event") == "verify"][-1]
        self.assertNotIn("baseline", last_verify)
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_changed_quest_still_attaches_baseline(self):
        # 변경이 있는 퀘스트는 종전대로 하네스 베이스라인이 붙는다 (게이트 무결성 회귀 쐐기)
        self.policy(baseline_checks=["false"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work", stdin=json.dumps({"changed_files": ["app.py"]}))
        self.verify("PASS", level="full")
        last_verify = [e for e in self.events() if e.get("event") == "verify"][-1]
        self.assertEqual((last_verify.get("baseline") or {}).get("state"), "red")
        self.assertEqual(self.qlog("close").returncode, 1)  # baseline-red → close 거부 유지


class TestCompletionFunnel(TrinityBase):
    """완료 판정 단일 퍼널 — REJECTED는 어떤 경로(transition·close·--force)로도 승인 승격 금지."""

    def sentinel(self, *paths, session="s1"):
        d = os.path.join(self.root, ".asgard", "state")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "writes-" + session + ".json"), "w") as f:
            json.dump(list(paths), f)

    def test_forced_close_writes_no_last_and_orphan_blocks(self):
        # 우회 체인 봉쇄: 무증거 PASS → close --force → (구) LAST 면제로 Stop 통과 → (신) LAST 미기록·차단
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", level="full", commands=[])  # 증거 없는 PASS
        self.assertEqual(self.qlog("close").returncode, 1)  # 퍼널 REJECTED → close 거부
        forced = jout(self.qlog("close", "--force"))
        self.assertTrue(forced["forced"])
        self.assertIs(forced["gate_exempt"], False)
        self.assertIn("no-evidence", forced["rejected"])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "LAST")))
        self.sentinel("app.py")
        out = jout(self.gate())
        self.assertEqual(out.get("decision"), "block")  # forced close는 게이트 면제가 아니다

    def test_verified_close_writes_last_and_exempts(self):
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", level="full")
        closed = jout(self.qlog("close"))
        self.assertFalse(closed["forced"])
        self.assertNotIn("gate_exempt", closed)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".asgard", "quest", "LAST")))
        self.sentinel("app.py")
        self.assertNotEqual(jout(self.gate()).get("decision"), "block")  # 검증된 close만 면제

    def test_close_requires_criteria_like_gate(self):
        # criteria 없는 PASS — 게이트는 차단하는데 close가 통과시키던 판정 분열 봉합
        self.assertEqual(self.qlog("open", "q1").returncode, 0)  # criteria 미지정
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", level="full")
        nxt = jout(self.qlog("next", "--write-expected"))
        self.assertEqual(nxt["next_role"], "VERIFIER")  # DONE 금지
        self.assertIn("criteria", nxt["why"])
        p = self.qlog("close")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no-criteria", p.stderr)
        self.assertEqual(jout(self.gate()).get("decision"), "block")  # 게이트와 동일 판정

    def test_escalate_close_does_not_publish_verified_last(self):
        # ESCALATE is a termination receipt, not a verified-state capability.
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify("ESCALATE", commands=[])
        closed = jout(self.qlog("close"))
        self.assertFalse(closed["forced"])
        self.assertFalse(closed["gate_exempt"])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "LAST")))


class TestDeepEvidenceFloor(TrinityBase):
    """깊은 변경은 증거 하나로 닫히지 않는다 — 안 깨지면 얕은 채로 끝나던 구멍 봉합.

    26-08-06 라이브에서 5파일 리팩터가 계약 명령 `python3 test_basic.py` exit 0 하나로
    PASS 했다. 실패가 안 났으니 3-실패 재계획도 안 돌아, 가장 어려운 과업이 가장 얕게
    종결됐다. 하한은 위험 축(full_verify_risk)에만 걸고 작은 변경은 종전 그대로 둔다."""

    def deep_write(self):
        """non-test 파일 3개 초과 — small_write(2파일) 위 = full_verify_risk."""
        for i in range(4):
            self.write("mod_%d.py" % i, "v = %d\n" % i)

    def test_deep_change_with_one_evidence_item_is_rejected(self):
        self.open_quest()
        self.deep_write()
        self.verify(commands=[{"cmd": "python3 -c 'import mod_0'", "exit_code": 0}])
        state = jout(self.qlog("state"))
        self.assertEqual(state["pass_evidence_breadth"], 1)
        nxt = jout(self.qlog("next"))
        self.assertEqual(nxt["next_role"], "VERIFIER")
        self.assertIn("evidence item", nxt["why"])
        self.assertNotEqual(self.qlog("close", "q1").returncode, 0)

    def test_a_second_independent_command_closes_it(self):
        self.open_quest()
        self.deep_write()
        self.verify(
            commands=[
                {"cmd": "python3 -c 'import mod_0'", "exit_code": 0},
                {"cmd": "python3 -m compileall -q .", "exit_code": 0},
            ]
        )
        self.assertEqual(jout(self.qlog("state"))["pass_evidence_breadth"], 2)
        self.assertEqual(jout(self.qlog("next"))["next_role"], "DONE")
        self.assertEqual(self.qlog("close", "q1").returncode, 0)

    def test_the_same_command_twice_is_one_evidence_item(self):
        """되풀이 실행은 새 증거가 아니다 — 하한을 명령 복사로 넘기지 못한다."""
        self.open_quest()
        self.deep_write()
        self.verify(
            commands=[
                {"cmd": "python3 -c 'import mod_0'", "exit_code": 0},
                {"cmd": "python3 -c 'import mod_0'", "exit_code": 0},
            ]
        )
        self.assertEqual(jout(self.qlog("state"))["pass_evidence_breadth"], 1)
        self.assertEqual(jout(self.qlog("next"))["next_role"], "VERIFIER")

    def test_small_change_keeps_the_single_evidence_path(self):
        """작은 비민감 변경은 하한을 지지 않는다 — 기본 low 의 속도 선택 유지."""
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify(commands=[{"cmd": "python3 app.py", "exit_code": 0}])
        self.assertEqual(jout(self.qlog("next"))["next_role"], "DONE")
        self.assertEqual(self.qlog("close", "q1").returncode, 0)

    def test_gate_blocks_the_same_thin_pass(self):
        """전이·close 와 Stop 게이트가 같은 판정을 낸다 (단일 출처)."""
        self.open_quest()
        self.deep_write()
        self.verify(commands=[{"cmd": "python3 -c 'import mod_0'", "exit_code": 0}])
        out = jout(self.gate())
        self.assertEqual(out["decision"], "block")
        self.assertEqual(out["code"], "thin-evidence")


class TestVerifyCostControls(TrinityBase):
    """판정 기준은 그대로 두고 중복 실행과 중복 대기만 없앤다 — 판정 결과가 같은지까지 함께 본다."""

    def last_event(self):
        with open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")) as handle:
            return json.loads(handle.read().splitlines()[-1])

    def test_deleted_test_is_full_level_from_the_first_verdict(self):
        """level 과 full_required 가 어긋나면 micro PASS 가 거부돼 같은 diff 를 두 번 판정한다.

        테스트를 지운 작은 diff 는 full_required 라서, 전이가 micro 를 배정하면 그 PASS 는
        completion_decision 이 micro-pass 로 되돌린다 — 판정 결과는 같고 Verifier 턴만 하나 늘었다."""
        self.policy(verify_level="high")
        self.write("tests/test_app.py", "def test_x():\n    assert True\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "add test"], check=True)
        self.open_quest()
        os.remove(os.path.join(self.root, "tests", "test_app.py"))
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["verify_level"], "full")

    SLOW_TEST = (
        "import time, unittest\n\n\nclass T(unittest.TestCase):\n    def test_slow(self):\n        time.sleep(5)\n"
    )

    def test_a_timed_out_check_is_not_paid_for_twice(self):
        """timeout 은 red 도 green 도 아니다 (증거 없음). 다시 돌려도 판정은 그대로라 기다림만 남는다."""
        self.write("slow_test.py", self.SLOW_TEST)
        self.policy(baseline_checks=["python3 -m unittest slow_test"], baseline_timeout=1)
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.assertTrue(self.last_event()["baseline"]["results"][0].get("timed_out"))
        self.write("app.py", "print('ok2')\n")  # diff_hash 가 달라져 캐시는 못 쓴다
        self.verify()
        row = self.last_event()["baseline"]["results"][0]
        self.assertTrue(row.get("memo"))
        self.assertEqual(row["secs"], 0.0)
        self.assertEqual(jout(self.qlog("state"))["baseline_state"], "none")  # 판정은 그대로 증거 없음

    def test_contract_reuses_the_baseline_run_of_the_same_command(self):
        """`verify:` 계약이 baseline 체크와 같은 명령이면 같은 트리에서 두 번 돌 이유가 없다."""
        self.policy(baseline_checks=["python3 -m compileall -q ."])
        self.qlog("open", "q1", "--criteria", "컴파일된다 | verify: python3 -m compileall -q .")
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "git status", "exit_code": 0}])
        check = self.last_event()["criteria_checks"][0]
        self.assertTrue(check.get("shared"))
        self.assertEqual(check["exit_code"], 0)  # 공유해도 계약 충족 판정은 동일
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "DONE")

    def test_the_baseline_lane_reuses_its_own_run_for_the_same_contract(self):
        """LLM 없이 끝나는 싼 레인도 계약이 baseline 과 같은 명령이면 두 번 돌 이유가 없다.

        공유는 append 경로에만 붙어 있었다 — 정작 지연을 줄이려고 만든 레인이 스위트를 두 번 물었다."""
        # 행위 테스트 러너만 LLM 판정자를 대신할 수 있다 (gate_first_checks_available) — 이 레인을
        # 실제로 세우려면 baseline 이 pytest 여야 한다.
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.qlog("open", "q1", "--criteria", "테스트가 초록이다 | verify: python3 -m pytest -q")
        self.write("app.py", "print('ok')\n")
        self.write("tests/test_app.py", "def test_ok():\n    assert True\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.assertEqual(jout(self.qlog("verify-baseline"))["verdict"], "PASS")
        check = self.last_event()["criteria_checks"][0]
        self.assertTrue(check.get("shared"))
        self.assertEqual(check["exit_code"], 0)  # 공유해도 계약 충족 판정은 동일

    def test_a_baseline_slower_than_the_timeout_names_the_command(self):
        """체크가 상한보다 느리면 이 레인은 영영 못 서고 모든 쓰기 퀘스트가 LLM Verifier 로 간다.

        종전 메시지는 그 자리를 '체크 없음/전부 skip' 으로 뭉갰다 — 읽는 사람은 판정 결과로 알지
        설정 결함으로 안 읽는다. 고칠 곳이 baseline_timeout 인지 명령 범위인지 말해야 한다."""
        self.write("tests/test_slow.py", "import time\n\n\ndef test_slow():\n    time.sleep(5)\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "slow"], check=True)
        self.policy(baseline_checks=["python3 -m pytest -q"], baseline_timeout=1)
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        p = self.qlog("verify-baseline")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("baseline_timeout", p.stderr)
        self.assertIn("python3 -m pytest -q", p.stderr)

    def test_the_append_timeout_follows_the_policy_not_a_constant(self):
        """append 가 baseline 보다 먼저 끊기면 이미 끝난 Verifier 턴 전체를 다시 사야 한다.

        상수로 적힌 상한은 정책의 baseline_timeout 이 커질 때 조용히 어긋난다 — 정책에서 계산해야
        둘이 갈라지지 않는다."""
        from asgard.agent.quest_bridge import _ql_timeout

        self.policy(baseline_checks=["python3 -m compileall -q ."], baseline_timeout=600)
        self.assertGreater(_ql_timeout(self.root), 600 * 2)  # 체크 1개 + 계약 몫보다 커야 한다

    def test_only_the_harness_running_calls_pay_for_a_process(self):
        """어느 호출이 프로세스로 나가는가 — 하네스 명령을 실제로 도는 갈래만.

        이 갈림이 뒤집히면 둘 중 하나가 조용히 깨진다: 무거운 갈래가 안으로 들어오면 분 단위
        벽시계를 끊을 손이 없어지고(timeout 은 프로세스에만 걸린다), 가벼운 갈래가 밖으로 나가면
        역할 턴 하나가 되사는 왕복이 29번이다. 그래서 목록이 아니라 **기준**을 고정한다."""
        from asgard.agent.quest_bridge import _ql_heavy

        for args in (("verify-baseline",), ("append", "--verdict", "PASS"), ("state", "--request-stdin")):
            with self.subTest(args=args):
                self.assertTrue(_ql_heavy(args))
        for args in (("state",), ("next",), ("open", "q1"), ("append", "--role", "worker", "--event", "work")):
            with self.subTest(args=args):
                self.assertFalse(_ql_heavy(args))

    def test_one_summary_builds_the_working_tree_once(self):
        """요약 하나가 트리를 한 번만 짓는다 — 그리고 그 값이 셋에게 그대로 간다.

        26-08-06 실측: 셋이 저마다 지을 때 `state` 한 번이 git 24회·301ms 였고 그중 224ms 가
        같은 트리를 두 번 더 짓는 몫이었다. 값보다 큰 것은 일관성이다 — 셋 사이에 파일이 바뀌면
        한 요약이 서로 다른 트리를 근거로 쓴다. 캐시로는 이것을 못 산다: 트리 참조는 워킹트리가
        바뀌면 같이 바뀌어야 하고(그래서 `current_tree_ref` 자체는 매번 다시 짓는다), 수명을 아는
        것은 판정을 조립하는 쪽뿐이다."""
        import asgard.hooks.asgard_hooklib.summary as summary_mod
        from asgard.hooks.asgard_hooklib.ledger import load_events
        from asgard.hooks.asgard_hooklib.policy import load_policy

        self.open_quest()
        self.write("app.py", "print('ok')\n")
        built: list[str | None] = []
        real = summary_mod.current_tree_ref

        def counting(root: str) -> str | None:
            built.append(real(root))
            return built[-1]

        with mock.patch.object(summary_mod, "current_tree_ref", counting):
            summary_mod.summarize(self.root, "q1", load_events(self.root, "q1"), load_policy(self.root))
        self.assertEqual(len(built), 1, f"요약 한 번이 트리를 {len(built)}번 지었다")

        # 그리고 캐시가 아니다 — 파일이 바뀌면 다음 트리는 다른 값이어야 한다
        from asgard.hooks.asgard_hooklib.tree import current_tree_ref

        before = current_tree_ref(self.root)
        self.write("app.py", "print('changed')\n")
        self.assertNotEqual(before, current_tree_ref(self.root))

    def test_the_in_process_branch_answers_like_the_process_one(self):
        """같은 명령이 두 갈래에서 같은 것을 낸다 — 종료 코드도, stdout 도.

        인프로세스 갈래는 `sys.stdout` 을 바꿔 끼워 답을 받는다. 그 배선이 틀리면 반환은 0인데
        본문이 비고, 호출부는 `json.loads("") or {}` 로 그것을 조용히 빈 상태로 읽는다."""
        import json as _json
        import subprocess

        from asgard.agent import quest_bridge

        self.open_quest()
        inproc = quest_bridge.ql(self.root, "state", session="native")
        forced = subprocess.run(
            [sys.executable, "-m", "asgard.hooks.quest_log", "state", "--session", "native"],
            capture_output=True,
            text=True,
            cwd=self.root,
            timeout=60,
        )
        self.assertEqual(inproc.returncode, forced.returncode)
        self.assertEqual(_json.loads(inproc.stdout)["quest_id"], _json.loads(forced.stdout)["quest_id"])

    def test_a_contract_slower_than_the_timeout_says_so(self):
        """계약이 timeout 보다 느리면 영영 못 채운다. 미충족은 유지하되 이유를 실패로 적지 않는다 —
        수리 턴이 멀쩡한 코드를 고치러 가는 것을 막는다."""
        self.write("slow_test.py", self.SLOW_TEST)
        self.policy(baseline_timeout=1)
        self.qlog("open", "q1", "--criteria", "느린 계약 | verify: python3 -m unittest slow_test")
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "git status", "exit_code": 0}])
        unmet = jout(self.qlog("state"))["contracts_unmet"]
        self.assertTrue(any("timed out" in u for u in unmet), unmet)
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "VERIFIER")


class TestCriteriaContracts(TrinityBase):
    """criteria verify 계약 — 계약 선언 기준은 하네스가 명령·산출물을 직접 결속 (무관한 exit-0 무효)."""

    def open_with(self, *criteria):
        p = self.qlog("open", "q1", *(a for c in criteria for a in ("--criteria", c)))
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_contract_cmd_harness_run_binds_and_completes(self):
        self.open_with("app.py 정상 실행 | verify: python3 app.py")
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        # 모델이 고른 무관 명령만 신고 — 계약 명령은 하네스가 직접 실행해 기록한다
        self.verify("PASS", commands=[{"cmd": "git status", "exit_code": 0}])
        ev = json.loads(open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")).read().splitlines()[-1])
        self.assertEqual(ev["criteria_checks"][0]["exit_code"], 0)  # 하네스 실행 기록
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_a_contract_longer_than_the_record_width_still_binds(self):
        """계약 명령이 길어도 exit 0 이면 충족이다 — 결속은 명령 길이에 걸리지 않는다.

        `run_criteria_checks` 가 실행 기록의 `cmd` 를 자르면 `unmet_contracts` 는 선언 원문으로 그
        표를 찾으므로 잘린 길이보다 긴 계약이 통과하고도 영영 미충족으로 남고, 전이가 VERIFIER 를
        계속 배정해 판정이 무한 재판정에 들어간다 (26-08-05 실측: 207자 계약 하나로 Stop 이 네 번
        연속 차단). 길이는 종전 절단폭 200자를 넘기려고 고른 값이다."""
        cmd = "python3 app.py #" + "x" * 220
        self.assertGreater(len(cmd), 200)
        self.open_with("app.py 정상 실행 | verify: " + cmd)
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "git status", "exit_code": 0}])
        with open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")) as handle:
            ev = json.loads(handle.read().splitlines()[-1])
        self.assertEqual(ev["criteria_checks"][0]["exit_code"], 0)
        self.assertFalse(jout(self.qlog("state"))["contracts_unmet"])
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_a_pytest_contract_binds_on_the_declared_string_though_it_ran_in_parallel(self):
        """병렬 실행이 결속을 흔들면 안 된다 — 계약 키는 선언 원문이고 `run_cmd` 가 실제 실행이다.

        실행을 빠르게 하려고 명령을 바꾸면서 그 바뀐 문자열을 키로 적으면, 선언으로 조회하는
        `unmet_contracts` 가 못 찾아 결함 2 와 같은 무한 재판정이 다시 난다."""
        self.open_with("스위트 초록 | verify: uv run pytest -q --version")
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "git status", "exit_code": 0}])
        with open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")) as handle:
            ev = json.loads(handle.read().splitlines()[-1])
        row = ev["criteria_checks"][0]
        self.assertEqual(row["cmd"], "uv run pytest -q --version")  # 결속 키 = 선언 원문
        self.assertEqual(row.get("run_cmd"), "uv run pytest -n auto -q --version")  # 실제 실행
        self.assertFalse(jout(self.qlog("state"))["contracts_unmet"])

    def test_failing_contract_rejects_despite_irrelevant_exit0(self):
        # Codex 교차검증이 지적한 구멍: 무관한 nontrivial exit-0(git status)이 증거로 인정되던 경로 —
        # 계약이 선언되면 그 명령의 성공만 증거다
        self.open_with("app.py 정상 실행 | verify: python3 app.py")
        self.write("app.py", "import sys; sys.exit(1)\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS", commands=[{"cmd": "git status", "exit_code": 0}])
        st = jout(self.qlog("state"))
        self.assertTrue(st["contracts_unmet"])
        nxt = jout(self.qlog("next", "--write-expected"))
        self.assertEqual(nxt["next_role"], "VERIFIER")
        self.assertIn("contract", nxt["why"])
        self.assertEqual(self.qlog("close").returncode, 1)  # 퍼널 REJECTED
        out = jout(self.gate())
        self.assertEqual(out.get("decision"), "block")  # 게이트 동일 판정
        self.assertIn("contract", out.get("reason", ""))

    def test_contract_binds_when_verifier_reports_criteria_as_objects(self):
        # 26-07-26 실측 교착: 판정자가 기준별 판정을 객체로 넣으면(역할 계약이 요구하는 형태)
        # 계약이 0건으로 보여 하네스가 계약 명령을 실행하지 않는데 게이트는 퀘스트 선언에서
        # 계약을 계속 읽어 `criteria-unverified`로 Stop을 영구 차단했다.
        self.open_with("app.py 정상 실행 | verify: python3 app.py")
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        body = {
            "role": "verifier",
            "event": "verify",
            "criteria": [{"id": "c1", "desc": "app.py 정상 실행", "status": "met", "evidence": "실행 확인"}],
            "commands": [{"cmd": "git status", "exit_code": 0}],
        }
        self.verifier_seat()  # 이 판정을 적은 것이 판정자 자리라는 사실 (TestVerifierIndependence 참고)
        self.qlog("append", "--verdict", "PASS", "--session", "s1", stdin=json.dumps(body))
        ev = json.loads(open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")).read().splitlines()[-1])
        self.assertEqual(ev["criteria_checks"][0]["exit_code"], 0)  # 계약이 여전히 결속된다
        self.assertEqual(jout(self.qlog("state"))["contracts_unmet"], [])
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "DONE")
        self.assertNotEqual(jout(self.gate()).get("decision"), "block")  # Stop 통과 — 교착 해소
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_contract_binds_when_verifier_reports_criteria_as_prose_strings(self):
        # 같은 교착의 다른 문 (26-08-04 실측): 판정자가 기준별 판정을 산문 **문자열**로 보내면
        # 형태 판별(객체 거르기)을 그냥 지나가고, 계약을 한 줄도 안 실은 목록이 원본으로 잡혀
        # 계약 명령이 영영 안 돈다. 원본은 형태가 아니라 계약 보유로 골라야 한다.
        self.open_with("app.py 정상 실행 | verify: python3 app.py")
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        body = {
            "role": "verifier",
            "event": "verify",
            "criteria": ["기준1 app.py 정상 실행 — 직접 실행해 확인", "기준2 회귀 없음 — 스위트 통과"],
            "commands": [{"cmd": "git status", "exit_code": 0}],
        }
        self.qlog("append", "--verdict", "PASS", "--session", "s1", stdin=json.dumps(body))
        with open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl"), encoding="utf-8") as handle:
            ev = json.loads(handle.read().splitlines()[-1])
        self.assertEqual(ev["criteria_checks"][0]["exit_code"], 0)
        self.assertEqual(jout(self.qlog("state"))["contracts_unmet"], [])
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_object_criteria_do_not_mask_a_failing_contract(self):
        # 반대 방향도 지킨다 — 객체 보고로 계약을 회피할 수 없다
        self.open_with("app.py 정상 실행 | verify: python3 app.py")
        self.write("app.py", "import sys; sys.exit(1)\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        body = {
            "role": "verifier",
            "event": "verify",
            "criteria": [{"id": "c1", "status": "met", "evidence": "정독으로 확인"}],
            "commands": [{"cmd": "git status", "exit_code": 0}],
        }
        self.qlog("append", "--verdict", "PASS", "--session", "s1", stdin=json.dumps(body))
        self.assertTrue(jout(self.qlog("state"))["contracts_unmet"])
        self.assertEqual(jout(self.gate()).get("decision"), "block")

    def test_artifacts_checked_live(self):
        self.open_with("산출물 존재 | artifacts: out.txt")
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS")
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "VERIFIER")  # out.txt 없음
        self.assertEqual(self.qlog("close").returncode, 1)
        self.write("out.txt", "built\n")
        self.verify("PASS")  # 산출물 생성 후 재검증 (out.txt가 diff에 포함 — 새 hash로 PASS)
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)

    def test_plain_criteria_backward_compat(self):
        self.open_quest()  # 계약 없는 평문 criteria
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS")
        st = jout(self.qlog("state"))
        self.assertEqual(st["contracts_unmet"], [])
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "DONE")

    def test_trivial_contract_is_not_a_contract(self):
        self.open_with("항상 성공 | verify: true")
        self.write("app.py", "print('ok')\n")
        self.qlog("append", "--role", "worker", "--event", "work")
        self.verify("PASS")  # nontrivial 증거(python3 app.py)로 통과 — trivial 계약은 무시
        self.assertEqual(jout(self.qlog("state"))["contracts_unmet"], [])
        self.assertEqual(jout(self.qlog("next", "--write-expected"))["next_role"], "DONE")

    def test_verify_baseline_binds_contracts(self):
        # 게이트-우선 경로 — baseline green 이어도 계약 미충족이면 FAIL 기록
        self.open_with("app.py 정상 실행 | verify: python3 app.py")
        self.write("app.py", "import sys; sys.exit(1)\n")
        self.write("tests/test_ok.py", "def test_ok():\n    assert True\n")
        self.policy(baseline_checks=["python3 -m pytest -q"])
        self.qlog("append", "--role", "worker", "--event", "work")
        out = jout(self.qlog("verify-baseline"))
        self.assertEqual(out["verdict"], "FAIL")
        self.assertTrue(any("python3 app.py" in str(f) for f in out.get("failing", [])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
