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

from ... import (
    errors,
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


def _task_snapshot(root: str | None = None) -> list[dict]:
    """작업은 작업 공간에 속한다 — root를 주면 그 경계 안의 것만 돌려준다.
    (기록이 없던 시절의 작업은 root가 없다. 그건 어느 경계에도 안 걸리게 두지 않고
    현재 작업 공간 것으로 본다 — 안 그러면 옛 작업이 화면에서 통째로 사라진다.)"""
    with _TASK_LOCK:
        rows = [_public_task(task) for task in _TASKS.values()]
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
    with _ROOT_LOCK:
        if root in _LOADED_ROOTS:
            return 0
        _LOADED_ROOTS.add(root)
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
        command = list(task["command"])
        snapshot = _public_task(task)
    _remember(root, snapshot)
    before = _workspace_files(root)  # 이 작업이 무엇을 바꿨는지는 시작 상태와 견줘야 안다
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "ASGARD_UNATTENDED": "1"},
            start_new_session=os.name == "posix",
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            encoding="utf-8",
            errors="replace",
        )
        if not _claim(task_id, process):
            from ...agent.tools import _kill_group

            _kill_group(process)
            return
        stdout, stderr = process.communicate()
        _finish(task_id, root, process, stdout, stderr, before)
    except Exception as exc:
        _blame(task_id, root, exc)


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
    head = lines[-1] if lines else f"작업이 종료 코드 {code}로 끝났습니다."
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
                T.add_comment(root, ticket["key"], summary or "작업이 끝났습니다.", author="studio")
            else:
                T.add_comment(root, ticket["key"], f"작업이 막혔습니다 — {summary}", author="studio")
    except Exception:
        pass


def _start(task_id: str, root: str) -> None:
    threading.Thread(target=_run_task, args=(task_id, root), daemon=True).start()


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
        running = sum(task.get("status") in {"queued", "running", "paused"} for task in _TASKS.values())
        if running >= _MAX_RUNNING:
            return _json_body(409, {"error": "too many running tasks"})
    provider = str(payload.get("provider") or "").strip()
    model = str(payload.get("model") or "").strip()
    command = [sys.executable, "-m", "asgard", "run", prompt, "--json"]
    if provider:
        command += ["--provider", provider]
    if model:
        command += ["--model", model]
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
        "result": "",
        "log": "",
        "files": [],
        "usage": {},
        # 한 작업 = 한 퀘스트. 턴이 쌓여도 원장의 줄은 하나다.
        "turns": [{"role": "user", "text": prompt, "ts": now}],
        "root": root,  # 작업은 작업 공간에 속한다 — 어느 경계에서 돌았는지가 기록의 일부다
        "approval": {
            "action": "로컬 Asgard 작업 실행",
            "reason": f"요청한 작업을 {workspace_label(root)}에서 실행하기 위해 필요합니다.",
            "scope": root,
            "target": f"{workspace_label(root)}의 파일과 허용된 도구",
            "reversible": "Git 변경은 검토 후 되돌릴 수 있습니다. 외부 작업은 실행 시 별도 정책을 따릅니다.",
        },
        "command": command,
    }
    with _TASK_LOCK:
        _TASKS[task_id] = task
    _remember(root, task)
    if task["status"] == "queued":
        _start(task_id, root)
    return _json_body(202, _public_task(task))


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
        return _json_body(409, {"error": f"{ticket['key']}는 이미 닫힌 티켓입니다"})
    blocked = ticket["blocked_by"]
    if blocked and not payload.get("force"):
        return _json_body(409, {"error": f"{ticket['key']}는 {', '.join(blocked)}에 막혀 있습니다"})

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


# 한 퀘스트 안에서 이어 가기 — 후속 지시는 **새 작업이 아니라 같은 작업의 다음 턴**이다.
# 여태 스튜디오은 매 실행을 새로 시작했다: 원장에 줄이 하나씩 늘고, 앞 턴의 맥락은 사라졌다.
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
        return _json_body(400, {"error": "다음 지시가 필요합니다 (최대 20000자)"})
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
            return _json_body(409, {"error": "아직 돌고 있는 작업입니다 — 끝나거나 멈춘 뒤에 이어 가세요"})
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
            task.update({"status": "blocked", "updated": time.time(), "result": "사용자가 실행을 거부했습니다."})
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
            return _json_body(404, {"error": "작업을 찾을 수 없습니다"})
        if task.get("status") == "needs_input":
            # 아직 시작도 안 한 작업이다 — '이미 끝났다'고 답하면 눈앞의 승인 판과 어긋난다
            return _json_body(409, {"error": "승인을 기다리는 작업입니다 — 승인 판에서 거부하세요"})
        if task.get("status") not in {"running", "queued", "paused"}:
            return _json_body(409, {"error": "이미 끝난 작업입니다"})
        was_paused = task.get("status") == "paused"
        process = task.get("process")
        task.update({"status": "blocked", "updated": time.time(), "result": "작업이 중지되었습니다.", "stopped": True})
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
        return _json_body(501, {"error": "이 플랫폼에서는 일시정지를 지원하지 않습니다"})
    task_id = str(payload.get("id") or "")
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "작업을 찾을 수 없습니다"})
        process = task.get("process")
        if task.get("status") != "running":
            return _json_body(409, {"error": "실행 중인 작업이 아닙니다"})
        if process is None:
            # 상태는 '실행 중'인데 아직 프로세스가 없는 짧은 사이. 여기서 '실행 중이 아니다'라고
            # 답하면 눈앞의 화면과 어긋난 말이 된다 — 무엇을 기다리는지를 말한다.
            return _json_body(409, {"error": "이제 막 시작하는 중입니다 — 잠시 뒤에 다시 눌러 주세요"})
        _signal_group(process, signal.SIGSTOP)
        task.update({"status": "paused", "updated": time.time()})
        return _json_body(200, _public_task(task))


def resume_task(payload: dict) -> tuple[int, str, bytes]:
    if not hasattr(signal, "SIGCONT"):
        return _json_body(501, {"error": "이 플랫폼에서는 재개를 지원하지 않습니다"})
    task_id = str(payload.get("id") or "")
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "작업을 찾을 수 없습니다"})
        process = task.get("process")
        if task.get("status") != "paused" or process is None:
            return _json_body(409, {"error": "멈춰 있는 작업이 아닙니다"})
        _signal_group(process, signal.SIGCONT)
        task.update({"status": "running", "updated": time.time()})
        return _json_body(200, _public_task(task))
