#!/usr/bin/env python3
"""베이스라인 레인 — 검사 명령 자동 감지, 병렬 실행, 파이프라인 검증."""

import contextlib
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from trinity_base import (
    TrinityBase,
    jout,
)


class TestBaseline(TrinityBase):
    """하네스 소유 베이스라인 체크: 증거 '품질'의 결정론화 (verifier 재량 커맨드 불신)."""

    def last_event(self):
        lines = open(os.path.join(self.root, ".asgard", "quest", "q1.jsonl")).read().splitlines()
        return json.loads(lines[-1])

    def test_red_blocks_close_routes_repair_and_gate(self):
        self.policy(baseline_checks=["false"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()  # verifier는 PASS + echo 급 증거 — 하네스 체크가 red를 기록한다
        st = jout(self.qlog("state"))
        self.assertEqual(st["baseline_state"], "red")
        self.assertEqual(jout(self.qlog("next"))["next_role"], "WORKER_RETRY")
        self.assertEqual(self.qlog("close").returncode, 1)
        gp = jout(self.gate())
        self.assertEqual(gp.get("decision"), "block")
        self.assertIn("baseline", gp.get("reason", ""))

    def test_green_baseline_done_and_close(self):
        self.policy(baseline_checks=["python3 -m compileall -q ."])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        st = jout(self.qlog("state"))
        self.assertEqual(st["baseline_state"], "green")
        self.assertEqual(jout(self.qlog("next"))["next_role"], "DONE")
        self.assertEqual(self.qlog("close").returncode, 0)
        self.assertNotEqual(jout(self.gate()).get("decision"), "block")

    def test_no_checks_waived(self):
        self.open_quest()  # 체크 미설정 + 자동 감지 대상 없음 → 요건 면제 (구 로그 하위호환)
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.assertEqual(jout(self.qlog("state"))["baseline_state"], "none")
        self.assertEqual(jout(self.qlog("next"))["next_role"], "DONE")

    def test_same_hash_reuses_cached_result(self):
        self.policy(baseline_checks=["python3 -m compileall -q ."])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.verify()  # 동일 트리 재검증 — 체크 재실행 없이 캐시 재사용
        self.assertTrue(self.last_event()["baseline"].get("cached"))

    def test_the_contract_cache_is_reused_only_when_it_holds_every_declared_command(self):
        """같은 트리라도 기록이 안 담은 명령은 캐시가 대신 답할 수 없다.

        재사용은 같은 스위트를 한 트리에 두 번 돌리지 않으려는 절약이다(26-08-13: 판정 130건에서
        판정자와 하네스가 같은 pytest 를 각각 돌렸다). 그런데 조건이 diff_hash 하나면 기준 수정은
        트리를 안 바꾸므로 옛 명령의 결과가 새 계약의 답으로 돌아온다 — `unmet_contracts` 는 새
        명령을 기록에서 못 찾아 영영 미충족이고 close 가 안 닫힌다."""
        green = "python -c 'import sys; sys.exit(0)'"
        self.open_quest("--criteria", "the renamed file | verify: python -c 'import sys; sys.exit(7)'")
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.assertTrue(jout(self.qlog("state"))["contracts_unmet"])

        amended = self.qlog(
            "amend-criteria",
            "q1",
            "--criteria",
            "correct target | verify: %s" % green,
            "--reason",
            "the file the contract named was renamed mid-quest",
        )
        self.assertEqual(amended.returncode, 0, amended.stderr)
        self.verify()  # 트리는 그대로다 — 그래도 수정된 명령은 직접 돌아야 한다
        rows = self.last_event()["criteria_checks"]
        self.assertEqual([r["cmd"] for r in rows], [green])
        self.assertEqual([r["exit_code"] for r in rows], [0])
        self.assertFalse(any(r.get("cached") for r in rows), "수정된 계약이 옛 기록으로 답했다")
        self.assertEqual(jout(self.qlog("state"))["contracts_unmet"], [])
        self.assertEqual(self.qlog("close", "q1").returncode, 0)

    def test_an_unchanged_contract_on_an_unchanged_tree_still_reuses_its_record(self):
        """절약 자체는 그대로다 — 조건을 좁히면서 재사용을 통째로 껐는지 여기서 본다."""
        self.open_quest("--criteria", "stays green | verify: python -c 'import sys; sys.exit(0)'")
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.verify()
        self.assertTrue(all(r.get("cached") for r in self.last_event()["criteria_checks"]))

    def test_timeout_is_skip_not_red(self):
        self.policy(baseline_checks=["sleep 3"], baseline_timeout=1)
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        self.assertEqual(jout(self.qlog("state"))["baseline_state"], "none")  # 인질 방지 fail-open

    def test_a_contract_timeout_memo_is_keyed_to_its_budget_and_tree(self):
        """무효화 축 없는 메모는 캐시가 아니라 낙인이다.

        26-08-12: 경합으로 한 번 늦은 계약이 세 턴 연속 미충족으로 굳었다 — 상한을 올려도,
        트리가 바뀌어도 명령을 다시 안 돌리고 같은 timeout 행을 다시 적었다 (단독 실행 44.4초,
        상한 120초). 그래서 그때의 상한과 그때의 트리를 키로 잡고, 하나라도 다르면 다시 잰다."""
        from asgard.hooks.asgard_hooklib.baseline import _contract_timed_out_before

        events = [{"diff_hash": "aaa", "criteria_checks": [{"cmd": "slow", "timed_out": True, "budget": 120}]}]
        self.assertTrue(_contract_timed_out_before(events, "slow", 120, "aaa"))
        self.assertFalse(_contract_timed_out_before(events, "slow", 240, "aaa"), "상한을 올렸는데 안 다시 잰다")
        self.assertFalse(_contract_timed_out_before(events, "slow", 120, "bbb"), "트리가 바뀌었는데 안 다시 잰다")
        legacy = [{"diff_hash": "aaa", "criteria_checks": [{"cmd": "slow", "timed_out": True}]}]
        self.assertFalse(_contract_timed_out_before(legacy, "slow", 120, "aaa"), "축 없는 옛 행이 메모로 섰다")

    def test_a_contract_timeout_records_the_budget_it_missed(self):
        """상한을 같이 안 적으면 다음 턴이 무슨 조건에서 늦었는지 모른 채 결론만 물려받는다."""
        self.policy(baseline_checks=[], baseline_timeout=1)
        slow = 'python3 -c "import time; time.sleep(5)"'
        self.open_quest("--criteria", f"느린 계약 | verify: {slow}")
        self.write("app.py", "print('ok')\n")
        self.verify()
        rows = [r for r in self.last_event()["criteria_checks"] if r["cmd"] == slow]
        self.assertEqual(len(rows), 1, self.last_event()["criteria_checks"])
        self.assertTrue(rows[0]["timed_out"])
        self.assertEqual(rows[0]["budget"], 1)

    def test_stdin_baseline_forgery_is_refused(self):
        """위조된 baseline 은 버려지는 대신 거절된다 — 조용히 버리면 시도한 쪽이 통과로 읽는다."""
        self.policy(baseline_checks=["false"])
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        body = {
            "role": "verifier",
            "event": "verify",
            "commands": [{"cmd": "python3 app.py", "exit_code": 0}],
            "baseline": {"state": "green"},  # 위조 시도
        }
        forged = self.qlog("append", "--verdict", "PASS", stdin=json.dumps(body))
        self.assertEqual(forged.returncode, 2, forged.stdout)
        self.assertIn("baseline", forged.stderr)
        self.assertEqual(self.last_event()["event"], "plan", "거절된 위조가 기록을 늘렸다")

        # 같은 판정을 위조 없이 다시 적으면 하네스가 자기 손으로 red 를 계산해 붙인다.
        del body["baseline"]
        clean = self.qlog("append", "--verdict", "PASS", stdin=json.dumps(body))
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(self.last_event()["baseline"]["state"], "red")

    def test_uv_project_autodetect_uses_uv_run(self):
        # uv.lock이 있으면 자동 감지가 PATH pytest 대신 uv run을 기록한다 — venv 밖 pytest는
        # 수집 실패(skip)로 게이트가 조용히 무력화되던 구멍 (베이스라인 uv-우선)
        self.write("uv.lock", "")
        self.write("tests/test_ok.py", "def test_ok():\n    assert True\n")
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        self.verify()
        bl = self.last_event()["baseline"]
        self.assertEqual(bl["results"][0]["cmd"], "uv run pytest -x -q")
        self.assertNotEqual(bl["state"], "red")  # uv spawn 실패(exit 2)여도 skip — fail-open

    def test_deleted_test_file_forces_full_verify(self):
        self.policy(verify_level="high")
        self.write("tests/test_app.py", "def test_a(): pass\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "add test"], check=True)
        self.open_quest()
        os.remove(os.path.join(self.root, "tests", "test_app.py"))
        self.write("app.py", "print('ok')\n")
        self.verify()  # micro PASS — 테스트 삭제 diff는 full을 요구한다 (anti-Goodhart)
        st = jout(self.qlog("state"))
        self.assertIn("tests/test_app.py", st["deleted_tests"])
        self.assertTrue(st["full_required"])
        self.assertEqual(jout(self.qlog("next"))["next_role"], "VERIFIER")
        gp = jout(self.gate())
        self.assertEqual(gp.get("decision"), "block")
        self.assertIn("deleted tests", gp.get("reason", ""))

    def test_untracked_test_file_is_not_a_deleted_test(self):
        """미추적 테스트가 디스크에 멀쩡히 있는데 삭제로 잡히면, 그 저장소의 모든 쓰기 퀘스트가
        무엇을 고치든 full Verifier 로 간다 — base_ref 는 미추적까지 담은 트리라 색인과 맞대면
        안 되고 현재 트리와 맞대야 한다 (26-08-04 실측: 미추적 4개가 24줄 변경을 full 로 올렸다)."""
        self.write("tests/test_untracked.py", "def test_a(): pass\n")  # 커밋하지 않는다
        self.open_quest()
        self.write("app.py", "print('ok')\n")
        st = jout(self.qlog("state"))
        self.assertEqual(st["deleted_tests"], [])
        self.assertFalse(st["full_required"])
        self.assertFalse(st["sig_risk"])
        self.assertTrue(os.path.exists(os.path.join(self.root, "tests", "test_untracked.py")))


class TestDetectChecks(unittest.TestCase):
    """베이스라인 자동 감지 (uv-우선) — uv 프로젝트는 uv run, 아니면 PATH pytest, 명시 정책 최우선."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        from asgard_hooklib import runners

        self.runners = runners
        self.detect = runners.detect_checks

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, rel):
        open(os.path.join(self.root, rel), "w").close()

    def which(self, *names):
        return mock.patch("shutil.which", side_effect=lambda c: f"/bin/{c}" if c in names else None)

    def test_uv_lock_prefers_uv_run(self):
        self.touch("uv.lock")
        self.touch("pyproject.toml")
        with self.which("uv", "pytest"):
            self.assertEqual(self.detect(self.root, {}), ["uv run pytest -x -q"])

    def test_uv_lock_without_uv_falls_back_to_path_pytest(self):
        self.touch("uv.lock")
        self.touch("pyproject.toml")
        with self.which("pytest"):
            self.assertEqual(self.detect(self.root, {}), ["pytest -x -q"])

    def test_plain_project_uses_path_pytest(self):
        self.touch("pyproject.toml")
        with self.which("uv", "pytest"):
            self.assertEqual(self.detect(self.root, {}), ["pytest -x -q"])

    def test_no_markers_no_checks(self):
        with self.which("uv", "pytest"):
            self.assertEqual(self.detect(self.root, {}), [])

    # ── JVM 레인. 자동 감지가 pytest·npm 계열만 보던 탓에 Gradle·Maven 저장소는 손으로 적지
    #    않으면 하네스 실행 증거 레인이 통째로 꺼진 채 돌았다 (26-08-05 hvami-mono 실측).
    def module(self, name, *, tests=True, pom="", gradlew=False):
        base = os.path.join(self.root, name) if name else self.root
        if tests:
            os.makedirs(os.path.join(base, "src", "test", "java"), exist_ok=True)
        else:
            os.makedirs(base, exist_ok=True)
        if pom:
            with open(os.path.join(base, "pom.xml"), "w", encoding="utf-8") as handle:
                handle.write(pom)
        if gradlew:
            wrapper = os.path.join(base, "gradlew")
            open(wrapper, "w").close()
            os.chmod(wrapper, 0o755)

    def test_gradle_module_with_tests_is_detected(self):
        self.module("svc", gradlew=True)
        with self.which("uv"):
            self.assertEqual(self.detect(self.root, {}), ["svc/gradlew test"])

    def test_runner_without_test_sources_is_not_a_baseline(self):
        """테스트가 0개인 모듈에서는 exit 0 이 설계상 보장된다 — 아무것도 안 재는 레인이 선다."""
        self.module("svc", tests=False, gradlew=True)
        with self.which("uv"):
            self.assertEqual(self.detect(self.root, {}), [])

    @contextlib.contextmanager
    def maven_host(self, *, local_repo=True, runner_starts=True):
        """호스트 사실을 시험이 빌려오지 않게 고정한다.

        `~/.m2/repository` 유무와 `mvn` 실행 가능 여부는 **이 기계의 사정**이다. 안 묶으면
        Maven 이 깔린 개발기에서만 초록이고 CI·컨테이너에서 빨개진다 — 같은 퀘스트가
        `templates/worker.py` 에 적은 Filesystem 결정론 규칙을 시험 자신이 어기게 된다."""
        with (
            self.which("uv", "mvn"),
            mock.patch("asgard_hooklib.runners._maven_local_repo", return_value=local_repo),
            mock.patch("asgard_hooklib.runners._runner_starts", return_value=runner_starts),
        ):
            yield

    def test_maven_module_needs_a_declared_test_runner(self):
        """`src/test/java` 가 있어도 pom 이 러너를 선언하지 않으면 진공 green 아니면 컴파일 red 다."""
        self.module("fep", pom="<project><artifactId>fep</artifactId></project>")
        with self.maven_host():
            self.assertEqual(self.detect(self.root, {}), [])
        self.module("fepj", pom="<project><dependency><artifactId>junit</artifactId></dependency></project>")
        with self.maven_host():
            self.assertEqual(self.detect(self.root, {}), ["mvn -q -f fepj/pom.xml test"])

    def test_maven_needs_a_runner_that_actually_starts(self):
        """버전 관리자의 셰임은 이름은 내주고 실행은 거절한다 — 그 exit 1 은 테스트 실패로 읽힌다."""
        self.module("fepj", pom="<project><dependency><artifactId>junit</artifactId></dependency></project>")
        with self.maven_host(runner_starts=False):
            self.assertEqual(self.detect(self.root, {}), [])

    def test_maven_needs_the_local_repository(self):
        """첫 실행의 의존성 내려받기 실패는 exit 1 이라 테스트 실패와 구분되지 않는다."""
        self.module("fepj", pom="<project><dependency><artifactId>junit</artifactId></dependency></project>")
        with self.maven_host(local_repo=False):
            self.assertEqual(self.detect(self.root, {}), [])

    def test_detected_jvm_commands_pass_the_deterministic_lane(self):
        """감지 레인과 검증 레인이 같은 답을 들어야 한다 — 내준 명령이 게이트를 세워야 한다."""

        self.module("svc", gradlew=True)
        with self.which("uv"):
            for cmd in self.detect(self.root, {}):
                self.assertTrue(self.runners.jvm_behavior_check(cmd), cmd)
            self.assertTrue(self.runners.gate_first_checks_available(self.root, {}))

    def test_explicit_policy_wins(self):
        self.touch("uv.lock")
        with self.which("uv", "pytest"):
            self.assertEqual(self.detect(self.root, {"baseline_checks": ["uv run ruff check"]}), ["uv run ruff check"])

    def test_trivial_or_shell_composed_policy_is_rejected(self):
        self.assertEqual(self.detect(self.root, {"baseline_checks": ["true", "pytest -q && curl bad"]}), [])

    # ── 안전 표는 **문자열 앞머리**로만 대조됐다 — 같은 검증을 부르는 정당한 표기가 표를 못 넘어
    #    통째로 사라졌고, 설정한 사람에게도 게이트에게도 아무 말이 없었다 (26-07-31 실측:
    #    `<abs>/python -m pytest` 하나로 checks_available이 false가 되어 독립 증거 레인이 침묵,
    #    회귀를 심은 채 날조한 PASS가 그대로 통과했다). 정규형은 판정 전용 — 실행은 원문으로.
    def accepted(self, cmd):
        return self.detect(self.root, {"baseline_checks": [cmd]}) == [cmd]

    def test_path_qualified_interpreter_running_a_safe_module_is_accepted(self):
        for cmd in (
            "/opt/py/bin/python -m pytest -x -q",
            "/repo/.venv/bin/python -m pytest -q",
            "python3.13 -m pytest -q",
            ".venv/bin/pytest -q",
            "env CI=1 python -m pytest -q",
            "PYTHONPATH=src python -m pytest -q",
            "poetry run pytest -q",
        ):
            self.assertTrue(self.accepted(cmd), cmd)

    def test_repo_local_executables_and_scripts_stay_rejected(self):
        """정책은 clone으로 딸려 오는 입력이다 — 이름으로 접어 주면 임의 실행 통로가 된다."""
        for cmd in (
            "./pytest",
            "evil/pytest -q",
            "/evil/bin/pytest",
            "python evil.py",
            "python3.13 evil.py",
            "python -m http.server",
            "bash -c 'pytest'",
        ):
            self.assertFalse(self.accepted(cmd), cmd)

    def test_rejected_checks_are_reported_rather_than_dropped_in_silence(self):

        policy = {"baseline_checks": ["pytest -q", "./evil.sh", "bash -c pytest"]}
        self.assertEqual(self.runners.rejected_checks(policy), ["./evil.sh", "bash -c pytest"])
        self.assertEqual(self.runners.configured_checks(policy)[0], ["pytest -q"])
        self.assertEqual(self.runners.rejected_checks({"baseline_checks": ["pytest -q"]}), [])

    # ── JS/TS 레인 — 자동감지가 pytest 전용이던 탓에 JS 저장소는 하네스 실행 증거가 통째로 꺼져
    #    있었다 (26-07-26 helios 실측). 의존성이 설치된 경우에만 감지 — 미설치 러너 실패(exit 1)는
    #    테스트 실패와 구분되지 않아 false-red가 된다.
    def package(self, scripts, lockfile=None):
        with open(os.path.join(self.root, "package.json"), "w") as handle:
            json.dump({"name": "x", "scripts": scripts}, handle)
        os.makedirs(os.path.join(self.root, "node_modules"), exist_ok=True)
        if lockfile:
            self.touch(lockfile)

    def test_node_project_with_installed_deps_uses_lockfile_manager(self):
        self.package({"test": "vitest run"}, "pnpm-lock.yaml")
        with self.which("pnpm", "npm"):
            self.assertEqual(self.detect(self.root, {}), ["pnpm test"])

    def test_node_project_without_lockfile_falls_back_to_npm(self):
        self.package({"test": "vitest run"})
        with self.which("npm"):
            self.assertEqual(self.detect(self.root, {}), ["npm test"])

    def test_node_project_without_installed_deps_is_not_detected(self):
        with open(os.path.join(self.root, "package.json"), "w") as handle:
            json.dump({"name": "x", "scripts": {"test": "vitest run"}}, handle)
        with self.which("pnpm", "npm"):
            self.assertEqual(self.detect(self.root, {}), [])

    def test_node_project_without_test_script_is_not_detected(self):
        self.package({"build": "vite build"}, "pnpm-lock.yaml")
        with self.which("pnpm", "npm"):
            self.assertEqual(self.detect(self.root, {}), [])

    def test_python_markers_still_win_over_node(self):
        self.touch("pyproject.toml")
        self.package({"test": "vitest run"}, "pnpm-lock.yaml")
        with self.which("pytest", "pnpm"):
            self.assertEqual(self.detect(self.root, {}), ["pytest -x -q"])

    def test_node_test_counts_as_a_behavior_runner(self):

        self.package({"test": "vitest run"}, "pnpm-lock.yaml")
        with self.which("pnpm", "npm"):
            self.assertTrue(self.runners.gate_first_checks_available(self.root, {}))

    # ── JVM 레인 — 서비스마다 래퍼를 두는 모노레포는 루트에 gradlew 가 없다 (26-08-04 hvami-mono:
    #    gradlew 3개가 전부 하위 디렉터리). 안전 표와 게이트-우선 판정이 같은 자를 써야 설정이
    #    통과했는데 레인은 안 서는 상태가 안 생긴다.
    def test_jvm_wrappers_are_accepted_at_any_depth_inside_the_repository(self):

        for cmd in (
            "./gradlew test",
            "./gradlew testDebugUnitTest",
            "hvami-batch/gradlew test",
            "./hvami-feph-secure/gradlew :app:testDebugUnitTest --no-daemon",
            "gradle test",
            "mvn -q test",
            "hvami-parser-secure/mvnw verify",
            "./gradlew test --tests SomeTest",  # 필터가 붙어도 태스크는 돈다
        ):
            policy = {"baseline_checks": [cmd]}
            self.assertEqual(self.runners.configured_checks(policy)[0], [cmd], cmd)
            self.assertTrue(self.runners.gate_first_checks_available(self.root, policy), cmd)

    def test_jvm_runners_outside_the_repository_or_without_a_test_task_are_refused(self):

        for cmd in (
            "/opt/evil/gradlew test",  # 저장소 밖 실행 파일
            "../evil/gradlew test",
            "$HOME/evil/gradlew test",  # 셸이 나중에 편다 — isabs 는 False 인데 실행은 shell=True
            "~/evil/gradlew test",
            "${HOME}/x/mvnw test",
            "/usr/bin/mvn test",  # PATH 러너에 경로가 붙으면 이름으로 안 접는다
            "./gradlew build",  # 테스트 태스크가 아니다
            "mvn package",
            "./gradlew",
            "./gradlew test -x test",  # 테스트를 빼는 명령이다
            "./gradlew testClasses",  # 컴파일만 — 단언이 안 돈다
            "./gradlew --tests SomeTest",  # 필터만 있고 태스크가 없다
            "mvn -DskipTests test",
            "mvn verify -Dmaven.test.skip=true",
        ):
            policy = {"baseline_checks": [cmd]}
            self.assertEqual(self.runners.configured_checks(policy)[0], [], cmd)
            self.assertIn(cmd, self.runners.rejected_checks(policy), cmd)
            self.assertFalse(self.runners.gate_first_checks_available(self.root, policy), cmd)


class TestParallelPytest(unittest.TestCase):
    """하네스가 도는 pytest 만 병렬로 — 선언 문자열은 결속 키라 그대로 남는다."""

    def parallel(self, cmd):
        from asgard.hooks.quest_log import _parallel_pytest

        return _parallel_pytest(cmd)

    def test_n_auto_lands_right_after_the_pytest_token(self):
        # 끝에 붙이면 `&&` 뒤의 다른 명령이 인자를 받는다 — 붙이는 자리가 계약이다.
        for cmd, want in (
            ("uv run pytest -q tests/x.py", "uv run pytest -n auto -q tests/x.py"),
            ("pytest -q", "pytest -n auto -q"),
            ("python -m pytest -q", "python -m pytest -n auto -q"),
            # AGENTS.md 가 계약 명령에 쓰는 형태 — 러너와 프로그램 사이의 긴 옵션은 건너뛴다.
            ("uv run --no-project pytest -q", "uv run --no-project pytest -n auto -q"),
            ("ruff check . && uv run pytest -q", "ruff check . && uv run pytest -n auto -q"),
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.parallel(cmd), want)

    def test_pytest_outside_the_program_slot_is_not_a_pytest_call(self):
        # 토큰만 찾으면 인자·경로에 스친 한 마디까지 잡아 엉뚱한 명령에 `-n auto` 를 붙인다.
        for cmd in ("echo pytest", "grep pytest README.md", "ls tests/pytest"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.parallel(cmd))

    def test_non_pytest_and_already_parallel_commands_are_left_alone(self):
        for cmd in ("npm test", "just check", "uv run pytest -n 4 -q", "uv run pytest --numprocesses=2"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.parallel(cmd))

    def test_a_disabled_xdist_plugin_is_respected_in_either_spelling(self):
        # `-p no:xdist` 와 `-pno:xdist` 는 같은 뜻이다. 토큰만 보면 붙여 쓴 쪽이 유일한 탈출구를
        # 그냥 지나쳐, 병렬을 끈 저장소가 그래도 병렬로 돌아간다.
        for cmd in ("uv run pytest -p no:xdist -q", "uv run pytest -pno:xdist -q"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.parallel(cmd))


class TestParallelCheckRun(TrinityBase):
    """`_run_check` — 병렬 실행이 직렬과 다른 판정을 내지 않는가."""

    def run_check(self, cmd, parallel_ok=True):
        from asgard.hooks.quest_log import _run_check

        return _run_check(cmd, self.root, 180, parallel_ok)

    def test_every_non_green_outcome_is_classified_by_the_serial_run(self):
        """불변식 하나: 초록이 아니면 판정하는 것은 직렬이다 — 코드 목록이 아니라 이것이 계약이다.

        xdist 는 종료 코드를 자기 방식으로 다시 매긴다. 직렬 대 병렬로 사용법 오류 4 대 5,
        `-x` 중단 1 대 2, `-k` 무매치 4 대 3 이다. `run_baseline` 은 2·3·4·5 를 skip 으로 접으므로
        재사상 하나를 놓칠 때마다 빨간 게이트가 사유 없이 꺼진다 — 목록을 넓히는 수리를 두 번 했고
        두 번 다 남은 코드가 있었다. 그래서 여기서 세는 것은 코드가 아니라 **누가 판정했는가**다:
        비초록이면 `run_cmd` 가 None, 곧 직렬이 답을 냈다는 뜻이다."""
        self.write("tests/test_red.py", "def test_red():\n    assert False\n")
        self.write("tests/test_ok.py", "def test_ok():\n    assert True\n")
        for cmd, serial_code in (
            ("uv run pytest -q tests/does_not_exist.py", 4),  # 사용법 오류
            ("uv run pytest -q -x tests/test_red.py", 1),  # 실패 중단
            ("uv run pytest -q -k zzz_no_such_test tests/test_ok.py", 5),  # 수집 0건
        ):
            with self.subTest(cmd=cmd):
                code, _, run_cmd = self.run_check(cmd)
                self.assertEqual(code, serial_code)
                self.assertIsNone(run_cmd, "비초록은 직렬이 판정해야 한다")

    def test_a_suite_that_only_breaks_in_parallel_is_not_a_red(self):
        """병렬에서만 깨지는 스위트는 직렬 재실행이 초록을 되돌려준다 — 거짓 red 가 안 난다."""
        self.write("tests/test_ok.py", "def test_ok():\n    assert True\n")
        code, _, _ = self.run_check("uv run pytest -q -p no:xdist tests/test_ok.py")
        self.assertEqual(code, 0)

    def test_a_green_suite_runs_in_parallel_and_records_what_it_ran(self):
        self.write("tests/test_ok.py", "def test_ok():\n    assert True\n")
        code, _, run_cmd = self.run_check("uv run pytest -q tests/test_ok.py")
        self.assertEqual(code, 0)
        self.assertEqual(run_cmd, "uv run pytest -n auto -q tests/test_ok.py")

    def test_the_policy_key_turns_parallel_off(self):
        """끄면 병렬을 아예 시도하지 않는다 — 판정이 아니라 값을 아끼는 손잡이다.

        비초록이 직렬로 다시 판정되므로 병렬은 결과를 안 흔든다. 다만 병렬에서 자주 깨지는
        스위트는 빨간 판정마다 병렬 실행 한 번을 더 쓰고 버리는데, 그 값이 아까운 저장소가 있다."""
        self.write("tests/test_ok.py", "def test_ok():\n    assert True\n")
        code, _, run_cmd = self.run_check("uv run pytest -q tests/test_ok.py", parallel_ok=False)
        self.assertEqual(code, 0)
        self.assertIsNone(run_cmd)


class TestPipelineVerification(TrinityBase):
    """Mode B barrier -> pipeline: a done unit whose files do not overlap any still-open
    unit's files is immediately verifiable, without waiting for the whole wave (see
    quest_log.verifiable_units)."""

    def ticket(self, unit, files):
        return self.qlog(
            "append",
            stdin=json.dumps(
                {
                    "role": "thinker",
                    "event": "ticket",
                    "unit": unit,
                    "ticket_status": "todo",
                    "subtask": "unit %s" % unit,
                    "changed_files": files,
                }
            ),
        )

    def finish(self, unit):
        claim = jout(self.qlog("ticket-claim", "--unit", str(unit), "--worker", "w%s" % unit))
        return self.qlog(
            "ticket-finish", "--unit", str(unit), "--claim-token", claim["claim_token"], "--status", "done"
        )

    def test_nonoverlapping_done_unit_is_immediately_verifiable(self):
        self.open_quest()
        self.ticket(1, ["a.py"])
        self.ticket(2, ["b.py"])
        self.qlog("ticket-claim", "--unit", "2", "--worker", "w2")
        self.finish(1)
        self.assertEqual(jout(self.qlog("state"))["verifiable_units"], ["1"])

    def test_overlapping_in_progress_unit_blocks_early_verification(self):
        self.open_quest()
        self.ticket(1, ["shared.py"])
        self.ticket(2, ["shared.py"])
        self.qlog("ticket-claim", "--unit", "2", "--worker", "w2")
        self.finish(1)
        self.assertEqual(jout(self.qlog("state"))["verifiable_units"], [])

    def test_open_unit_with_no_declared_files_blocks_all_early_verification(self):
        # Absence of a `files` declaration on a still-open unit is not proof of no overlap —
        # fail-closed: no unit is early-verifiable until every open unit declares its files.
        self.open_quest()
        self.ticket(1, ["a.py"])
        self.ticket(2, [])
        self.finish(1)
        self.assertEqual(jout(self.qlog("state"))["verifiable_units"], [])

    def test_path_normalization_treats_dot_slash_prefix_as_same_file(self):
        self.open_quest()
        self.ticket(1, ["./a.py"])
        self.ticket(2, ["a.py"])
        self.qlog("ticket-claim", "--unit", "2", "--worker", "w2")
        self.finish(1)
        self.assertEqual(jout(self.qlog("state"))["verifiable_units"], [])

    def test_final_close_still_requires_every_ticket_done(self):
        self.open_quest()
        self.ticket(1, ["a.py"])
        self.ticket(2, ["b.py"])
        self.qlog("ticket-claim", "--unit", "2", "--worker", "w2")
        self.finish(1)
        self.assertEqual(jout(self.qlog("state"))["verifiable_units"], ["1"])
        self.assertNotEqual(self.qlog("close").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
