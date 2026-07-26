#!/usr/bin/env python3
"""Same-task A/B: a direct agent command versus `asgard run`.

The harness owns fresh Git fixtures and post-run checks. Both arms receive the same prompt and
repository; model/provider selection remains explicit in the command templates.

Examples:
  uv run python benchmarks/core-loop/harness.py --self-check
  uv run python benchmarks/core-loop/harness.py \
    --control 'claude -p --model sonnet {prompt}' \
    --candidate '/abs/asgard run --json --provider claude-native --model sonnet {prompt}'
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_ASGARD = REPO / ".venv" / "bin" / "asgard"
DEFAULT_RESULTS = HERE / "results.jsonl"

TASKS = (
    {
        "id": "simple-fix",
        "prompt": "Fix add() so it returns the arithmetic sum. Preserve the public signature and run the tests.",
        "files": {
            "calc.py": "def add(left, right):\n    return left - right\n",
            "test_calc.py": (
                "import unittest\nfrom calc import add\n\n"
                "class AddTest(unittest.TestCase):\n"
                "    def test_positive_and_negative(self):\n"
                "        self.assertEqual(add(4, 3), 7)\n"
                "        self.assertEqual(add(-2, 5), 3)\n\n"
                "if __name__ == '__main__': unittest.main()\n"
            ),
        },
    },
    {
        "id": "hidden-caller",
        "prompt": (
            "Make a missing catalog lookup return None and make the existing service render 'missing'. "
            "Do not break found records. Run the tests."
        ),
        "files": {
            "catalog.py": (
                "def find(records, key):\n    return next(record for record in records if record['id'] == key)\n"
            ),
            "service.py": (
                "from catalog import find\n\ndef label(records, key):\n    return find(records, key)['name']\n"
            ),
            "test_catalog.py": (
                "import unittest\nfrom catalog import find\nfrom service import label\n\n"
                "ROWS = [{'id': 1, 'name': 'one'}]\n\n"
                "class CatalogTest(unittest.TestCase):\n"
                "    def test_found_and_missing(self):\n"
                "        self.assertEqual(find(ROWS, 1), ROWS[0])\n"
                "        self.assertIsNone(find(ROWS, 2))\n"
                "        self.assertEqual(label(ROWS, 2), 'missing')\n\n"
                "if __name__ == '__main__': unittest.main()\n"
            ),
        },
    },
    {
        "id": "security-boundary",
        "prompt": (
            "Use a constant-time comparison for non-None tokens while preserving None rejection. "
            "Do not change the public signature. Run the tests."
        ),
        "files": {
            "auth.py": (
                "def token_matches(provided, expected):\n"
                "    if provided is None or expected is None:\n"
                "        return False\n"
                "    return provided == expected\n"
            ),
            "test_auth.py": (
                "import hmac\nimport unittest\nfrom unittest import mock\nimport auth\n\n"
                "class AuthTest(unittest.TestCase):\n"
                "    def test_boundary_and_constant_time_compare(self):\n"
                "        self.assertFalse(auth.token_matches(None, 'x'))\n"
                "        with mock.patch('auth.hmac.compare_digest', wraps=hmac.compare_digest) as compare:\n"
                "            self.assertTrue(auth.token_matches('x', 'x'))\n"
                "            self.assertFalse(auth.token_matches('x', 'y'))\n"
                "            self.assertEqual(compare.call_count, 2)\n\n"
                "if __name__ == '__main__': unittest.main()\n"
            ),
        },
    },
)


def _run(args: list[str], root: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=timeout, check=False)


def _build(root: Path, task: dict) -> str:
    for rel, body in task["files"].items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _run(["git", "init", "-q"], root, 30)
    _run(["git", "config", "user.email", "core-bench@asgard.local"], root, 30)
    _run(["git", "config", "user.name", "Asgard Core Bench"], root, 30)
    _run(["git", "add", "-A"], root, 30)
    _run(["git", "commit", "-qm", "fixture"], root, 30)
    tests = "\0".join(task["files"][path] for path in sorted(task["files"]) if path.startswith("test_"))
    return hashlib.sha256(tests.encode()).hexdigest()


def _test_hash(root: Path) -> str:
    rows = []
    for path in sorted(root.glob("test_*.py")):
        rows.append(path.read_text(encoding="utf-8"))
    return hashlib.sha256("\0".join(rows).encode()).hexdigest()


def _command(template: str, prompt: str) -> list[str]:
    parts = shlex.split(template)
    if not any("{prompt}" in part for part in parts):
        raise ValueError("command template must contain {prompt}")
    return [part.replace("{prompt}", prompt) for part in parts]


def _json_tail(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return {}


def _quest_metrics(root: Path) -> dict:
    logs = sorted((root / ".asgard" / "quest").glob("*.jsonl")) if (root / ".asgard" / "quest").exists() else []
    events = []
    for path in logs:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    closes = [event for event in events if event.get("event") == "quest_closed"]
    return {
        "quest_events": len(events),
        "verify_failures": sum(event.get("event") == "verify" and event.get("verdict") == "FAIL" for event in events),
        "replans": max(0, sum(event.get("event") == "plan" for event in events) - bool(events)),
        "approved_close": bool(closes and (closes[-1].get("risk") or {}).get("decision") == "APPROVED"),
    }


def _one(task: dict, arm: str, template: str, timeout: int) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"asgard-core-{task['id']}-{arm}-") as tmp:
        root = Path(tmp)
        expected_tests = _build(root, task)
        started = time.monotonic()
        result = _run(_command(template, task["prompt"]), root, timeout)
        wall = round(time.monotonic() - started, 3)
        checked = _run(["python3", "-m", "unittest", "-q"], root, 60)
        payload = _json_tail(result.stdout)
        status = _run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", ".", ":(exclude).asgard"],
            root,
            30,
        ).stdout.splitlines()
        return {
            "task": task["id"],
            "arm": arm,
            "agent_exit": result.returncode,
            "checks_passed": checked.returncode == 0 and _test_hash(root) == expected_tests,
            "tests_preserved": _test_hash(root) == expected_tests,
            "wall_s": wall,
            "tokens": payload.get("tokens"),
            "changed": [line[3:] for line in status],
            "stdout_tail": result.stdout[-500:],
            "stderr_tail": result.stderr[-500:],
            **_quest_metrics(root),
        }


def _summary(rows: list[dict]) -> dict:
    out = {}
    for arm in ("control", "asgard"):
        selected = [row for row in rows if row["arm"] == arm]
        walls = [row["wall_s"] for row in selected]
        tokens = [row["tokens"] for row in selected if isinstance(row.get("tokens"), int)]
        out[arm] = {
            "runs": len(selected),
            "success_rate": round(sum(row["checks_passed"] for row in selected) / len(selected), 3),
            "median_wall_s": round(statistics.median(walls), 3),
            "median_tokens": statistics.median(tokens) if tokens else None,
            "verified_close_rate": round(sum(row["approved_close"] for row in selected) / len(selected), 3),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", help="direct-agent command template; must contain {prompt}")
    parser.add_argument(
        "--candidate",
        default=f"{DEFAULT_ASGARD} run --json {{prompt}}",
        help="Asgard command template; must contain {prompt}",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--out", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        for task in TASKS:
            with tempfile.TemporaryDirectory(prefix="asgard-core-self-check-") as tmp:
                root = Path(tmp)
                _build(root, task)
                assert _run(["python3", "-m", "unittest", "-q"], root, 60).returncode != 0
        print(json.dumps({"fixtures": len(TASKS), "initially_red": True}))
        return 0
    if not args.control:
        parser.error("--control is required unless --self-check is used")
    if args.runs < 1:
        parser.error("--runs must be positive")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for run_index in range(args.runs):
        arms = (("control", args.control), ("asgard", args.candidate))
        if run_index % 2:
            arms = tuple(reversed(arms))
        for task in TASKS:
            for arm, template in arms:
                row = {"run": run_index + 1, **_one(task, arm, template, args.timeout)}
                rows.append(row)
                with args.out.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(json.dumps(row, ensure_ascii=False))
    print(json.dumps({"summary": _summary(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
