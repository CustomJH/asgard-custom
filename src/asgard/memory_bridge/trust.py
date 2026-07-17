"""machine-local backend trust 저장소 + 원격 ownership binding 검증 (fail-closed)."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time

from ..project_memory_backends import ProjectMemoryBinding, get_backend, parse_settings
from .client import backend_target

TRUST_NAME = "project-memory-trust.json"
TRUST_LOCK_WAIT = 5.0
TRUST_LOCK_STALE = 30.0


def _trust_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".asgard", TRUST_NAME)


def _load_trust() -> dict:
    try:
        with open(_trust_path(), encoding="utf-8") as source:
            value = json.load(source)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def is_backend_trusted(cfg: dict) -> bool:
    try:
        target = backend_target(cfg)
    except Exception:
        return False
    if not target["project_uid"] or not target["binding_id"]:
        return False
    entry = _load_trust().get(target["fingerprint"])
    return (
        isinstance(entry, dict)
        and entry.get("engine") == target["engine"]
        and entry.get("project_id") == target["project_id"]
        and entry.get("project_uid") == target["project_uid"]
        and entry.get("binding_id") == target["binding_id"]
    )


def expected_backend_binding(cfg: dict) -> ProjectMemoryBinding:
    settings = parse_settings(cfg)
    if not settings.project_uid or not settings.binding_id:
        raise PermissionError("project memory binding is not configured; reconnect or explicitly adopt the bank")
    return ProjectMemoryBinding(
        project_uid=settings.project_uid,
        binding_id=settings.binding_id,
        project_id=settings.project_id,
    )


def verify_backend_binding(cfg: dict, *, backend=None) -> ProjectMemoryBinding:
    """Read the reserved control document exactly and fail closed on drift."""
    expected = expected_backend_binding(cfg)
    owns_backend = backend is None
    adapter = get_backend(cfg) if owns_backend else backend
    try:
        observed = adapter.read_binding()
        if observed is None:
            raise PermissionError("project memory binding is missing from the selected namespace")
        if (
            observed.project_id != expected.project_id
            or not secrets.compare_digest(observed.project_uid, expected.project_uid)
            or not secrets.compare_digest(observed.binding_id, expected.binding_id)
        ):
            raise PermissionError("foreign or drifted project memory binding")
        return observed
    finally:
        if owns_backend:
            with contextlib.suppress(Exception):
                adapter.close()


def assert_backend_access(cfg: dict) -> ProjectMemoryBinding:
    """Require both machine-local target trust and the exact remote ownership binding."""
    if not is_backend_trusted(cfg):
        raise PermissionError("project memory backend target is not trusted")
    return verify_backend_binding(cfg)


@contextlib.contextmanager
def _trust_guard():
    """machine-local trust read-modify-write를 프로세스 간 직렬화한다."""
    path = _trust_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    lock_path = f"{path}.lock"
    deadline = time.monotonic() + TRUST_LOCK_WAIT
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                stale = time.time() - os.path.getmtime(lock_path) > TRUST_LOCK_STALE
            except OSError:
                stale = False
            if stale:
                with contextlib.suppress(OSError):
                    os.remove(lock_path)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for project-memory trust lock")
            time.sleep(0.01)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.remove(lock_path)


def trust_backend(cfg: dict) -> str:
    """Explicit connect가 승인한 backend target을 repo 밖 machine-local store에 기록한다."""
    verify_backend_binding(cfg)
    target = backend_target(cfg)
    path = _trust_path()
    with _trust_guard():
        data = _load_trust()
        data[target["fingerprint"]] = {
            "engine": target["engine"],
            "project_id": target["project_id"],
            "project_uid": target["project_uid"],
            "binding_id": target["binding_id"],
            "trusted_at": int(time.time()),
        }
        tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as output:
                json.dump(data, output, ensure_ascii=False, sort_keys=True, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp)
    return path
