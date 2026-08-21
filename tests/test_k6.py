"""asgard-k6 — 부하 시험 레인의 계약 봉인 (k6.py + assets/k6_kit).

부하 하네스의 결함은 조용하다. 요약을 잘못 읽어도 숫자는 그럴듯하게 나오고, 임계값이
깨졌는데 통과로 보고해도 CI는 초록이다. 그래서 여기서 잠그는 것은 "돌아가는가"가 아니라
**어긋나면 드러나는가**다:

  요약 계약   JS 쪽 스키마 문자열·출력 경로와 파이썬 파서가 같은 값을 본다 (드리프트 봉인).
  명령 조립   마운트·이미지·환경이 실제로 나가는 argv에 있다 (순수 함수라 도커 없이 본다).
  판정        임계값 결과와 종료 코드가 어긋나는 실행을 `exit_agrees`가 사건으로 본다.
  표적        pacer의 오류 주입이 확률이 아니라 **주기**다 — 기대 실패 건수가 계산된다.

도커가 필요한 실검증(`selftest`)은 `ASGARD_K6_DOCKER=1` 일 때만 돈다 — 기본 스위트는
네트워크·엔진 없이 밀폐돼야 하기 때문이다.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from asgard import k6, k6_gate, k6_selftest


def _load_pacer():
    spec = importlib.util.spec_from_file_location("asgard_k6_pacer", k6.pacer_script())
    assert spec is not None and spec.loader is not None, "키트가 배송한 pacer 를 못 읽었다"
    module = importlib.util.module_from_spec(spec)
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
        for relative in ("lib/asgard.js", "pacer.py", "out/.gitkeep", "project/.gitkeep"):
            self.assertTrue((kit / relative).is_file(), f"키트에 {relative} 가 없다")

    def test_docker_artifacts_do_not_live_in_the_kit(self):
        """이미지·compose의 집은 `docker/asgard-k6/` 다 — 키트는 실려 가는 것만 담는다.

        두 벌이 생기면 어느 쪽으로 잰 값인지 물을 수 없게 된다."""
        kit = k6.kit_dir()
        for stray in ("compose.yml", "docker-compose.yml", "Dockerfile"):
            self.assertFalse((kit / stray).exists(), f"{stray} 는 docker/{k6.PROJECT}/ 에 있어야 한다")

    def test_mount_points_exist_because_the_kit_is_read_only(self):
        """`/asgard`가 읽기 전용으로 마운트되므로 그 안의 마운트 자리는 미리 있어야 한다.

        디렉터리가 없으면 도커가 마운트 지점을 만들려다 read-only로 실패한다 — 실행이
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
    """JS와 파이썬이 같은 계약을 본다 — 한쪽만 바뀌면 여기서 걸린다."""

    def _lib(self) -> str:
        return (k6.kit_dir() / "lib" / "asgard.js").read_text(encoding="utf-8")

    def test_summary_schema_string_is_shared(self):
        self.assertIn(f"export const SCHEMA = '{k6.SUMMARY_SCHEMA}'", self._lib())

    def test_default_out_path_matches_the_container_mount(self):
        expected = f"{k6.CONTAINER_MOUNT}/out/{k6.SUMMARY_NAME}"
        self.assertIn(f"__ENV.ASGARD_K6_OUT || '{expected}'", self._lib())

    def test_compose_default_image_matches_the_runner_default(self):
        home = k6.docker_dir()
        assert home is not None, "저장소 체크아웃에는 docker/asgard-k6/ 가 있어야 한다"
        compose = (home / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn(f"${{ASGARD_K6_IMAGE:-{k6.DEFAULT_IMAGE}}}", compose)
        self.assertIn(f"name: {k6.PROJECT}", compose)


class TestLaneIsTheProject(unittest.TestCase):
    """도커에 넘어가는 호스트 경로는 **잴 프로젝트의 `.asgard/k6/`** 아래여야 한다.

    여기가 흔들리면 증상이 조용하다: 체크아웃에서는 잘 돌고 설치본에서만 죽거나(`src/`가
    없다), 여러 프로젝트가 한 설치본의 키트를 함께 마운트해 "이 실행이 어떤 시나리오를
    돌았나"가 프로젝트 밖에서 정해진다."""

    docker = k6.Runner("docker", "/usr/bin/docker", "grafana/k6:test")

    def test_the_project_is_found_by_walking_up_not_by_standing_still(self):
        """`src/` 안에서 부른 실행이 거기에 `.asgard/`를 새로 파면 기록이 두 곳으로 갈린다."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "proj").resolve()
            (root / ".asgard").mkdir(parents=True)
            nested = root / "src" / "deep" / "deeper"
            nested.mkdir(parents=True)
            self.assertEqual(k6.project_root(nested), root)
            self.assertEqual(k6.project_root(root), root)

    def test_a_git_boundary_is_the_project_when_there_is_no_asgard_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "proj").resolve()
            (root / ".git").mkdir(parents=True)
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            self.assertEqual(k6.project_root(nested), root)

    def test_the_home_asgard_dir_does_not_swallow_a_repo_beneath_it(self):
        """아스가르드는 자격 증명을 `~/.asgard/`에 둔다 — 표식 종류로 우선순위를 매기면
        홈 아래의 저장소가 자기 `.git`을 지나쳐 홈을 프로젝트로 잡는다."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp, "home").resolve()
            (home / ".asgard").mkdir(parents=True)  # 사용자 홈의 아스가르드 (프로젝트 아님)
            repo = home / "proj"
            (repo / ".git").mkdir(parents=True)
            self.assertEqual(k6.project_root(repo / "src"), repo)

    def test_the_lane_hangs_off_the_project(self):
        root = Path("/somewhere/proj")
        self.assertEqual(k6.lane_dir(root), root / ".asgard" / "k6")
        for path in (k6.mounted_kit_dir(root), k6.runs_dir(root), k6.compose_out_dir(root)):
            self.assertEqual(path.parent, k6.lane_dir(root))

    def test_sync_materialises_the_shipped_kit_inside_the_project(self):
        with tempfile.TemporaryDirectory() as root:
            kit = k6.sync_kit(root)
            self.assertEqual(kit, k6.mounted_kit_dir(root))
            for relative in ("lib/asgard.js", "pacer.py", "scenarios/selftest.js", "out/.gitkeep"):
                self.assertTrue((kit / relative).is_file(), f"실체화된 키트에 {relative} 가 없다")
            self.assertTrue(k6.kit_is_synced(root))

    def test_resync_is_content_addressed_not_blind(self):
        """매 실행 부르는 자리다 — 같으면 손대지 않고, 다르면 반드시 되돌린다."""
        with tempfile.TemporaryDirectory() as root:
            kit = k6.sync_kit(root)
            marker = kit / "lib" / "asgard.js"
            untouched = marker.stat().st_mtime_ns
            self.assertEqual(k6.sync_kit(root), kit)
            self.assertEqual(marker.stat().st_mtime_ns, untouched, "내용이 같은데 다시 복사했다")

            marker.write_text("// 손댄 키트\n", encoding="utf-8")
            self.assertFalse(k6.kit_is_synced(root), "실체화된 키트가 배송본과 갈라졌는데 동기라고 말한다")
            k6.sync_kit(root)
            self.assertNotIn("손댄 키트", marker.read_text(encoding="utf-8"))
            self.assertTrue(k6.kit_is_synced(root))

    def test_a_scenario_dropped_by_an_upgrade_does_not_survive(self):
        """덮어 쓰기로 동기화하면 이전 판에서 사라진 시나리오가 그대로 산다."""
        with tempfile.TemporaryDirectory() as root:
            kit = k6.sync_kit(root)
            ghost = kit / "scenarios" / "removed-upstream.js"
            ghost.write_text("// 이전 판의 잔해\n", encoding="utf-8")
            self.assertFalse(k6.kit_is_synced(root), "배송본에 없는 파일이 있는데 동기라고 말한다")
            k6.sync_kit(root)
            self.assertFalse(ghost.exists(), "이전 판의 시나리오가 재동기화 뒤에도 남아 있다")

    def test_every_mounted_host_path_is_inside_the_project(self):
        """이 검사가 이 수리의 전부다 — `-v` 왼쪽이 하나라도 프로젝트 밖이면 되돌아간 것이다."""
        docker = k6.Runner("docker", "/usr/bin/docker", "grafana/k6:test")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            kit = k6.prepare_lane(root)
            (k6.lane_dir(root) / "scenarios").mkdir(parents=True, exist_ok=True)
            mine = k6.lane_dir(root) / "scenarios" / "mine.js"
            mine.write_text("// mine\n", encoding="utf-8")

            for scenario in (
                k6.Scenario("selftest", k6.kit_dir() / "scenarios" / "selftest.js", "builtin"),
                k6.Scenario("mine", mine, "project"),
            ):
                argv = k6.build_argv(scenario=scenario, runner=docker, out_dir=k6.runs_dir(root) / "now", kit=kit)
                sources = [argv[i + 1].split(":")[0] for i, item in enumerate(argv) if item == "-v"]
                self.assertTrue(sources, "마운트가 하나도 없다")
                with self.subTest(scenario=scenario.name):
                    for source in sources:
                        self.assertTrue(
                            Path(source).is_relative_to(k6.lane_dir(root)),
                            f"{source} 가 프로젝트 레인 밖이다 — 볼륨의 집은 <프로젝트>/.asgard/k6 다",
                        )

    def test_the_run_command_hands_the_runner_the_lane_kit(self):
        """`build_argv`는 안 넘기면 배송 경로로 내려간다 — 표면이 실제로 넘기는지는 여기서 본다.

        `kit=` 한 줄이 조용히 빠지면 되돌아간 것이고, 증상은 실검증 전까지 안 보인다."""
        from unittest import mock

        from asgard.commands import k6 as cmd

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".asgard").mkdir()
            seen: dict[str, object] = {}

            def capture(scenario, *, runner, out_dir, kit=None, **rest):
                seen["kit"] = kit
                seen["out_dir"] = out_dir
                raise k6.SummaryError("조립만 본다 — 여기서 멈춘다")

            with (
                mock.patch.object(k6, "resolve_runner", return_value=self.docker),
                mock.patch.object(k6, "runner_version", return_value="k6 vTest"),
                mock.patch.object(k6, "run_scenario", side_effect=capture),
                mock.patch.object(cmd, "_root", return_value=str(root)),
            ):
                cmd.run_k6_run("selftest", json_=True)

            self.assertEqual(seen["kit"], str(k6.mounted_kit_dir(root)))
            self.assertTrue(Path(str(seen["out_dir"])).is_relative_to(k6.runs_dir(root)))

    def test_the_selftest_command_runs_inside_the_lane(self):
        """세 판의 산출도 마운트되는 볼륨이다 — 시스템 임시 디렉터리로 돌아가면 안 된다."""
        from unittest import mock

        from asgard.commands import k6 as cmd

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".asgard").mkdir()
            seen: dict[str, object] = {}

            def capture(*, runner, out_dir, kit=None, **rest):
                seen["kit"] = kit
                seen["out_dir"] = out_dir
                return k6_selftest.Selftest(checks=[k6_selftest.Check("stub", True, "", "")])

            with (
                mock.patch.object(k6, "resolve_runner", return_value=self.docker),
                mock.patch.object(k6_selftest, "selftest", side_effect=capture),
                mock.patch.object(cmd, "_root", return_value=str(root)),
            ):
                self.assertEqual(cmd.run_k6_selftest(json_=True), 0)

            self.assertEqual(seen["kit"], str(k6.mounted_kit_dir(root)))
            self.assertTrue(Path(str(seen["out_dir"])).is_relative_to(k6.lane_dir(root)))

    def test_compose_volumes_are_anchored_to_the_lane_not_the_checkout(self):
        home = k6.docker_dir()
        assert home is not None, "저장소 체크아웃에는 docker/asgard-k6/ 가 있어야 한다"
        compose = (home / "docker-compose.yml").read_text(encoding="utf-8")
        body = compose.split("\nservices:", 1)[1]  # 헤더 주석은 설명이라 규칙에서 뺀다
        self.assertNotIn("../../src/", body, "compose 가 체크아웃의 src/ 를 마운트한다 — 설치본에는 없는 경로다")
        for mount in (f"{k6.CONTAINER_MOUNT}:ro", f"{k6.CONTAINER_MOUNT}/out"):
            line = next(row for row in body.splitlines() if row.strip().endswith(mount))
            self.assertIn("ASGARD_K6_LANE", line, f"{mount} 마운트가 프로젝트 레인에 걸려 있지 않다")
        self.assertIn(f".asgard/{k6.LANE_DIR}", body, "레인 기본값이 프로젝트의 .asgard 를 안 가리킨다")


