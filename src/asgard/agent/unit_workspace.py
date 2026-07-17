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


# quest_log._junk 와 동일 유지 (단일 출처 원칙) — 실행 캐시는 단위 산출물이 아니다.
# .gitignore 없는 프로젝트에서 단위 검증(pytest 류)이 만든 __pycache__/.pytest_cache 가
# 캡처 패치에 편입되면 scope 검증·병합이 캐시 때문에 실패한다 (26-07-17 편대 라이브 실측).
_JUNK_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox", "node_modules", ".venv"}


def _junk_rel(p: str) -> bool:
    return p.endswith((".pyc", ".pyo")) or any(seg in _JUNK_DIRS for seg in p.split("/"))


@dataclass(frozen=True)
class UnitArtifact:
    path: str
    kind: str
    payload: bytes | str
    mode: int


@dataclass(frozen=True)
class UnitPatch:
    unit: str
    data: bytes
    paths: tuple[str, ...]
    artifacts: tuple[UnitArtifact, ...] = ()


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


def _open_artifact_parent(root: str, rel: str) -> tuple[int, str, list[tuple[int, str]]]:
    """Open/create an artifact parent without following a swappable symlink component."""
    rel = _safe_rel(root, rel)
    required = ("O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, flag) for flag in required):
        raise WorkspaceError("platform lacks symlink-safe directory open support")
    parts = Path(rel).parts
    if not parts or parts[-1] in {"", ".", ".."}:
        raise WorkspaceError(f"unsafe artifact path: {rel}")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    current = os.open(os.path.realpath(root), flags)
    created: list[tuple[int, str]] = []
    try:
        for component in parts[:-1]:
            try:
                child = os.open(component, flags, dir_fd=current)
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=current)
                created.append((os.dup(current), component))
                child = os.open(component, flags, dir_fd=current)
            os.close(current)
            current = child
        return current, parts[-1], created
    except Exception as exc:
        os.close(current)
        for parent_fd, name in reversed(created):
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError:
                pass
            os.close(parent_fd)
        if isinstance(exc, WorkspaceError):
            raise
        raise WorkspaceError(f"artifact parent is not a stable project directory: {rel}") from exc


