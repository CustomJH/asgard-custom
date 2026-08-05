"""도구 — 파일 편집. 패치 형식을 읽어 훅 판정을 거친 뒤 적용한다."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from ._core import ToolError, _cap, _confine
from .guards import _BOUNDARY_FILES, _CONTROL_PATHS, _hook_guard


def _parse_patch(patch_text: str) -> list[dict]:
    if len(patch_text) > 200_000:
        raise ToolError("패치가 200,000자 안전 상한을 초과합니다")
    lines = patch_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    end_index = next((index for index, line in enumerate(lines) if line.strip() == "*** End Patch"), None)
    if not lines or lines[0].strip() != "*** Begin Patch" or end_index is None:
        raise ToolError("*** Begin Patch / *** End Patch 형식이 필요합니다")
    operations: list[dict] = []
    current: dict | None = None
    hunk: list[tuple[str, str]] | None = None
    for line in lines[1:end_index]:
        header = re.match(r"\*\*\* (Add|Update|Delete) File: (.+)$", line)
        if header:
            current = {"action": header.group(1).lower(), "path": header.group(2).strip(), "hunks": []}
            operations.append(current)
            hunk = None
            continue
        if line.startswith("*** Move to: "):
            if current is None or current["action"] != "update":
                raise ToolError("Move to는 Update File 바로 뒤에서만 사용할 수 있습니다")
            current["move_to"] = line.removeprefix("*** Move to: ").strip()
            continue
        if line.startswith("@@"):
            if current is None or current["action"] != "update":
                raise ToolError("업데이트 hunk 앞에 Update File이 필요합니다")
            hunk = []
            current["hunks"].append(hunk)
            continue
        if current is None:
            if line.strip():
                raise ToolError(f"파일 작업 밖의 패치 내용: {line[:80]}")
            continue
        if current["action"] == "add":
            if not line.startswith("+"):
                raise ToolError(f"Add File 본문 줄은 +로 시작해야 합니다: {current['path']}")
            current.setdefault("content", []).append(line[1:])
        elif current["action"] == "update":
            if hunk is None:
                raise ToolError(f"Update File에 @@ hunk가 필요합니다: {current['path']}")
            if not line or line[0] not in " +-":
                raise ToolError(f"hunk 줄은 공백, +, - 중 하나로 시작해야 합니다: {current['path']}")
            hunk.append((line[0], line[1:]))
        elif line.strip():
            raise ToolError(f"Delete File 뒤에는 본문을 둘 수 없습니다: {current['path']}")
    if not operations or len(operations) > 50:
        raise ToolError("패치에는 1..50개 파일 작업이 필요합니다")
    return operations


def _patch_path(root: str, path: str) -> tuple[str, str]:
    absolute = _confine(root, path)
    relative = os.path.relpath(absolute, os.path.realpath(root))
    normalized = relative.replace(os.sep, "/")
    if (
        relative in _CONTROL_PATHS
        or relative.startswith(tuple(marker + os.sep for marker in _CONTROL_PATHS))
        or normalized in _BOUNDARY_FILES
    ):
        raise ToolError("Asgard 제어 경로는 모델이 변경할 수 없음")
    return absolute, relative


def _apply_hunks(path: str, content: str, hunks: list[list[tuple[str, str]]]) -> str:
    source = content.splitlines()
    trailing_newline = content.endswith("\n")
    cursor = 0
    for hunk in hunks:
        old = [text for prefix, text in hunk if prefix != "+"]
        new = [text for prefix, text in hunk if prefix != "-"]
        if not old:
            raise ToolError(f"문맥 없는 추가 hunk는 거부됩니다: {path}")
        matches = [
            index for index in range(cursor, len(source) - len(old) + 1) if source[index : index + len(old)] == old
        ]
        if not matches:
            raise ToolError(f"패치 문맥이 현재 파일과 일치하지 않습니다: {path}")
        at = matches[0]
        source[at : at + len(old)] = new
        cursor = at + len(new)
    result = "\n".join(source)
    return result + ("\n" if trailing_newline and source else "")


def run_apply_patch(root: str, tool_input: dict, writes: list[str]) -> str:
    operations = _parse_patch(str(tool_input.get("patch_text") or ""))
    state: dict[str, str | None] = {}
    paths: dict[str, tuple[str, str]] = {}

    def load(path: str) -> tuple[str, str, str | None]:
        absolute, relative = _patch_path(root, path)
        paths[absolute] = (absolute, relative)
        if absolute not in state:
            try:
                state[absolute] = Path(absolute).read_text(encoding="utf-8")
            except FileNotFoundError:
                state[absolute] = None
            except UnicodeDecodeError as exc:
                raise ToolError(f"UTF-8 텍스트 파일만 패치할 수 있습니다: {relative}") from exc
        return absolute, relative, state[absolute]

    for operation in operations:
        absolute, relative, current = load(operation["path"])
        action = operation["action"]
        if action == "add":
            if current is not None:
                raise ToolError(f"Add File 대상이 이미 존재합니다: {relative}")
            state[absolute] = "\n".join(operation.get("content", [])) + "\n"
        elif action == "delete":
            if current is None:
                raise ToolError(f"Delete File 대상이 없습니다: {relative}")
            state[absolute] = None
        else:
            if current is None:
                raise ToolError(f"Update File 대상이 없습니다: {relative}")
            updated = _apply_hunks(relative, current, operation["hunks"])
            move_to = operation.get("move_to")
            if move_to:
                destination, destination_rel, destination_content = load(move_to)
                if destination_content is not None:
                    raise ToolError(f"Move 대상이 이미 존재합니다: {destination_rel}")
                state[absolute] = None
                state[destination] = updated
            else:
                state[absolute] = updated

    originals = {path: (Path(path).read_bytes() if os.path.exists(path) else None) for path in state}
    for path, content in state.items():
        if content is None:
            continue
        relative = paths[path][1]
        blocked = _hook_guard(root, "asgard.hooks.secret_guard", {"file_path": relative, "content": content})
        if blocked:
            raise ToolError(blocked)
    try:
        for path, content in state.items():
            if content is None:
                continue
            os.makedirs(os.path.dirname(path) or root, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".asgard-patch-", dir=os.path.dirname(path) or root)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
                    output.write(content)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        for path, content in state.items():
            if content is None and os.path.exists(path):
                os.unlink(path)
    except Exception:
        for path, content in originals.items():
            if content is None:
                if os.path.exists(path):
                    os.unlink(path)
            else:
                os.makedirs(os.path.dirname(path) or root, exist_ok=True)
                Path(path).write_bytes(content)
        raise
    changed = [paths[path][1] for path in state]
    writes.extend(changed)
    return "applied patch:\n" + "\n".join(f"- {path}" for path in changed)


def run_editor(root: str, tool_input: dict, writes: list[str]) -> str:
    """text_editor 계약. write 계열은 writes에 상대경로 기록 — 게이트의 write-sentinel 대응."""
    cmd = tool_input.get("command")
    path = _confine(root, str(tool_input.get("path") or ""))
    rel = os.path.relpath(path, os.path.realpath(root))  # path는 realpath — 기준도 풀어야 함 (macOS /var 심링크)

    if cmd in ("create", "str_replace", "insert"):
        if rel == ".asgard" or rel.startswith(".asgard/") or rel == ".claude" or rel.startswith(".claude/"):
            raise ToolError("Asgard 제어 경로는 모델이 변경할 수 없음")
        # secret-guard 훅 (Canon Law 4) — mode B와 동일 차단 지점(파일 쓰기). shell 우회는
        # 훅 헤더에 문서화된 알려진 구멍 (양 모드 공통).
        body = str(tool_input.get("file_text") or tool_input.get("new_str") or tool_input.get("insert_text") or "")
        blocked = _hook_guard(root, "asgard.hooks.secret_guard", {"file_path": rel, "content": body})
        if blocked:
            raise ToolError(blocked)

    if cmd == "view":
        if os.path.isdir(path):
            return _cap("\n".join(sorted(os.listdir(path))[:500]))
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except FileNotFoundError:
            raise ToolError(f"파일 없음: {rel}")
        rng = tool_input.get("view_range")
        if rng and len(rng) == 2:
            lo = max(1, int(rng[0]))
            hi = len(lines) if int(rng[1]) == -1 else int(rng[1])
            lines = lines[lo - 1 : hi]
            start = lo
        else:
            start = 1
        return _cap("\n".join(f"{i + start:6}\t{ln}" for i, ln in enumerate(lines)))

    if cmd == "create":
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        if os.path.exists(path):  # 계약: 기존 파일은 백업 후 덮어쓴다
            os.replace(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(tool_input.get("file_text") or "")
        writes.append(rel)
        return f"created {rel}"

    if cmd == "str_replace":
        old = tool_input.get("old_str") or ""
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except FileNotFoundError:
            raise ToolError(f"파일 없음: {rel}")
        n = text.count(old)
        if n != 1:
            raise ToolError(f"old_str 매치 {n}회 — 정확히 1회여야 합니다 (더 좁혀서 재시도)")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text.replace(old, tool_input.get("new_str") or "", 1))
        writes.append(rel)
        return f"edited {rel}"

    if cmd == "insert":
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines(keepends=True)
        except FileNotFoundError:
            raise ToolError(f"파일 없음: {rel}")
        at = int(tool_input.get("insert_line") or 0)
        if not 0 <= at <= len(lines):
            raise ToolError(f"insert_line {at} 범위 밖 (0..{len(lines)})")
        ins = tool_input.get("insert_text") or ""
        if not ins.endswith("\n"):
            ins += "\n"
        lines.insert(at, ins)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("".join(lines))
        writes.append(rel)
        return f"inserted into {rel}"

    raise ToolError(f"지원하지 않는 command: {cmd}")
