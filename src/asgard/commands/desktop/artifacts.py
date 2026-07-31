"""산출물 — 끝난 작업이 남긴 파일을 읽고, 바뀐 곳을 보여 주고, 폴더를 연다.

여기서 지켜야 하는 것은 하나다: **경계 밖을 못 읽는다**. 작업의 자리 안으로 경로를 가두고
(`boundary.confine`), 그 자리가 등록된 곳인지도 확인한다 — 남의 프로젝트의 파일을 이 창의
산출물이라고 보여 주면 그것은 뷰어가 아니라 유출이다.
"""

from __future__ import annotations

import os
import subprocess
import sys

from .. import loopback
from . import state
from .boundary import _confine

_json_body = loopback.json_body
_ARTIFACT_CAP = state._ARTIFACT_CAP
_trim = state.trim


# ── 산출물 열기 ────────────────────────────────────────────────────────────────

_TEXT_HINT = frozenset({0x09, 0x0A, 0x0D})


def read_artifact(root: str, params: dict[str, list[str]]) -> tuple[int, str, bytes]:
    """변경 파일 한 장을 읽어 준다. 이진 파일은 내용 대신 그렇다고 말한다."""
    target = _confine(root, (params.get("path") or [""])[0])
    if target is None:
        return _json_body(404, {"error": "프로젝트 경계 안의 파일이 아닙니다"})
    try:
        size = os.path.getsize(target)
        with open(target, "rb") as handle:
            raw = handle.read(_ARTIFACT_CAP)
    except OSError as exc:
        return _json_body(400, {"error": f"읽을 수 없습니다: {type(exc).__name__}"})
    binary = any(byte == 0 or (byte < 0x20 and byte not in _TEXT_HINT) for byte in raw[:2048])
    return _json_body(
        200,
        {
            "path": os.path.relpath(target, os.path.realpath(root)),
            "size": size,
            "binary": binary,
            "truncated": size > len(raw),
            "text": "" if binary else raw.decode("utf-8", "replace"),
        },
    )


def read_diff(root: str, params: dict[str, list[str]]) -> tuple[int, str, bytes]:
    """그 파일의 git diff. 저장소가 아니거나 추적 밖이면 빈 diff 를 정직하게 돌려준다."""
    rel = (params.get("path") or [""])[0]
    target = _confine(root, rel)
    if target is None:
        return _json_body(404, {"error": "프로젝트 경계 안의 파일이 아닙니다"})
    rel_path = os.path.relpath(target, os.path.realpath(root))
    try:
        result = subprocess.run(
            ["git", "diff", "--no-color", "--", rel_path],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        return _json_body(200, {"path": rel_path, "diff": "", "note": f"git diff 실패: {type(exc).__name__}"})
    diff = _trim(result.stdout)
    note = ""
    if not diff:
        # 추적 밖 파일은 `git diff` 가 조용하다 — "변경 없음"이라고 말하면 새 파일을 없는 파일로 만든다
        note = "이 파일에는 커밋되지 않은 변경이 없습니다"
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain", "--", rel_path],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
            if status.returncode != 0:
                # Git 저장소가 아닌 자리(개인 작업 공간이 그렇다). "변경 없음"이라고 말하면
                # 비교할 것이 없다는 사실을 '비교했더니 같더라'로 바꿔 말하는 것이 된다.
                note = "이 작업 공간은 Git 저장소가 아닙니다 — 원본으로 보세요"
            elif status.stdout.startswith("??"):
                note = "아직 추적되지 않는 새 파일입니다 — 원본으로 보세요"
        except Exception:
            pass
    return _json_body(200, {"path": rel_path, "diff": diff, "note": note})


def reveal_path(root: str, payload: dict) -> tuple[int, str, bytes]:
    """파일이 있는 자리를 OS 탐색기로 연다. 경계 밖은 열지 않는다.

    작업 공간이 여럿이 되면서 "어느 폴더를 여는가"가 실제 물음이 됐다. 목록의 카드마다 붙은
    '폴더 열기'는 그 카드의 자리를 열어야 한다 — 여태는 무엇을 눌러도 창이 보던 곳이 열렸다.
    다만 열 수 있는 자리는 **아는 자리**로 묶는다(등록부 + 개인 작업 공간 + 지금 보는 곳):
    임의 경로를 받아 여는 창은 파일 탐색기가 되고, 그건 이 표면의 일이 아니다."""
    from .. import desktop_store

    wanted = str(payload.get("root") or "").strip()
    if wanted:
        target_root = os.path.abspath(os.path.expanduser(wanted))
        if target_root not in desktop_store.known_roots(root):
            return _json_body(403, {"error": "목록에 없는 폴더는 열지 않습니다"})
        root = target_root
    rel = str(payload.get("path") or "")
    target = _confine(root, rel) if rel else os.path.realpath(root)
    if target is None:
        return _json_body(404, {"error": "작업 공간 경계 안의 파일이 아닙니다"})
    try:
        if sys.platform == "darwin":
            command = ["open", "-R", target] if os.path.isfile(target) else ["open", target]
        elif os.name == "nt":
            command = ["explorer", f"/select,{target}"] if os.path.isfile(target) else ["explorer", target]
        else:
            command = ["xdg-open", target if os.path.isdir(target) else os.path.dirname(target)]
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    except OSError as exc:
        return _json_body(400, {"error": f"열 수 없습니다: {type(exc).__name__}"})
    return _json_body(200, {"revealed": os.path.relpath(target, os.path.realpath(root))})
