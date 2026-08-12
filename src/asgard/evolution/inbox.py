"""pending 인박스 — 후보 스테이징(`mine`)과 읽기(`pending_list`·`show`)."""

from __future__ import annotations

import os
import time

from .. import io_files
from ..skill_bank import SKILL_FILE
from .corrections import _corrections
from .drafts import _cand_id, _correction_draft, _draft
from .quests import _quest_signal, _read_quest
from .store import _SCAN_CAP, ARCHIVED, PENDING, PROPOSED, _evo_dir, _load_seen, _mineable, _save_seen


def _stage_candidate(root: str, seen: dict, signal: str, name: str, skill_md: str, meta_extra: dict) -> dict:
    """후보 1건을 pending에 스테이징 + seen latch. 반환 = 후보 메타 (채굴원 공용)."""
    cid = _cand_id(signal)
    d = _evo_dir(root, PENDING, cid)
    os.makedirs(d, exist_ok=True)
    io_files.write_text(os.path.join(d, SKILL_FILE), skill_md)
    meta = {
        "id": cid,
        "name": name,
        "signal": signal,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **meta_extra,
    }
    # 보관에서 다시 열린 신호였다는 사실은 상태를 `proposed` 로 덮어도 남아야 한다 — 그 표식이
    # 없으면 `autoapprove` 가 사람이 내려놓은 카드를 같은 턴에 되설치한다.
    row: dict = {"status": PROPOSED, "id": cid, "ts": meta["created"]}
    if str((seen.get(signal) or {}).get("status")) == ARCHIVED:
        meta["reopened"] = True
        row["reopened"] = True
    io_files.write_json(os.path.join(d, "meta.json"), meta)
    seen[signal] = row
    return meta


def mine(root: str, cap: int = _SCAN_CAP) -> list[dict]:
    """2채굴원 스캔 — quest 로그(FAIL→PASS) + 사용자 정정(corrections.jsonl) → pending 스테이징."""
    seen = _load_seen(root)
    created: list[dict] = []
    qdir = os.path.join(root, ".asgard", "quest")
    if os.path.isdir(qdir):
        for fname in sorted(os.listdir(qdir)):
            if not fname.endswith(".jsonl") or len(created) >= cap:
                continue
            sig = _quest_signal(_read_quest(os.path.join(qdir, fname)))
            if not sig or not _mineable(seen, sig["signal"]):
                continue
            name, skill_md = _draft(sig)
            created.append(
                _stage_candidate(
                    root,
                    seen,
                    sig["signal"],
                    name,
                    skill_md,
                    {"quest_id": sig["quest_id"], "fail_count": sig["fail_count"], "origin": "retrospective"},
                )
            )
    for row in _corrections(root):
        if len(created) >= cap:
            break
        signal = str(row.get("signal") or "")
        if not signal or not _mineable(seen, signal):
            continue
        name, skill_md = _correction_draft(row)
        created.append(_stage_candidate(root, seen, signal, name, skill_md, {"origin": "correction"}))
    if created:
        _save_seen(root, seen)
    return created


def unmined_signals(root: str, qid: str | None = None) -> int:
    """미제안 신호 수 (쓰기 없음) — 넛지·doctor 용. qid 지정 시 해당 퀘스트만 (정정 제외)."""
    seen = _load_seen(root)
    n = 0
    qdir = os.path.join(root, ".asgard", "quest")
    if os.path.isdir(qdir):
        for fname in sorted(os.listdir(qdir)):
            if not fname.endswith(".jsonl"):
                continue
            if qid and fname != f"{qid}.jsonl":
                continue
            sig = _quest_signal(_read_quest(os.path.join(qdir, fname)))
            if sig and _mineable(seen, sig["signal"]):
                n += 1
    if qid is None:
        n += sum(1 for row in _corrections(root) if _mineable(seen, str(row.get("signal") or "")))
    return n


def pending_list(root: str) -> list[dict]:
    d = _evo_dir(root, PENDING)
    if not os.path.isdir(d):
        return []
    out = []
    for cid in sorted(os.listdir(d)):
        try:
            out.append(io_files.read_json(os.path.join(d, cid, "meta.json"), {}))
        except OSError:
            continue
    return out


def show(root: str, cid: str) -> str | None:
    return io_files.read_text(_evo_dir(root, PENDING, cid, SKILL_FILE)) or None
