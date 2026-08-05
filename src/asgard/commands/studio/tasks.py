"""작업의 수명 — 만들고, 돌리고, 이어 가고, 승인하고, 멈춘다.

`asgard run`을 자식 프로세스로 띄우는 것이 실제 실행이다. 이 모듈이 지는 것은 그 둘레다:
어느 자리에서 돌지, 무엇을 바꿨는지, 기록에 어떻게 남는지, 그리고 티켓에서 시작한 일이면
그 티켓을 어떻게 되돌려 놓을지.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextvars import copy_context

from ... import (
    activity,
    errors,
    profiles,
    ui,  # noqa: F401  (하위 호환 — 이 모듈은 ui를 직접 쓰지 않는다)
)
from .. import loopback
from . import state
from .boundary import resolve_workspace, task_root, workspace_label

_json_body = loopback.json_body
_TASKS = state._TASKS
_TASK_LOCK = state._TASK_LOCK
_LOADED_ROOTS = state._LOADED_ROOTS
_ROOT_LOCK = state._ROOT_LOCK
_MAX_RUNNING = state._MAX_RUNNING
_PROMPT_CAP = state._PROMPT_CAP
_LOG_CAP = state._LOG_CAP
_trim = state.trim


def _public_task(task: dict) -> dict:
    return {k: v for k, v in task.items() if k not in {"process", "command"}}


def _task_agent(task: dict) -> str:
    # agent가 없던 기록은 default의 작업이다. 다른 프로파일에 공개하지 않는다.
    return profiles.normalize(str(task.get("agent") or profiles.DEFAULT))


def _visible_task(task: dict) -> bool:
    return _task_agent(task) == profiles.active()


def _task_snapshot(root: str | None = None) -> list[dict]:
    """작업은 작업 공간에 속한다 — root를 주면 그 경계 안의 것만 돌려준다.
    (기록이 없던 시절의 작업은 root가 없다. 그건 어느 경계에도 안 걸리게 두지 않고
    현재 작업 공간 것으로 본다 — 안 그러면 옛 작업이 화면에서 통째로 사라진다.)"""
    with _TASK_LOCK:
        rows = [_public_task(task) for task in _TASKS.values() if _visible_task(task)]
    if root:
        target = os.path.abspath(root)
        rows = [row for row in rows if os.path.abspath(str(row.get("root") or target)) == target]
    return sorted(rows, key=lambda row: row["created"], reverse=True)


def _feed_snapshot(root: str, limit: int = 200) -> list[dict]:
    """프로젝트를 건너 보는 하나의 대화 목록 — 이 창의 사이드바가 드는 것.

    두 곳을 겹친다: 지금 살아 있는 메모리의 작업(가장 최신)과 디스크의 기계 색인(어제까지의
    것, 남의 프로젝트 것까지). 같은 id는 메모리 쪽이 우선한다 — 돌고 있는 작업의 상태를
    디스크의 옛 줄이 덮으면 화면이 뒤로 간다."""
    from .. import studio_store

    try:
        rows = {row["id"]: row for row in studio_store.feed(limit)}
    except Exception:
        rows = {}
    for task in _task_snapshot():
        live = studio_store.index_row(task.get("root") or root, task)
        live["missing"] = not os.path.isdir(live["root"])
        rows[live["id"]] = live
    ordered = sorted(rows.values(), key=lambda row: row.get("updated") or row.get("created") or 0, reverse=True)
    current = os.path.abspath(root)
    for row in ordered:
        row["here"] = row.get("root") == current
        row["scratch"] = studio_store.is_scratch(row.get("root"))
        if row["scratch"]:
            row["project"] = studio_store.SCRATCH_NAME
    return ordered[:limit]


def _remember(root: str, task: dict) -> None:
    """작업 한 건을 그 프로젝트의 기록에 남긴다. 실패해도 실행은 계속된다 — 기록이 실행을
    막으면 기록이 아니라 관문이 된다."""
    from .. import studio_store

    try:
        studio_store.save_task(root, _public_task(task))
    except Exception:
        pass


def load_project_tasks(root: str) -> int:
    """그 프로젝트의 기록을 메모리로 올린다. 프로젝트당 1회 — 재방문이 이력을 겹쳐 넣지 않게."""
    from .. import studio_store

    root = os.path.abspath(root)
    loaded = (profiles.active(), root)
    with _ROOT_LOCK:
        if loaded in _LOADED_ROOTS:
            return 0
        _LOADED_ROOTS.add(loaded)
    try:
        rows = studio_store.load_tasks(root)
    except Exception:
        return 0
    added = 0
    with _TASK_LOCK:
        for row in rows:
            task_id = str(row.get("id") or "")
            if task_id and task_id not in _TASKS:
                row.setdefault("files", [])
                row.setdefault("usage", {})
                row.setdefault("root", root)
                row.setdefault("activity", [])  # 활동을 모르던 시절의 기록 — 빈 목록이 정직하다
                row.setdefault("todos", [])
                _TASKS[task_id] = row
                added += 1
    return added


# 티어가 아스가르드에서 뜻하는 바. 모델 홍보 문구가 아니라 **이 저장소가 티어를 쓰는 방식**이다


def _git_branch(root: str) -> str:
    """이 자리가 지금 서 있는 가지. 저장소가 아니면 빈 문자열이다.

    독이 이 값을 쓴다 — 보내기 직전에 **어느 가지에 손대게 되는지**가 보여야 한다. 여태
    창은 폴더만 말했고, 같은 폴더의 다른 가지는 같은 얼굴이었다."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    name = result.stdout.strip()
    # 분리된 HEAD는 가지 이름이 없다 — 'HEAD'라고 적으면 그게 가지 이름인 줄 안다
    return "" if name in ("", "HEAD") else name[:80]


