"""Desktop 의 디스크 기억 — 작업 기록과 프로젝트 등록부.

여태 데스크탑의 작업은 프로세스 메모리 딕셔너리에만 있었다. 창을 닫으면 최근 작업도
산출물도 통째로 사라졌고, "산출물 0" 은 아무것도 안 했다는 뜻이 아니라 **기억이 없다**는
뜻이었다. 이 계층이 그 절반을 디스크로 내린다.

자리:
  <프로젝트>/.asgard/desktop/tasks.jsonl   그 프로젝트의 작업 기록 (경계는 프로젝트다)
  ~/.asgard/desktop/projects.json          어느 프로젝트들을 열어 봤는지 (기계 단위)

계약:
  · 작업은 **프로젝트에 속한다**. 데스크탑을 다른 프로젝트로 옮기면 그 프로젝트의 기록을 본다.
    기계 전역 목록에 섞으면 경계가 무너지고, 그건 Canon 의 프로젝트 경계를 UI 가 깨는 것이다.
  · 살아 있던 상태(running/queued/paused)는 프로세스와 함께 죽는다. 다시 읽을 때
    `interrupted` 로 정규화한다 — 죽은 작업을 "실행 중"이라고 말하는 창은 계기가 아니다.
  · 실패해도 화면은 산다(fail-open). 기록이 없어서 화면이 안 뜨는 것이 더 나쁜 고장이다.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time

DESKTOP_HOME_ENV = "ASGARD_DESKTOP_HOME"
DESKTOP_DIR = os.path.join(".asgard", "desktop")
TASKS_FILE = "tasks.jsonl"
PROJECTS_FILE = "projects.json"
KEEP_TASKS = 200  # 기록은 이력이지 보관소가 아니다 — 최근 것만 남긴다
_ALIVE = frozenset({"running", "queued", "paused"})
_IO_LOCK = threading.Lock()

# 프로세스 핸들·명령줄은 디스크로 안 내린다 (핸들은 의미가 없고, 명령줄은 재실행 유혹이다)
_DROP_KEYS = frozenset({"process", "command", "stopped"})


def store_dir(root: str) -> str:
    return os.path.join(os.path.abspath(root), DESKTOP_DIR)


def tasks_path(root: str) -> str:
    return os.path.join(store_dir(root), TASKS_FILE)


def machine_dir() -> str:
    """기계 단위 자리. 환경변수로 옮길 수 있어야 테스트가 사용자의 홈을 더럽히지 않는다
    (실측: 등록부가 없던 첫 판에서 테스트의 임시 디렉터리들이 실제 목록에 쌓였다)."""
    override = os.environ.get(DESKTOP_HOME_ENV)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(os.path.expanduser("~"), ".asgard", "desktop")


def projects_path() -> str:
    return os.path.join(machine_dir(), PROJECTS_FILE)


def _ensure(path: str) -> bool:
    """디렉터리 보장 — 심링크 홈은 거부한다(경계 보전)."""
    try:
        if os.path.islink(path):
            return False
        os.makedirs(path, exist_ok=True)
        return True
    except OSError:
        return False


def _atomic_write(path: str, text: str) -> bool:
    """같은 디렉터리 임시파일 → replace. 반쯤 쓰인 기록은 없는 기록보다 나쁘다."""
    directory = os.path.dirname(path)
    if not _ensure(directory):
        return False
    try:
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".swap")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
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


def public_task(task: dict) -> dict:
    """디스크·API 로 나가는 형태 — 내부 핸들 제거."""
    return {key: value for key, value in task.items() if key not in _DROP_KEYS}


def load_tasks(root: str) -> list[dict]:
    """그 프로젝트의 작업 기록. 살아 있던 상태는 interrupted 로 정규화한다."""
    path = tasks_path(root)
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # 잘린 줄 하나가 이력 전체를 못 삼키게 한다
                if isinstance(row, dict) and row.get("id"):
                    rows.append(row)
    except OSError:
        return []
    for row in rows:
        if row.get("status") in _ALIVE:
            row["status"] = "interrupted"
            row.setdefault("result", "")
            row["interrupted_at"] = row.get("interrupted_at") or time.time()
    return rows[-KEEP_TASKS:]


def write_tasks(root: str, tasks: list[dict]) -> bool:
    """기록 전체를 다시 쓴다 — 건수가 KEEP_TASKS 라 추가 비용보다 단순함이 이긴다."""
    body = "".join(json.dumps(public_task(task), ensure_ascii=False) + "\n" for task in tasks[-KEEP_TASKS:])
    with _IO_LOCK:
        return _atomic_write(tasks_path(root), body)


def save_task(root: str, task: dict) -> bool:
    """한 건 upsert — 같은 id 는 갈아 끼우고, 없으면 뒤에 붙인다."""
    rows = [row for row in _read_raw(root) if row.get("id") != task.get("id")]
    rows.append(public_task(task))
    rows.sort(key=lambda row: row.get("created") or 0)
    return write_tasks(root, rows)


def _read_raw(root: str) -> list[dict]:
    """정규화 없이 원문 그대로 — 저장 경로가 상태를 덮어쓰지 않게 한다."""
    path = tasks_path(root)
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("id"):
                    rows.append(row)
    except OSError:
        return []
    return rows


# ── 프로젝트 등록부 ────────────────────────────────────────────────────────────


def _read_projects() -> list[dict]:
    try:
        with open(projects_path(), encoding="utf-8") as handle:
            raw = json.load(handle)
    except OSError, ValueError:
        return []
    rows = raw.get("projects") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("root")]


def list_projects(current: str | None = None) -> list[dict]:
    """열어 본 프로젝트들 — 최근 순. 현재 프로젝트는 등록부에 없어도 항상 포함된다."""
    rows = _read_projects()
    if current:
        current = os.path.abspath(current)
        if not any(os.path.abspath(row["root"]) == current for row in rows):
            rows.append({"root": current, "name": os.path.basename(current) or current, "opened": time.time()})
    for row in rows:
        row["exists"] = os.path.isdir(row.get("root", ""))
        row["current"] = bool(current) and os.path.abspath(row["root"]) == current
    rows.sort(key=lambda row: row.get("opened") or 0, reverse=True)
    return rows


def add_project(path: str) -> dict:
    """경로를 등록부에 넣는다. 실제 디렉터리가 아니면 거부 — 없는 자리를 목록에 두지 않는다."""
    target = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not target or not os.path.isdir(target):
        raise ValueError("존재하는 디렉터리 경로가 필요합니다")
    if os.path.islink(target):
        raise ValueError("심링크는 프로젝트 경계로 쓰지 않습니다")
    rows = [row for row in _read_projects() if os.path.abspath(row["root"]) != target]
    rows.append({"root": target, "name": os.path.basename(target) or target, "opened": time.time()})
    rows.sort(key=lambda row: row.get("opened") or 0, reverse=True)
    with _IO_LOCK:
        _atomic_write(projects_path(), json.dumps({"projects": rows[:50]}, ensure_ascii=False, indent=1))
    return {"root": target, "name": os.path.basename(target) or target}


def remove_project(path: str) -> bool:
    """등록부에서만 지운다 — 디스크의 프로젝트는 건드리지 않는다."""
    target = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    rows = _read_projects()
    kept = [row for row in rows if os.path.abspath(row["root"]) != target]
    if len(kept) == len(rows):
        return False
    with _IO_LOCK:
        _atomic_write(projects_path(), json.dumps({"projects": kept}, ensure_ascii=False, indent=1))
    return True


def touch_project(path: str) -> None:
    """열었다는 사실만 기록 — 실패해도 조용히 넘어간다(등록부는 편의지 정본이 아니다)."""
    try:
        add_project(path)
    except ValueError, OSError:
        pass
