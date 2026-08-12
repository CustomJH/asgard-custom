#!/usr/bin/env python3
"""역할·상황별 모델 티어와 배치·폴백 규칙."""

import os
import unittest

from asgard.agent.heimdall import Heimdall
from asgard.agent.session import SessionResult
from asgard.model_tiers import tiers_for
from asgard.providers import PROVIDERS
from heimdall.harness import (
    CLS_WRITE,
    DONE,
    Base,
    FakeHeimdall,
    FakeSession,
    thinker,
    verifier,
    worker,
)

OPUS_DEFAULT = PROVIDERS["anthropic"].default_model
# 티어 앵커 — 해석된 표에서 읽는다 (리터럴 모델 ID는 세대 교체마다 낡는 앵커다)
TIER = tiers_for("anthropic", "anthropic")


class TestModelTiers(Base):
    """상황별 모델 티어 — opus/fable/sonnet/haiku를 역할·상황이 결정."""

    def _h(self, sessions=None, model=OPUS_DEFAULT):
        return FakeHeimdall(self.root, sessions or [], cls=CLS_WRITE, model=model)

    def test_policy_tiers_map_roles_to_models(self):
        h = self._h()
        # 기대값은 리터럴이 아니라 해석된 표에서 — 세대가 올라가도 앵커가 낡지 않는다
        table = tiers_for("anthropic", "anthropic")
        # worker 정책 티어는 standard 지만 코디네이터(opus=high)가 하한 — 위임 손은 세션 모델 아래로 안 내려간다
        self.assertEqual(h._model_for("worker"), table["high"])
        self.assertEqual(h._model_for("thinker"), table["high"])
        self.assertEqual(h._model_for("verifier"), table["high"])
        self.assertEqual(h._model_for("verifier", bump=True), table["max"])  # full-verify 승급

    def test_tier_table_tracks_the_current_generation(self):
        # 26-07-26 실측 회귀: 표가 이전 세대(opus-4-8)에 박혀 opus-5 세션이 역할 턴마다 조용히
        # 내려갔다. high 티어는 코디네이터 별칭 `opus`가 해석되는 세대와 같은 계열·최신이어야 한다.
        from asgard.model_tiers import FAMILY, generation

        table = tiers_for("anthropic", "anthropic")
        for tier, marker in FAMILY.items():
            self.assertIn(marker, table[tier])
        self.assertGreater(generation(table["high"]), generation("claude-opus-4-8"))
        # claude CLI 모드는 별칭 그대로 — CLI가 최신 세대로 해석하므로 표 유지보수가 없다
        self.assertEqual(tiers_for("claude-native", "claude_cli"), dict(FAMILY))
        # 티어 개념이 없는 provider는 스왑하지 않는다 (커스텀 ID 존중)
        self.assertEqual(tiers_for("openai", "openai_responses"), {})

    def _set_coordinator(self, h, model):
        # role_rp가 동일 rp 객체를 공유하므로 in-place 변이 (placement 오인 방지)
        h.rp.model = model

    def test_coordinator_tier_floor(self):
        # 프론티어 코디네이터(max) — 전 역할이 fable로 승급, bump는 이미 천장
        h = self._h()
        self._set_coordinator(h, TIER["max"])
        self.assertEqual(h._model_for("worker"), TIER["max"])
        self.assertEqual(h._model_for("verifier"), TIER["max"])
        self.assertEqual(h._model_for("worker", bump=True), TIER["max"])
        # 코디네이터가 역할 티어보다 낮으면(haiku=fast) 하한은 무효 — 정책 티어 유지
        h2 = self._h()
        self._set_coordinator(h2, TIER["fast"])
        self.assertEqual(h2._model_for("worker"), TIER["standard"])
        self.assertEqual(h2._model_for("verifier"), TIER["high"])

    def test_delivery_tiers(self):
        h = self._h()
        self.assertEqual(h._delivery_model("freyja"), TIER["high"])
        self.assertEqual(h._delivery_model("thor"), TIER["high"])
        self.assertEqual(h._delivery_model("loki"), TIER["fast"])
        h.policy["delivery"]["thor"] = "custom"
        self.assertIsNone(h._delivery_model("thor"))

    def test_cli_aliases_keep_low_tier_role_floors(self):
        h = self._h(model="haiku")
        self.assertEqual(h._model_for("worker"), TIER["standard"])
        self.assertEqual(h._model_for("verifier"), TIER["high"])
        self.assertEqual(h._delivery_model("thor"), TIER["standard"])
        self.assertEqual(h._delivery_model("loki"), TIER["fast"])

    def test_explicit_delivery_placement_wins_over_floor(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.thor]\nprovider = "ollama"\nmodel = "m1"\n'
        )
        h = self._h()
        self.assertIsNone(h._delivery_model("thor"))
        self.assertEqual(Heimdall._session(h, "sys", role="thor").rp.model, "m1")

    def test_explicit_placement_wins_over_tier(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.worker]\nprovider = "ollama"\nmodel = "m1"\n'
        )
        h = self._h()
        self.assertIsNone(h._model_for("worker"))  # placement 존중 — 스왑 없음
        self.assertEqual(Heimdall._session(h, "sys", role="worker").rp.model, "m1")

    def test_fallback_override_uses_default_provider_but_keeps_capability_role(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.thinker]\nprovider = "ollama"\nmodel = "placed-t"\n'
        )
        h = self._h()

        session = Heimdall._session(h, "sys", role="thinker", rp_override=h.rp)

        self.assertEqual(session.rp.profile.name, h.rp.profile.name)
        self.assertEqual(session.role, "thinker")

    def test_user_custom_model_not_overridden(self):
        h = self._h(model="claude-x")  # 사용자가 기본 모델을 바꿈 — 티어 매핑 비활성
        self.assertIsNone(h._model_for("worker"))
        self.assertIsNone(h._delivery_model("loki"))

    def test_session_model_override_swaps_model_only(self):
        h = self._h()
        # FakeHeimdall은 _session을 대체하므로 실제 구현을 직접 호출
        s = Heimdall._session(h, "sys", role="worker", model=TIER["standard"])
        self.assertEqual(s.rp.model, TIER["standard"])
        self.assertEqual(s.rp.profile.name, "anthropic")
        self.assertEqual(h.role_rp["worker"].model, OPUS_DEFAULT)  # 원본 불변

    def test_worker_turn_floors_at_coordinator_tier(self):
        h = self._h([worker({"w1.txt": "x\n"}, self.root), verifier("PASS")])
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        self.assertEqual(h.consumed[0].model, TIER["high"])  # worker=standard이나 코디네이터(high) 하한
        self.assertEqual(h.consumed[1].model, TIER["high"])  # verifier micro=high

    def test_quest_events_record_used_model(self):
        # 모델 티어 → route-priors 데이터 축: 실사용 provider:model이 로그에 남는다
        h = self._h([worker({"w1.txt": "x\n"}, self.root), verifier("PASS")])
        h.handle("w1.txt 만들어")
        d = os.path.join(self.root, ".asgard", "quest")
        log = "\n".join(open(os.path.join(d, f)).read() for f in os.listdir(d) if f.endswith(".jsonl"))
        self.assertIn('"role":"worker","event":"work"', log)
        self.assertIn(f"anthropic:{TIER['high']}", log)  # work·verify — 코디네이터 하한으로 동일 티어

    def test_second_replan_uses_thinker_alt_placement(self):
        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.thinker_alt]\nprovider = "ollama"\nmodel = "alt-m"\n'
        )
        seq = [
            worker({"w1.txt": "a\n"}, self.root),
            verifier("FAIL", structural=True, sig="s1"),
            thinker("재계획 1"),
            worker({"w1.txt": "b\n"}, self.root),
            verifier("FAIL", structural=True, sig="s2"),
            thinker("재계획 2 — clean slate"),
            worker({"w1.txt": "c\n"}, self.root),
            verifier("PASS"),
        ]
        h = self._h(seq)
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        thinkers = [s for s in h.consumed if s.label == "thinker"]
        self.assertEqual(thinkers[0].role, "thinker")  # 1차 재계획 = 기본 배치
        self.assertEqual(thinkers[1].role, "thinker_alt")  # 2차 = clean-slate 대체 모델

    def test_placed_verifier_fallback_keeps_verifier_capability_role(self):
        from asgard.agent.claude_native import UsageCapError

        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.verifier]\nprovider = "ollama"\nmodel = "placed-v"\n'
        )

        def capped():
            raise UsageCapError("cap")

        failed = FakeSession(SessionResult(text="", stop_reason="error"), effect=capped, label="verifier")
        h = self._h([worker({"w1.txt": "x\n"}, self.root), failed, verifier("PASS")])
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        verifier_sessions = [s for s in h.consumed if s.label == "verifier"]
        self.assertEqual([s.role for s in verifier_sessions], ["verifier", "verifier"])
        self.assertTrue(all(s.readonly for s in verifier_sessions))

    def test_placed_thinker_fallback_keeps_thinker_capability_role(self):
        from asgard.agent.claude_native import UsageCapError

        os.makedirs(os.path.join(self.root, ".asgard"), exist_ok=True)
        open(os.path.join(self.root, ".asgard", "config.toml"), "w").write(
            '[trinity.thinker]\nprovider = "ollama"\nmodel = "placed-t"\n'
        )

        def capped():
            raise UsageCapError("cap")

        failed = FakeSession(SessionResult(text="", stop_reason="error"), effect=capped, label="thinker")
        seq = [
            worker({"w1.txt": "bad\n"}, self.root),
            verifier("FAIL", structural=True, sig="bad-plan"),
            failed,
            thinker("fallback plan"),
            worker({"w1.txt": "good\n"}, self.root),
            verifier("PASS"),
        ]
        h = self._h(seq)
        out = h.handle("w1.txt 만들어")
        self.assertIn(DONE, out)
        thinker_sessions = [s for s in h.consumed if s.label == "thinker"]
        self.assertEqual([s.role for s in thinker_sessions], ["thinker", "thinker"])
        self.assertTrue(all(s.readonly for s in thinker_sessions))


if __name__ == "__main__":
    unittest.main(verbosity=1)
