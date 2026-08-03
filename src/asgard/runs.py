"""기계 단위 실행 등록부."""

from __future__ import annotations

import json
import os
import subprocess
import time

RUNS_FILE = "runs.json"
RUNS_ENV = "ASGARD_RUNS_STATE"


def runs_path() -> str:
    base = os.environ.get(RUNS_ENV) or os.path.join(os.path.expanduser("~"), ".asgard")
    return os.path.join(os.path.abspath(os.path.expanduser(base)), RUNS_FILE)


def _new_token(size: int) -> str:
    return os.urandom(size).hex()


def _proc_identity(pid: int) -> tuple[str, str]:
    proc = f"/proc/{pid}"
    try:
        with open(os.path.join(proc, "stat"), encoding="utf-8") as handle:
            fields = handle.read().rsplit(")", 1)[1].split()
        with open(os.path.join(proc, "cmdline"), "rb") as handle:
            command = handle.read()
        return fields[19], command.hex() if command else ""
    except OSError, IndexError:
        pass

    try:
        # 인코딩을 적는다 — `text=True`만 두면 로케일 기본으로 읽어서, cp949 호스트의
        # `ps` 출력에 한글 경로가 섞이는 순간 UnicodeDecodeError로 죽는다(저장소 계약).
        started = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1,
        )
        command = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1,
        )
    except OSError, subprocess.SubprocessError:
        return "", ""
    if started.returncode or command.returncode:
        return "", ""
    return started.stdout.strip(), command.stdout.strip()


def _pid_state(pid: int) -> str:
    try:
        os.kill(pid, 0)
        return "live"
    except ProcessLookupError:
        return "stale"
    except PermissionError:
        return "indeterminate"
    except OSError, OverflowError, ValueError:
        return "indeterminate"


def alive(record: dict) -> str:
    raw_pid = record.get("pid")
    if isinstance(raw_pid, bool) or not isinstance(raw_pid, (int, str)):
        return "indeterminate"
    try:
        pid = int(raw_pid)
    except ValueError:
        return "indeterminate"
    state = _pid_state(pid)
    if state != "live":
        return state
    expected_start = record.get("proc_start")
    expected_cmd = record.get("proc_cmd")
    if (
        not isinstance(expected_start, str)
        or not expected_start
        or not isinstance(expected_cmd, str)
        or not expected_cmd
    ):
        return "indeterminate"
    proc_start, proc_cmd = _proc_identity(pid)
    if not proc_start or not proc_cmd:
        return "stale" if _pid_state(pid) == "stale" else "indeterminate"
    if proc_start != expected_start or proc_cmd != expected_cmd:
        return "stale"
    return "live"


def _read() -> list[dict]:
    try:
        with open(runs_path(), encoding="utf-8") as handle:
            rows = json.load(handle)
    except OSError, ValueError:
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("id")]


def _write(rows: list[dict]) -> bool:
    path = runs_path()
    directory = os.path.dirname(path)
    try:
        os.makedirs(directory, exist_ok=True)
        tmp = os.path.join(directory, f".{RUNS_FILE}.{os.getpid()}.{_new_token(6)}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(rows, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            return True
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False
    except OSError:
        return False


def _acquire_lock() -> str:
    path = runs_path() + ".lock"
    token = _new_token(12)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return ""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(token)
            return token
        except FileExistsError:
            time.sleep(0.01)
        except OSError:
            return ""
    return ""


def _release_lock(token: str) -> None:
    path = runs_path() + ".lock"
    try:
        with open(path, encoding="utf-8") as handle:
            if handle.read() != token:
                return
        os.unlink(path)
    except OSError:
        pass


def _owned(record: dict, token: str = "") -> bool:
    if token:
        return record.get("token") == token
    if record.get("pid") != os.getpid():
        return False
    proc_start, proc_cmd = _proc_identity(os.getpid())
    return bool(
        proc_start and proc_cmd and record.get("proc_start") == proc_start and record.get("proc_cmd") == proc_cmd
    )


def register(agent, kind, host, port, url, root="", label="") -> dict:
    now = time.time()
    pid = os.getpid()
    proc_start, proc_cmd = _proc_identity(pid)
    record = {
        "id": _new_token(12),
        "agent": str(agent),
        "kind": str(kind),
        "host": str(host),
        "port": int(port),
        "url": str(url),
        "pid": pid,
        "proc_start": proc_start,
        "proc_cmd": proc_cmd,
        "token": _new_token(24),
        "root": str(root),
        "label": str(label),
        "started": now,
        "heartbeat": now,
    }
    lock = _acquire_lock()
    if not lock:
        return record
    try:
        rows = [row for row in _read() if row.get("id") != record["id"]]
        rows.append(record)
        _write(rows)
    finally:
        _release_lock(lock)
    return record


def heartbeat(run_id) -> bool:
    lock = _acquire_lock()
    if not lock:
        return False
    try:
        rows = _read()
        for row in rows:
            if row.get("id") == run_id and _owned(row):
                row["heartbeat"] = time.time()
                return _write(rows)
        return False
    finally:
        _release_lock(lock)


def unregister(run_id, token="") -> bool:
    lock = _acquire_lock()
    if not lock:
        return False
    try:
        rows = _read()
        for row in rows:
            if row.get("id") == run_id:
                if not _owned(row, token):
                    return False
                return _write([item for item in rows if item.get("id") != run_id])
        return False
    finally:
        _release_lock(lock)


def listing(prune=True) -> list[dict]:
    lock = _acquire_lock() if prune else ""
    try:
        rows = _read()
        visible = []
        kept = []
        for row in rows:
            state = alive(row)
            item = dict(row)
            item["state"] = state
            visible.append(item)
            if state != "stale":
                kept.append(row)
        if prune and lock and len(kept) != len(rows) and _write(kept):
            visible = [row for row in visible if row["state"] != "stale"]
        return visible
    finally:
        if lock:
            _release_lock(lock)


def find(agent=None, kind=None) -> list[dict]:
    return [
        row
        for row in listing()
        if (agent is None or row.get("agent") == agent) and (kind is None or row.get("kind") == kind)
    ]
