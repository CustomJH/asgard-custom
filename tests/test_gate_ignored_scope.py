#!/usr/bin/env python3
"""판정 해시의 무시 파일 결속 범위 — 선언된 산출물만 센다 (A1 회귀).

이 파일이 지키는 것은 양쪽이다. 느슨한 쪽으로 새면 계측 스크립트 하나가 직전 PASS 를 stale 로
만들어 게이트가 자기 판정을 무효로 하고 (26-08-04 세션 3회 orphan-write), 조인 쪽으로 새면
`.gitignore` 아래 증거물이 바뀌어도 해시가 안 움직여 게이트가 무장해제된다. 두 훅이 같은 값을
내는지도 여기서 못박는다 — 어긋나면 PASS 가 영구 stale 이 된다.

실행: uv run pytest tests/test_gate_ignored_scope.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "asgard", "hooks"))
QLOG = os.path.join(SRC, "quest_log.py")

from asgard.hooks import quest_log, verifier_gate  # noqa: E402


class ScopeParsing(unittest.TestCase):
    """`artifacts:` 선언 → 결속 경로. 두 훅이 같은 함수를 갖는다."""

    def test_declared_artifacts_become_the_scope(self):
        for module in (quest_log, verifier_gate):
            scope = module.artifact_scope(["보고서 | artifacts: workspace/report.md build/log.txt"])
            self.assertEqual(scope, ("build/log.txt", "workspace/report.md"), module.__name__)

    def test_criteria_without_a_contract_declare_nothing(self):
        for module in (quest_log, verifier_gate):
            self.assertEqual(module.artifact_scope(["app.py prints ok"]), (), module.__name__)
            self.assertEqual(module.artifact_scope([]), (), module.__name__)
            self.assertEqual(module.artifact_scope(None), (), module.__name__)

    def test_paths_that_leave_the_repository_are_dropped(self):
        for module in (quest_log, verifier_gate):
            self.assertEqual(module.artifact_scope(["x | artifacts: ../outside.txt ."]), (), module.__name__)
            # `..` 를 그대로 넘기면 git 이 저장소 밖으로 거절해 스냅샷 전체가 불가로 떨어진다.
            self.assertEqual(module.artifact_scope(["x | artifacts: .. a/../../b"]), (), module.__name__)
            # 절대 경로를 저장소 상대로 접으면 결속은 없는 파일에 걸리고 `unmet_contracts` 는
            # 원문을 이어 붙여 저장소 밖 파일로 계약을 충족시킨다 — 한 선언, 두 파일.
            self.assertEqual(module.artifact_scope(["x | artifacts: /etc/passwd"]), (), module.__name__)

    def test_scope_membership_stops_at_a_segment_boundary(self):
        for module in (quest_log, verifier_gate):
            scope = ("workspace",)
            self.assertTrue(module.in_artifact_scope("workspace", scope), module.__name__)
            self.assertTrue(module.in_artifact_scope("workspace/a/b.txt", scope), module.__name__)
            self.assertFalse(module.in_artifact_scope("workspace2/a.txt", scope), module.__name__)

    def test_the_verify_command_cap_does_not_cap_the_binding_scope(self):
        """`criteria_contracts` 는 계약을 5건에서 자른다 — 그 상한이 결속까지 물면 여섯 번째
        산출물이 조용히 안 묶인다."""
        criteria = [f"기준 {i} | verify: pytest -q t{i}.py | artifacts: workspace/a{i}.txt" for i in range(7)]
        for module in (quest_log, verifier_gate):
            self.assertEqual(len(module.criteria_contracts(criteria)), 5, module.__name__)
            self.assertEqual(len(module.artifact_scope(criteria)), 7, module.__name__)

    def test_scope_is_collected_from_every_event_that_carries_criteria(self):
        events = [
            {"criteria": ["열 때 선언 | artifacts: workspace/one.txt"]},
            {"criteria": [{"description": "객체 판정은 계약이 아니다"}]},
            {"criteria": ["나중에 선언 | artifacts: workspace/two.txt"]},
        ]
        for module in (quest_log, verifier_gate):
            self.assertEqual(
                module.quest_events_scope(events),
                ("workspace/one.txt", "workspace/two.txt"),
                module.__name__,
            )


class Repo(unittest.TestCase):
    """`workspace/` 를 무시하는 임시 저장소 — 무시 파일이 실재하는 조건에서만 의미가 있다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = self.root  # 호스트의 git excludesfile·~/.asgard 상태 격리
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "-C", self.root, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", self.root, "config", "user.name", "t"], check=True)
        self.write(".gitignore", "workspace/\n")
        self.write("app.py", "print('ok')\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "init"], check=True)
        self.head = subprocess.run(
            ["git", "-C", self.root, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()

    def tearDown(self):
        if self._home is not None:
            os.environ["HOME"] = self._home
        self.tmp.cleanup()

    def write(self, rel, content):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def qlog(self, *args, stdin=""):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        return subprocess.run(
            [sys.executable, QLOG, *args],
            input=stdin,
            capture_output=True,
            text=True,
            cwd=self.root,
            env=env,
            timeout=120,
        )

    def hashes(self, scope):
        """두 훅이 낸 (해시, 변경목록) — 같아야 한다 (단일 출처 원칙)."""
        snapshot = quest_log.ignored_state(self.root, scope)
        self.assertEqual(snapshot, verifier_gate.ignored_state(self.root, scope))
        q = quest_log.diff_state(self.root, self.head, self.base_snapshot, scope)
        g = verifier_gate.diff_state(self.root, self.head, self.base_snapshot, scope)
        self.assertEqual(q, g, "quest_log 와 verifier_gate 의 해시가 갈리면 PASS 가 영구 stale 이 된다")
        return q[0], q[1]


class UndeclaredIgnoredPathsDoNotMoveTheHash(Repo):
    def test_scratch_output_outside_the_declared_artifacts_is_not_a_change(self):
        self.base_snapshot = quest_log.ignored_state(self.root, ())
        before, _ = self.hashes(())
        self.write("workspace/gate_probe.py", "print('probe')\n")
        after, changed = self.hashes(())
        self.assertEqual(before, after, "선언 밖 스크래치 산출물이 판정 해시를 흔들면 안 된다")
        self.assertNotIn("workspace/gate_probe.py", changed)

    def test_a_declared_artifact_still_binds(self):
        scope = ("workspace/report.md",)
        self.write("workspace/report.md", "before\n")
        self.base_snapshot = quest_log.ignored_state(self.root, scope)
        self.assertEqual(list(self.base_snapshot), ["workspace/report.md"])
        before, _ = self.hashes(scope)

        self.write("workspace/gate_probe.py", "print('probe')\n")  # 선언 밖 — 안 센다
        self.assertEqual(self.hashes(scope)[0], before)

        self.write("workspace/report.md", "after\n")  # 선언 안 — 센다
        after, changed = self.hashes(scope)
        self.assertNotEqual(before, after, "선언한 산출물의 변경이 해시에 안 실리면 게이트가 무장해제된다")
        self.assertIn("workspace/report.md", changed)

    def test_deleting_a_declared_artifact_moves_the_hash(self):
        scope = ("workspace/report.md",)
        self.write("workspace/report.md", "evidence\n")
        self.base_snapshot = quest_log.ignored_state(self.root, scope)
        before, _ = self.hashes(scope)
        os.unlink(os.path.join(self.root, "workspace", "report.md"))
        after, changed = self.hashes(scope)
        self.assertNotEqual(before, after)
        self.assertIn("workspace/report.md", changed)

    def test_a_directory_declaration_binds_everything_under_it(self):
        scope = ("workspace",)
        self.write("workspace/a/report.md", "before\n")
        self.base_snapshot = quest_log.ignored_state(self.root, scope)
        before, _ = self.hashes(scope)
        self.write("workspace/a/report.md", "after\n")
        self.assertNotEqual(self.hashes(scope)[0], before)

    def test_a_declared_artifact_under_a_build_directory_still_binds(self):
        """`_generated` 는 전 저장소를 훑던 시절의 비용 상한이지 결속 규칙이 아니다. 태우면
        `build/`·`target/` 을 기본 출력으로 쓰는 Gradle·Maven 의 증거물이 선언해도 안 묶인다."""
        self.write(".gitignore", "workspace/\nbuild/\ntarget/\n")
        for scope, rel in ((("build/report.json",), "build/report.json"), (("target",), "target/surefire/r.xml")):
            self.write(rel, "before\n")
            self.base_snapshot = quest_log.ignored_state(self.root, scope)
            self.assertEqual(list(self.base_snapshot), [rel], rel)
            before, _ = self.hashes(scope)
            self.write(rel, "after\n")
            after, changed = self.hashes(scope)
            self.assertNotEqual(before, after, rel)
            self.assertIn(rel, changed)

    def test_a_glob_declaration_does_not_widen_the_scope(self):
        """pathspec 은 glob 을 받는다 — 선언이 `*` 여도 돌려받은 경로가 술어를 통과해야 한다."""
        self.write("workspace/gate_probe.py", "print('probe')\n")
        for module in (quest_log, verifier_gate):
            self.assertEqual(module.ignored_state(self.root, ("*",)), {}, module.__name__)

    def test_tracked_changes_are_counted_whatever_the_scope_is(self):
        self.base_snapshot = quest_log.ignored_state(self.root, ())
        before, _ = self.hashes(())
        self.write("app.py", "print('changed')\n")
        after, changed = self.hashes(())
        self.assertNotEqual(before, after)
        self.assertIn("app.py", changed)

    def test_enumeration_failure_is_still_reported_when_something_is_declared(self):
        """열거가 실패하면 스냅샷은 증거가 아니다 — 그 사실이 marker 로 남아야 open 이 막힌다."""
        from unittest import mock

        marker = {"<snapshot-unavailable>": "ignored-enumeration-failed"}
        for module in (quest_log, verifier_gate):
            with mock.patch.object(module, "git", return_value=(1, b"")):
                self.assertEqual(module.ignored_state(self.root, ("workspace",)), marker, module.__name__)


class LiveQuestKeepsItsPassThroughScratchWrites(Repo):
    """CLI 왕복 — 배포 형태 그대로 (임포트가 아니라 subprocess)."""

    def test_pass_survives_an_undeclared_ignored_write_and_falls_to_a_declared_one(self):
        self.write("workspace/report.md", "before\n")
        opened = self.qlog(
            "open",
            "scope-q",
            "--criteria",
            "증거 보고서 | artifacts: workspace/report.md",
            "--session",
            "s1",
        )
        self.assertEqual(opened.returncode, 0, opened.stderr)

        self.write("app.py", "print('patched')\n")
        verified = self.qlog(
            "append",
            "--verdict",
            "PASS",
            "--session",
            "s1",
            stdin=json.dumps(
                {"role": "verifier", "event": "verify", "commands": [{"cmd": "python3 app.py", "exit_code": 0}]}
            ),
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(self.qlog("state", "--session", "s1").stdout)["pass_hash_match"])

        self.write("workspace/gate_probe.py", "print('probe')\n")  # 계측 산출물 — 판정과 무관
        state = json.loads(self.qlog("state", "--session", "s1").stdout)
        self.assertTrue(state["pass_hash_match"], "스크래치 산출물이 PASS 를 stale 로 만들면 안 된다")
        self.assertNotIn("workspace/gate_probe.py", state["changed_files"])

        self.write("workspace/report.md", "after\n")  # 선언한 증거물 — 판정 대상
        state = json.loads(self.qlog("state", "--session", "s1").stdout)
        self.assertFalse(state["pass_hash_match"])
        self.assertIn("workspace/report.md", state["changed_files"])


if __name__ == "__main__":
    unittest.main()