def _workspace_files(root: str) -> list[dict]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return []
    rows = []
    for line in result.stdout.splitlines()[:100]:
        if len(line) >= 4:
            rows.append({"status": line[:2].strip() or "?", "path": line[3:]})
    return rows


def _changed_by_task(root: str, before: list[dict]) -> list[dict]:
    """이 작업이 실제로 바꾼 것만 남긴다.

    여태는 끝난 뒤의 `git status`를 통째로 실었다. 그래서 README 한 줄만 읽고 끝난 작업이
    '변경 파일 14개'를 달고 산출물 목록에 올라왔다 — 사용자가 이미 들고 있던 더러운 트리였다.
    작업 시작 시점의 상태와 견주어 새로 생겼거나 상태가 달라진 줄만 그 작업의 몫이다."""
    baseline = {row["path"]: row["status"] for row in before}
    return [row for row in _workspace_files(root) if baseline.get(row["path"]) != row["status"]]


def _signal_group(process: subprocess.Popen, sig: int) -> None:
    """멈춤도 재개도 **무리 전체**에 건다 — 맨 앞의 프로세스 하나가 아니라.

    자식 하나에만 SIGSTOP을 걸면 멈추는 것은 껍데기다. 모델을 실제로 부르는 것은 그 아래의
    CLI라서, 창은 '일시정지'라고 적는데 토큰은 그대로 나갔다(실측: 부모는 T, 자식은 S).
    `_run_task`가 `start_new_session`으로 띄우니 이 무리는 그 작업만의 것이다 — 무리째 걸어도
    창이나 다른 작업에 번지지 않는다."""
    try:
        os.killpg(os.getpgid(process.pid), sig)
    except ProcessLookupError, PermissionError, OSError:
        # 무리를 못 찾는 자리(윈도우, 이미 거둬진 프로세스)에서는 최소한 앞의 하나라도
        try:
            process.send_signal(sig)
        except ProcessLookupError, OSError:
            pass


def _run_task(task_id: str, root: str) -> None:
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return
        # 띄우기 전에 이미 '그만'이라고 했으면 띄우지 않는다 — 중지는 프로세스가 뜬 뒤에만
        # 듣는 명령이 아니다(줄 서 있는 동안 누른 중지가 여태 조용히 버려졌다).
        if task.get("stopped"):
            return
        task["status"] = "running"
        task["updated"] = time.time()
        task["activity"] = []
        task["now"] = None
        command = list(task["command"])
        snapshot = _public_task(task)
    _remember(root, snapshot)
    before = _workspace_files(root)  # 이 작업이 무엇을 바꿨는지는 시작 상태와 견줘야 안다
    # 활동 파일은 **띄우기 전에** 만든다. 자식이 첫 줄을 적기 전에 읽는 쪽이 붙어 있어야
    # 시작 직후의 사건을 안 놓친다 (그 몇 초가 사람이 화면을 제일 오래 보는 구간이다).
    try:
        events = activity.open_log(root, task_id)
    except OSError:
        events = ""  # 활동 파일을 못 만들어도 실행은 돈다 — 관측이 실행을 막지 않는다
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "ASGARD_UNATTENDED": "1", **({activity.ENV_PATH: events} if events else {})},
            start_new_session=os.name == "posix",
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            encoding="utf-8",
            errors="replace",
        )
        if not _claim(task_id, process):
            from ...agent.tools import _kill_group

            _kill_group(process)
            return
        drain = _watch(task_id, events) if events else None
        # `communicate()`는 여전히 이 스레드를 붙잡는다 — 그래도 되는 이유는 화면이 이 스레드를
        # 안 보기 때문이다. 창은 `_TASKS`를 읽고, 그 사전은 아래 감시 스레드가 갱신한다.
        stdout, stderr = process.communicate()
        # 마무리보다 **먼저** 감시를 닫는다. 둘을 나란히 두면 `_finish`가 '지금'을 비우는 것과
        # 감시가 마지막 완료를 접어 넣는 것이 겹쳐서, 마지막 도구 한 줄이 짝을 잃고 이름 없이
        # 기록된다 (실측: 끝나는 순간의 도구만 detail이 빈 문자열이었다).
        if drain is not None:
            drain()
        _finish(task_id, root, process, stdout, stderr, before)
    except Exception as exc:
        _blame(task_id, root, exc)


_ACTIVITY_CAP = 120  # 화면이 드는 최근 활동 줄 수 — 그 위는 사람이 안 읽고 기록만 무거워진다