class UnitWorkspace:
    def __init__(self, root: str, unit: str | int, *, include_ignored: list[str] | tuple[str, ...] = ()):
        self.root = os.path.realpath(root)
        self.unit = str(unit)
        self.include_ignored = tuple(str(path) for path in include_ignored)
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.path = ""
        self._ignored_at_entry: set[str] = set()

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
        ignored = _git(
            self.root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
        ).stdout
        self._ignored_at_entry = set()
        for item in ignored.split(b"\0"):
            if not item:
                continue
            raw_rel = os.fsdecode(item).replace(os.sep, "/")
            if raw_rel == ".asgard" or raw_rel.startswith(".asgard/"):
                continue
            self._ignored_at_entry.add(_safe_rel(self.root, raw_rel))
        # A read-only Verifier may need quest-changed ignored artifacts, but must not receive
        # every pre-existing ignored credential. Callers provide the canonical changed-path
        # manifest; only paths that Git currently confirms as ignored are copied.
        for raw_rel in self.include_ignored:
            normalized = os.path.normpath(raw_rel).replace(os.sep, "/")
            if normalized not in self._ignored_at_entry:
                continue
            rel = _safe_rel(self.root, normalized)
            source = os.path.join(self.root, rel)
            destination = os.path.join(self.path, rel)
            info = os.lstat(source)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            if stat.S_ISREG(info.st_mode):
                shutil.copy2(source, destination, follow_symlinks=False)
            elif stat.S_ISLNK(info.st_mode):
                target = os.readlink(source)
                resolved = os.path.realpath(
                    target if os.path.isabs(target) else os.path.join(os.path.dirname(source), target)
                )
                if os.path.commonpath((self.root, resolved)) != self.root:
                    raise WorkspaceError(f"included ignored symlink escapes project root: {rel}")
                os.symlink(target, destination)
            else:
                raise WorkspaceError(f"unsupported included ignored artifact type: {rel}")
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

    def _reported_rel(self, raw_path: str) -> str:
        raw_path = os.path.expanduser(str(raw_path))
        candidate = os.path.realpath(raw_path if os.path.isabs(raw_path) else os.path.join(self.path, raw_path))
        for base in (self.path, self.root):
            # macOS의 /var → /private/var 같은 경로 별칭을 동일 물리 경로로 비교한다.
            base_abs = os.path.realpath(base)
            try:
                if os.path.commonpath((base_abs, candidate)) == base_abs:
                    return _safe_rel(self.root, os.path.relpath(candidate, base_abs))
            except ValueError:
                continue
        raise WorkspaceError(f"reported write escapes unit workspace: {raw_path}")

    def capture(self, *, extra_paths: list[str] | tuple[str, ...] = ()) -> UnitPatch:
        if not self.path:
            raise WorkspaceError("workspace is not active")
        # Intent-to-add only genuinely new files. `git add -N .` also refreshes deleted
        # baseline entries on some Git versions and can hide Worker deletions.
        untracked = _git(self.path, "ls-files", "--others", "--exclude-standard", "-z").stdout
        for encoded in untracked.split(b"\0"):
            if encoded and not _junk_rel(os.fsdecode(encoded).replace(os.sep, "/")):
                _git(self.path, "add", "-N", "--", os.fsdecode(encoded))
        names = _git(self.path, "diff", "--name-only", "-z").stdout
        git_paths = {_safe_rel(self.root, os.fsdecode(item)) for item in names.split(b"\0") if item}
        patch = _git(self.path, "diff", "--binary", "--full-index", "--no-ext-diff").stdout
        artifacts: list[UnitArtifact] = []
        for raw_path in extra_paths:
            rel = self._reported_rel(raw_path)
            if rel in git_paths:
                continue
            # Only explicitly reported paths that Git excludes are exported outside the patch.
            # This keeps ignored credentials absent from the Worker clone and prevents arbitrary
            # baseline files from being smuggled through the side channel.
            if _git(self.path, "check-ignore", "-q", "--", rel, check=False).returncode != 0:
                continue
            if rel in self._ignored_at_entry:
                raise WorkspaceError(f"ignored baseline path is unavailable to isolated Worker: {rel}")
            source = os.path.join(self.path, rel)
            try:
                info = os.lstat(source)
            except FileNotFoundError:
                continue
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISREG(info.st_mode):
                artifact = UnitArtifact(rel, "file", Path(source).read_bytes(), mode)
            elif stat.S_ISLNK(info.st_mode):
                target = os.readlink(source)
                resolved = os.path.realpath(
                    target if os.path.isabs(target) else os.path.join(os.path.dirname(source), target)
                )
                if os.path.commonpath((os.path.realpath(self.path), resolved)) != os.path.realpath(self.path):
                    raise WorkspaceError(f"ignored artifact symlink escapes unit workspace: {rel}")
                artifact = UnitArtifact(rel, "symlink", target, mode)
            else:
                raise WorkspaceError(f"unsupported ignored artifact type: {rel}")
            artifacts.append(artifact)
            git_paths.add(rel)
        return UnitPatch(self.unit, patch, tuple(sorted(git_paths)), tuple(sorted(artifacts, key=lambda a: a.path)))

    def apply(self, patch: UnitPatch) -> None:
        if not patch.data and not patch.artifacts:
            return
        safe_paths = tuple(_safe_rel(self.root, rel) for rel in patch.paths)
        safe_path_set = set(safe_paths)
        safe_artifacts: list[UnitArtifact] = []
        for artifact in patch.artifacts:
            rel = _safe_rel(self.root, artifact.path)
            if rel not in safe_path_set:
                raise WorkspaceError(f"artifact path is absent from patch paths: {artifact.path}")
            safe_artifacts.append(UnitArtifact(rel, artifact.kind, artifact.payload, artifact.mode))
        if patch.data:
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
        artifact_paths = {artifact.path for artifact in safe_artifacts}

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
        artifact_targets: list[tuple[UnitArtifact, int, str]] = []
        created_dirs: list[tuple[int, str]] = []
        try:
            if patch.data:
                _git(self.root, "apply", "--binary", "--whitespace=nowarn", input_data=patch.data)
            for artifact in safe_artifacts:
                parent_fd, name, created = _open_artifact_parent(self.root, artifact.path)
                created_dirs.extend(created)
                try:
                    if artifact.kind == "file":
                        fd = os.open(
                            name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            artifact.mode or 0o600,
                            dir_fd=parent_fd,
                        )
                        with os.fdopen(fd, "wb") as handle:
                            handle.write(artifact.payload if isinstance(artifact.payload, bytes) else b"")
                            os.fchmod(handle.fileno(), artifact.mode)
                    elif artifact.kind == "symlink":
                        os.symlink(str(artifact.payload), name, dir_fd=parent_fd)
                    else:
                        raise WorkspaceError(f"unsupported ignored artifact type: {artifact.path}")
                except FileExistsError as exc:
                    os.close(parent_fd)
                    raise WorkspaceError(
                        f"unit {patch.unit} merge conflict: ignored artifact already exists: {artifact.path}"
                    ) from exc
                except Exception:
                    os.close(parent_fd)
                    raise
                artifact_targets.append((artifact, parent_fd, name))
        except Exception:
            for _, parent_fd, name in reversed(artifact_targets):
                try:
                    os.unlink(name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
            for rel, (kind, payload, mode) in backups.items():
                if rel in artifact_paths:
                    continue
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
            for parent_fd, name in reversed(created_dirs):
                try:
                    os.rmdir(name, dir_fd=parent_fd)
                except OSError:
                    pass
            raise
        finally:
            for _, parent_fd, _ in artifact_targets:
                os.close(parent_fd)
            for parent_fd, _ in created_dirs:
                os.close(parent_fd)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
        self.path = ""
