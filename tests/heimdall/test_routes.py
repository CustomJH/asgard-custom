#!/usr/bin/env python3
"""턴 갈래 — 봉인 레인·DIRECT 가드·standard 종결·대화 맥락."""

import json
import os
import unittest
from unittest import mock

from asgard.agent.session import SessionResult
from heimdall.harness import (
    CLS_WRITE,
    DONE,
    Base,
    FakeHeimdall,
    FakeSession,
    seed_map_canary,
    verifier,
    worker,
)


class TestSealLane(Base):
    """봉인 레인 — 커밋만 하는 턴이 Trinity 절차를 사지 않는다.

    26-08-04 회귀: `/skill` 호출은 당시 12.8KB였던 스킬 본문이 곧 요청이 되어 분류기에 실렸고,
    본문에 든 write 동사 열둘이 `_classify`의 write 거부권을 만족시켜 **분류 결과와 무관하게**
    write 로 확정됐다. 그래서 커밋만 하면 되는 턴이 thinker 계획 → worker 웨이브 → 베이스라인
    테스트 → verifier 판정을 전부 실행했다."""

    def _seal_prompt(self) -> str:
        """`invoked_skill_prompt` 와 같은 확장문 — 레지스트리 배정과 무관하게 파서 경로를 탄다."""
        from asgard.templates.seal import SEAL_SKILL_MD

        body = SEAL_SKILL_MD.split("---", 2)[2].lstrip()
        return (
            f'<user_invoked_skill name="asgard-seal">\n{body.rstrip()}\n</user_invoked_skill>\n\n'
            "The user explicitly invoked this skill.\n\nArguments: (none)"
        )

    def test_the_invocation_is_recovered_from_the_expanded_prompt(self):
        from asgard.skill_registry import invoked_skill_command

        self.assertEqual(invoked_skill_command(self._seal_prompt()), "/asgard-seal")
        self.assertIsNone(invoked_skill_command("커밋해줘"))  # 평범한 요청은 건드리지 않는다

    def test_skill_body_alone_still_reads_as_a_write_task(self):
        """회귀의 원인 자체 — 본문을 요청으로 읽으면 vcs 전용 판정이 사라진다."""
        from asgard.agent.heimdall.classify import classify_heuristic, has_write_verbs
        from asgard.templates.seal import SEAL_SKILL_MD

        body = SEAL_SKILL_MD.split("---", 2)[2]
        self.assertTrue(has_write_verbs(body))  # 본문은 늘 write 로 읽힌다
        classification = classify_heuristic(body)
        assert classification is not None
        self.assertTrue(classification["write_expected"])
        self.assertNotEqual(classification["task_class"], "vcs")

    def test_invoked_seal_takes_the_seal_lane_without_a_quest(self):
        seal = FakeSession(SessionResult(text="봉인 완료", stop_reason="end_turn"), label="seal")
        h = FakeHeimdall(self.root, [seal])
        h.handle(self._seal_prompt())
        self.assertEqual(len(h.consumed), 1)  # 단일 세션 — thinker·worker·verifier 없음
        self.assertEqual(seal.role, "seal")
        self.assertFalse(seal.readonly)  # 격리 사본이 아니라 진짜 저장소에서 커밋한다
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))
        self.assertIn('"route": "seal"', open(os.path.join(self.root, ".asgard", "state", "classify.jsonl")).read())

    def test_seal_lane_never_calls_the_classifier(self):
        seal = FakeSession(SessionResult(text="봉인 완료", stop_reason="end_turn"), label="seal")
        h = FakeHeimdall(self.root, [seal])
        with mock.patch.object(h, "_classify", side_effect=AssertionError("분류 호출 금지")):
            h.handle(self._seal_prompt())

    def test_plain_commit_request_takes_the_seal_lane_too(self):
        seal = FakeSession(SessionResult(text="봉인 완료", stop_reason="end_turn"), label="seal")
        h = FakeHeimdall(self.root, [seal])
        h.handle("지금까지 변경사항 커밋해줘")
        self.assertEqual(seal.role, "seal")

    def test_seal_turn_that_edits_source_is_promoted_to_verification(self):
        """게이트를 버린 게 아니라 자리를 옮겼다 — 편집이 관측되면 검증 경로로 승격한다."""
        seal = worker({"sneaky.txt": "oops\n"}, self.root, text="봉인 완료")
        h = FakeHeimdall(self.root, [seal, verifier("PASS")])
        out = h.handle(self._seal_prompt())
        self.assertIn(DONE, out)
        self.assertIn("misroute", open(os.path.join(self.root, ".asgard", "state", "classify.jsonl")).read())

    def test_skill_without_a_declared_lane_keeps_the_delivery_route(self):
        h = FakeHeimdall(self.root, [])
        cls = h._skill_classification("/asgard-freyja 랜딩 만들어줘")
        self.assertTrue(cls["write_expected"])
        self.assertEqual(cls["task_class"], "standard")


