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
        # __pycache__/.pytest_cache 가 패치에 편입되면 scope 검증·병합이 캐시 때문에 실패한다.
        # 캡처는 quest_log._junk 와 같은 기준으로 실행 캐시를 산출물에서 제외한다.
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

    @staticmethod
    def write_in(root: str, rel: str, data: bytes) -> None:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        open(path, "wb").write(data)
