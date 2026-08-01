#!/usr/bin/env python3
"""map 숏컷 벤치 — 지도 주입면이 실제로 홉을 줄이는가 (0-LLM).

메모리 주입은 `benchmarks/shortcut-recall/`에서 토큰 −67%·벽시계 −69%로 못 박혔는데 지도
주입은 그 자를 한 번도 안 대봤다. 이 하네스가 그 자다.

**LLM을 부르지 않는다.** 지도 숏컷의 이득은 "에이전트가 grep 사다리를 안 타는 것"이고, 그 앞에
반드시 성립해야 하는 조건은 결정론적이다 — 질의에 맞는 명령이 주입면에 **뜨는가**, 그리고 **맞는
것이** 뜨는가. 이 앞단이 무너지면 LLM A/B는 잴 것이 없다. 실제 턴 절감은 여기가 녹색이 된 뒤에
`shortcut-recall` 형상으로 따로 잰다.

    python benchmarks/map-shortcut/harness.py [--root PATH] [--json OUT.jsonl]

판정 기준:
- 라우팅 발화율 — 명령이 있어야 할 질의에서 라우팅 블록이 뜬 비율
- 라우팅 정확도 — 뜬 블록의 상위 3개 안에 기대 명령이 있는 비율
- 침묵 정확도 — 명령이 없어야 할 질의에서 조용했는지 (오발화는 홉을 늘린다)
- 예산 — 주입면 바이트와 가장 큰 단일 행 (한 행이 예산을 독점하면 나머지가 잘린다)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from asgard.map_context import CONTEXT_BUDGET, build_map_context  # noqa: E402

ROUTE_MARKER = "핸들러를 grep 하기 전에"
SEED_MARKER = "asgard map impact"


def observe(root: Path, query: str) -> dict:
    """질의 하나를 주입면에 통과시키고 관측값만 뽑는다 — 판정은 호출자가 한다."""
    context = build_map_context(root, query)
    lines = context.text.splitlines()
    routed = [line[3:].split("`", 1)[0] for line in lines if line.startswith("- `asgard ")]
    entry_rows = [line for line in lines if line.startswith("- `") and not line.startswith("- `asgard ")]
    return {
        "query": query,
        "routed": routed if ROUTE_MARKER in context.text else [],
        "seeded": SEED_MARKER in context.text,
        "entries": len(entry_rows),
        "bytes": len(context.text.encode("utf-8")),
        "widest_row": max((len(line.encode("utf-8")) for line in entry_rows), default=0),
    }


def judge(observed: dict, expect: str | None) -> dict:
    """기대와 대조 — 기대가 None이면 "조용해야 한다"가 기대다."""
    routed = observed["routed"]
    if expect is None:
        return observed | {"expect": None, "verdict": "quiet" if not routed else "false-fire"}
    if not routed:
        return observed | {"expect": expect, "verdict": "silent"}
    hit = any(command.startswith(expect) for command in routed)
    # 상위 3개 안 적중과 1위 적중을 갈라 센다. 셋을 다 읽는 것과 첫 줄만 보고 치는 것은 홉이 다르다.
    verdict = "hit" if routed[0].startswith(expect) else "hit@3" if hit else "miss"
    return observed | {"expect": expect, "verdict": verdict, "top": routed[0]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(REPO), help="측정할 저장소 (기본: 이 저장소)")
    parser.add_argument("--json", dest="out", default="", help="런당 1행 jsonl 로 append")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not (root / ".asgard" / "map" / "PROJECT.md").exists():
        print(f"지도가 없다: {root} — 먼저 `asgard map update && asgard map scan`", file=sys.stderr)
        return 2

    cases = json.loads((Path(__file__).parent / "queries.json").read_text(encoding="utf-8"))
    results = [judge(observe(root, case["query"]), case["expect"]) for case in cases]

    width = max(len(row["query"]) for row in results)
    print(f"\nmap 숏컷 벤치 — {root.name}\n")
    marks = {"hit": "OK", "hit@3": "@3", "quiet": "OK", "miss": "MISS", "silent": "SILENT", "false-fire": "FIRE"}
    for row in results:
        target = row.get("top") or ("(조용)" if not row["routed"] else "")
        print(f"  {marks[row['verdict']]:7} {row['query']:<{width}}  {target}")

    routable = [row for row in results if row["expect"] is not None]
    quiet = [row for row in results if row["expect"] is None]
    fired = [row for row in routable if row["routed"]]
    top1 = [row for row in routable if row["verdict"] == "hit"]
    top3 = [row for row in routable if row["verdict"] in {"hit", "hit@3"}]
    widest = max(row["widest_row"] for row in results)
    summary = {
        "queries": len(results),
        "fire_rate": round(len(fired) / len(routable), 3) if routable else 0.0,
        "top1": round(len(top1) / len(routable), 3) if routable else 0.0,
        "top3": round(len(top3) / len(routable), 3) if routable else 0.0,
        "quiet_accuracy": round(sum(row["verdict"] == "quiet" for row in quiet) / len(quiet), 3) if quiet else 0.0,
        "seed_rate": round(sum(row["seeded"] for row in results) / len(results), 3),
        "median_bytes": sorted(row["bytes"] for row in results)[len(results) // 2],
        "budget": CONTEXT_BUDGET,
        "widest_row_bytes": widest,
    }
    print(
        f"\n  라우팅 발화 {summary['fire_rate']:.0%} · 1위 적중 {summary['top1']:.0%}"
        f" · 상위3 적중 {summary['top3']:.0%} · 침묵 정확도 {summary['quiet_accuracy']:.0%}"
        f" · 시드 {summary['seed_rate']:.0%}"
        f"\n  주입 median {summary['median_bytes']}B / {CONTEXT_BUDGET}B · 최대 행 {widest}B\n"
    )
    if args.out:
        with open(args.out, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"summary": summary, "results": results}, ensure_ascii=False) + "\n")
    # 정확도가 발화율보다 중요하다 — 틀린 명령은 턴을 아끼는 게 아니라 하나 더 쓰게 만든다.
    # 오발화는 하나도 봐주지 않는다: 없는 명령을 들이미는 것이 침묵보다 나쁘다.
    return 0 if summary["top3"] >= 0.7 and summary["quiet_accuracy"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
