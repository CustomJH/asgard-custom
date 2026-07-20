"""Container execution boundaries for ``asgard start``."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from hashlib import sha256
from importlib.resources import files
from pathlib import Path

from . import __version__

MODES = ("local", "container", "container-shared", "sandbox", "sandbox-shared")
_NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}")
_API_KEY_ENVS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "NVIDIA_API_KEY",
    "OLLAMA_API_KEY",
)


def choose_mode(requested: str | None) -> str:
    """Resolve an explicit/env mode, or ask only in an interactive host terminal."""
    mode = requested or os.environ.get("ASGARD_EXECUTION")
    if mode:
        if mode not in MODES:
            raise ValueError(f"execution must be one of: {', '.join(MODES)}")
        return mode
    if not sys.stdin.isatty():
        return "local"
    sys.stdout.write(
        "\n  execution environment\n"
        "    1  local            fastest; agent can reach the host\n"
        "    2  container        private workspace; Docker/Podman on macOS or Windows\n"
        "    3  container shared edits the host working tree live\n"
        "    4  Docker Sandbox   microVM + private Git clone (requires sbx login)\n"
    )
    try:
        answer = input("  number [1]: ").strip() or "1"
    except EOFError, KeyboardInterrupt:
        return "local"
    return {"1": "local", "2": "container", "3": "container-shared", "4": "sandbox"}.get(answer, "local")


def sandbox_name(root: str, shared: bool = False) -> str:
    leaf = re.sub(r"[^a-zA-Z0-9.+-]+", "-", os.path.basename(os.path.abspath(root))).strip("-") or "project"
    digest = sha256(os.path.abspath(root).encode()).hexdigest()[:8]
    return f"asgard-{leaf[:35]}-{digest}-{'shared' if shared else 'isolated'}"


def _container_engine() -> str | None:
    requested = os.environ.get("ASGARD_CONTAINER_ENGINE")
    if requested:
        return shutil.which(requested)
    return shutil.which("docker") or shutil.which("podman")


def _private_workspace(root: str, name: str) -> Path:
    if not _NAME_RE.fullmatch(name):
        raise ValueError("sandbox name must contain only letters, numbers, '.', '_' or '-'")
    target = Path.home() / ".asgard" / "sandboxes" / name
    if target.is_symlink():
        raise ValueError("sandbox workspace cannot be a symlink")
    if target.exists():
        if not target.is_dir():
            raise ValueError("sandbox workspace must be a directory")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)

    git = shutil.which("git")
    if git:
        top = subprocess.run([git, "-C", root, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode == 0:
            dirty = subprocess.run([git, "-C", root, "status", "--porcelain"], capture_output=True, text=True)
            if dirty.stdout.strip():
                sys.stderr.write("Note: private workspace starts from HEAD; uncommitted host changes are not copied.\n")
            cloned = subprocess.run([git, "clone", "--local", "--no-hardlinks", root, str(target)], check=False)
            if cloned.returncode == 0:
                subprocess.run([git, "-C", str(target), "remote", "remove", "origin"], check=False)
                return target
            if target.exists():
                shutil.rmtree(target)
    shutil.copytree(root, target, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    return target


def run_container(root: str, *, shared: bool = False, name: str | None = None) -> int:
    """Run Asgard in a login-free Docker-compatible container."""
    engine = _container_engine()
    if not engine:
        sys.stderr.write(
            "A Docker-compatible engine is required.\n"
            "Install OrbStack/Docker on macOS, or Podman Desktop/Docker Desktop on Windows.\n"
            "No Docker Sandboxes account is required.\n"
        )
        return 2

    name = name or sandbox_name(root, shared)
    if not _NAME_RE.fullmatch(name):
        sys.stderr.write("sandbox name must contain only letters, numbers, '.', '_' or '-'\n")
        return 2
    try:
        workspace = Path(root) if shared else _private_workspace(root, name)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"Cannot create isolated workspace: {exc}\n")
        return 2

    image = f"asgard-runtime:{__version__}"
    inspected = subprocess.run([engine, "image", "inspect", image], capture_output=True, text=True, check=False)
    if inspected.returncode:
        kit = str(files("asgard").joinpath("assets", "container_kit"))
        built = subprocess.run(
            [engine, "build", "--build-arg", f"ASGARD_VERSION={__version__}", "-t", image, kit], check=False
        )
        if built.returncode:
            return built.returncode

    container_name = f"{name}-{os.getpid()}"
    cmd = [
        engine,
        "run",
        "--rm",
        "--name",
        container_name,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
    ]
    if sys.stdin.isatty() and sys.stdout.isatty():
        cmd.append("-it")
    cmd.extend(("--mount", f"type=bind,src={workspace},dst=/workspace"))
    cmd.extend(("--env", "ASGARD_EXECUTION=local", "--env", "ASGARD_ISOLATION=oci-container"))
    for key in _API_KEY_ENVS:
        if key in os.environ:
            cmd.extend(("--env", key))
    cmd.append(image)
    sys.stderr.write(f"Starting {Path(engine).name} container {container_name}.\n")
    sys.stderr.write(f"Workspace: {workspace}{' (host working tree)' if shared else ' (private copy)'}\n")
    return subprocess.run(cmd, cwd=root, check=False).returncode


def run(root: str, *, shared: bool = False, name: str | None = None) -> int:
    """Create or reattach to the Asgard Docker Sandbox for ``root``."""
    sbx = shutil.which("sbx")
    if not sbx:
        sys.stderr.write(
            "Docker Sandboxes CLI (sbx) is required.\n"
            "macOS: brew trust docker/tap && brew install docker/tap/sbx\n"
            "Then run: sbx login\n"
        )
        return 2

    if not shared:
        git_bin = shutil.which("git")
        if not git_bin:
            sys.stderr.write("Private-clone isolation requires Git; use --execution sandbox-shared.\n")
            return 2
        git = subprocess.run(
            [git_bin, "-C", root, "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
        )
        if git.returncode:
            sys.stderr.write("Private-clone isolation requires a Git repository; use --execution sandbox-shared.\n")
            return 2
        dirty = subprocess.run(
            [git_bin, "-C", root, "status", "--porcelain"], capture_output=True, text=True, check=False
        )
        if dirty.stdout.strip():
            sys.stderr.write("Note: private clone starts from HEAD; uncommitted host changes are not copied.\n")

    name = name or sandbox_name(root, shared)
    listed = subprocess.run([sbx, "ls", "-q"], capture_output=True, text=True, check=False)
    if listed.returncode == 0 and name in listed.stdout.splitlines():
        return subprocess.run([sbx, "run", "--name", name], cwd=root, check=False).returncode

    kit = str(files("asgard").joinpath("assets", "sandbox_kit"))
    cmd = [sbx, "run", "--name", name, "--kit", kit]
    if not shared:
        cmd.append("--clone")
    cmd.extend(("asgard", root))
    sys.stderr.write(f"Starting Docker Sandbox {name} ({'shared workspace' if shared else 'private clone'}).\n")
    sys.stderr.write("Provider secrets stay host-side via sbx; configure the provider inside the sandbox.\n")
    return subprocess.run(cmd, cwd=root, check=False).returncode