_DRAIN_GRACE = 5.0  # 마지막 한 바퀴를 기다려 주는 상한 — 이 위로는 작업 마무리가 더 급하다


def _watch(task_id: str, events: str):
    """활동 파일을 따라 읽어 그 작업의 '지금'을 갱신한다. 돌려주는 것은 **닫는 손잡이**다.

    자식이 끝난 뒤에도 한 바퀴를 더 돈다: 마지막 툴의 완료 줄이 프로세스 종료와 같은 순간에
    적히므로, 신호를 보자마자 그만두면 그 한 줄이 늘 빠진다. 닫는 손잡이가 그 한 바퀴를
    기다려 주므로, 부르는 쪽은 이 함수가 돌아온 뒤에 마음 놓고 작업을 마무리할 수 있다."""
    done = threading.Event()

    def loop() -> None:
        offset = 0
        while True:
            finished = done.is_set()
            rows, offset = activity.read_log(events, offset)
            if rows:
                _absorb(task_id, rows)
            if finished:
                return
            done.wait(0.35)

    context = copy_context()
    thread = threading.Thread(target=context.run, args=(loop,), daemon=True)
    thread.start()

    def close() -> None:
        done.set()
        thread.join(timeout=_DRAIN_GRACE)

    return close


def _absorb(task_id: str, rows: list[dict]) -> None:
    """읽어 온 활동을 그 작업에 접어 넣는다 — 창이 그대로 그릴 수 있는 모양으로.

    창은 스트림이 아니라 **현재 상태**를 그린다. 그래서 여는 사건과 닫는 사건을 여기서 짝지어
    한 줄로 만든다: 도는 동안은 `now`(기호·한 줄·시작시각)로 서 있다가, 끝나면 소요시간을 달고
    `activity`의 꼬리로 내려간다. 짝을 못 찾은 완료는 버리지 않고 그대로 남긴다 — 놓친 시작보다
    잘못 지운 완료가 화면을 더 망친다."""
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if task is None:
            return
        log: list[dict] = task.setdefault("activity", [])
        for row in rows:
            kind = row.get("kind")
            if kind == "tool.start":
                task["now"] = {
                    "id": row.get("id"),
                    "sym": row.get("sym") or "⚙︎",
                    "detail": row.get("detail") or "",
                    "role": row.get("role") or "",
                    "ts": row.get("ts") or time.time(),
                }
            elif kind == "tool.end":
                now = task.get("now") or {}
                started = now.get("ts") if now.get("id") == row.get("id") else None
                log.append(
                    {
                        "kind": "tool",
                        "sym": now.get("sym") or "⚙︎",
                        "detail": now.get("detail") or "",
                        "role": row.get("role") or now.get("role") or "",
                        "ok": bool(row.get("ok")),
                        "secs": row.get("secs"),
                        "ts": started or row.get("ts") or time.time(),
                    }
                )
                if now.get("id") == row.get("id"):
                    task["now"] = None
            elif kind == "thought":
                log.append({"kind": "thought", "secs": row.get("secs"), "ts": row.get("ts"), "label": row.get("label")})
            elif kind == "role":
                task["step"] = {"role": row.get("role") or "", "why": row.get("why") or ""}
                log.append(
                    {"kind": "role", "role": row.get("role") or "", "why": row.get("why") or "", "ts": row.get("ts")}
                )
            elif kind == "todo":
                task["todos"] = row.get("items") or []
            elif kind == "run.end":
                task["now"] = None
        if len(log) > _ACTIVITY_CAP:
            del log[: len(log) - _ACTIVITY_CAP]
        task["updated"] = time.time()


def _claim(task_id: str, process: subprocess.Popen) -> bool:
    """띄운 프로세스를 그 작업의 것으로 붙인다 — 아직 중지를 안 눌렀다면.

    띄우는 사이에 중지가 들어왔을 수 있다. 그 짧은 사이도 창에서는 '실행 중'으로 보이니 사람은
    당연히 중지를 누른다 — 그때 눌린 뜻을 여기서 거둔다. False면 부르는 쪽이 프로세스를 거둔다."""
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if task is None or task.get("stopped"):
            return False
        task["process"] = process
        return True


def _finish(task_id: str, root: str, process: subprocess.Popen, stdout: str, stderr: str, before: list[dict]) -> None:
    """끝난 프로세스를 작업에 적어 넣고 티켓까지 되돌려 놓는다."""
    payload: dict = {}
    for line in reversed(stdout.splitlines()):
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            payload = parsed
            break
    status = "ready" if process.returncode == 0 else "blocked"
    failure = _failure_of(payload, process.returncode, stdout, stderr)
    result = failure["message"] if failure else str(payload.get("result") or stdout.strip() or stderr.strip())
    finished: dict = {}
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        # 중지된 작업에는 결과를 안 적는다 — 사람이 그만이라고 한 뒤에 도착한 답이다
        if task and not task.get("stopped"):
            task.update(
                {
                    "status": status,
                    "updated": time.time(),
                    "now": None,  # 끝난 작업에 '지금 이걸 하는 중'이 남아 있으면 화면이 안 멈춘다
                    "exit_code": process.returncode,
                    "result": _trim(result),
                    # 구조화된 사유는 결과 문자열과 **따로** 든다. 창이 사유를 보여 주려고
                    # 결과 문장을 되파싱하면, 문구를 바꾸는 순간 화면이 조용히 깨진다.
                    "error": failure,
                    "log": _trim(stderr),
                    "usage": {
                        key: payload.get(key)
                        for key in ("tokens", "cache_read_tokens", "wall_s", "provider", "model")
                        if payload.get(key) is not None
                    },
                    "files": _changed_by_task(root, before),
                    "turns": [
                        *(task.get("turns") or []),
                        {"role": "agent", "text": _trim(result), "ts": time.time()},
                    ],
                }
            )
            finished = _public_task(task)
        if task:
            task.pop("process", None)
    if finished:
        _remember(root, finished)
        _settle_ticket(root, finished)


