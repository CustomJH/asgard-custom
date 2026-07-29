"""Asgard Desktop — local task, artifact, and settings workspace.

The desktop surface is a thin loopback UI over existing Asgard ownership:
settings.py persists configuration, ``asgard run`` executes work, and the
central skill/plugin registry remains the catalog source of truth.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files as _files
from urllib.parse import parse_qs, urlsplit

from .. import ui

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
_TASKS: dict[str, dict] = {}
_TASK_LOCK = threading.Lock()
_MAX_RUNNING = 4
_PROMPT_CAP = 20_000
_LOG_CAP = 200_000
_ARTIFACT_CAP = 400_000  # 뷰어가 읽는 최대 바이트 — 창은 편집기가 아니다

# 어느 프로젝트를 보고 있는가. 프로세스가 뜰 때는 서버가 잡은 root 지만, 사용자가 창 안에서
# 프로젝트를 바꾸면 이 값이 정본이 된다. 서버 객체가 아니라 모듈에 두는 이유: dispatch_post 는
# 핸들러를 안 받는데 전환은 POST 이고, 전환 직후의 GET 도 같은 답을 해야 하기 때문이다.
_CURRENT_ROOT: str | None = None
_ROOT_LOCK = threading.Lock()
_LOADED_ROOTS: set[str] = set()
_SERVER: "_RootServer | None" = None

_SETTING_KEYS = {
    "provider": {"name", "model", "base_url", "api_key_env", "context_window", "rpm"},
    "ui": {"lang", "theme", "density", "desktop_permission"},
    "memory": {"directory", "inject", "providers", "auto_retain_turns"},
    "lagom": {"mode"},
    "bridge": {"claude-code", "cursor", "codex"},
}


def host_allowed(host_header: str | None) -> bool:
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host in _LOOPBACK_HOSTS


def origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        return parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS
    except ValueError:
        return False


def _json_body(status: int, payload: object) -> tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode()


def _trim(text: str) -> str:
    return text[-_LOG_CAP:]


def _public_task(task: dict) -> dict:
    return {k: v for k, v in task.items() if k not in {"process", "command"}}


def _task_snapshot(root: str | None = None) -> list[dict]:
    """작업은 프로젝트에 속한다 — root 를 주면 그 경계 안의 것만 돌려준다.
    (기록이 없던 시절의 작업은 root 가 없다. 그건 어느 경계에도 안 걸리게 두지 않고
    현재 프로젝트 것으로 본다 — 안 그러면 옛 작업이 화면에서 통째로 사라진다.)"""
    with _TASK_LOCK:
        rows = [_public_task(task) for task in _TASKS.values()]
    if root:
        target = os.path.abspath(root)
        rows = [row for row in rows if os.path.abspath(str(row.get("root") or target)) == target]
    return sorted(rows, key=lambda row: row["created"], reverse=True)


# ── 자리 · 기억 ────────────────────────────────────────────────────────────────


def current_root(default: str | None = None) -> str:
    """지금 보고 있는 프로젝트.

    호출자가 경계를 명시하면 그것이 정본이다 — 요청 핸들러는 늘 서버의 root 를 넘기고,
    프로젝트 전환은 **그 서버의 root 를 바꾼다**. 모듈 전역은 서버 없이 호출되는 경로
    (직접 dispatch, 테스트)를 위한 뒷받침일 뿐, 명시된 경계를 덮지 않는다."""
    if default:
        return os.path.abspath(default)
    with _ROOT_LOCK:
        if _CURRENT_ROOT:
            return _CURRENT_ROOT
    return os.path.abspath(os.getcwd())


def _remember(root: str, task: dict) -> None:
    """작업 한 건을 그 프로젝트의 기록에 남긴다. 실패해도 실행은 계속된다 — 기록이 실행을
    막으면 기록이 아니라 관문이 된다."""
    from . import desktop_store

    try:
        desktop_store.save_task(root, _public_task(task))
    except Exception:
        pass


def load_project_tasks(root: str) -> int:
    """그 프로젝트의 기록을 메모리로 올린다. 프로젝트당 1회 — 재방문이 이력을 겹쳐 싣지 않게."""
    from . import desktop_store

    root = os.path.abspath(root)
    with _ROOT_LOCK:
        if root in _LOADED_ROOTS:
            return 0
        _LOADED_ROOTS.add(root)
    try:
        rows = desktop_store.load_tasks(root)
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
# (model_tiers: 티어 = 계열 이름, 역할·과업 난이도에 따라 골라 쓰는 눈금).
_TIER_NOTE = {
    "fast": "짧고 되풀이되는 판정 — 값싸고 빠른 쪽",
    "standard": "보통의 작업 — 기본값으로 두는 자리",
    "high": "어려운 설계와 검증",
    "max": "가장 무거운 판단",
}


def _provider_detail(profile) -> dict:
    """그 프로바이더가 실제로 아는 것만 싣는다 — 검증된 모델 목록·티어 표·연결 요건.

    모델의 성능 설명은 여기서 짓지 않는다. 아스가르드가 가진 사실은 '계열이 어느 티어인가'와
    '무엇이 있어야 연결되는가'뿐이고, 없는 사실을 화면이 지어내면 그 순간 계기가 아니다."""
    from .. import model_tiers

    tiers = model_tiers.tiers_for(profile.name, profile.api_mode)
    models = list(dict.fromkeys([*(profile.fallback_models or ()), profile.default_model or ""]))
    rows = []
    for model in models:
        if not model:
            continue
        tier = model_tiers.family_tier(model)
        rows.append(
            {
                "id": model,
                "tier": tier or "",
                "note": _TIER_NOTE.get(tier or "", ""),
                "default": model == profile.default_model,
            }
        )
    return {
        "name": profile.name,
        "label": profile.display,
        "api_mode": profile.api_mode,
        "default_model": profile.default_model,
        "context_window": getattr(profile, "context_window", 0),
        "key_optional": bool(getattr(profile, "key_optional", False)),
        "env_vars": list(getattr(profile, "env_vars", ()) or ()),
        "signup_hint": getattr(profile, "signup_hint", ""),
        "tiers": tiers,
        "models": rows,
    }


def _provider_state(root: str) -> dict:
    from ..providers import PROVIDERS, resolve

    resolved = resolve(root)
    return {
        "name": resolved.profile.name,
        "label": resolved.profile.display,
        "model": resolved.model,
        "source": resolved.source,
        "ready": not resolved.missing,
        "missing": resolved.missing,
        # 화면이 프로바이더를 바꾸면 그 자리에서 모델 목록이 따라 바뀌어야 한다 — 왕복을 없앤다
        "choices": [_provider_detail(profile) for profile in PROVIDERS.values()],
    }


def _catalog_state(root: str) -> dict:
    from ..skill_registry import plugins, skills

    skill_rows = skills(root)
    plugin_rows = plugins()
    return {
        "skills": [
            {
                "name": row.get("name", ""),
                "description": row.get("description", ""),
                "plugin": row.get("plugin", ""),
                "origin": row.get("origin", ""),
                "invocation": row.get("invocation", ""),
                "enabled": row.get("enabled", True),
            }
            for row in skill_rows
        ],
        "plugins": [
            {
                "name": row.get("name", ""),
                "description": row.get("description", ""),
                "origin": row.get("origin", ""),
                "skills": row.get("skills", []),
            }
            for row in plugin_rows
        ],
    }


def _safe_sections(data: dict) -> dict:
    return {
        name: {key: value for key, value in dict(data.get(name) or {}).items() if key in keys}
        for name, keys in _SETTING_KEYS.items()
    }


def settings_state(root: str) -> dict:
    from ..providers import project_section
    from ..settings import load_global, load_project, section

    effective = {
        name: {key: value for key, value in section(name, root).items() if key in keys}
        for name, keys in _SETTING_KEYS.items()
    }
    effective["trinity_mode"] = project_section(root, "trinity.mode")
    return {
        "global": _safe_sections(load_global()),
        "project": _safe_sections(load_project(root)),
        "effective": effective,
    }


def snapshot_data(root: str) -> dict:
    from ..memory.policy import inject_enabled, memory_dir
    from . import desktop_store
    from .role import role_model_state

    load_project_tasks(root)  # 창을 열자마자 그 프로젝트의 이력이 보여야 한다
    catalog = _catalog_state(root)
    return {
        "project": {"name": os.path.basename(root) or root, "root": root, "local": True},
        "projects": desktop_store.list_projects(root),
        "provider": _provider_state(root),
        "memory": {"directory": memory_dir(), "inject": inject_enabled()},
        "settings": settings_state(root),
        "roles": role_model_state(root),
        "catalog": {
            "skills": len(catalog["skills"]),
            "plugins": len(catalog["plugins"]),
        },
        "capabilities": {"pause": hasattr(signal, "SIGSTOP") and hasattr(signal, "SIGCONT")},
        "tasks": _task_snapshot(root),
    }


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


def _run_task(task_id: str, root: str) -> None:
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return
        task["status"] = "running"
        task["updated"] = time.time()
        command = list(task["command"])
        snapshot = _public_task(task)
    _remember(root, snapshot)
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
        with _TASK_LOCK:
            if task_id in _TASKS:
                _TASKS[task_id]["process"] = process
        stdout, stderr = process.communicate()
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
        result = str(payload.get("result") or stdout.strip() or stderr.strip())
        finished: dict = {}
        with _TASK_LOCK:
            task = _TASKS.get(task_id)
            if task:
                if task.get("stopped"):
                    task.pop("process", None)
                    return
                task.update(
                    {
                        "status": status,
                        "updated": time.time(),
                        "exit_code": process.returncode,
                        "result": _trim(result),
                        "log": _trim(stderr),
                        "usage": {
                            key: payload.get(key)
                            for key in ("tokens", "cache_read_tokens", "wall_s", "provider", "model")
                            if payload.get(key) is not None
                        },
                        "files": _workspace_files(root),
                        "turns": [
                            *(task.get("turns") or []),
                            {"role": "agent", "text": _trim(result), "ts": time.time()},
                        ],
                    }
                )
                task.pop("process", None)
                finished = _public_task(task)
        if finished:
            _remember(root, finished)
    except Exception as exc:
        failed: dict = {}
        with _TASK_LOCK:
            task = _TASKS.get(task_id)
            if task:
                task.update(
                    {
                        "status": "blocked",
                        "updated": time.time(),
                        "exit_code": 1,
                        "result": f"{type(exc).__name__}: {exc}",
                    }
                )
                task.pop("process", None)
                failed = _public_task(task)
        if failed:
            _remember(root, failed)


def _start(task_id: str, root: str) -> None:
    threading.Thread(target=_run_task, args=(task_id, root), daemon=True).start()


def create_task(payload: dict, root: str) -> tuple[int, str, bytes]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt or len(prompt) > _PROMPT_CAP:
        return _json_body(400, {"error": "prompt required (max 20000 chars)"})
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
        "root": root,  # 작업은 프로젝트에 속한다 — 어느 경계에서 돌았는지가 기록의 일부다
        "approval": {
            "action": "로컬 Asgard 작업 실행",
            "reason": "요청한 작업을 현재 프로젝트에서 실행하기 위해 필요합니다.",
            "scope": root,
            "target": "현재 프로젝트의 파일과 허용된 도구",
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


# 한 퀘스트 안에서 이어 가기 — 후속 지시는 **새 작업이 아니라 같은 작업의 다음 턴**이다.
# 여태 데스크탑은 매 실행을 새로 시작했다: 원장에 줄이 하나씩 늘고, 앞 턴의 맥락은 사라졌다.
_TURN_CAP = 40
_THREAD_HEAD = "지금까지 이 작업에서 오간 것:"
_THREAD_TAIL = "위 맥락을 이어서 아래 지시를 수행하라."


def _compose(turns: list[dict], prompt: str) -> str:
    """앞 턴들을 지시문에 실어 준다.

    `asgard run` 은 단발 헤드리스라 프로세스 사이에 기억이 없다. 그래서 '이어 가기'는
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
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "task not found"})
        if task.get("status") in {"running", "queued", "paused"}:
            return _json_body(409, {"error": "아직 돌고 있는 작업입니다 — 끝나거나 멈춘 뒤에 이어 가세요"})
        turns = list(task.get("turns") or [])
        turns.append({"role": "user", "text": prompt, "ts": time.time()})
        permission = str(task.get("permission") or "important")
        composed = _compose(turns[:-1], prompt)
        command = [sys.executable, "-m", "asgard", "run", composed, "--json"]
        for flag, value in (("--provider", task.get("provider")), ("--model", task.get("model"))):
            if value:
                command += [flag, str(value)]
        task.update(
            {
                "turns": turns,
                "command": command,
                "status": "needs_input" if permission in {"manual", "important"} else "queued",
                "updated": time.time(),
                "result": "",
                "stopped": False,
            }
        )
        task.pop("exit_code", None)
        snapshot = _public_task(task)
        queued = task["status"] == "queued"
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
    task_id = str(payload.get("id") or "")
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "task not found"})
        process = task.get("process")
        if task.get("status") not in {"running", "paused"} or process is None:
            return _json_body(409, {"error": "task is not running"})
        if task.get("status") == "paused" and hasattr(signal, "SIGCONT"):
            process.send_signal(signal.SIGCONT)
        from ..agent.tools import _kill_group

        _kill_group(process)
        task.update({"status": "blocked", "updated": time.time(), "result": "작업이 중지되었습니다.", "stopped": True})
        stopped = _public_task(task)
    # 경계를 모르는 작업은 어디에도 안 적는다 — cwd 로 떨어뜨리면 남의 프로젝트에 남의 이력이 쌓인다
    if stopped.get("root"):
        _remember(str(stopped["root"]), stopped)
    return _json_body(200, stopped)


