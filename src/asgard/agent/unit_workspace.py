"""Per-unit isolated Git workspace and deterministic patch merge.

The canonical project root owns Quest state and final verification. Workers run in an
independent local clone seeded with the canonical tracked-dirty and untracked state.
Only the delta from that seed is captured and merged back.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class UnitPatch:
    unit: str
    data: bytes
    paths: tuple[str, ...]


def _git(root: str, *args: str, input_data: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", root, *args],
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode:
        raise WorkspaceError(proc.stderr.decode("utf-8", "replace").strip() or "git command failed")
    return proc


def _safe_rel(root: str, rel: str) -> str:
    normalized = os.path.normpath(rel).replace(os.sep, "/")
    if normalized in ("", ".") or normalized == ".git" or normalized == ".asgard":
        raise WorkspaceError(f"unsafe unit patch path: {rel}")
    if normalized.startswith("../") or normalized.startswith(".git/") or normalized.startswith(".asgard/"):
        raise WorkspaceError(f"unsafe unit patch path: {rel}")
    absolute = os.path.abspath(os.path.join(root, normalized))
    if os.path.commonpath((os.path.abspath(root), absolute)) != os.path.abspath(root):
        raise WorkspaceError(f"unit patch escapes project root: {rel}")
    return normalized


class UnitWorkspace:
    def __init__(self, root: str, unit: object):
        self.root = os.path.abspath(root)
        self.unit = str(unit)
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.path = ""

    def __enter__(self) -> "UnitWorkspace":
        if _git(self.root, "rev-parse", "--verify", "HEAD", check=False).returncode:
            raise WorkspaceError("unit isolation requires a Git repository with HEAD")
        self._tmp = tempfile.TemporaryDirectory(prefix=f"asgard-unit-{self.unit}-")
        self.path = os.path.join(self._tmp.name, "repo")
        _git(os.getcwd(), "clone", "--quiet", "--local", "--no-hardlinks", self.root, self.path)

        # Clone contains HEAD only. Overlay tracked staged/unstaged changes as one binary patch.
        dirty = _git(self.root, "diff", "--binary", "--full-index", "HEAD").stdout
        if dirty:
            _git(self.path, "apply", "--binary", "--whitespace=nowarn", input_data=dirty)

        # Preserve untracked user files, but never copy ignored credentials/caches or Asgard runtime state.
        raw = _git(self.root, "ls-files", "--others", "--exclude-standard", "-z").stdout
        for encoded in raw.split(b"\0"):
            if not encoded:
                continue
            raw_rel = os.fsdecode(encoded).replace(os.sep, "/")
            if raw_rel == ".asgard" or raw_rel.startswith(".asgard/"):
                continue
            rel = _safe_rel(self.root, raw_rel)
            src = os.path.join(self.root, rel)
            dst = os.path.join(self.path, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.islink(src):
                os.symlink(os.readlink(src), dst)
            elif os.path.isdir(src):
                shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst, follow_symlinks=False)

        # This clone-local index is the exact Worker baseline, including user dirty/untracked state.
        _git(self.path, "add", "-A", "--", ".")
        return self

    def capture(self) -> UnitPatch:
        if not self.path:
            raise WorkspaceError("workspace is not active")
        # Intent-to-add only genuinely new files. `git add -N .` also refreshes deleted
        # baseline entries on some Git versions and can hide Worker deletions.
        untracked = _git(self.path, "ls-files", "--others", "--exclude-standard", "-z").stdout
        for encoded in untracked.split(b"\0"):
            if encoded:
                _git(self.path, "add", "-N", "--", os.fsdecode(encoded))
        names = _git(self.path, "diff", "--name-only", "-z").stdout
        paths = tuple(_safe_rel(self.root, os.fsdecode(item)) for item in names.split(b"\0") if item)
        patch = _git(self.path, "diff", "--binary", "--full-index", "--no-ext-diff").stdout
        return UnitPatch(self.unit, patch, paths)

    def apply(self, patch: UnitPatch) -> None:
        if not patch.data:
            return
        safe_paths = tuple(_safe_rel(self.root, rel) for rel in patch.paths)
        checked = _git(
            self.root,
            "apply",
            "--check",
            "--binary",
            "--whitespace=nowarn",
            input_data=patch.data,
            check=False,
        )
        if checked.returncode:
            reason = checked.stderr.decode("utf-8", "replace").strip()
            raise WorkspaceError(f"unit {patch.unit} merge conflict: {reason}")

        backups: dict[str, tuple[str, bytes | str | None, int]] = {}
        for rel in safe_paths:
            target = os.path.join(self.root, rel)
            try:
                mode = stat.S_IMODE(os.lstat(target).st_mode)
                if os.path.islink(target):
                    backups[rel] = ("symlink", os.readlink(target), mode)
                elif os.path.isfile(target):
                    backups[rel] = ("file", Path(target).read_bytes(), mode)
                else:
                    backups[rel] = ("other", None, mode)
            except FileNotFoundError:
                backups[rel] = ("missing", None, 0)
        try:
            _git(self.root, "apply", "--binary", "--whitespace=nowarn", input_data=patch.data)
        except Exception:
            for rel, (kind, payload, mode) in backups.items():
                target = os.path.join(self.root, rel)
                if os.path.lexists(target):
                    if os.path.isdir(target) and not os.path.islink(target):
                        shutil.rmtree(target)
                    else:
                        os.remove(target)
                if kind == "file":
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    Path(target).write_bytes(payload if isinstance(payload, bytes) else b"")
                    os.chmod(target, mode)
                elif kind == "symlink":
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    os.symlink(str(payload), target)
            raise

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
        self.path = ""