def _blame(task_id: str, root: str, exc: Exception) -> None:
    """프로세스를 못 띄운 것도 실패의 한 갈래다 — 창에는 같은 모양으로 도착해야 한다."""
    wrapped = errors.coerce(exc, code="task_spawn_failed").to_dict()
    errors.record(root, errors.coerce(exc, code="task_spawn_failed"), surface="studio", where="tasks._run_task")
    failed: dict = {}
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if task:
            task.update(
                {
                    "status": "blocked",
                    "updated": time.time(),
                    "now": None,
                    "exit_code": 1,
                    "result": wrapped["message"],
                    "error": wrapped,
                }
            )
            task.pop("process", None)
            failed = _public_task(task)
    if failed:
        _remember(root, failed)


def _failure_of(payload: dict, code: int, stdout: str, stderr: str) -> dict | None:
    """끝난 프로세스에서 **구조화된 사유**를 꺼낸다 — 못 꺼내면 만들어서라도 돌려준다.

    좋은 경우는 자식이 `{"error": {...}}`를 냈을 때다. 그러면 코드·처방·상세가 그대로 있다.
    문제는 안 그런 경우인데, 여태 그 자리가 화면을 망가뜨렸다: 사유가 없으면 stdout 원문을
    결과라고 불렀고, 그래서 터미널용 체크리스트가 창의 결과 칸에 통째로 들어갔다.

    그래서 사유가 없으면 **여기서 하나 세운다**. 마지막 의미 있는 줄을 메시지로 삼고 원문은
    `detail.output`으로 내린다 — 창은 한 줄을 보여 주고, 원문은 펼쳐야 보인다. 0으로 끝난
    프로세스는 실패가 아니므로 None이다."""
    envelope = payload.get("error")
    if isinstance(envelope, dict) and envelope.get("message"):
        return {
            "code": str(envelope.get("code") or "error"),
            "message": str(envelope["message"]),
            **({"remedy": str(envelope["remedy"])} if envelope.get("remedy") else {}),
            **({"detail": envelope["detail"]} if isinstance(envelope.get("detail"), dict) else {}),
        }
    if code == 0:
        return None
    raw = (stderr.strip() or stdout.strip() or "").strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    head = lines[-1] if lines else f"작업이 종료 코드 {code}로 끝났어요."
    # 여기서는 앞을 남긴다 — `state.trim`은 로그용이라 꼬리를 남기지만, 표제는 첫머리가 뜻이다.
    return {
        "code": "task_failed",
        "message": head[:400],
        "detail": {"exit_code": code, "output": raw[-4000:]},
    }


def _settle_ticket(root: str, task: dict) -> None:
    """끝난 작업이 티켓에서 나온 것이면 그 티켓에 결과를 돌려준다.

    성공은 **완료가 아니라 검토 중**으로 옮긴다 — 프로세스가 0으로 끝났다는 것은 사람이
    받아들였다는 뜻이 아니다. 실패는 상태를 안 건드리고 댓글만 남긴다: 안 된 일을 자동으로
    되돌려 놓으면 무엇이 왜 막혔는지가 보드에서 사라진다.
    이 되먹임이 실패해도 작업은 이미 끝났다 — 조용히 넘어간다(기록이 실행을 막지 않는다)."""
    from ...studio import tickets as T

    task_id = str(task.get("id") or "")
    if not task_id:
        return
    try:
        for ticket in T.tickets_for_task(root, task_id):
            summary = " ".join(str(task.get("result") or "").split())[:600]
            if task.get("status") == "ready":
                if ticket["status"] == "in_progress":
                    T.update_ticket(root, ticket["key"], {"status": "in_review"}, actor="studio")
                T.add_comment(root, ticket["key"], summary or "작업이 끝났어요.", author="studio")
            else:
                T.add_comment(root, ticket["key"], f"작업이 막혔어요 — {summary}", author="studio")
    except Exception:
        pass


def _start(task_id: str, root: str) -> None:
    context = copy_context()
    threading.Thread(target=context.run, args=(_run_task, task_id, root), daemon=True).start()


