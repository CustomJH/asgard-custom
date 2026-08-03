"""`asgard orchestrate` 의 표면 계약 — 정책을 보여 주고 바꾸는 자리.

이 표면이 지는 계약은 셋이다. ① **관문이 아니다** — 잘못된 값을 줘도 종료 코드는 0 이고,
대신 고를 수 있는 것을 그 자리에서 다시 보여 준다. ② **엔진이 없어도 죽지 않는다** — 계량기
(`engines`)와 정책 엔진(`orchestration.policy`)은 이 표면보다 늦게 배송될 수 있고, 없을 때
할 일은 실패가 아니라 그 칸만 비우는 것이다. ③ **기본 호출은 네트워크를 안 탄다** — 설정을
고치러 들어온 사람에게 매번 엔진 전부를 다시 재게 하면 설정 한 줄 바꾸는 데 몇 초가 든다.

셋 다 "안 되면 조용히 덜 보여 준다" 로 넘어진다. 반대쪽(못 재면 막는다)으로 넘어지면 엔진
하나가 안 닿는다는 이유로 정책을 못 바꾸게 되고, 그건 사람이 이 화면에 온 이유를 막는 것이다.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from cli_boundary import run_cli  # noqa: E402


class _Repo:
    """빈 저장소 하나 — 설정이 아무것도 없는 자리에서 기본값이 무엇인지 재려면 필요하다."""

    def __enter__(self) -> str:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        os.makedirs(os.path.join(self.root, ".git"), exist_ok=True)
        self._before = os.getcwd()
        os.chdir(self.root)
        return self.root

    def __exit__(self, *exc: object) -> None:
        os.chdir(self._before)
        self._tmp.cleanup()


class TestPolicySurface(unittest.TestCase):
    def test_default_policy_is_auto(self):
        """기본값은 auto 다 — 사용자가 아무것도 안 골랐을 때 아스가르드가 알아서 한다."""
        with _Repo():
            out = run_cli("orchestrate", "--json")
        self.assertEqual(out.exit_code, 0)
        payload = json.loads(out.stdout)
        self.assertEqual(payload["policy"], "auto")
        self.assertEqual(payload["source"], "built-in default")

    def test_every_policy_is_offered_with_a_meaning(self):
        """고를 수 있는 값마다 뜻이 붙어 있어야 한다 — 이름만 늘어놓으면 아무도 안 바꾼다."""
        with _Repo():
            payload = json.loads(run_cli("orchestrate", "--json").stdout)
        names = [row["name"] for row in payload["policies"]]
        self.assertEqual(names, ["auto", "solo", "graph", "squad", "off"])
        for row in payload["policies"]:
            self.assertTrue(row["help"].strip(), f"{row['name']} 에 뜻이 없다")

    def test_human_screen_shows_the_current_choice_and_the_others(self):
        with _Repo():
            out = run_cli("orchestrate")
        self.assertEqual(out.exit_code, 0)
        for name in ("auto", "solo", "graph", "squad", "off"):
            self.assertIn(name, out.output)

    def test_bad_policy_does_not_become_a_gate(self):
        """잘못된 값에도 종료 코드는 0 — 이 자리는 설정 표면이지 판정기가 아니다."""
        with _Repo():
            out = run_cli("orchestrate", "--set", "존재하지-않는-정책")
        self.assertEqual(out.exit_code, 0)


class TestFailOpen(unittest.TestCase):
    """엔진·정책 모듈이 없어도 화면은 선다 — 표면이 엔진보다 먼저 배송될 수 있다."""

    def test_screen_survives_a_missing_engine_meter(self):
        import asgard.commands.orchestrate as surface

        def _none() -> object | None:
            return None

        with mock.patch.object(surface, "_engines_mod", _none), _Repo():
            out = run_cli("orchestrate")
            payload = json.loads(run_cli("orchestrate", "--json").stdout)
        self.assertEqual(out.exit_code, 0)
        self.assertEqual(payload["engines"], [])
        # 못 잰 것을 "0개 연결됨" 으로 적으면 그건 거짓이다 — 이유가 남아 있어야 한다.
        self.assertTrue(payload["unmeasured"].strip())

    def test_a_thrown_probe_is_reported_not_raised(self):
        """계량기가 터져도 화면은 선다. 관측이 실행을 세우면 그건 관측이 아니라 관문이다."""
        import asgard.commands.orchestrate as surface

        class _Boom:
            def cached(self, *a: object, **k: object):
                raise RuntimeError("잴 수 없다")

            def probe(self, *a: object, **k: object):
                raise RuntimeError("잴 수 없다")

        def _boom() -> object:
            return _Boom()

        with mock.patch.object(surface, "_engines_mod", _boom), _Repo():
            payload = json.loads(run_cli("orchestrate", "--json").stdout)
        self.assertEqual(payload["engines"], [])
        self.assertIn("잴 수 없다", payload["unmeasured"])


class TestProbeIsOptIn(unittest.TestCase):
    """기본 호출은 캐시만 읽는다 — `--probe` 를 준 호출만 실제로 다시 잰다."""

    def _spy(self):
        calls = {"cached": 0, "probe": 0}

        class _Spy:
            def cached(self, *a: object, **k: object):
                calls["cached"] += 1
                return []

            def probe(self, *a: object, **k: object):
                calls["probe"] += 1
                return []

        return calls, _Spy()

    def test_plain_call_reads_the_cache_only(self):
        import asgard.commands.orchestrate as surface

        calls, spy = self._spy()

        def _spy_mod() -> object:
            return spy

        with mock.patch.object(surface, "_engines_mod", _spy_mod), _Repo():
            run_cli("orchestrate", "--json")
        self.assertEqual(calls["probe"], 0, "설정을 보러 온 호출이 네트워크를 탔다")
        self.assertEqual(calls["cached"], 1)

    def test_probe_flag_actually_remeasures(self):
        import asgard.commands.orchestrate as surface

        calls, spy = self._spy()

        def _spy_mod() -> object:
            return spy

        with mock.patch.object(surface, "_engines_mod", _spy_mod), _Repo():
            run_cli("orchestrate", "--probe", "--json")
        self.assertEqual(calls["probe"], 1)
        self.assertEqual(calls["cached"], 0)


if __name__ == "__main__":
    unittest.main()
