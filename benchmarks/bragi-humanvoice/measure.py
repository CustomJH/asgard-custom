#!/usr/bin/env python3
"""Bragi 판정기 실측 — 상류 라벨 코퍼스(Part A) + held-out 사람 코퍼스(Part B).

Part A  상류 저장소의 before/after 라벨로 재현율·특이도를 잰다. 패턴 출처와 코퍼스 출처가
        같으므로 **이식률에 가깝다** — 일반화 근거로 쓰지 않는다.
Part B  이 저장소가 실제로 축적한 사람 글(커밋 본문·메모리 문서·모듈 독스트링)에서
        오탐률을 잰다. 라벨 출처가 판정기와 무관하므로 이쪽이 결정에 쓰는 숫자다.
        게이트가 여기서 울리면 사용자는 답 대신 안내문을 받는다 = 실제 비용.

사용: uv run python benchmarks/bragi-humanvoice/measure.py [--corpus corpus.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))
from asgard import bragi  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def flagged(text: str) -> bool:
    """게이트 발동 여부 — 재작성을 트리거하는 조건과 같아야 의미가 있다."""
    return bool(bragi.tells(text))


# ── Part A — 상류 라벨 코퍼스
def part_a(corpus: list[dict], scope: str = "ai-tell") -> dict:
    """scope='ai-tell' 만 채점한다 — 상류의 맞춤법·표기 패턴은 브라기의 대상이 아니다."""
    corpus = [r for r in corpus if r.get("scope", "ai-tell") == scope]
    langs = sorted({r["lang"] for r in corpus})
    out = {}
    for lang in [*langs, "ALL"]:
        rows = corpus if lang == "ALL" else [r for r in corpus if r["lang"] == lang]
        ai = [r for r in rows if r["label"] == "ai"]
        hu = [r for r in rows if r["label"] == "human"]
        tp = sum(1 for r in ai if flagged(r["text"]))
        fp = sum(1 for r in hu if flagged(r["text"]))
        out[lang] = {
            "ai_n": len(ai),
            "human_n": len(hu),
            "recall": tp / len(ai) if ai else None,
            "false_positive": fp / len(hu) if hu else None,
        }
    return out


# ── Part B — held-out 사람 코퍼스 (이 저장소가 실제로 쌓아 온 글)
def _commit_bodies(limit: int = 400) -> list[str]:
    """커밋 본문 — 사람이 쓴 한국어 기술 산문. 제목 줄(gitmoji)은 제외한다."""
    raw = subprocess.run(
        ["git", "-C", ROOT, "log", f"-{limit}", "--no-merges", "--pretty=format:%b%x00"],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    out = []
    for body in raw.split("\x00"):
        body = "\n".join(ln for ln in body.splitlines() if not ln.startswith(("Co-Authored", "Signed-off")))
        if len(body.strip()) >= 120:
            out.append(body.strip())
    return out


def _memory_docs() -> list[str]:
    """오딘의 개인 메모리 — 사람이 쓴 글 (frontmatter 제거)."""
    home = os.path.expanduser("~/.claude/projects")
    out = []
    for base, _, files in os.walk(home):
        if not base.endswith("memory"):
            continue
        for name in files:
            if not name.endswith(".md") or name == "MEMORY.md":
                continue
            text = open(os.path.join(base, name), encoding="utf-8").read()
            text = re.sub(r"^---.*?^---", "", text, flags=re.S | re.M).strip()
            if len(text) >= 120:
                out.append(text)
    return out


def _docstrings() -> list[str]:
    """모듈 독스트링 — 사람이 쓴 설계 산문 (코드 아님)."""
    import ast

    out = []
    for base, _, files in os.walk(os.path.join(ROOT, "src", "asgard")):
        for name in files:
            if not name.endswith(".py"):
                continue
            try:
                tree = ast.parse(open(os.path.join(base, name), encoding="utf-8").read())
            except Exception:
                continue
            doc = ast.get_docstring(tree)
            if doc and len(doc) >= 120:
                out.append(doc)
    return out


def _tracked_prose() -> list[str]:
    """저장소가 추적하는 .md 산문 — Trinity 완료 게이트가 실제로 검사하는 경로다."""
    names = subprocess.run(
        ["git", "-C", ROOT, "ls-files", "*.md"], capture_output=True, text=True, timeout=60
    ).stdout.split()
    # 벤더링된 상류 스킬 자산과 archive 는 이 저장소 저자의 글이 아니다 — held-out 표본이 아니라 오염이다
    skip = (".asgard/", "archive/", "src/asgard/assets/skill_plugins/")
    out = []
    for rel in names:
        if rel.startswith(skip):
            continue
        try:
            text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        except Exception:
            continue
        for para in (p.strip() for p in text.split("\n\n")):
            if len(para) >= 150:
                out.append(para)
    return out


def part_b() -> dict:
    sources = {
        "commit bodies": _commit_bodies(),
        "tracked .md prose": _tracked_prose(),
        "memory docs": _memory_docs(),
        "module docstrings": _docstrings(),
    }
    out = {}
    for name, texts in sources.items():
        if not texts:
            out[name] = {"n": 0}
            continue
        hits = [(t, bragi.tells(t)) for t in texts]
        fired = [(t, f) for t, f in hits if f]
        out[name] = {
            "n": len(texts),
            "false_positive": len(fired) / len(texts),
            "grades": {g: sum(1 for _, f in hits if bragi.grade(f) == g) for g in ("A", "B", "C", "D")},
            "top_ids": _top_ids(fired),
            "examples": [{"id": f[0].id, "sample": f[0].sample, "text": t[:110]} for t, f in fired[:5]],
        }
    return out


def _top_ids(fired: list) -> dict:
    counts: dict[str, int] = {}
    for _, findings in fired:
        for f in findings:
            counts[f.id] = counts.get(f.id, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:6])


def _pct(x) -> str:
    return "  n/a" if x is None else f"{x:5.1%}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=os.path.join(os.path.dirname(__file__), "corpus.json"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    corpus = json.load(open(args.corpus, encoding="utf-8"))
    a, b = part_a(corpus), part_b()
    if args.json:
        print(json.dumps({"part_a": a, "part_b": b}, ensure_ascii=False, indent=1))
        return

    print("Part A — upstream labeled pairs (recall = AI text caught, FP = human text wrongly caught)")
    print(f"  {'lang':5s} {'AI n':>5s} {'human n':>8s} {'recall':>8s} {'FP':>8s}")
    for lang, r in a.items():
        print(f"  {lang:5s} {r['ai_n']:5d} {r['human_n']:8d} {_pct(r['recall']):>8s} {_pct(r['false_positive']):>8s}")
    print("\n  By sample length (the gate reads whole reports, not isolated sentences):")
    ai = [r for r in corpus if r["label"] == "ai" and r.get("scope", "ai-tell") == "ai-tell"]
    for lo, hi, name in ((0, 100, "< 100 chars"), (100, 250, "100-250 chars"), (250, 10**9, "> 250 chars")):
        rows = [r for r in ai if lo <= len(r["text"]) < hi]
        if rows:
            hit = sum(1 for r in rows if flagged(r["text"]))
            print(f"    {name:14s} n={len(rows):3d}  recall={hit / len(rows):5.1%}")
    grammar = [r for r in corpus if r.get("scope") == "grammar" and r["label"] == "ai"]
    if grammar:
        hit = sum(1 for r in grammar if flagged(r["text"]))
        print("\n  Out of scope, reported for completeness: upstream spelling/typography rules")
        print(f"    n={len(grammar)}  caught={hit / len(grammar):.1%} — Bragi is a voice gate, not a spell checker.")
    print("\n  Leakage note: Bragi's patterns were ported from these same repos.")
    print("  Read this as port fidelity, not generalization. Part B is the held-out number.\n")

    print("Part B — held-out human corpus written by this project's author (FP = gate wrongly fires)")
    for name, r in b.items():
        if not r.get("n"):
            print(f"  {name:20s} (no samples)")
            continue
        grades = " ".join(f"{g}:{n}" for g, n in r["grades"].items() if n)
        print(f"  {name:20s} n={r['n']:4d}  FP={_pct(r['false_positive'])}  grades[{grades}]")
        if r["top_ids"]:
            print(f"  {'':20s} fired: {', '.join(f'{k}×{v}' for k, v in r['top_ids'].items())}")
    for name, r in b.items():
        for ex in r.get("examples", [])[:2]:
            print(f"\n  ! {name} · {ex['id']} · {ex['sample']!r}\n    {ex['text']}…")


if __name__ == "__main__":
    main()