class TestDockerHome(unittest.TestCase):
    """`docker/asgard-k6/` — 이미지와 스택의 집 (docker/asgard-project-memory와 나란히)."""

    def setUp(self):
        home = k6.docker_dir()
        assert home is not None, "저장소 체크아웃에는 docker/asgard-k6/ 가 있어야 한다"
        self.home = home

    def test_the_home_holds_the_docker_artifacts(self):
        for relative in ("Dockerfile", "docker-compose.yml", "README.md"):
            self.assertTrue((self.home / relative).is_file(), f"docker/{k6.PROJECT}/{relative} 가 없다")

    def test_the_image_bakes_the_canonical_kit(self):
        """이미지가 다른 키트를 구우면 '같은 시나리오를 돈다'는 전제가 조용히 깨진다."""
        dockerfile = (self.home / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(f"COPY src/asgard/assets/k6_kit {k6.CONTAINER_MOUNT}", dockerfile)

    def test_the_image_is_a_k6_entrypoint(self):
        """러너는 이미지 뒤에 `run <script>`만 붙인다 — 진입점이 k6 여야 그 조립이 맞는다."""
        dockerfile = (self.home / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('ENTRYPOINT ["k6"]', dockerfile)

    def test_the_summary_mountpoint_is_writable_in_the_image(self):
        """이미지는 비루트로 돈다 — 마운트 없이 단독으로 돌 때 요약을 못 쓰면 실행이 버려진다."""
        dockerfile = (self.home / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(f"chmod 0777 {k6.CONTAINER_MOUNT}/out", dockerfile)

    def test_owned_image_tags_carry_the_lane_name(self):
        from asgard import __version__

        self.assertEqual(k6.owned_image_tags(), [f"{k6.PROJECT}:{__version__}", f"{k6.PROJECT}:local"])

    def test_a_pinned_image_wins_over_discovery(self):
        previous = os.environ.get("ASGARD_K6_IMAGE")
        os.environ["ASGARD_K6_IMAGE"] = "example/k6:pinned"
        try:
            # engine_binary를 줘도 환경 고정이 이긴다 — 엔진을 부르지 않는다는 뜻이기도 하다.
            self.assertEqual(k6.resolve_image("/nonexistent/docker"), "example/k6:pinned")
        finally:
            if previous is None:
                os.environ.pop("ASGARD_K6_IMAGE", None)
            else:
                os.environ["ASGARD_K6_IMAGE"] = previous

    def test_without_an_engine_the_public_image_is_the_answer(self):
        previous = os.environ.pop("ASGARD_K6_IMAGE", None)
        try:
            self.assertEqual(k6.resolve_image(""), k6.DEFAULT_IMAGE)
        finally:
            if previous is not None:
                os.environ["ASGARD_K6_IMAGE"] = previous


class TestScenarioResolution(unittest.TestCase):
    def test_builtins_are_present(self):
        names = set(k6.builtin_scenarios())
        self.assertLessEqual({"selftest", "http-smoke", "recall", "saturate", "search"}, names)

    def test_project_scenarios_win_on_a_name_clash(self):
        with tempfile.TemporaryDirectory() as root:
            lane = Path(root, ".asgard", "k6", "scenarios")
            lane.mkdir(parents=True)
            (lane / "recall.js").write_text("// mine\n", encoding="utf-8")
            found = k6.scenarios(root)
            self.assertEqual(found["recall"].origin, "project")
            self.assertEqual(found["selftest"].origin, "builtin")

    def test_scenarios_left_directly_under_the_lane_still_resolve(self):
        """레인 밑이 키트·기록의 자리가 됐어도 예전에 거기 둔 시나리오는 계속 돌아야 한다."""
        with tempfile.TemporaryDirectory() as root:
            lane = Path(root, ".asgard", "k6")
            lane.mkdir(parents=True)
            (lane / "legacy.js").write_text("// 예전 자리\n", encoding="utf-8")
            self.assertEqual(k6.scenarios(root)["legacy"].origin, "project")

    def test_the_explicit_scenarios_dir_wins_over_the_legacy_spot(self):
        with tempfile.TemporaryDirectory() as root:
            lane = Path(root, ".asgard", "k6")
            (lane / "scenarios").mkdir(parents=True)
            (lane / "both.js").write_text("// 예전 자리\n", encoding="utf-8")
            (lane / "scenarios" / "both.js").write_text("// 정본\n", encoding="utf-8")
            self.assertEqual(k6.scenarios(root)["both"].path, lane / "scenarios" / "both.js")

    def test_a_direct_path_is_its_own_scenario(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "custom.js")
            path.write_text("// one-off\n", encoding="utf-8")
            scenario = k6.find_scenario(str(path))
            assert scenario is not None, "직접 경로는 그 자체로 시나리오여야 한다"
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

    def test_container_mounts_the_given_kit_read_only(self):
        """`/asgard`의 원본은 부르는 쪽이 정한다 — 설치 위치가 아니라 프로젝트 안의 사본이다."""
        argv = k6.build_argv(self.docker, self.scenario, "/tmp/run", kit="/proj/.asgard/k6/kit")
        self.assertIn(f"/proj/.asgard/k6/kit:{k6.CONTAINER_MOUNT}:ro", argv)
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
        """프로젝트 시나리오는 `/asgard/project`로 들어와야 `../lib/asgard.js`가 맞는다."""
        with tempfile.TemporaryDirectory() as root:
            lane = Path(root, ".asgard", "k6", "scenarios")
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
        """모르는 모양을 0으로 채우면 '요청 0건, 지연 0ms' 라는 완벽한 보고서가 나온다."""
        for payload in ({}, {"schema": "something-else"}, {"schema": None}):
            with self.subTest(payload=payload), self.assertRaises(k6.SummaryError):
                k6.parse_summary(payload)
        with self.assertRaises(k6.SummaryError):
            k6.parse_summary([])  # ty: ignore[invalid-argument-type]  — 계약 밖 타입도 거절하는지 본다

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
        """임계값이 깨졌는데 0으로 끝나면 CI가 빨간 것을 초록으로 통과시킨다."""
        lying = k6.parse_summary(
            _summary(thresholds=[{"metric": "http_req_duration", "expression": "p(95)<5", "ok": False}]),
            exit_code=0,
        )
        self.assertFalse(lying.exit_agrees)

        silent = k6.parse_summary(_summary(), exit_code=k6.THRESHOLD_EXIT)
        self.assertFalse(silent.exit_agrees, "멀쩡한 실행이 임계값 코드로 끝나는 것도 어긋남이다")

    def test_no_thresholds_means_nothing_to_break(self):
        """임계값이 없으면 깨질 것이 없다 — 그러나 그것은 **통과가 아니다**.

        `all([])` 은 참이므로 `thresholds_ok` 는 여전히 참이고, 그 자체는 맞다. 갈라야 하는 것은
        판정에 통과한 실행과 판정할 것이 없던 실행이다. 여태 둘이 `ok` 와 종료 코드에서 같아
        보여서, 요청이 100% 실패한 실행이 `verdict pass` · exit 0 으로 나갔다."""
        report = k6.parse_summary(_summary(thresholds=[]), exit_code=0)
        self.assertTrue(report.thresholds_ok)
        self.assertFalse(report.judged)
        self.assertFalse(report.ok)

    def test_a_run_with_thresholds_met_is_a_pass(self):
        report = k6.parse_summary(_summary(), exit_code=0)
        self.assertTrue(report.judged)
        self.assertTrue(report.ok)

    def test_unjudged_run_exits_apart_from_pass_and_fail(self):
        """미판정은 통과(0)와도 미달(1)과도 다른 종료 코드로 나간다 — CI 가 셋을 가를 수 있게."""
        from asgard.commands import k6 as surface

        self.assertEqual(surface._exit_for(k6.parse_summary(_summary(thresholds=[]), exit_code=0)), k6.UNJUDGED_EXIT)
        self.assertEqual(surface._exit_for(k6.parse_summary(_summary(), exit_code=0)), 0)
        self.assertEqual(
            surface._exit_for(
                k6.parse_summary(
                    _summary(thresholds=[{"metric": "m", "expression": "e", "ok": False}]), exit_code=k6.THRESHOLD_EXIT
                )
            ),
            1,
        )


class TestRunRecord(unittest.TestCase):
    def test_report_is_written_and_reads_back(self):
        report = k6.parse_summary(_summary(), exit_code=0, runner="docker", k6_version="k6 v2.1.0")
        with tempfile.TemporaryDirectory() as root:
            path = k6_gate.record_run(root, report, "20260728T000000-selftest")
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
            docker = k6.resolve_runner("docker")
            assert docker is not None, "docker 가 PATH 에 있는데 러너를 못 찾았다"
            self.assertEqual(docker.kind, "docker")
        if shutil.which("k6"):
            runner = k6.resolve_runner("native")
            assert runner is not None, "k6 가 PATH 에 있는데 러너를 못 찾았다"
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
    """`--env BANK=x`는 시나리오가 읽는 이름(ASGARD_K6_BANK)으로 올라가야 쓸모가 있다."""

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


def _record(root, stamp: str, **overrides) -> k6_gate.RunRecord:
    """기록 하나를 만들어 두고 그 자리를 돌려준다 — 게이트 시험은 전부 파일에서 시작한다."""
    payload = _summary(**overrides)
    payload.setdefault("runner", "native k6")
    payload.setdefault("k6_version", "k6 vTest")
    payload.setdefault("exit_code", 0)
    payload.setdefault("judged", bool(payload.get("thresholds")))
    path = Path(root, ".asgard", "k6", "runs", stamp)
    path.mkdir(parents=True, exist_ok=True)
    (path / "report.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return k6_gate.RunRecord(stamp, payload, path / "report.json")


class TestGateTolerance(unittest.TestCase):
    """허용 오차는 명시적이어야 한다 — 그리고 저장소가 덮어쓸 수 있어야 한다."""

    def _write(self, root, body: str) -> None:
        Path(root, "pyproject.toml").write_text(body, encoding="utf-8")

    def test_defaults_stand_when_the_repo_says_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(k6_gate.gate_tolerance(root), k6_gate.Tolerance())

    def test_the_repo_can_widen_or_narrow_every_axis(self):
        with tempfile.TemporaryDirectory() as root:
            self._write(root, "[tool.asgard.k6-gate]\np95_pct = 5.0\nfailed_rate_pp = 0.1\nrate_per_s_pct = 2.0\n")
            self.assertEqual(k6_gate.gate_tolerance(root), k6_gate.Tolerance(5.0, 0.1, 2.0))

    def test_a_partial_table_leaves_the_other_axes_at_their_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            self._write(root, "[tool.asgard.k6-gate]\np95_pct = 8\n")
            self.assertEqual(
                k6_gate.gate_tolerance(root),
                k6_gate.Tolerance(8.0, k6_gate.DEFAULT_FAILED_RATE_PP, k6_gate.DEFAULT_RATE_PER_S_PCT),
            )

    def test_unusable_values_fall_back_instead_of_reading_as_zero(self):
        """0 으로 읽으면 오타 하나가 오차를 없애서, 아무것도 안 바뀐 실행이 회귀로 나온다."""
        with tempfile.TemporaryDirectory() as root:
            self._write(root, '[tool.asgard.k6-gate]\np95_pct = "loose"\nfailed_rate_pp = -3\nrate_per_s_pct = true\n')
            self.assertEqual(k6_gate.gate_tolerance(root), k6_gate.Tolerance())

    def test_a_broken_pyproject_does_not_take_the_gate_down(self):
        with tempfile.TemporaryDirectory() as root:
            self._write(root, "[tool.asgard.k6-gate\np95 = ")
            self.assertEqual(k6_gate.gate_tolerance(root), k6_gate.Tolerance())


class TestBaselineRecord(unittest.TestCase):
    """기준선은 앞으로의 실행을 통과시키는 표준이라, 대조군보다 요구가 높다."""

    def test_the_whole_run_is_engraved_not_just_the_numbers(self):
        """`runs/` 는 보존 정책에 따라 지워진다 — 그때 기준선만 남아도 근거를 물을 수 있어야 한다."""
        with tempfile.TemporaryDirectory() as root:
            record = _record(root, "20260803T000000-selftest")
            baseline = k6_gate.write_baseline(root, record)
            shutil.rmtree(Path(root, ".asgard", "k6", "runs"))
            again = k6_gate.read_baseline(root)
            assert again is not None, "기록을 지웠다고 기준선까지 사라지면 안 된다"
            self.assertEqual(again.stamp, record.stamp)
            self.assertEqual(again.run["target"], record.payload["target"])
            self.assertEqual(again.run["k6_version"], "k6 vTest")
            self.assertEqual(again.set_at, baseline.set_at)

    def test_an_unjudged_run_is_refused_as_the_standard(self):
        """임계값이 없던 실행을 표준으로 삼으면 똑같이 망가진 실행이 영원히 통과한다."""
        self.assertEqual(k6_gate.baseline_blocker(_summary(thresholds=[])), "unjudged")

    def test_a_run_whose_exit_code_disagrees_is_refused(self):
        breached = _summary(thresholds=[{"metric": "m", "expression": "e", "ok": False}])
        self.assertEqual(k6_gate.baseline_blocker(breached), "exit-disagrees")  # exit 0 인데 임계값이 깨졌다

    def test_a_run_that_measured_nothing_is_refused(self):
        self.assertEqual(k6_gate.baseline_blocker(_summary(requests={"count": 0})), "empty")

    def test_a_foreign_shape_is_refused(self):
        self.assertEqual(k6_gate.baseline_blocker({"schema": "something-else"}), "unreadable")

    def test_a_judged_and_agreeing_run_is_accepted(self):
        self.assertEqual(k6_gate.baseline_blocker(_summary()), "")

    def test_absent_and_broken_are_different_answers(self):
        """둘을 None 하나로 합치면 손상된 기준선이 '아직 안 세웠다'로 읽힌다."""
        with tempfile.TemporaryDirectory() as root:
            Path(root, ".asgard", "k6").mkdir(parents=True)
            self.assertIsNone(k6_gate.read_baseline(root))
            k6_gate.baseline_path(root).write_text('{"schema": "nope"}', encoding="utf-8")
            with self.assertRaises(k6.SummaryError):
                k6_gate.read_baseline(root)

    def test_clearing_says_whether_there_was_anything_to_clear(self):
        with tempfile.TemporaryDirectory() as root:
            record = _record(root, "20260803T000000-selftest")
            k6_gate.write_baseline(root, record)
            self.assertTrue(k6_gate.clear_baseline(root))
            self.assertFalse(k6_gate.clear_baseline(root))
            self.assertIsNone(k6_gate.read_baseline(root))

    def test_the_newest_run_is_the_default_and_a_stamp_overrides_it(self):
        with tempfile.TemporaryDirectory() as root:
            _record(root, "20260803T000000-a")
            _record(root, "20260803T000100-b")
            newest = k6_gate.find_recorded_run(root)
            assert newest is not None, "기록이 둘인데 최근 것을 못 찾았다"
            self.assertEqual(newest.stamp, "20260803T000100-b")
            named = k6_gate.find_recorded_run(root, "20260803T000000-a")
            assert named is not None, "스탬프로 지목한 기록을 못 찾았다"
            self.assertEqual(named.stamp, "20260803T000000-a")
            self.assertIsNone(k6_gate.find_recorded_run(root, "no-such-stamp"))

    def test_a_broken_record_does_not_hide_the_rest_of_the_history(self):
        """기록 하나가 깨졌다고 이력 전체를 못 보면, 사람이 하는 일은 runs/ 를 통째로 지우는 것이다."""
        with tempfile.TemporaryDirectory() as root:
            _record(root, "20260803T000000-a")
            broken = Path(root, ".asgard", "k6", "runs", "20260803T000100-b")
            broken.mkdir(parents=True)
            (broken / "report.json").write_text("{ not json", encoding="utf-8")
            found = k6_gate.find_recorded_run(root)
            assert found is not None, "깨진 기록 하나가 멀쩡한 기록까지 가렸다"
            self.assertEqual(found.stamp, "20260803T000000-a")

    def test_the_scenario_filter_reads_the_summary_not_the_stamp(self):
        """직접 경로로 돌린 실행은 스탬프 접미사가 파일 이름이라 시나리오 이름과 다를 수 있다."""
        with tempfile.TemporaryDirectory() as root:
            _record(root, "20260803T000000-mine", scenario="http-smoke")
            _record(root, "20260803T000100-http-smoke", scenario="recall")
            found = k6_gate.find_recorded_run(root, scenario="http-smoke")
            assert found is not None, "요약 본문의 시나리오로 못 찾았다"
            self.assertEqual(found.stamp, "20260803T000000-mine")
            self.assertIsNone(k6_gate.find_recorded_run(root, scenario="no-such-scenario"))


class TestGateComparability(unittest.TestCase):
    """**비교 가능성이 판정보다 먼저다.** 다른 조건에서 나온 수치를 견주면 그 판정은 거짓이다."""

    def _pair(self, root, **current_overrides):
        base = _record(root, "20260803T000000-base")
        current = _record(root, "20260803T000100-now", **current_overrides)
        baseline = k6_gate.write_baseline(root, base)
        return k6_gate.compare_to_baseline(baseline, current, k6_gate.Tolerance())

    def test_same_conditions_are_judged(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self._pair(root).verdict, k6_gate.VERDICT_PASS)

    def test_a_different_condition_is_never_called_a_regression(self):
        """느려진 수치라도 조건이 다르면 회귀가 아니다 — 거짓 회귀 한 번이면 게이트는 꺼진다."""
        slower = {"latency_ms": {"p95": 900.0}, "requests": {"count": 40, "failed_rate": 0.9, "rate_per_s": 1.0}}
        for axis, override in (
            ("scenario", {"scenario": "recall"}),
            ("runner", {"runner": "docker (grafana/k6:latest)"}),
            ("k6_version", {"k6_version": "k6 v9.9.9"}),
            ("target", {"target": "http://127.0.0.1:9999"}),
            ("vus_max", {"vus_max": 40}),
        ):
            with tempfile.TemporaryDirectory() as root, self.subTest(axis=axis):
                verdict = self._pair(root, **{**slower, **override})
                self.assertEqual(verdict.verdict, k6_gate.VERDICT_UNDECIDABLE)
                self.assertEqual(verdict.reason, "not-comparable")
                self.assertEqual([a.name for a in verdict.mismatched], [axis])
                self.assertFalse(verdict.blocked, "견줄 수 없는데 막았다")
                self.assertEqual(verdict.deltas, (), "견줄 수 없는데 수치를 견줬다")

    def test_iterations_are_not_an_axis(self):
        """기간 기반 시나리오에서 반복 수는 설정이 아니라 결과다 — 같기를 요구하면 그 시나리오는
        영영 판정을 못 받고, 잡으려던 처리량 악화가 '견줄 수 없음'으로 둔갑한다."""
        with tempfile.TemporaryDirectory() as root:
            verdict = self._pair(root, iterations=4000)
            self.assertEqual(verdict.verdict, k6_gate.VERDICT_PASS)

    def test_a_run_that_measured_nothing_is_not_a_regression_either(self):
        """기준선 p95 0ms 는 허용치 0ms 가 된다 — 그러면 정상 실행이 전부 회귀로 나온다."""
        with tempfile.TemporaryDirectory() as root:
            verdict = self._pair(root, requests={"count": 0, "failed_rate": 0.0, "rate_per_s": 0.0})
            self.assertEqual(verdict.reason, "no-measurement")
            self.assertFalse(verdict.blocked)


class TestGateVerdict(unittest.TestCase):
    """무엇을 회귀라 부르는가 — 그리고 부등호가 축마다 다르다는 것."""

    def _verdict(self, root, tolerance=None, **current_overrides):
        base = _record(root, "20260803T000000-base")
        current = _record(root, "20260803T000100-now", **current_overrides)
        return k6_gate.compare_to_baseline(
            k6_gate.write_baseline(root, base), current, tolerance or k6_gate.Tolerance()
        )

    def _latency(self, p95: float) -> dict:
        return {"latency_ms": {"avg": p95, "med": p95, "p95": p95, "p99": p95, "max": p95}}

    def test_latency_inside_the_tolerance_passes(self):
        with tempfile.TemporaryDirectory() as root:
            # 기준선 p95 는 84.0 이고 기본 오차는 20% 라 100.8 까지 봐준다.
            self.assertEqual(self._verdict(root, **self._latency(100.0)).verdict, k6_gate.VERDICT_PASS)

    def test_latency_past_the_tolerance_blocks(self):
        with tempfile.TemporaryDirectory() as root:
            verdict = self._verdict(root, **self._latency(101.0))
            self.assertEqual(verdict.verdict, k6_gate.VERDICT_REGRESSED)
            self.assertTrue(verdict.blocked)
            self.assertEqual([d.metric for d in verdict.regressions], ["p95"])

    def test_throughput_is_judged_the_other_way_round(self):
        """처리량은 **높을수록 좋다** — 부등호를 안 뒤집으면 처리량 회귀가 전부 통과한다."""
        with tempfile.TemporaryDirectory() as root:
            faster = {"requests": {"count": 40, "failed_rate": 0.0, "rate_per_s": 999.0}}
            self.assertEqual(self._verdict(root, **faster).verdict, k6_gate.VERDICT_PASS)
        with tempfile.TemporaryDirectory() as root:
            # 기준선 33.3 req/s 에 기본 오차 10% — 29.97 아래로 떨어지면 회귀다.
            slower = {"requests": {"count": 40, "failed_rate": 0.0, "rate_per_s": 29.0}}
            verdict = self._verdict(root, **slower)
            self.assertEqual([d.metric for d in verdict.regressions], ["rate_per_s"])

    def test_the_failure_axis_is_measured_in_percentage_points(self):
        """건강한 기준선의 failed_rate 는 0.0 이라, 비율 오차를 걸면 실패 한 건이 곧 회귀가 된다."""
        with tempfile.TemporaryDirectory() as root:
            clean = {"requests": {"count": 400, "failed": 0, "failed_rate": 0.0, "rate_per_s": 33.3}}
            base = _record(root, "20260803T000000-base", **clean)
            baseline = k6_gate.write_baseline(root, base)
            for rate, expected in ((0.009, k6_gate.VERDICT_PASS), (0.011, k6_gate.VERDICT_REGRESSED)):
                current = _record(
                    root,
                    f"20260803T0001-{int(rate * 1000)}",
                    requests={"count": 400, "failed_rate": rate, "rate_per_s": 33.3},
                )
                with self.subTest(rate=rate):
                    verdict = k6_gate.compare_to_baseline(baseline, current, k6_gate.Tolerance())
                    self.assertEqual(verdict.verdict, expected)

    def test_the_tolerance_actually_drives_the_verdict(self):
        """오차가 화면 장식이 아니라 판정의 재료인지 — 같은 두 실행을 오차만 바꿔 견준다."""
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                self._verdict(root, k6_gate.Tolerance(p95_pct=200.0), **self._latency(200.0)).verdict,
                k6_gate.VERDICT_PASS,
            )
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                self._verdict(root, k6_gate.Tolerance(p95_pct=1.0), **self._latency(90.0)).verdict,
                k6_gate.VERDICT_REGRESSED,
            )

    def test_an_unjudged_current_run_is_still_compared(self):
        """대조군은 표준이 아니라 판정 대상이다 — 임계값이 사라진 시나리오라도 악화는 잡아야 한다."""
        with tempfile.TemporaryDirectory() as root:
            broken = {"thresholds": [], "requests": {"count": 40, "failed_rate": 1.0, "rate_per_s": 33.3}}
            verdict = self._verdict(root, **broken)
            self.assertEqual(verdict.verdict, k6_gate.VERDICT_REGRESSED)
            self.assertIn("failed_rate", [d.metric for d in verdict.regressions])

    def test_the_json_shape_carries_the_verdict_and_the_reason(self):
        with tempfile.TemporaryDirectory() as root:
            payload = self._verdict(root).as_dict()
            self.assertEqual(payload["schema"], k6_gate.GATE_SCHEMA)
            self.assertEqual(payload["verdict"], k6_gate.VERDICT_PASS)
            self.assertEqual([a["name"] for a in payload["axes"]], list(k6_gate.GATE_AXES))
            self.assertEqual([d["metric"] for d in payload["deltas"]], ["p95", "failed_rate", "rate_per_s"])
            self.assertEqual(payload["tolerance"], k6_gate.Tolerance().as_dict())

    def test_undecidable_is_a_different_word_from_pass(self):
        """종료 코드는 둘 다 0 이다 — 그래서 낱말이 갈라져 있지 않으면 아무도 못 가른다."""
        self.assertNotEqual(k6_gate.VERDICT_UNDECIDABLE, k6_gate.VERDICT_PASS)


class TestGateSurface(unittest.TestCase):
    """사람이 보는 자리 — 종료 코드가 계약이다."""

    def _cmd(self):
        from asgard.commands import k6 as surface

        return surface

    def _run(self, root, fn, *args):
        from unittest import mock

        surface = self._cmd()
        with mock.patch.object(surface, "_root", return_value=str(root)):
            return getattr(surface, fn)(*args)

    def test_no_baseline_does_not_block(self):
        """표적이 없는 프로젝트에서 이 게이트가 도는 것은 소음이다 — 말하되 막지는 않는다."""
        with tempfile.TemporaryDirectory() as root:
            Path(root, ".asgard", "k6").mkdir(parents=True)
            self.assertEqual(self._run(root, "run_k6_gate", True), 0)

    def test_no_run_does_not_block(self):
        with tempfile.TemporaryDirectory() as root:
            record = _record(root, "20260803T000000-base")
            k6_gate.write_baseline(root, record)
            shutil.rmtree(Path(root, ".asgard", "k6", "runs"))
            self.assertEqual(self._run(root, "run_k6_gate", True), 0)

    def test_a_broken_baseline_does_not_block_either(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, ".asgard", "k6").mkdir(parents=True)
            k6_gate.baseline_path(root).write_text("{ not json", encoding="utf-8")
            self.assertEqual(self._run(root, "run_k6_gate", True), 0)

    def test_a_regression_blocks_and_a_pass_does_not(self):
        with tempfile.TemporaryDirectory() as root:
            k6_gate.write_baseline(root, _record(root, "20260803T000000-base"))
            _record(root, "20260803T000100-ok")
            self.assertEqual(self._run(root, "run_k6_gate", True), 0)
            _record(root, "20260803T000200-slow", latency_ms={"p95": 5000.0})
            self.assertEqual(self._run(root, "run_k6_gate", True), 1)

    def test_not_comparable_does_not_block(self):
        """이 갈래가 1 을 돌려주면 게이트가 거짓말을 하는 것이다."""
        with tempfile.TemporaryDirectory() as root:
            k6_gate.write_baseline(root, _record(root, "20260803T000000-base"))
            _record(root, "20260803T000100-elsewhere", target="http://elsewhere:8080", latency_ms={"p95": 5000.0})
            self.assertEqual(self._run(root, "run_k6_gate", True), 0)

    def test_setting_an_unjudged_run_as_the_baseline_uses_the_lanes_own_exit_code(self):
        with tempfile.TemporaryDirectory() as root:
            _record(root, "20260803T000000-unjudged", thresholds=[])
            self.assertEqual(self._run(root, "run_k6_baseline_set", "", True), k6.UNJUDGED_EXIT)
            self.assertIsNone(k6_gate.read_baseline(root), "거절한 실행이 기준선 파일을 남겼다")

    def test_a_named_stamp_that_does_not_exist_is_an_argument_error(self):
        with tempfile.TemporaryDirectory() as root:
            _record(root, "20260803T000000-base")
            self.assertEqual(self._run(root, "run_k6_baseline_set", "no-such-stamp", True), 2)

    def test_setting_with_no_runs_at_all_says_so(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, ".asgard", "k6").mkdir(parents=True)
            self.assertEqual(self._run(root, "run_k6_baseline_set", "", True), 1)

    def test_show_and_clear_round_trip(self):
        with tempfile.TemporaryDirectory() as root:
            _record(root, "20260803T000000-base")
            self.assertEqual(self._run(root, "run_k6_baseline_set", "", True), 0)
            self.assertEqual(self._run(root, "run_k6_baseline_show", True), 0)
            self.assertEqual(self._run(root, "run_k6_baseline_clear", True), 0)
            # 없던 것을 치우는 것은 실패가 아니다 — 바라던 상태가 이미 참이다.
            self.assertEqual(self._run(root, "run_k6_baseline_clear", True), 0)
            self.assertEqual(self._run(root, "run_k6_baseline_show", True), 1)

    def test_the_gate_never_runs_load(self):
        """게이트가 몇 분짜리가 되면 아무도 안 건다 — 이 레인이 이미지 자동 빌드를 거절한 것과
        같은 이유다. 부하를 도는 자리를 통째로 막아 두고 판정이 나오는지 본다."""
        from unittest import mock

        with tempfile.TemporaryDirectory() as root:
            k6_gate.write_baseline(root, _record(root, "20260803T000000-base"))
            _record(root, "20260803T000100-now")
            boom = AssertionError("게이트가 부하를 돌렸다")
            with (
                mock.patch.object(k6, "run_scenario", side_effect=boom),
                mock.patch.object(k6, "resolve_runner", side_effect=boom),
                mock.patch.object(k6, "runner_version", side_effect=boom),
            ):
                self.assertEqual(self._run(root, "run_k6_gate", True), 0)

    def test_every_gate_surface_is_reachable_from_the_cli(self):
        """표면이 배선 안 된 채 구현만 있는 것을 막는다 — `asgard k6 <이름>` 이 실제로 있는가."""
        from asgard import cli

        names = {command.name for command in cli.k6_app.registered_commands}
        self.assertIn("gate", names)
        groups = {group.name for group in cli.k6_app.registered_groups}
        self.assertIn("baseline", groups)
        sub = {command.name for command in cli.k6_baseline_app.registered_commands}
        self.assertLessEqual({"set", "show", "clear"}, sub)


@unittest.skipUnless(os.environ.get("ASGARD_K6_DOCKER") == "1", "실엔진 검증 — ASGARD_K6_DOCKER=1 일 때만")
class TestHarnessIntegrityLive(unittest.TestCase):
    """레인이 자기 자신에게 거는 검사 — 엔진이 있을 때만 돈다."""

    def test_selftest_is_green(self):
        """실행도 CLI와 같은 자리에서 — 마운트되는 것은 전부 프로젝트 레인 아래다."""
        root = k6.project_root()
        kit = k6.prepare_lane(root)
        out = k6.lane_dir(root) / "selftest-pytest"
        try:
            result = k6_selftest.selftest(out_dir=out, kit=kit, iterations=20, vus=4)
        finally:
            shutil.rmtree(out, ignore_errors=True)
        self.assertEqual(result.error, "")
        red = [c.name for c in result.checks if not c.ok]
        self.assertFalse(red, f"정합성 검사 실패: {red}")


class TestDeadDaemonIsNotReady(unittest.TestCase):
    """도커 데몬이 죽었을 때 하네스가 무엇이라고 답하는가.

    26-08-21 실측: `runner_version` 이 종료 코드를 안 보고 실패 프로브의 stderr 첫 줄을
    판 문자열로 돌려줬다. `Cannot connect to the Docker daemon...` 이 비어 있지 않다는
    이유로 `k6 doctor` 가 `ready pass` 와 종료 코드 0 을 냈다. CI 가 그 명령을 문지기로
    쓰면 부하를 한 판도 못 도는 기계에서 초록이 난다."""

    @staticmethod
    def _dead(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?",
        )

    def test_a_failed_probe_is_not_a_version(self):
        runner = k6.Runner("docker", "/usr/bin/docker", "grafana/k6:latest")
        with mock.patch.object(k6.subprocess, "run", side_effect=self._dead):
            self.assertEqual(k6.runner_version(runner), "")

    def test_a_succeeding_probe_still_reads_stderr(self):
        """판 번호를 stderr 로 내는 k6 도 있다 — 종료 코드가 0 이면 그대로 읽는다."""
        runner = k6.Runner("native", "/usr/local/bin/k6")

        def ok(*_args, **_kwargs):
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="k6 v0.49.0\n")

        with mock.patch.object(k6.subprocess, "run", side_effect=ok):
            self.assertEqual(k6.runner_version(runner), "k6 v0.49.0")

    def test_a_dead_engine_falls_through_to_native(self):
        """옆에 멀쩡한 k6 가 있는데 죽은 도커를 고르면 부하는 한 판도 안 돈다."""
        with (
            mock.patch.object(k6.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"),
            mock.patch.object(k6, "engine_responds", return_value=False),
            mock.patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("ASGARD_K6_RUNNER", None)
            runner = k6.resolve_runner()
        assert runner is not None
        self.assertEqual(runner.kind, "native")

    def test_a_live_engine_is_still_preferred(self):
        with (
            mock.patch.object(k6.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"),
            mock.patch.object(k6, "engine_responds", return_value=True),
            mock.patch.object(k6, "resolve_image", return_value="grafana/k6:latest"),
        ):
            os.environ.pop("ASGARD_K6_RUNNER", None)
            runner = k6.resolve_runner()
        assert runner is not None
        self.assertEqual(runner.kind, "docker")

    def test_an_explicit_preference_is_not_second_guessed(self):
        """`ASGARD_K6_RUNNER=docker` 는 '이걸로 돌려라'이지 '되는 걸로 골라라'가 아니다."""
        with (
            mock.patch.object(k6.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"),
            mock.patch.object(k6, "engine_responds", return_value=False),
            mock.patch.object(k6, "resolve_image", return_value="grafana/k6:latest"),
        ):
            runner = k6.resolve_runner("docker")
        assert runner is not None
        self.assertEqual(runner.kind, "docker")

    def test_engine_responds_reads_the_exit_code(self):
        with mock.patch.object(k6.subprocess, "run", side_effect=self._dead):
            self.assertFalse(k6.engine_responds("/usr/bin/docker"))

        def alive(*_args, **_kwargs):
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="27.3.1\n", stderr="")

        with mock.patch.object(k6.subprocess, "run", side_effect=alive):
            self.assertTrue(k6.engine_responds("/usr/bin/docker"))

    def test_doctor_refuses_to_call_a_dead_engine_ready(self):
        from asgard.commands import k6 as k6_cmd

        runner = k6.Runner("docker", "/usr/bin/docker", "grafana/k6:latest")
        buf = io.StringIO()
        with (
            mock.patch.object(k6, "resolve_runner", return_value=runner),
            mock.patch.object(k6.subprocess, "run", side_effect=self._dead),
            redirect_stdout(buf),
        ):
            code = k6_cmd.run_k6_doctor(json_=True)
        state = json.loads(buf.getvalue())
        self.assertFalse(state["ready"], "데몬이 죽었는데 ready 다")
        self.assertEqual(state["k6_version"], "", "오류 문장이 판 번호 자리에 실렸다")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
