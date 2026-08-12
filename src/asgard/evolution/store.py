"""진화 인박스가 디스크에 두는 자리 — 경로 조립, `seen.json` latch, 넛지 지문 파일."""

from __future__ import annotations

import os
import time

from .. import io_files

EVO_DIR = "evolution"
PENDING = "pending"
REJECTED = "rejected"
PROPOSED = "proposed"  # 기계가 붙이는 유일한 상태 — 나머지는 사람이나 정책이 내린 판단이다
ARCHIVED = "archived"  # 승인이 보관으로 물린 자리 — 기록은 남기고 재채굴만 다시 연다
_DECIDED = frozenset({"approved", "rejected", ARCHIVED})
SEEN_FILE = "seen.json"
CORRECTIONS_FILE = "corrections.jsonl"
_SCAN_CAP = 3  # 스캔 1회당 신규 후보 상한 — 인박스 폭탄 방지
_CORRECTIONS_CAP = 200  # corrections.jsonl 보존 상한 — 최신 우선


def _evo_dir(root: str, *parts: str) -> str:
    return os.path.join(root, ".asgard", EVO_DIR, *parts)


def _load_seen(root: str) -> dict:
    d = io_files.read_json(_evo_dir(root, SEEN_FILE))
    return d if isinstance(d, dict) else {}


def _save_seen(root: str, seen: dict, *, drop: object = ()) -> None:
    """latch 저장 — 디스크 최신본과 합쳐서 쓴다. `drop` 은 이번에 없앨 신호들 (`reset` 전용).

    왜 통째로 안 덮어쓰는가. 이 파일을 쓰는 손이 둘 이상인데 읽기-수정-쓰기 사이에 잠금이
    없다: 사람이 치는 `evolve approve`/`reject` 와, 매 턴 끝 Stop 훅이 도는 `autoscan` 이
    같은 파일을 각자 읽고 각자 덮어쓴다. 나중에 쓰는 쪽이 앞 쪽 항목을 통째로 지우는데,
    지워지는 것이 `proposed` 면 후보가 한 번 더 뜨는 정도지만 `approved`·`rejected` 면
    사람이 내린 판단과 그 사유가 없어진다 — `reject` 가 약속한 "같은 신호는 다시 제안하지
    않는다"가 깨지고, 사유 문자열은 이 파일에만 있어 복구할 곳도 없다.

    보관(`archived`)도 사람의 판단이라 같은 보호를 받는다. 판단 둘이 같은 신호를 두고 부딪히면
    **적힌 시각이 더 새 쪽을 채택한다** — 호출 순서로 정하면 보관 직전 스냅샷을 든 손이 `archived` 를
    `approved` 로 되돌리고 그 신호가 다시 못 캐지게 된다. 예외는 하나다: 그 보관에서 다시 캔
    후보(`reopened`)의 `proposed` 는 보관 사실에서 파생된 것이라 통과시킨다. 안 그러면
    재채굴이 latch 를 영영 못 갱신한다.

    잠금 대신 병합인 이유는 이식성이다. POSIX 의 `fcntl.flock` 과 Windows 의 `msvcrt.locking`
    은 서로 다른 모듈이라 잠금을 쓰면 운영체제마다 구현을 따로 두어야 하고, 병합은 같은 코드가
    양쪽에서 그대로 동작한다. 시각은 초 단위라 같은 초의 두 쓰기는 못 가른다 (수용).
    """
    merged = dict(_load_seen(root))
    for signal in drop if isinstance(drop, (list, tuple, set, frozenset)) else ():
        merged.pop(str(signal), None)
    for signal, row in seen.items():
        prior = merged.get(signal)
        # 보호받는 행은 둘이다: 사람이 내린 판단(승인·거절·보관)과, 그 보관에서 다시 캔
        # 제안이다. 뒤쪽은 상태만 보면 기계가 붙인 `proposed` 라 그냥 두면 보호에서 빠지는데,
        # 그 행이 들고 있는 `reopened` 가 곧 보관 사실이라 잃으면 보관이 취소된다.
        held = isinstance(prior, dict) and (prior.get("status") in _DECIDED or prior.get("reopened"))
        if not held:
            merged[signal] = row
            continue
        incoming = row or {}
        if str(incoming.get("status")) == PROPOSED and not incoming.get("reopened"):
            continue  # 디스크의 사람 판단을 기계가 붙이는 `proposed` 로 되돌리지 않는다
        if str(incoming.get("ts") or "") < str(prior.get("ts") or ""):
            continue  # 낡은 스냅샷이 더 새 판단을 덮지 않는다
        merged[signal] = row
    io_files.write_json(_evo_dir(root, SEEN_FILE), merged)


def _mineable(seen: dict, signal: str) -> bool:
    """이 신호를 (다시) 캘 수 있는가 — 처음 보는 신호이거나, 승인이 보관으로 물린 신호다.

    latch 는 키 존재로 판정했다. 그래서 승인된 스킬을 나중에 보관해도 그 신호는 영영 다시
    안 캐졌다 — 초안 생성기가 좋아져도(트리거 규칙은 26-08-11 에 실제로 한 번 바뀌었다) 같은
    퀘스트에서 더 나은 카드를 다시 뜰 수 없고, 퀘스트 로그는 keep-last-N 으로 지워져 원자료가
    먼저 사라진다. 보관은 키를 지우지 않고 상태만 되돌리므로 누가 언제 승인했는지는 남는다."""
    row = seen.get(signal)
    return row is None or str((row or {}).get("status")) == ARCHIVED


def _archive_slot(root: str, base: str) -> str:
    """`rejected/` 안에서 아직 안 쓰인 자리 — 이름이 겹치면 뒤에 번호를 붙인다.

    자리 이름이 초 단위 시각이라 같은 초에 두 번 치면 겹친다. `shutil.move` 는 목적지가 이미
    디렉터리면 그 **안으로** 옮기려 하고, 그 안에 같은 이름이 또 있으면 `shutil.Error` 로 죽는다
    — `evolve reset` 을 연달아 두 번 친 사람이 예외를 본 자리다."""
    slot = _evo_dir(root, REJECTED, base)
    seq = 2
    while os.path.exists(slot):
        slot = _evo_dir(root, REJECTED, f"{base}-{seq}")
        seq += 1
    return slot


def _latched(root: str, digest: str, count: int) -> bool:
    """같은 집합으로 두 번 말하지 않기 — 반복 넛지는 거부 피로를 만든다."""
    state_path = os.path.join(root, ".asgard", "state", "evolve-nudge.json")
    try:
        if (io_files.read_json(state_path) or {}).get("digest") == digest:
            return True
    except AttributeError:
        pass
    try:
        io_files.write_json(
            state_path,
            {"digest": digest, "count": count, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            indent=None,
        )
    except OSError:
        return True  # latch를 기록할 수 없으면 침묵 — 반복 넛지가 침묵보다 나쁘다
    return False


def _clear_nudge_latch(root: str) -> None:
    """넛지 지문도 같이 지운다 — 안 지우면 초기화 뒤 첫 채굴이 "같은 집합" 으로 읽혀 조용하다."""
    try:
        os.remove(os.path.join(root, ".asgard", "state", "evolve-nudge.json"))
    except OSError:
        pass  # 없으면 지울 것도 없다 — 초기화가 이 한 줄로 실패하지 않는다
