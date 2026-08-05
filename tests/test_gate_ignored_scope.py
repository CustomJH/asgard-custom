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
    # 각 하위 클래스가 자기 시나리오의 기준 스냅샷을 세운다 — 여기서는 선언만 한다.
    base_snapshot: dict
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
        """열거가 실패하면 스냅샷은 증거가 아니다 — 그 사실이 marker 로 남아야 open 이 막힌다.

        패치 대상이 훅이 아니라 `asgard_hooklib.scope` 인 것이 요점이다: 두 훅은 이제 이름을
        재수출할 뿐이라 훅 쪽 이름을 갈아 끼워도 열거를 도는 함수는 그대로다. 고칠 곳도 여기다."""
        from unittest import mock

        from asgard_hooklib import scope as scope_module

        marker = {"<snapshot-unavailable>": "ignored-enumeration-failed"}
        with mock.patch.object(scope_module, "git", return_value=(1, b"")):
            for module in (quest_log, verifier_gate):
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


class DeclaredButUnbindableArtifacts(Repo):
    """선언은 결속을 약속하는데 해시가 못 따라가는 두 형상 — 조용히 통과시키지 않는다.

    링크를 안 따라가는 것도, 중첩 저장소 안으로 안 내려가는 것도 그 자체로는 옳다 (전자는
    저장소 밖 자격 증명을 증거로 열지 않기 위해서고, 후자는 git 의 동작이다). 결함은 그
    자리에서 `artifacts:` 선언이 결속된 척한다는 것이다."""

    def test_a_symlinked_artifact_does_not_move_the_hash(self):
        os.makedirs(os.path.join(self.root, "workspace"), exist_ok=True)
        self.write("outside.txt", "before\n")
        os.symlink(os.path.join(self.root, "outside.txt"), os.path.join(self.root, "workspace", "link.txt"))
        scope = ("workspace/link.txt",)
        before = quest_log.ignored_state(self.root, scope)
        self.write("outside.txt", "after\n")  # 링크 뒤 파일이 바뀌었다
        self.assertEqual(before, quest_log.ignored_state(self.root, scope), "링크 신원만 해시된다")
        for module in (quest_log, verifier_gate):
            self.assertTrue(
                any(v.startswith(module.UNBOUND) for v in module.ignored_state(self.root, scope).values()),
                module.__name__,
            )
            unbound = module.unbound_artifacts(self.root, scope)
            self.assertEqual(len(unbound), 1, module.__name__)
            self.assertIn("symlink", unbound[0])

    def test_a_nested_repository_artifact_does_not_move_the_hash(self):
        nested = os.path.join(self.root, "workspace", "sub")
        os.makedirs(nested)
        subprocess.run(["git", "init", "-q"], cwd=nested, check=True)
        self.write("workspace/sub/report.md", "before\n")
        scope = ("workspace/sub",)
        before = quest_log.ignored_state(self.root, scope)
        self.write("workspace/sub/report.md", "after\n")
        self.assertEqual(before, quest_log.ignored_state(self.root, scope), "git 이 안으로 안 내려간다")
        for module in (quest_log, verifier_gate):
            unbound = module.unbound_artifacts(self.root, scope)
            self.assertEqual(len(unbound), 1, module.__name__)
            self.assertIn("nested repository", unbound[0])

    def test_an_unbindable_artifact_leaves_the_contract_unmet(self):
        os.makedirs(os.path.join(self.root, "workspace"), exist_ok=True)
        self.write("outside.txt", "x\n")
        os.symlink(os.path.join(self.root, "outside.txt"), os.path.join(self.root, "workspace", "link.txt"))
        criteria = ["증거 | artifacts: workspace/link.txt"]
        for module in (quest_log, verifier_gate):
            unmet = module.unmet_contracts(self.root, criteria, {})
            self.assertTrue(any("symlink" in item for item in unmet), f"{module.__name__}: {unmet}")

    def test_a_symlinked_parent_does_not_satisfy_the_contract(self):
        # `os.path.exists` 는 링크를 따라가 "있다"고 답하는데 git 은 링크 하나만 저장하고 안으로
        # 안 내려간다 — 저장소 밖 파일이 계약을 채운다 (26-08-05 교차검토).
        outside = tempfile.mkdtemp(prefix="asgard-outside-")
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        with open(os.path.join(outside, "x.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        os.symlink(outside, os.path.join(self.root, "out"))
        criteria = ["증거 | artifacts: out/x.json"]
        for module in (quest_log, verifier_gate):
            self.assertTrue(os.path.exists(os.path.join(self.root, "out/x.json")), "전제: 존재 검사만으론 통과한다")
            unmet = module.unmet_contracts(self.root, criteria, {})
            self.assertTrue(any("symlink" in item for item in unmet), f"{module.__name__}: {unmet}")

    def test_a_tracked_symlink_inside_a_declared_directory_is_unbound(self):
        # 추적된 심링크는 `ls-files --others --ignored` 에 안 나온다 — 무시 파일 열거만 보면 놓친다.
        os.makedirs(os.path.join(self.root, "dist"))
        self.write("dist/keep.txt", "x\n")
        os.symlink("/etc/hosts", os.path.join(self.root, "dist", "bundle.js"))
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "dist"], check=True)
        criteria = ["증거 | artifacts: dist"]
        for module in (quest_log, verifier_gate):
            unmet = module.unmet_contracts(self.root, criteria, {})
            self.assertTrue(any("dist/bundle.js" in item for item in unmet), f"{module.__name__}: {unmet}")

    def test_an_untracked_symlink_under_a_declared_directory_is_unbound(self):
        # 추적도 무시도 아닌 새 링크는 두 열거 어디에도 안 나온다 — 걸어서 봐야 잡힌다.
        os.makedirs(os.path.join(self.root, "out"))
        self.write("out/keep.txt", "x\n")
        os.symlink("/etc/hosts", os.path.join(self.root, "out", "report.json"))
        for module in (quest_log, verifier_gate):
            unmet = module.unmet_contracts(self.root, ["증거 | artifacts: out"], {})
            self.assertTrue(any("out/report.json" in item for item in unmet), f"{module.__name__}: {unmet}")

    def test_harness_state_cannot_be_a_declared_artifact(self):
        # `.asgard/**` 는 어느 트리에도 안 들어간다 — 존재만 확인되고 내용은 어디에도 안 묶인다.
        os.makedirs(os.path.join(self.root, ".asgard", "receipts"))
        self.write(".asgard/receipts/run.json", "{}\n")
        for module in (quest_log, verifier_gate):
            unmet = module.unmet_contracts(self.root, ["증거 | artifacts: .asgard/receipts/run.json"], {})
            self.assertTrue(any("under .asgard" in item for item in unmet), f"{module.__name__}: {unmet}")

    def test_a_map_page_is_the_one_bound_place_under_asgard(self):
        os.makedirs(os.path.join(self.root, ".asgard", "map"))
        self.write(".asgard/map/orchestrator.md", "# map\n")
        for module in (quest_log, verifier_gate):
            self.assertEqual(
                module.unmet_contracts(self.root, ["지도 | artifacts: .asgard/map/orchestrator.md"], {}), []
            )

    def test_a_bindable_artifact_leaves_nothing_unmet(self):
        self.write("workspace/report.md", "ok\n")
        criteria = ["증거 | artifacts: workspace/report.md"]
        for module in (quest_log, verifier_gate):
            self.assertEqual(module.unmet_contracts(self.root, criteria, {}), [], module.__name__)

    def test_an_absolute_artifact_is_not_met_by_a_file_outside_the_repository(self):
        outside = os.path.join(tempfile.gettempdir(), "asgard-outside-artifact.json")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("{}")
        self.addCleanup(lambda: os.path.exists(outside) and os.unlink(outside))
        criteria = [f"증거 | artifacts: {outside}"]
        for module in (quest_log, verifier_gate):
            # 결속(`artifact_scope`)은 이미 거절한다 — 충족 검사도 같은 술어여야 한 선언을
            # 두 소비처가 다르게 읽지 않는다 (`os.path.join(root, "/tmp/x")` == "/tmp/x").
            self.assertEqual(module.artifact_scope(criteria), (), module.__name__)
            unmet = module.unmet_contracts(self.root, criteria, {})
            self.assertTrue(any("outside the repository" in item for item in unmet), f"{module.__name__}: {unmet}")


