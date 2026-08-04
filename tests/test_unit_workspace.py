import os
import subprocess
import tempfile
import unittest
from unittest import mock

from asgard.agent.unit_workspace import UnitArtifact, UnitPatch, UnitWorkspace, WorkspaceError


class TestUnitWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.root, check=True)
        self.write("tracked.txt", b"head\n")
        self.write("delete.txt", b"delete\n")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.root, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, data: bytes) -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def test_dirty_and_untracked_baseline_isolated_then_binary_patch_merges(self):
        self.write("tracked.txt", b"head\nuser-dirty\n")
        self.write("untracked.txt", b"user-untracked\n")
        with UnitWorkspace(self.root, 1) as workspace:
            self.assertEqual(open(os.path.join(workspace.path, "tracked.txt"), "rb").read(), b"head\nuser-dirty\n")
            self.assertEqual(open(os.path.join(workspace.path, "untracked.txt"), "rb").read(), b"user-untracked\n")
            with open(os.path.join(workspace.path, "tracked.txt"), "ab") as handle:
                handle.write(b"worker\n")
            with open(os.path.join(workspace.path, "untracked.txt"), "ab") as handle:
                handle.write(b"worker\n")
            open(os.path.join(workspace.path, "binary.bin"), "wb").write(b"\x00\xffworker")
            os.remove(os.path.join(workspace.path, "delete.txt"))
            patch = workspace.capture()
            self.assertEqual(
                set(patch.paths),
                {"tracked.txt", "untracked.txt", "binary.bin", "delete.txt"},
            )
            self.assertEqual(open(os.path.join(self.root, "tracked.txt"), "rb").read(), b"head\nuser-dirty\n")
            workspace.apply(patch)
        self.assertEqual(open(os.path.join(self.root, "tracked.txt"), "rb").read(), b"head\nuser-dirty\nworker\n")
        self.assertEqual(open(os.path.join(self.root, "untracked.txt"), "rb").read(), b"user-untracked\nworker\n")
        self.assertEqual(open(os.path.join(self.root, "binary.bin"), "rb").read(), b"\x00\xffworker")
        self.assertFalse(os.path.exists(os.path.join(self.root, "delete.txt")))

    def test_execution_caches_are_not_captured(self):
        # 26-07-17 편대 라이브 실측 — .gitignore 없는 프로젝트에서 단위 검증(pytest)이 만든
        # __pycache__/.pytest_cache가 패치에 편입되면 scope 검증·병합이 캐시 때문에 실패한다.
        # 캡처는 quest_log._junk와 같은 기준으로 실행 캐시를 산출물에서 제외한다.
        with UnitWorkspace(self.root, "junk") as workspace:

            def w(rel: str, data: bytes) -> None:
                path = os.path.join(workspace.path, rel)
                os.makedirs(os.path.dirname(path) or workspace.path, exist_ok=True)
                open(path, "wb").write(data)

            w("src/mod.py", b"VALUE = 1\n")
            w("src/__pycache__/mod.cpython-314.pyc", b"\x00cache")
            w(".pytest_cache/v/cache/lastfailed", b"{}")
            w("stray.pyc", b"\x00")
            patch = workspace.capture()
            self.assertEqual(set(patch.paths), {"src/mod.py"})
            workspace.apply(patch)
        self.assertTrue(os.path.exists(os.path.join(self.root, "src/mod.py")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "src/__pycache__")))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".pytest_cache")))

    def test_same_path_user_edit_during_worker_causes_conflict_and_user_wins(self):
        with UnitWorkspace(self.root, 2) as workspace:
            open(os.path.join(workspace.path, "tracked.txt"), "wb").write(b"worker\n")
            patch = workspace.capture()
            self.write("tracked.txt", b"user-raced\n")
            with self.assertRaisesRegex(WorkspaceError, "merge conflict"):
                workspace.apply(patch)
        self.assertEqual(open(os.path.join(self.root, "tracked.txt"), "rb").read(), b"user-raced\n")

    def test_reported_new_ignored_artifact_is_captured_and_merged(self):
        with UnitWorkspace(self.root, "ignored-new") as workspace:
            self.write_in(workspace.path, ".gitignore", b"runtime.env\n")
            self.write_in(workspace.path, "runtime.env", b"E2E_SECRET=BOUND\n")
            # Native adapters may normalize the isolated path back to the canonical project root.
            patch = workspace.capture(extra_paths=[os.path.join(self.root, "runtime.env")])
            self.assertIn("runtime.env", patch.paths)
            workspace.apply(patch)
        self.assertEqual(open(os.path.join(self.root, "runtime.env"), "rb").read(), b"E2E_SECRET=BOUND\n")

    def test_reported_path_through_symlink_alias_stays_inside_workspace(self):
        with UnitWorkspace(self.root, "alias") as workspace:
            alias = os.path.join(self.root, "workspace-alias")
            os.symlink(workspace.path, alias)
            self.assertEqual(
                workspace._reported_rel(os.path.join(alias, "deliverables", "mark.svg")), "deliverables/mark.svg"
            )

    def test_unreported_ignored_artifact_is_not_exported(self):
        with UnitWorkspace(self.root, "ignored-unreported") as workspace:
            self.write_in(workspace.path, ".gitignore", b"runtime.env\n")
            self.write_in(workspace.path, "runtime.env", b"not-reported\n")
            patch = workspace.capture()
            self.assertNotIn("runtime.env", patch.paths)
            workspace.apply(patch)
        self.assertFalse(os.path.exists(os.path.join(self.root, "runtime.env")))

    def test_existing_ignored_user_file_cannot_be_blindly_overwritten(self):
        self.write(".gitignore", b"runtime.env\n")
        self.write("runtime.env", b"USER_SECRET\n")
        with UnitWorkspace(self.root, "ignored-existing") as workspace:
            self.assertFalse(os.path.exists(os.path.join(workspace.path, "runtime.env")))
            ignored = os.path.join(workspace.path, "runtime.env")
            self.write_in(workspace.path, "runtime.env", b"WORKER_VALUE\n")
            with self.assertRaisesRegex(WorkspaceError, "ignored baseline"):
                workspace.capture(extra_paths=[ignored])
        self.assertEqual(open(os.path.join(self.root, "runtime.env"), "rb").read(), b"USER_SECRET\n")

    def test_readonly_manifest_exposes_only_selected_ignored_artifact(self):
        self.write(".gitignore", b"*.env\n")
        self.write("runtime.env", b"E2E_SECRET=BOUND\n")
        self.write("credential.env", b"DO_NOT_EXPOSE\n")
        with UnitWorkspace(self.root, "readonly", include_ignored=["runtime.env"]) as workspace:
            self.assertEqual(
                open(os.path.join(workspace.path, "runtime.env"), "rb").read(),
                b"E2E_SECRET=BOUND\n",
            )
            self.assertFalse(os.path.exists(os.path.join(workspace.path, "credential.env")))

    def test_concurrent_creation_of_new_ignored_artifact_causes_conflict(self):
        with UnitWorkspace(self.root, "ignored-race") as workspace:
            self.write_in(workspace.path, ".gitignore", b"runtime.env\n")
            ignored = os.path.join(workspace.path, "runtime.env")
            self.write_in(workspace.path, "runtime.env", b"WORKER_VALUE\n")
            patch = workspace.capture(extra_paths=[ignored])
            self.write("runtime.env", b"USER_RACED\n")
            with self.assertRaisesRegex(WorkspaceError, "merge conflict"):
                workspace.apply(patch)
        self.assertEqual(open(os.path.join(self.root, "runtime.env"), "rb").read(), b"USER_RACED\n")

    def test_disjoint_unit_patches_merge_but_actual_overlap_is_detectable(self):
        workspaces = [UnitWorkspace(self.root, i) for i in (1, 2)]
        try:
            for workspace in workspaces:
                workspace.__enter__()
            self.write_in(workspaces[0].path, "a.txt", b"a")
            self.write_in(workspaces[1].path, "b.txt", b"b")
            patches = [workspace.capture() for workspace in workspaces]
            self.assertFalse(set(patches[0].paths) & set(patches[1].paths))
            for workspace, patch in zip(workspaces, patches, strict=True):
                workspace.apply(patch)
            self.assertEqual(open(os.path.join(self.root, "a.txt"), "rb").read(), b"a")
            self.assertEqual(open(os.path.join(self.root, "b.txt"), "rb").read(), b"b")
        finally:
            for workspace in workspaces:
                workspace.__exit__(None, None, None)

    def test_artifact_parent_symlink_swap_cannot_write_outside_root(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        os.makedirs(os.path.join(self.root, "nested"))
        patch = UnitPatch(
            unit="race",
            data=b"",
            paths=("nested/secret.env",),
            artifacts=(UnitArtifact("nested/secret.env", "file", b"secret\n", 0o600),),
        )
        real_open = os.open
        swapped = False

        def racing_open(path, flags, *args, dir_fd=None, **kwargs):
            nonlocal swapped
            if path == "nested" and dir_fd is not None and not swapped:
                swapped = True
                os.rmdir(os.path.join(self.root, "nested"))
                os.symlink(outside.name, os.path.join(self.root, "nested"))
            return real_open(path, flags, *args, dir_fd=dir_fd, **kwargs)

        workspace = UnitWorkspace(self.root, "race")
        with mock.patch("asgard.agent.unit_workspace.os.open", side_effect=racing_open):
            with self.assertRaises(WorkspaceError):
                workspace.apply(patch)
        self.assertFalse(os.path.exists(os.path.join(outside.name, "secret.env")))

    def test_malformed_artifact_path_cannot_escape_even_when_patch_paths_are_safe(self):
        outside = os.path.join(os.path.dirname(self.root), "escaped-by-artifact.txt")
        self.addCleanup(lambda: os.path.exists(outside) and os.remove(outside))
        patch = UnitPatch(
            unit="escape",
            data=b"",
            paths=("safe.txt",),
            artifacts=(UnitArtifact("../escaped-by-artifact.txt", "file", b"owned\n", 0o600),),
        )

        with self.assertRaisesRegex(WorkspaceError, "unsafe unit patch path|artifact path"):
            UnitWorkspace(self.root, "escape").apply(patch)

        self.assertFalse(os.path.exists(outside))

    def test_artifact_must_be_declared_in_patch_paths(self):
        patch = UnitPatch(
            unit="undeclared",
            data=b"",
            paths=("safe.txt",),
            artifacts=(UnitArtifact("other.txt", "file", b"hidden\n", 0o600),),
        )

        with self.assertRaisesRegex(WorkspaceError, "artifact path.*patch paths"):
            UnitWorkspace(self.root, "undeclared").apply(patch)

        self.assertFalse(os.path.exists(os.path.join(self.root, "other.txt")))

    def test_control_surface_edits_cannot_ride_a_unit_patch_into_the_repository(self):
        """격리 클론 안에서는 스캐폴드 편집이 허용된다 (readonly_guard 의 harness_owned 갈래).
        되돌려 붙이는 자리에서 막지 않으면 통제 표면 규칙이 클론을 경유해 우회된다."""
        for rel in (
            ".claude/hooks/quest-log.py",
            ".claude/settings.json",
            ".CLAUDE/settings.json",  # macOS·Windows 는 같은 파일을 연다 — 표기로 지나가면 안 된다
            "./.codex/agents/x.toml",
            ".cursor/rules/000-agents.mdc",
            ".codex/agents/asgard-worker.toml",
            ".agents/skills/asgard-skills/SKILL.md",
            ".asgard/asgard-setting-project.json",
            ".git/config",
        ):
            patch = UnitPatch(
                unit="smuggle",
                data=(
                    f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}\n"
                    "@@ -0,0 +1 @@\n+owned\n"
                ).encode(),
                paths=(rel,),
                artifacts=(),
            )
            target = os.path.join(self.root, rel)
            before = self.read_or_none(target)
            with self.assertRaisesRegex(WorkspaceError, "control surface|unsafe unit patch path", msg=rel):
                UnitWorkspace(self.root, "smuggle").apply(patch)
            self.assertEqual(before, self.read_or_none(target), rel)

    def test_ordinary_paths_that_only_start_with_a_control_name_still_apply(self):
        """`.claudecfg` 는 `.claude` 가 아니다 — 세그먼트 경계로 판정한다."""
        from asgard.agent.unit_workspace import _safe_rel

        for rel in (".claudecfg/note.txt", "docs/.claude-notes.md", "src/agents/main.py"):
            self.assertEqual(_safe_rel(self.root, rel), rel)

    def test_isolation_still_opens_in_a_repository_that_has_scaffold_files(self):
        """열거가 `_safe_rel` 로 거절하면 `.claude/` 파일 하나만 있어도 격리가 통째로 못 뜬다 —
        격리가 안 도는 것이 스캐폴드 반입을 막는 방법이 되어 버린다 (26-08-05 교차검토 실측)."""
        self.write(".gitignore", b".claude/settings.local.json\n")
        self.write(".codex/agents/worker.toml", b"scaffold\n")  # 추적 파일 — clone 으로 따라온다
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "scaffold"], cwd=self.root, check=True)
        self.write(".claude/settings.local.json", b'{"local": true}\n')  # 무시 파일
        self.write(".claude/agents/worker.md", b"scaffold\n")  # 미추적 파일

        with UnitWorkspace(self.root, "enter") as workspace:
            for rel in (".claude/settings.local.json", ".claude/agents/worker.md"):
                self.assertFalse(os.path.exists(os.path.join(workspace.path, rel)), rel)
            self.write_in(workspace.path, "src/app.py", b"print('unit work')\n")
            self.write_in(workspace.path, ".claude/agents/worker.md", b"smuggled\n")
            self.write_in(workspace.path, ".codex/agents/worker.toml", b"smuggled\n")
            patch = workspace.capture()

        self.assertIn("src/app.py", patch.paths)
        self.assertEqual([p for p in patch.paths if p.startswith((".claude", ".codex"))], [])
        self.assertNotIn(b".codex/agents/worker.toml", patch.data)
        UnitWorkspace(self.root, "enter").apply(patch)  # 정당한 작업은 살아서 돌아온다
        with open(os.path.join(self.root, "src", "app.py"), "rb") as handle:
            self.assertEqual(handle.read(), b"print('unit work')\n")
        with open(os.path.join(self.root, ".codex", "agents", "worker.toml"), "rb") as handle:
            self.assertEqual(handle.read(), b"scaffold\n")
        with open(os.path.join(self.root, ".claude", "agents", "worker.md"), "rb") as handle:
            self.assertEqual(handle.read(), b"scaffold\n")

    def test_forbidden_roots_match_the_guard_control_surface(self):
        """두 목록이 갈리면 한쪽이 막는 자리를 다른 쪽이 연다 (단일 출처 원칙)."""
        from asgard.agent.unit_workspace import _FORBIDDEN_ROOTS
        from asgard.hooks.readonly_guard import _CONTROL_PATHS

        self.assertEqual(set(_CONTROL_PATHS) - set(_FORBIDDEN_ROOTS), set())

    @staticmethod
    def read_or_none(path: str) -> bytes | None:
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as handle:
            return handle.read()

    @staticmethod
    def write_in(root: str, rel: str, data: bytes) -> None:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        open(path, "wb").write(data)
