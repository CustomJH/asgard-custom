"""네이티브 루프 툴셋 (CUS-137) — Anthropic-defined bash + text_editor 계약 구현.

Anthropic-defined 툴(스키마리스)을 쓰는 이유: 모델이 이 계약으로 훈련돼 있어 프롬프트 비용 없이
정확히 동작한다. 핸들러 계약(레퍼런스 문서 그대로):
  bash        {command} | {restart: true}
  text_editor view/create/str_replace/insert — str_replace 는 정확히 1회 매치만 허용

보안 경계 (여기서만 지킨다 — 모델 출력은 전부 불신):
  * 모든 파일 경로는 프로젝트 루트 안으로 격리 (resolve 후 is_relative_to)
  * bash 는 git-guard 훅을 배포 형태(subprocess stdin 계약)로 통과해야 실행 — 로직 중복 금지
  * 타임아웃·출력 상한 — 무한 명령/출력 폭주가 루프를 인질로 잡지 않게
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

BASH_TOOL = {"type": "bash_20250124", "name": "bash"}
EDITOR_TOOL = {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"}

_TIMEOUT = 120
_MAX_OUT = 30_000  # chars — 초과분은 절단 표기 (조용한 절단 금지)


class ToolError(Exception):
    """핸들러 실패 — 메시지가 그대로 is_error tool_result 로 나간다 (모델이 복구하게)."""


def _confine(root: str, path: str) -> str:
    """모델이 준 경로를 루트 안으로 격리. 탈출(.., 절대경로 밖, 심링크)은 거부."""
    p = os.path.realpath(os.path.join(root, path) if not os.path.isabs(path) else path)
    if p != os.path.realpath(root) and not p.startswith(os.path.realpath(root) + os.sep):
        raise ToolError(f"경로가 프로젝트 루트를 벗어납니다: {path} (Canon — 범위 존중)")
    return p


def _git_guard(root: str, command: str) -> str | None:
    """git-guard 훅을 배포 형태로 통과. 차단이면 사유 문자열, 통과면 None. fail-open (훅 오류 = 통과)."""
    try:
        p = subprocess.run(
            [sys.executable, "-m", "asgard.hooks.git_guard"],
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True,
            text=True,
            timeout=10,
            cwd=root,
        )
        if p.returncode != 0:
            return (p.stderr or p.stdout or "git-guard 차단").strip()[:500]
    except Exception:
        pass
    return None


def _cap(s: str) -> str:
    return s if len(s) <= _MAX_OUT else s[:_MAX_OUT] + f"\n[... {len(s) - _MAX_OUT} chars 절단]"


def run_bash(root: str, tool_input: dict) -> tuple[str, int | None]:
    """(output, exit_code). exit_code 는 원장 commands 증거용."""
    if tool_input.get("restart"):
        return "shell restarted (stateless — cwd는 프로젝트 루트 고정)", 0
    cmd = str(tool_input.get("command") or "")
    if not cmd.strip():
        raise ToolError("빈 명령")
    blocked = _git_guard(root, cmd)
    if blocked:
        raise ToolError(blocked)
    try:
        p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True, timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ToolError(f"타임아웃 ({_TIMEOUT}s) — 장기 실행은 분할하거나 백그라운드로")
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    return _cap(out.strip() or f"(no output, exit {p.returncode})"), p.returncode


def run_editor(root: str, tool_input: dict, writes: list[str]) -> str:
    """text_editor 계약. write 계열은 writes 에 상대경로 기록 — 게이트의 write-sentinel 대응."""
    cmd = tool_input.get("command")
    path = _confine(root, str(tool_input.get("path") or ""))
    rel = os.path.relpath(path, os.path.realpath(root))  # path 는 realpath — 기준도 풀어야 함 (macOS /var 심링크)

    if cmd == "view":
        if os.path.isdir(path):
            return _cap("\n".join(sorted(os.listdir(path))[:500]))
        try:
            lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
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
        open(path, "w", encoding="utf-8").write(tool_input.get("file_text") or "")
        writes.append(rel)
        return f"created {rel}"

    if cmd == "str_replace":
        old = tool_input.get("old_str") or ""
        try:
            text = open(path, encoding="utf-8").read()
        except FileNotFoundError:
            raise ToolError(f"파일 없음: {rel}")
        n = text.count(old)
        if n != 1:
            raise ToolError(f"old_str 매치 {n}회 — 정확히 1회여야 합니다 (더 좁혀서 재시도)")
        open(path, "w", encoding="utf-8").write(text.replace(old, tool_input.get("new_str") or "", 1))
        writes.append(rel)
        return f"edited {rel}"

    if cmd == "insert":
        try:
            lines = open(path, encoding="utf-8").read().splitlines(keepends=True)
        except FileNotFoundError:
            raise ToolError(f"파일 없음: {rel}")
        at = int(tool_input.get("insert_line") or 0)
        if not 0 <= at <= len(lines):
            raise ToolError(f"insert_line {at} 범위 밖 (0..{len(lines)})")
        ins = tool_input.get("insert_text") or ""
        if not ins.endswith("\n"):
            ins += "\n"
        lines.insert(at, ins)
        open(path, "w", encoding="utf-8").write("".join(lines))
        writes.append(rel)
        return f"inserted into {rel}"

    raise ToolError(f"지원하지 않는 command: {cmd}")
