#!/usr/bin/env python3
"""Resident Asgard-surface CPU/memory census — read-only, kills nothing.

Answers one question: outside a hook's own PreToolUse/PostToolUse turn, what keeps
burning CPU or holding RSS? Three classes, each with an explicit match rule so a
substring hit ("asgard" anywhere in a command line) cannot pull in an unrelated
process:

  serve    - the local dashboard server, `node .../asgard-serve.mjs`, matched on the
             basename as the last path segment (not a substring anywhere in argv).
  mcp      - `asgard memory mcp` servers, one pair (uv launcher + python child) per
             open editor session that has the MCP connected. Matched on the three
             literal subcommand tokens in sequence, so `asgard memory query` or
             `asgard memory mcp --help` in a --help listing does not qualify.
  docker   - containers whose name starts with `asgard-` (the compose project
             prefix for this repo) and whose docker-ps status is Up. Exited
             containers and containers from other projects (e.g. `hermes-*`,
             `wams-*`) are not this repo's resident surface.

Anything else that happens to contain the string "asgard" in a `ps` snapshot
(a `pytest` worker, a one-shot `asgard --help` a hook just spawned) is neither
long-running nor a candidate match — it is reported once as a discarded-count so
a reader can tell the rule saw it and chose not to count it, not that the rule
missed it.

Cumulative CPU (`ps -o time`) over wall-clock residency (`ps -o etime`) gives
CPU-seconds-per-hour, which is stable across the run instead of a `%CPU` instant
that depends on what else the machine was doing in the last sampling tick.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_SERVE_RE = re.compile(r"(?:^|/)asgard-serve\.mjs(?:\s|$)")
_MCP_RE = re.compile(r"\basgard\s+memory\s+mcp\b")
_ASGARD_HINT_RE = re.compile(r"\basgard\b", re.IGNORECASE)


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except OSError, subprocess.TimeoutExpired:
        return ""
    return out.stdout if out.returncode == 0 else ""


def _parse_clock(text: str) -> float:
    """`[[DD-]HH:]MM:SS[.hh]` (ps etime/time format on macOS/BSD and Linux) -> seconds."""
    text = text.strip()
    days = 0
    if "-" in text:
        day_part, text = text.split("-", 1)
        days = int(day_part)
    parts = [float(p) for p in text.split(":")]
    padded = [0.0] * (3 - len(parts)) + parts if len(parts) < 3 else parts
    hours, minutes, seconds = padded[-3], padded[-2], padded[-1]
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _ps_snapshot() -> list[dict]:
    raw = _run(["ps", "-axo", "pid=,etime=,time=,rss=,args="])
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        fields = line.split(None, 4)
        if len(fields) < 5:
            continue
        pid, etime, cputime, rss, args = fields
        try:
            rows.append(
                {
                    "pid": int(pid),
                    "etime_s": _parse_clock(etime),
                    "cpu_s": _parse_clock(cputime),
                    "rss_kb": int(rss),
                    "args": args,
                }
            )
        except ValueError:
            continue
    return rows


def _cpu_per_hour(cpu_s: float, etime_s: float) -> float:
    if etime_s <= 0:
        return 0.0
    return cpu_s * 3600.0 / etime_s


def classify_processes() -> dict:
    matched = []
    discarded = 0
    for row in _ps_snapshot():
        args = row["args"]
        if _SERVE_RE.search(args):
            kind = "serve"
        elif _MCP_RE.search(args):
            kind = "mcp"
        elif _ASGARD_HINT_RE.search(args):
            discarded += 1
            continue
        else:
            continue
        matched.append(
            {
                "kind": kind,
                "pid": row["pid"],
                "command": args,
                "etime_s": round(row["etime_s"], 1),
                "cpu_s": round(row["cpu_s"], 2),
                "cpu_s_per_hour": round(_cpu_per_hour(row["cpu_s"], row["etime_s"]), 4),
                "rss_kb": row["rss_kb"],
            }
        )
    return {"matched": matched, "discarded_snapshot_hits": discarded}


def classify_pytest_noise() -> int:
    """Count pytest worker processes present in the same snapshot, reported apart from
    Asgard's own surface per the task's request not to conflate the two."""
    return sum(1 for row in _ps_snapshot() if "pytest" in row["args"] and "asgard" not in row["args"].lower())


def docker_report() -> dict:
    if not shutil.which("docker"):
        return {"available": False, "note": "docker CLI 없음"}
    if not _run(["docker", "info", "--format", "{{.ServerVersion}}"]):
        return {"available": True, "daemon_up": False, "note": "docker 미가동"}
    ps_out = _run(
        ["docker", "ps", "--filter", "status=running", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
    )
    containers = []
    names = []
    for line in ps_out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name = parts[0]
        if not name.startswith("asgard-"):
            continue
        names.append(name)
        containers.append(
            {"name": name, "image": parts[1], "status": parts[2], "ports": parts[3] if len(parts) > 3 else ""}
        )
    if not names:
        return {"available": True, "daemon_up": True, "containers": [], "note": "asgard- 접두 컨테이너 없음"}
    stats_out = _run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}", *names]
    )
    stats_by_name = {}
    for line in stats_out.splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            stats_by_name[parts[0]] = {"cpu_pct": parts[1], "mem_usage": parts[2], "mem_pct": parts[3]}
    for c in containers:
        c.update(stats_by_name.get(c["name"], {}))
    return {"available": True, "daemon_up": True, "containers": containers}


def sqlite_row_counts(path: Path) -> dict:
    """Read-only row counts per table. `mode=ro` refuses any write, including the
    journal-recovery write SQLite would otherwise attempt on a dirty WAL file."""
    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            counts = {}
            for table in tables:
                try:
                    counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                except sqlite3.DatabaseError as exc:
                    counts[table] = f"error: {exc}"
            return {"tables": counts}
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return {"error": str(exc)}


def disk_state() -> dict:
    asgard_dir = REPO_ROOT / ".asgard"
    result: dict = {}

    db_files = sorted(asgard_dir.rglob("*.db")) if asgard_dir.is_dir() else []
    result["db_files"] = []
    for db in db_files:
        try:
            size = db.stat().st_size
        except OSError:
            continue
        entry = {"path": str(db.relative_to(REPO_ROOT)), "size_bytes": size}
        entry.update(sqlite_row_counts(db))
        result["db_files"].append(entry)

    quest_dir = asgard_dir / "quest"
    jsonl_files = sorted(quest_dir.glob("*.jsonl")) if quest_dir.is_dir() else []
    sized = []
    total = 0
    for f in jsonl_files:
        try:
            sz = f.stat().st_size
        except OSError:
            continue
        sized.append((sz, f))
        total += sz
    sized.sort(reverse=True)
    result["quest_jsonl"] = {
        "file_count": len(jsonl_files),
        "total_bytes": total,
        "top5": [{"path": str(f.relative_to(REPO_ROOT)), "size_bytes": sz} for sz, f in sized[:5]],
    }

    def dir_size(path: Path) -> int | None:
        if not path.is_dir():
            return None
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    result["map_dir_bytes"] = dir_size(asgard_dir / "map")
    result["asgard_dir_bytes"] = dir_size(asgard_dir)
    home_asgard = Path.home() / ".asgard"
    result["home_asgard_bytes"] = dir_size(home_asgard)
    result["home_asgard_path"] = str(home_asgard)
    return result


def hook_read_frequency() -> dict:
    """Grep `.claude/hooks/*.py` for literal `.asgard/...` read sites and pair each with
    the events wired to that hook in `.claude/settings.json`, so size x per-turn read
    count is legible without re-deriving it from two files by hand."""
    hooks_dir = REPO_ROOT / ".claude" / "hooks"
    settings_path = REPO_ROOT / ".claude" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        settings = {}

    hook_events: dict[str, list[str]] = {}
    for event_name, matchers in settings.get("hooks", {}).items():
        for matcher in matchers:
            for hook in matcher.get("hooks", []):
                cmd = hook.get("command", "")
                m = re.search(r"hooks/([\w.\-]+\.py)", cmd)
                if m:
                    hook_events.setdefault(m.group(1), []).append(event_name)

    target_re = re.compile(r'"\.asgard[/"][^"]*"|os\.path\.join\([^)]*"\.asgard"[^)]*\)')
    findings = []
    if hooks_dir.is_dir():
        for py in sorted(hooks_dir.glob("*.py")):
            text = py.read_text(encoding="utf-8", errors="replace")
            if target_re.search(text) or ".asgard" in text:
                hits = sorted(set(re.findall(r'"\.asgard[/\w.\-]*"', text)))
                if hits:
                    findings.append(
                        {
                            "hook": py.name,
                            "literal_paths": hits,
                            "events": sorted(set(hook_events.get(py.name, []))),
                        }
                    )
    return {"findings": findings}


def asgard_serve_watch(node: str | None) -> dict:
    script = REPO_ROOT / ".claude" / "scripts" / "asgard-serve.mjs"
    if not script.is_file():
        return {"error": "asgard-serve.mjs not found at expected path", "expected": str(script)}
    text = script.read_text(encoding="utf-8", errors="replace")
    interval_hits = re.findall(r"setInterval\([^,]+,\s*([0-9_]+)\)", text)
    watch_hits = re.findall(r"\b(fs\.watch|chokidar|watchFile)\b", text)
    return {
        "path": str(script.relative_to(REPO_ROOT)),
        "line_count": text.count("\n") + 1,
        "setInterval_ms_args": interval_hits,
        "file_watch_calls": sorted(set(watch_hits)),
    }


def background_jobs() -> dict:
    crontab = _run(["crontab", "-l"])
    launchd = _run(["launchctl", "list"])
    launchd_asgard = [line for line in launchd.splitlines() if "asgard" in line.lower()]
    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    plists = []
    if launch_agents_dir.is_dir():
        plists = [p.name for p in launch_agents_dir.glob("*asgard*")]
    return {
        "crontab": crontab.strip() or "no crontab for user",
        "launchd_list_asgard_lines": launchd_asgard,
        "launchagents_plists": plists,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()

    report = {
        "processes": classify_processes(),
        "pytest_worker_count_excluded": classify_pytest_noise(),
        "docker": docker_report(),
        "ollama": "not running" if not _run(["pgrep", "-f", r"(^|/)ollama($| )"]) else "running",
        "disk": disk_state(),
        "hook_read_frequency": hook_read_frequency(),
        "asgard_serve": asgard_serve_watch(None),
        "background_jobs": background_jobs(),
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for p in report["processes"]["matched"]:
            print(
                f"{p['kind']:6s} pid={p['pid']:<7d} etime={p['etime_s']:.0f}s "
                f"cpu={p['cpu_s']:.2f}s cpu/h={p['cpu_s_per_hour']:.4f}s rss={p['rss_kb']}KB"
            )
        print(
            f"discarded snapshot hits (name contains 'asgard', not serve/mcp): {report['processes']['discarded_snapshot_hits']}"
        )
        print(
            f"pytest workers in same snapshot (excluded, not Asgard's own surface): {report['pytest_worker_count_excluded']}"
        )
        print(json.dumps(report["docker"], indent=2, ensure_ascii=False))
        print(json.dumps(report["disk"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
