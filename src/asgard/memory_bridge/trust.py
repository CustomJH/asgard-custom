"""machine-local backend trust 저장소 + 원격 ownership binding 검증 (fail-closed)."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from typing import TypeGuard

from ..project_memory_backends import ProjectMemoryBinding, get_backend, parse_settings
from .client import backend_target

TRUST_NAME = "project-memory-trust.json"
TRUST_LOCK_WAIT = 5.0
TRUST_LOCK_STALE = 30.0

# 이 기계가 한 번 승인해야 켜지는 손잡이들 — 리포 설정은 **제안**이고 여기 이름이 없으면 꺼진 것이다.
# 왜 trust store에 얹는가: 스코프 단위를 새로 만들면 신뢰가 두 축으로 갈라진다. 승인의 대상은
# 이미 있는 그 target(engine·project_id·project_uid·binding_id의 fingerprint)이지 다른 무엇이 아니다.
GRANT_AUTOSAVE = "autosave"
GRANT_AUTO_RETAIN_TURNS = "auto_retain_turns"
MACHINE_GRANTS = (GRANT_AUTOSAVE, GRANT_AUTO_RETAIN_TURNS)


def _trust_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".asgard", TRUST_NAME)


def _load_trust() -> dict:
    try:
        with open(_trust_path(), encoding="utf-8") as source:
            value = json.load(source)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _trusted_entry(cfg: dict) -> dict | None:
    """이 기계가 신뢰한다고 적어 둔 target 항목 — 신원 네 값이 다 맞을 때만 준다 (아니면 None).

    `is_backend_trusted`와 grant 조회가 같은 판정을 쓰게 하려고 갈라냈다. 판정이 두 벌이면
    한쪽만 느슨해지는 날이 온다."""
    try:
        target = backend_target(cfg)
    except Exception:
        return None
    if not target["project_uid"] or not target["binding_id"]:
        return None
    entry = _load_trust().get(target["fingerprint"])
    return entry if _entry_matches(entry, target) else None


def _entry_matches(entry: object, target: dict) -> TypeGuard[dict]:
    return isinstance(entry, dict) and all(
        entry.get(key) == target[key] for key in ("engine", "project_id", "project_uid", "binding_id")
    )


def is_backend_trusted(cfg: dict) -> bool:
    return _trusted_entry(cfg) is not None


def machine_grants(cfg: dict) -> tuple[str, ...]:
    """이 기계가 이 backend target에 준 허가 이름들 — 정렬된 튜플, 없으면 빈 튜플.

    신뢰되지 않은 target에는 허가가 있을 수 없다 (fail-closed): trust 항목이 곧 허가의 자리다."""
    entry = _trusted_entry(cfg)
    if entry is None:
        return ()
    raw = entry.get("grants")
    if not isinstance(raw, dict):
        return ()
    return tuple(name for name in MACHINE_GRANTS if isinstance(raw.get(name), dict))


def has_machine_grant(cfg: dict, grant: str) -> bool:
    """이 기계가 그 허가를 줬는가 — 없으면 False (리포 설정이 뭐라 적었든)."""
    return grant in machine_grants(cfg)


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


def _write_trust(data: dict) -> str:
    """trust store 통째 교체 — 임시 이름은 랜덤, 자리 바꾸기는 원자적."""
    path = _trust_path()
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


def trust_backend(cfg: dict) -> str:
    """Explicit connect가 승인한 backend target을 repo 밖 machine-local store에 기록한다.

    이미 준 허가(grants)는 같은 target을 다시 연결해도 남긴다 — fingerprint가 신원 네 값을
    다 덮으므로 같은 fingerprint는 같은 대상이고, 재연결은 승인의 철회가 아니다."""
    verify_backend_binding(cfg)
    target = backend_target(cfg)
    with _trust_guard():
        data = _load_trust()
        entry = {
            "engine": target["engine"],
            "project_id": target["project_id"],
            "project_uid": target["project_uid"],
            "binding_id": target["binding_id"],
            "trusted_at": int(time.time()),
        }
        previous = data.get(target["fingerprint"])
        if isinstance(previous, dict) and isinstance(previous.get("grants"), dict):
            kept = {name: value for name, value in previous["grants"].items() if name in MACHINE_GRANTS}
            if kept:
                entry["grants"] = kept
        data[target["fingerprint"]] = entry
        return _write_trust(data)


def _set_machine_grant(cfg: dict, grant: str, *, granted: bool) -> dict:
    """허가 한 건을 켜거나 끈다 — 반환 형상은 grant/revoke 공통 (CLI가 그대로 읽는다)."""
    if grant not in MACHINE_GRANTS:
        raise ValueError(f"unknown machine grant: {grant}")
    target = backend_target(cfg)
    with _trust_guard():
        data = _load_trust()
        entry = data.get(target["fingerprint"])
        if not _entry_matches(entry, target):
            raise PermissionError("project memory backend target is not trusted")
        raw = entry.get("grants")
        grants = {
            name: value
            for name, value in (raw if isinstance(raw, dict) else {}).items()
            if name in MACHINE_GRANTS and isinstance(value, dict)
        }
        was = grant in grants
        granted_at: int | None = None
        if granted:
            # 이미 있던 허가를 다시 주는 것은 새 승인이 아니다 — 처음 준 때를 그대로 둔다.
            granted_at = (int(grants[grant].get("granted_at") or 0) if was else 0) or int(time.time())
            grants[grant] = {"granted_at": granted_at}
        else:
            grants.pop(grant, None)
        if grants:
            entry["grants"] = grants
        else:
            entry.pop("grants", None)
        data[target["fingerprint"]] = entry
        path = _write_trust(data)
    return {
        "grant": grant,
        "granted": granted,
        "changed": was != granted,
        "granted_at": granted_at,
        "engine": target["engine"],
        "project_id": target["project_id"],
        "fingerprint": target["fingerprint"],
        "path": path,
    }


def grant_machine_approval(cfg: dict, grant: str) -> dict:
    """이 기계에서 그 손잡이를 켜도 좋다는 사람의 허가를 적는다 (repo 설정은 제안일 뿐이다).

    이미 신뢰된 target에만 붙는다 — 신뢰가 없으면 PermissionError. 원격 왕복은 하지 않는다:
    신뢰는 `asgard memory connect`가 이미 binding까지 확인하고 준 것이고, 허가는 그 위에 얹는
    두 번째 사람 손짓이다. 모르는 허가 이름은 ValueError."""
    return _set_machine_grant(cfg, grant, granted=True)


def revoke_machine_approval(cfg: dict, grant: str) -> dict:
    """허가를 거둔다 — 신뢰 자체는 남기고 그 손잡이만 끈다. 반환 형상은 grant와 같다."""
    return _set_machine_grant(cfg, grant, granted=False)
