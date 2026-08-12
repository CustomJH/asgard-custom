"""플러그인 출처 — 휠에 동봉된 번들, 사람이 설치한 제3자 묶음, 그 설치."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from ..settings import global_dir
from .builtin import _builtin_plugins
from .manifest import _validate_manifest

# 번들 자원은 이 패키지 밖 `asgard/assets` 에 있다 — 패키지가 한 단 깊어졌으므로 파일이
# 아니라 그 위 디렉터리(`asgard/`)를 기준으로 푼다.
_BUNDLED_PLUGINS_DIR = Path(__file__).parent.parent / "assets" / "skill_plugins"


def _plugins_dir() -> str:
    return os.path.join(global_dir(), "plugins")


def bundled_plugins() -> dict[str, dict]:
    """휠에 동봉된 플러그인 목록 — 자원 트리는 얕게 본다 (`_validate_manifest` 의 deep 인자).

    호출당 값은 47.2ms 에서 2.3ms 로 내려갔다 (26-08-04 실측). 프로세스 캐시는 안 둔다:
    남는 값이 호출 몇 번어치뿐인데, 반환값이 `_BUNDLED_PLUGINS_DIR` 과 디스크 내용에 걸려
    있어 그 둘을 바꿔 끼우는 자리(테스트·앵커 복구)마다 무를 자리를 만들어야 한다."""
    found: dict[str, dict] = {}
    if not _BUNDLED_PLUGINS_DIR.is_dir():
        return found
    for child in sorted(_BUNDLED_PLUGINS_DIR.iterdir()):
        if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
            continue
        try:
            manifest = _validate_manifest(str(child), deep=False)
        except ValueError:
            continue
        if manifest["name"] == child.name:
            found[child.name] = {**manifest, "root": str(child)}
    return found


def installed_plugins() -> dict[str, dict]:
    """사람이 설치한 제3자 플러그인 — 자원 트리는 깊게 본다 (신뢰 경계)."""
    found: dict[str, dict] = {}
    base = _plugins_dir()
    if not os.path.isdir(base):
        return found
    for name in sorted(os.listdir(base)):
        root = os.path.join(base, name)
        if name.startswith(".") or os.path.islink(root) or not os.path.isdir(root):
            continue
        try:
            manifest = _validate_manifest(root)
        except ValueError:
            continue
        if manifest["name"] == name:
            found[name] = {**manifest, "root": root}
    return found


def install_plugin(source: str) -> dict:
    """Install one local skill bundle; only declared Python skill entrypoints are executable."""
    source = os.path.abspath(source)
    if os.path.islink(source) or not os.path.isdir(source):
        raise ValueError("plugin source must be a regular directory")
    manifest = _validate_manifest(source)
    builtins = _builtin_plugins()
    if manifest["name"] in builtins or manifest["name"] in bundled_plugins():
        raise ValueError(f"plugin name collides with built-in: {manifest['name']}")
    builtin_skills = {name for plugin in builtins.values() for name, _ in plugin["skills"]} | {
        skill for plugin in bundled_plugins().values() for skill in plugin["skills"]
    }
    existing_skills = {
        skill
        for plugin in installed_plugins().values()
        for skill in plugin["skills"]
        if plugin["name"] != manifest["name"]
    }
    collisions = builtin_skills.intersection(manifest["skills"]) | existing_skills.intersection(manifest["skills"])
    if collisions:
        raise ValueError("skill name collision: " + ", ".join(sorted(collisions)))
    base = _plugins_dir()
    destination = os.path.join(base, manifest["name"])
    if os.path.lexists(destination):
        raise ValueError(f"plugin already installed: {manifest['name']}")
    os.makedirs(base, mode=0o700, exist_ok=True)
    temp = tempfile.mkdtemp(prefix=f".{manifest['name']}.", dir=base)
    try:
        Path(os.path.join(temp, "plugin.json")).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for skill in manifest["skills"]:
            shutil.copytree(os.path.join(source, "skills", skill), os.path.join(temp, "skills", skill))
        for name in ("LICENSE", "LICENSE.md", "NOTICE", "NOTICE.md"):
            path = os.path.join(source, name)
            if os.path.isfile(path):
                shutil.copy2(path, os.path.join(temp, name))
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            shutil.rmtree(temp)
    return manifest


def plugins() -> list[dict]:
    rows = [
        {
            "name": name,
            "version": "bundled",
            "description": plugin["description"],
            "skills": [skill for skill, _ in plugin["skills"]],
            "origin": "bundled",
        }
        for name, plugin in _builtin_plugins().items()
    ]
    rows.extend({**manifest, "origin": "bundled"} for manifest in bundled_plugins().values())
    rows.extend({**manifest, "origin": "installed"} for manifest in installed_plugins().values())
    return rows
