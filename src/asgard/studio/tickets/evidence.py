"""티켓 — 완료 증거. 부하 실행 하나를 티켓에 매달고, 판정 셋(pass·fail·unjudged)을 그대로 진다."""

from __future__ import annotations

import os
import sqlite3
from typing import Any
from uuid import uuid4

from ..db import reading, writing
from ._core import (
    _MAX_EVIDENCE_NOTE,
    _MAX_NAME,
    _STAMP,
    TicketError,
    _find,
    _log,
    _now,
    _read_scope,
    _resolve,
    _text,
    _untouched,
)

# ── 부하 근거 — 이 티켓의 성능 주장이 어느 실행에서 나왔는가 ─────────────────────
#
# **판정이 아니라 참조다.** 모든 티켓이 부하와 관계있지는 않으므로 여기에 게이트를 두지 않는다.
# 무관한 티켓을 부하 시험으로 막으면 그 게이트는 우회되고, 우회된 게이트는 아무것도 재지 않는다.
# 매다는 것도 떼는 것도 티켓의 상태를 안 건드린다.
#
# 미판정 실행(`verdict="unjudged"`)도 받는다. 거절하는 쪽이 더 엄격해 보이지만, 거절은 매달기를
# 막을 뿐이라 그 사람이 하는 일은 아무것도 안 매다는 것이고 그러면 성능 주장은 다시 사람의
# 기억으로 돌아간다 — 이 계층이 닫으려던 구멍 그대로다. 저장소가 최근에 고친 자리도 미판정을
# **금지**한 것이 아니라 통과와 **다르게 읽히게** 한 것이다(`k6.Report.judged`, 종료 코드 3).
# 같은 형상을 따른다: 기록은 남기고, 판정 칸이 그것을 통과로 위장하지 못하게 한다.


def _stamp(value: Any) -> str:
    stamp = str(value or "").strip()
    if not _STAMP.fullmatch(stamp):
        raise TicketError(f"'{stamp}' is not a run stamp — expected one path segment like 20260803T151258-http-smoke")
    return stamp


def _judged(payload: dict) -> bool:
    """이 실행에 판정할 것이 있었는가.

    `judged` 칸이 있으면 그것을 읽고, 없으면 임계값 목록으로 되짚는다. 그 칸이 생기기 전에
    적힌 기록이 아직 남아 있고, 없는 칸을 참으로 읽으면 판정 안 받은 실행이 통과로 굳는다.
    되짚는 방법은 정본과 같은 정의다 — `k6.Report.judged` 가 곧 `bool(thresholds)` 다."""
    if "judged" in payload:
        return bool(payload["judged"])
    return bool(payload.get("thresholds"))


def _verdict(payload: dict) -> str:
    if not _judged(payload):
        return "unjudged"
    return "pass" if bool(payload.get("ok")) else "fail"


def _run_payload(root: str, stamp: str = "", scenario: str = "") -> tuple[str, dict]:
    """기록된 실행 하나를 찾아 (표식, 요약 본문)으로 돌려준다. 없으면 거절한다.

    `k6` 는 같은 계층의 형제라 모듈 최상단에서 부르지 않는다(계층 규칙은 임포트 시점에 도는
    것만 본다). 경로를 직접 조립하지 않고 그쪽에 묻는 이유는 `runs/` 의 배치가 그 모듈의
    계약이어서다 — 여기에 사본을 두면 한쪽만 옮겨졌을 때 이 표가 없는 파일을 가리킨다."""
    from ...k6_gate import find_recorded_run

    if stamp:
        stamp = _stamp(stamp)
    record = find_recorded_run(root or ".", stamp, scenario=scenario)
    if record is None:
        if stamp:
            raise TicketError(f"no recorded load run for stamp {stamp} — run `asgard k6 run` first")
        where = f" for scenario {scenario}" if scenario else ""
        raise TicketError(f"there is no recorded load run{where} in this project yet — run `asgard k6 run` first")
    return _stamp(record.stamp), record.payload


def _evidence_root(root: str, filed: str) -> str:
    """어느 폴더의 기록을 볼 것인가 — 부르는 자리가 먼저고, 거기 기록이 하나도 없을 때만 티켓의 자리다.

    보드는 폴더에 안 매이지만 `runs/` 는 프로젝트 안에 있다. 창은 개인 작업 공간에서 열려서
    그 자리에만 물으면 창으로 매다는 길이 영영 "기록이 없다"로 끝난다.

    그렇다고 티켓의 자리를 먼저 보면 안 된다: 프로젝트 A 에서 방금 잰 사람이 B 에 적힌 티켓에
    매달면, **다른 실행**이 조용히 근거로 붙는다. 그건 이 계층이 막으려는 것보다 나쁘다 — 근거가
    없는 것은 화면에 보이지만 틀린 근거는 안 보인다. 그래서 부르는 자리에 기록이 하나도 없어
    헷갈릴 것이 없을 때만 물러난다."""
    from ...k6_gate import recorded_runs

    if not filed or not os.path.isdir(filed) or recorded_runs(root or "."):
        return root
    return filed


