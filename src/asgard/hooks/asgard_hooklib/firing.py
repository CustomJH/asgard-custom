"""훅이 몇 번 불렸고 그중 몇 번 실제로 무언가를 했는지 세는 누적 장부.

`gate-events.jsonl` 은 사건만 적는다 — 차단, 판정 없이 건너뜀, 상한 초과 에스컬레이션.
그래서 "이 게이트가 21번 잡았다"는 알아도 "몇 번 중 21번인가"는 모른다. 분모가 없으면 한 번도
발화하지 않은 훅과 발화할 일이 아예 없었던 훅이 화면에서 똑같이 생기고, 그러면 어느 층이
값을 그쳤는지 고를 수 없다. 이 파일이 그 분모다.

발화 판정은 훅의 신고가 아니라 관측이다: stdout 에 무엇을 냈거나 0 이 아닌 코드로 끝났으면
발화로 센다. 훅이 자기가 무엇을 했다고 말하는지와 무관하게 호스트가 실제로 받은 것이 기준이라,
계측을 위해 훅 21개의 내부 분기를 각각 읽고 표시할 필요가 없다.

예외로 죽은 호출은 발화가 아니라 `errors` 로 따로 센다. 둘을 합치면 "매번 고장 나 있었다"가
"열심히 일하고 있다"와 같은 숫자로 보인다.

기록은 전부 fail-open 이다 — 계측이 실패해도 훅의 판단은 그대로 나간다.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time

from .paths import repo_root

SCHEMA = 1


def counter_path(root: str) -> str:
    return os.path.join(root, ".asgard", "state", "gate-firing.json")


def load(root: str) -> dict:
    """카운터를 읽는다. 없거나 깨졌으면 빈 장부 — 계측 손상이 훅을 막지는 않는다."""
    try:
        with open(counter_path(root), encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        # 타입을 좁혀 여러 개로 적을 수 없다 — 포매터가 py314 로 맞춰져 있어 괄호를 지우고
        # PEP 758 문법으로 바꾸는데, 훅은 3.9 로도 파스돼야 한다 (test_hooks_parse_on_old_python).
        return {"schema": SCHEMA, "gates": {}}
    if not isinstance(data, dict) or not isinstance(data.get("gates"), dict):
        return {"schema": SCHEMA, "gates": {}}
    return data


def record(root: str, gate: str, fired: bool, failed: bool = False) -> None:
    """호출 1 을 올리고, 발화했으면 발화 수와 그 시각도 올린다.

    쓰기는 임시 파일 + `os.replace` 라 중간 상태가 디스크에 남지 않는다. 병렬 세션이 겹치면
    읽고-고치고-쓰는 사이에 남의 갱신을 덮어 카운트 몇 건을 잃지만, 이 장부가 답하는 질문
    ("이 훅이 아직 발화하는가")은 한두 건 손실로 뒤집히지 않는다. 정확한 총량이 필요해지면
    그때 append 로 바꿔야 한다.
    """
    try:
        state = os.path.join(root, ".asgard", "state")
        if not os.path.isdir(state):
            return  # asgard 를 안 쓰는 트리다 — 계측이 꺼진 게 아니라 잴 자리가 없다
        data = load(root)
        row = data["gates"].setdefault(gate, {"calls": 0, "fires": 0})
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        row["calls"] = int(row.get("calls", 0)) + 1
        row["last_call"] = stamp
        if fired:
            row["fires"] = int(row.get("fires", 0)) + 1
            row["last_fire"] = stamp
        if failed:
            row["errors"] = int(row.get("errors", 0)) + 1
        data["schema"] = SCHEMA
        path = counter_path(root)
        # pid 를 붙인다 — 이름을 공유하면 훅 둘이 겹칠 때 한쪽이 `os.replace` 로 살린 파일에
        # 다른 쪽 fd 가 계속 써서 장부가 깨진 JSON 이 되고, 그때 `load()` 는 빈 장부를 준다.
        # 잃는 것이 카운트 몇 건이 아니라 누적 전체이고, 되감기면 발화 없는 훅이 문턱에 영영
        # 도달하지 못한다 (craft_gate._bump 가 같은 이유로 같은 모양을 쓴다).
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        # 타입을 좁혀 여러 개로 적지 않는 이유는 craft_gate 와 같다 — 포매터가 py314 문법으로
        # 바꾸는데 훅은 3.9 로도 파스돼야 한다 (tests/architecture/test_layered.py).
        pass  # 계측 실패는 계측만 잃는다


def event(root, gate: str, kind: str, code: str, subject=None, sid=None) -> None:
    """게이트 운영 사건을 `gate-events.jsonl` 에 append 한다 — 차단, 판정 없이 건너뜀, 상한 초과.

    `record()` 가 세는 누적과 달리 여기는 개별 사건이라 시각 순서와 대상이 남는다. 두 게이트가
    각자 이 함수를 품고 있어서 verifier 쪽 21건에는 `gate` 가 아예 안 찍혔다 — 어느 게이트가
    잡았는지 모르는 차단 기록은 사유별 집계는 되어도 어느 층을 고칠지는 말해주지 않는다.

    `subject` 는 그 차단이 무엇을 두고 걸렸는지다 (stale-pass 면 드리프트한 파일).
    """
    try:
        state = os.path.join(str(root), ".asgard", "state")
        os.makedirs(state, exist_ok=True)
        row = {"event": kind, "gate": gate, "code": code}
        if subject:
            row["subject"] = list(subject)
        if sid is not None:
            row["sid"] = str(sid)
        with open(os.path.join(state, "gate-events.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 계측 실패는 계측만 잃는다


def run(gate: str, main) -> None:
    """훅 본체를 돌리고 호출·발화를 센 뒤 원래대로 끝낸다.

    stdout 을 모았다가 그대로 다시 내보낸다 — 훅이 낸 바이트는 한 글자도 바뀌지 않고, 그것이
    비었는지 아닌지만 본다. 본체가 던진 예외는 삼키지 않고 다시 흘려보낸다: 훅 계약이
    fail-open 이라 예외를 여기서 먹으면 죽은 층이 조용해지고, 그 침묵이야말로 이 장부가
    드러내려는 것이다.
    """
    buffer = io.StringIO()
    code = 0
    fired = False
    failed = True  # 정상 경로를 다 지난 뒤에만 내린다 — 중간에 예외로 나가면 고장으로 센다
    try:
        try:
            with contextlib.redirect_stdout(buffer):
                code = main() or 0
        except SystemExit as exit_signal:
            code = exit_signal.code if exit_signal.code is not None else 0
        fired = bool(buffer.getvalue()) or code != 0
        failed = False
    finally:
        text = buffer.getvalue()
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()
        record(repo_root(), gate, fired, failed)
    raise SystemExit(code)