def create_task(payload: dict, root: str) -> tuple[int, str, bytes]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt or len(prompt) > _PROMPT_CAP:
        return _json_body(400, {"error": "prompt required (max 20000 chars)"})
    # 어디서 돌릴지는 **이 대화**가 정한다 — 창이 어느 프로젝트를 보고 있든.
    root, failed = resolve_workspace(payload.get("root"), root)
    if failed:
        return _json_body(400, {"error": failed})
    label = str(payload.get("label") or "").strip()
    if len(label) > 200:
        return _json_body(400, {"error": "label must be at most 200 characters"})
    permission = str(payload.get("permission") or "important")
    if permission not in {"manual", "important", "auto"}:
        return _json_body(400, {"error": "unknown permission mode"})
    with _TASK_LOCK:
        running = sum(
            task.get("status") in {"queued", "running", "paused"} for task in _TASKS.values() if _visible_task(task)
        )
        if running >= _MAX_RUNNING:
            return _json_body(409, {"error": "too many running tasks"})
    provider = str(payload.get("provider") or "").strip()
    model = str(payload.get("model") or "").strip()
    agent, failed = _resolve_agent(payload.get("agent"))
    if failed:
        return _json_body(400, {"error": failed})
    command = _run_command(prompt, agent, provider, model)
    now = time.time()
    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "prompt": prompt,
        **({"label": label} if label else {}),
        "status": "needs_input" if permission in {"manual", "important"} else "queued",
        "created": now,
        "updated": now,
        "permission": permission,
        "provider": provider,
        "model": model,
        "agent": agent,  # 누가 돌았는가 — 기록의 일부다(빈 값은 default)
        "result": "",
        "log": "",
        "files": [],
        "usage": {},
        # 도는 동안 화면이 드는 것 — 지금 쓰는 도구 하나(now)와 지나간 것들(activity),
        # 그리고 이 퀘스트가 실제로 밟은 단계(step)와 배정 단위(todos).
        "now": None,
        "activity": [],
        "todos": [],
        # 한 작업 = 한 퀘스트. 턴이 쌓여도 퀘스트 로그의 줄은 하나다.
        "turns": [{"role": "user", "text": prompt, "ts": now}],
        "root": root,  # 작업은 작업 공간에 속한다 — 어느 경계에서 돌았는지가 기록의 일부다
        "approval": {
            "action": "로컬 Asgard 작업 실행",
            "reason": f"{workspace_label(root)}에서 이 작업을 돌리려면 승인이 필요해요.",
            "scope": root,
            "target": f"{workspace_label(root)}의 파일과 허용된 도구",
            "reversible": "Git 변경은 검토한 뒤 되돌릴 수 있어요. 외부 작업은 돌릴 때 별도 정책을 따라요.",
        },
        "command": command,
    }
    with _TASK_LOCK:
        _TASKS[task_id] = task
    _remember(root, task)
    if task["status"] == "queued":
        _start(task_id, root)
    return _json_body(202, _public_task(task))


def _run_command(prompt: str, agent: str, provider: str, model: str) -> list[str]:
    """자식으로 띄울 명령 한 줄.

    `--agent`는 하위 명령보다 먼저 평가되는 루트 옵션이라 **`run` 앞에** 서야 한다 —
    뒤에 두면 typer가 run의 인자로 읽고 거절한다."""
    command = [sys.executable, "-m", "asgard"]
    if agent:
        command += ["--agent", agent]
    command += ["run", prompt, "--json"]
    if provider:
        command += ["--provider", provider]
    if model:
        command += ["--model", model]
    return command


def _resolve_agent(wanted: object) -> tuple[str, str]:
    """이 이름으로 돌 수 있는가 — 돌 이름과 거절 사유 중 하나만 채워 돌려준다.

    빈 값은 이 창의 활성 에이전트다. default는 기존 명령 형식을 유지하려고 빈 값으로 둔다.
    아직 안 세운 이름만 막는다.
    여기서 미리 판정하는 이유는, 없는 에이전트로 띄우면 실패가 프로세스 로그 안쪽에만
    남아서다 — 창은 '실행 중'을 그리다 조용히 끝난 작업 하나를 보게 된다."""
    from ... import profiles

    name = str(wanted or "").strip()
    if not name:
        active = profiles.active()
        return ("" if active == profiles.DEFAULT else active), ""
    try:
        name = profiles.validate(name)
    except Exception as exc:
        return "", str(exc)
    if not profiles.exists(name):
        made = ", ".join(row["id"] for row in profiles.listing()) or "default"
        return "", f"{name} 에이전트가 아직 없어요 — 세운 에이전트는 {made}예요"
    return name, ""


_TICKET_BRIEF = "아래 티켓 하나를 끝내라. 끝나면 무엇을 바꿨는지 한 줄로 보고한다."


def _ticket_workspace(ticket: dict, fallback: str) -> str:
    """이 티켓이 도는 자리 — 티켓이 적어 둔 폴더, 그다음 그 팀에 결속된 폴더, 없으면 창의 자리.

    자리가 사라졌으면 없는 것으로 친다: 지워진 경로에서 돌리려다 죽는 것보다, 창이 보는
    자리에서 돌고 사람이 옮기는 편이 낫다."""
    from ...studio import teams as TM

    candidates = [str(ticket.get("root") or "")]
    key = (ticket.get("team") or {}).get("key") or ""
    if key:
        try:
            candidates += list(TM.get_team(key).get("roots") or ())
        except Exception:
            pass
    for candidate in candidates:
        if candidate and os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return fallback


