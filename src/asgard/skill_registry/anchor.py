"""앵커 스킬 — 본문 대신 디스크 위치를 넘기는 스킬 트리를 프로젝트 옆에 푼다."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from .frontmatter import _read_text
from .manifest import _safe_tree, _skill_md

# 앵커 스킬이 프로젝트 옆에 풀리는 자리와, 어느 판본이 풀렸는지 적어 두는 표식.
_ANCHOR_DIR = (".asgard", "skills")
_ANCHOR_STAMP = ".asgard-skill.json"


def _anchor_target(root: str, name: str) -> str:
    return os.path.join(root, *_ANCHOR_DIR, name)


def _tree_files(root: str) -> set[str]:
    """Relative paths of a skill tree, minus what unpacking never copies (bytecode) or adds (stamp)."""
    found: set[str] = set()
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        for name in files:
            if name.endswith((".pyc", ".pyo")) or (current == root and name == _ANCHOR_STAMP):
                continue
            found.add(os.path.relpath(os.path.join(current, name), root))
    return found


def anchor_skill(root: str, plugin: dict, name: str) -> str:
    """Unpack one anchored skill tree beside the project and return the directory holding SKILL.md.

    Idempotent: a stamp records which plugin revision is on disk, so this is a no-op until an
    Asgard update changes the shipped tree.  A project that cannot be written to (read-only
    checkout, foreign cwd) falls back to the wheel copy — the caller only needs a real path.
    """
    source = os.path.join(plugin["root"], "skills", name)
    target = _anchor_target(root, name)
    marker = {"plugin": plugin["name"], "version": plugin["version"], "revision": plugin["revision"]}
    try:
        # 판본만 보면 손으로 지운 파일을 영원히 못 본다 — 이 트리를 가리켜 놓고 그 안이 비어 있으면
        # 스킬은 파이썬 역추적으로 죽는다. 배송한 파일이 전부 제자리인지까지 확인하고 통과시킨다
        # (실행 부산물 같은 여분은 눈감는다 — 엔진이 자기 자리에 .pyc를 남긴다).
        if json.loads(_read_text(os.path.join(target, _ANCHOR_STAMP))) == marker and not _tree_files(source).difference(
            _tree_files(target)
        ):
            return target
    except OSError, ValueError:
        pass
    home = os.path.dirname(target)
    try:
        # `_safe_tree` 는 ValueError 를 던지고 아래 `except OSError` 가 그걸 안 잡는다. 종전에는
        # 같은 조건을 `bundled_plugins()` 의 `except ValueError: continue` 가 삼켜 플러그인이
        # 조용히 빠졌는데(읽기 경로가 얕아지며 그 자리가 없어졌다), 여기서 새어 나가면 스킬
        # 해석 전체가 역추적으로 죽는다. 링크가 든 트리는 배송을 포기하고 휠 사본을 가리킨다 —
        # 아래 OSError 갈래와 같은 폴백이다.
        _safe_tree(source)
        os.makedirs(home, mode=0o700, exist_ok=True)
        # 이 트리는 파생물이다 — 셋업 전이라 `.asgard/.gitignore`가 아직 없어도 커밋에 안 섞이게.
        Path(os.path.join(home, ".gitignore")).write_text("*\n", encoding="utf-8")
        temp = tempfile.mkdtemp(prefix=f".{name}.", dir=home)
        try:
            staging = os.path.join(temp, name)
            shutil.copytree(source, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            Path(os.path.join(staging, _ANCHOR_STAMP)).write_text(
                json.dumps(marker, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            if os.path.lexists(target):
                shutil.rmtree(target, ignore_errors=True)
            os.replace(staging, target)
        finally:
            shutil.rmtree(temp, ignore_errors=True)
    except OSError, ValueError:
        return source
    return target


def _anchor_md(directory: str, name: str, frontmatter: str, lines: int) -> str:
    """Hand back where the skill lives instead of its body; the original file stays the only policy."""
    return (
        f"---{frontmatter}---\n\n"
        f"# {name} — read this skill from disk\n\n"
        "This skill ships its own runtime and resolves every path against the directory holding\n"
        "its `SKILL.md`, so it is delivered as a location rather than as text. Asgard unpacked it:\n\n"
        f"    SKILL_DIR={directory}\n\n"
        "Before doing anything else:\n\n"
        # 줄 수를 준다 — 이만한 파일은 어떤 리더든 한 번에 안 준다. 어디까지 읽었는지 알아야
        # 이어 읽고, 그래야 파일 뒤쪽의 계약(LAW·합성 규칙)이 통째로 빠지지 않는다.
        f"1. Read `$SKILL_DIR/SKILL.md` — all {lines} lines of it. If your reader returns only part\n"
        "   of the file, continue from where it stopped until you reach the last line. That file is\n"
        "   the canonical instruction set; this pointer carries no policy and overrides nothing.\n"
        "2. Use the `SKILL_DIR` above wherever the skill asks for the directory containing the\n"
        "   SKILL.md you just read. Do not search the filesystem for it.\n"
        "3. Then follow that file exactly, including any setup or preflight step it defines.\n"
    )


def _delivered_md(root: str, plugin: dict, name: str, *, unpack: bool = True) -> str:
    """The text a client receives for one file-backed skill: its body, or its location if anchored."""
    text = _skill_md(plugin, name)
    if name not in plugin.get("anchored", ()):
        return text
    directory = anchor_skill(root, plugin, name) if unpack else _anchor_target(root, name)
    frontmatter = text.split("---", 2)[1] if text.startswith("---") else "\n"
    return _anchor_md(directory, name, frontmatter, len(text.splitlines()))
