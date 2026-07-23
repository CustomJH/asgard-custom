#!/usr/bin/env python3
"""Expose Freyja's complete pinned design engine through one safe entrypoint."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from asgard.settings import global_dir

REVISION = "0a7f3a1e17814c8a1b000ce075b3b2620b70db9e-vanadis3"
SKILL_ROOT = Path(__file__).resolve().parent
UPSTREAM = SKILL_ROOT / "references" / "vanadis"


def _cache_root() -> Path:
    override = os.environ.get("ASGARD_FREYJA_DESIGN_CACHE")
    return Path(override).expanduser().resolve() if override else Path(global_dir(), "cache", "freyja-design", REVISION)


def _program(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"{name} is required")
    return executable


def _relative(root: Path, value: str) -> Path:
    if not value or Path(value).is_absolute():
        raise ValueError("resource path must be relative")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("resource path escapes the design snapshot") from exc
    if not candidate.exists():
        raise ValueError(f"design resource not found: {value}")
    return candidate


def _copy(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _snapshot() -> Path:
    cache = _cache_root()
    source = cache / "source"
    marker = cache / "REVISION"
    if source.is_dir() and marker.is_file() and marker.read_text(encoding="utf-8").strip() == REVISION:
        return source

    cache.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".vanadis-", dir=cache.parent))
    try:
        shutil.copytree(UPSTREAM, staging / "source")
        (staging / "REVISION").write_text(REVISION + "\n", encoding="utf-8")
        if cache.exists():
            shutil.rmtree(cache)
        os.replace(staging, cache)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return source


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_ready(source: Path) -> None:
    if (source / ".git").is_dir():
        return
    git = _program("git")
    commands = (
        [git, "init", "-q"],
        [git, "add", "-f", "--all"],
        [git, "-c", "user.name=Asgard", "-c", "user.email=asgard@localhost", "commit", "-qm", "Design snapshot"],
    )
    for command in commands:
        code = subprocess.run(command, cwd=source, check=False).returncode
        if code:
            raise RuntimeError(f"git cache initialization failed with exit code {code}")


def _npm_ready(package_root: Path) -> None:
    npm = _program("npm")
    lock = package_root / "package-lock.json"
    if not lock.is_file():
        raise RuntimeError(f"package-lock.json is missing: {package_root}")
    relative = package_root.relative_to(_snapshot())
    label = "root" if relative == Path(".") else relative.as_posix().replace("/", "-")
    marker = _cache_root() / "state" / label
    current = _digest(lock)
    if (package_root / "node_modules").is_dir() and marker.is_file() and marker.read_text().strip() == current:
        return
    code = subprocess.run(
        [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=package_root,
        check=False,
    ).returncode
    if code:
        raise RuntimeError(f"npm ci failed with exit code {code}: {package_root}")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(current + "\n", encoding="utf-8")


def _root_ready() -> Path:
    source = _snapshot()
    _npm_ready(source)
    cli = source / "dist" / "bin" / "vanadis.js"
    if not cli.is_file():
        code = subprocess.run([_program("npm"), "run", "build"], cwd=source, check=False).returncode
        if code:
            raise RuntimeError(f"design CLI build failed with exit code {code}")
    return source


def _package_script(area: str, script: str, arguments: list[str]) -> int:
    source = _snapshot()
    packages = {"root": source, "web": source / "web", "mcp": source / "packages" / "mcp"}
    if area not in packages:
        raise ValueError("npm area must be root, web, or mcp")
    package_root = packages[area]
    _git_ready(source)
    if area == "mcp":
        _npm_ready(source / "web")
    _npm_ready(package_root)
    scripts = json.loads((package_root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
    if script not in scripts:
        raise ValueError(f"unknown {area} npm script: {script}")
    command = [_program("npm"), "run", script]
    if arguments:
        command.extend(["--", *arguments])
    return subprocess.run(command, cwd=package_root, check=False).returncode


def _run_file(relative: str, arguments: list[str]) -> int:
    source = _snapshot()
    target = _relative(source, relative)
    if not target.is_file():
        raise ValueError(f"script is not a file: {relative}")
    suffix = target.suffix.lower()
    if suffix == ".py":
        command = [sys.executable, str(target)]
    elif suffix in {".js", ".mjs", ".cjs"}:
        command = [_program("node"), str(target)]
    elif suffix == ".ts":
        command = [_program("node"), "--no-warnings", "--experimental-strip-types", str(target)]
    elif suffix == ".sh":
        command = [_program("bash"), str(target)]
    else:
        raise ValueError(f"unsupported executable resource: {relative}")
    if target.is_relative_to(source / "web"):
        _npm_ready(source / "web")
    elif target.is_relative_to(source / "packages" / "mcp"):
        _npm_ready(source / "web")
        _npm_ready(source / "packages" / "mcp")
    else:
        _npm_ready(source)
    return subprocess.run([*command, *arguments], cwd=source, check=False).returncode


def _help() -> None:
    print(
        """usage: asgard skills run asgard-freyja-design -- COMMAND [ARGS]

