"""제목 벤치 — 기억 한 장의 제목을 무엇으로 삼을 때 그 장을 실제로 찾을 수 있는가.

왜 재는가 (26-08-19). 개인 기억 50장 중 49장이 본문 첫 줄을 베낀 제목을 달고 있었다. 낱말
한가운데서 끊기는 것은 고쳤지만, 고친 제목도 여전히 본문의 앞부분이다. 그러면 제목 칸은
본문이 이미 말한 것을 한 번 더 말할 뿐이고, 색인에서 앞부분에만 가중치를 더 준다.

A-MEM(arXiv 2502.12110)은 노트마다 `context` 를 따로 두고 그 한 문장이 무엇을 담을지를
갈래로 지정한다 — 주제, 논점, 대상. 그리고 키워드에서 화자 이름과 시간을 빼라고 못박는다.
cognee 는 `name`·`summary`·`content` 를 각각 다른 벡터 컬렉션으로 색인한다. 둘 다 "요약 칸은
본문의 복사본이 아니다" 라는 같은 주장 위에 서 있다. 이 벤치는 그 주장이 **오딘의 실제
기억에서** 성립하는지 잰다.

네 팔 — 같은 본문, 같은 모델, 제목 짓는 방식만 다르다:
  derived_legacy  화자를 떼기 전의 파생기 (모델 없음, 26-08-19 이전 동작)
  derived         `store.derive_title` (모델 없음, 지금 저장소의 실제 상태)
  current  지금 도구 스키마가 모델에게 주는 지시문
  amem     A-MEM 의 두 규칙을 옮긴 지시문 (담을 것을 갈래로, 화자 이름 제외)

축 둘로 나뉜다. 앞의 다섯은 모델 없이 세는 것이고 "제목이 본문과 다른가" 만 답한다 —
무작위 문자열이어도 만점이 나오므로 이것만으로는 품질이 아니다. 판정을 지는 것은 여섯째다:

  summary_recall@3  제목**만** 색인한 상태에서, 본문 **뒷부분**에서 뽑은 낱말로 질의한다.
                    제목이 앞부분 복사본이면 뒷부분 주제어가 제목에 없어 못 찾는다.
                    제목이 장 전체를 대표하는 요약이면 찾는다.
  indexed_recall@1  저장소의 실제 구성(제목+본문을 합쳐 색인) 그대로 두고 1위만 센다. k=3 은
                    세 팔 모두 1.0 이라 아무것도 안 가른다 (실측 26-08-19).

이 벤치가 못 재는 것:
  · 제목이 사람에게 읽기 좋은가. 주관이라 세지 않는다.
  · 실제 세션에서 모델이 제목을 얼마나 잘 짓는가. 여기서는 본문만 주지만, 실제 도구 호출은
    대화 맥락 안에서 일어나므로 모델이 쥔 정보가 더 많다.
  · 일반화. 코퍼스가 오딘의 기억 50장이고 한국어다. 다른 위키에서 같은 값이 나온다는 근거는 없다.
  · 재현. `memory.manager.complete` 에 온도 손잡이가 없어 팔을 다시 돌리면 제목이 달라진다.
    그래서 결론은 한 판의 차이가 아니라 부호와 크기로만 읽어야 한다.

오딘의 기억은 **읽기만** 한다. 팔마다 임시 홈을 새로 만들어 거기에 색인한다.

사용:  uv run --no-project python benchmarks/memory-title/harness.py [--arms derived,current,amem] [--limit N]
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ["ASGARD_MEMORY_SEMANTIC"] = "off"  # 임베딩을 켜면 제목의 몫과 벡터의 몫이 섞인다

from asgard import memory  # noqa: E402
from asgard.memory import store  # noqa: E402
from asgard.memory.manager import complete  # noqa: E402
from asgard.memory.recall import _content_words, _stopword  # noqa: E402

OUT = Path(__file__).resolve().parent
RESULTS = OUT / "results.jsonl"
REPORT = OUT / "REPORT.md"


# 화자 — 이 위키의 페이지는 거의 다 이 낱말로 시작한다. 제목이 그것까지 물려받으면 앞 세 글자가
# 늘 같아 목록에서 서로 안 갈린다 (A-MEM 의 "화자 이름을 키워드에 넣지 마라"와 같은 자리).
def starts_with_speaker(title: str) -> bool:
    """제목이 화자로 시작하는가 — 파생기가 실제로 떼는 것과 **같은 자**로 센다.

    처음에는 정규식 `\b` 로 쟀다. 한국어는 조사가 낱말 문자라 `오딘은` 에서 경계가 안 잡히고,
    48장 중 32장이 화자로 시작하는데 계기는 0 을 냈다 (실측 26-08-19). 다음에는 문자열
    startswith 로 셌는데 그러면 `사용자 정의 필드` 까지 화자로 센다. 자를 두 벌 두지 않는다."""
    return store._SPEAKER_HEAD.match(title) is not None


# 화자 + 조사/소유격까지 한 조각으로 — `오딘은`, `오딘의`, `사용자가`, `the user`.
_SYS = "You write titles for a personal memory wiki. Answer with the title only — no quotes, no trailing period."

# 팔 — 모델에게 주는 지시문만 다르다. 본문도 모델도 같다.
ARMS: dict[str, str | None] = {
    # 화자를 떼기 **전**의 파생기. 이 벤치가 그 변경을 재려고 옛 동작을 들고 있는다 —
    # `store.derive_title` 이 앞으로 더 바뀌어도 비교 대상은 여기 남는다.
    "derived_legacy": None,
    # 모델을 안 부른다. 지금 저장소가 제목 없이 저장될 때 실제로 하는 일 (화자를 뗀다).
    "derived": None,
    # 지금 다섯 도구 표면이 쓰는 문구 그대로 (`agent/tools/schemas.py` 외).
    "current": (
        "A short noun phrase naming what this fact is about — not the first words of the sentence. "
        "Under 40 characters, no trailing period.\n\nFact:\n{body}"
    ),
    # A-MEM 의 두 규칙: 담을 것을 갈래로 지정하고, 화자와 시간을 뺀다.
    "amem": (
        "Write a title for this memory. The title names:\n"
        "- the subject it is about (the tool, file, rule, or concept — not the person)\n"
        "- what is claimed about that subject\n"
        "Do not begin with the speaker's name or a date, and do not copy the opening words of the "
        "fact. Under 40 characters, no trailing period.\n\nFact:\n{body}"
    ),
}


def corpus(limit: int | None = None) -> list[tuple[str, str]]:
    """오딘의 실제 기억에서 (원본 slug, 본문) — 읽기만 한다."""
    d = memory.memory_dir()
    rows: list[tuple[str, str]] = []
    for slug in sorted(store._pages(d)):
        page = store._read(d, slug)
        if not page:
            continue
        body = page[1].strip()
        if len(body) < 40:  # 제목과 본문이 사실상 같은 장은 어느 팔에서도 안 갈린다
            continue
        rows.append((slug, body))
    return rows[:limit] if limit else rows


def legacy_derive_title(body: str) -> str:
    """화자를 떼기 전의 파생기 — `store.derive_title` 에서 그 한 줄만 뺀 것.

    저장소가 앞으로 나아가도 이 벤치는 "무엇에서 무엇으로 갔는가" 를 말할 수 있어야 하므로
    옛 동작을 여기 붙들어 둔다. 나머지 절단 규칙은 현행을 그대로 쓴다 — 다른 것이 섞이면
    화자 한 줄의 몫을 못 가른다."""
    line = store._fm_value(next((ln.strip().lstrip("# ") for ln in body.splitlines() if ln.strip()), "untitled"))
    if len(line) <= store.TITLE_MAX:
        return line
    end = next(
        (m for m in store._SENTENCE_END.finditer(line) if store._SENTENCE_MIN <= m.end() <= store.TITLE_MAX), None
    )
    if end:
        return line[: end.end()]
    head = line[: store.TITLE_MAX - 1]
    cut = head.rfind(" ")
    return (head[:cut] if cut >= store.TITLE_MAX // 2 else head).rstrip() + "…"


def title_for(arm: str, body: str) -> str:
    """한 팔이 이 본문에 붙이는 제목."""
    template = ARMS[arm]
    if arm == "derived_legacy":
        return legacy_derive_title(body)
    if template is None:
        return store.derive_title(body)
    out = complete(os.getcwd(), _SYS, template.format(body=body[:1200]), max_tokens=60)
    return store._fm_value(out.strip().strip('"').strip("'"))[: store.TITLE_MAX] or store.derive_title(body)


# ── 모델 없이 세는 다섯 ────────────────────────────────────────────────────────


def title_terms(title: str) -> list[str]:
    """제목에서 근거로 셀 낱말 — 주어·기능어는 뺀다.

    `오딘은`·`user` 같은 것을 세면 어느 팔이든 그 하나로 값이 흔들린다 (`recall._stopword`)."""
    return [w for w in _content_words(title) if not _stopword(w)]


def shape_scores(rows: list[tuple[str, str, str]]) -> dict:
    """(slug, body, title) 목록의 모양 축. 여기서 만점이어도 품질은 아니다 — 회수 축이 판정한다.

    낱말이 본문에 있는지는 집합 교집합이 아니라 **부분문자열 포함**으로 본다. 색인이 실제로
    그렇게 맞추기 때문이다 (`recall/search.py` 의 `matched = [w for w in scan_words if w in hay]`,
    그 위에 조사·어미를 뗀 변형까지 후보에 넣는다). 집합으로 세면 `baseline_checks가` 와
    `baseline_checks` 가 남남이 되어, 색인이 같다고 보는 낱말을 계기만 새 낱말로 센다 —
    실측 26-08-19 에 그 차이가 `novel_words` 를 0.323 에서 0.598 로 부풀렸고 두 팔의 부호까지
    뒤집었다."""
    prefix = substring = overlap_sum = speaker = 0
    novel_sum = 0.0
    heads: Counter[str] = Counter()
    for _slug, body, title in rows:
        low = body.lower()
        first = next((ln.strip().lstrip("# ") for ln in body.splitlines() if ln.strip()), "")
        bare = title.rstrip("…")
        if title and first.startswith(bare):
            prefix += 1
        if bare and bare in body:
            substring += 1
        tw = title_terms(title)
        head_low = first[:80].lower()
        overlap_sum += (len([w for w in tw if w in head_low]) / len(tw)) if tw else 1.0
        if starts_with_speaker(title):
            speaker += 1
        novel_sum += (len([w for w in tw if w not in low]) / len(tw)) if tw else 0.0
        heads[title[:10]] += 1
    n = len(rows) or 1
    return {
        # 본문 첫 줄의 접두사인가. 화자를 떼면 정의상 떨어지므로 이것만으로 개선을 읽으면 안 된다 —
        # 옆의 `body_substring` 이 "본문에서 온 것인가" 를 그대로 말한다.
        "body_prefix": round(prefix / n, 3),
        "body_substring": round(substring / n, 3),
        "head_overlap": round(overlap_sum / n, 3),
        "speaker_prefix": round(speaker / n, 3),
        "novel_words": round(novel_sum / n, 3),
        "distinct10": round(sum(1 for c in heads.values() if c == 1) / n, 3),
        "chars": round(sum(len(t) for _s, _b, t in rows) / n, 1),
    }


# ── 회수 — 판정을 지는 축 ──────────────────────────────────────────────────────


def tail_queries(rows: list[tuple[str, str, str]], per_doc: int = 3) -> list[tuple[int, str]]:
    """본문 **뒷부분**에서 뽑은 드문 낱말 질의. 반환 = (행 번호, 질의).

    앞부분을 쓰면 어느 팔이든 제목에 그 낱말이 있어 축이 죽는다. 코퍼스 전체에서 드문 낱말만
    골라 다른 장이 우연히 걸리는 것을 줄인다."""
    df: Counter[str] = Counter()
    tails: list[list[str]] = []
    for _slug, body, _title in rows:
        tail = body[len(body) // 2 :]
        words = [w for w in dict.fromkeys(_content_words(tail)) if len(w) >= 3]
        tails.append(words)
        df.update(set(words))
    out: list[tuple[int, str]] = []
    for i, words in enumerate(tails):
        rare = sorted(words, key=lambda w: (df[w], -len(w)))[:per_doc]
        if rare:
            out.append((i, " ".join(rare)))
    return out


def recall_at_k(rows: list[tuple[str, str, str]], *, titles_only: bool, k: int = 3) -> float:
    """임시 홈에 색인하고 뒷부분 질의로 hit@k 를 잰다. 오딘의 홈은 안 건드린다."""
    tmp = tempfile.mkdtemp(prefix="asgard-title-bench-")
    prev_home, prev_mem = os.environ.get("HOME"), os.environ.get(memory.MEMORY_ENV)
    try:
        os.environ["HOME"] = tmp
        d = os.path.join(tmp, "memory")
        os.environ[memory.MEMORY_ENV] = d
        memory.ensure_home(d)
        placed: dict[int, str] = {}
        for i, (_slug, body, title) in enumerate(rows):
            text = title if titles_only else body
            try:
                slug, _ = memory.add(text, title=title, kind="note", d=d)
            except Exception:
                continue  # 스캔에 걸린 장은 이 팔에서 빠진다 — 아래 커버리지로 보고된다
            placed[i] = slug
        hits = asked = 0
        for i, q in tail_queries(rows):
            if i not in placed:
                continue
            asked += 1
            got = [h["slug"] for h in memory.query(q, k=k, d=d, track=False)]
            if placed[i] in got:
                hits += 1
        return round(hits / asked, 3) if asked else 0.0
    finally:
        for key, value in (("HOME", prev_home), (memory.MEMORY_ENV, prev_mem)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)


def impl_sha(arm: str) -> str:
    """이 팔이 실제로 부르는 코드의 짧은 해시 — 모델 팔은 지시문, 파생 팔은 함수 본문."""
    src = ARMS[arm] or (
        inspect.getsource(legacy_derive_title)
        if arm == "derived_legacy"
        # 정규식은 모듈 상수라 함수 본문 해시에 안 들어간다 — 빼면 화자 판정을 바꿔도 해시가
        # 그대로여서, 이 표시가 막으려던 "두 판이 한 평균에 섞이는 것" 을 정작 못 본다.
        else inspect.getsource(store.derive_title)
        + inspect.getsource(store.strip_speaker)
        + store._SPEAKER_HEAD.pattern
    )
    return hashlib.sha1(src.encode("utf-8")).hexdigest()[:8]


def run_arm(arm: str, docs: list[tuple[str, str]], workers: int, rep: int = 0) -> dict:
    t0 = time.time()
    if ARMS[arm] is None:
        titles = [title_for(arm, b) for _s, b in docs]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            titles = list(pool.map(lambda sb: title_for(arm, sb[1]), docs))
    rows = [(s, b, t) for (s, b), t in zip(docs, titles)]
    rec = {
        "arm": arm,
        # 계기 판. 1 판은 화자 판정이 한국어에서 0 을 냈고 본문 회수가 k=3 천장에 붙어 있었다 —
        # 같은 파일에 남아 있지만 2 판과 나란히 읽으면 안 된다.
        "instrument": 5,
        # 팔이 부르는 코드의 판. `derived` 는 저장소를 따라 움직이므로, 이 표시가 없으면 정의가
        # 바뀐 뒤의 판과 그 전의 판이 같은 이름으로 한 평균에 섞인다 (실측 26-08-19: 그렇게 섞였다).
        "impl": impl_sha(arm),
        "rep": rep,
        "pages": len(rows),
        **shape_scores(rows),
        "summary_recall@3": recall_at_k(rows, titles_only=True),
        "indexed_recall@1": recall_at_k(rows, titles_only=False, k=1),
        "seconds": round(time.time() - t0, 1),
        "titles": [t for _s, _b, t in rows],
    }
    return rec


def recompute(docs: list[tuple[str, str]]) -> list[dict]:
    """이미 기록된 제목으로 축만 다시 센다 — 모델을 다시 부르지 않는다.

    계기가 틀린 것을 고쳤을 때 쓴다. 모델 팔을 다시 돌리면 제목이 달라져(온도 손잡이 없음)
    계기 수정의 몫과 모델의 흔들림이 섞인다."""
    out: list[dict] = []
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        old = json.loads(line)
        titles = old.get("titles") or []
        if old.get("instrument") != 3 or len(titles) != len(docs):
            continue
        rows = [(s, b, t) for (s, b), t in zip(docs, titles)]
        out.append(
            {
                "arm": old["arm"],
                "instrument": 5,
                "impl": old.get("impl", ""),
                "rep": old.get("rep", 0),
                "recomputed_from": 3,
                "pages": len(rows),
                **shape_scores(rows),
                "summary_recall@3": recall_at_k(rows, titles_only=True),
                "indexed_recall@1": recall_at_k(rows, titles_only=False, k=1),
                "seconds": 0.0,
                "titles": titles,
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="derived_legacy,derived,current,amem")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--repeat", type=int, default=1, help="모델 팔은 온도 손잡이가 없어 판마다 다르다")
    ap.add_argument("--recompute", action="store_true", help="기록된 제목으로 축만 다시 센다 (모델 호출 없음)")
    args = ap.parse_args()

    docs = corpus(args.limit or None)
    print(f"corpus: {len(docs)} pages")
    records = []
    if args.recompute:
        records = recompute(docs)
        for rec in records:
            print(json.dumps({k: v for k, v in rec.items() if k != "titles"}, ensure_ascii=False))
        with RESULTS.open("a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"\nrecomputed {len(records)} record(s) -> {RESULTS}")
        return 0
    for arm in args.arms.split(","):
        arm = arm.strip()
        if arm not in ARMS:
            raise SystemExit(f"unknown arm: {arm}")
        # 모델을 안 부르는 팔은 판마다 같은 답을 내므로 한 번만 돈다.
        reps = 1 if ARMS[arm] is None else args.repeat
        for rep in range(reps):
            rec = run_arm(arm, docs, args.workers, rep)
            records.append(rec)
            show = {k: v for k, v in rec.items() if k != "titles"}
            print(json.dumps(show, ensure_ascii=False))
    with RESULTS.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\nappended {len(records)} record(s) -> {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
