"""asgard-k6 — 부하 시험 레인의 계약 봉인 (k6.py + assets/k6_kit).

부하 하네스의 결함은 조용하다. 요약을 잘못 읽어도 숫자는 그럴듯하게 나오고, 임계값이
깨졌는데 통과로 보고해도 CI 는 초록이다. 그래서 여기서 잠그는 것은 "돌아가는가"가 아니라
**어긋나면 드러나는가**다:

  요약 계약   JS 쪽 스키마 문자열·출력 경로와 파이썬 파서가 같은 값을 본다 (드리프트 봉인).
  명령 조립   마운트·이미지·환경이 실제로 나가는 argv 에 있다 (순수 함수라 도커 없이 본다).
  판정        임계값 결과와 종료 코드가 어긋나는 실행을 `exit_agrees` 가 사건으로 본다.
  표적        pacer 의 오류 주입이 확률이 아니라 **주기**다 — 기대 실패 건수가 계산된다.

도커가 필요한 실검증(`selftest`)은 `ASGARD_K6_DOCKER=1` 일 때만 돈다 — 기본 스위트는
네트워크·엔진 없이 밀폐돼야 하기 때문이다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from asgard import k6


def _load_pacer():
    spec = importlib.util.spec_from_file_location("asgard_k6_pacer", k6.pacer_script())
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _summary(**overrides) -> dict:
    payload = {
        "schema": k6.SUMMARY_SCHEMA,
        "scenario": "selftest",
        "target": "http://127.0.0.1:8799",
        "duration_ms": 1200.0,
        "requests": {"count": 40, "failed": 10, "failed_rate": 0.25, "rate_per_s": 33.3},
        "latency_ms": {"avg": 81.0, "min": 79.0, "med": 80.5, "p90": 83.0, "p95": 84.0, "p99": 90.0, "max": 95.0},
        "iterations": 40,
        "vus_max": 4,
        "checks": {"passes": 40, "fails": 0, "rows": []},
        "thresholds": [{"metric": "http_req_duration", "expression": "p(95)<5000", "ok": True}],
        "custom": {},
    }
    payload.update(overrides)
    return payload


class TestKitIntegrity(unittest.TestCase):
    """키트는 설치본에 실려 나간다 — 파일 하나가 빠지면 레인 전체가 죽는다."""

    def test_kit_ships_its_parts(self):
        kit = k6.kit_dir()
        for relative in ("lib/asgard.js", "pacer.py", "compose.yml", "out/.gitkeep", "project/.gitkeep"):
            self.assertTrue((kit / relative).is_file(), f"키트에 {relative} 가 없다")

    def test_mount_points_exist_because_the_kit_is_read_only(self):
        """`/asgard` 가 읽기 전용으로 마운트되므로 그 안의 마운트 자리는 미리 있어야 한다.

        디렉터리가 없으면 도커가 마운트 지점을 만들려다 read-only 로 실패한다 — 실행이
        시작조차 못 하고, 증상은 시나리오 오류처럼 보인다."""
        kit = k6.kit_dir()
        self.assertTrue((kit / "out").is_dir())
        self.assertTrue((kit / "project").is_dir())

    def test_every_scenario_follows_the_contract(self):
        for name, scenario in k6.builtin_scenarios().items():
            source = scenario.path.read_text(encoding="utf-8")
            with self.subTest(scenario=name):
                self.assertIn("../lib/asgard.js", source, "시나리오는 정본 라이브러리를 통해야 한다")
                self.assertIn("export function handleSummary", source, "요약을 내보내지 않으면 결과가 없다")
                self.assertIn("summarize(", source, "요약 조립은 라이브러리 한 곳에서만 한다")

    def test_scenarios_do_not_use_random_query_selection(self):
        """난수로 질의를 고르면 두 실행의 차이가 코드 때문인지 운 때문인지 갈리지 않는다."""
        for name, scenario in k6.builtin_scenarios().items():
            with self.subTest(scenario=name):
                self.assertNotIn("Math.random", scenario.path.read_text(encoding="utf-8"))


class TestSchemaDrift(unittest.TestCase):
    """JS 와 파이썬이 같은 계약을 본다 — 한쪽만 바뀌면 여기서 걸린다."""

    def _lib(self) -> str:
        return (k6.kit_dir() / "lib" / "asgard.js").read_text(encoding="utf-8")

    def test_summary_schema_string_is_shared(self):
        self.assertIn(f"export const SCHEMA = '{k6.SUMMARY_SCHEMA}'", self._lib())

    def test_default_out_path_matches_the_container_mount(self):
        expected = f"{k6.CONTAINER_MOUNT}/out/{k6.SUMMARY_NAME}"
        self.assertIn(f"__ENV.ASGARD_K6_OUT || '{expected}'", self._lib())

    def test_compose_default_image_matches_the_runner_default(self):
        compose = (k6.kit_dir() / "compose.yml").read_text(encoding="utf-8")
        self.assertIn(f"${{ASGARD_K6_IMAGE:-{k6.DEFAULT_IMAGE}}}", compose)
        self.assertIn(f"name: {k6.PROJECT}", compose)


class TestScenarioResolution(unittest.TestCase):
    def test_builtins_are_present(self):
        names = set(k6.builtin_scenarios())
        self.assertLessEqual({"selftest", "http-smoke", "recall", "saturate", "search"}, names)

    def test_project_scenarios_win_on_a_name_clash(self):
        with tempfile.TemporaryDirectory() as root:
            lane = Path(root, ".asgard", "k6")
            lane.mkdir(parents=True)
            (lane / "recall.js").write_text("// mine\n", encoding="utf-8")
            found = k6.scenarios(root)
            self.assertEqual(found["recall"].origin, "project")
            self.assertEqual(found["selftest"].origin, "builtin")

    def test_a_direct_path_is_its_own_scenario(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "custom.js")
            path.write_text("// one-off\n", encoding="utf-8")
            scenario = k6.find_scenario(str(path))
            self.assertIsNotNone(scenario)
            self.assertEqual(scenario.name, "custom")
            self.assertEqual(scenario.origin, "project")

    def test_unknown_name_is_none(self):
        self.assertIsNone(k6.find_scenario("no-such-scenario"))


class TestCommandAssembly(unittest.TestCase):
    """실제로 나갈 argv — 도커 없이 여기서 본다."""

    def setUp(self):
        self.docker = k6.Runner("docker", "/usr/bin/docker", "grafana/k6:test")
        self.native = k6.Runner("native", "/usr/local/bin/k6")
        self.scenario = k6.Scenario("selftest", k6.kit_dir() / "scenarios" / "selftest.js", "builtin")

    def test_container_mounts_the_kit_read_only(self):
        argv = k6.build_argv(self.docker, self.scenario, "/tmp/run")
        self.assertIn(f"{k6.kit_dir()}:{k6.CONTAINER_MOUNT}:ro", argv)
        self.assertIn(f"/tmp/run:{k6.CONTAINER_MOUNT}/out", argv)
        self.assertEqual(argv[-1], f"{k6.CONTAINER_MOUNT}/scenarios/selftest.js")
        self.assertIn("grafana/k6:test", argv)

    def test_container_can_reach_a_host_target(self):
        argv = k6.build_argv(self.docker, self.scenario, "/tmp/run")
        self.assertIn("--add-host=host.docker.internal:host-gateway", argv)
        self.assertEqual(k6.container_target(self.docker, 8799), "http://host.docker.internal:8799")
        self.assertEqual(k6.container_target(self.native, 8799), "http://127.0.0.1:8799")

    def test_summary_path_is_injected_not_guessed(self):
        argv = k6.build_argv(self.docker, self.scenario, "/tmp/run")
        self.assertIn(f"ASGARD_K6_OUT={k6.CONTAINER_MOUNT}/out/{k6.SUMMARY_NAME}", argv)
        native = k6.build_argv(self.native, self.scenario, "/tmp/run")
        self.assertIn(f"ASGARD_K6_OUT={os.path.join('/tmp/run', k6.SUMMARY_NAME)}", native)

    def test_project_scenario_mounts_beside_the_library(self):
        """프로젝트 시나리오는 `/asgard/project` 로 들어와야 `../lib/asgard.js` 가 맞는다."""
        with tempfile.TemporaryDirectory() as root:
            lane = Path(root, ".asgard", "k6")
            lane.mkdir(parents=True)
            path = lane / "mine.js"
            path.write_text("// mine\n", encoding="utf-8")
            scenario = k6.Scenario("mine", path, "project")
            argv = k6.build_argv(self.docker, scenario, "/tmp/run")
            self.assertIn(f"{lane}:{k6.CONTAINER_MOUNT}/project:ro", argv)
            self.assertEqual(argv[-1], f"{k6.CONTAINER_MOUNT}/project/mine.js")

    def test_env_reaches_the_scenario(self):
        argv = k6.build_argv(self.docker, self.scenario, "/tmp/run", {"ASGARD_K6_VUS": "9"})
        self.assertIn("ASGARD_K6_VUS=9", argv)
        native = k6.build_argv(self.native, self.scenario, "/tmp/run", {"ASGARD_K6_VUS": "9"})
        self.assertIn("ASGARD_K6_VUS=9", native)

    def test_hostile_env_names_are_refused(self):
        for bad in ("A B", "-x", "", "A;rm -rf /"):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                k6.build_argv(self.docker, self.scenario, "/tmp/run", {bad: "1"})

    def test_container_name_is_validated(self):
        with self.assertRaises(ValueError):
            k6.build_argv(self.docker, self.scenario, "/tmp/run", container_name="../escape")

    def test_bind_host_is_narrow_for_the_native_runner(self):
        self.assertEqual(k6.bind_host(self.native), "127.0.0.1")
        self.assertEqual(k6.bind_host(self.docker), "0.0.0.0")


class TestSummaryParsing(unittest.TestCase):
    def test_round_trip(self):
        report = k6.parse_summary(_summary(), exit_code=0, runner="docker", k6_version="k6 v2.1.0")
        self.assertEqual(report.requests, 40)
        self.assertEqual(report.failed, 10)
        self.assertEqual(report.latency_ms["p95"], 84.0)
        self.assertEqual(report.vus_max, 4)
        self.assertTrue(report.thresholds_ok)
        self.assertTrue(report.ok)

    def test_a_foreign_shape_is_refused_not_zero_filled(self):
        """모르는 모양을 0 으로 채우면 '요청 0건, 지연 0ms' 라는 완벽한 보고서가 나온다."""
        for payload in ({}, {"schema": "something-else"}, {"schema": None}):
            with self.subTest(payload=payload), self.assertRaises(k6.SummaryError):
                k6.parse_summary(payload)
        with self.assertRaises(k6.SummaryError):
            k6.parse_summary([])  # type: ignore[arg-type]

    def test_verdict_needs_both_halves(self):
        breached = _summary(thresholds=[{"metric": "http_req_duration", "expression": "p(95)<5", "ok": False}])
        report = k6.parse_summary(breached, exit_code=k6.THRESHOLD_EXIT)
        self.assertFalse(report.thresholds_ok)
        self.assertFalse(report.ok)
        self.assertTrue(report.exit_agrees)

        crashed = k6.parse_summary(_summary(), exit_code=2)
        self.assertTrue(crashed.thresholds_ok)
        self.assertFalse(crashed.ok, "임계값을 지켰어도 비정상 종료는 통과가 아니다")

    def test_disagreement_between_exit_code_and_verdict_is_visible(self):
        """임계값이 깨졌는데 0 으로 끝나면 CI 가 빨간 것을 초록으로 통과시킨다."""
        lying = k6.parse_summary(
            _summary(thresholds=[{"metric": "http_req_duration", "expression": "p(95)<5", "ok": False}]),
            exit_code=0,
        )
        self.assertFalse(lying.exit_agrees)

        silent = k6.parse_summary(_summary(), exit_code=k6.THRESHOLD_EXIT)
        self.assertFalse(silent.exit_agrees, "멀쩡한 실행이 임계값 코드로 끝나는 것도 어긋남이다")

    def test_no_thresholds_means_nothing_to_break(self):
        report = k6.parse_summary(_summary(thresholds=[]), exit_code=0)
        self.assertTrue(report.thresholds_ok)
        self.assertTrue(report.ok)


class TestRunRecord(unittest.TestCase):
    def test_report_is_written_and_reads_back(self):
        report = k6.parse_summary(_summary(), exit_code=0, runner="docker", k6_version="k6 v2.1.0")
        with tempfile.TemporaryDirectory() as root:
            path = k6.record_run(root, report, "20260728T000000-selftest")
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["k6_version"], "k6 v2.1.0")
            again = k6.parse_summary(payload, exit_code=payload["exit_code"])
            self.assertEqual(again.requests, report.requests)
            self.assertEqual(again.latency_ms, report.latency_ms)


class TestPacer(unittest.TestCase):
    """기준 표적의 거동은 미리 계산된다 — 그래야 하네스를 대조할 수 있다."""

    def setUp(self):
        self.pacer_mod = _load_pacer()

    def test_failures_are_periodic_not_probabilistic(self):
        for rate, total in ((0.25, 40), (0.5, 40), (0.1, 100), (0.0, 40)):
            pacer = self.pacer_mod.Pacer(latency_ms=0, error_rate=rate, max_concurrency=0)
            failures = sum(1 for _ in range(total) if pacer.handle("/ok")[1])
            with self.subTest(rate=rate):
                self.assertEqual(failures, int(total * rate))

    def test_every_request_fails_at_rate_one(self):
        pacer = self.pacer_mod.Pacer(latency_ms=0, error_rate=1.0, max_concurrency=0)
        self.assertTrue(all(pacer.handle("/ok")[1] for _ in range(10)))

    def test_status_code_follows_the_injection(self):
        pacer = self.pacer_mod.Pacer(latency_ms=0, error_rate=0.5, max_concurrency=0)
        codes = [pacer.handle("/ok")[0] for _ in range(4)]
        self.assertEqual(codes.count(500), 2)
        self.assertEqual(codes.count(200), 2)

    def test_the_target_counts_for_itself(self):
        pacer = self.pacer_mod.Pacer(latency_ms=0, error_rate=0.25, max_concurrency=0)
        for _ in range(20):
            pacer.handle("/ok")
        stats = pacer.stats()
        self.assertEqual(stats["requests"], 20)
        self.assertEqual(stats["errored"], 5)
        self.assertEqual(stats["by_path"]["/ok"], 20)

    def test_throughput_ceiling_is_littles_law(self):
        pacer = self.pacer_mod.Pacer(latency_ms=100, error_rate=0, max_concurrency=4)
        self.assertAlmostEqual(pacer.stats()["throughput_ceiling_rps"], 40.0, places=6)
        unbounded = self.pacer_mod.Pacer(latency_ms=100, error_rate=0, max_concurrency=0)
        self.assertIsNone(unbounded.stats()["throughput_ceiling_rps"])

    def test_concurrency_cap_is_enforced(self):
        import threading

        pacer = self.pacer_mod.Pacer(latency_ms=60, error_rate=0, max_concurrency=2)
        threads = [threading.Thread(target=pacer.handle, args=("/ok",)) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertLessEqual(pacer.stats()["peak_in_flight"], 2)
        self.assertEqual(pacer.stats()["requests"], 8)


class TestRunnerResolution(unittest.TestCase):
    def test_explicit_preference_is_honored(self):
        import shutil

        if shutil.which("docker"):
            self.assertEqual(k6.resolve_runner("docker").kind, "docker")
        if shutil.which("k6"):
            runner = k6.resolve_runner("native")
            self.assertEqual(runner.kind, "native")
            self.assertFalse(runner.containerized)

    def test_image_override_reaches_the_runner(self):
        previous = os.environ.get("ASGARD_K6_IMAGE")
        os.environ["ASGARD_K6_IMAGE"] = "example/k6:pinned"
        try:
            self.assertEqual(k6.default_image(), "example/k6:pinned")
        finally:
            if previous is None:
                os.environ.pop("ASGARD_K6_IMAGE", None)
            else:
                os.environ["ASGARD_K6_IMAGE"] = previous


class TestEnvPromotion(unittest.TestCase):
    """`--env BANK=x` 는 시나리오가 읽는 이름(ASGARD_K6_BANK)으로 올라가야 쓸모가 있다."""

    def _parse(self, pairs):
        from asgard.commands.k6 import _parse_env

        return _parse_env(pairs)

    def test_bare_uppercase_keys_get_the_lane_prefix(self):
        self.assertEqual(self._parse(["BANK=hvami"]), {"ASGARD_K6_BANK": "hvami"})
        self.assertEqual(self._parse(["PROFILE=short"]), {"ASGARD_K6_PROFILE": "short"})

    def test_already_prefixed_keys_pass_through(self):
        self.assertEqual(self._parse(["ASGARD_K6_LADDER=1,2,4"]), {"ASGARD_K6_LADDER": "1,2,4"})

    def test_a_value_may_contain_equals(self):
        self.assertEqual(self._parse(["TOKEN=a=b=c"]), {"ASGARD_K6_TOKEN": "a=b=c"})

    def test_a_pair_without_equals_is_refused(self):
        with self.assertRaises(ValueError):
            self._parse(["BANK"])


@unittest.skipUnless(os.environ.get("ASGARD_K6_DOCKER") == "1", "실엔진 검증 — ASGARD_K6_DOCKER=1 일 때만")
class TestHarnessIntegrityLive(unittest.TestCase):
    """레인이 자기 자신에게 거는 검사 — 엔진이 있을 때만 돈다."""

    def test_selftest_is_green(self):
        with tempfile.TemporaryDirectory() as out:
            result = k6.selftest(out_dir=out, iterations=20, vus=4)
        self.assertEqual(result.error, "")
        red = [c.name for c in result.checks if not c.ok]
        self.assertFalse(red, f"정합성 검사 실패: {red}")


if __name__ == "__main__":
    unittest.main()