commands:
  cli [ARGS]                    Run the pinned design source CLI
  prepare [cli|web|mcp|all]     Prepare pinned dependencies (and build the CLI)
  npm [root|web|mcp] SCRIPT     Run any declared upstream package script
  script PATH [ARGS]            Run a pinned Python, Node, TypeScript, or shell script
  list [PREFIX]                 List bundled design source files
  resource PATH                 Print one UTF-8 resource
  extract PATH DESTINATION      Copy any text, binary, or directory resource
  materialize DESTINATION       Copy the complete pinned reference repository
  reference list [QUERY]        List the 440 DESIGN.md reference ids
  reference show ID             Print one canonical DESIGN.md
  reference copy ID DESTINATION Copy one canonical DESIGN.md
"""
    )


def _prepare(area: str) -> int:
    if area not in {"cli", "web", "mcp", "all"}:
        raise ValueError("prepare target must be cli, web, mcp, or all")
    if area in {"cli", "all"}:
        _root_ready()
    if area in {"web", "all"}:
        _npm_ready(_snapshot() / "web")
    if area in {"mcp", "all"}:
        _npm_ready(_snapshot() / "web")
        _npm_ready(_snapshot() / "packages" / "mcp")
    return 0


def _reference(arguments: list[str]) -> int:
    if not arguments:
        raise ValueError("reference requires list, show, or copy")
    action, *rest = arguments
    references = UPSTREAM / "design-md"
    if action == "list":
        query = " ".join(rest).casefold()
        ids = sorted(item.parent.name for item in references.glob("*/DESIGN.md"))
        print("\n".join(item for item in ids if not query or query in item.casefold()))
        return 0
    if action not in {"show", "copy"} or not rest:
        raise ValueError("reference usage: reference list [QUERY] | show ID | copy ID DESTINATION")
    design = _relative(references, f"{rest[0]}/DESIGN.md")
    if action == "show":
        print(design.read_text(encoding="utf-8"), end="")
        return 0
    if len(rest) != 2:
        raise ValueError("reference copy requires ID and DESTINATION")
    _copy(design, Path(rest[1]).expanduser().resolve())
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv or argv[0] in {"-h", "--help", "help"}:
        _help()
        return 0
    command, *arguments = argv
    if command == "cli":
        source = _root_ready()
        return subprocess.run(
            [_program("node"), str(source / "dist" / "bin" / "vanadis.js"), *arguments],
            cwd=Path.cwd(),
            check=False,
        ).returncode
    if command == "prepare":
        return _prepare(arguments[0] if arguments else "all")
    if command == "npm" and len(arguments) >= 2:
        return _package_script(arguments[0], arguments[1], arguments[2:])
    if command == "script" and arguments:
        return _run_file(arguments[0], arguments[1:])
    if command == "list":
        prefix = arguments[0] if arguments else ""
        print(
            "\n".join(
                item.relative_to(UPSTREAM).as_posix()
                for item in sorted(UPSTREAM.rglob("*"))
                if item.is_file() and item.relative_to(UPSTREAM).as_posix().startswith(prefix)
            )
        )
        return 0
    if command == "resource" and len(arguments) == 1:
        print(_relative(UPSTREAM, arguments[0]).read_text(encoding="utf-8"), end="")
        return 0
    if command == "extract" and len(arguments) == 2:
        _copy(_relative(UPSTREAM, arguments[0]), Path(arguments[1]).expanduser().resolve())
        return 0
    if command == "materialize" and len(arguments) == 1:
        _copy(UPSTREAM, Path(arguments[0]).expanduser().resolve())
        return 0
    if command == "reference":
        return _reference(arguments)
    raise ValueError(f"unknown or incomplete command: {command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, RuntimeError, ValueError, UnicodeError) as exc:
        print(f"freyja-design: {exc}", file=sys.stderr)
        raise SystemExit(2)