def run_ticket(payload: dict, root: str) -> tuple[int, str, bytes]:
    """`POST /api/tickets/run` — 보드의 티켓 한 건을 그 자리에서 실행한다.

    티켓과 실행을 잇는 자리가 여기다. 티켓만 있으면 목록이고 실행만 있으면 이력이지만,
    둘이 이어지면 **일감이 스스로 움직인 기록**이 된다: 티켓은 진행 중으로 가고 `task_id`를
    들며, 작업은 어느 티켓의 것인지를 라벨로 든다. 실행이 거절되면 티켓은 건드리지 않는다 —
    안 돈 일을 '진행 중'이라고 적는 보드는 계기가 아니다.

    **어디서 도는가는 티켓이 안다.** 보드는 폴더에 안 매이지만 실행은 매인다: 창은 이제
    개인 작업 공간에서 열리므로, 창의 자리에서 돌리면 저장소 얘기인 티켓이 코드 없는 데서
    돈다. 티켓이 적어 둔 자리가 아직 있으면 거기서, 없으면 창이 보는 곳에서 돈다."""
    from ...studio import tickets as T

    ref = str(payload.get("ref") or "").strip()
    try:
        ticket = T.get_ticket(root, ref)
    except T.TicketError as exc:
        return _json_body(404, {"error": str(exc)})
    except T.StoreError as exc:
        return _json_body(503, {"error": str(exc)})
    if ticket["status_type"] in {"completed", "canceled"}:
        return _json_body(
            409, {"error": f"{ticket['key']} 티켓은 이미 닫혀 있어요 — 상태를 다시 열어야 돌릴 수 있어요"}
        )
    blocked = ticket["blocked_by"]
    if blocked and not payload.get("force"):
        return _json_body(
            409, {"error": f"{ticket['key']} 티켓은 {', '.join(blocked)}에 막혀 있어요 — 막은 티켓을 먼저 끝내 주세요"}
        )

    lines = [_TICKET_BRIEF, "", f"[{ticket['key']}] {ticket['title']}"]
    if ticket["body"]:
        lines += ["", ticket["body"]]
    if ticket["children_list"]:
        lines += ["", "하위 티켓:"]
        lines += [f"- [{kid['key']}] {kid['title']}" for kid in ticket["children_list"]]
    status, ctype, body = create_task(
        {
            "prompt": "\n".join(lines)[:_PROMPT_CAP],
            "label": f"{ticket['key']} · {ticket['title']}"[:200],
            "permission": payload.get("permission") or "important",
            "provider": payload.get("provider") or "",
            "model": payload.get("model") or "",
            "root": payload.get("root") or _ticket_workspace(ticket, root),
        },
        root,
    )
    if status != 202:
        return status, ctype, body
    task = json.loads(body)
    changes: dict = {"task_id": task["id"]}
    if ticket["status_type"] not in {"started"}:
        changes["status"] = "in_progress"
    ticket = T.update_ticket(root, ticket["key"], changes, actor=str(payload.get("actor") or "studio"))
    return _json_body(202, {"task": task, "ticket": ticket})


_ASSIGN_BRIEF = "댓글에서 이름이 불렸다. 아래 티켓에서 부탁받은 일을 하고, 무엇을 했는지 한 줄로 보고한다."


def assign_ticket(payload: dict, root: str) -> tuple[int, str, bytes]:
    """`POST /api/tickets/assign` — 댓글에서 부른 에이전트에게 이 티켓을 맡긴다.

    `run`과 갈라 두는 이유는 **실린 맥락이 다르기 때문**이다. `run`은 티켓 본문만 준다
    ("이걸 끝내라"). 부름은 대화 도중에 일어나므로 부른 말이 곧 지시다 — 그 한 줄을 빼면
    에이전트는 티켓 전체를 다시 해석하고, 사람이 "이 부분만"이라고 적은 뜻이 사라진다.

    담당도 같이 옮긴다. 부르기만 하고 담당이 비어 있으면 보드에서는 아무 일도 안 일어난
    것처럼 보이고, 같은 일이 두 번 배정된다. 이미 다른 사람 것이면 **안 뺏는다** —
    부름은 요청이지 인수인계가 아니다."""
    from ...studio import mentions
    from ...studio import tickets as T

    ref = str(payload.get("ref") or "").strip()
    agent = str(payload.get("agent") or "").strip().lower()
    note = str(payload.get("note") or "").strip()
    if not agent:
        return _json_body(400, {"error": "어느 에이전트에게 맡길지 이름이 필요해요"})
    if agent not in {row["handle"] for row in mentions.roster()}:
        return _json_body(400, {"error": f"{agent} 에이전트가 아직 없어요 — 에이전트 화면에서 먼저 세워 주세요"})
    try:
        ticket = T.get_ticket(root, ref)
    except T.TicketError as exc:
        return _json_body(404, {"error": str(exc)})
    except T.StoreError as exc:
        return _json_body(503, {"error": str(exc)})
    if ticket["status_type"] in {"completed", "canceled"}:
        return _json_body(
            409, {"error": f"{ticket['key']} 티켓은 이미 닫혀 있어요 — 상태를 다시 열어야 맡길 수 있어요"}
        )

    lines = [_ASSIGN_BRIEF, "", f"[{ticket['key']}] {ticket['title']}"]
    if ticket["body"]:
        lines += ["", ticket["body"]]
    if note:
        lines += ["", f"불린 자리의 말: {note}"]
    status, ctype, body = create_task(
        {
            "prompt": "\n".join(lines)[:_PROMPT_CAP],
            "label": f"{ticket['key']} · @{agent}"[:200],
            "permission": payload.get("permission") or "important",
            "agent": agent,
            "root": payload.get("root") or _ticket_workspace(ticket, root),
        },
        root,
    )
    if status != 202:
        return status, ctype, body
    task = json.loads(body)
    changes: dict = {"task_id": task["id"]}
    if not ticket["assignee"]:
        changes["assignee"] = agent
    if ticket["status_type"] not in {"started"}:
        changes["status"] = "in_progress"
    ticket = T.update_ticket(root, ticket["key"], changes, actor=str(payload.get("actor") or "studio"))
    return _json_body(202, {"task": task, "ticket": ticket, "agent": agent})


