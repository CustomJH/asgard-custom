"""원탁 대조 벤치 — 좌석을 여럿 앉히는 것이 모델 하나에게 묻는 것보다 나은가.

이 벤치가 서는 이유는 하나다. `asgard siege roundtable` 은 동작이 시험으로 묶여 있지만
(`tests/test_roundtable.py`), 시험이 재는 것은 "규칙대로 도는가"다. 값어치는 다른 질문이다 —
**같은 안건에서 좌석 여럿이 모델 하나보다 결함을 더 짚는가, 그리고 그 차이가 좌석 수만큼의
비용을 갚는가.**

## 조건 셋

  A  단일 호출 — 모델 하나에게 안건과 함께 "반론을 내라"를 한 번 묻는다. 대조군이다.
  B  동일 모델 3좌석 2회차 — 원탁의 구조만 있고 벤더 다양성은 없다.
  C  혼합 벤더 3좌석 2회차 — 좌석마다 다른 뒷단.

B 를 따로 두는 것이 이 벤치의 요지다. C 가 A 를 이겨도 그것이 **구조(회차·교차 반박)** 때문인지
**모델을 여럿 썼기 때문**인지 가릴 수 없기 때문이다. B 는 구조만 바꾸고 모델은 A 와 같다.

## 채점 — 결정론 먼저, 모델은 그 다음

각 사례에는 이 저장소가 나중에 문서로 남긴 결함이 라벨로 붙어 있다(`cases.py`). 채점은 "좋은
답인가"가 아니라 "그 결함을 짚었는가" 하나다.

  1. 결정론 — `cases.keys` 의 낱말 묶음이 전부 하나씩 맞는가. 사람이 다시 셀 수 있다.
  2. 모델 판정 — 같은 물음을 판정 모델에게 던진다. **모든 산출물에 돌린다** — 결정론이 놓친
     것만 골라 돌리면 그 선택이 곧 편향이다.
  3. 라벨 밖 반론 — 알려진 결함을 뺀 나머지 반론을 열거해 센다(`--breadth`). 라벨 하나를
     맞혔는가로는 천장에 닿은 조건들을 못 가르기 때문이다.

셋을 따로 싣고, 어긋나면 어긋난 채로 보고한다. 판정 모델은 시험 대상과 다른 뒷단에 두는 것이
기본이다(`--judge`).

## 실행

    .venv/bin/python benchmarks/roundtable/harness.py --self-check          # 모델 없이 형상만
    .venv/bin/python benchmarks/roundtable/harness.py --conditions A,B,C
    .venv/bin/python benchmarks/roundtable/harness.py --cases baseline-timeout --conditions A
    .venv/bin/python benchmarks/roundtable/harness.py --rejudge             # 판정 축을 균일하게
    .venv/bin/python benchmarks/roundtable/harness.py --breadth             # 라벨 밖 반론을 센다

`--rejudge` 와 `--breadth` 는 저장된 산출물만 읽어 대상 모델을 다시 안 부르지만, 파일을 읽어
되쓰므로 본 실행이 도는 동안 돌리지 않는다.

결과는 한 건씩 `results.jsonl` 에 덧붙는다. 중간에 끊겨도 이미 끝난 (사례, 조건) 짝은 다시 안
돌린다 — 한 판이 수십 번의 모델 호출이라 처음부터 다시 도는 것이 가장 비싼 실패다.

## 이 벤치가 못 재는 것

말뭉치 여덟 건은 전부 **이 저장소의** 결정이고, 라벨은 이 저장소가 남긴 원인이다. 다른 저장소나
다른 종류의 결정으로 일반화되지 않는다. 그리고 안건을 쓴 것이 이 저장소를 아는 쪽(나)이라,
결함을 흘리지 않으려 애썼어도 어느 안건이 얼마나 쉬운지는 균일하지 않다.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from cases import CASES  # noqa: E402

from asgard import roundtable as rt  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULTS = os.path.join(os.path.dirname(__file__), "results.jsonl")

# 단일 호출 대조군의 지시. 좌석 하나가 받는 것과 같은 요구를 한 번에 준다 — 대조군을 약하게
# 잡으면 원탁이 이기는 것이 당연해지고, 그 결과는 아무것도 안 말한다.
SOLO_SYSTEM = (
    "You are a senior engineer reviewing a design decision before it ships. "
    "Find what is wrong with it: the failure mode, the case it does not cover, the cost it hides."
)
SOLO_USER = (
    "{agenda}\n\n"
    "Give your objections. Name the failure mode concretely — what breaks, when, and why the "
    "proposal as written does not catch it. Under 400 words."
)

JUDGE_SYSTEM = (
    "You judge one narrow question. You are not evaluating writing quality, only whether the same "
    "defect was found. Keep any reasoning short and put the verdict on the last line."
)
JUDGE_USER = (
    "A known defect of a design proposal:\n\n{flaw}\n\n"
    "Below is what a reviewer wrote about that proposal. Did the reviewer identify that same "
    "defect — the same mechanism, not merely an adjacent concern?\n\n"
    "---\n{answer}\n---\n\n"
    "End your reply with the verdict on its own last line: YES or NO."
)

# 혼합 벤더 조건의 좌석. 이 기계에서 실제로 답을 내는 뒷단만 적는다 — 안 닿는 것을 적으면 그
# 좌석은 매번 실패하고, 실패한 좌석은 조건 C 를 조건 B 로 만든다. ollama(gemma4:12b-mlx)는
# 빈 응답만 내서 뺐다. codex 는 CLI 좌석이라 저장소를 읽을 수 있다 — 조건 C 가 B 와 벤더
# **와** 저장소 접근 둘에서 갈린다는 뜻이고, 이 기계에 닿는 API 벤더가 둘뿐이라 감수한 것이다.
MIXED_BACKENDS = ("claude-native", "nvidia", "codex")
SEAT_ROLES = ("researcher", "critic", "challenger")

# 좌석이 도는 자리. **이 저장소 안에서 돌리면 안 된다** — 26-08-14 실측: `claude-native` 좌석은
# cwd 로 프로젝트 슬러그를 풀어 Claude Code 의 자동 기억(`~/.claude/projects/<슬러그>/memory/`)
# 을 읽는다. `setting_sources=[]` 로 훅과 설정을 끊어도 그 경로는 안 덮인다. 이 벤치의 라벨
# 여덟은 전부 그 기억에 한 줄씩 있으므로, 저장소 안에서 돌린 회차는 "답을 이미 들은 모델이
# 되풀이하는가"를 잰 것이 된다. 중립 디렉터리로 물으면 같은 질문에 "모름"이 나온다.
_SEAT_ROOT: str = ""


def seat_root() -> str:
    """좌석을 돌릴 중립 디렉터리 — 없으면 만든다.

    설정 해석은 여기서도 선다: provider 자격은 기계 전역(`~/.asgard`)에 있고, 프로젝트 설정이
    없으면 전역으로 떨어진다. 잃는 것은 이 저장소의 답이고, 그것이 이 함수의 목적이다.

    빈 Git 저장소로 만드는 이유는 codex 좌석이다. `codex exec` 는 Git 저장소 밖에서
    `Not inside a trusted directory and --skip-git-repo-check was not specified` 를 내고 종료
    코드 1로 끝난다 — 26-08-14 실측이고, 그것 때문에 조건 C 의 세 번째 좌석이 매 판 빠져 C 가
    2좌석으로 돌았다. `git init` 만으로 그 검사가 통과하며, 커밋도 원격도 없으므로 좌석이
    읽을 코드는 여전히 없다.
    """
    global _SEAT_ROOT
    if not _SEAT_ROOT:
        _SEAT_ROOT = tempfile.mkdtemp(prefix="asgard-rt-bench-")
        subprocess.run(["git", "init", "-q", _SEAT_ROOT], check=True, capture_output=True)
    return _SEAT_ROOT


def deterministic_hit(text: str, keys: list[list[str]]) -> bool:
    """낱말 묶음이 **전부** 하나씩 맞았는가 — 사람이 다시 셀 수 있는 채점."""
    low = (text or "").lower()
    return all(any(k.lower() in low for k in group) for group in keys)


def solo(case: dict, provider: str, model: str) -> dict:
    """대조군 한 번 — 좌석과 같은 중립 자리에서 부른다."""
    from asgard.agent.oneshot import complete_with
    from asgard.providers import resolve

    where = seat_root()
    rp = resolve(where, provider or None, model or None)
    if rp.missing:
        raise RuntimeError(f"provider 미충족: {'; '.join(rp.missing)}")
    started = time.monotonic()
    text = complete_with(rp, where, SOLO_SYSTEM, SOLO_USER.format(agenda=case["agenda"]), max_tokens=1600)
    return {"text": text or "", "calls": 1, "secs": round(time.monotonic() - started, 1)}


def table(case: dict, backends: list[str], rounds: int) -> dict:
    """원탁 한 판 — 사회자가 읽는 것은 전사 전체이므로 모든 발언을 이어 붙여 채점한다.

    좌석은 중립 자리에서 돈다. CLI 좌석이 이 저장소를 못 읽게 되므로 제품에서의 이점 하나가
    빠지지만, 이 벤치에서 그 이점은 답안지를 보는 것과 같다.
    """
    seats = [rt.Seat(name=role, role=role, provider=backends[i % len(backends)]) for i, role in enumerate(SEAT_ROLES)]
    started = time.monotonic()
    result = rt.convene(seat_root(), case["agenda"], seats, rounds=rounds, run_id="")
    spoken = [turn for turn in result["turns"] if turn["ok"]]
    return {
        "text": "\n\n".join(turn["text"] for turn in spoken),
        "calls": len(result["turns"]),
        "secs": round(time.monotonic() - started, 1),
        "failed": result["failed"],
        "stances": result["stances"],
        "by_round": {str(n): sum(1 for t in spoken if t["round"] == n) for n in sorted({t["round"] for t in spoken})},
    }


def judge(root: str, case: dict, answer: str, provider: str, model: str, budget: int = 400) -> str:
    """판정 모델의 한 낱말. 부를 수 없으면 빈 문자열 — 없는 판정을 NO 로 세지 않는다.

    `budget` 이 낮으면 추론을 앞세우는 모델이 판정에 닿기 전에 잘린다. 그 경우도 빈 문자열이라
    NO 와 구분되고, `--rejudge` 가 **모든 행에 같은 예산으로** 다시 돌려 그 구멍을 메운다.
    """
    from asgard.agent.oneshot import complete_with
    from asgard.providers import resolve

    try:
        rp = resolve(root, provider or None, model or None)
        if rp.missing:
            return ""
        said = complete_with(
            rp,
            root,
            JUDGE_SYSTEM,
            JUDGE_USER.format(flaw=case["flaw"], answer=(answer or "")[:12000]),
            max_tokens=budget,
        )
    except Exception:
        return ""
    # 추론을 앞에 붙여 내는 모델이 있으므로 **마지막** 판정 낱말을 읽는다. 앞을 읽으면
    # 생각하는 문장 안의 "no" 를 판정으로 세게 된다.
    for line in reversed((said or "").strip().splitlines()):
        token = line.strip().strip("*_`#. ").upper()
        if token.endswith("YES") or token == "YES":
            return "YES"
        if token.endswith("NO") or token == "NO":
            return "NO"
    return ""


def rejudge(root: str, args) -> int:
    """저장된 산출물 전부를 같은 예산으로 다시 판정한다 — 판정 축을 한 자리에서 고른다.

    실행 중의 판정은 예산이 낮아 몇 건이 빈 값으로 남는다. 그 몇 건만 다시 돌리면 "빈 값이던
    것만 후하게 판정한" 셈이라 편향이 된다. 그래서 전부 다시 돌리고 `hit_judge2` 에 적는다 —
    원래 값은 지우지 않으므로 둘을 견줄 수 있다.
    """
    if not os.path.exists(RESULTS):
        print("결과 파일이 없어요")
        return 2
    rows = [json.loads(line) for line in open(RESULTS, encoding="utf-8") if line.strip()]
    by_id = {case["id"]: case for case in CASES}
    for row in rows:
        case = by_id.get(row.get("case", ""))
        if case is None or row.get("error"):
            continue
        row["hit_judge2"] = judge(
            root, case, row.get("text", ""), args.judge, args.judge_model, budget=args.rejudge_budget
        )
        print(f"  {row['case']}/{row['condition']} → {row['hit_judge2'] or '-'}", flush=True)
    print(f"  {merge_write(rows)}행")
    return 0


BREADTH_SYSTEM = (
    "You extract a list. You are not judging quality and you are not adding objections of your own — "
    "you only itemise what the text already argues. Do not deliberate and do not restate the task: "
    "emit the marker line first, then the list, and nothing else."
)
BREADTH_USER = (
    "Below is a review of a design proposal. List the distinct objections it raises — one per line, "
    "each a short phrase naming the mechanism that breaks. Merge restatements of the same objection "
    "into one line. Do not add objections the text does not make.\n\n"
    "One of them is already known and does not count; skip any line that says the same thing as "
    "this:\n{flaw}\n\n"
    "---\n{answer}\n---\n\n"
    "Start your reply with a line containing exactly {marker}. After it, write one objection per "
    'line prefixed with "- ". Write "- NONE" if the text raises no other objection. Nothing but '
    "those lines may follow the marker."
)
# 목록이 시작하는 자리를 산출물이 스스로 표시하게 하는 말. `judge()` 가 **마지막** 판정 낱말을
# 읽는 것과 같은 이유다 — 추론을 앞세우는 모델이 있고, 그 문장들은 목록이 아니다.
_BREADTH_MARKER = "###LIST###"
_BREADTH_CAP = 40  # 한 산출물에서 세는 반론의 상한. 넘으면 열거가 아니라 문단 쪼개기다


def breadth(root: str, case: dict, answer: str, provider: str, model: str, budget: int = 12000) -> list[str] | None:
    """라벨 밖 반론의 목록 — 이 벤치가 첫 회차에 못 잰 축.

    첫 회차는 "알려진 결함 하나를 짚었나"만 봤고 세 조건이 전부 8/8 이라 아무것도 못 갈랐다.
    그런데 이번 작업에서 원탁이 실제로 바꾼 결정은 **라벨이 없는 반론**이었다. 그러니 세어야
    하는 것은 라벨을 맞혔는가가 아니라 라벨 밖에 무엇을 더 얹었는가다.

    대상 모델은 다시 안 부른다 — `results.jsonl` 에 저장된 산출물만 읽는다. 그래서 이 축은
    앞 회차의 값을 그대로 쓰고, 세는 쪽만 새로 붙는다.

    목록은 `_BREADTH_MARKER` 뒤의 `- ` 줄만 읽는다. 26-08-14 에 그 표식 없이 모든 줄을 세다가
    추론을 앞세우는 모델의 생각 문장이 반론으로 들어갔다 — 한 A 산출물(1,117자)을 그 세는 법으로
    다시 세니 30건이 나왔고 앞머리가 "The user wants me to extract distinct objections" 였다.
    그 회차의 조건별 합(A 158·B 256·C 269)은 전부 무효다.

    `budget` 기본값이 큰 이유는 그 다음에 잰 것이다. 판정 뒷단(nvidia)은 추론을 끄지 못하고,
    추론 길이는 입력 길이를 따라간다 — 1,200토큰으로 시험한 세 행이 모두 목록에 못 닿았고,
    4,000에서 1,117자 산출물이 3건을 냈지만 11,457자 산출물은 여전히 못 닿았으며, 12,000에서
    그 행이 88초에 35건을 냈다. 예산이 짧으면 **긴 산출물만 골라 분모에서 빠지므로**, 좌석을
    늘려 길어진 조건이 조용히 빠지고 비교가 뒤집힌다. 예산은 모든 행에 같아야 한다.

    Returns:
        반론 문구의 목록. 표식이 없거나 판정 뒷단을 못 부르면 `None` — "반론이 없다"(빈 목록)와
        "셀 수 없었다"를 가른다. 못 센 행은 조건 평균의 분모에서 빠진다.
    """
    from asgard.agent.oneshot import complete_with
    from asgard.providers import resolve

    try:
        rp = resolve(root, provider or None, model or None)
        if rp.missing:
            return None
        said = complete_with(
            rp,
            root,
            BREADTH_SYSTEM,
            BREADTH_USER.format(flaw=case["flaw"], answer=(answer or "")[:12000], marker=_BREADTH_MARKER),
            max_tokens=budget,
        )
    except Exception:
        return None
    lines = (said or "").splitlines()
    # 표식이 여러 번 나오면 마지막 것이 목록의 시작이다 — 앞의 것은 모델이 지시를 되풀이한 자리다.
    marker_at = -1
    for index, line in enumerate(lines):
        if line.strip() == _BREADTH_MARKER:
            marker_at = index
    if marker_at < 0:
        return None
    found: list[str] = []
    for line in lines[marker_at + 1 :]:
        text = line.strip()
        if not text.startswith("- "):
            continue
        text = text[2:].strip()
        if not text or text.upper() == "NONE":
            continue
        found.append(text[:200])
    return found[:_BREADTH_CAP]


def count_breadth(root: str, args) -> int:
    """저장된 산출물 전부에서 라벨 밖 반론을 세어 `breadth` 에 적는다.

    행끼리는 서로를 안 읽으므로 나란히 센다. 순차로는 한 행에 수 분이 걸려 24행이 한나절이 되고,
    그 사이 어느 행에서 끊기면 `merge_write` 가 마지막에 한 번만 도는 탓에 통째로 잃는다.
    동시 실행 수를 판정 뒷단의 RPM 상한(`agent.rate_limit`)보다 한참 낮게 두어 429를 피한다.
    """
    if not os.path.exists(RESULTS):
        print("결과 파일이 없어요")
        return 2
    rows = [json.loads(line) for line in open(RESULTS, encoding="utf-8") if line.strip()]
    by_id = {case["id"]: case for case in CASES}
    todo = [row for row in rows if by_id.get(row.get("case", "")) and not row.get("error")]

    def one(row: dict) -> None:
        found = breadth(
            root, by_id[row["case"]], row.get("text", ""), args.judge, args.judge_model, budget=args.breadth_budget
        )
        row["breadth"] = found
        shown = "못 셈" if found is None else f"{len(found)}건{' (상한)' if len(found) >= _BREADTH_CAP else ''}"
        print(f"  {row['case']}/{row['condition']} → {shown}", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.breadth_workers) as pool:
        for future in concurrent.futures.as_completed([pool.submit(one, row) for row in todo]):
            future.result()
    print(f"  {merge_write(rows)}행")
    return 0


def done_pairs() -> set[tuple[str, str]]:
    if not os.path.exists(RESULTS):
        return set()
    found: set[tuple[str, str]] = set()
    with open(RESULTS, encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            found.add((row.get("case", ""), row.get("condition", "")))
    return found


def append(row: dict) -> None:
    with open(RESULTS, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def merge_write(updated: list[dict]) -> int:
    """뒤에 붙은 값을 안 지우고 되쓴다 — `(사례, 조건)` 을 열쇠로 합친다.

    `--rejudge` 와 `--breadth` 는 파일을 읽어 고친 뒤 되쓴다. 그 사이에 본 실행이 새 행을
    덧붙이면 통째로 되쓰기가 그것을 지운다. 26-08-14 에 실제로 그 직전까지 갔다 — 옛 24행을
    든 채로 도는 `--breadth` 와, 새 회차를 붙이는 실행이 같은 파일을 보고 있었다.

    Returns:
        되쓴 뒤의 행 수.
    """
    fresh: list[dict] = []
    if os.path.exists(RESULTS):
        fresh = [json.loads(line) for line in open(RESULTS, encoding="utf-8") if line.strip()]
    by_key = {(row.get("case"), row.get("condition")): row for row in fresh}
    for row in updated:
        key = (row.get("case"), row.get("condition"))
        if key in by_key:
            by_key[key].update(row)  # 새 실행이 덮어쓴 행이면 그쪽이 정본이고, 축만 얹는다
        else:
            by_key[key] = row
    with open(RESULTS, "w", encoding="utf-8") as handle:
        for row in by_key.values():
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(by_key)


def run_pair(root: str, case: dict, condition: str, args) -> dict:
    if condition == "A":
        got = solo(case, args.provider, args.model)
    elif condition == "B":
        got = table(case, [args.provider], args.rounds)
    elif condition == "C":
        got = table(case, list(MIXED_BACKENDS), args.rounds)
    else:
        raise ValueError(f"모르는 조건이에요: {condition}")
    verdict = judge(root, case, got["text"], args.judge, args.judge_model)
    return {
        "case": case["id"],
        "condition": condition,
        "hit_keys": deterministic_hit(got["text"], case["keys"]),
        "hit_judge": verdict,
        "calls": got["calls"],
        "secs": got["secs"],
        "chars": len(got["text"]),
        "extra": {k: v for k, v in got.items() if k not in ("text", "calls", "secs")},
        "text": got["text"],
    }


def summarise(rows: list[dict]) -> dict:
    out: dict = {}
    for condition in sorted({row["condition"] for row in rows}):
        picked = [row for row in rows if row["condition"] == condition]
        judged = [row for row in picked if row["hit_judge"] in ("YES", "NO")]
        # `hit_judge2` 는 `--rejudge` 가 모든 행에 같은 예산으로 다시 물은 값이다. 있으면 그쪽이
        # 판정 축이다 — 실행 중 판정은 예산이 낮아 몇 건이 빈 값으로 남기 때문이다.
        rejudged = [row for row in picked if row.get("hit_judge2") in ("YES", "NO")]
        counted = [row for row in picked if isinstance(row.get("breadth"), list)]
        out[condition] = {
            "n": len(picked),
            "keys_hit": sum(1 for row in picked if row["hit_keys"]),
            "judge_yes": sum(1 for row in judged if row["hit_judge"] == "YES"),
            "judge_n": len(judged),
            "rejudge_yes": sum(1 for row in rejudged if row["hit_judge2"] == "YES"),
            "rejudge_n": len(rejudged),
            # 라벨 밖 반론 — 합과 사례당 평균. 셀 수 없던 행(`breadth=null`)은 분모에서 빠진다.
            "extra_objections": sum(len(row["breadth"]) for row in counted),
            "extra_per_case": round(sum(len(row["breadth"]) for row in counted) / len(counted), 1) if counted else 0.0,
            "breadth_n": len(counted),
            # 상한에 닿은 행이 있으면 그 조건의 합은 하한이다 — 평균을 그대로 읽으면 안 된다.
            "breadth_capped": sum(1 for row in counted if len(row["breadth"]) >= _BREADTH_CAP),
            "calls": sum(row["calls"] for row in picked),
            "secs": round(sum(row["secs"] for row in picked), 1),
        }
    return out


def self_check() -> int:
    """모델 없이 도는 형상 확인 — 채점기와 말뭉치가 서로 맞는지만 본다."""
    problems: list[str] = []
    seen: set[str] = set()
    for case in CASES:
        for field in ("id", "agenda", "flaw", "source", "keys"):
            if not case.get(field):
                problems.append(f"{case.get('id', '?')} — {field} 가 비었어요")
        if case["id"] in seen:
            problems.append(f"{case['id']} — 사례 id 가 겹쳐요")
        seen.add(case["id"])
        # 라벨이 안건에 새면 그 사례는 못 쓴다. 결함 문장의 긴 조각이 안건에 그대로 있으면 잡는다.
        for chunk in [case["flaw"][i : i + 14] for i in range(0, max(1, len(case["flaw"]) - 14), 7)]:
            if chunk.strip() and chunk in case["agenda"]:
                problems.append(f"{case['id']} — 결함 문장이 안건에 샜어요: {chunk!r}")
                break
        if not deterministic_hit(case["flaw"], case["keys"]):
            problems.append(f"{case['id']} — 채점 낱말이 자기 결함 문장도 못 잡아요")
        if deterministic_hit(case["agenda"], case["keys"]):
            problems.append(f"{case['id']} — 채점 낱말이 안건만으로 통과해요 (라벨 누출)")
    print(f"사례 {len(CASES)}건 · 문제 {len(problems)}건")
    for line in problems:
        print("  ✘", line)
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="원탁 대조 벤치")
    parser.add_argument("--self-check", action="store_true", help="모델 없이 말뭉치·채점기만 확인")
    parser.add_argument("--conditions", default="A,B,C")
    parser.add_argument("--cases", default="", help="쉼표로 구분한 사례 id — 비면 전부")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--provider", default="", help="A·B 가 쓰는 뒷단 — 비면 프로젝트 기본")
    parser.add_argument("--model", default="")
    parser.add_argument("--judge", default="nvidia", help="판정 뒷단 — 시험 대상과 다른 쪽이 기본")
    parser.add_argument("--judge-model", default="")
    parser.add_argument("--rejudge", action="store_true", help="저장된 산출물 전부를 같은 예산으로 다시 판정")
    parser.add_argument("--rejudge-budget", type=int, default=1200)
    parser.add_argument("--breadth", action="store_true", help="저장된 산출물에서 라벨 밖 반론을 센다")
    parser.add_argument("--breadth-budget", type=int, default=12000, help="반론 세기의 토큰 예산 — 전 행에 같은 값")
    parser.add_argument("--breadth-workers", type=int, default=6, help="반론 세기의 동시 실행 수")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        return self_check()
    if args.rejudge:
        return rejudge(ROOT, args)
    if args.breadth:
        return count_breadth(ROOT, args)

    wanted = [c.strip() for c in args.cases.split(",") if c.strip()]
    cases = [case for case in CASES if not wanted or case["id"] in wanted]
    conditions = [c.strip().upper() for c in args.conditions.split(",") if c.strip()]
    already = done_pairs()

    for case in cases:
        for condition in conditions:
            if (case["id"], condition) in already:
                print(f"· 건너뜀 {case['id']}/{condition} (이미 있음)", flush=True)
                continue
            print(f"▶ {case['id']}/{condition}", flush=True)
            try:
                row = run_pair(ROOT, case, condition, args)
            except Exception as exc:  # 한 짝의 실패가 나머지를 못 태운다
                row = {
                    "case": case["id"],
                    "condition": condition,
                    "error": f"{type(exc).__name__}: {exc}",
                    "hit_keys": False,
                    "hit_judge": "",
                    "calls": 0,
                    "secs": 0.0,
                    "chars": 0,
                    "text": "",
                }
            append(row)
            mark = "○" if row.get("error") else ("●" if row["hit_keys"] else "·")
            print(f"  {mark} keys={row['hit_keys']} judge={row['hit_judge'] or '-'} {row['secs']}s", flush=True)

    rows = [json.loads(line) for line in open(RESULTS, encoding="utf-8") if line.strip()]
    rows = [row for row in rows if row["case"] in {c["id"] for c in cases} and row["condition"] in conditions]
    found = summarise(rows)
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
    else:
        print()
        for condition, stat in found.items():
            print(
                f"{condition}: 결정론 {stat['keys_hit']}/{stat['n']} · "
                f"판정 {stat['judge_yes']}/{stat['judge_n']} · "
                f"호출 {stat['calls']} · {stat['secs']}초"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
