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


def _part_b_sources() -> dict:
    return {
        "commit bodies": _commit_bodies(),
        "tracked .md prose": _tracked_prose(),
        "memory docs": _memory_docs(),
        "module docstrings": _docstrings(),
    }


def part_b(sources: dict) -> dict:
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


# ── 문장 완결성 축 — 채택한 절반(연결어미 종결)과 기각한 절반(명사구 종결)을 한 코퍼스에서 잰다.
#
# 기각한 쪽의 판정기는 배송되지 않으므로 여기 산다. 게이트에 안 들어간 이유를 문서가 주장만
# 하고 다시 못 재면, 다음 사람이 같은 축을 같은 값으로 또 시도한다.
BROKEN_KO = (
    "먼저 설정 파일을 읽고.",
    "값이 없으면 기본값을 쓰면.",
    "그 다음 캐시를 지우도록.",
    "다음 단계는 훅을 배포하고.",
    "그 뒤에 게이트를 다시 돌리며.",
    "테스트를 세 번 돌렸지만.",
    "실패는 재현되지 않았으므로.",
    "원인을 확인하는데.",
    "로그를 남기면서.",
    "값을 비교하니까.",
)
_BROKEN_PAD = "이 변경은 세 파일을 건드린다. 결과는 로그에 남는다. "
# 서술어 + 종결어미로 끝나는 마지막 음절. 이 밖에서 끝나면 명사구·부사구 종결로 센다.
_FINAL_SYLLABLES = set("다요죠까라자오네지군야어아여소걸게마니냐나")
_NOUN_THRESHOLDS = (0.20, 0.25, 0.30, 0.35, 0.40, 0.50)


def _noun_ending_ratio(text: str) -> float | None:
    """명사구로 끝난 문장의 비율 — 배송 안 된 판정기. 문장이 6개 미만이면 안 잰다."""
    sents = bragi._ko_sentences(bragi.lintable_spans(text))
    if len(sents) < 6:
        return None
    return sum(1 for s in sents if s[-1] not in _FINAL_SYLLABLES) / len(sents)


def sentence_completion(sources: dict) -> dict:
    """채택한 축의 재현율·오탐과 사각, 그리고 기각한 축의 임계별 오탐.

    사각을 여기서 같이 재는 이유는 한 번 틀렸기 때문이다 — 문서가 쉼표 면제분이라고 적은 값이
    실은 쉼표와 대시의 합집합이었고, 판정이 그것을 잡았다 (26-08-19)."""
    texts = [t for rows in sources.values() for t in rows]
    sents = [s for t in texts for s in bragi._ko_sentences(bragi.lintable_spans(t))]
    exempt = sum(1 for s in sents if bragi.stats._CONTINUATION.search(s))
    with_comma = sum(1 for s in sents if "," in s)  # 대시·콜론을 함께 문 문장도 포함한다
    fired = sum(1 for t in texts if any(f.id == "KO-unfinished-sentence" for f in bragi.tells(t)))
    caught = sum(
        1
        for b in BROKEN_KO
        if any(f.id == "KO-unfinished-sentence" for f in bragi.tells(_BROKEN_PAD + b + " 확인은 끝났다."))
    )
    ratios = sorted(r for r in (_noun_ending_ratio(t) for t in texts) if r is not None)
    return {
        "corpus_n": len(texts),
        "connective_false_positive": fired,
        "connective_recall": f"{caught}/{len(BROKEN_KO)}",
        "korean_sentences": len(sents),
        "exempt_by_continuation": exempt,
        "sentences_with_comma": with_comma,
        "noun_ending_n": len(ratios),
        "noun_ending_false_positive": {
            f"{thr:.2f}": sum(1 for r in ratios if r > thr) / len(ratios) if ratios else None
            for thr in _NOUN_THRESHOLDS
        },
    }


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
    sources = _part_b_sources()
    a, b, c = part_a(corpus), part_b(sources), sentence_completion(sources)
    if args.json:
        print(json.dumps({"part_a": a, "part_b": b, "sentence_completion": c}, ensure_ascii=False, indent=1))
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

    print("\nSentence completion — the shipped half and the rejected half, on the same corpus")
    print(
        f"  KO-unfinished-sentence  fires on {c['connective_false_positive']} of {c['corpus_n']} human "
        f"samples · catches {c['connective_recall']} hand-written broken sentences"
    )
    ks, ex, ca = c["korean_sentences"], c["exempt_by_continuation"], c["sentences_with_comma"]
    print(
        f"  blind spot              {ex} of {ks} Korean sentences ({ex / ks:.1%}) carry a dash, comma, or "
        f"colon and are exempt — of those {ks}, {ca} carry a comma ({ca / ks:.1%})"
    )
    print(f"  noun-phrase endings     not shipped — misfire on {c['noun_ending_n']} samples by threshold:")
    print("    " + "  ".join(f"{thr}={_pct(fp)}" for thr, fp in c["noun_ending_false_positive"].items()))


if __name__ == "__main__":
    main()