# 한 퀘스트 안에서 이어 가기 — 후속 지시는 **새 작업이 아니라 같은 작업의 다음 턴**이다.
# 여태 스튜디오는 매 실행을 새로 시작했다: 퀘스트 로그에 줄이 하나씩 늘고, 앞 턴의 맥락은 사라졌다.
_TURN_CAP = 40
_THREAD_HEAD = "지금까지 이 작업에서 오간 것:"
_THREAD_TAIL = "위 맥락을 이어서 아래 지시를 수행하라."


def _compose(turns: list[dict], prompt: str) -> str:
    """앞 턴들을 지시문에 넣어 준다.

    `asgard run`은 단발 헤드리스라 프로세스 사이에 기억이 없다. 그래서 '이어 가기'는
    맥락을 **말로** 넘기는 것이다 — 없는 세션을 있는 척하지 않는다."""
    if not turns:
        return prompt
    lines = [_THREAD_HEAD]
    for turn in turns[-_TURN_CAP:]:
        who = "나" if turn.get("role") == "user" else "Asgard"
        text = " ".join(str(turn.get("text") or "").split())
        if text:
            lines.append(f"[{who}] {text[:1200]}")
    lines += ["", _THREAD_TAIL, prompt]
    return "\n".join(lines)


def follow_task(payload: dict, root: str) -> tuple[int, str, bytes]:
    """`POST /api/tasks/follow` — 열린 작업에 다음 지시를 붙이고 같은 줄에서 다시 돌린다."""
    task_id = str(payload.get("id") or "")
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt or len(prompt) > _PROMPT_CAP:
        return _json_body(400, {"error": "다음 지시를 적어 주세요 (최대 20000자)"})
    # 권한은 이어가는 턴마다 다시 정할 수 있다 — 화면의 권한 칸이 입력과 같은 자리에 있으니,
    # 보내는 순간의 값이 이 턴의 범위다. 안 주면 그 작업이 여태 쓰던 값을 그대로 쓴다.
    override = str(payload.get("permission") or "").strip()
    if override and override not in {"manual", "important", "auto"}:
        return _json_body(400, {"error": "unknown permission mode"})
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "task not found"})
        if task.get("status") in {"running", "queued", "paused"}:
            return _json_body(409, {"error": "아직 돌고 있는 작업이에요 — 끝나거나 멈춘 뒤에 이어 가 주세요"})
        turns = list(task.get("turns") or [])
        turns.append({"role": "user", "text": prompt, "ts": time.time()})
        permission = override or str(task.get("permission") or "important")
        composed = _compose(turns[:-1], prompt)
        command = [sys.executable, "-m", "asgard", "run", composed, "--json"]
        for flag, value in (("--provider", task.get("provider")), ("--model", task.get("model"))):
            if value:
                command += [flag, str(value)]
        task.update(
            {
                "turns": turns,
                "command": command,
                # 바꾼 권한은 기록에도 남는다 — 안 남기면 다음에 이 작업을 열었을 때 화면이
                # 옛 값을 말하고, 실제로 돈 범위와 적힌 범위가 갈린다
                "permission": permission,
                "status": "needs_input" if permission in {"manual", "important"} else "queued",
                "updated": time.time(),
                "result": "",
                "stopped": False,
                # 이어가기는 같은 퀘스트의 **다음 턴**이다 — 활동은 턴의 것이라 여기서 비운다.
                # 안 비우면 앞 턴에 쓴 도구들이 새 턴의 진행처럼 화면에 남는다.
                "now": None,
                "activity": [],
            }
        )
        task.pop("exit_code", None)
        snapshot = _public_task(task)
        queued = task["status"] == "queued"
        root = task_root(task, root)  # 이어가기는 그 대화가 시작된 자리에서 돈다
    _remember(root, snapshot)
    if queued:
        _start(task_id, root)
    return _json_body(202, snapshot)


