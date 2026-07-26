#!/usr/bin/env python3
"""상류 저장소의 **라벨된** before/after 쌍을 벤치 코퍼스로 추출한다.

내가 쓴 문장으로 내 판정기를 채점하면 아무것도 증명하지 못한다. 그래서 라벨은 전부 남의 것이다:
  ko  DaleSeo/korean-skills          examples/before-N.md · after-N.md
  en  blader/humanizer (31k★)        SKILL.md 의 **Before:** / **After:** 블록
  vi  longhang2004/vietnamese-humanizer  patterns/*.yml 의 bad_examples · good_examples
  ja  gonta223/humanizer-ja          SKILL.md 의 NG例 / OK例

한계 (정직하게): 브라기의 패턴 목록도 같은 저장소들에서 왔다. 그래서 이 코퍼스의 재현율은
"상류 코퍼스를 얼마나 이식했는가"에 가깝고, 새 분포에 대한 일반화 근거가 아니다.
일반화 근거는 held-out 사람 코퍼스(measure.py 의 Part B)와 라이브 A/B(live_ab.py)가 맡는다.

사용: python build_corpus.py <clone_dir> [--out corpus.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("> ", " ")).strip()


def korean_skills(base: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(base, "korean-skills/skills/humanizer/examples/*.md"))):
        name = os.path.basename(path)
        label = "ai" if name.startswith("before") else "human"
        body = re.sub(r"^#.*$", "", open(path, encoding="utf-8").read(), flags=re.M)
        for para in (p.strip() for p in body.split("\n\n")):
            if len(para) >= 80 and not para.startswith(("-", "*", "|", ">")):
                rows.append(
                    {
                        "lang": "ko",
                        "label": label,
                        "src": f"korean-skills/{name}",
                        "scope": "ai-tell",
                        "text": _clean(para),
                    }
                )
    return rows


def blader(base: str) -> list[dict]:
    """**Before:** / **After:** 다음에 오는 인용 블록을 짝으로 뽑는다."""
    path = os.path.join(base, "humanizer/SKILL.md")
    if not os.path.exists(path):
        return []
    rows, label, buf = [], None, []

    def flush():
        if label and buf:
            text = _clean(" ".join(buf))
            if len(text) >= 60:
                rows.append({"lang": "en", "label": label, "src": "blader/humanizer", "scope": "ai-tell", "text": text})

    for line in open(path, encoding="utf-8"):
        m = re.match(r"\*\*(Before|After)\b[^*]*:?\*\*", line.strip())
        if m:
            flush()
            label, buf = ("ai" if m.group(1) == "Before" else "human"), []
            continue
        if line.startswith(">"):
            buf.append(line[1:].strip())
        elif buf:
            flush()
            label, buf = None, []
    flush()
    return rows


def vietnamese(base: str) -> list[dict]:
    """patterns/*.yml — 들여쓰기 기반 스캔 (yaml 의존을 추가하지 않는다).

    scope 를 함께 기록한다. 상류의 grammar.yml·style.yml 은 오탈자·표기 규칙("sát nhập"→
    "sáp nhập", 쉼표 앞 공백)이고 브라기의 대상이 아니다 — 브라기는 맞춤법 검사기가 아니라
    기계 문체 판정기다. 섞어서 채점하면 재현율이 범위 밖 표본 때문에 깎인다."""
    rows = []
    for path in sorted(glob.glob(os.path.join(base, "vi-hum/patterns/*.yml"))):
        family = os.path.splitext(os.path.basename(path))[0]
        scope = "ai-tell" if family in ("humanizer", "translationese") else "grammar"
        label = None
        for line in open(path, encoding="utf-8"):
            if re.match(r"^\s{2}(bad|good)_examples:", line):
                label = "ai" if "bad_" in line else "human"
                continue
            if re.match(r"^\s{2}\w", line):  # 다른 최상위 필드로 넘어감
                label = None
            m = re.match(r"^\s+-?\s*text:\s*(.+)$", line)
            if m and label:
                text = _clean(m.group(1).strip("'\""))
                if len(text) >= 30:
                    rows.append(
                        {"lang": "vi", "label": label, "src": "vietnamese-humanizer", "scope": scope, "text": text}
                    )
    return rows


def japanese(base: str) -> list[dict]:
    path = os.path.join(base, "ja-hum/SKILL.md")
    if not os.path.exists(path):
        return []
    rows = []
    for label, marker in (("ai", "NG例"), ("human", "OK例")):
        for m in re.finditer(rf"\*\*{marker}[^*]*:?\*\*\s*\n+「(.+?)」", open(path, encoding="utf-8").read(), re.S):
            text = _clean(m.group(1))
            if len(text) >= 30:
                rows.append({"lang": "ja", "label": label, "src": "humanizer-ja", "scope": "ai-tell", "text": text})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clones", help="상류 저장소들을 clone 해 둔 디렉토리")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "corpus.json"))
    args = ap.parse_args()

    rows = korean_skills(args.clones) + blader(args.clones) + vietnamese(args.clones) + japanese(args.clones)
    seen, unique = set(), []
    for r in rows:
        if r["text"] not in seen:
            seen.add(r["text"])
            unique.append(r)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(unique, fh, ensure_ascii=False, indent=1)

    by: dict[tuple[str, str], int] = {}
    for r in unique:
        by[(r["lang"], r["label"])] = by.get((r["lang"], r["label"]), 0) + 1
    print(f"{len(unique)} samples → {args.out}")
    for key in sorted(by):
        print(f"  {key[0]:3s} {key[1]:6s} {by[key]}")


if __name__ == "__main__":
    main()
