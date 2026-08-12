"""초안에 대한 처분 — 승인(설치), 거부(latch), 초기화(인박스 비우기)."""

from __future__ import annotations

import os
import shutil
import time

from .. import io_files
from ..skill_bank import APPROVAL_FILE, SKILL_FILE, approval_receipt, learned_skills, parse_skill_md
from .drafts import weak_triggers
from .inbox import pending_list, show
from .skills import _redraw_roster
from .store import (
    ARCHIVED,
    PENDING,
    PROPOSED,
    REJECTED,
    _archive_slot,
    _clear_nudge_latch,
    _evo_dir,
    _load_seen,
    _save_seen,
)


def approve(root: str, cid: str, *, auto: bool = False) -> tuple[bool, str]:
    """승인 — dry-run 검증 통과 시 learned 스킬 뱅크로 설치. (성공, 메시지) 반환.

    이곳이 pending → 활성의 유일한 관문이다. `auto=True` 는 그 관문을 여는 손이 사람이
    아니라 정책이었다는 표식일 뿐이고(`autonomy_mode`), 아래 검사는 한 자리도 안 건너뛴다.
    누가 눌렀는지는 영수증과 seen 기록에 남아 나중에 되짚을 수 있다."""
    text = show(root, cid)
    if text is None:
        return False, f"후보 없음: {cid} (asgard evolve list로 확인)"
    parsed = parse_skill_md(text)
    if not parsed:
        return False, "frontmatter 불량 — name/triggers 필수. pending SKILL.md를 고친 뒤 재시도."
    meta, _body = parsed
    name = str(meta["name"])
    loose = weak_triggers(meta["triggers"])
    if loose:
        return False, (
            f"이 트리거로는 재발을 못 알아본다: {', '.join(loose)} — 무엇에나 걸리거나 아무것에도 안 "
            "걸린다. 코드가 부르는 이름으로 바꿔라 (파일 이름·함수 이름·실패 서명). 짧은 이름은 자리를 "
            "붙여 늘린다 (`k6` → `asgard-k6`)."
        )
    if name in learned_skills(root):
        return False, f"이름 충돌: learned 스킬 '{name}'이 이미 있다."
    # 번들 이름은 파사드 속성으로 부른다 — 분해 전 한 모듈이던 시절 이 이름은 `evolution`
    # 네임스페이스의 전역이었고, `tests/test_evolution.py` 가 `mock.patch.object(evolution,
    # "_bundled_names", ...)` 로 그것을 갈아 끼운다. 모듈 최상단에서 묶어 두면 그 대역이 여기
    # 안 닿아 번들 충돌 검사를 시험이 못 재현한다.
    from . import _bundled_names

    if name in _bundled_names():
        return False, f"이름 충돌: 번들 스킬 '{name}'과 겹친다."
    dst = os.path.join(root, ".asgard", "skills", name)
    os.makedirs(dst, exist_ok=True)
    io_files.write_text(os.path.join(dst, SKILL_FILE), text)
    approval = approval_receipt(
        root,
        name,
        text,
        create_key=True,
        approved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        candidate_id=cid,
        approved_by="policy" if auto else "user",
    )
    io_files.write_json(os.path.join(dst, APPROVAL_FILE), approval, indent=None, sort_keys=True)
    src = _evo_dir(root, PENDING, cid)
    cmeta = io_files.read_json(os.path.join(src, "meta.json"), {"id": cid, "signal": cid})
    seen = _load_seen(root)
    seen[str(cmeta.get("signal", cid))] = {
        "status": "approved",
        "id": cid,
        "name": name,
        "by": "policy" if auto else "user",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_seen(root, seen)
    shutil.rmtree(src, ignore_errors=True)
    # 명단은 설치 시점에 구워지므로 여기서 다시 그리지 않으면 방금 깐 스킬이 다음 `asgard sync`
    # 까지 배차에 안 보인다 (26-08-12 실측: 워커 둘 다 이 스킬을 못 받았고 명단에도 없었다).
    _redraw_roster(root)
    return True, f"설치됨: .asgard/skills/{name}/ — 다음 디스패치부터 자동 라우팅 (재시작 불필요)"


def reject(root: str, cid: str, reason: str = "") -> tuple[bool, str]:
    """거부 — latch 기록 (동일 신호 재제안 금지) + 후보는 rejected/ 로 보존 (감사 가능)."""
    src = _evo_dir(root, PENDING, cid)
    if not os.path.isdir(src):
        return False, f"후보 없음: {cid}"
    cmeta = io_files.read_json(os.path.join(src, "meta.json"), {"signal": cid})
    seen = _load_seen(root)
    seen[str(cmeta.get("signal", cid))] = {
        "status": "rejected",
        "id": cid,
        "reason": reason[:300],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_seen(root, seen)
    dst = _evo_dir(root, REJECTED, cid)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.move(src, dst)
    return True, f"거부됨 — 같은 신호는 다시 제안하지 않는다{' (' + reason[:80] + ')' if reason else ''}"


def reset(root: str) -> tuple[int, int, list[str]]:
    """인박스를 비우고 다시 채굴할 수 있게 연다. 반환 = (치운 초안 수, 푼 latch 수, 초안 이름들).

    왜 필요한가. 초안의 모양은 생성기가 정하는데 생성기는 고쳐진다 — 26-08-11 에 트리거 규칙이
    산문 낱말에서 이름 축으로 바뀌자, 그 전에 뜬 초안 다섯이 전부 승인 문턱에 걸린 채 인박스에
    남았다. 그것들은 고칠 값이 있는 문서가 아니라 옛 규칙의 산물이고, 같은 퀘스트 로그에서 새
    규칙으로 다시 뜨는 편이 낫다. 그런데 `seen` latch 가 "이 신호는 이미 제안했다"를 붙들고 있어
    재채굴이 막힌다 — 그 latch 를 사람이 손으로 지우게 두면 `.asgard` 를 직접 여는 습관이 생긴다.

    **아무것도 잃지 않는다.** 초안은 `rejected/` 로 옮겨 그대로 남고(감사 가능), latch 는 퀘스트
    로그와 `corrections.jsonl` 에서 언제든 다시 만들어지는 파생물이다. 이미 설치된 learned 스킬은
    이 함수가 아예 안 본다 — 그쪽을 내리는 것은 `archive_skill` 의 일이다.
    """
    stamp = time.strftime("%Y%m%d%H%M%S")
    names = []
    for meta in pending_list(root):
        cid = str(meta.get("id") or "")
        if not cid:
            continue
        src, dst = _evo_dir(root, PENDING, cid), _archive_slot(root, f"{cid}-{stamp}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        names.append(str(meta.get("name") or cid))
    seen = _load_seen(root)
    # 사람이 내린 판단은 초기화가 안 지운다. 승인은 이미 스킬이 서 있어서 다시 제안하면 이름이
    # 충돌하고, 거절은 `reject` 가 "같은 신호는 다시 제안하지 않는다"고 약속한 자리다 — 그 약속과
    # 거절 사유는 `seen.json` 에만 있어서 여기서 지우면 사람이 한 번 내친 초안이 다시 올라온다.
    # 초기화가 푸는 것은 기계가 붙인 `proposed` 뿐이다.
    #
    # 보관에서 다시 캔 후보(`reopened`)는 지우는 대신 `archived` 로 되돌린다. 그 행이 사라지면
    # "사람이 이 스킬을 내려놓았다"는 사실이 같이 사라져, 다음 채굴이 표식 없는 새 후보를 뜨고
    # 등급 safe 가 그것을 자동 설치한다 — 초기화 한 번이 보관을 취소하는 자리였다. 되돌린
    # 행은 `_mineable` 이 열린 것으로 보므로 재채굴은 그대로 열려 있다.
    kept: dict = {}
    freed = 0
    for sig, row in seen.items():
        if str((row or {}).get("status")) != PROPOSED:
            kept[sig] = row
            continue
        freed += 1
        if (row or {}).get("reopened"):
            kept[sig] = {**row, "status": ARCHIVED}
    _save_seen(root, kept, drop=set(seen) - set(kept))
    _clear_nudge_latch(root)
    return (len(names), freed, names)
