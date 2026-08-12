"""선언된 스킬 진입점 실행 — 셸 없이 파이썬 파일 하나만 돌린다."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .bundles import bundled_plugins, installed_plugins


def run_skill(root: str, name: str, args: list[str]) -> int:
    """Run one declared Python helper without a shell; instruction-only skills are rejected."""
    for plugin in [*bundled_plugins().values(), *installed_plugins().values()]:
        relative = plugin.get("entrypoints", {}).get(name)
        if not relative:
            continue
        skill_root = os.path.join(plugin["root"], "skills", name)
        entrypoint = os.path.realpath(os.path.join(skill_root, relative))
        try:
            Path(entrypoint).relative_to(Path(skill_root).resolve())
        except ValueError as exc:
            raise ValueError("plugin entrypoint escapes its skill directory") from exc
        if os.path.islink(entrypoint) or not os.path.isfile(entrypoint):
            raise ValueError("plugin entrypoint is missing or unsafe")
        # ponytail: Python-only entrypoints; add another declared runtime when a real bundled skill needs it.
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, entrypoint, *args], cwd=root, env=env, check=False).returncode
    raise ValueError(f"skill has no runnable entrypoint: {name}")
