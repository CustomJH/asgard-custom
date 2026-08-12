"""설치된 learned 스킬의 보관·복원 — 파일 전이와 latch 전이를 짝지어 옮긴다."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import time

from .. import io_files
from ..skill_bank import APPROVAL_FILE
from .inbox import pending_list
from .store import ARCHIVED, PENDING, PROPOSED, _archive_slot, _evo_dir, _load_seen, _save_seen


def _relatch(root: str, name: str, cid: str, *, was: str, now: str) -> bool:
    """스킬 하나의 latch 를 `was` 에서 `now` 로 옮긴다 — 파일 전이와 짝을 맞추는 손.

    보관은 `approved → archived`(그 신호를 다시 캘 수 있게), 복원은 그 반대다. 복원 쪽 짝이
    없으면 되살린 스킬의 신호가 계속 열린 채라 다음 채굴이 이미 설치된 스킬의 초안을 또 만들고,
    그 초안은 승인하면 이름 충돌로 거절되므로 인박스에서 없어지지 않는다.

    영수증의 `candidate_id` 를 **먼저** 다 훑고, 못 찾았을 때만 이름으로 찾는다. 순서가 계약이다:
    한 번의 훑기에서 `id 일치 또는 이름 일치` 로 받으면, 이름이 같은 다른 신호가 앞에 있을 때
    그쪽이 먼저 걸려 영수증이 지목한 행은 그대로 남는다 (`approve` 는 이름을 검사하지만 신호는
    안 검사하므로 같은 이름이 두 신호에 적힐 수 있다). 재채굴로 `proposed` 가 된 행도 같은 표에서
    잡힌다."""
    rows = [
        (signal, row) for signal, row in _load_seen(root).items() if isinstance(row, dict) and row.get("status") == was
    ]
    hit = next((pair for pair in rows if cid and pair[1].get("id") == cid), None)
    hit = hit or next((pair for pair in rows if pair[1].get("name") == name), None)
    if not hit:
        return False
    signal, row = hit
    moved = {**row, "status": now, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    moved.pop("reopened", None)
    _save_seen(root, {signal: moved})
    return True


def _receipt_cid(skill_dir: str) -> str:
    return str((io_files.read_json(os.path.join(skill_dir, APPROVAL_FILE), {}) or {}).get("candidate_id") or "")


def _discard_reopened_draft(root: str, name: str, cid: str) -> bool:
    """복원한 스킬 때문에 떠 있던 초안을 인박스에서 뺀다 — 승인해도 이름 충돌로만 끝날 초안이다.

    보관과 복원 사이에 스캔이 한 번이라도 돌면 그 신호의 초안이 pending 에 서 있다. latch 만
    올리고 이 초안을 두면 넛지가 매번 "승인을 기다린다"고 말하는데, 승인하면 방금 되살린 스킬과
    이름이 부딪혀 거절된다. 초안은 `rejected/` 로 옮겨 그대로 남는다 — `reject` 를 안 쓰는 이유는
    그쪽이 latch 를 `rejected` 로 적어, 복원이 방금 올려 둔 `approved` 를 덮기 때문이다."""
    for meta in pending_list(root):
        if str(meta.get("id") or "") != cid and str(meta.get("name") or "") != name:
            continue
        src = _evo_dir(root, PENDING, str(meta.get("id") or ""))
        dst = _archive_slot(root, f"{meta.get('id')}-{time.strftime('%Y%m%d%H%M%S')}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with contextlib.suppress(OSError):
            shutil.move(src, dst)
            return True
    return False


def archive_skill(root: str, name: str) -> tuple[bool, str]:
    """보관 전이 — 삭제 없는 비활성화 (라우팅 스캔이 .archive를 건너뛴다). 복원 = 되돌리기.

    파일만 치우면 절반이다. 승인 latch 가 `approved` 로 남아 그 신호는 영영 다시 안 캐지고,
    배차 명단은 `approve` 가 구워 둔 대로라 내린 스킬 이름이 워커·프레이야·토르 파일에 남는다.
    셋을 한 걸음에 되돌린다."""
    src = os.path.join(root, ".asgard", "skills", name)
    if not os.path.isdir(src):
        return False, f"learned 스킬 없음: {name}"
    cid = _receipt_cid(src)
    dst = os.path.join(root, ".asgard", "skills", ".archive", f"{name}-{time.strftime('%Y%m%d%H%M%S')}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    reopened = _relatch(root, name, cid, was="approved", now=ARCHIVED)
    _redraw_roster(root)
    tail = " 같은 신호는 다시 채굴된다." if reopened else ""
    return True, f"보관됨: {dst} (복원: asgard evolve restore {name}).{tail}"


def _redraw_roster(root: str) -> None:
    """배차 명단 재렌더 — 클라이언트 서브에이전트는 스킬 목록을 자기 파일에서 읽는다.

    실패는 삼킨다: 명단이 낡는 것과 보관·복원 자체가 실패하는 것 중에는 앞이 낫다
    (`approve` 가 설치 뒤에 거는 것과 같은 판단)."""
    with contextlib.suppress(Exception):
        from ..commands.setup import refresh_role_agents

        refresh_role_agents(root)


def restore_skill(root: str, name: str) -> tuple[bool, str]:
    """보관 해제 — 최신 아카이브 스냅샷을 활성 위치로 복귀 (충돌 검증 포함).

    latch 도 `approved` 로 되돌린다. 안 되돌리면 신호가 계속 채굴 가능한 채라 다음 스캔이
    이미 서 있는 스킬의 초안을 또 뜨고, 승인하면 이름 충돌로 거절되는 후보가 인박스에 남는다."""
    adir = os.path.join(root, ".asgard", "skills", ".archive")
    snaps = sorted(
        d for d in (os.listdir(adir) if os.path.isdir(adir) else []) if re.fullmatch(rf"{re.escape(name)}-\d{{14}}", d)
    )
    if not snaps:
        return False, f"아카이브에 없음: {name}"
    dst = os.path.join(root, ".asgard", "skills", name)
    if os.path.isdir(dst):
        return False, f"활성 스킬 '{name}'이 이미 있다 — 먼저 archive 하거나 이름을 정리하라."
    if name in _bundled_names():
        return False, f"이름 충돌: 번들 스킬 '{name}'과 겹친다 (아카이브 중 번들이 추가됨)."
    shutil.move(os.path.join(adir, snaps[-1]), dst)
    cid = _receipt_cid(dst)
    # 보관이 latch 를 어디에 놓았든(그대로 `archived`, 또는 재채굴로 `proposed`) 한 번에 올린다.
    for was in (ARCHIVED, PROPOSED):
        if _relatch(root, name, cid, was=was, now="approved"):
            break
    _discard_reopened_draft(root, name, cid)
    _redraw_roster(root)
    return True, f"복원됨: .asgard/skills/{name}/ — 다음 디스패치부터 다시 라우팅 (최신 스냅샷 {snaps[-1]})"


def _bundled_names() -> frozenset[str]:
    """번들 스킬 이름 — 충돌 방지용 (lazy import — 상수 본문이 크다)."""
    try:
        from ..templates.bragi import BRAGI_SKILLS
        from ..templates.eitri import EITRI_SKILLS
        from ..templates.freyja import FREYJA_SKILLS
        from ..templates.lagom import LAGOM_SKILLS
        from ..templates.mimir import MIMIR_SKILLS
        from ..templates.thor import THOR_SKILLS
        from ..templates.worker import WORKER_SKILLS

        return frozenset(
            n
            for n, _ in [
                *FREYJA_SKILLS,
                *THOR_SKILLS,
                *EITRI_SKILLS,
                *MIMIR_SKILLS,
                *WORKER_SKILLS,
                *LAGOM_SKILLS,
                *BRAGI_SKILLS,
            ]
        )
    except Exception:
        return frozenset()
