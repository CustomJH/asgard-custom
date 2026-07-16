import os
import subprocess
import tempfile
import unittest

from asgard.agent.unit_workspace import UnitWorkspace, WorkspaceError


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

    def test_same_path_user_edit_during_worker_causes_conflict_and_user_wins(self):
        with UnitWorkspace(self.root, 2) as workspace:
            open(os.path.join(workspace.path, "tracked.txt"), "wb").write(b"worker\n")
            patch = workspace.capture()
            self.write("tracked.txt", b"user-raced\n")
            with self.assertRaisesRegex(WorkspaceError, "merge conflict"):
                workspace.apply(patch)
        self.assertEqual(open(os.path.join(self.root, "tracked.txt"), "rb").read(), b"user-raced\n")

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

    @staticmethod
    def write_in(root: str, rel: str, data: bytes) -> None:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        open(path, "wb").write(data)
