#!/usr/bin/env python3
"""Memory profile for Asgard's Claude Code hooks and import surface.

Two independent measurements per hook, both spawned as fresh subprocesses so no
measurement's peak leaks into the next one's baseline:

  rss    Peak RSS of the real hook invocation (`uv run --no-project python <hook> <argv>`,
          read straight from `.claude/settings.json`), via a one-shot wrapper that reads its
          own `RUSAGE_CHILDREN.ru_maxrss` before and after `subprocess.run`. macOS reports
          bytes; Linux reports KiB — `_maxrss_unit()` carries the platform split.
  alloc  Python allocation sites for one hook body, run in-process via `runpy.run_path` under
          `tracemalloc`, in a throwaway subprocess (the hook's own `sys.exit()` would otherwise
          kill the profiler).

`staircase` re-measures RSS after each import step (`python -c pass` -> `import asgard` ->
... -> one full hook run) to localize which import raises RSS the most.

Examples:
  uv run python benchmarks/cpu-profile/memprofile.py rss --json
  uv run python benchmarks/cpu-profile/memprofile.py alloc --hook secret-guard.py --json
  uv run python benchmarks/cpu-profile/memprofile.py staircase --json
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SETTINGS = REPO / ".claude" / "settings.json"
VENV_PYTHON = REPO / ".venv" / "bin" / "python3"

# RUSAGE_MAXRSS 단위 — macOS는 바이트, Linux는 KiB (man getrusage 플랫폼별 차이).
_MAXRSS_UNIT_BYTES = {"darwin": 1, "linux": 1024}


def maxrss_to_bytes(raw: int) -> int:
    return raw * _MAXRSS_UNIT_BYTES.get(sys.platform, 1024)


def load_hook_invocations() -> list[dict]:
    """`.claude/settings.json`에 실제 등록된 훅 커맨드를 그대로 읽어 (file, argv, event) 조합을 낸다.

    직접 표를 손으로 짜지 않는 이유: 매처마다 같은 훅이 다른 인자로 여러 번 걸리므로, 원본이
    유일한 정본이다. `(hook 파일명, argv, event)` 로 중복 제거한다."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    out: list[dict] = []
    for event, matchers in settings.get("hooks", {}).items():
        for entry in matchers:
            for h in entry.get("hooks", []):
                cmd = str(h.get("command") or "").replace("$CLAUDE_PROJECT_DIR", str(REPO))
                parts = shlex.split(cmd)
                py_idx = next((i for i, p in enumerate(parts) if p.endswith(".py")), None)
                if py_idx is None:
                    continue
                hook_path = Path(parts[py_idx])
                argv = tuple(parts[py_idx + 1 :])
                key = (hook_path.name, argv, event)
                if key in seen:
                    continue
                seen.add(key)
                label = hook_path.name + (f" {' '.join(argv)}" if argv else "") + f" ({event})"
                out.append({"label": label, "path": hook_path, "argv": list(argv), "event": event})
    return out


def base_payload(event: str) -> dict:
    """모든 훅이 최소한 견디는 범용 stdin — 실제 필드 이름을 각 훅 소스에서 확인해 채웠다
    (readonly-guard/secret-guard/git-guard/budget-guard/subagent-gate/memory-activate 등이
    공통으로 `tool_input`·`cwd`·`transcript_path`·`session_id`·`hook_event_name`을 읽는다)."""
    return {
        "hook_event_name": event,
        "session_id": "memprofile-session",
        "cwd": str(REPO),
        "transcript_path": "",
        "tool_name": "Bash",
        "tool_input": {"command": "echo memprofile"},
        "command": "echo memprofile",
        "prompt": "memprofile smoke prompt",
        "last_assistant_message": "",
        "agent_type": "",
        "subagent_type": "",
        "source": "startup",
        "stop_hook_active": False,
    }


_RSS_WRAPPER = """
import json, resource, subprocess, sys, time
cfg = json.loads(open(sys.argv[1], encoding="utf-8").read())
before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
started = time.monotonic()
try:
    proc = subprocess.run(
        cfg["argv"], input=cfg["stdin"], capture_output=True, text=True,
        cwd=cfg["cwd"], timeout=cfg["timeout"], env=cfg["env"],
    )
    rc, err_tail = proc.returncode, proc.stderr[-500:]
except subprocess.TimeoutExpired:
    rc, err_tail = None, "timeout"
wall = time.monotonic() - started
after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
print(json.dumps({"before": before, "after": after, "wall_s": round(wall, 3), "returncode": rc, "stderr_tail": err_tail}))
"""


