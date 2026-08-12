#!/usr/bin/env python3
"""역할 프롬프트 주입면 — charter·딜리버리 정본 카탈로그·탐색 힌트."""

import json
import os
import unittest

from heimdall.harness import (
    CLS_WRITE,
    DONE,
    Base,
    FakeHeimdall,
    thinker,
    verifier,
    worker,
)


class TestCharterInjection(Base):
    """Charter (프로젝트 북극성) — through-line/coherence가 라이브 Trinity 순환에서 올바른
    역할 프롬프트에만 도달하고, evidence-first 게이트를 훼손하지 않음을 검증."""

    def _set_charter(self, charter):
        d = os.path.join(self.root, ".asgard")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "asgard-setting-project.json"), "w", encoding="utf-8") as f:
            json.dump({"charter": charter}, f)

    def test_charter_reaches_thinker_and_verifier_not_worker(self):
        self._set_charter({"through_line": "TL관통원칙", "coherence": ["C1일관성"]})
        # structural replan 경로 = thinker 턴을 강제 (해피패스는 thinker 생략)
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="wrong-approach", why="접근 틀림"),
            thinker("재설계"),
            worker({"w1.txt": "good\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)  # 게이트 정상 통과 — charter가 순환을 막지 않음
        by = {}
        for s in h.consumed:
            by.setdefault(s.label, s)
        # Thinker: 관통 원칙 + coherence를 criteria로 환원 지시 (설계①/협업②)
        self.assertIn("TL관통원칙", by["thinker"].system)
        self.assertIn("C1일관성", by["thinker"].system)
        # Verifier: 렌즈로 주입되되 criteria 대체 아님 명시 (판단③, evidence-first 보존)
        self.assertIn("TL관통원칙", by["verifier"].system)
        self.assertIn("does not replace criteria", by["verifier"].system)
        # Worker: charter 전혀 무주입 — worker.md+lagom만 (Fugu 격리, CC 훅과 패리티)
        self.assertNotIn("C1일관성", by["worker"].system)
        self.assertNotIn("Project North Star", by["worker"].system)

    def test_no_charter_no_injection(self):
        # 미설정이면 프롬프트 무변화 (토큰 회귀 없음)
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        for s in h.consumed:
            self.assertNotIn("프로젝트 북극성", s.system)


class TestDeliveryCanonInjection(Base):
    """딜리버리 정본 카탈로그 — 도메인 매칭 과업의 Thinker 프롬프트에만 정본 존재를 알린다.

    실증 근거(26-07-21 bilskirnir 4모드 실증): Thinker가 저장소 문서 검색만으로 "정본 부재"를
    확정하고 응답 봉투를 발명해 verify 계약으로 고정 → thor 미디스패치·정책 우회 (2/2 재현)."""

    def _consumed_by_label(self, h):
        by = {}
        for s in h.consumed:
            by.setdefault(s.label, s)
        return by

    def test_matched_task_reaches_thinker_prompt_only(self):
        # structural replan 경로 = thinker 턴을 강제 (해피패스는 thinker 생략)
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="wrong-approach", why="접근 틀림"),
            thinker("재설계"),
            worker({"w1.txt": "good\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=CLS_WRITE)
        out = h.handle("신규 백엔드 API 설계 — 하우스 룰 준수로 w1.txt 만들어")
        self.assertIn(DONE, out)  # 주입이 순환을 막지 않음
        by = self._consumed_by_label(h)
        self.assertIn("Delivery canon (binds the plan", by["thinker"].prompt)
        self.assertIn("asgard-thor-bilskirnir", by["thinker"].prompt)
        # Worker: 계획 구속 노트 대신 착수 힌트만 — 정본 소유 전문가 dispatch 지시 (관찰-정지 방어)
        self.assertNotIn("Delivery canon (binds the plan", by["worker"].prompt)
        self.assertIn("Delivery canon hint", by["worker"].prompt)
        self.assertIn("dispatch", by["worker"].prompt)
        self.assertNotIn("Delivery canon", by["verifier"].prompt)

    def test_unmatched_task_no_injection(self):
        from asgard.agent.heimdall.roles import delivery_canon_note, worker_canon_hint

        self.assertEqual(delivery_canon_note(self.root, "readme 문서 오탈자 정리"), "")
        self.assertEqual(worker_canon_hint(self.root, "readme 문서 오탈자 정리"), "")


class TestExplorationHint(Base):
    """탐색 캐시 최소판 — Thinker 관찰 명령을 Worker에 힌트로 전달 (게이트 증거 아님)."""

    def test_worker_gets_thinker_observations(self):
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="bad-plan"),
            thinker("계획: w1 을 만든다", commands=[{"cmd": "grep -rn foo src/", "exit_code": 0}]),
            worker({"w1.txt": "x\n"}, self.root),
            verifier("PASS"),
        ]
        h = FakeHeimdall(self.root, seq, cls=dict(CLS_WRITE, ambiguous=True))
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        w = [s for s in h.consumed if s.label == "worker"][1]
        self.assertIn("grep -rn foo src/", w.prompt)
        self.assertIn("no need to re-explore", w.prompt)


if __name__ == "__main__":
    unittest.main(verbosity=1)