def pause_task(payload: dict) -> tuple[int, str, bytes]:
    if not hasattr(signal, "SIGSTOP"):
        return _json_body(501, {"error": "pause is not supported on this platform"})
    task_id = str(payload.get("id") or "")
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "task not found"})
        process = task.get("process")
        if task.get("status") != "running" or process is None:
            return _json_body(409, {"error": "task is not running"})
        process.send_signal(signal.SIGSTOP)
        task.update({"status": "paused", "updated": time.time()})
        return _json_body(200, _public_task(task))


def resume_task(payload: dict) -> tuple[int, str, bytes]:
    if not hasattr(signal, "SIGCONT"):
        return _json_body(501, {"error": "resume is not supported on this platform"})
    task_id = str(payload.get("id") or "")
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return _json_body(404, {"error": "task not found"})
        process = task.get("process")
        if task.get("status") != "paused" or process is None:
            return _json_body(409, {"error": "task is not paused"})
        process.send_signal(signal.SIGCONT)
        task.update({"status": "running", "updated": time.time()})
        return _json_body(200, _public_task(task))


# ── 프로젝트 전환 ──────────────────────────────────────────────────────────────


def use_project(payload: dict) -> tuple[int, str, bytes]:
    """창이 보는 프로젝트를 바꾼다. 실행 중인 작업은 그 자리에 그대로 둔다 — 경계를 옮긴다고
    남의 프로세스를 죽이지 않는다. 새 경계의 이력은 이때 디스크에서 올라온다."""
    from . import desktop_store

    target = os.path.abspath(os.path.expanduser(str(payload.get("root") or "").strip()))
    if not target or not os.path.isdir(target):
        return _json_body(400, {"error": "존재하는 디렉터리 경로가 필요합니다"})
    global _CURRENT_ROOT
    with _ROOT_LOCK:
        _CURRENT_ROOT = target
    if _SERVER is not None:  # 이후 요청은 핸들러가 서버의 root 를 넘긴다 — 거기를 바꿔야 실제로 옮겨진다
        _SERVER.root = target
    desktop_store.touch_project(target)
    load_project_tasks(target)
    return _json_body(200, {"root": target, "snapshot": snapshot_data(target)})


