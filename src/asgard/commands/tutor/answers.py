"""답 걷기 — 보고서에 손으로 적어 둔 답을 한 번에 성장 기록으로 옮긴다."""

from __future__ import annotations

import os
import re

from ... import tutor_growth, ui

_CID_RE = re.compile(r"`([0-9a-f]{8})`")
_ITEM_RE = re.compile(r"^\s*- \[.\] ")


def collect(text: str) -> dict[str, str]:
    """보고서 본문 → {물음 표식: 손으로 적은 답}. 빈 칸은 안 걷는다.

    사람이 실제로 답하는 자리는 명령줄이 아니라 **편집기**다 — 보고서를 열어 놓고 그 자리에
    적는다. 그래서 되걷는 통로가 없으면 그 답은 파일에만 남고 이 층은 계속 아무것도 모른다.
    파서는 일부러 느슨하다: 사람이 손으로 고친 문서를 엄격히 읽으면 대부분 못 읽는다.
    """
    out: dict[str, str] = {}
    cid, buffer, taking = "", [], False
    for line in text.splitlines():
        body = line.strip()
        if _ITEM_RE.match(line):
            _flush(out, cid, buffer)
            found = _CID_RE.search(line)
            cid, buffer, taking = (found.group(1) if found else ""), [], False
            continue
        if body.startswith("- 답:"):
            buffer, taking = [body[len("- 답:") :].strip()], True
            continue
        if taking and body and not body.startswith(("- ", "#", "|", ">")):
            buffer.append(body)  # 여러 줄로 적은 답 — 다음 항목이나 다른 절이 시작될 때까지
            continue
        taking = False
    _flush(out, cid, buffer)
    return out


def _flush(out: dict[str, str], cid: str, buffer: list[str]) -> None:
    body = " ".join(b for b in buffer if b).strip()
    if cid and body:
        out[cid] = body


def _run_collect(root: str, path: str) -> int:
    from ...io_files import read_text

    full = path if os.path.isabs(path) else os.path.join(root, path)
    answers = collect(read_text(full))
    ui.head("tutor · 보고서에 적어 두신 답을 걷을게요")
    if not answers:
        ui.ok(f"{os.path.relpath(full, root)}에 채워 둔 `답:` 칸이 없어요 — 걷을 게 없네요")
        ui.done()
        return 0
    taken, missed = 0, 0
    for cid, body in answers.items():
        ok, note = tutor_growth.answer(root, cid, body)
        if ok:
            taken += 1
            ui.ok(f"[{cid}] {ui.oneline(body, 60)}")
            ui.step(ui.dim(f"    {note}"))
        else:
            missed += 1
    if missed:
        ui.step(ui.dim(f"    {missed}건은 이미 닫혔거나 열린 물음이 아니라서 건너뛰었어요"))
    ui.done(f"{taken}건을 성장 기록에 넣었어요")
    return 0
