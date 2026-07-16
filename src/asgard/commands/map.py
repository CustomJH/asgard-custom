"""`asgard setup map` — deterministic project-map setup, refresh, and drift check."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from .. import ui
from ..code_map import MapError, check_map, refresh_map


def _project_root(start: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return str(Path(proc.stdout.strip()).resolve())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return str(Path(start).resolve())


def _gitignore_preview(root: str) -> tuple[Path, str | None, str, bool, Path, str, bool]:
    from .setup import _ASGARD_GITIGNORE, merge_gitignore

    path = Path(root, ".gitignore")
    try:
        previous = path.read_text(encoding="utf-8")
    except OSError:
        previous = None
    merged = merge_gitignore(previous)
    internal = Path(root, ".asgard", ".gitignore")
    try:
        internal_previous = internal.read_text(encoding="utf-8")
    except OSError:
        internal_previous = None
    internal_changed = internal_previous != _ASGARD_GITIGNORE
    return path, previous, merged, merged != previous, internal, _ASGARD_GITIGNORE, internal_changed


def _atomic_root_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def run_setup_map(*, check: bool = False, dry_run: bool = False, json_out: bool = False, quiet: bool = False) -> int:
    root = _project_root(os.getcwd())
    ui.set_quiet(quiet or json_out)
    if check and dry_run:
        payload = {"error": "--check and --dry-run are mutually exclusive"}
        if json_out:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            ui.fail(payload["error"])
        return 2
    ignore, _previous, merged, gitignore_changed, internal_ignore, internal_merged, internal_changed = _gitignore_preview(root)
    try:
        if check:
            result = check_map(root)
            ok = result.ok and not gitignore_changed and not internal_changed
            payload = asdict(result)
            payload.update(
                {"ok": ok, "gitignore_changed": gitignore_changed, "asgard_gitignore_changed": internal_changed}
            )
            if json_out:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            elif ok:
                ui.done("project map is current")
            else:
                ui.warn("project map drift detected")
                for path in result.added:
                    ui.step(f"added   {path}")
                for path in result.removed:
                    ui.step(f"removed {path}")
                ui.step("run: asgard setup map")
            return 0 if ok else 1

        preview = refresh_map(root, dry_run=True)
        changed = preview.changed or preview.index_changed or gitignore_changed or internal_changed
        result = preview
        if not dry_run:
            if gitignore_changed:
                _atomic_root_write(ignore, merged)
            result = refresh_map(root)
            if internal_changed:
                _atomic_root_write(internal_ignore, internal_merged)
        payload = asdict(result)
        payload.update(
            {
                "project_changed": preview.changed,
                "changed": changed,
                "index_changed": preview.index_changed,
                "gitignore_changed": gitignore_changed,
                "asgard_gitignore_changed": internal_changed,
                "dry_run": dry_run,
            }
        )
    except (MapError, OSError) as exc:
        payload = {"error": str(exc)}
        if json_out:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            ui.fail(str(exc))
        return 2
    if json_out:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif dry_run:
        ui.head("setup · project map preview")
        ui.step(f"{result.files_scanned} files → {result.landmarks} landmarks")
        ui.step(("would update " if changed else "already current ") + result.path)
    else:
        ui.head("setup · project map")
        ui.ok(f"{result.files_scanned} files → {result.landmarks} landmarks")
        ui.done(("updated " if changed else "current ") + result.path)
    return 0
