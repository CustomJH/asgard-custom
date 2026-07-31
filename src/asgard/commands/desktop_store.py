"""Desktop의 디스크 기억 — 작업 기록과 프로젝트 등록부.

여태 데스크탑의 작업은 프로세스 메모리 딕셔너리에만 있었다. 창을 닫으면 최근 작업도
산출물도 통째로 사라졌고, "산출물 0"은 아무것도 안 했다는 뜻이 아니라 **기억이 없다**는
뜻이었다. 이 계층이 그 절반을 디스크로 내린다.

자리:
  <프로젝트>/.asgard/desktop/tasks.jsonl   그 프로젝트의 작업 **상세** 기록 (경계는 프로젝트다)
  ~/.asgard/desktop/index.jsonl            어느 프로젝트에서 무엇을 했는지 (기계 단위 **머리글**)
  ~/.asgard/desktop/projects.json          어느 프로젝트들을 열어 봤는지 (기계 단위)
  ~/.asgard/desktop/workspace/             프로젝트가 없을 때 서는 개인 작업 공간

계약:
  · 작업의 **본문은 프로젝트에 속한다**. 로그·산출물·턴은 그 프로젝트 안에 남는다 —
    기계 전역 파일에 남의 프로젝트 본문을 섞으면 경계가 무너진다.
  · 작업의 **머리글은 기계에 속한다**. 창은 폴더가 아니라 사람의 것이라, 프로젝트를 열지
    않고도 "내가 최근에 뭘 하고 있었지"에 답할 수 있어야 한다. 색인이 그 답을 든다.
    색인은 편의지 정본이 아니다 — 지워도 프로젝트의 기록에서 다시 세울 수 있다.
  · 살아 있던 상태(running/queued/paused)는 프로세스와 함께 죽는다. 다시 읽을 때
    `interrupted`로 정규화한다 — 죽은 작업을 "실행 중"이라고 말하는 창은 계기가 아니다.
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
INDEX_FILE = "index.jsonl"
SCRATCH_DIR = "workspace"
KEEP_TASKS = 200  # 기록은 이력이지 보관소가 아니다 — 최근 것만 남긴다
KEEP_INDEX = 500  # 기계의 피드는 프로젝트 여럿을 겹쳐 든다 — 그만큼 더 길게
_ALIVE = frozenset({"running", "queued", "paused"})
_IO_LOCK = threading.Lock()

# 머리글에 싣는 칸 — 본문(log·turns·files)은 프로젝트 쪽에 두고 여기엔 안 싣는다.
_INDEX_KEYS = ("id", "root", "prompt", "label", "status", "created", "updated", "permission")
_PROMPT_HEAD = 300  # 목록의 한 줄이 드는 만큼만

# 이 폴더가 "프로젝트"인지 — 자리에 있는 표식으로만 판정한다. 없으면 아니라고 말하고,
# 사용자가 명시적으로 더한 것만 등록부에 들어간다(홈 디렉터리가 프로젝트가 되지 않게).
_PROJECT_MARKS = (
    ".git",
    ".asgard",
    ".hg",
    ".svn",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "composer.json",
    "CLAUDE.md",
    "AGENTS.md",
)

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


def index_path() -> str:
    return os.path.join(machine_dir(), INDEX_FILE)


def scratch_root() -> str:
    """프로젝트가 없을 때 서는 자리.

    창은 폴더가 아니라 사람의 것이다 — 아무 프로젝트도 안 열고도 물어보고 시켜야 한다.
    그렇다고 홈 디렉터리에서 돌리면 사용자의 집 전체가 작업 경계가 되고, `.asgard/`가
    거기에 생긴다. 그래서 **자기 자리**를 하나 판다: 여기는 아스가르드가 소유한 폴더라
    더럽혀도 남의 것을 안 건드린다."""
    return os.path.join(machine_dir(), SCRATCH_DIR)


def ensure_scratch() -> str:
    """개인 작업 공간을 자리에 만들어 돌려준다. 못 만들면 경로만 돌려준다 — 판단은 호출자 몫."""
    path = scratch_root()
    _ensure(path)
    return path


def is_scratch(root: str | None) -> bool:
    if not root:
        return False
    return os.path.abspath(root) == os.path.abspath(scratch_root())


def looks_like_project(path: str | None) -> bool:
    """이 폴더를 프로젝트로 볼 것인가 — 자리에 있는 표식으로만 판정한다.

    `asgard desktop`은 어디서든 실행될 수 있다(독에서 누르면 홈이나 `/` 다). 그때 cwd를
    말없이 프로젝트로 등록하면 등록부가 쓰레기가 되고, 사용자의 홈에
    `.asgard/desktop/`이 생긴다. 표식이 없으면 프로젝트가 아니라고 말한다."""
    if not path:
        return False
    target = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(target) or is_scratch(target):
        return False
    home = os.path.abspath(os.path.expanduser("~"))
    if target in {home, os.path.abspath(os.sep)}:
        return False  # 집과 뿌리는 프로젝트가 아니다 — 표식이 있어도
    return any(os.path.exists(os.path.join(target, mark)) for mark in _PROJECT_MARKS)


def last_project() -> str | None:
    """등록부에서 가장 최근에 열었고 아직 자리에 있는 프로젝트. 없으면 None."""
    for row in sorted(_read_projects(), key=lambda row: row.get("opened") or 0, reverse=True):
        root = row.get("root") or ""
        if root and os.path.isdir(root):
            return os.path.abspath(root)
    return None


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
    """디스크·API로 나가는 형태 — 내부 핸들 제거."""
    return {key: value for key, value in task.items() if key not in _DROP_KEYS}


def load_tasks(root: str) -> list[dict]:
    """그 프로젝트의 작업 기록. 살아 있던 상태는 interrupted로 정규화한다."""
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
    """기록 전체를 다시 쓴다 — 건수가 KEEP_TASKS라 추가 비용보다 단순함이 이긴다."""
    body = "".join(json.dumps(public_task(task), ensure_ascii=False) + "\n" for task in tasks[-KEEP_TASKS:])
    with _IO_LOCK:
        return _atomic_write(tasks_path(root), body)


def save_task(root: str, task: dict) -> bool:
    """한 건 upsert — 같은 id는 갈아 끼우고, 없으면 뒤에 붙인다.

    본문은 프로젝트에, 머리글은 기계에. 두 자리에 같은 순간 적히므로 목록과 상세가 어긋나지
    않는다. 색인 쓰기가 실패해도 본문 저장의 성패를 뒤집지 않는다 — 편의가 정본을 못 이긴다."""
    rows = [row for row in _read_raw(root) if row.get("id") != task.get("id")]
    rows.append(public_task(task))
    rows.sort(key=lambda row: row.get("created") or 0)
    saved = write_tasks(root, rows)
    try:
        index_task(root, task)
    except OSError:
        pass
    return saved


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


# ── 기계 단위 색인 — 프로젝트를 건너 보는 하나의 피드 ──────────────────────────────


def index_row(root: str, task: dict) -> dict:
    """작업 한 건의 **머리글**. 본문은 안 싣는다 — 색인은 목록이지 사본이 아니다."""
    row = {key: task.get(key) for key in _INDEX_KEYS if task.get(key) is not None}
    row["id"] = str(task.get("id") or "")
    row["root"] = os.path.abspath(row.get("root") or root)
    row["project"] = os.path.basename(row["root"]) or row["root"]
    row["prompt"] = str(row.get("prompt") or "")[:_PROMPT_HEAD]
    row["turns"] = len(task.get("turns") or ())  # 몇 번 오갔는지는 한 줄이면 든다
    return row


def read_index() -> list[dict]:
    rows: list[dict] = []
    try:
        with open(index_path(), encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("id") and row.get("root"):
                    rows.append(row)
    except OSError:
        return []
    return rows


def index_task(root: str, task: dict) -> bool:
    """머리글 한 건 upsert. 실패해도 조용히 넘어간다 — 색인이 실행을 막으면 색인이 아니다."""
    row = index_row(root, task)
    if not row["id"]:
        return False
    rows = [old for old in read_index() if old.get("id") != row["id"]]
    rows.append(row)
    rows.sort(key=lambda item: item.get("created") or 0)
    body = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows[-KEEP_INDEX:])
    with _IO_LOCK:
        return _atomic_write(index_path(), body)


def feed(limit: int = 200) -> list[dict]:
    """전 프로젝트의 최근 작업 — 최신 순.

    살아 있던 상태는 여기서도 `interrupted`로 정규화한다: 창을 새로 열었는데 남의
    프로젝트의 옛 작업이 '실행 중'으로 떠 있으면, 그 줄은 계기가 아니라 거짓말이다.
    자리에 없는 프로젝트의 줄은 `missing` 표시만 달고 남긴다 — 마운트 안 된 외장 디스크의
    이력을 조용히 지우는 쪽이 사용자가 더 크게 잃는다."""
    rows = read_index()
    for row in rows:
        if row.get("status") in _ALIVE:
            row["status"] = "interrupted"
        row["missing"] = not os.path.isdir(row.get("root", ""))
    rows.sort(key=lambda row: row.get("updated") or row.get("created") or 0, reverse=True)
    return rows[: max(1, limit)]


def reindex(roots: list[str]) -> int:
    """프로젝트들의 기록에서 색인을 다시 세운다 — 색인은 정본이 아니라는 것의 증명.

    (색인 파일을 지웠거나, 색인이 생기기 전에 만든 작업이 있는 프로젝트를 위해.)"""
    rows: list[dict] = []
    seen: set[str] = set()
    for root in roots:
        for task in load_tasks(root):
            task_id = str(task.get("id") or "")
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            rows.append(index_row(root, task))
    rows.sort(key=lambda row: row.get("created") or 0)
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows[-KEEP_INDEX:])
    with _IO_LOCK:
        _atomic_write(index_path(), body)
    return len(rows)


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


SCRATCH_NAME = "개인 작업 공간"


def list_projects(current: str | None = None) -> list[dict]:
    """열어 본 프로젝트들 — 최근 순. 현재 프로젝트는 등록부에 없어도 항상 포함된다.

    개인 작업 공간은 언제나 목록의 끝에 있다. 프로젝트를 하나도 안 연 사람에게도 설 자리가
    있어야 창이 열리기 때문이다 — 그건 등록의 결과가 아니라 앱의 성질이다."""
    rows = _read_projects()
    scratch = os.path.abspath(scratch_root())
    rows = [row for row in rows if os.path.abspath(row["root"]) != scratch]
    if current:
        current = os.path.abspath(current)
        if current != scratch and not any(os.path.abspath(row["root"]) == current for row in rows):
            rows.append({"root": current, "name": os.path.basename(current) or current, "opened": time.time()})
    for row in rows:
        row["exists"] = os.path.isdir(row.get("root", ""))
        row["current"] = bool(current) and os.path.abspath(row["root"]) == current
        row["scratch"] = False
    rows.sort(key=lambda row: row.get("opened") or 0, reverse=True)
    rows.append(
        {
            "root": scratch,
            "name": SCRATCH_NAME,
            "opened": 0,
            "exists": True,  # 없으면 만들어 쓰는 자리라 목록에서는 늘 있는 것으로 든다
            "current": bool(current) and os.path.abspath(current) == scratch,
            "scratch": True,
        }
    )
    return rows


_BROWSE_CAP = 400


def browse(path: str | None = None, *, show_hidden: bool = False) -> dict:
    """폴더 하나를 열어 그 **아래 폴더들만** 돌려준다 — 작업 공간을 고르는 눈이다.

    여태 작업 공간을 더하려면 경로를 손으로 적어야 했다. 경로는 사람이 외우는 것이 아니라
    **찾아가는 것**이라, 오타 하나면 "존재하는 디렉터리 경로가 필요합니다"만 돌아왔고 어디가
    틀렸는지는 아무도 안 알려 줬다.

    파일은 내지 않는다. 여기서 필요한 것은 자리를 고르는 일이지 안을 들여다보는 일이 아니고,
    이름만 내는 쪽이 낼 수 있는 것이 적어서 안전하다."""
    start = str(path or "").strip()
    target = os.path.abspath(os.path.expanduser(start)) if start else os.path.abspath(os.path.expanduser("~"))
    if not os.path.isdir(target):
        raise ValueError(f"{target}은(는) 폴더가 아닙니다")
    try:
        with os.scandir(target) as scan:
            rows = [
                {
                    "name": entry.name,
                    "path": os.path.join(target, entry.name),
                    "project": looks_like_project(os.path.join(target, entry.name)),
                }
                for entry in scan
                if entry.is_dir(follow_symlinks=False) and (show_hidden or not entry.name.startswith("."))
            ]
    except PermissionError as exc:
        raise ValueError(f"{target}을(를) 열 권한이 없습니다") from exc
    except OSError as exc:
        raise ValueError(f"{target}을(를) 읽지 못했습니다") from exc
    rows.sort(key=lambda row: row["name"].casefold())
    registered = {os.path.abspath(row["root"]) for row in _read_projects()}
    parent = os.path.dirname(target)
    return {
        "path": target,
        "name": os.path.basename(target) or target,
        # 뿌리에서는 부모가 자기 자신이다 — 그때는 위로 가는 문을 안 연다
        "parent": parent if parent and parent != target else "",
        "crumbs": _crumbs(target),
        "entries": rows[:_BROWSE_CAP],
        "truncated": len(rows) > _BROWSE_CAP,
        "home": os.path.abspath(os.path.expanduser("~")),
        "registered": os.path.abspath(target) in registered,
        "project": looks_like_project(target),
    }


def _crumbs(target: str) -> list[dict]:
    """뿌리부터 여기까지 — 눌러서 되돌아갈 수 있는 자리들."""
    out: list[dict] = []
    cursor = target
    while True:
        parent = os.path.dirname(cursor)
        out.append({"name": os.path.basename(cursor) or cursor, "path": cursor})
        if not parent or parent == cursor:
            break
        cursor = parent
    return list(reversed(out))[:24]


def add_project(path: str) -> dict:
    """경로를 등록부에 넣는다. 실제 디렉터리가 아니면 거부 — 없는 자리를 목록에 두지 않는다."""
    target = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not target or not os.path.isdir(target):
        raise ValueError("존재하는 디렉터리 경로가 필요합니다")
    if os.path.islink(target):
        raise ValueError("심링크는 프로젝트 경계로 쓰지 않습니다")
    if is_scratch(target):
        return {"root": target, "name": SCRATCH_NAME}  # 늘 있는 자리 — 등록부에 적지 않는다
    rows = [row for row in _read_projects() if os.path.abspath(row["root"]) != target]
    rows.append({"root": target, "name": os.path.basename(target) or target, "opened": time.time()})
    rows.sort(key=lambda row: row.get("opened") or 0, reverse=True)
    with _IO_LOCK:
        _atomic_write(projects_path(), json.dumps({"projects": rows[:50]}, ensure_ascii=False, indent=1))
    return {"root": target, "name": os.path.basename(target) or target}


def remove_project(path: str) -> bool:
    """등록부에서만 지운다 — 디스크의 프로젝트는 건드리지 않는다."""
    target = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if is_scratch(target):
        return False  # 개인 작업 공간은 앱의 일부라 목록에서 뺄 수 없다
    rows = _read_projects()
    kept = [row for row in rows if os.path.abspath(row["root"]) != target]
    if len(kept) == len(rows):
        return False
    with _IO_LOCK:
        _atomic_write(projects_path(), json.dumps({"projects": kept}, ensure_ascii=False, indent=1))
    return True


def prune_projects(current: str | None = None) -> int:
    """자리에 없는 등록만 걷어낸다 — 지운 개수를 돌려준다.

    등록부는 자동으로 줄지 않는다: 마운트 안 된 외장 디스크의 프로젝트를 조용히 잊으면
    사용자가 잃는 쪽이 크다. 그래서 정리는 사용자가 부를 때만 한다. 현재 경계는 언제나 남긴다."""
    rows = _read_projects()
    keep_current = os.path.abspath(current) if current else None
    kept = [row for row in rows if os.path.isdir(row.get("root", "")) or os.path.abspath(row["root"]) == keep_current]
    removed = len(rows) - len(kept)
    if removed:
        with _IO_LOCK:
            _atomic_write(projects_path(), json.dumps({"projects": kept}, ensure_ascii=False, indent=1))
    return removed


def touch_project(path: str) -> None:
    """열었다는 사실만 기록 — 실패해도 조용히 넘어간다(등록부는 편의지 정본이 아니다)."""
    try:
        add_project(path)
    except ValueError, OSError:
        pass


def known_roots(current: str | None = None) -> list[str]:
    """색인을 다시 세울 때 훑을 자리들 — 등록부 + 개인 작업 공간 + 지금 보는 경계."""
    roots = [row["root"] for row in list_projects(current) if row.get("exists")]
    return list(dict.fromkeys(os.path.abspath(root) for root in roots if root))