class TestDirectGuard(Base):
    """DIRECT 가드 — 오분류 write 소급 편입."""

    def _cls_read(self):
        return dict(CLS_WRITE, write_expected=False, criteria=[])

    def test_direct_write_enters_retro_verification(self):
        direct = worker({"sneaky.txt": "oops\n"}, self.root)  # DIRECT 세션이 파일을 씀
        seq = [direct, verifier("PASS")]
        h = FakeHeimdall(self.root, seq, cls=self._cls_read())
        out = h.handle("그냥 이거 처리해줘")
        self.assertIn(DONE, out)  # 소급 quest → Verifier → 게이트 → close
        self.assertIn("misroute", open(os.path.join(self.root, ".asgard", "state", "classify.jsonl")).read())

    def test_direct_readonly_stays_taxless(self):
        seed_map_canary(self.root)
        direct = FakeSession(SessionResult(text="답변", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        h.handle("이 함수 뭐하는거야")
        self.assertEqual(len(h.consumed), 1)
        self.assertIn("MAP_CANARY", direct.system)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_active_lagom_streams_live_and_appends_rewrite_as_canonical(self):
        # 26-07-23: 검사 전 전량 버퍼링은 REPL을 '먹통 → 한번에 팍'으로 보이게 했다.
        # 새 계약: DIRECT는 라곰 활성에도 라이브 스트리밍, 위반 시에만 교정 표식+정본을 덧붙인다.
        direct = FakeSession(
            SessionResult(text="혁신적 RAGX는 즉시 배포 가능하다.", stop_reason="end_turn"), label="direct"
        )
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        with mock.patch.object(
            h, "_rewrite_lagom_text", return_value="RAGX는 JSON 키를 정렬하는 13줄짜리 도구다."
        ) as rewrite:
            h.handle("RAGX 소개를 답해. 사실: 13줄, JSON 키 정렬")
        rewrite.assert_called_once()
        self.assertFalse(direct.quiet)  # 스트리밍 계약 — DIRECT 세션의 on_text는 살아 있다
        self.assertEqual(h.last_response_text, "RAGX는 JSON 키를 정렬하는 13줄짜리 도구다.")
        joined = "".join(h.texts)
        self.assertIn("⠶", joined)  # 교정 표식(언어 중립 글리프) — 초안과 정본이 갈렸음을 알린다
        self.assertIn(h.last_response_text, joined)

    def test_failed_rewrite_keeps_the_streamed_draft_instead_of_deleting_the_answer(self):
        # 26-07-30: 재작성이 나아지지 않아도 답은 남는다 — 본문은 이미 스트리밍된 뒤라
        # 안내문으로 바꿔치면 사용자는 읽은 답이 무효라는 통보만 받는다.
        direct = FakeSession(SessionResult(text="혁신적 결과다.", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        with mock.patch.object(h, "_rewrite_lagom_text", return_value="강력한 결과다."):
            h.handle("결과를 설명해")
        self.assertEqual(h.last_response_text, "혁신적 결과다.")  # 초안이 정본
        joined = "".join(h.texts)
        self.assertNotIn("강력한", joined)  # 채택 못 한 재작성문은 표시되지 않는다
        self.assertNotIn("⠶", joined)  # 교정 표식도 없다 — 갈린 정본이 없으므로

    def test_rewrite_failure_does_not_lose_the_answer(self):
        """재작성 모델 호출이 터져도 초안이 정본으로 남는다 (일시 장애 = 답 소실 아님)."""
        direct = FakeSession(SessionResult(text="혁신적 결과다.", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        with mock.patch.object(h, "_rewrite_lagom_text", side_effect=RuntimeError("boom")):
            h.handle("결과를 설명해")
        self.assertEqual(h.last_response_text, "혁신적 결과다.")

    def test_advisory_only_findings_skip_the_rewrite_call(self):
        """조언만 남은 답(세상의 약어 한 건)은 모델 재호출 없이 그대로 통과한다."""
        direct = FakeSession(SessionResult(text="측정에는 NPS 지표를 썼다.", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        with mock.patch.object(h, "_rewrite_lagom_text") as rewrite:
            h.handle("무슨 지표를 썼어?")
        rewrite.assert_not_called()
        self.assertEqual(h.last_response_text, "측정에는 NPS 지표를 썼다.")

    def test_identity_carries_both_style_axes(self):
        """두 계약은 모든 역할이 공유하는 신원에 들어간다 — 딜리버리 자식도 같은 문체로 보고한다."""
        h = FakeHeimdall(self.root, [], cls=self._cls_read())
        self.assertIn("Lagom — Minimalism Contract", h.delivery_identity)
        self.assertIn("Bragi — Human Voice Contract", h.delivery_identity)

    def test_bragi_axis_survives_lagom_off(self):
        """`/lagom off`는 압축을 끄는 것이지 사람처럼 쓰기를 끄는 게 아니다 — 축이 독립이다."""
        old = os.environ.get("LAGOM_MODE")
        os.environ["LAGOM_MODE"] = "off"
        try:
            h = FakeHeimdall(self.root, [], cls=self._cls_read())
            self.assertEqual(h.lagom, "")
            self.assertIn("Bragi — Human Voice Contract", h.delivery_identity)
        finally:
            if old is None:
                os.environ.pop("LAGOM_MODE", None)
            else:
                os.environ["LAGOM_MODE"] = old

    def test_machine_writing_tells_trigger_the_rewrite_even_without_lagom_violations(self):
        """근거 게이트는 통과하지만 기계 문체가 남은 답 — 패치 이전엔 그대로 나갔다."""
        slop = "Great question! This change plays a crucial role in the codebase. I hope this helps!"
        direct = FakeSession(SessionResult(text=slop, stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
        with mock.patch.object(h, "_rewrite_lagom_text", return_value="캐시를 세션 조회에 붙였다.") as rewrite:
            h.handle("무엇을 바꿨는지 알려줘")
        rewrite.assert_called_once()
        self.assertIn("U-chat-artifact", "\n".join(rewrite.call_args.args[2]))
        self.assertEqual(h.last_response_text, "캐시를 세션 조회에 붙였다.")

    def test_lagom_off_keeps_direct_streaming_without_rewrite(self):
        old = os.environ.get("LAGOM_MODE")
        os.environ["LAGOM_MODE"] = "off"
        try:
            direct = FakeSession(SessionResult(text="혁신적 결과다.", stop_reason="end_turn"), label="direct")
            h = FakeHeimdall(self.root, [direct], cls=self._cls_read())
            with mock.patch.object(h, "_rewrite_lagom_text") as rewrite:
                h.handle("결과를 설명해")
            rewrite.assert_not_called()
            self.assertEqual(h.last_response_text, "혁신적 결과다.")
        finally:
            if old is None:
                os.environ.pop("LAGOM_MODE", None)
            else:
                os.environ["LAGOM_MODE"] = old


class TestStandardRoute(Base):
    """ordinary write는 안전 가드가 허용하면 baseline으로 닫고, 아니면 Verifier로 승격한다."""

    def policy(self, **kw):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "trinity-policy.json"), "w") as f:
            json.dump(kw, f)

    def test_standard_closes_with_green_baseline(self):
        self.policy(baseline_checks=["python3 -m pytest -q"])
        h = FakeHeimdall(
            self.root,
            [worker({"w1.txt": "x\n", "test_w1.py": "def test_w1(): assert True\n"}, self.root)],
            cls={**CLS_WRITE, "task_class": "standard"},
        )
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        self.assertEqual([s.label for s in h.consumed], ["worker"])
        self.assertIn('"harness"', self.quest_log_text())
        self.assertFalse(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_ambiguous_deep_write_starts_single_worker_without_thinker(self):
        work = worker({"w1.txt": "x\n"}, self.root)
        h = FakeHeimdall(
            self.root,
            [work, verifier("PASS")],
            cls={**CLS_WRITE, "ambiguous": True, "task_class": "deep"},
        )

        out = h.handle("모호한 부분은 합리적으로 판단해서 w1.txt 만들어")

        self.assertIn(DONE, out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier"])
        self.assertIn("Success criteria:", work.prompt)

    def test_standard_red_gives_worker_retry_with_failing_check(self):
        self.policy(baseline_checks=["python3 -m pytest -q"])
        seq = [
            worker(
                {
                    "w1.txt": "x\n",
                    "test_fixed.py": "from pathlib import Path\n\ndef test_fixed(): assert Path('fixed.txt').exists()\n",
                },
                self.root,
            ),
            worker({"fixed.txt": "y\n"}, self.root),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("고쳐줘")
        self.assertIn(DONE, out)
        self.assertEqual([s.label for s in h.consumed], ["worker", "worker"])
        self.assertIn("baseline-red", seq[1].prompt or "")  # 실패 체크가 재시도 컨텍스트로 전달

    def test_invalid_verdict_is_recorded_as_fail_instead_of_crashing(self):
        seq = [
            worker({"w1.txt": "x\n"}, self.root),
            verifier("Pass"),
            worker({"w1.txt": "fixed\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("고쳐줘")
        self.assertIn(DONE, out)
        events = [json.loads(line) for line in self.quest_log_text().splitlines() if line.strip()]
        failures = [event for event in events if event.get("event") == "verify" and event.get("verdict") == "FAIL"]
        self.assertEqual(failures[0]["failure_sig"], "invalid-verdict-submitted")

    def test_empty_classifier_criteria_is_bound_to_request_for_every_role(self):
        cls = {**CLS_WRITE, "criteria": [], "task_class": "standard"}
        seq = [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")]
        h = FakeHeimdall(self.root, seq, cls=cls)
        request = "Create w1.txt containing x"
        out = h.handle(request)
        self.assertIn(DONE, out)
        self.assertIn(request, seq[1].prompt)
        self.assertNotIn("criteria: []", seq[1].prompt)
        opened = json.loads(self.quest_log_text().splitlines()[0])
        self.assertEqual(opened["criteria"], [f"Request text and resulting change match: {request}"])

    def test_missing_task_class_stays_trinity(self):
        # task_class 미상(None) = 안전 기본값 — 기존 LLM Verifier 경로 유지
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        self.assertEqual([s.label for s in h.consumed], ["worker", "verifier"])


class TestDirectHistory(Base):
    """REPL 턴 간 대화 맥락 — DIRECT 후속 질문이 직전 문답을 받는다 (Trinity 경로는 안 받음)."""

    def test_direct_followup_gets_history(self):
        cls_ro = {**CLS_WRITE, "write_expected": False, "criteria": []}
        s1 = FakeSession(SessionResult(text="답1", stop_reason="end_turn"), label="direct")
        s2 = FakeSession(SessionResult(text="답2", stop_reason="end_turn"), label="direct")
        h = FakeHeimdall(self.root, [s1, s2], cls=cls_ro)
        h.handle("파이썬 버전 뭐야?")
        h.handle("그건 왜?")
        self.assertNotIn("Previous exchange", s1.prompt)  # 첫 턴은 맥락 없음
        self.assertIn("Previous exchange", s2.prompt)
        self.assertIn("파이썬 버전 뭐야?", s2.prompt)
        self.assertIn("답1", s2.prompt)


if __name__ == "__main__":
    unittest.main(verbosity=1)
