#!/usr/bin/env python3
"""배차 장부에서 "워커가 딜리버리 전문가 둘을 동시에 돌렸다"를 읽어 낸다.

재는 것 셋. ① 두 전문가의 배차가 장부에 있는가. ② 각 배차의 Task 가 워커의 Task 를
`parent_id` 로 가리키는가 — 훅이 `--caller` 를 실제로 받았다는 뜻이고, 받지 못하면 부른 쪽이
장부에서 통째로 사라진다. ③ 두 배차의 생존 구간이 시간상 겹치는가 — 한 메시지에서 함께 떴다는
주장의 유일한 물증이다. 순서대로 떴다면 겹침이 0 이 되고 이 시험은 FAIL 이다.

구간은 `created_at`(PreToolUse, 훅이 배차를 여는 시각) ~ `settled_at`(SubagentStop). 아직 안
접힌 배차는 **PASS 근거가 되지 못한다** — 끝을 지금 시각으로 때우면 방금 뜬 배차 둘만으로도
겹침이 양수가 되어, 아무것도 안 끝난 순간이 "동시에 돌았다"로 읽힌다. 화면에는 그대로 뜨되
판정은 접힌 배차만 센다.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, ".asgard", "orchestration.db")
QUEST = "parallel-dispatch-check-260812"
SPECIALISTS = ("asgard-freyja", "asgard-thor")


def rows(quest: str) -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sql = """
        select d.id, d.agent, d.state, d.created_at, d.settled_at,
               t.id as task_id, t.parent_id, pt.agent as parent_agent
          from dispatches d
          join tasks t on t.id = d.task_id
          join runs r on r.id = d.run_id
     left join tasks pt on pt.id = t.parent_id
         where r.quest_id = ?
      order by d.created_at
    """
    out = [dict(r) for r in con.execute(sql, (quest,))]
    con.close()
    return out


def span(row: dict) -> tuple[float, float]:
    return float(row["created_at"] or 0.0), float(row["settled_at"] or time.time())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quest", default=QUEST)
    args = parser.parse_args()

    records = rows(args.quest)
    if not records:
        print(f"FAIL: no dispatch rows for quest {args.quest}")
        return 1

    for row in records:
        start, end = span(row)
        print(f"  {row['agent']:<18} {row['state']:<9} {end - start:7.1f}s  caller={row['parent_agent'] or '<none>'}")

    failures: list[str] = []
    picked: dict[str, dict] = {}
    for name in SPECIALISTS:
        hits = [r for r in records if r["agent"] == name]
        if not hits:
            failures.append(f"{name} has no dispatch row — the fan-out never reached the ledger")
            continue
        picked[name] = hits[-1]
        if hits[-1]["parent_agent"] != "asgard-worker":
            failures.append(
                f"{name} dispatch has caller={hits[-1]['parent_agent'] or '<none>'}, expected asgard-worker "
                "(the hook did not see the calling agent)"
            )

    if len(picked) == len(SPECIALISTS):
        spans = [span(picked[name]) for name in SPECIALISTS]
        overlap = min(e for _, e in spans) - max(s for s, _ in spans)
        unsettled = [name for name in SPECIALISTS if not picked[name]["settled_at"]]
        print(
            f"  overlap: {overlap:.1f}s"
            + (f" (provisional — {', '.join(unsettled)} still running)" if unsettled else "")
        )
        if unsettled:
            failures.append(
                "still running: " + ", ".join(unsettled) + " — a dispatch that has not settled has no end, "
                "and borrowing the current time for it makes any two live dispatches look concurrent"
            )
        elif overlap <= 0:
            failures.append(f"the two specialists did not run at the same time (overlap {overlap:.1f}s)")

    for line in failures:
        print("FAIL:", line)
    if failures:
        return 1
    print("PASS: worker fanned out to freyja and thor, and they ran concurrently")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
