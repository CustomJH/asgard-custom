#!/usr/bin/env python3
"""In-process CPU profile harness for the four costliest Asgard Claude Code hooks.

Runs one hook script per process under `cProfile` via `runpy.run_path()`, after swapping
`sys.stdin` for a realistic event payload and `sys.argv` for the argv tail the real
matcher in `.claude/settings.json` registers, so the profiled branch matches what a live
session actually takes (not just "the script loaded and exited"). Import cost is measured
separately with `python -X importtime` (a subprocess, not cProfile) — cProfile times
function calls, so it cannot split "importing a module" from "the first call into it";
importtime's own per-module self/cumulative columns can.

Each hook is profiled in a fresh interpreter (invoked as a subprocess of this script under
`--all`, or once per direct `--hook` call) so `sys.modules` caching from one hook's imports
never discounts the next hook's import cost.

Two hooks need setup that does not exist by default: `tutor-note` only takes its review
branch when a session's write journal is non-empty (`_writes()` in tutor-note.py), and
`map-activate` only skips a full `asgard map update` when its 6-hour freshness marker is
recent (`REFRESH_SECONDS` in map-activate.py) — profiling without freshening it would
measure a full map rebuild, not the steady per-turn cost. `_setup`/`_teardown` create and
restore exactly those two files around the profiled run.

Usage:
  python3 hotpath.py --hook tutor-note --root <repo> [--mode exec|importtime|both] [--json]
  python3 hotpath.py --all --root <repo> --json
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import pstats
import runpy
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS_DIR = os.path.join(REPO_ROOT, ".claude", "hooks")
SID = "cpu-profile-bench"
# A realistic UserPromptSubmit body — short greetings skip scope-activate's 8-char floor
# and would not exercise the branch this harness is profiling.
PROMPT = (
    "verifier-gate 훅의 diff_state 해시 계산이 대형 저장소에서 느려지는 원인을 찾아 "
    "캐시 계층을 붙이고 회귀 테스트를 추가해줘"
)


def _payload_tutor_note(root: str) -> dict:
    return {"hook_event_name": "Stop", "session_id": SID, "cwd": root}


def _payload_memory_activate(root: str) -> dict:
    return {"hook_event_name": "SessionStart", "session_id": SID, "cwd": root}


def _payload_scope_activate(root: str) -> dict:
    return {"hook_event_name": "UserPromptSubmit", "prompt": PROMPT, "session_id": SID, "cwd": root}


def _payload_map_activate(root: str) -> dict:
    return {"hook_event_name": "UserPromptSubmit", "prompt": PROMPT, "session_id": SID, "cwd": root}


# hook name -> (argv tail the real matcher registers, payload builder). Matchers read from
# `.claude/settings.json` on 2026-08-14 (Stop/SessionStart/UserPromptSubmit rows).
HOOKS = {
    "tutor-note": ([], _payload_tutor_note),
    "memory-activate": ([], _payload_memory_activate),
    "scope-activate": ([], _payload_scope_activate),
    "map-activate": ([], _payload_map_activate),
}


def _writes_state_path(root: str) -> str:
    return os.path.join(root, ".asgard", "state", "writes-" + SID + ".json")


def _map_marker_path(root: str) -> str:
    return os.path.join(root, ".asgard", "state", "map-maintained")


def _setup(hook: str, root: str) -> list[tuple[str, bool, str | None]]:
    """Write the state that puts `hook` on its expensive branch; return what to restore."""
    restore: list[tuple[str, bool, str | None]] = []
    if hook == "tutor-note":
        path = _writes_state_path(root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existed = os.path.exists(path)
        previous = open(path, encoding="utf-8").read() if existed else None
        with open(path, "w", encoding="utf-8") as handle:
            # One real file (no git call in `_reviewable`) and one missing path (forces the
            # `git cat-file -e HEAD:...` branch) so both code paths show up in the profile.
            json.dump(["AGENTS.md", "benchmarks/cpu-profile/DOES_NOT_EXIST_PROBE.md"], handle)
        restore.append((path, existed, previous))
    if hook == "map-activate":
        path = _map_marker_path(root)
        existed = os.path.exists(path)
        previous = open(path, encoding="utf-8").read() if existed else None
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(int(time.time())) + "\n")
        restore.append((path, existed, previous))
    return restore


def _teardown(restore: list[tuple[str, bool, str | None]]) -> None:
    for path, existed, previous in restore:
        try:
            if existed:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(previous or "")
            else:
                os.remove(path)
        except OSError:
            pass  # best-effort restore — a leftover scratch file does not affect the repo


def clear_synthetic_state() -> list[str]:
    """훅이 이 하네스의 합성 세션(`SID`) 앞으로 남긴 `.asgard/state` 파일을 지운다.

    `SID` 는 이 파일이 정한 고정 문자열이라 실제 세션 id 와 겹치지 않는다 — 지우는 대상이
    이 하네스 자신의 산물로 한정된다.
    """
    state = os.path.join(REPO_ROOT, ".asgard", "state")
    removed = []
    if os.path.isdir(state):
        for name in os.listdir(state):
            if SID in name:
                try:
                    os.remove(os.path.join(state, name))
                    removed.append(name)
                except OSError:
                    pass  # 다른 프로세스가 먼저 지웠거나 권한이 없으면 그대로 둔다
    return removed


def _top_functions(profiler, limit: int) -> list[dict]:
    stats = pstats.Stats(profiler)
    rows = []
    # `Stats.stats` 는 실재하는 속성인데 typeshed 에 선언이 없다 (CPython Lib/pstats.py).
    for (path, line, func), (_cc, nc, tt, ct, _callers) in stats.stats.items():  # ty: ignore[unresolved-attribute]
        rows.append(
            {
                "function": "%s:%s(%s)" % (os.path.basename(path), line, func),
                "ncalls": nc,
                "tottime_ms": round(tt * 1000, 3),
                "cumtime_ms": round(ct * 1000, 3),
            }
        )
    rows.sort(key=lambda row: row["cumtime_ms"], reverse=True)
    return rows[:limit]


def _profile_exec(script: str, argv_tail: list[str], payload: dict, root: str, limit: int) -> dict:
    import cProfile

    old_argv, old_stdin = sys.argv, sys.stdin
    old_env = dict(os.environ)
    sys.argv = [script, *argv_tail]
    sys.stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
    os.environ["CLAUDE_PROJECT_DIR"] = root  # matches the real host — skips paths.repo_root()'s git fallback
    profiler = cProfile.Profile()
    hook_stdout = io.StringIO()
    start = time.perf_counter()
    profiler.enable()
    try:
        # The hook's own stdout (its actual hookSpecificOutput payload) is not this
        # harness's diagnostic output — captured separately so the two JSON streams do
        # not interleave on the real stdout the caller reads.
        with contextlib.redirect_stdout(hook_stdout):
            runpy.run_path(script, run_name="__main__")
    except SystemExit:
        pass  # every hook ends its main() with sys.exit() via asgard_hooklib.firing.run
    finally:
        profiler.disable()
        elapsed_ms = (time.perf_counter() - start) * 1000
        sys.argv, sys.stdin = old_argv, old_stdin
        os.environ.clear()
        os.environ.update(old_env)
    return {
        "elapsed_ms": round(elapsed_ms, 1),
        "hook_stdout_bytes": len(hook_stdout.getvalue()),
        "top_functions": _top_functions(profiler, limit),
    }


def _parse_importtime(stderr_text: str) -> list[dict]:
    """Parse `python -X importtime` stderr lines: `import time: self | cumulative | name`.

    The `name` column's leading-space count encodes nesting depth (nested imports of an
    import) — cpython's own `Lib/importlib/_bootstrap.py` formatting. Depth must survive
    parsing: a stripped name loses the only signal that separates "this hook imported it
    directly" (depth 1) from "a depth-1 import pulled this in as a dependency" (depth 2+),
    and summing the wrong set double-counts nested time inside its parent's cumulative.
    """
    rows = []
    for line in stderr_text.splitlines():
        if not line.startswith("import time:"):
            continue
        body = line[len("import time:") :]
        parts = body.split("|")
        if len(parts) != 3:
            continue
        self_us, cumulative_us, raw_name = parts
        depth = len(raw_name) - len(raw_name.lstrip(" "))
        try:
            rows.append(
                {
                    "name": raw_name.strip(),
                    "depth": depth,
                    "self_us": int(self_us.strip()),
                    "cumulative_us": int(cumulative_us.strip()),
                }
            )
        except ValueError:
            continue  # header row ("self [us] | cumulative | imported package")
    return rows


def _profile_importtime(script: str, argv_tail: list[str], payload: dict, root: str) -> dict:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = root
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-X", "importtime", script, *argv_tail],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        cwd=root,
        env=env,
        timeout=60,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    rows = _parse_importtime(proc.stderr)
    min_depth = min((row["depth"] for row in rows), default=0)
    # Top-level entries are siblings in program order — their cumulative windows do not
    # overlap, so the sum across them (not the last row alone) is the total import wall time.
    top_level = [row for row in rows if row["depth"] == min_depth]
    return {
        "elapsed_ms": round(elapsed_ms, 1),
        "total_import_us": sum(row["cumulative_us"] for row in top_level),
        "top_level_imports": sorted(top_level, key=lambda r: r["cumulative_us"], reverse=True)[:15],
        "all_rows": rows,
    }


def run_hook(hook: str, root: str, mode: str, limit: int) -> dict:
    if hook not in HOOKS:
        raise SystemExit("unknown hook: %s (know: %s)" % (hook, ", ".join(HOOKS)))
    argv_tail, payload_fn = HOOKS[hook]
    script = os.path.join(HOOKS_DIR, hook + ".py")
    payload = payload_fn(root)
    restore = _setup(hook, root)
    try:
        result: dict = {"hook": hook, "payload": payload, "argv_tail": argv_tail}
        if mode in ("exec", "both"):
            result["exec"] = _profile_exec(script, argv_tail, payload, root, limit)
        if mode in ("importtime", "both"):
            result["importtime"] = _profile_importtime(script, argv_tail, payload, root)
        return result
    finally:
        _teardown(restore)


def run_all_isolated(root: str, mode: str, limit: int) -> list[dict]:
    """One subprocess per hook — keeps `sys.modules` caching from leaking between hooks."""
    results = []
    for hook in HOOKS:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--hook", hook, "--root", root, "--mode", mode, "--json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            results.append({"hook": hook, "error": proc.stderr[-4000:]})
            continue
        results.append(json.loads(proc.stdout))
    return results


def _print_human(result: dict, limit: int) -> None:
    print("== %s ==" % result["hook"])
    if "exec" in result:
        print("  exec: %.1fms wall (cProfile)" % result["exec"]["elapsed_ms"])
        for row in result["exec"]["top_functions"][: min(10, limit)]:
            print(
                "    %8.2fms cum  %8.2fms self  %-6d calls  %s"
                % (row["cumtime_ms"], row["tottime_ms"], row["ncalls"], row["function"])
            )
    if "importtime" in result:
        it = result["importtime"]
        print(
            "  importtime: %.1fms wall, %.2fms total import (all modules)"
            % (it["elapsed_ms"], it["total_import_us"] / 1000)
        )
        for row in it["top_level_imports"][:8]:
            print("    %8.2fms cum  %s" % (row["cumulative_us"] / 1000, row["name"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hook", choices=sorted(HOOKS))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--root", default=REPO_ROOT)
    parser.add_argument("--mode", choices=("exec", "importtime", "both"), default="both")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.hook and not args.all:
        parser.error("pass --hook <name> or --all")

    if args.all:
        results = run_all_isolated(args.root, args.mode, args.top)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            for result in results:
                _print_human(result, args.top)
        return

    result = run_hook(args.hook, args.root, args.mode, args.top)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result, args.top)


if __name__ == "__main__":
    try:
        main()
    finally:
        clear_synthetic_state()