def measure_hook_rss(hook: dict, timeout: int = 30) -> dict:
    """훅 1개의 최대 RSS. 매 훅을 별도 래퍼 프로세스로 띄우는 이유: `RUSAGE_CHILDREN.ru_maxrss`는
    reap된 자식들의 최댓값(고수위표)이라, 한 프로세스에서 여러 훅을 연달아 재면 먼저 잰 무거운
    훅의 값이 다음의 가벼운 훅 측정에 섞여 나온다. 래퍼마다 `before`가 항상 0에서 시작하므로
    이 훅 하나의 값만 깨끗하게 남는다."""
    import os

    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(REPO)
    argv = ["uv", "run", "--no-project", "python", str(hook["path"]), *hook["argv"]]
    cfg = {
        "argv": argv,
        "stdin": json.dumps(base_payload(hook["event"])),
        "cwd": str(REPO),
        "timeout": timeout,
        "env": env,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(cfg, fh)
        cfg_path = fh.name
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _RSS_WRAPPER, cfg_path],
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )
    finally:
        Path(cfg_path).unlink(missing_ok=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return {**hook_summary(hook), "error": (proc.stderr or "no output")[-500:]}
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    delta_bytes = maxrss_to_bytes(max(0, result["after"] - result["before"]))
    return {
        **hook_summary(hook),
        "max_rss_children_bytes": delta_bytes,
        "max_rss_children_mb": round(delta_bytes / 1_048_576, 2),
        "wall_s": result["wall_s"],
        "returncode": result["returncode"],
        "stderr_tail": result["stderr_tail"],
    }


def hook_summary(hook: dict) -> dict:
    return {"label": hook["label"], "file": hook["path"].name, "argv": hook["argv"], "event": hook["event"]}


_ALLOC_WRAPPER = """
import contextlib, io, json, os, runpy, sys, tracemalloc
cfg = json.loads(open(sys.argv[1], encoding="utf-8").read())
os.chdir(cfg["cwd"])
os.environ["CLAUDE_PROJECT_DIR"] = cfg["cwd"]
sys.argv = [cfg["hook_path"]] + cfg["argv"]
sys.stdin = io.StringIO(cfg["stdin"])
tracemalloc.start(25)
buf = io.StringIO()
error = None
with contextlib.redirect_stdout(buf):
    try:
        runpy.run_path(cfg["hook_path"], run_name="__main__")
    except SystemExit:
        pass
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
snapshot = tracemalloc.take_snapshot()
stats = snapshot.statistics("lineno")
top = [
    {"path_line": str(s.traceback[0]), "size_bytes": s.size, "count": s.count}
    for s in stats[:20]
]
total = sum(s.size for s in stats)
print(json.dumps({"top": top, "total_traced_bytes": total, "error": error}))
"""


def measure_hook_alloc(hook: dict, timeout: int = 30) -> dict:
    """훅 본문의 파이썬 할당 상위 20개 지점 — in-process `runpy.run_path` + `tracemalloc`.
    별도 프로세스로 격리하는 이유: 훅 대부분이 끝에서 `sys.exit()`을 부르는데, 그걸 그대로
    받으면 프로파일러 프로세스 자체가 죽는다."""
    cfg = {
        "hook_path": str(hook["path"]),
        "argv": hook["argv"],
        "stdin": json.dumps(base_payload(hook["event"])),
        "cwd": str(REPO),
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(cfg, fh)
        cfg_path = fh.name
    try:
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", _ALLOC_WRAPPER, cfg_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        Path(cfg_path).unlink(missing_ok=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return {**hook_summary(hook), "error": (proc.stderr or "no output")[-800:]}
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    return {**hook_summary(hook), **result}


STAIRCASE_STEPS: list[tuple[str, str]] = [
    ("python -c pass", "pass"),
    ("import asgard", "import asgard"),
    ("import asgard.memory", "import asgard.memory"),
    ("import asgard.project_memory", "import asgard.project_memory"),
    ("import asgard.hooks.quest_log", "import asgard.hooks.quest_log"),
]


def measure_staircase() -> list[dict]:
    """임포트 표면별 RSS 계단 — 각 단계를 새 프로세스로 재서 `RUSAGE_SELF.ru_maxrss`를 읽는다
    (이전 단계의 페이지가 다음 단계 측정에 남아있지 않도록 단계마다 새 인터프리터)."""
    out = []
    for label, stmt in STAIRCASE_STEPS:
        code = f"import resource, sys; {stmt}; print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)"
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", code],
            capture_output=True,
            text=True,
            cwd=REPO,
            timeout=30,
        )
        if proc.returncode != 0:
            out.append({"step": label, "error": proc.stderr[-500:]})
            continue
        raw = int(proc.stdout.strip().splitlines()[-1])
        out.append(
            {
                "step": label,
                "rss_self_bytes": maxrss_to_bytes(raw),
                "rss_self_mb": round(maxrss_to_bytes(raw) / 1_048_576, 2),
            }
        )
    # 계단 마지막 칸: 훅 하나를 완료 시점까지 실행 (readonly-guard.py, 가장 흔한 PreToolUse 훅)
    hooks = [h for h in load_hook_invocations() if h["path"].name == "readonly-guard.py" and h["event"] == "PreToolUse"]
    if hooks:
        rss = measure_hook_rss(hooks[0])
        out.append(
            {
                "step": "readonly-guard.py 실행 완료 (PreToolUse, RUSAGE_CHILDREN)",
                **{k: v for k, v in rss.items() if k in ("max_rss_children_bytes", "max_rss_children_mb", "wall_s")},
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["rss", "alloc", "staircase", "list"])
    parser.add_argument("--hook", help="alloc/rss 를 파일명 하나로 제한 (예: secret-guard.py)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.mode == "list":
        rows = [hook_summary(h) for h in load_hook_invocations()]
    elif args.mode == "rss":
        hooks = load_hook_invocations()
        if args.hook:
            hooks = [h for h in hooks if h["path"].name == args.hook]
        rows = [measure_hook_rss(h) for h in hooks]
    elif args.mode == "alloc":
        hooks = load_hook_invocations()
        if args.hook:
            hooks = [h for h in hooks if h["path"].name == args.hook]
        rows = [measure_hook_alloc(h) for h in hooks]
    else:
        rows = measure_staircase()

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