def add_project(payload: dict) -> tuple[int, str, bytes]:
    from . import desktop_store

    try:
        added = desktop_store.add_project(str(payload.get("root") or ""))
    except ValueError as exc:
        return _json_body(400, {"error": str(exc)})
    return _json_body(200, {"added": added, "projects": desktop_store.list_projects(current_root())})


def forget_project(payload: dict) -> tuple[int, str, bytes]:
    """목록에서만 뺀다. 현재 보고 있는 프로젝트는 뺄 수 없다 — 발밑을 지울 수는 없다."""
    from . import desktop_store

    target = os.path.abspath(os.path.expanduser(str(payload.get("root") or "").strip()))
    if target == current_root():
        return _json_body(409, {"error": "현재 열려 있는 프로젝트는 목록에서 뺄 수 없습니다"})
    removed = desktop_store.remove_project(target)
    return _json_body(200, {"removed": removed, "projects": desktop_store.list_projects(current_root())})


# ── 산출물 열기 ────────────────────────────────────────────────────────────────

_TEXT_HINT = frozenset({0x09, 0x0A, 0x0D})


def _confine(root: str, rel: str) -> str | None:
    """프로젝트 경계 안의 실제 경로만 돌려준다.

    realpath 로 비교하는 이유: `..` 도, 밖을 가리키는 심링크도 문자열 검사로는 안 잡힌다.
    경계 밖이면 None — 창은 프로젝트를 보는 창이지 파일 시스템 탐색기가 아니다."""
    rel = str(rel or "").strip()
    if not rel or os.path.isabs(rel) or "\x00" in rel:
        return None
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        return None
    return target if os.path.isfile(target) else None


