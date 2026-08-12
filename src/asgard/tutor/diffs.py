"""git 에서 읽어 오는 재료 — base 시점의 본문과 경로별 행 통계.

여기서만 `git` 을 부른다. 판정하는 쪽이 직접 부르면 같은 diff 를 두 벌로 읽게 되고, 두 벌은
반드시 갈라진다.
"""

from __future__ import annotations

import subprocess


def _at_base(root: str, rel: str, base: str) -> str | None:
    """base 시점의 본문. 새 파일이면 None."""
    try:
        proc = subprocess.run(
            ["git", "show", f"{base}:{rel}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
    except OSError, subprocess.SubprocessError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _numstat(root: str, base: str) -> dict[str, tuple[int, int]]:
    """경로 → (추가행, 삭제행). 바이너리(`-`)는 0 — 못 센 것을 0이라 부르되 인벤토리에는 남긴다."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--numstat", base],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
    except OSError, subprocess.SubprocessError:
        return {}
    out: dict[str, tuple[int, int]] = {}
    for line in proc.stdout.splitlines() if proc.returncode == 0 else []:
        bits = line.split("\t")
        if len(bits) == 3:
            out[bits[2].strip()] = (_int(bits[0]), _int(bits[1]))
    return out


def _int(raw: str) -> int:
    return int(raw) if raw.strip().isdigit() else 0