class TreeSnapshotSeed(Repo):
    """C — 임시 인덱스의 씨앗을 바꿔도 트리는 같아야 한다 (해시의 뜻이 안 바뀐다)."""

    def _slow_tree(self):
        """씨앗을 강제로 `read-tree HEAD` 로 세운 종전 경로."""
        import tempfile as _tempfile

        fd, index_path = _tempfile.mkstemp(prefix="seed-check-")
        os.close(fd)
        os.unlink(index_path)
        env = {**os.environ, "GIT_INDEX_FILE": index_path}

        def run(*args):
            return subprocess.run(["git", "-C", self.root, *args], capture_output=True, env=env, check=False)

        try:
            run("read-tree", self.head)
            run("add", "-A", "--", ".", ":(exclude).asgard")
            run("add", "-A", "-f", "--", ".asgard/map")
            return run("write-tree").stdout.decode().strip()
        finally:
            if os.path.exists(index_path):
                os.unlink(index_path)

    def test_the_fast_seed_gives_the_same_tree(self):
        self.write("app.py", "print('changed')\n")
        self.write("workspace/scratch.txt", "junk\n")
        for module in (quest_log, verifier_gate):
            self.assertEqual(module.current_tree_ref(self.root), self._slow_tree(), module.__name__)

    def test_a_stat_flagged_entry_falls_back_to_the_slow_seed(self):
        # `add -A` 는 assume-unchanged 표를 존중해 항목을 건너뛴다. 새 인덱스에는 그 표가 없어
        # 같은 `add -A` 가 다시 해시하므로, 사본을 쓰면 그 파일의 편집이 스냅샷에서 사라진다
        # (26-08-05 교차검토 재현: 두 트리가 갈렸다).
        subprocess.run(["git", "-C", self.root, "update-index", "--assume-unchanged", "app.py"], check=True)
        self.write("app.py", "print('an edit the gate must still see')\n")
        self.assertEqual(
            subprocess.run(
                ["git", "-C", self.root, "diff-index", "--cached", "--quiet", "HEAD"], check=False
            ).returncode,
            0,
            "전제: 스테이지는 깨끗하다 — 그래서 빠른 씨앗의 조건을 통과한다",
        )
        for module in (quest_log, verifier_gate):
            self.assertEqual(module.current_tree_ref(self.root), self._slow_tree(), module.__name__)

    def test_a_staged_change_falls_back_to_the_slow_seed(self):
        # 스테이지된 인덱스를 씨앗으로 쓰면 `add -A` 가 안 덮는 구역에서 트리가 갈린다.
        # 그때는 느린 길로 물러서야 하고, 결과 트리는 종전과 같아야 한다.
        self.write("app.py", "print('staged')\n")
        subprocess.run(["git", "-C", self.root, "add", "--", "app.py"], check=True)
        self.write("app.py", "print('and then edited')\n")
        for module in (quest_log, verifier_gate):
            self.assertEqual(module.current_tree_ref(self.root), self._slow_tree(), module.__name__)


if __name__ == "__main__":
    unittest.main()
