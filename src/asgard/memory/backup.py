"""개인 메모리 백업 — 정본만 담은 이식 가능한 아카이브와 검증된 복원.

정본은 md 파일이고 index.md·state.db는 파생물이다 (memory/__init__ 원칙). 그래서
백업은 파생물을 담지 않는다 — 담으면 복원본이 원본과 다른 시점의 인덱스를 들고
살아나고, 그 불일치는 조용하다. 복원은 pages/ 를 통째 갈아끼운 뒤 파생을 재생성한다.

무결성: 아카이브 안에 MANIFEST.json(멤버별 sha256)을 같이 넣고, restore/verify가
추출 전에 대조한다. 손상된 아카이브로 멀쩡한 위키를 덮어쓰는 경로를 만들지 않는다.
복원은 되돌릴 수 있어야 하므로 항상 직전 상태를 먼저 백업한다.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import io
import json
import os
import shutil
import tarfile

from .index import reindex
from .norn import ARCHIVE_DIR
from .store import CONTRADICTIONS, LOG, PAGES, SCHEMA, USAGE, _atomic_write, _chmod, _lock, ensure_home, log_op
from .usage import flush as _usage_flush

BACKUPS_DIR = "backups"
MANIFEST_NAME = "MANIFEST.json"
BACKUP_SCHEMA = 1
KEEP_DEFAULT = 10
NO_PRUNE = 1_000_000  # 정리를 건너뛰는 보존 한도 (복원 시 안전 백업)
MAX_MEMBER_BYTES = 4 * 1024 * 1024  # 페이지 하나가 이보다 크면 정본이 아니라 사고다
MAX_TOTAL_BYTES = 256 * 1024 * 1024

# 정본 = 지식 + 되돌릴 수 있는 이력 + **사람의 손이 남긴 것**. 나머지(index.md·state.db·락·
# 리포트·백업 자신)는 pages/ 에서 재생성되거나 그 기계에만 의미가 있다.
#
# 회수 기록(usage.json)과 모순 처리 상태(contradictions.json)가 여기 있는 이유: 둘 다
# pages/ 에서 다시 만들 수 없다. 예전엔 회수 기록이 state.db 에만 살아서, 파생물을 지우는
# 정상 경로 하나가 원본 데이터를 같이 지웠다 — 그리고 그 순간 90일 넘은 전 페이지가 일제히
# 부패 후보로 떴다 (`memory.usage`). state.db 자체를 담지 않는 규율은 그대로다: 파생물을
# 백업에 넣으면 복원본이 다른 시점의 색인을 들고 살아나고 그 불일치는 조용하다.
CANONICAL_FILES = (SCHEMA, LOG, USAGE, CONTRADICTIONS)
CANONICAL_DIRS = (PAGES, ARCHIVE_DIR)


class BackupError(ValueError):
    """백업/복원 계약 위반 — 손상 아카이브·경로 탈출·용량 초과."""


def _stamp() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def backups_dir(d: str) -> str:
    path = os.path.join(d, BACKUPS_DIR)
    os.makedirs(path, exist_ok=True)
    _chmod(path, 0o700)
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_members(d: str) -> list[str]:
    """백업 대상 상대경로 — 정렬된 결정적 목록. 심볼릭 링크·비 md는 제외한다."""
    members: list[str] = []
    for name in CANONICAL_FILES:
        path = os.path.join(d, name)
        if os.path.isfile(path) and not os.path.islink(path):
            members.append(name)
    for folder in CANONICAL_DIRS:
        root = os.path.join(d, folder)
        if not os.path.isdir(root) or os.path.islink(root):
            continue
        for entry in sorted(os.listdir(root)):
            path = os.path.join(root, entry)
            if entry.endswith(".md") and os.path.isfile(path) and not os.path.islink(path):
                members.append(f"{folder}/{entry}")
    return sorted(members)


def _read_bytes(path: str) -> bytes:
    size = os.path.getsize(path)
    if size > MAX_MEMBER_BYTES:
        raise BackupError(f"member exceeds {MAX_MEMBER_BYTES} bytes: {path}")
    with open(path, "rb") as handle:
        return handle.read()


def create(d: str | None = None, *, label: str = "", keep: int = KEEP_DEFAULT) -> dict:
    """정본 스냅샷 하나를 backups/<stamp>.tar.gz로 만든다. 반환 = 요약 dict."""
    d = ensure_home(d)
    safe_label = "".join(ch for ch in label if ch.isalnum() or ch in "-_")[:32]
    # 노출 계수는 DB 에만 쌓이다 큰 계기에 접힌다 — 백업이 그 계기다. 여기서 안 접으면
    # 아카이브가 담는 회수 기록이 마지막 검색 시점에 멈춰 있다 (`memory.usage`).
    _usage_flush(d)
    with _lock(d):
        members = canonical_members(d)
        payload: dict[str, bytes] = {}
        total = 0
        for relative in members:
            data = _read_bytes(os.path.join(d, relative))
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise BackupError(f"backup exceeds {MAX_TOTAL_BYTES} bytes")
            payload[relative] = data
        stamp = _stamp()
        manifest = {
            "schema": BACKUP_SCHEMA,
            "created": stamp,
            "label": safe_label,
            "pages": sum(1 for m in members if m.startswith(f"{PAGES}/")),
            "archived": sum(1 for m in members if m.startswith(f"{ARCHIVE_DIR}/")),
            "bytes": total,
            "files": {relative: _sha256(data) for relative, data in payload.items()},
        }
        name = f"{stamp}{'-' + safe_label if safe_label else ''}.tar.gz"
        path = os.path.join(backups_dir(d), name)
        _write_archive(path, manifest, payload)
        log_op(d, "backup:create", name, f"{manifest['pages']} page(s)")
        pruned = prune(d, keep=keep)
    return {"path": path, "name": name, **{k: v for k, v in manifest.items() if k != "files"}, "pruned": pruned}


def _write_archive(path: str, manifest: dict, payload: dict[str, bytes]) -> None:
    tmp = f"{path}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    try:
        with tarfile.open(tmp, "w:gz") as archive:
            blob = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode()
            _add_bytes(archive, MANIFEST_NAME, blob, manifest["created"])
            for relative, data in payload.items():
                _add_bytes(archive, relative, data, manifest["created"])
        _chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            if os.path.exists(tmp):
                os.remove(tmp)


def _add_bytes(archive: tarfile.TarFile, name: str, data: bytes, stamp: str) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o600
    with contextlib.suppress(ValueError):
        info.mtime = int(_dt.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.UTC).timestamp())
    archive.addfile(info, io.BytesIO(data))


def _safe_member(name: str) -> str:
    """아카이브 멤버 이름 검증 — 절대경로·상위 참조·구분자 이상은 전부 거절."""
    if name != name.strip() or name.startswith("/") or "\\" in name:
        raise BackupError(f"unsafe archive member: {name!r}")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts) or len(parts) > 2:
        raise BackupError(f"unsafe archive member: {name!r}")
    if len(parts) == 2 and parts[0] not in CANONICAL_DIRS:
        raise BackupError(f"member outside the canonical set: {name!r}")
    if len(parts) == 1 and name not in (*CANONICAL_FILES, MANIFEST_NAME):
        raise BackupError(f"member outside the canonical set: {name!r}")
    if len(parts) == 2 and not name.endswith(".md"):
        raise BackupError(f"member outside the canonical set: {name!r}")
    return name


def read_archive(path: str) -> tuple[dict, dict[str, bytes]]:
    """아카이브를 메모리로 읽고 manifest와 대조한다. 반환 = (manifest, {relpath: bytes})."""
    if not os.path.isfile(path):
        raise BackupError(f"backup not found: {path}")
    payload: dict[str, bytes] = {}
    manifest: dict = {}
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for info in archive:
            if not info.isfile():
                raise BackupError(f"archive contains a non-regular member: {info.name!r}")
            name = _safe_member(info.name)
            if info.size > MAX_MEMBER_BYTES:
                raise BackupError(f"member exceeds {MAX_MEMBER_BYTES} bytes: {name}")
            total += info.size
            if total > MAX_TOTAL_BYTES:
                raise BackupError(f"archive exceeds {MAX_TOTAL_BYTES} bytes")
            handle = archive.extractfile(info)
            data = handle.read() if handle else b""
            if name == MANIFEST_NAME:
                try:
                    loaded = json.loads(data.decode())
                except (ValueError, UnicodeDecodeError) as exc:
                    raise BackupError("backup manifest is not readable JSON") from exc
                if not isinstance(loaded, dict):
                    raise BackupError("backup manifest is malformed")
                manifest = loaded
            else:
                payload[name] = data
    if not manifest:
        raise BackupError("backup is missing its manifest")
    if int(manifest.get("schema") or 0) != BACKUP_SCHEMA:
        raise BackupError(f"unsupported backup schema: {manifest.get('schema')!r}")
    digests = manifest.get("files")
    if not isinstance(digests, dict):
        raise BackupError("backup manifest has no file digests")
    if set(digests) != set(payload):
        missing = sorted(set(digests) - set(payload))
        extra = sorted(set(payload) - set(digests))
        raise BackupError(f"backup contents do not match its manifest (missing={missing[:3]} extra={extra[:3]})")
    for relative, expected in digests.items():
        if _sha256(payload[relative]) != str(expected):
            raise BackupError(f"backup member digest mismatch: {relative}")
    return manifest, payload


def verify(path: str) -> dict:
    """무결성 검사만 — 쓰기 없음. 반환 = manifest 요약."""
    manifest, payload = read_archive(path)
    return {k: v for k, v in manifest.items() if k != "files"} | {"members": len(payload), "path": path}


def _entries(d: str) -> list[dict]:
    root = os.path.join(d, BACKUPS_DIR)
    if not os.path.isdir(root):
        return []
    rows: list[dict] = []
    for name in sorted(os.listdir(root), reverse=True):
        if not name.endswith(".tar.gz"):
            continue
        path = os.path.join(root, name)
        with contextlib.suppress(OSError):
            rows.append({"name": name, "path": path, "bytes": os.path.getsize(path)})
    return rows


def listing(d: str | None = None) -> list[dict]:
    """최신순 백업 목록. 각 행은 열지 않고 파일 사실만 — 목록이 손상 아카이브에 걸리지 않는다."""
    return _entries(ensure_home(d))


def prune(d: str, *, keep: int = KEEP_DEFAULT) -> list[str]:
    """최신 keep 개만 남긴다. 반환 = 삭제한 이름들."""
    keep = max(1, int(keep))
    removed: list[str] = []
    for row in _entries(d)[keep:]:
        with contextlib.suppress(OSError):
            os.remove(row["path"])
            removed.append(row["name"])
    return removed


def resolve(d: str, name: str) -> str:
    """이름/경로를 backups/ 안의 실제 파일로 해석한다. 'latest'는 최신 백업."""
    if name in ("latest", ""):
        rows = _entries(d)
        if not rows:
            raise BackupError("no backup to restore — run `asgard memory backup` first")
        return rows[0]["path"]
    if os.path.sep in name or name.startswith("~"):
        return os.path.abspath(os.path.expanduser(name))
    candidate = os.path.join(d, BACKUPS_DIR, name if name.endswith(".tar.gz") else f"{name}.tar.gz")
    if not os.path.isfile(candidate):
        raise BackupError(f"backup not found: {name}")
    return candidate


def restore(name: str = "latest", d: str | None = None) -> dict:
    """검증된 아카이브로 정본을 갈아끼운다. 직전 상태는 자동으로 먼저 백업된다."""
    d = ensure_home(d)
    path = resolve(d, name)
    manifest, payload = read_archive(path)
    # 안전 백업은 정리하지 않는다 — 보존 한도에 걸린 복원이 지금 복원 중인 아카이브를 지울 수 있다.
    # 정리는 다음 평시 백업의 몫이다.
    safety = create(d, label="prerestore", keep=NO_PRUNE)
    with _lock(d):
        staging = os.path.join(d, f".restore.{os.getpid()}.{os.urandom(4).hex()}")
        os.makedirs(staging, exist_ok=True)
        _chmod(staging, 0o700)
        try:
            for relative, data in payload.items():
                target = os.path.join(staging, relative)
                os.makedirs(os.path.dirname(target) or staging, exist_ok=True)
                with open(target, "wb") as handle:
                    handle.write(data)
                _chmod(target, 0o600)
            for folder in CANONICAL_DIRS:
                live = os.path.join(d, folder)
                staged = os.path.join(staging, folder)
                if os.path.isdir(live):
                    shutil.rmtree(live)
                if os.path.isdir(staged):
                    shutil.move(staged, live)
                else:
                    os.makedirs(live, exist_ok=True)
                _chmod(live, 0o700)
            for name_ in CANONICAL_FILES:
                staged = os.path.join(staging, name_)
                if os.path.isfile(staged):
                    shutil.move(staged, os.path.join(d, name_))
                    _chmod(os.path.join(d, name_), 0o600)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    pages = reindex(d)  # 파생은 백업에 없다 — 정본에서 다시 만든다
    log_op(d, "backup:restore", os.path.basename(path), f"{pages} page(s)")
    return {
        "restored": os.path.basename(path),
        "path": path,
        "pages": pages,
        "created": manifest.get("created", ""),
        "safety_backup": safety["name"],
    }


def state_note(d: str | None = None) -> dict:
    """백업 상태 한 줄 요약 — doctor/status 표면용."""
    d = ensure_home(d)
    rows = _entries(d)
    latest = rows[0] if rows else None
    return {
        "directory": os.path.join(d, BACKUPS_DIR),
        "count": len(rows),
        "latest": latest["name"] if latest else "",
        "latest_bytes": latest["bytes"] if latest else 0,
    }


def write_manifest_sidecar(d: str, summary: dict) -> str:
    """마지막 백업 요약을 텍스트로 남긴다 — 아카이브를 열지 않고도 상태를 읽을 수 있게."""
    path = os.path.join(d, BACKUPS_DIR, "LATEST.json")
    _atomic_write(path, json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return path
