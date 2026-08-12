#!/usr/bin/env python3
"""API 오류 회복과 턴 예산 — 백오프·폴백·grace 판정."""

import os
import unittest

from asgard.agent.session import SessionResult
from heimdall.harness import (
    CLS_WRITE,
    DONE,
    Base,
    FakeHeimdall,
    verifier,
    worker,
)


class TestErrorRecovery(Base):
    """API 오류 회복 — recovery-hint 분류 + 백오프 + 폴백."""

    class _Boom(Exception):
        def __init__(self, status=None):
            super().__init__("boom")
            if status is not None:
                self.status_code = status

    def test_retryable_backs_off_then_succeeds(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        sleeps: list[float] = []
        h._sleep = sleeps.append
        ok = SessionResult(text="ok", stop_reason="end_turn")
        attempts = []

        class S:
            def run(_, user_content):
                attempts.append(1)
                if len(attempts) < 3:
                    raise self._Boom(429)
                return ok

        r = h._run_turn(lambda: S(), "p")
        self.assertEqual(r.text, "ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(len(sleeps), 2)  # jittered backoff 2회

    def test_fatal_raises_immediately(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        attempts = []

        class S:
            def run(_, user_content):
                attempts.append(1)
                raise self._Boom(401)

        with self.assertRaises(self._Boom):
            h._run_turn(lambda: S(), "p")
        self.assertEqual(len(attempts), 1)  # 재시도 0

    def test_fatal_uses_fallback_once(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        ok = SessionResult(text="fb", stop_reason="end_turn")

        class Bad:
            def run(_, user_content):
                raise self._Boom(401)

        class Good:
            def run(_, user_content):
                return ok

        r = h._run_turn(lambda: Bad(), "p", fallback=lambda: Good())
        self.assertEqual(r.text, "fb")

    def test_trinity_exception_reports_dangling_quest(self):
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)  # 세션 스크립트 없음 → 첫 역할 턴에서 예외
        out = h.handle("w1.txt 만들어")
        self.assertIn("Trinity를 멈췄어요", out)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".asgard", "quest", "ACTIVE")))

    def test_dangling_active_warned_on_init(self):
        os.makedirs(os.path.join(self.root, ".asgard", "quest"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "quest", "ACTIVE"), "w").write("old-quest\n")
        h = FakeHeimdall(self.root, [], cls=CLS_WRITE)
        self.assertTrue(any("안 끝난 퀘스트가 있어요" in t for t in h.texts))


class TestBudget(Base):
    """budget priors 배선 — task-class 턴 예산 + 80% 자기규제 + grace 판정."""

    def _cls(self):
        return dict(CLS_WRITE, task_class="trivial")  # trivial=1 → 최소 순환 3으로 클램프

    def test_grace_verifier_completes_after_budget(self):
        seq = [
            worker({"w1.txt": "a\n"}, self.root),  # t1
            verifier("FAIL", sig="s1"),  # t2
            worker({"w1.txt": "b\n"}, self.root),  # t3 (예산 마지막)
            verifier("PASS"),  # t4 = grace 판정
        ]
        h = FakeHeimdall(self.root, seq, cls=self._cls())
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        self.assertIn("turn 3/3", h.consumed[2].prompt)  # 80% 도달 자기규제 주입
        self.assertIn("narrow scope", h.consumed[2].prompt)

    def test_budget_exhaustion_honest_report(self):
        seq = [
            worker({"w1.txt": "a\n"}, self.root),
            verifier("FAIL", sig="s1"),
            worker({"w1.txt": "b\n"}, self.root),
            verifier("FAIL", sig="s2"),  # grace 판정도 FAIL → 다음 작업 턴은 예산 밖
        ]
        h = FakeHeimdall(self.root, seq, cls=self._cls())
        out = h.handle("w1.txt 만들어")
        self.assertIn("예산", out)
        self.assertNotIn(DONE, out)
        # 침묵 break 금지 — 어떤 전이가 왜 못 뛰었는지 Odin 보고에 들어간다 (26-07-22 실측:
        # grace PASS 후 베이스라인 red 수리 전이가 막혔는데 "판정 실패"로 오독되는 보고).
        # 전이명은 승격 규칙(동종 red 2회 → THINKER_REPLAN)에 따라 달라진다 — 형식만 봉인.
        self.assertIn("미실행 전이 ", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