def attach_evidence(
    root: str, ref: Any, stamp: str = "", *, scenario: str = "", note: str = "", actor: str = ""
) -> dict[str, Any]:
    """부하 실행 하나를 티켓에 매단다. 표식을 안 주면 이 프로젝트의 가장 최근 기록이다.

    수치를 스냅샷으로 함께 적는다 — 원본(`.asgard/k6/runs/`)은 gitignore이고 정리 정책이 없어서,
    가리키는 값만 적어 두면 그 디렉터리가 없어진 뒤에 성능 주장의 근거도 조용히 사라진다.

    같은 실행을 두 번 매달면 행이 늘지 않고 스냅샷이 다시 적힌다: 한 티켓에 같은 실행이 두 번
    붙으면 목록을 읽는 사람이 두 번 쟀다고 읽는다."""
    note = _text(note, "note", _MAX_EVIDENCE_NOTE)
    actor = _text(actor, "actor", _MAX_NAME)
    if _untouched():
        raise TicketError(f"ticket not found: {ref}")
    # 티켓을 먼저 푼다 — 어느 폴더의 기록을 볼지가 그 티켓이 적어 둔 자리에 달려 있고, 없는
    # 티켓에 대고 "기록이 없다"고 답하면 사람은 엉뚱한 것을 고치러 간다.
    with reading() as conn:
        filed = str(_resolve(conn, ref, scope=_read_scope(conn, root))["root"] or "")
    where = _evidence_root(root, filed)
    found, payload = _run_payload(where, stamp, scenario)
    verdict = _verdict(payload)
    latency = payload.get("latency_ms") or {}
    requests = payload.get("requests") or {}
    with writing() as conn:
        row = _resolve(conn, ref, scope=_read_scope(conn, root))
        now = _now()
        conn.execute(
            "INSERT INTO ticket_evidence(id, ticket_id, stamp, scenario, verdict, p95_ms, failed_rate, rate_per_s, "
            "runner, k6_version, target, root, note, actor, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(ticket_id, stamp) DO UPDATE SET "
            "scenario = excluded.scenario, verdict = excluded.verdict, p95_ms = excluded.p95_ms, "
            "failed_rate = excluded.failed_rate, rate_per_s = excluded.rate_per_s, runner = excluded.runner, "
            "k6_version = excluded.k6_version, target = excluded.target, root = excluded.root, "
            # 다시 매달 때 한 줄을 안 주면 먼저 적어 둔 것을 그대로 남긴다 — 수치를 새로 재려고 부른
            # 호출이 "이 실행이 왜 근거인가"까지 조용히 비우면, 그 문장을 다시 적을 사람이 없다.
            "note = CASE WHEN excluded.note = '' THEN ticket_evidence.note ELSE excluded.note END, "
            "actor = excluded.actor, created_at = excluded.created_at",
            (
                uuid4().hex,
                row["id"],
                found,
                str(payload.get("scenario") or ""),
                verdict,
                float(latency.get("p95") or 0.0),
                float(requests.get("failed_rate") or 0.0),
                float(requests.get("rate_per_s") or 0.0),
                str(payload.get("runner") or ""),
                str(payload.get("k6_version") or ""),
                str(payload.get("target") or ""),
                os.path.abspath(where) if where else "",
                note,
                actor,
                now,
            ),
        )
        conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now, row["id"]))
        _log(conn, str(row["id"]), actor, "evidence", "", f"{found} · {verdict}")
        return _evidence_rows(conn, str(row["id"]), found)[0]


def list_evidence(root: str | None = None, ref: Any = None) -> list[dict[str, Any]]:
    """이 티켓에 매달린 부하 근거 전부, 최근에 매단 것부터."""
    if _untouched():
        return []
    with reading() as conn:
        row = _resolve(conn, ref, scope=_read_scope(conn, root))
        return _evidence_rows(conn, str(row["id"]))


def detach_evidence(root: str, ref: Any, stamp: str) -> bool:
    """근거 하나를 뗀다. 원본 기록은 안 건드린다 — 이 표가 소유한 것은 참조뿐이다."""
    with writing() as conn:
        row = _find(conn, ref, _read_scope(conn, root))
        if row is None:
            return False
        cursor = conn.execute(
            "DELETE FROM ticket_evidence WHERE ticket_id = ? AND stamp = ?", (row["id"], _stamp(stamp))
        )
        return cursor.rowcount > 0


def _evidence_rows(conn: sqlite3.Connection, ticket_id: str, stamp: str = "") -> list[dict[str, Any]]:
    """읽기 모델. 스냅샷에 **원본이 아직 있는가**를 함께 붙인다.

    이 한 칸이 표면의 문장을 가른다: 원본이 있으면 스탬프로 전문을 열 수 있고, 없으면 화면이
    "여기 적힌 수치가 남은 전부"라고 말해야 한다. 그 사실을 화면이 스스로 알아내게 두면
    창·CLI·툴이 각각 경로를 조립하고, 그중 하나는 언젠가 다른 자리를 본다."""
    clause = " AND stamp = ?" if stamp else ""
    args: list[Any] = [ticket_id, stamp] if stamp else [ticket_id]
    out: list[dict[str, Any]] = []
    for row in conn.execute(
        f"SELECT * FROM ticket_evidence WHERE ticket_id = ?{clause} ORDER BY created_at DESC", args
    ):
        path = _report_path(str(row["root"] or ""), str(row["stamp"]))
        out.append(
            {
                "stamp": row["stamp"],
                "scenario": row["scenario"],
                "verdict": row["verdict"],
                "judged": row["verdict"] != "unjudged",
                "p95_ms": row["p95_ms"],
                "failed_rate": row["failed_rate"],
                "rate_per_s": row["rate_per_s"],
                "runner": row["runner"],
                "k6_version": row["k6_version"],
                "target": row["target"],
                "root": row["root"],
                "note": row["note"],
                "actor": row["actor"],
                "created_at": row["created_at"],
                "report_path": path,
                "report_exists": bool(path) and os.path.isfile(path),
            }
        )
    return out


def _report_path(root: str, stamp: str) -> str:
    """스냅샷이 나온 원본 요약의 자리. 매단 폴더를 모르면 빈 문자열이다."""
    if not root or not _STAMP.fullmatch(stamp):
        return ""
    from ...k6 import runs_dir

    return str(runs_dir(root) / stamp / "report.json")
