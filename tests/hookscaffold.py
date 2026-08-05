"""시험이 훅을 배포 배치 그대로 깔게 하는 한 줄.

훅은 `.claude/hooks/`(또는 `.cursor/`·`.codex/`)로 복사돼 그 폴더에서 subprocess 로 돈다. 그
폴더에는 훅 파일만 있는 게 아니라 공용 라이브러리(`asgard_hooklib/`)가 함께 있고, 그 인접이 곧
임포트 경로다 — 스크립트로 실행된 훅은 자기 폴더가 `sys.path[0]` 이다.

시험이 훅 파일 하나만 복사하면 그 배치는 배포본이 아니다. 여기 한 자리를 두는 이유가 그것이다:
배포 표에 파일이 하나 늘 때 시험 여섯이 각자 옛 배치를 계속 증명하지 않도록.
"""

from __future__ import annotations

import os
import stat
import sys
import time

from asgard.hooks import library_files

SRC = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "src"))


def deploy_library(hooks_dir: str) -> None:
    """`hooks_dir` 에 공용 라이브러리를 깐다 — setup 이 쓰는 목록 그대로."""
    for rel, body in library_files():
        path = os.path.join(hooks_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)


def deploy_cli(bin_dir: str) -> str:
    """PATH 에 얹을 `asgard` 를 깐다 — 이 저장소의 CLI 를 그대로 부르는 얇은 스크립트.

    훅은 배차 장부를 임포트가 아니라 **프로세스**로 적는다 (`asgard_hooklib.siege`). 그 이유가
    곧 이 함수가 필요한 이유다: 배포 인터프리터에 `asgard` 가 없어서 임포트가 늘 실패했고,
    시험은 `PYTHONPATH=src` 를 얹은 덕에 그 실패를 못 봤다. 이제 시험도 실사와 같은 문으로
    간다 — 훅이 PATH 의 `asgard` 를 찾고, 그 `asgard` 가 이 저장소의 코드다.

    Returns:
        깔린 실행 파일의 경로.
    """
    os.makedirs(bin_dir, exist_ok=True)
    path = os.path.join(bin_dir, "asgard")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            f'#!/bin/sh\nPYTHONPATH="{SRC}" exec "{sys.executable}" -m asgard "$@"\n'  # noqa: S608 — 셸 아님
        )
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def until(predicate, timeout: float = 30.0, step: float = 0.1) -> bool:
    """`predicate()` 가 참이 될 때까지 기다린다 — 장부 기록은 떼어 낸 프로세스가 적는다.

    훅은 답을 안 기다리고 돌아간다(장부는 파생이고 디스패치는 사람이 기다리는 자리다). 그래서
    시험도 곧바로 읽으면 아직 없는 것을 못 찾았다고 말한다. 상한을 넉넉히 두는 이유는 이
    프로세스가 CLI 기동 전체를 치르기 때문이다.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()
