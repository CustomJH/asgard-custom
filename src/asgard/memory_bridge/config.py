"""설정 탐색·기록 + 2단 retain 승인 저장소 (pending·consumed·승인 키)."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import stat
import subprocess
import time
from collections.abc import Mapping

from ..project_memory_backends import parse_settings
from .trust import _trust_guard

CONFIG_NAME = "memory-server.json"
PROJECT_SECTION = "project_memory"
LEGACY_PROJECT_SECTION = "memory"  # 구 섹션 키 — 글로벌 개인 메모리 섹션과 동명이라 개명됨
PENDING_NAME = "memory-pending.json"
PENDING_TTL = 3600  # 승인 id 만료 (초) — 승인과 실행 사이가 길면 재계획이 맞다
PENDING_LOCK_STALE = 60  # pending JSON lock은 짧은 local critical section에만 유지된다


# ── 설정 탐색 — cwd 에서 상향 (모노레포·서브디렉토리 실행 대응) ─────────────────────


class ProjectMemoryConfigError(ValueError):
    """A project-memory config file is present but malformed."""


def _binding_sidecar_path(root: str) -> str:
    return os.path.join(root, ".asgard", "memory", "binding.json")


def read_binding_sidecar(root: str) -> dict:
    """바인딩 사이드카(.asgard/memory/binding.json) — 아스가르드가 관리하는 내부 신원.

    project_uid·binding_id 는 사용자가 읽고 고치는 설정이 아니라 connect 가 발급·검증하는
    소유권 마커다 (오딘 지적 26-07-23: 설정 파일에는 사람이 만지는 키만). git 추적으로 팀과
    공유된다. 깨진 파일은 없음과 동일 (fail-safe)."""
    try:
        with open(_binding_sidecar_path(root), encoding="utf-8") as source:
            raw = json.load(source)
        if not isinstance(raw, dict):
            return {}
        return {key: str(raw.get(key) or "").strip() for key in ("project_id", "project_uid", "binding_id")}
    except Exception:
        return {}


def _write_binding_sidecar(root: str, project_id: str, project_uid: str, binding_id: str) -> None:
    path = _binding_sidecar_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "_comment": "asgard memory connect 가 관리하는 프로젝트 메모리 소유권 마커 — 직접 수정 금지",
        "project_id": project_id,
        "project_uid": project_uid,
        "binding_id": binding_id,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as sink:
        json.dump(payload, sink, ensure_ascii=False, indent=1)
        sink.write("\n")
    os.replace(tmp, path)


def project_memory_disabled(section: Mapping[str, object] | None) -> bool:
    """`enabled` 토글 — 명시적 false/off/0 만 비활성. 부재·그 외 값 = 활성 (기본 on)."""
    if not section:
        return False
    value = section.get("enabled")
    if value is None or value is True:
        return False
    return str(value).strip().lower() in ("false", "off", "0")


def project_memory_section(project: dict) -> dict | None:
    """통합 설정에서 프로젝트 메모리 섹션을 고른다 — project_memory 우선, 구 memory 폴백.

    `_` 로 시작하는 키는 스캐폴드가 심는 주석·입력 예제(_comment·_example)라 설정으로 치지
    않는다. 실 설정 키가 하나도 없으면 None — opt-in 미연결(공란 시드) 상태로, 깨진 설정과
    구별된다 (미연결 시드를 malformed 로 읽으면 fresh init 이 doctor 에서 빨갛게 뜬다)."""
    for name in (PROJECT_SECTION, LEGACY_PROJECT_SECTION):
        raw = project.get(name)
        if isinstance(raw, dict):
            section = {key: value for key, value in raw.items() if not str(key).startswith("_")}
            if section:
                return section
    return None


def find_config(start: str | None = None, *, strict: bool = False) -> tuple[str, dict] | None:
    """프로젝트 메모리 섹션(project_memory — engine·project_id)을 위로 걸어가며 탐색한다.

    구 server·bank 설정은 Hindsight로 정규화한다. 반환 dict에는 전환 기간 동안 기존 호출부를
    위한 server·bank alias도 제공하지만, 저장 정본은 engine·endpoint·project_id다.
    깨진 JSON·필수 키 누락은 없음과 동일 (fail-safe — 툴 미노출이 오동작보다 낫다)."""
    from ..settings import PROJECT_FILE

    d = os.path.realpath(start or os.getcwd())
    while True:
        asg = os.path.join(d, ".asgard")
        project_file = os.path.join(asg, PROJECT_FILE)
        legacy_file = os.path.join(asg, CONFIG_NAME)
        if os.path.isfile(project_file) or os.path.isfile(legacy_file):
            try:
                from ..settings import load_project

                if strict and os.path.isfile(project_file):
                    with open(project_file, encoding="utf-8") as source:
                        raw = json.load(source)
                    if not isinstance(raw, dict):
                        raise ValueError("project settings must be a JSON object")
                    if project_memory_section(raw) is None:
                        return None
                    if project_memory_disabled(project_memory_section(raw)):
                        return None
                elif strict and os.path.isfile(legacy_file):
                    with open(legacy_file, encoding="utf-8") as source:
                        raw = json.load(source)
                    if not isinstance(raw, dict):
                        raise ValueError("legacy project-memory settings must be a JSON object")
                project = load_project(d)
                mem = project_memory_section(project)
                if mem is None or project_memory_disabled(mem):
                    return None
                # 신원(uid·binding)은 사이드카가 정본 — 설정 파일 잔존 값(구 스키마)이 있으면 그 값 우선.
                sidecar = read_binding_sidecar(d)
                mem = dict(mem)
                for key in ("project_uid", "binding_id"):
                    if not str(mem.get(key) or "").strip() and sidecar.get(key):
                        mem[key] = sidecar[key]
                settings = parse_settings(mem)
                normalized = dict(mem)
                normalized.update(
                    {
                        "engine": settings.engine,
                        "project_id": settings.project_id,
                        "endpoint": settings.endpoint,
                        "timeout": settings.timeout,
                        "options": dict(settings.options),
                        "project_uid": settings.project_uid,
                        "binding_id": settings.binding_id,
                        # 기존 정책/manifest 코드가 쓰는 호환 alias. backend에는 canonical key가 전달된다.
                        "bank": settings.project_id,
                        "server": settings.endpoint,
                    }
                )
                return d, normalized
            except Exception as exc:
                if strict:
                    raise ProjectMemoryConfigError(f"malformed project-memory configuration at {asg}") from exc
            return None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def write_config(
    root: str,
    endpoint: str,
    project_id: str,
    *,
    engine: str = "hindsight",
    timeout: int | None = None,
    options: dict | None = None,
    project_uid: str = "",
    binding_id: str = "",
) -> str:
    from ..settings import save_project

    config = {
        "engine": engine.strip().lower(),
        "endpoint": endpoint.rstrip("/"),
        "project_id": project_id.strip(),
        "timeout": timeout,
        "options": options or None,
        "project_uid": project_uid or None,
        "binding_id": binding_id or None,
    }
    parse_settings({key: value for key, value in config.items() if value is not None})
    # 설정 파일에는 사람이 만지는 키만 남긴다 — uid·binding 신원은 사이드카로 (오딘 결정 26-07-23).
    # save_project 는 섹션을 통째 교체하므로 구 스키마의 잔존 uid·binding 키도 함께 사라진다.
    visible = {key: value for key, value in config.items() if key not in ("project_uid", "binding_id")}
    # 구 memory 섹션은 함께 제거 — 남기면 정본이 이원화되고 폴백 리더가 낡은 값을 읽는다.
    path = save_project(root, PROJECT_SECTION, visible, drop=(LEGACY_PROJECT_SECTION,))
    if project_uid or binding_id:
        _write_binding_sidecar(root, config["project_id"], project_uid, binding_id)
    return path


# ── 승인 대기 (2단 retain) — 개인 위키 plan-id 와 동일 계약 ───────────────────────────


def _pending_path(root: str) -> str:
    project_key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:24]
    return os.path.join(os.path.expanduser("~"), ".asgard", "state", f"project-memory-pending-{project_key}.json")


def _secure_machine_directory(path: str) -> None:
    """Create an owner-only machine-local directory without following links."""
    parent = os.path.dirname(path)
    if parent and parent != path and not os.path.exists(parent):
        _secure_machine_directory(parent)
    is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(path))
    if os.path.lexists(path) and (os.path.islink(path) or is_junction):
        raise OSError(f"unsafe machine-local memory state directory: {path}")
    os.makedirs(path, mode=0o700, exist_ok=True)
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        raise OSError(f"machine-local memory state path is not a directory: {path}")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise OSError(f"machine-local memory state directory has the wrong owner: {path}")
    _apply_private_acl(path, directory=True)


def _apply_private_acl(path: str, *, directory: bool = False) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700 if directory else 0o600)
        return
    user = os.environ.get("USERNAME", "")
    if not user:
        raise OSError("USERNAME is required to secure project-memory approval state")
    grant = f"{user}:(OI)(CI)F" if directory else f"{user}:F"
    # /grant:r only replaces ACEs for the named user; it does not remove explicit ACEs for
    # Everyone or other users. Reset to inherited defaults first, then remove inheritance and
    # install the sole owner ACE.
    commands = (
        ["icacls", path, "/reset"],
        ["icacls", path, "/inheritance:r", "/grant:r", grant],
    )
    for command in commands:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise OSError(f"failed to secure project-memory approval state ACL: {path}")


def _validate_private_state_file(fd: int, label: str, path: str | None = None) -> None:
    info = os.fstat(fd)
    unsafe_posix_mode = os.name != "nt" and bool(info.st_mode & 0o077)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or unsafe_posix_mode:
        raise OSError(f"{label} must be a singly-linked regular 0600 file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise OSError(f"{label} has the wrong owner")
    if path is not None:
        is_junction = bool(getattr(os.path, "isjunction", lambda _path: False)(path))
        path_info = os.stat(path, follow_symlinks=False)
        if stat.S_ISLNK(path_info.st_mode) or is_junction:
            raise OSError(f"{label} must not be a symlink or junction")
        if (path_info.st_dev, path_info.st_ino) != (info.st_dev, info.st_ino):
            raise OSError(f"{label} changed while it was opened")


@contextlib.contextmanager
def _pending_guard(root: str):
    """프로세스/스레드 공통 lock — approval JSON의 lost update·double commit 방지."""
    path = _pending_path(root) + ".lock"
    _secure_machine_directory(os.path.dirname(path))
    deadline = time.monotonic() + 5
    fd = None
    while fd is None:
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > PENDING_LOCK_STALE:
                    os.remove(path)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("project memory approval lock timeout")
            time.sleep(0.01)
    try:
        _validate_private_state_file(fd, "project-memory approval lock", path)
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.remove(path)


def _load_pending_unlocked(root: str) -> dict:
    try:
        _apply_private_acl(_pending_path(root))
        fd = os.open(_pending_path(root), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            _validate_private_state_file(fd, "project-memory pending approval state", _pending_path(root))
        except Exception:
            os.close(fd)
            raise
        with os.fdopen(fd, encoding="utf-8") as source:
            d = json.load(source)
        if not isinstance(d, dict):
            return {}
        now = time.time()
        live: dict[str, dict] = {}
        for approval_id, entry in d.items():
            if not isinstance(approval_id, str) or not isinstance(entry, dict):
                continue
            try:
                issued_at = float(entry.get("issued_at") or entry.get("ts") or 0)
            except TypeError, ValueError:
                continue
            if issued_at > 0 and now - issued_at < PENDING_TTL:
                live[approval_id] = entry
        return live
    except Exception:
        return {}


def _load_pending(root: str) -> dict:
    with _pending_guard(root):
        return _load_pending_unlocked(root)


def _save_pending_unlocked(root: str, d: dict) -> None:
    p = _pending_path(root)
    _secure_machine_directory(os.path.dirname(p))
    tmp = f"{p}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        _validate_private_state_file(fd, "project-memory pending approval temporary state", tmp)
    except Exception:
        os.close(fd)
        raise
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    _apply_private_acl(p)


def _save_pending(root: str, d: dict) -> None:
    with _pending_guard(root):
        _save_pending_unlocked(root, d)


def _approval_key() -> bytes:
    """Repo 밖 0600 key. pending JSON을 수정한 repo-local 주체가 승인 payload를 재서명하지 못하게 한다."""
    directory = os.path.join(os.path.expanduser("~"), ".asgard")
    _secure_machine_directory(directory)
    path = os.path.join(directory, "project-memory-approval.key")
    with _trust_guard():
        if not os.path.exists(path):
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            try:
                key = secrets.token_bytes(32)
                os.write(fd, key)
                os.fsync(fd)
            finally:
                os.close(fd)
        _apply_private_acl(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            _validate_private_state_file(fd, "project-memory approval key", path)
            key = os.read(fd, 33)
        finally:
            os.close(fd)
    if len(key) != 32:
        raise OSError("invalid project-memory approval key")
    return key


def _retain_item_mac(
    approval_id: str,
    issued_at: float,
    expires_at: float,
    item: str | dict,
    target: dict | None,
) -> str:
    payload = json.dumps(
        {
            "schema": 4,
            "approval_id": approval_id,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "item": item,
            "target": target,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac.new(_approval_key(), payload, hashlib.sha256).hexdigest()


def _consumed_path(root: str) -> str:
    project_key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:24]
    return os.path.join(
        os.path.expanduser("~"),
        ".asgard",
        "state",
        f"project-memory-approval-consumed-{project_key}.json",
    )


def _approval_scope(root: str, approval_id: str) -> str:
    project_key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:24]
    return f"{project_key}:{approval_id}"


def _consumed_mac(entries: dict[str, float]) -> str:
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_approval_key(), payload, hashlib.sha256).hexdigest()


def _load_consumed_unlocked(root: str) -> dict[str, float]:
    path = _consumed_path(root)
    if not os.path.exists(path):
        return {}
    _apply_private_acl(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        _validate_private_state_file(fd, "project-memory consumed approval state", path)
        source = os.fdopen(fd, encoding="utf-8")
        fd = -1
        with source:
            data = json.load(source)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("entries"), dict):
        raise OSError("invalid project-memory consumed approval state")
    raw_entries: dict[str, float] = {}
    for key, value in data["entries"].items():
        try:
            raw_entries[str(key)] = float(value)
        except TypeError, ValueError:
            raise OSError("invalid project-memory consumed approval entry") from None
    expected = str(data.get("mac") or "")
    if not expected or not secrets.compare_digest(expected, _consumed_mac(raw_entries)):
        raise OSError("project-memory consumed approval state authentication failed")
    now = time.time()
    return {key: expiry for key, expiry in raw_entries.items() if expiry > now}


def _save_consumed_unlocked(root: str, entries: dict[str, float]) -> None:
    path = _consumed_path(root)
    _secure_machine_directory(os.path.dirname(path))
    payload = {"schema": 1, "entries": entries, "mac": _consumed_mac(entries)}
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        _validate_private_state_file(fd, "project-memory consumed approval temporary state", tmp)
        output = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with output:
            json.dump(payload, output, ensure_ascii=False, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
        _apply_private_acl(path)
    finally:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.remove(tmp)


def stage_retain(root: str, item: str | dict, *, target: dict | None = None) -> str:
    """승인 대기 등록 — 반환 = approval id (1회 소비)."""
    with _pending_guard(root):
        pend = _load_pending_unlocked(root)
        document_id = str(item.get("document_id") or "") if isinstance(item, dict) else ""
        item_hash = hashlib.sha256(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        now = time.time()
        expires_at = now + PENDING_TTL
        if document_id:
            for existing_id, entry in pend.items():
                existing = entry.get("item")
                issued = float(entry.get("issued_at") or 0)
                expires = float(entry.get("expires_at") or 0)
                expected_mac = str(entry.get("item_mac") or "")
                actual_mac = _retain_item_mac(existing_id, issued, expires, existing, entry.get("target"))
                if (
                    entry.get("schema") == 4
                    and isinstance(existing, dict)
                    and existing.get("document_id") == document_id
                    and entry.get("item_hash") == item_hash
                    and entry.get("target") == target
                    and not entry.get("claim")
                    and expected_mac
                    and secrets.compare_digest(expected_mac, actual_mac)
                ):
                    return existing_id
        aid = secrets.token_hex(4)
        pend[aid] = {
            "item": item,
            "item_hash": item_hash,
            "item_mac": _retain_item_mac(aid, now, expires_at, item, target),
            "target": target,
            "ts": now,
            "issued_at": now,
            "expires_at": expires_at,
            "schema": 4,
        }
        _save_pending_unlocked(root, pend)
    return aid


def _retain_item_hash(item: str | dict) -> str:
    return hashlib.sha256(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def claim_retain(root: str, aid: str, *, target: dict | None = None) -> tuple[str | dict, str] | None:
    """approval을 원격 write 동안 독점 claim한다. 실패 시 같은 ID를 재사용할 수 있다."""
    with _pending_guard(root):
        if _approval_scope(root, aid) in _load_consumed_unlocked(root):
            return None
        pend = _load_pending_unlocked(root)
        entry = pend.get(aid)
        if not entry:
            return None
        if entry.get("schema") != 4:
            return None
        item = entry.get("item", entry.get("content"))
        expected_hash = str(entry.get("item_hash") or "")
        actual_hash = _retain_item_hash(item)
        if not expected_hash or not secrets.compare_digest(expected_hash, actual_hash):
            return None
        issued_at = float(entry.get("issued_at") or 0)
        expires_at = float(entry.get("expires_at") or 0)
        now = time.time()
        if not issued_at or expires_at <= issued_at or now >= expires_at:
            return None
        expected_mac = str(entry.get("item_mac") or "")
        actual_mac = _retain_item_mac(aid, issued_at, expires_at, item, entry.get("target"))
        if not expected_mac or not secrets.compare_digest(expected_mac, actual_mac):
            return None
        expected_target = entry.get("target")
        if target is not None:
            if not isinstance(expected_target, dict):
                return None
            expected_fingerprint = str(expected_target.get("fingerprint") or "")
            actual_fingerprint = str(target.get("fingerprint") or "")
            if (
                expected_target.get("engine") != target.get("engine")
                or expected_target.get("project_id") != target.get("project_id")
                or not expected_fingerprint
                or not secrets.compare_digest(expected_fingerprint, actual_fingerprint)
            ):
                return None
        if entry.get("claim"):
            return None
        token = secrets.token_hex(8)
        entry["claim"] = token
        entry["claimed_at"] = now
        _save_pending_unlocked(root, pend)
        return (item, token) if item is not None else None


def finish_retain(root: str, aid: str, token: str, *, success: bool) -> None:
    with _pending_guard(root):
        pend = _load_pending_unlocked(root)
        entry = pend.get(aid)
        if not entry or entry.get("claim") != token:
            return
        if success:
            consumed = _load_consumed_unlocked(root)
            consumed[_approval_scope(root, aid)] = float(entry.get("expires_at") or time.time() + PENDING_TTL)
            _save_consumed_unlocked(root, consumed)
            pend.pop(aid, None)
        else:
            entry.pop("claim", None)
            entry.pop("claimed_at", None)
        _save_pending_unlocked(root, pend)
