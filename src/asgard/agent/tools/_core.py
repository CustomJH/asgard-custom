"""도구의 공용 바닥 — 오류 하나, 상한값, 뿌리 밖 경로 차단, 출력 자르기."""

from __future__ import annotations

import os

_TIMEOUT = 120
_MAX_OUT = 30_000  # chars — 초과분은 절단 표기 (조용한 절단 금지)
_MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_FETCH_BYTES = 5 * 1024 * 1024


class ToolError(Exception):
    """핸들러 실패 — 메시지가 그대로 is_error tool_result로 나간다 (모델이 복구하게)."""


def _confine(root: str, path: str) -> str:
    """모델이 준 경로를 작업 뿌리 안으로 격리. 탈출(.., 절대경로 밖, 심링크)은 거부.

    뿌리는 하나가 아니다 — 선언된 추가 뿌리(`hooks.readonly_guard.work_roots`)까지가 경계이고,
    그 판정은 훅과 같은 함수를 쓴다. 네이티브만 다른 규칙을 들면 같은 작업이 모드에 따라 되고
    안 된다."""
    from ...hooks.readonly_guard import work_roots

    p = os.path.realpath(os.path.join(root, path) if not os.path.isabs(path) else path)
    for base in work_roots(root):
        if p == base or p.startswith(base + os.sep):
            return p
    raise ToolError(f"경로가 작업 뿌리를 벗어납니다: {path} (Canon — 범위 존중)")


def _cap(s: str) -> str:
    return s if len(s) <= _MAX_OUT else s[:_MAX_OUT] + f"\n[... {len(s) - _MAX_OUT} chars 절단]"


def _dedup_log(s: str) -> str:
    """성공한 셸 로그의 연속 중복만 접는다. 오류 출력과 서로 떨어진 중복은 원문 보존."""
    if len(s) < 500:
        return s
    out: list[str] = []
    previous: str | None = None
    repeated = 0
    for line in s.splitlines():
        if line == previous:
            repeated += 1
            continue
        if repeated:
            out.append(f"[... {repeated} duplicate lines]")
        out.append(line)
        previous, repeated = line, 0
    if repeated:
        out.append(f"[... {repeated} duplicate lines]")
    compact = "\n".join(out)
    return compact if len(compact) < len(s) else s
