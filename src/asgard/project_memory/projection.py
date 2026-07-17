"""프로젝션 — manifest·kernel lock·plan/plan-id·backend sync (artifact 원격 반영)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import stat
import time
from collections.abc import Iterable
from typing import Any

from ..memory_bridge import assert_backend_access, backend_target, server_retain_items
from . import scan
from .records import MAX_ONTOLOGY_VALUE, ONTOLOGY_SCHEMA, ArtifactCandidate
from .scan import _canonical_repo_path

fcntl: Any = None
msvcrt: Any = None
with contextlib.suppress(ImportError):
    import fcntl as _fcntl

    fcntl = _fcntl
with contextlib.suppress(ImportError):  # pragma: no cover - Windows only
    import msvcrt as _msvcrt

    msvcrt = _msvcrt

PROJECTION_MANIFEST = "project-memory-manifest.json"
PROJECTION_VERSION = 3
PROJECTION_LOCK_TTL = 300


def artifact_item(
    candidate: ArtifactCandidate,
    project_id: str,
    source_revision: str,
    *,
    project_uid: str = "",
    binding_id: str = "",
) -> dict:
    path_hash = hashlib.sha256(f"{project_uid}\0{candidate.path}".encode()).hexdigest()[:24]
    symbols = ", ".join(candidate.symbols)[:MAX_ONTOLOGY_VALUE]
    imports = ", ".join(candidate.imports)[:MAX_ONTOLOGY_VALUE]
    header = (
        f"[ProjectArtifact:{candidate.kind}]\n"
        f"Path: {candidate.path}\n"
        f"Revision: {source_revision}\n"
        f"Content-SHA256: {candidate.content_hash}\n"
        f"Symbols: {symbols or '(none)'}\n"
        f"Imports: {imports or '(none)'}\n"
        f"Importance: {candidate.importance}\n\n"
    )
    return {
        "content": header + candidate.content,
        "context": f"asgard project artifact {candidate.kind}",
        "document_id": f"asgard:artifact:{path_hash}",
        "update_mode": "replace",
        "tags": [f"project:{project_id}", "artifact", f"kind:{candidate.kind}", f"importance:{candidate.importance}"],
        "metadata": {
            "source": candidate.path,
            "source_revision": source_revision,
            "content_hash": candidate.content_hash,
            "structural_hash": candidate.structural_hash,
            "ontology_schema": ONTOLOGY_SCHEMA,
            "ontology_type": "source-artifact",
            "origin": "deterministic",
            "extractor": candidate.extractor,
            "symbols": symbols,
            "imports": imports,
            "kind": candidate.kind,
            "importance": candidate.importance,
            "scope": "project",
            "status": "active",
            "confidence": "verified",
            "project_uid": project_uid,
            "binding_id": binding_id,
            "record_schema": "asgard-project-memory-v1",
        },
    }


def _artifact_document_id(path: str, project_uid: str = "") -> str:
    path_hash = hashlib.sha256((project_uid + "\0" + path).encode()).hexdigest()[:24]
    return f"asgard:artifact:{path_hash}"


def _projection_manifest_path(root: str) -> str:
    return os.path.join(root, ".asgard", "state", PROJECTION_MANIFEST)


def load_projection_manifest(root: str) -> dict:
    """Manifest 부재는 bootstrap, 파손은 stale remote 정리를 보존하기 위해 fail-closed."""
    path = _projection_manifest_path(root)
    if not os.path.exists(path):
        return {
            "version": PROJECTION_VERSION,
            "backend": "",
            "project_id": "",
            "project_uid": "",
            "binding_id": "",
            "target_fingerprint": "",
            "last_synced_revision": "",
            "items": {},
        }
    try:
        if os.path.islink(path):
            raise OSError("projection manifest must not be a symlink")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            _validate_projection_file(fd, "projection manifest", path)
        except Exception:
            os.close(fd)
            raise
        with os.fdopen(fd, encoding="utf-8") as source:
            data = json.load(source)
        if isinstance(data, dict) and data.get("version") in (1, 2) and isinstance(data.get("items"), dict):
            # Unbound manifests must never authorize foreign tombstones. Bootstrap from local source instead.
            data = {
                **data,
                "version": PROJECTION_VERSION,
                "backend": "",
                "project_id": str(data.get("bank") or ""),
                "project_uid": "",
                "binding_id": "",
                "target_fingerprint": "",
                "items": {},
            }
            data.pop("bank", None)
        items = data.get("items") if isinstance(data, dict) else None
        if (
            not isinstance(data, dict)
            or data.get("version") != PROJECTION_VERSION
            or not isinstance(items, dict)
            or not all(
                isinstance(data.get(field), str)
                for field in ("backend", "project_id", "project_uid", "binding_id", "target_fingerprint")
            )
        ):
            raise ValueError("unsupported projection manifest")
        for source_path, entry in items.items():
            if (
                not isinstance(source_path, str)
                or _canonical_repo_path(os.path.realpath(root), source_path) != source_path
                or not isinstance(entry, dict)
                or not all(
                    isinstance(entry.get(field), str) and entry[field]
                    for field in ("document_id", "content_hash", "structural_hash", "kind", "status")
                )
                or entry.get("document_id") != _artifact_document_id(source_path, str(data.get("project_uid") or ""))
            ):
                raise ValueError("malformed projection manifest item")
        return data
    except (OSError, AttributeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("project memory projection manifest is corrupt; rebuild explicitly") from exc


def _validate_projection_file(fd: int, label: str, path: str | None = None) -> None:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError(f"{label} must be a singly-linked regular file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise OSError(f"{label} must be owned by the current user")
    if path is not None:
        is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(path))
        path_info = os.stat(path, follow_symlinks=False)
        if stat.S_ISLNK(path_info.st_mode) or is_junction:
            raise OSError(f"{label} must not be a symlink or junction")
        if (path_info.st_dev, path_info.st_ino) != (info.st_dev, info.st_ino):
            raise OSError(f"{label} changed while it was opened")


@contextlib.contextmanager
def _projection_guard(root: str):
    """Kernel-owned advisory lock; process death releases it without stale-file reclamation."""
    lock = _projection_manifest_path(root) + ".lock"
    managed = (os.path.join(root, ".asgard"), os.path.dirname(lock))
    for component in managed:
        is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(component))
        if os.path.lexists(component) and (os.path.islink(component) or is_junction):
            raise OSError(f"unsafe project memory state path: symlink/junction: {component}")
    lock_is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(lock))
    if os.path.lexists(lock) and (os.path.islink(lock) or lock_is_junction):
        raise OSError("projection lock must not be a symlink or junction")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    deadline = time.monotonic() + 5
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock, flags, 0o600)
    acquired = False
    try:
        _validate_projection_file(fd, "projection lock", lock)
        if fcntl is None and msvcrt is None:
            raise OSError("no supported kernel file-lock implementation")
        if msvcrt is not None and os.fstat(fd).st_size == 0:  # pragma: no cover - Windows only
            os.write(fd, b"\0")
        while not acquired:
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:  # pragma: no cover - Windows only
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                acquired = True
            except BlockingIOError, OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("project memory projection lock timeout")
                time.sleep(0.01)
        owner = f"{os.getpid()}:{secrets.token_hex(8)}"
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, owner.encode())
        os.fsync(fd)
        yield
    finally:
        try:
            if acquired:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                else:  # pragma: no cover - Windows only
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)


def _save_projection_manifest(root: str, data: dict) -> None:
    path = _projection_manifest_path(root)
    managed = (os.path.join(root, ".asgard"), os.path.dirname(path))
    for component in managed:
        is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(component))
        if os.path.lexists(component) and (os.path.islink(component) or is_junction):
            raise OSError(f"unsafe project memory state path: symlink/junction: {component}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(tmp, flags, 0o600)
        try:
            _validate_projection_file(fd, "projection manifest temporary file", tmp)
        except Exception:
            os.close(fd)
            raise
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        # Windows cannot open/fsync a directory through this POSIX path. os.replace has already
        # made the manifest visible there; keep the stronger directory durability barrier on POSIX.
        if os.name != "nt":
            directory = os.open(os.path.dirname(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


def projection_plan(
    root: str,
    project_id: str,
    candidates: Iterable[ArtifactCandidate],
    *,
    force: bool = False,
    target: dict | None = None,
) -> dict:
    current = {candidate.path: candidate for candidate in candidates}
    manifest = load_projection_manifest(root)
    target_identity = target or {"engine": "", "project_id": project_id, "fingerprint": ""}
    same_target = (
        manifest.get("backend") == target_identity.get("engine")
        and manifest.get("project_id") == target_identity.get("project_id")
        and manifest.get("project_uid") == target_identity.get("project_uid")
        and manifest.get("binding_id") == target_identity.get("binding_id")
        and manifest.get("target_fingerprint") == target_identity.get("fingerprint")
    )
    previous = manifest.get("items", {}) if same_target else {}
    upserts = [
        candidate
        for path, candidate in sorted(current.items())
        if force
        or previous.get(path, {}).get("content_hash") != candidate.content_hash
        or previous.get(path, {}).get("structural_hash") != candidate.structural_hash
    ]
    removed_paths = sorted(set(previous) - set(current))
    new_by_hash: dict[str, list[str]] = {}
    for path, candidate in current.items():
        if path not in previous:
            new_by_hash.setdefault(candidate.content_hash, []).append(path)
    old_by_hash: dict[str, list[str]] = {}
    for path in removed_paths:
        old_by_hash.setdefault(str(previous[path].get("content_hash") or ""), []).append(path)
    renamed: dict[str, str] = {}
    for path in removed_paths:
        content_hash = str(previous[path].get("content_hash") or "")
        matches = new_by_hash.get(content_hash, [])
        if len(matches) == 1 and len(old_by_hash.get(content_hash, [])) == 1:
            renamed[path] = matches[0]
    return {
        "manifest": manifest,
        "target": target_identity,
        "previous": previous,
        "current": current,
        "upserts": upserts,
        "removed": removed_paths,
        "renamed": renamed,
    }


def projection_plan_id(project_id: str, plan: dict, source_revision: str, *, force: bool = False) -> str:
    """실제로 publish할 전체 payload와 provenance revision을 식별한다."""
    target = plan.get("target") or {}
    project_uid = str(target.get("project_uid") or "")
    binding_id = str(target.get("binding_id") or "")
    items = [
        artifact_item(
            candidate,
            project_id,
            source_revision,
            project_uid=project_uid,
            binding_id=binding_id,
        )
        for candidate in plan["upserts"]
    ]
    items.extend(
        _tombstone_item(
            path,
            plan["previous"][path],
            project_id,
            source_revision,
            plan["renamed"].get(path, ""),
            project_uid=project_uid,
            binding_id=binding_id,
        )
        for path in plan["removed"]
    )
    payload = {
        "target": plan.get("target") or {"engine": "", "project_id": project_id, "fingerprint": ""},
        "mode": "force-all" if force else "manifest-diff",
        "source_revision": source_revision,
        "items": items,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _tombstone_item(
    path: str,
    entry: dict,
    project_id: str,
    revision: str,
    renamed_to: str = "",
    *,
    project_uid: str = "",
    binding_id: str = "",
) -> dict:
    status = "renamed" if renamed_to else "deleted"
    content = f"[ProjectArtifactTombstone]\nPath: {path}\nStatus: {status}\nRevision: {revision}"
    if renamed_to:
        content += f"\nRenamed-To: {renamed_to}"
    metadata = {
        "source": path,
        "source_revision": revision,
        "content_hash": entry.get("content_hash", ""),
        "structural_hash": entry.get("structural_hash", ""),
        "kind": entry.get("kind", "artifact"),
        "scope": "project",
        "origin": "deterministic",
        "status": status,
        "project_uid": project_uid,
        "binding_id": binding_id,
        "record_schema": "asgard-project-memory-v1",
    }
    if renamed_to:
        metadata["renamed_to"] = renamed_to
    return {
        "content": content,
        "context": "asgard project artifact tombstone",
        # The repository-local manifest is cache state, not authority. Never let it redirect a
        # tombstone to an arbitrary stable document ID.
        "document_id": _artifact_document_id(path, project_uid),
        "update_mode": "replace",
        "tags": [f"project:{project_id}", "artifact", f"status:{status}"],
        "metadata": metadata,
    }


def _projection_summary(plan: dict) -> dict:
    return {
        "upserted_count": len(plan["upserts"]),
        "deleted_count": len(plan["removed"]) - len(plan["renamed"]),
        "renamed_count": len(plan["renamed"]),
        "paths": [candidate.path for candidate in plan["upserts"]],
        "removed": [
            {
                "path": path,
                "status": "renamed" if path in plan["renamed"] else "deleted",
                "renamed_to": plan["renamed"].get(path, ""),
            }
            for path in plan["removed"]
        ],
    }


def sync_artifacts(
    root: str,
    cfg: dict,
    candidates: Iterable[ArtifactCandidate],
    *,
    source_revision: str | None = None,
    force: bool = False,
    expected_plan_id: str | None = None,
) -> dict:
    target = backend_target(cfg)
    project_id = str(target["project_id"])
    candidate_list = list(candidates)
    with _projection_guard(root):
        revision = source_revision or scan.source_revision(root)
        for candidate in candidate_list:
            canonical = _canonical_repo_path(os.path.realpath(root), candidate.path)
            if canonical != candidate.path:
                raise ValueError(f"non-canonical project artifact path: {candidate.path}")
            try:
                with open(os.path.join(root, candidate.path), "rb") as source:
                    live_hash = hashlib.sha256(source.read()).hexdigest()
            except OSError as exc:
                raise ValueError(f"project artifact changed after scan: {candidate.path}") from exc
            if live_hash != candidate.content_hash:
                raise ValueError(f"project artifact changed after scan: {candidate.path}")
        plan = projection_plan(root, project_id, candidate_list, force=force, target=target)
        actual_plan_id = projection_plan_id(project_id, plan, revision, force=force)
        if expected_plan_id is not None and not secrets.compare_digest(expected_plan_id, actual_plan_id):
            raise ValueError("project memory sync plan changed; preview again")
        project_uid = str(target.get("project_uid") or "")
        binding_id = str(target.get("binding_id") or "")
        items = [
            artifact_item(
                candidate,
                project_id,
                revision,
                project_uid=project_uid,
                binding_id=binding_id,
            )
            for candidate in plan["upserts"]
        ]
        items.extend(
            _tombstone_item(
                path,
                plan["previous"][path],
                project_id,
                revision,
                plan["renamed"].get(path, ""),
                project_uid=project_uid,
                binding_id=binding_id,
            )
            for path in plan["removed"]
        )
        if items:
            result = server_retain_items(cfg, items)
        else:
            assert_backend_access(cfg)
            result = {"success": True}
        summary = _projection_summary(plan)
        if result.get("success") is not True:
            return {
                **result,
                **summary,
                "items_count": len(items),
                "plan_id": actual_plan_id,
            }
        manifest_items = {
            candidate.path: {
                "document_id": _artifact_document_id(candidate.path, project_uid),
                "content_hash": candidate.content_hash,
                "structural_hash": candidate.structural_hash,
                "extractor": candidate.extractor,
                "kind": candidate.kind,
                "status": "active",
            }
            for candidate in candidate_list
        }
        _save_projection_manifest(
            root,
            {
                "version": PROJECTION_VERSION,
                "backend": target["engine"],
                "project_id": project_id,
                "project_uid": project_uid,
                "binding_id": binding_id,
                "target_fingerprint": target["fingerprint"],
                "last_synced_revision": revision,
                "items": manifest_items,
            },
        )
        return {
            **result,
            **summary,
            "success": True,
            "items_count": len(items),
            "plan_id": actual_plan_id,
        }
