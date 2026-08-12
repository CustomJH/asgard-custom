#!/usr/bin/env python3
"""디스패치 장부(.asgard/orchestration.db)를 JSON 레코드로 뽑는 수집기.

레코드 한 건은 dispatches 한 행이다. 계약 키는 dispatch·task·run·agent·role·
state·start·end 여덟 개로 고정이고, end 는 아직 정산되지 않은 디스패치에서 null 이다.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / ".asgard" / "orchestration.db"

QUERY = """
SELECT id, task_id, run_id, agent, role, state, created_at, settled_at
FROM dispatches
{where}
ORDER BY created_at
"""


def role_of(role: str, agent: str) -> str:
    """디스패치 행이 실제로 태운 역할 이름.

    dispatches.role 은 역할이 아니라 배차 경로다 — 66행 중 63행이 리터럴 'agent'
    (이름 붙은 서브에이전트로 나갔다), 나머지 3행이 'worker'(워커 자리에서 직접 돌았다).
    경로가 'agent' 인 행에서만 agent 이름의 asgard- 접두를 떼어 역할로 쓴다.
    """
    if role == "agent" and agent:
        return agent[len("asgard-") :] if agent.startswith("asgard-") else agent
    return role


def collect(db_path: Path, run: str | None) -> list[dict]:
    where = "WHERE run_id = ?" if run else ""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        rows = conn.execute(QUERY.format(where=where), (run,) if run else ()).fetchall()
    return [
        {
            "dispatch": did,
            "task": task,
            "run": run_id,
            "agent": agent,
            "role": role_of(role, agent),
            "state": state,
            "start": float(created),
            "end": None if settled is None else float(settled),
        }
        for did, task, run_id, agent, role, state, created, settled in rows
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="dispatch records as JSON")
    ap.add_argument("--run", help="restrict to one run id")
    ap.add_argument("--out", type=Path, help="write here instead of stdout")
    args = ap.parse_args()

    if not DB_PATH.exists():
        json.dump({"error": "db_not_found", "path": str(DB_PATH)}, sys.stderr, ensure_ascii=False)
        sys.stderr.write("\n")
        return 2

    payload = json.dumps({"records": collect(DB_PATH, args.run)}, ensure_ascii=False)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
