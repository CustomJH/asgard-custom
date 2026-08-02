"""활동 스트림 — 도는 동안 무엇을 하고 있는지를 **기계가 읽을 수 있게** 흘린다.

터미널은 이미 이걸 알고 있었다. `AgentSession._execute`가 툴을 부르기 직전에 `on_status`로
`$ uv run pytest -q`를 띄우고, 끝나면 소요시간을 단 줄을 스크롤백에 남긴다. 문제는 그 앎이
**사람의 눈에만** 흘렀다는 것이다: 헤드리스(`asgard run --json`)는 활동을 stderr의 색칠된
문장으로 뱉었고, 그걸 자식으로 띄운 스튜디오는 프로세스가 끝날 때까지 기다렸다가 통째로
받았다. 그래서 창에는 '실행 중'과 무한히 도는 막대뿐이었다 — 화면이 게을러서가 아니라
**줄 것이 없어서**다.

이 모듈은 그 앎을 한 줄짜리 JSON으로 한 번 더 적는다. 소비자는 파일을 tail 한다.

왜 파일인가. stdout은 이미 `--json` 요약 한 덩이의 자리라 계약이 차 있고, stderr는 사람이
읽는 색칠된 문장이라 파싱하면 문구를 바꾸는 순간 조용히 깨진다. 파일은 셋 다 안 건드린다:
기존 두 표면은 바이트 단위로 그대로고, 재접속한 소비자는 처음부터 다시 읽어 놓친 구간을
복원할 수 있으며, 파이프 버퍼가 없으니 소비자가 느려도 생산자가 막히지 않는다.

계약 하나: **이 층은 절대 실행을 막지 않는다.** 경로가 없으면 no-op이고, 쓰다 실패하면
삼킨다. 관측이 실행을 세우면 그건 관측이 아니라 관문이다.
"""

from __future__ import annotations

import json
import os
import threading
import time

ENV_PATH = "ASGARD_EVENT_LOG"  # 소비자(스튜디오)가 자식에게 건네는 자리
MAX_BYTES = 8_000_000  # 이 위로는 안 적는다 — 폭주한 턴이 디스크를 먹지 않게

_lock = threading.Lock()  # wave·편대가 병렬로 부른다 — 한 줄이 반씩 섞이면 소비자가 못 읽는다
_seq = 0
_stopped = False  # 상한 초과·쓰기 실패로 한 번 접으면 그 프로세스에서는 다시 안 연다


def path() -> str:
    """이 프로세스가 활동을 적을 자리. 빈 문자열이면 아무 데도 안 적는다."""
    return os.environ.get(ENV_PATH) or ""


def enabled() -> bool:
    return bool(path()) and not _stopped


def emit(kind: str, **payload) -> None:
    """활동 한 건. 실패는 전부 삼킨다 (fail-open)."""
    global _seq, _stopped
    target = path()
    if not target or _stopped:
        return
    try:
        with _lock:
            if _stopped:
                return
            try:
                if os.path.getsize(target) > MAX_BYTES:
                    _stopped = True
                    return
            except OSError:
                pass  # 아직 없는 파일 — 첫 줄이 만든다
            _seq += 1
            row = {"seq": _seq, "ts": round(time.time(), 3), "kind": kind}
            for key, value in payload.items():
                if value is not None and value != "":
                    row[key] = value
            line = json.dumps(row, ensure_ascii=False) + "\n"
            fd = os.open(target, os.O_APPEND | os.O_WRONLY | os.O_CREAT, 0o644)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
    except Exception:
        _stopped = True  # 한 번 못 적으면 매 툴콜마다 다시 시도해 봐야 같은 실패다


def open_log(root: str, task_id: str) -> str:
    """소비자 쪽 — 이 작업의 활동 파일을 만들고 그 경로를 돌려준다.

    자리는 `io_journal`과 같은 `.asgard/state/` 다. 거기에 이미 `.gitignore` 자가 설치 규약이
    서 있어서, 활동 파일이 그 폴더의 첫 기록자여도 저장소를 더럽히지 않는다."""
    folder = os.path.join(root, ".asgard", "state", "events")
    os.makedirs(folder, exist_ok=True)
    guard = os.path.join(root, ".asgard", ".gitignore")
    if not os.path.exists(guard):
        try:
            with open(guard, "w", encoding="utf-8") as fh:
                fh.write("*\n")
        except OSError:
            pass
    target = os.path.join(folder, f"{task_id}.jsonl")
    with open(target, "w", encoding="utf-8"):  # 소비자가 붙기 전에 존재해야 tail이 안 헤맨다
        pass
    _prune(folder)
    return target


_KEEP = 40  # 최근 작업 몇 건의 활동을 남길 것인가 — 퀘스트 로그 keep-last-30과 같은 성격


def _prune(folder: str) -> None:
    """오래된 활동 파일 정리. 실패해도 조용히 넘어간다 — 청소가 실행을 막지 않는다."""
    try:
        rows = [os.path.join(folder, name) for name in os.listdir(folder) if name.endswith(".jsonl")]
        rows.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for stale in rows[_KEEP:]:
            os.unlink(stale)
    except OSError:
        pass


def read_log(target: str, offset: int = 0) -> tuple[list[dict], int]:
    """`offset` 바이트 뒤부터 읽어 (사건들, 다음 offset)을 돌려준다.

    마지막 줄이 아직 개행으로 안 닫혔으면 그 줄은 **안 읽고 offset도 안 옮긴다** — 반만 적힌
    줄을 파싱해 버리면 그 사건은 영영 유실된다. 다음 차례에 온전해진 채로 다시 만난다."""
    rows: list[dict] = []
    try:
        with open(target, "rb") as fh:
            fh.seek(offset)
            blob = fh.read()
    except OSError:
        return rows, offset
    if not blob:
        return rows, offset
    tail = blob.rfind(b"\n")
    if tail < 0:
        return rows, offset
    for line in blob[: tail + 1].splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows, offset + tail + 1