def read_artifact(root: str, params: dict[str, list[str]]) -> tuple[int, str, bytes]:
    """변경 파일 한 장을 읽어 준다. 이진 파일은 내용 대신 그렇다고 말한다."""
    target = _confine(root, (params.get("path") or [""])[0])
    if target is None:
        return _json_body(404, {"error": "프로젝트 경계 안의 파일이 아닙니다"})
    try:
        size = os.path.getsize(target)
        with open(target, "rb") as handle:
            raw = handle.read(_ARTIFACT_CAP)
    except OSError as exc:
        return _json_body(400, {"error": f"읽을 수 없습니다: {type(exc).__name__}"})
    binary = any(byte == 0 or (byte < 0x20 and byte not in _TEXT_HINT) for byte in raw[:2048])
    return _json_body(
        200,
        {
            "path": os.path.relpath(target, os.path.realpath(root)),
            "size": size,
            "binary": binary,
            "truncated": size > len(raw),
            "text": "" if binary else raw.decode("utf-8", "replace"),
        },
    )


def read_diff(root: str, params: dict[str, list[str]]) -> tuple[int, str, bytes]:
    """그 파일의 git diff. 저장소가 아니거나 추적 밖이면 빈 diff 를 정직하게 돌려준다."""
    rel = (params.get("path") or [""])[0]
    target = _confine(root, rel)
    if target is None:
        return _json_body(404, {"error": "프로젝트 경계 안의 파일이 아닙니다"})
    rel_path = os.path.relpath(target, os.path.realpath(root))
    try:
        result = subprocess.run(
            ["git", "diff", "--no-color", "--", rel_path],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        return _json_body(200, {"path": rel_path, "diff": "", "note": f"git diff 실패: {type(exc).__name__}"})
    diff = _trim(result.stdout)
    note = ""
    if not diff:
        # 추적 밖 파일은 `git diff` 가 조용하다 — "변경 없음"이라고 말하면 새 파일을 없는 파일로 만든다
        note = "이 파일에는 커밋되지 않은 변경이 없습니다"
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain", "--", rel_path],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
            if status.stdout.startswith("??"):
                note = "아직 추적되지 않는 새 파일입니다 — 원본으로 보세요"
        except Exception:
            pass
    return _json_body(200, {"path": rel_path, "diff": diff, "note": note})


def reveal_path(root: str, payload: dict) -> tuple[int, str, bytes]:
    """파일이 있는 자리를 OS 탐색기로 연다. 경계 밖은 열지 않는다."""
    rel = str(payload.get("path") or "")
    target = _confine(root, rel) if rel else os.path.realpath(root)
    if target is None:
        return _json_body(404, {"error": "프로젝트 경계 안의 파일이 아닙니다"})
    try:
        if sys.platform == "darwin":
            command = ["open", "-R", target] if os.path.isfile(target) else ["open", target]
        elif os.name == "nt":
            command = ["explorer", f"/select,{target}"] if os.path.isfile(target) else ["explorer", target]
        else:
            command = ["xdg-open", target if os.path.isdir(target) else os.path.dirname(target)]
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    except OSError as exc:
        return _json_body(400, {"error": f"열 수 없습니다: {type(exc).__name__}"})
    return _json_body(200, {"revealed": os.path.relpath(target, os.path.realpath(root))})


def _validate_settings(section_name: str, values: object) -> dict:
    from ..providers import PROVIDERS, normalize_model_id

    if section_name not in _SETTING_KEYS or not isinstance(values, dict):
        raise ValueError("unknown settings section")
    unknown = set(values).difference(_SETTING_KEYS[section_name])
    if unknown:
        raise ValueError(f"unknown settings keys: {', '.join(sorted(unknown))}")
    clean = dict(values)
    if section_name == "provider":
        if clean.get("name") and clean["name"] not in PROVIDERS:
            raise ValueError("unknown provider")
        if clean.get("model"):
            clean["model"] = normalize_model_id(str(clean["model"]))
            if not clean["model"]:
                raise ValueError("invalid model")
        for key in ("context_window", "rpm"):
            if key in clean and clean[key] not in (None, ""):
                clean[key] = int(clean[key])
    elif section_name == "ui":
        if clean.get("theme") not in (None, "system", "light", "dark"):
            raise ValueError("theme must be system, light, or dark")
        if clean.get("density") not in (None, "comfortable", "compact"):
            raise ValueError("density must be comfortable or compact")
        if clean.get("desktop_permission") not in (None, "manual", "important", "auto"):
            raise ValueError("invalid permission mode")
    elif section_name == "memory":
        if "inject" in clean:
            clean["inject"] = "on" if str(clean["inject"]).lower() in {"on", "true", "1"} else "off"
        if "providers" in clean and not isinstance(clean["providers"], list):
            raise ValueError("memory providers must be a list")
        if "auto_retain_turns" in clean:
            clean["auto_retain_turns"] = bool(clean["auto_retain_turns"])
    elif section_name == "lagom" and clean.get("mode") not in (None, "off", "lite", "full"):
        raise ValueError("lagom mode must be off, lite, or full")
    elif section_name == "bridge":
        clean = {key: bool(value) for key, value in clean.items()}
    return {key: value for key, value in clean.items() if value is not None and value != ""}


def save_settings(payload: dict, root: str) -> tuple[int, str, bytes]:
    from ..settings import save_global, save_project

    scope = str(payload.get("scope") or "project")
    section_name = str(payload.get("section") or "")
    try:
        if scope not in {"global", "project"}:
            raise ValueError("scope must be global or project")
        values = _validate_settings(section_name, payload.get("values"))
        path = save_global(section_name, values) if scope == "global" else save_project(root, section_name, values)
    except (TypeError, ValueError) as exc:
        return _json_body(400, {"error": str(exc)})
    return _json_body(200, {"saved": path, "settings": settings_state(root)})


def save_skill(payload: dict, root: str) -> tuple[int, str, bytes]:
    from ..skill_registry import set_skill_enabled

    name = str(payload.get("name") or "")
    enabled = payload.get("enabled")
    if not name or not isinstance(enabled, bool):
        return _json_body(400, {"error": "name and boolean enabled required"})
    try:
        set_skill_enabled(root, name, enabled=enabled)
    except ValueError as exc:
        return _json_body(400, {"error": str(exc)})
    return _json_body(200, {"name": name, "enabled": enabled})


def save_role(payload: dict, root: str) -> tuple[int, str, bytes]:
    from .role import configure_role_model

    try:
        result = configure_role_model(
            root,
            str(payload.get("host") or ""),
            str(payload.get("role") or ""),
            model=str(payload.get("model") or "") or None,
            effort=str(payload.get("effort") or "") or None,
            provider=str(payload.get("provider") or "") or None,
            reset=payload.get("reset") is True,
        )
    except ValueError as exc:
        return _json_body(400, {"error": str(exc)})
    return _json_body(200, result)


def dispatch(
    method: str, path: str, params: dict[str, list[str]] | None = None, root: str | None = None
) -> tuple[int, str, bytes]:
    root = current_root(root)
    params = params or {}
    if method not in ("GET", "HEAD"):
        return 405, "text/plain; charset=utf-8", b"method not allowed"
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", render_html().encode()
    if path == "/asset/logo":
        return 200, "image/png", (_files("asgard") / "assets" / "gold-brand-logo.png").read_bytes()
    if path == "/asset/mark":
        # 위그드라실 마크 — asgard map · memory 가 드는 것과 같은 파일이라 세 창이 같은 마크를 든다
        return 200, "image/png", (_files("asgard") / "assets" / "yggdrasil-mark.png").read_bytes()
    if path == "/api/snapshot":
        return _json_body(200, snapshot_data(root))
    if path == "/api/tasks":
        return _json_body(200, _task_snapshot(root))
    if path == "/api/projects":
        from . import desktop_store

        return _json_body(200, {"projects": desktop_store.list_projects(root), "current": root})
    if path == "/api/artifact":
        return read_artifact(root, params)
    if path == "/api/diff":
        return read_diff(root, params)
    if path == "/api/task":
        task_id = (params.get("id") or [""])[0]
        with _TASK_LOCK:
            task = _TASKS.get(task_id)
            return _json_body(200, _public_task(task)) if task else _json_body(404, {"error": "task not found"})
    if path == "/api/settings":
        return _json_body(200, settings_state(root))
    if path == "/api/catalog":
        return _json_body(200, _catalog_state(root))
    if path == "/health":
        return _json_body(200, {"ok": True, "surface": "desktop"})
    return 404, "text/plain; charset=utf-8", b"not found"


def dispatch_post(path: str, payload: dict, root: str | None = None) -> tuple[int, str, bytes]:
    root = current_root(root)
    routes = {
        "/api/tasks": lambda: create_task(payload, root),
        "/api/tasks/approve": lambda: approve_task(payload, root),
        "/api/tasks/follow": lambda: follow_task(payload, root),
        "/api/tasks/stop": lambda: stop_task(payload),
        "/api/tasks/pause": lambda: pause_task(payload),
        "/api/tasks/resume": lambda: resume_task(payload),
        "/api/projects/use": lambda: use_project(payload),
        "/api/projects/add": lambda: add_project(payload),
        "/api/projects/forget": lambda: forget_project(payload),
        "/api/reveal": lambda: reveal_path(root, payload),
        "/api/settings": lambda: save_settings(payload, root),
        "/api/skill": lambda: save_skill(payload, root),
        "/api/role": lambda: save_role(payload, root),
    }
    route = routes.get(path)
    return route() if route else (404, "text/plain; charset=utf-8", b"not found")


class _Handler(BaseHTTPRequestHandler):
    server_version = "AsgardDesktop"

    def _send(self, status: int, ctype: str, body: bytes, head_only: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; connect-src 'self'; frame-src 'none'; base-uri 'none'; form-action 'none'",
        )
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _route(self, head_only: bool = False) -> None:
        if not host_allowed(self.headers.get("Host")):
            self._send(403, "text/plain; charset=utf-8", b"forbidden host", head_only)
            return
        parts = urlsplit(self.path)
        root = getattr(self.server, "root", os.getcwd())
        try:
            status, ctype, body = dispatch(self.command, parts.path, parse_qs(parts.query), root)
        except Exception as exc:
            status, ctype, body = 500, "text/plain; charset=utf-8", f"error: {type(exc).__name__}".encode()
        self._send(status, ctype, body, head_only)

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route(head_only=True)

    def do_POST(self) -> None:
        if not host_allowed(self.headers.get("Host")) or not origin_allowed(self.headers.get("Origin")):
            self._send(403, "text/plain; charset=utf-8", b"forbidden")
            return
        try:
            size = min(int(self.headers.get("Content-Length") or 0), 256_000)
            payload = json.loads(self.rfile.read(size).decode() or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        parts = urlsplit(self.path)
        root = getattr(self.server, "root", os.getcwd())
        try:
            status, ctype, body = dispatch_post(parts.path, payload, root)
        except Exception as exc:
            status, ctype, body = 500, "text/plain; charset=utf-8", f"error: {type(exc).__name__}".encode()
        self._send(status, ctype, body)

    def log_message(self, format: str, *args: object) -> None:
        return


class _RootServer(ThreadingHTTPServer):
    root: str


def _bind(host: str, port: int, root: str | None = None) -> _RootServer:
    from . import desktop_store

    try:
        httpd = _RootServer((host, port), _Handler)
    except OSError:
        httpd = _RootServer((host, 0), _Handler)
    httpd.root = os.path.abspath(root or os.getcwd())
    global _CURRENT_ROOT, _SERVER
    _SERVER = httpd
    with _ROOT_LOCK:
        _CURRENT_ROOT = httpd.root
    desktop_store.touch_project(httpd.root)
    load_project_tasks(httpd.root)  # 지난번에 하던 일이 창을 열면 그대로 있어야 한다
    return httpd


def _native_candidates() -> list[str]:
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    configured = os.environ.get("ASGARD_DESKTOP_APP")
    found = shutil.which("asgard-desktop")
    binary = "asgard-desktop.exe" if os.name == "nt" else "asgard-desktop"
    candidates = [
        configured,
        found,
        os.path.join(repo, "desktop", "src-tauri", "target", "release", binary),
        os.path.join(repo, "desktop", "src-tauri", "target", "debug", binary),
    ]
    if os.name == "nt":
        candidates.extend(
            os.path.join(base, "Asgard Desktop", binary)
            for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"))
            if base
        )
    else:
        candidates.extend(
            [
                os.path.join(
                    repo,
                    "desktop",
                    "src-tauri",
                    "target",
                    "release",
                    "bundle",
                    "macos",
                    "Asgard Desktop.app",
                    "Contents",
                    "MacOS",
                    binary,
                ),
                f"/Applications/Asgard Desktop.app/Contents/MacOS/{binary}",
                os.path.expanduser(f"~/Applications/Asgard Desktop.app/Contents/MacOS/{binary}"),
            ]
        )
    return list(dict.fromkeys(path for path in candidates if path and os.path.isfile(path)))


def _open_native(url: str, root: str) -> bool:
    env = {**os.environ, "ASGARD_DESKTOP_URL": url, "ASGARD_DESKTOP_ROOT": root}
    for path in _native_candidates():
        try:
            subprocess.run([path], env=env, check=False)
            return True
        except OSError:
            continue
    return False


def run_desktop(
    port: int = 8766,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    prefer_native: bool = True,
) -> int:
    if host not in ("127.0.0.1", "localhost", "::1"):
        ui.warn(f"host {host!r} is not loopback — forcing 127.0.0.1")
        host = "127.0.0.1"
    httpd = _bind(host, port)
    actual = httpd.server_address[1]
    url = f"http://{host}:{actual}/"
    ui.ok(f"Asgard Desktop → {url}")
    ui.step("종료: Ctrl-C")
    if open_browser:

        def launch() -> None:
            if prefer_native and _open_native(url, httpd.root):
                httpd.shutdown()
                return
            if prefer_native:
                ui.warn("Tauri app not built yet — opening the browser fallback")
            _open(url)

        threading.Timer(0.4, launch).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        ui.step("stopped")
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


def _open(url: str) -> None:
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        pass


def render_html() -> str:
    return _PAGE


_PAGE = (_files("asgard") / "assets" / "desktop.html").read_text(encoding="utf-8")
