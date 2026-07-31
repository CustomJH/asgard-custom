"""격리 workspace의 단위 패치를 정본 트리로 합친다 — 범위 검증·겹침 판정·적용.

`WaveRunner.run`에서 들어낸 이유: 병렬 실행과 병합은 다른 질문이다. 앞은 "몇 개를 어떻게 동시에
돌리는가"이고, 뒤는 "**실제로 무엇을 썼는가**, 그게 배정 범위 안인가, 둘이 같은 파일을 건드렸는가"다.

이 모듈이 재는 것은 자기보고가 아니라 실측 delta 다. 단위가 "이 파일들을 고쳤다"고 말한 목록이
아니라 workspace가 캡처한 실제 경로로 판정한다 — 자기보고를 믿으면 범위를 벗어난 쓰기가
그대로 정본에 들어온다.

순서에 이유가 있다. 범위 위반을 **먼저** 걸러야 겹침 판정이 옳다: 범위를 벗어난 단위는 이미
탈락이므로, 그 단위가 만든 겹침 때문에 정상 단위까지 같이 떨어뜨리면 안 된다.
"""

from __future__ import annotations

import os


def merge_unit_patches(outs: list, workspaces: dict, writes_by_id: dict) -> tuple[list, dict, list]:
    """(적용된 결과, 단위별 실제 쓰기 경로, 실패 목록) — 실패는 (단위, 예외) 쌍이다."""
    from ..unit_workspace import WorkspaceError

    patches = {u["id"]: _capture(workspaces[u["id"]], writes_by_id[u["id"]], r) for u, r, _ in outs}
    failures: list[tuple[dict, Exception]] = []

    in_scope = []
    for out in outs:
        unit = out[0]
        outside = _outside_scope(unit, patches[unit["id"]].paths)
        if outside:
            failures.append((unit, WorkspaceError("scope violation: " + ", ".join(sorted(outside)))))
            continue
        in_scope.append(out)

    owners = _path_owners(in_scope, patches)
    applied, actual_writes = [], {}
    for out in in_scope:
        unit = out[0]
        overlap = sorted(path for path, holders in owners.items() if unit in holders and len(holders) > 1)
        if overlap:
            failures.append((unit, WorkspaceError("actual path overlap: " + ", ".join(overlap))))
            continue
        try:
            workspaces[unit["id"]].apply(patches[unit["id"]])
        except Exception as apply_error:
            failures.append((unit, apply_error))
            continue
        actual_writes[unit["id"]] = list(patches[unit["id"]].paths)
        applied.append(out)
    return (applied, actual_writes, failures)


def _capture(workspace, declared_writes: list[str], result):
    """디스패치 경유 쓰기와 세션이 보고한 쓰기를 합쳐 캡처 힌트로 준다 (중복 제거)."""
    extra = tuple(declared_writes) + tuple(path for path in result.writes if path not in declared_writes)
    return workspace.capture(extra_paths=extra)


def _outside_scope(unit: dict, written: list[str]) -> list[str]:
    declared = [os.path.normpath(str(path)).replace(os.sep, "/") for path in unit["files"]]
    return [path for path in written if not any(_covered(path, allowed) for allowed in declared)]


def _covered(path: str, allowed: str) -> bool:
    return path == allowed or path.startswith(allowed.rstrip("/") + "/")


def _path_owners(outs: list, patches: dict) -> dict[str, list[dict]]:
    owners: dict[str, list[dict]] = {}
    for out in outs:
        unit = out[0]
        for path in patches[unit["id"]].paths:
            owners.setdefault(path, []).append(unit)
    return owners
