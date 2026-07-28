"""개인 메모리 서버 연동 — 정본 md 를 원격과 양방향으로 맞춘다.

두 전송을 지원한다. 둘 다 "파일이 정본"이라는 같은 규칙 위에서 돈다.
  dir  — 마운트된 폴더(클라우드 동기화 폴더·NAS·공유 볼륨). 기준선(baseline) 대조 3-way.
  git  — 임의의 git 원격(자체 호스팅 포함). 이력·충돌 판정을 git 에 위임한다.

기준선이 핵심이다. 양쪽 다이제스트만 비교하면 "저쪽이 새로 쓴 것"과 "이쪽이 지운 것"을
구분할 수 없어서, 삭제가 부활하거나 새 글이 조용히 사라진다. 마지막으로 양쪽이 같았던
시점의 다이제스트를 sync-state.json 에 남기고 셋을 비교한다.

충돌은 자동으로 풀지 않는다. 양쪽이 같은 파일을 서로 다르게 고쳤으면 로컬을 그대로 두고
원격본을 conflicts/<stamp>/ 에 떨궈 사람이 판정하게 한다 — 기억은 조용히 덮어써질 수 없다.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import uuid

from .backup import CANONICAL_DIRS, CANONICAL_FILES, canonical_members
from .index import reindex
from .policy import _memory_settings
from .store import LOG, _atomic_write, _chmod, _lock, ensure_home, log_op

STATE_FILE = "sync-state.json"
CONFLICTS_DIR = "conflicts"
MARKER_NAME = ".asgard-memory-sync.json"
STATE_SCHEMA = 1
TRANSPORTS = ("dir", "git")
GIT_TIMEOUT = 120

# 파생물은 원격에 올리지 않는다 — pages/ 에서 재생성되고, 기계마다 달라 충돌만 만든다.
# log.md 는 append-only 운영 로그다. 두 기계가 각자 append 하면 3-way 로는 매번 충돌인데,
# 정답은 언제나 "둘 다"다. git 은 내장 union 드라이버로, dir 전송은 _merge_log 로 같은 판정을 한다.
GIT_ATTRIBUTES = f"{LOG} merge=union\n"

GIT_IGNORE = """# Asgard personal memory — derived artifacts are rebuilt from pages/
index.md
state.db
state.db-wal
state.db-shm
.lock
maps/
backups/
norn-backups/
reports/
conflicts/
sync-state.json
norn-state.json
.obsidian/workspace*.json
*.tmp
"""


class SyncError(ValueError):
    """동기화 계약 위반 — 미설정 원격·정체불명 폴더·전송 실패."""


# ── 설정 ──────────────────────────────────────────────────────────────────────


def settings() -> dict:
    """[memory].sync — {"transport": "dir|git", "remote": str}. 미설정이면 빈 dict."""
    raw = _memory_settings().get("sync")
    if not isinstance(raw, dict):
        return {}
    transport = str(raw.get("transport") or "").strip().lower()
    remote = str(raw.get("remote") or "").strip()
    if transport not in TRANSPORTS or not remote:
        return {}
    return {"transport": transport, "remote": remote, "branch": str(raw.get("branch") or "main").strip() or "main"}


def save_settings(remote: str, transport: str = "dir", branch: str = "main") -> dict:
    """원격을 전역 설정에 기록한다. 반환 = 저장된 설정."""
    transport = transport.strip().lower()
    if transport not in TRANSPORTS:
        raise SyncError(f"transport must be one of {', '.join(TRANSPORTS)}")
    remote = remote.strip()
    if not remote:
        raise SyncError("remote is required")
    if transport == "dir":
        remote = os.path.abspath(os.path.expanduser(remote))
    from ..settings import load_global, save_global

    configured = dict(load_global().get("memory") or {})
    configured["sync"] = {"transport": transport, "remote": remote, "branch": branch}
    save_global("memory", configured)
    return dict(configured["sync"])


def clear_settings() -> None:
    from ..settings import load_global, save_global

    configured = dict(load_global().get("memory") or {})
    configured.pop("sync", None)
    save_global("memory", configured)


# ── 기준선 상태 ───────────────────────────────────────────────────────────────


def _state_path(d: str) -> str:
    return os.path.join(d, STATE_FILE)


def load_state(d: str) -> dict:
    try:
        with open(_state_path(d), encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict) and int(loaded.get("schema") or 0) == STATE_SCHEMA:
            baseline = loaded.get("baseline")
            loaded["baseline"] = baseline if isinstance(baseline, dict) else {}
            return loaded
    except OSError, ValueError:
        pass
    return {"schema": STATE_SCHEMA, "baseline": {}, "remote": "", "transport": "", "last_sync": ""}


def save_state(d: str, state: dict) -> None:
    state["schema"] = STATE_SCHEMA
    _atomic_write(_state_path(d), json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _digest(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def digest_map(root: str) -> dict[str, str]:
    """정본 상대경로 → sha256. 존재하지 않는 트리는 빈 map."""
    if not os.path.isdir(root):
        return {}
    out: dict[str, str] = {}
    for name in CANONICAL_FILES:
        path = os.path.join(root, name)
        if os.path.isfile(path) and not os.path.islink(path):
            out[name] = _digest(path)
    for folder in CANONICAL_DIRS:
        folder_root = os.path.join(root, folder)
        if not os.path.isdir(folder_root) or os.path.islink(folder_root):
            continue
        for entry in sorted(os.listdir(folder_root)):
            path = os.path.join(folder_root, entry)
            if entry.endswith(".md") and os.path.isfile(path) and not os.path.islink(path):
                out[f"{folder}/{entry}"] = _digest(path)
    return out


# ── dir 전송 ──────────────────────────────────────────────────────────────────


def _marker_path(remote: str) -> str:
    return os.path.join(remote, MARKER_NAME)


def _read_marker(remote: str) -> dict:
    try:
        with open(_marker_path(remote), encoding="utf-8") as handle:
            loaded = json.load(handle)
        return loaded if isinstance(loaded, dict) else {}
    except OSError, ValueError:
        return {}


def _ensure_remote_dir(remote: str, *, adopt: bool) -> dict:
    """원격 폴더의 정체를 확인하거나 새로 표식한다.

    표식 없는 비어 있지 않은 폴더에 그냥 쓰면 남의 폴더를 메모리로 오염시킬 수 있다.
    프로젝트 메모리의 binding 과 같은 규율 — 빈 폴더는 자동 개설, 남의 내용물은 명시 동의."""
    if os.path.islink(remote):
        raise SyncError("sync remote must not be a symlink")
    if not os.path.isdir(remote):
        os.makedirs(remote, exist_ok=True)
    marker = _read_marker(remote)
    if marker.get("type") == "asgard-personal-memory":
        return marker
    contents = [n for n in os.listdir(remote) if not n.startswith(".")]
    if contents and not adopt:
        raise SyncError(
            f"remote folder is not an Asgard memory remote and is not empty ({len(contents)} entr(ies)); "
            "pass --adopt to use it anyway"
        )
    marker = {
        "type": "asgard-personal-memory",
        "id": str(uuid.uuid4()),
        "created": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema": STATE_SCHEMA,
    }
    with open(_marker_path(remote), "w", encoding="utf-8") as handle:
        json.dump(marker, handle, ensure_ascii=False, indent=2, sort_keys=True)
    return marker


def plan_dir_sync(d: str, remote: str) -> dict:
    """3-way 판정만 — 쓰기 없음. 반환 = {"push", "pull", "delete_local", "delete_remote", "conflict"}."""
    state = load_state(d)
    baseline = {str(k): str(v) for k, v in (state.get("baseline") or {}).items()}
    local = digest_map(d)
    remote_map = digest_map(remote)
    plan: dict[str, list[str]] = {
        "push": [],
        "pull": [],
        "delete_local": [],
        "delete_remote": [],
        "merge": [],
        "conflict": [],
    }
    for key in sorted(set(local) | set(remote_map) | set(baseline)):
        mine, theirs, base = local.get(key), remote_map.get(key), baseline.get(key)
        if mine == theirs:
            continue
        if key == LOG:
            plan["merge"].append(key)  # append-only 로그 — 판정은 언제나 union
            continue
        if base is None:
            # 기준선에 없던 파일 — 한쪽만 있으면 새 글, 양쪽이 다르면 독립 생성 충돌
            plan["push" if theirs is None else "pull" if mine is None else "conflict"].append(key)
            continue
        if mine == base:  # 이쪽은 그대로, 저쪽이 움직였다
            plan["delete_local" if theirs is None else "pull"].append(key)
        elif theirs == base:  # 저쪽은 그대로, 이쪽이 움직였다
            plan["delete_remote" if mine is None else "push"].append(key)
        else:
            plan["conflict"].append(key)
    return plan


def _copy(src_root: str, dst_root: str, relative: str) -> None:
    source = os.path.join(src_root, relative)
    target = os.path.join(dst_root, relative)
    os.makedirs(os.path.dirname(target) or dst_root, exist_ok=True)
    shutil.copyfile(source, target)
    _chmod(target, 0o600)


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def merge_log(local_text: str, remote_text: str) -> str:
    """append-only 로그 union — 헤더 1줄 + 타임스탬프 순 정렬된 중복 없는 엔트리.

    같은 초에 두 기계가 쓴 줄은 사전순으로 갈린다. 순서보다 중요한 건 어느 쪽도 잃지 않는 것이다."""
    header = ""
    entries: list[str] = []
    seen: set[str] = set()
    for text in (local_text, remote_text):
        for line in text.splitlines():
            stripped = line.rstrip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                header = header or stripped
                continue
            if stripped not in seen:
                seen.add(stripped)
                entries.append(stripped)
    entries.sort(key=lambda line: (line[2:20], line))  # "- <ISO stamp> [op] …" 의 시각 구간
    return "\n".join([header or "# Memory Log", *entries]) + "\n"


def _stash_conflict(d: str, remote: str, relative: str, stamp: str) -> str:
    """원격본을 conflicts/<stamp>/ 에 보존한다. 로컬 정본은 손대지 않는다."""
    target = os.path.join(d, CONFLICTS_DIR, stamp, relative)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    source = os.path.join(remote, relative)
    if os.path.isfile(source):
        shutil.copyfile(source, target)
    else:  # 저쪽이 지웠고 이쪽이 고친 경우 — 삭제 자체가 판정 대상이다
        _atomic_write(target, "")
    _chmod(target, 0o600)
    return os.path.relpath(target, d)


def sync_dir(d: str, remote: str, *, dry_run: bool = False, adopt: bool = False) -> dict:
    """폴더 전송 동기화 — 무충돌 변경은 양방향 적용, 충돌은 보존 후 보고."""
    marker = _ensure_remote_dir(remote, adopt=adopt)
    with _lock(d):
        plan = plan_dir_sync(d, remote)
        result = {
            "transport": "dir",
            "remote": remote,
            "remote_id": str(marker.get("id") or ""),
            "dry_run": dry_run,
            **{key: list(value) for key, value in plan.items()},
            "conflict_copies": [],
        }
        if dry_run:
            return result
        stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        for relative in plan["push"]:
            _copy(d, remote, relative)
        for relative in plan["pull"]:
            _copy(remote, d, relative)
        for relative in plan["delete_local"]:
            with contextlib.suppress(OSError):
                os.remove(os.path.join(d, relative))
        for relative in plan["delete_remote"]:
            with contextlib.suppress(OSError):
                os.remove(os.path.join(remote, relative))
        for relative in plan["merge"]:
            merged = merge_log(_read_text(os.path.join(d, relative)), _read_text(os.path.join(remote, relative)))
            _atomic_write(os.path.join(d, relative), merged)
            _atomic_write(os.path.join(remote, relative), merged)
        result["conflict_copies"] = [_stash_conflict(d, remote, relative, stamp) for relative in plan["conflict"]]
        # 기준선은 "지금 양쪽이 같다"고 확인된 파일만 담는다 — 충돌 파일은 빠지고,
        # 다음 동기화에서 다시 충돌로 잡힌다 (사람이 풀 때까지 판정이 유지된다).
        local_after, remote_after = digest_map(d), digest_map(remote)
        save_state(
            d,
            {
                "schema": STATE_SCHEMA,
                "transport": "dir",
                "remote": remote,
                "remote_id": result["remote_id"],
                "last_sync": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "baseline": {k: v for k, v in local_after.items() if remote_after.get(k) == v},
            },
        )
    changed = len(plan["pull"]) + len(plan["delete_local"])
    if changed:
        reindex(d)  # 원격에서 들어온 정본 — 파생을 다시 만든다
    log_op(
        d,
        "sync:dir",
        os.path.basename(remote.rstrip(os.sep)) or remote,
        f"push={len(plan['push'])} pull={len(plan['pull'])} conflict={len(plan['conflict'])}",
    )
    return result


# ── git 전송 ──────────────────────────────────────────────────────────────────


def _git(d: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", d, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT,
        check=check,
    )


def _git_available() -> bool:
    return shutil.which("git") is not None


def ensure_git_repo(d: str, remote: str, branch: str = "main") -> bool:
    """메모리 홈을 git 저장소로 준비한다. 반환 = 새로 만들었으면 True."""
    created = not os.path.isdir(os.path.join(d, ".git"))
    if created:
        if _git(d, "init", "-q", "-b", branch, check=False).returncode != 0:  # git < 2.28
            _git(d, "init", "-q")
            _git(d, "checkout", "-q", "-b", branch, check=False)
    ignore = os.path.join(d, ".gitignore")
    if GIT_IGNORE not in _read_text(ignore):
        _atomic_write(ignore, GIT_IGNORE)
    attributes = os.path.join(d, ".gitattributes")
    if GIT_ATTRIBUTES not in _read_text(attributes):
        _atomic_write(attributes, GIT_ATTRIBUTES)
    if _git(d, "config", "user.email", check=False).returncode != 0:
        _git(d, "config", "user.email", "memory@asgard.local")
        _git(d, "config", "user.name", "Asgard Memory")
    current = _git(d, "remote", "get-url", "origin", check=False)
    if current.returncode != 0:
        _git(d, "remote", "add", "origin", remote)
    elif current.stdout.strip() != remote:
        _git(d, "remote", "set-url", "origin", remote)
    return created


def sync_git(d: str, remote: str, *, branch: str = "main", dry_run: bool = False) -> dict:
    """git 전송 — 로컬 정본 커밋 → pull --rebase → push. 충돌은 되돌리고 보고한다."""
    if not _git_available():
        raise SyncError("git is not installed — use the dir transport or install git")
    result: dict = {"transport": "git", "remote": remote, "branch": branch, "dry_run": dry_run}
    with _lock(d):
        ensure_git_repo(d, remote, branch)
        status = _git(d, "status", "--porcelain")
        pending = [line[3:] for line in status.stdout.splitlines() if line.strip()]
        result["pending"] = pending
        if dry_run:
            return result
        if pending:
            # 존재하는 경로만 넘긴다 — 없는 pathspec 하나가 add 전체를 실패시킨다
            tracked = (*CANONICAL_DIRS, *CANONICAL_FILES, ".gitignore", ".gitattributes")
            present = [p for p in tracked if os.path.exists(os.path.join(d, p))]
            _git(d, "add", "-A", "--", *present)
            staged = _git(d, "diff", "--cached", "--name-only")
            if staged.stdout.strip():
                stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%MZ")
                _git(d, "commit", "-q", "-m", f"memory: sync {stamp}")
                result["committed"] = [line for line in staged.stdout.splitlines() if line.strip()]
        fetch = _git(d, "fetch", "origin", branch, check=False)
        result["fetched"] = fetch.returncode == 0
        if fetch.returncode == 0:
            rebase = _git(d, "rebase", f"origin/{branch}", check=False)
            if rebase.returncode != 0:
                _git(d, "rebase", "--abort", check=False)
                result["conflict"] = True
                result["detail"] = (rebase.stdout + rebase.stderr).strip()[:400]
                log_op(d, "sync:git", branch, "diverged — manual resolution required")
                return result
        push = _git(d, "push", "-u", "origin", branch, check=False)
        result["pushed"] = push.returncode == 0
        if not result["pushed"]:
            result["detail"] = (push.stdout + push.stderr).strip()[:400]
        head = _git(d, "rev-parse", "--short", "HEAD", check=False)
        result["head"] = head.stdout.strip()
    reindex(d)
    log_op(d, "sync:git", branch, f"pushed={result.get('pushed')} head={result.get('head', '')}")
    return result


# ── 진입점 ────────────────────────────────────────────────────────────────────


def sync(d: str | None = None, *, dry_run: bool = False, adopt: bool = False) -> dict:
    """설정된 전송으로 동기화한다. 미설정이면 SyncError."""
    d = ensure_home(d)
    configured = settings()
    if not configured:
        raise SyncError("no sync remote configured — run `asgard memory sync --set-remote <path-or-url>`")
    if configured["transport"] == "git":
        return sync_git(d, configured["remote"], branch=configured["branch"], dry_run=dry_run)
    return sync_dir(d, configured["remote"], dry_run=dry_run, adopt=adopt)


def status(d: str | None = None) -> dict:
    """동기화 상태 요약 — 원격·마지막 시각·미해결 충돌 수."""
    d = ensure_home(d)
    state = load_state(d)
    configured = settings()
    conflicts_root = os.path.join(d, CONFLICTS_DIR)
    unresolved = sorted(os.listdir(conflicts_root)) if os.path.isdir(conflicts_root) else []
    return {
        "configured": bool(configured),
        "transport": configured.get("transport", "") or state.get("transport", ""),
        "remote": configured.get("remote", "") or state.get("remote", ""),
        "last_sync": state.get("last_sync", ""),
        "tracked": len(state.get("baseline") or {}),
        "local_files": len(canonical_members(d)),
        "unresolved_conflicts": unresolved,
    }