def approve_task(payload: dict, root: str) -> tuple[int, str, bytes]:
    task_id = str(payload.get("id") or "")
    decision = str(payload.get("decision") or "")
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "task not found"})
        if task.get("status") != "needs_input":
            return _json_body(409, {"error": "task does not need approval"})
        root = task_root(task, root)  # 승인은 그 대화의 자리를 연다 — 창이 옮겨 갔더라도
        if decision == "deny":
            task.update(
                {
                    "status": "blocked",
                    "updated": time.time(),
                    "result": "사용자가 실행을 거부해서 이 작업은 돌지 않았어요.",
                }
            )
            denied = _public_task(task)
            _remember(root, denied)
            return _json_body(200, denied)
        if decision != "allow_once":
            return _json_body(400, {"error": "decision must be allow_once or deny"})
        task["status"] = "queued"
        task["updated"] = time.time()
        queued = _public_task(task)
    _remember(root, queued)
    _start(task_id, root)
    return _json_body(202, queued)


def stop_task(payload: dict) -> tuple[int, str, bytes]:
    """`POST /api/tasks/stop` — 중지는 **의사 표시가 먼저**다.

    여태 이 함수는 프로세스가 이미 떠 있을 때만 들었다. 그런데 창은 `queued`도 '실행 중'으로
    그리고 중지 단추를 함께 내놓는다 — 승인을 누르고 곧바로 중지를 누르면 그 사이에는 아직
    프로세스가 없어서 `task is not running`으로 튕겼다. 누른 사람에게는 단추가 죽은 것이다.
    그래서 뜻을 먼저 적고(`stopped`), 프로세스는 있으면 거둔다. 없으면 `_run_task`가 띄우는
    자리에서 이 표시를 보고 스스로 물러난다."""
    task_id = str(payload.get("id") or "")
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "그 작업을 못 찾았어요"})
        if task.get("status") == "needs_input":
            # 아직 시작도 안 한 작업이다 — '이미 끝났다'고 답하면 눈앞의 승인 판과 어긋난다
            return _json_body(409, {"error": "아직 승인을 기다리는 작업이에요 — 승인 판에서 거부해 주세요"})
        if task.get("status") not in {"running", "queued", "paused"}:
            return _json_body(409, {"error": "이미 끝난 작업이에요 — 중지할 것이 없어요"})
        was_paused = task.get("status") == "paused"
        process = task.get("process")
        task.update(
            {
                "status": "blocked",
                "updated": time.time(),
                "now": None,
                "result": "작업을 중지했어요.",
                "stopped": True,
            }
        )
        task.pop("process", None)
        stopped = _public_task(task)
    # 거두는 일은 잠금 **밖**에서 한다 — `_kill_group`은 유예 2초를 기다리는데, 그동안 잠금을
    # 쥐고 있으면 창의 다른 요청이 전부 그 2초에 걸린다(중지 한 번에 화면이 굳던 자리다).
    if process is not None:
        if was_paused and hasattr(signal, "SIGCONT"):
            _signal_group(process, signal.SIGCONT)  # 멈춰 있으면 깨워야 종료 신호를 받는다
        from ...agent.tools import _kill_group

        _kill_group(process)
    # 경계를 모르는 작업은 어디에도 안 적는다 — cwd로 떨어뜨리면 남의 프로젝트에 남의 이력이 쌓인다
    if stopped.get("root"):
        _remember(str(stopped["root"]), stopped)
    return _json_body(200, stopped)


def pause_task(payload: dict) -> tuple[int, str, bytes]:
    if not hasattr(signal, "SIGSTOP"):
        return _json_body(501, {"error": "이 기계에서는 일시정지가 안 돼요 — 대신 중지할 수 있어요"})
    task_id = str(payload.get("id") or "")
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "그 작업을 못 찾았어요"})
        process = task.get("process")
        if task.get("status") != "running":
            return _json_body(409, {"error": "돌고 있는 작업만 멈출 수 있어요"})
        if process is None:
            # 상태는 '실행 중'인데 아직 프로세스가 없는 짧은 사이. 여기서 '실행 중이 아니다'라고
            # 답하면 눈앞의 화면과 어긋난 말이 된다 — 무엇을 기다리는지를 말한다.
            return _json_body(409, {"error": "이제 막 시작하는 중이에요 — 잠시 뒤에 다시 눌러 주세요"})
        _signal_group(process, signal.SIGSTOP)
        task.update({"status": "paused", "updated": time.time()})
        return _json_body(200, _public_task(task))


def resume_task(payload: dict) -> tuple[int, str, bytes]:
    if not hasattr(signal, "SIGCONT"):
        return _json_body(501, {"error": "이 기계에서는 멈춘 작업을 다시 돌릴 수 없어요"})
    task_id = str(payload.get("id") or "")
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "그 작업을 못 찾았어요"})
        process = task.get("process")
        if task.get("status") != "paused" or process is None:
            return _json_body(409, {"error": "멈춰 있는 작업만 다시 돌릴 수 있어요"})
        _signal_group(process, signal.SIGCONT)
        task.update({"status": "running", "updated": time.time()})
        return _json_body(200, _public_task(task))
