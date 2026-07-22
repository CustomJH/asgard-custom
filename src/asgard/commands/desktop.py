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


def _task_snapshot() -> list[dict]:
    with _TASK_LOCK:
        rows = [_public_task(task) for task in _TASKS.values()]
    return sorted(rows, key=lambda row: row["created"], reverse=True)


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
        "choices": [{"name": name, "label": profile.display} for name, profile in PROVIDERS.items()],
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

    effective = {name: {key: value for key, value in section(name, root).items() if key in keys} for name, keys in _SETTING_KEYS.items()}
    effective["trinity_mode"] = project_section(root, "trinity.mode")
    return {
        "global": _safe_sections(load_global()),
        "project": _safe_sections(load_project(root)),
        "effective": effective,
    }


def snapshot_data(root: str) -> dict:
    from ..memory.policy import inject_enabled, memory_dir
    from .role import role_model_state

    catalog = _catalog_state(root)
    return {
        "project": {"name": os.path.basename(root) or root, "root": root, "local": True},
        "provider": _provider_state(root),
        "memory": {"directory": memory_dir(), "inject": inject_enabled()},
        "settings": settings_state(root),
        "roles": role_model_state(root),
        "catalog": {
            "skills": len(catalog["skills"]),
            "plugins": len(catalog["plugins"]),
        },
        "capabilities": {"pause": hasattr(signal, "SIGSTOP") and hasattr(signal, "SIGCONT")},
        "tasks": _task_snapshot(),
    }


def _workspace_files(root: str) -> list[dict]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"], cwd=root, capture_output=True, text=True, timeout=10, check=False
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
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "ASGARD_UNATTENDED": "1"},
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
                    }
                )
                task.pop("process", None)
    except Exception as exc:
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
    if task["status"] == "queued":
        _start(task_id, root)
    return _json_body(202, _public_task(task))


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
            return _json_body(200, _public_task(task))
        if decision != "allow_once":
            return _json_body(400, {"error": "decision must be allow_once or deny"})
        task["status"] = "queued"
        task["updated"] = time.time()
    _start(task_id, root)
    return _json_body(202, _public_task(task))


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
        process.terminate()
        task.update(
            {"status": "blocked", "updated": time.time(), "result": "작업이 중지되었습니다.", "stopped": True}
        )
    return _json_body(200, _public_task(task))


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
    root = os.path.abspath(root or os.getcwd())
    params = params or {}
    if method not in ("GET", "HEAD"):
        return 405, "text/plain; charset=utf-8", b"method not allowed"
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", render_html().encode()
    if path == "/asset/logo":
        return 200, "image/png", (_files("asgard") / "assets" / "gold-brand-logo.png").read_bytes()
    if path == "/api/snapshot":
        return _json_body(200, snapshot_data(root))
    if path == "/api/tasks":
        return _json_body(200, _task_snapshot())
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
    root = os.path.abspath(root or os.getcwd())
    routes = {
        "/api/tasks": lambda: create_task(payload, root),
        "/api/tasks/approve": lambda: approve_task(payload, root),
        "/api/tasks/stop": lambda: stop_task(payload),
        "/api/tasks/pause": lambda: pause_task(payload),
        "/api/tasks/resume": lambda: resume_task(payload),
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


def _bind(host: str, port: int, root: str | None = None) -> ThreadingHTTPServer:
    try:
        httpd = ThreadingHTTPServer((host, port), _Handler)
    except OSError:
        httpd = ThreadingHTTPServer((host, 0), _Handler)
    httpd.root = os.path.abspath(root or os.getcwd())  # type: ignore[attr-defined]
    return httpd


def _native_candidates() -> list[str]:
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    configured = os.environ.get("ASGARD_DESKTOP_APP")
    found = shutil.which("asgard-desktop")
    candidates = [
        configured,
        found,
        os.path.join(repo, "desktop", "src-tauri", "target", "release", "asgard-desktop"),
        os.path.join(repo, "desktop", "src-tauri", "target", "debug", "asgard-desktop"),
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
            "asgard-desktop",
        ),
        "/Applications/Asgard Desktop.app/Contents/MacOS/asgard-desktop",
        os.path.expanduser("~/Applications/Asgard Desktop.app/Contents/MacOS/asgard-desktop"),
    ]
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
            if prefer_native and _open_native(url, httpd.root):  # type: ignore[attr-defined]
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
