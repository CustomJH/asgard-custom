"""근거 대조 벤치 — 어간 하한(`memory/recall.py:_stem_floor`)을 재는 자.

**왜 따로 서는가.** 회수 하니스(`benchmarks/longmemeval/`)는 `query()` 만 지나가느라
`_stem_hit` 을 한 번도 안 부른다 (계수기 실측 26-08-01: S 15문항 호출 0회). 그런데 하한이
실제로 일하는 자리는 회수가 아니라 **근거 대조와 극성 판정**이다:

  · `memory/pattern.py:_grounded` — 관측(explicit)이 인용 턴에 실제로 있는가
  · `memory/norn.py:_insight_grounding` — 통찰이 출처에 실제로 있는가 (자동 승격의 문지기)
  · `memory/norn.py:_spans` — 그 낱말이 **어디에** 있는가 (극성 판정의 좌표)

`_stem_floor` 독스트링이 값을 못 옮긴 이유로 "재는 자가 없어서"를 든다. 이 파일이 그 자다.

**제품 코드는 안 고친다.** 하한은 주입으로 바꾼다 — `recall.stems._stem_floor` 와
`norn._stem_floor` 두 자리를 갈아 끼운다. 두 자리인 이유: `norn` 이 `from .recall import
_stem_floor` 로 **이름을 자기 모듈에 복사**해 오므로 `recall` 쪽만 갈면 `_spans` 는 옛 식을
계속 쓴다 (그 갈라짐이야말로 `_stem_floor` 독스트링이 막으려던 것이라, 벤치가 먼저 그 실수를
저지르면 안 된다).

실행: .venv/bin/python benchmarks/grounding/harness.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

HERE = os.path.dirname(os.path.abspath(__file__))


# ── 하한 후보(arm) ────────────────────────────────────────────────────────────
#
# 숫자만 훑지 않는다. 현행 식 `max(2, (len+1)//2)` 에는 손잡이가 둘 있고(절대 하한·비율),
# 게다가 **문자 체계마다 옳은 값이 다르다**는 가설이 있다: 한국어는 조사·어미가 낱말 뒤에
# 1~2자 붙고, 영어 굴절은 -s/-ed/-ing 로 1~3자 붙는다. 붙는 길이가 낱말 길이에 안 비례하는데
# 현행 식은 비례로 깎는다 — 긴 영어 낱말일수록 과하게 깎이는 이유다 (`authentication` 은
# 7자까지 깎여 `author` 를 삼킬 뻔한 자리에 선다).


def floor_default(word: str) -> int:
    """현행 제품 값 — `max(2, (len+1)//2)`."""
    return max(2, (len(word) + 1) // 2)


def floor_min(n: int):
    """절대 하한만 올린다 — `max(n, (len+1)//2)`."""

    def _f(word: str) -> int:
        return max(n, (len(word) + 1) // 2)

    return _f


def floor_ratio(r: float):
    """비율만 올린다 — `max(2, ceil(len*r))`."""

    def _f(word: str) -> int:
        return max(2, math.ceil(len(word) * r))

    return _f


def floor_suffix(n: int):
    """접미 n자까지만 깎는다 — `max(2, len-n)`. 굴절 길이가 낱말 길이에 안 비례한다는 가설."""

    def _f(word: str) -> int:
        return max(2, len(word) - n)

    return _f


def floor_script(latin_suffix: int):
    """문자 체계로 가른다 — 라틴은 접미 n자, 그 밖(한글)은 현행 식 그대로.

    한글을 안 건드리는 이유는 아래 표가 말한다: 한국어에서 `배포를`(진짜)과 `저장소`(가짜)는
    **둘 다 3자→2자**다. 길이만으로는 원리적으로 못 가른다."""

    def _f(word: str) -> int:
        return max(2, len(word) - latin_suffix) if word.isascii() else max(2, (len(word) + 1) // 2)

    return _f


# 조사·어미 목록. `memory/recall.py:query` 가 **이미 들고 있는** 목록을 옮겨 오고(거기서는
# FTS 질의 어간 후보를 만드는 데 쓴다) 용언 활용과 복합 조사를 더했다. 회수 경로는 한국어를
# 형태로 다루는데 근거 대조 경로만 길이로 다룬다 — 그 비대칭이 이 arm 의 가설이다.
_KO_SUFFIXES = (
    "에서는",
    "으로는",
    "에게는",
    "한테는",
    "으로",
    "에서",
    "에게",
    "한테",
    "처럼",
    "까지",
    "부터",
    "에는",
    "에도",
    "로는",
    "이나",
    "라도",
    "마다",
    "밖에",
    "조차",
    "께서",
    "이라",
    "라고",
    "이며",
    "한다",
    "했다",
    "하고",
    "하는",
    "하며",
    "하지",
    "된다",
    "됐다",
    "되고",
    "되는",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "에",
    "의",
    "로",
    "과",
    "와",
    "도",
    "만",
)
# 영어 굴절·파생 접미. 길이에 안 비례한다는 것이 요점이다 — `authorization` 은 7자를 떼야 하고
# `deploys` 는 1자만 떼야 한다. 현행 절반 규칙은 둘 다 절반으로 깎는다.
_EN_SUFFIXES = (
    "ization",
    "ation",
    "ments",
    "tion",
    "ment",
    "ing",
    "ers",
    "ize",
    "ized",
    "ed",
    "er",
    "es",
    "s",
    "d",
)


def floor_morphology(word: str) -> int:
    """어미·접미 **목록**으로 깎는다 — 목록에 없으면 완전 일치.

    가설: 하한이 틀린 게 아니라 **자가 틀렸다**. 붙는 형태소의 길이는 낱말 길이에 안 비례하는데
    `(len+1)//2` 는 비례로 깎는다. 그래서 짧은 낱말은 덜 깎여야 할 것이 더 깎이고
    (`저장소`→`저장`), 긴 낱말은 훨씬 더 깎인다 (`authentication`→`authent`).

    이 규칙은 `_stem_floor` 의 자리에 그대로 앉는다 — `_stem_hit` 은 낱말 전체부터 하한까지
    한 글자씩 줄여 보므로, 하한을 "형태소를 뗀 길이"로 두면 완전 일치와 어간 일치 **둘만**
    시도한다. 사이의 임의 절단이 사라진다.

    남는 대가는 목록의 성질이다: 한 글자 조사(`도`·`로`)는 진짜 명사의 끝 글자이기도 해서
    `가속도`→`가속`을 만든다. 그 대가는 corpus.json 에 두 건 심어 표에 드러나게 했다."""
    suffixes = _EN_SUFFIXES if word.isascii() else _KO_SUFFIXES
    for suffix in suffixes:  # 긴 것부터 — `에서는` 을 `는` 으로 먼저 떼면 남는 말이 다르다
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            return len(word) - len(suffix)
    return len(word)


ARMS: list[tuple[str, object]] = [
    ("default(min2)", floor_default),
    ("min3", floor_min(3)),
    ("min4", floor_min(4)),
    ("min5", floor_min(5)),
    ("ratio0.60", floor_ratio(0.60)),
    ("ratio0.75", floor_ratio(0.75)),
    ("suffix3", floor_suffix(3)),
    ("suffix2", floor_suffix(2)),
    ("script(latin-suffix3)", floor_script(3)),
    ("script(latin-suffix2)", floor_script(2)),
    ("exact", len),  # 하한 = 낱말 전체. 어간 일치를 끄는 것과 같다 (도입 전 거동의 하계)
    ("morphology(목록)", floor_morphology),  # 하한값이 아니라 하한 **식**을 바꾸는 arm
]


# 하한을 **부르는** 모듈들. 재수출한 파사드가 아니라 호출부가 사는 자리여야 한다 —
# `norn/insight.py` 는 import 시점에 `_stem_floor` 를 자기 모듈 전역으로 복사하므로,
# 패키지 파사드(`norn._stem_floor`)를 바꿔도 `_spans` 는 원본을 계속 부른다.
_FLOOR_CALLERS = (
    ("asgard.memory.recall.stems", "_stem_hit 이 부르는 자리"),
    ("asgard.memory.norn.insight", "_spans 가 부르는 자리"),
)


def install(fn) -> None:
    """하한을 부르는 **모든** 자리에 꽂는다 — 하나라도 빠지면 계약 열이 조용히 거짓이 된다.

    26-08-13 평가가 그 자리를 찾았다: 이 하네스가 파사드(`norn._stem_floor`)에 꽂고 있어서
    `_spans` 는 늘 원본 하한으로 돌았고, 그런데도 REPORT 의 계약 칸은 12개 arm 전부 `ok` 로
    적혀 있었다. 다시 돌리니 11개가 깨져 있었다 — 벤치가 자기가 안 바꾼 것을 바꿨다고 적은
    것이다. 이름이 없으면 여기서 죽는다: 소유 자리가 옮겨졌다는 뜻이고, 그때 조용히 넘어가면
    같은 거짓이 다시 쌓인다."""
    import importlib

    for module_name, role in _FLOOR_CALLERS:
        module = importlib.import_module(module_name)
        if not hasattr(module, "_stem_floor"):
            raise RuntimeError(f"{module_name}._stem_floor 가 없다 ({role}) — 하한의 소유 자리가 옮겨졌다")
        # 모듈을 이름으로 들고 왔으므로 속성도 이름으로 꽂는다 — 점 표기로 적으면 판독기가
        # 그 이름을 `ModuleType` 에서 찾다가 못 찾는다.
        setattr(module, "_stem_floor", fn)


# ── 지표 ─────────────────────────────────────────────────────────────────────


def score(pairs: list[tuple[bool, bool]]) -> dict:
    """(예측, 정답) 쌍 → 정밀도·재현율·F1·정확도.

    양성 = "근거가 있다"고 판정한 것. 정밀도가 떨어진다는 말은 **없는 근거를 셌다**는 뜻이고,
    그건 허구가 정본으로 승격되는 경로다. 재현율이 떨어진다는 말은 진짜 관측이 버려진다는
    뜻이다. 하한을 옮기는 일은 언제나 이 둘의 맞바꿈이라 하나만 적으면 거짓말이 된다."""
    tp = sum(1 for pred, want in pairs if pred and want)
    fp = sum(1 for pred, want in pairs if pred and not want)
    fn = sum(1 for pred, want in pairs if not pred and want)
    tn = sum(1 for pred, want in pairs if not pred and not want)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall_ = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall_ / (precision + recall_) if precision + recall_ else 0.0
    # F0.5 — 정밀도에 두 배 무게. 이 판정의 두 오류는 값이 다르다: 오탐은 **허구를 정본으로**
    # 올리고(`INSIGHT_AUTO_FLOOR` 는 사람 승인을 건너뛴다), 오탈락은 사람이 한 번 더 보게
    # 할 뿐이다. F1 로 고르면 그 비대칭이 지워진다.
    f_half = (1.25 * precision * recall_ / (0.25 * precision + recall_)) if precision + recall_ else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall_, 4),
        "f1": round(f1, 4),
        "f0.5": round(f_half, 4),
        "accuracy": round((tp + tn) / len(pairs), 4) if pairs else 0.0,
    }


def word_level(cases: list[dict]) -> dict:
    """낱말 층 — `_stem_hit` 이 낱말 하나를 두고 내리는 판정. 하한이 직접 닿는 자리다."""
    from asgard.memory import norn, recall

    pairs: list[tuple[bool, bool]] = []
    by_lang: dict[str, list[tuple[bool, bool]]] = {}
    misses: list[dict] = []
    span_disagreements: list[str] = []
    for case in cases:
        word, hay, want = case["word"], case["haystack"], bool(case["expect"])
        pred = recall._stem_hit(word, hay)
        pairs.append((pred, want))
        by_lang.setdefault(str(case.get("lang") or "?"), []).append((pred, want))
        if pred != want:
            misses.append({"word": word, "haystack": hay, "expect": want, "got": pred, "note": case.get("note", "")})
        # 계약 검사 — 근거 검사가 찾은 낱말은 극성도 찾아야 한다 (`_spans` 독스트링).
        # 하한을 옮기면서 이게 깨지면 그 arm 은 수치가 좋아도 못 쓴다.
        if bool(norn._spans(word, hay)) != pred:
            span_disagreements.append(f"{word} ⊄ {hay}")
    return {
        "overall": score(pairs),
        "by_lang": {lang: score(sub) for lang, sub in sorted(by_lang.items())},
        "span_contract_broken": span_disagreements,
        "misses": misses,
    }


def claim_level(cases: list[dict]) -> dict:
    """주장 층 — 낱말 판정이 모여 만드는 **실제 게이트**의 결정.

    제품에 문턱이 셋 있고 셋 다 같은 점수를 다르게 읽는다. 낱말 정밀도가 조금 나빠도 문턱이
    걸러 주면 게이트는 멀쩡할 수 있고, 반대로 낱말은 멀쩡한데 문턱 위치 때문에 게이트만
    무너질 수도 있다 — 그래서 두 층을 따로 잰다."""
    from asgard.memory import norn, pattern

    floors = {
        "insight_admit": norn.INSIGHT_GROUNDING_FLOOR,  # 통찰이 저장될 자격
        "insight_auto": norn.INSIGHT_AUTO_FLOOR,  # 사람 승인 없이 정본이 될 자격
        "observation": pattern.GROUNDING_FLOOR,  # 관측(explicit)이 저장될 자격
    }
    gate_pairs: dict[str, list[tuple[bool, bool]]] = {name: [] for name in floors}
    detail: list[dict] = []
    for case in cases:
        sources = [({"title": title}, body) for title, body in case["sources"]]
        total, per_source = norn._insight_grounding(case.get("title", ""), case["text"], sources)
        # 관측 경로는 턴 모양(request/response)을 받는다 — 같은 본문을 그 모양으로 넘긴다.
        turns = [{"request": body, "response": ""} for _title, body in case["sources"]]
        observed = pattern._grounded(case["text"], turns)
        want = bool(case["expect"])
        scores = {"insight_admit": total, "insight_auto": total, "observation": observed}
        for name, floor in floors.items():
            gate_pairs[name].append((scores[name] >= floor, want))
        detail.append(
            {
                "id": case["id"],
                "expect": want,
                "insight_grounding": round(total, 4),
                "observation_grounding": round(observed, 4),
                "per_source": [round(v, 4) for v in per_source],
            }
        )
    return {
        "floors": floors,
        "gates": {name: score(pairs) for name, pairs in gate_pairs.items()},
        "detail": detail,
    }


def run_arm(name: str, fn, corpus: dict) -> dict:
    install(fn)
    words = word_level(corpus["words"])
    claims = claim_level(corpus["claims"])
    return {"arm": name, "words": words, "claims": claims}


def table(results: list[dict]) -> str:
    """사람이 읽는 표 — 이 벤치의 산출은 숫자 하나가 아니라 맞바꿈의 모양이다."""
    lines = [
        "| arm | 낱말 P | 낱말 R | F1 | F0.5 | ko P | ko R | en P | en R | 통찰승격 P | 통찰승격 R | 계약 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in results:
        w = row["words"]["overall"]
        ko = row["words"]["by_lang"].get("ko", {})
        en = row["words"]["by_lang"].get("en", {})
        auto = row["claims"]["gates"]["insight_auto"]
        broken = len(row["words"]["span_contract_broken"])
        lines.append(
            f"| {row['arm']} | {w['precision']:.3f} | {w['recall']:.3f} | {w['f1']:.3f} | {w['f0.5']:.3f} "
            f"| {ko.get('precision', 0):.3f} | {ko.get('recall', 0):.3f} "
            f"| {en.get('precision', 0):.3f} | {en.get('recall', 0):.3f} "
            f"| {auto['precision']:.3f} | {auto['recall']:.3f} "
            f"| {'깨짐 ' + str(broken) if broken else 'ok'} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=os.path.join(HERE, "corpus.json"))
    parser.add_argument("--out", default=os.path.join(HERE, "results.json"))
    args = parser.parse_args()

    with open(args.corpus, encoding="utf-8") as handle:
        corpus = json.load(handle)

    results = [run_arm(name, fn, corpus) for name, fn in ARMS]
    report = {
        "corpus": os.path.basename(args.corpus),
        "corpus_note": "합성 — 절대 수치가 아니라 arm 간 상대 비교로 읽는다 (corpus.json 의 about 절)",
        "n_words": len(corpus["words"]),
        "n_words_positive": sum(1 for c in corpus["words"] if c["expect"]),
        "n_words_negative": sum(1 for c in corpus["words"] if not c["expect"]),
        "n_claims": len(corpus["claims"]),
        "n_claims_positive": sum(1 for c in corpus["claims"] if c["expect"]),
        "n_claims_negative": sum(1 for c in corpus["claims"] if not c["expect"]),
        "arms": results,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
    print(
        f"낱말 {report['n_words']}건 (양성 {report['n_words_positive']} · 음성 {report['n_words_negative']}) "
        f"· 주장 {report['n_claims']}건 (양성 {report['n_claims_positive']} · 음성 {report['n_claims_negative']})\n"
    )
    print(table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
