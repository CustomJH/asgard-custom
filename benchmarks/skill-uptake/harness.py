#!/usr/bin/env python3
"""스킬이 실제로 배차에 닿는가 — 결정론 실측 (LLM 없음).

새 스킬을 얹는 일은 두 단계다. ① 카탈로그에 들어간다 ② 진짜 요청에서 **불린다**. ①은
`skills list`가 바로 보여 주지만 ②는 아무도 안 재 왔고, 실패는 조용하다 — 트리거가 안 걸리면
스킬은 존재한 채로 한 번도 안 뜬다. 이 하네스가 ②를 잰다.

축:
  reach      — 이름 붙인 요청 배터리에서 기대 스킬이 실제로 해석 결과에 나오는가 (언어별로 나눠 본다)
  precision  — 관계없는 요청에서 그 스킬이 **안** 뜨는가 (오발은 남의 본문을 컨텍스트에 끌어온다)
  semantic   — 트리거 낱말이 하나도 없는 요청 (하한 아님 — 결정론 층의 천장을 재는 자리)
  shape      — 형상 노트가 사용자 호출 오케스트레이터 이름을 대 주는가
  shape-prec — 한 조각짜리 요청이 feature 로 안 올라가는가 (과승격은 매 턴 규율 블록을 붙인다)
  shape-rec  — 신설 표면 요청이 feature 로 올라가는가 (미탐은 규율도 스펙 제안도 통째로 없앤다)
  shape-gap  — 이 층이 못 잡는 신설 요청 (하한 아님 — 지운 갈래가 남긴 구멍을 매 실행 보이게 둔다)
  load       — 역할별 턴당 상시 부하: 그 역할에 열린 model 호출 스킬의 이름+설명 글자 수
  latency    — `resolve_skills` 한 번의 벽시계 중앙값

돌리는 법:
    uv run --no-project python benchmarks/skill-uptake/harness.py          # 표로 본다
    uv run --no-project python benchmarks/skill-uptake/harness.py --json   # 기계용
    uv run --no-project python benchmarks/skill-uptake/harness.py --check  # 하한 위반이면 exit 2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from asgard import skill_registry, skill_scope  # noqa: E402

# ── 배터리 — (요청, 언어, 기대 스킬, 금지 스킬) ────────────────────────────────
# 기대는 "이 요청에서 이 스킬이 안 뜨면 배차가 실패한 것"이고, 금지는 "떠서는 안 되는 것"이다.
#
# `want` 사례는 트리거 낱말을 **반드시** 품는다 — 배차가 부분 문자열 매칭이라 그러지 않으면
# 원리상 못 걸린다. 그래서 이 축이 재는 것은 "그 낱말이 오딘이 실제로 칠 법한 문장 안에,
# 조사와 굴절이 붙은 채로 있어도 걸리는가"이지 의미 이해가 아니다. 자기 채점을 막는 것은 문장
# 쪽이 아니라 다른 두 축이다: `deny` 사례가 트리거가 남의 요청까지 먹는지 보고,
# `SEMANTIC_CASES` 가 낱말이 아예 없을 때의 천장을 따로 잰다.
CASES: tuple[dict, ...] = (
    # escort — 사람만 할 수 있는 절차
    {"req": "스트라이프 붙이려면 API 키부터 발급받아야 하는데 절차 좀 만들어줘", "lang": "ko", "want": "escort"},
    {"req": "배포 워크플로에 쓸 CI 시크릿 설정 순서 좀 정리해줘", "lang": "ko", "want": "escort"},
    {"req": "스테이징 환경 프로비저닝을 처음부터 밟게 해줘", "lang": "ko", "want": "escort"},
    {"req": "walk me through provisioning the staging database credentials", "lang": "en", "want": "escort"},
    {"req": "set up the CI secrets the deploy workflow needs", "lang": "en", "want": "escort"},
    {"req": "I have to grab an api key out of their dashboard first", "lang": "en", "want": "escort"},
    # asgard-skillcraft — 에이전트가 읽는 문서
    {"req": "AGENTS.md 를 손볼 건데 어디까지 넣어야 할지 모르겠어", "lang": "ko", "want": "asgard-skillcraft"},
    {"req": "스킬 작성 규율대로 이 파일을 정리해줘", "lang": "ko", "want": "asgard-skillcraft"},
    {"req": "컨텍스트 부하를 줄이게 이 문서를 갈라줘", "lang": "ko", "want": "asgard-skillcraft"},
    {"req": "edit CLAUDE.md so the agent stops missing this rule", "lang": "en", "want": "asgard-skillcraft"},
    {"req": "this SKILL.md is too long — apply progressive disclosure", "lang": "en", "want": "asgard-skillcraft"},
    # prototype — 돌려 봐야 답이 나오는 결정
    {"req": "어느 쪽이 나은지 프로토타입으로 먼저 보자", "lang": "ko", "want": "prototype"},
    {"req": "spike this so we can see which approach actually feels right", "lang": "en", "want": "prototype"},
    # domain-modeling / codebase-design / merge-resolution — 기존 배차의 회귀 감시
    {"req": "용어 정리부터 하자, 같은 걸 세 이름으로 부르고 있어", "lang": "ko", "want": "domain-modeling"},
    {"req": "write the ubiquitous language down before we build", "lang": "en", "want": "domain-modeling"},
    {"req": "모듈 경계가 이상해서 한 줄 고치면 세 파일이 딸려와", "lang": "ko", "want": "codebase-design"},
    {"req": "the layering is wrong — a lower module reaches back up", "lang": "en", "want": "codebase-design"},
    {"req": "리베이스 충돌 났는데 어느 쪽을 살려야 할지 모르겠어", "lang": "ko", "want": "merge-resolution"},
    {"req": "there are conflict markers left in three files", "lang": "en", "want": "merge-resolution"},
    # 비트리거 — 오발 감시. 새 스킬은 여기서 절대 뜨면 안 된다.
    {"req": "이 함수 이름만 바꿔줘", "lang": "ko", "deny": ("escort", "asgard-skillcraft", "prototype")},
    {"req": "README 오타 하나 고쳐줘", "lang": "ko", "deny": ("escort", "asgard-skillcraft", "prototype")},
    {"req": "타임아웃 상수를 30초로 올려줘", "lang": "ko", "deny": ("escort", "asgard-skillcraft", "prototype")},
    {"req": "bump the version and tag the release", "lang": "en", "deny": ("escort", "asgard-skillcraft", "prototype")},
    {
        "req": "rename this variable so it reads better",
        "lang": "en",
        "deny": ("escort", "asgard-skillcraft", "prototype"),
    },
)

# 의미로만 닿는 요청 — 스킬이 다루는 개념을 말하지만 트리거 낱말은 하나도 안 쓴다. 부분 문자열
# 라우팅으로는 원리상 못 잡으므로 하한에 넣지 않고, **결정론 배차의 천장**으로 재서 보고한다.
# 여기 걸린 요청도 모델은 카탈로그 설명을 읽고 스스로 고를 수 있다 — 이 축이 0이어도 스킬이
# 안 뜬다는 뜻이 아니라, 결정론 층이 거기까지는 못 도와준다는 뜻이다.
SEMANTIC_CASES: tuple[dict, ...] = (
    {
        "req": "this module is shallow — the interface costs as much as the behaviour",
        "lang": "en",
        "want": "codebase-design",
    },
    {"req": "같은 결정을 세 번째 다시 하고 있어, 매번 처음부터 얘기해", "lang": "ko", "want": "domain-modeling"},
    {"req": "돌려 보기 전에는 어느 쪽이 나은지 못 정하겠어", "lang": "ko", "want": "prototype"},
    {"req": "the vendor console has to be clicked through by a person", "lang": "en", "want": "escort"},
)

# 사용자 호출 스킬은 모델이 못 부른다. 대신 형상 노트가 오딘에게 이름을 대 줘야 한다.
SHAPE_CASES: tuple[dict, ...] = (
    {"req": "결제 정산 화면 추가해줘", "shape": "feature", "must_name": ("blueprint", "quests")},
    {"req": "build a new settings page for the workspace", "shape": "feature", "must_name": ("blueprint", "quests")},
    {"req": "인증 계층을 전면 재설계하자", "shape": "expedition", "must_name": ("expedition",)},
)

# 형상 과승격 감시 — 한 조각짜리 요청이 feature 로 올라가면 매 쓰기 턴에 기능 규율 블록이
# 붙고 스펙을 먼저 고정하라는 제안까지 뜬다. 표면 명사를 **언급**만 하는 문장이 여기 산다.
SHAPE_DENY: tuple[dict, ...] = (
    {"req": "fix the new login page bug", "lang": "en"},
    {"req": "update the new pricing page copy", "lang": "en"},
    {"req": "the new payment service is down", "lang": "en"},
    {"req": "delete the new debug endpoint", "lang": "en"},
    {"req": "document the new auth module", "lang": "en"},
    {"req": "the new export endpoint returns 500", "lang": "en"},
    {"req": "revert the new checkout flow change", "lang": "en"},
    # 복수 표면 — 이미 있는 여러 개를 가리키는 말이지 신설 요청이 아니다.
    {"req": "the new pages are slow", "lang": "en"},
    {"req": "document the new modules", "lang": "en"},
    {"req": "list the new endpoints in the changelog", "lang": "en"},
    # 정관사 — `the new X` 는 그 X 가 이미 있다는 뜻이라, 뜻이 넓은 동사와 붙어도 신설이 아니다.
    {"req": "I want the new export page fixed", "lang": "en"},
    {"req": "we need the new pricing page copy updated", "lang": "en"},
    {"req": "I want the new billing service restarted", "lang": "en"},
    {"req": "we need the new admin page reviewed", "lang": "en"},
    {"req": "make the new login page load faster", "lang": "en"},
    {"req": "need the new debug endpoint removed", "lang": "en"},
    {"req": "함수 하나 새로 만들어줘", "lang": "ko"},
    {"req": "새 결제 서비스 로그 한 줄만 더 찍어줘", "lang": "ko"},
    # 거절문 — 신설을 **거절하는** 말이라 어간까지 글자가 같다. 거절 어형은 열린 집합이라
    # (조사 삽입·선행 부정·대체 표현이 각각 다른 방향으로 는다) 세 갈래를 모두 담는다.
    {"req": "페이지를 새로 만들지 말고 기존 걸 고쳐줘", "lang": "ko"},
    {"req": "화면을 새로 추가하지 말고 기존 걸 써줘", "lang": "ko"},
    {"req": "화면을 새로 추가하지 않고 기존 걸 고쳐줘", "lang": "ko"},
    {"req": "페이지를 새로 만들 필요 없어", "lang": "ko"},
    {"req": "페이지를 새로 만들 필요는 없어", "lang": "ko"},
    {"req": "화면을 새로 만들지 않아도 돼", "lang": "ko"},
    {"req": "페이지를 새로 만들면 안 돼", "lang": "ko"},
    {"req": "엔드포인트를 새로 추가할 필요 없어", "lang": "ko"},
    {"req": "화면을 새로 추가 안 해도 돼", "lang": "ko"},
    {"req": "페이지를 새로 추가하는 대신 고쳐줘", "lang": "ko"},
    {"req": "화면을 새로 만들 게 아니라 고쳐줘", "lang": "ko"},
    {"req": "페이지를 새로 만들기보다 기존 걸 손보자", "lang": "ko"},
    # 내포절 — 요청 어미가 문장 끝이 아니라 절 안에 있다. 요청 어미를 요구하는 규칙이 여기서
    # 샜다. 이 넷이 이 자리의 자물쇠다: 한국어 신설 갈래를 되살리는 어떤 규칙도 여기서 걸린다.
    {"req": "화면을 새로 만들라고 한 적 없어", "lang": "ko"},
    {"req": "페이지를 새로 만들자는 게 아니라 고치자는 거야", "lang": "ko"},
    {"req": "페이지를 새로 추가해야 할 이유가 없다", "lang": "ko"},
    {"req": "화면을 새로 만들자니까 다들 반대했어", "lang": "ko"},
)

# 형상 미탐 감시 — 과승격만 재면 경계를 좁히는 수정이 반대편으로 튀고 아무도 못 본다. 26-08-13
# 실측: 승격 문에 생성 동사를 요구했더니 신설 요청 7종이 조용히 slice 로 내려갔다. 신설을
# 부탁하는 말투는 동사가 없기도 하다 — "we need a new page", "new screen please".
SHAPE_WANT: tuple[dict, ...] = (
    {"req": "we need a new page", "lang": "en"},
    {"req": "a new endpoint is needed", "lang": "en"},
    {"req": "spin up a new billing service", "lang": "en"},
    {"req": "make a new page", "lang": "en"},
    {"req": "set up a new service", "lang": "en"},
    {"req": "I want a new feature", "lang": "en"},
    {"req": "new screen please", "lang": "en"},
    {"req": "we need a new admin page", "lang": "en"},
    {"req": "신규 엔드포인트 하나 파줘", "lang": "ko"},
    {"req": "정산 페이지 추가해줘", "lang": "ko"},
)

# 형상 구멍 — 신설 요청인데 이 층이 못 잡는 것. 하한이 없다: 고치라는 뜻이 아니라 **값을 보라는**
# 뜻이다. 한국어 `{표면}을 새로 {동사}` 갈래를 26-08-13 에 넣었다가 지운 자리가 여기 산다
# (`skill_scope._FEATURE_PAT` 의 결정 기록 참고). 구멍을 배터리에서 지우면 다음 사람이 그것이
# 있었다는 사실도 못 보므로, 지우지 않고 매 실행이 찍게 남긴다.
SHAPE_GAP: tuple[dict, ...] = (
    {"req": "결제 정산 화면을 새로 만들어줘", "lang": "ko"},
    {"req": "그 화면 새로 하나 뽑아줘", "lang": "ko"},
    {"req": "모듈을 새로 만들어 주세요", "lang": "ko"},
    {"req": "페이지를 새로 만들자", "lang": "ko"},
    {"req": "서비스를 새로 구현해줘", "lang": "ko"},
    # `신규` 갈래는 살아 있지만 수식어가 끼면 못 잡는다 — 퀘스트 이전에도 그랬다.
    {"req": "신규 정산 화면 하나 만들어줘", "lang": "ko"},
)

ROLES = ("worker", "thor", "freyja", "eitri", "mimir")
NEW_SKILLS = ("escort", "inquiry", "lost")

# 하한 — `--check` 가 이 아래로 내려가면 exit 2. 회귀를 잡는 바닥이지 목표치가 아니다.
FLOORS = {
    "reach": 1.0,
    "precision": 1.0,
    "shape_naming": 1.0,
    "shape_precision": 1.0,
    "shape_recall": 1.0,
    "latency_ms_p50": 120.0,
}


def _resolved(root: str, request: str, agent: str = "worker") -> list[str]:
    return [name for name, _ in skill_registry.resolve_skills(root, request, agent)]


def measure_reach(root: str) -> dict:
    rows, hits, total = [], 0, 0
    misfires, denials = 0, 0
    by_lang: dict[str, list[int]] = {"ko": [], "en": []}
    for case in CASES:
        got = _resolved(root, case["req"])
        if "want" in case:
            ok = case["want"] in got
            hits += ok
            total += 1
            by_lang[case["lang"]].append(int(ok))
            rows.append({"req": case["req"], "lang": case["lang"], "want": case["want"], "got": got, "ok": ok})
        else:
            bad = [name for name in case["deny"] if name in got]
            denials += 1
            misfires += bool(bad)
            rows.append(
                {"req": case["req"], "lang": case["lang"], "deny": list(case["deny"]), "got": got, "ok": not bad}
            )
    return {
        "reach": hits / total if total else 0.0,
        "reach_ko": statistics.fmean(by_lang["ko"]) if by_lang["ko"] else 0.0,
        "reach_en": statistics.fmean(by_lang["en"]) if by_lang["en"] else 0.0,
        "precision": 1.0 - (misfires / denials if denials else 0.0),
        "cases": total + denials,
        "rows": rows,
    }


def measure_semantic(root: str) -> dict:
    """트리거 낱말이 없는 요청에서 결정론 층이 어디까지 닿는가 — 하한이 아니라 천장 측정."""
    catalog = {row["name"]: row["description"] for row in skill_registry.skills(root)}
    rows, hits = [], 0
    for case in SEMANTIC_CASES:
        got = _resolved(root, case["req"])
        ok = case["want"] in got
        hits += ok
        # 결정론 층이 놓쳤을 때 모델이 대신 읽는 것이 이 설명이다. 사람이 판단할 수 있게 같이 낸다.
        rows.append(
            {
                "req": case["req"],
                "lang": case["lang"],
                "want": case["want"],
                "got": got,
                "ok": ok,
                "catalog_description": catalog.get(case["want"], ""),
            }
        )
    return {"semantic_reach": hits / len(SEMANTIC_CASES), "semantic_rows": rows}


def measure_shape(root: str) -> dict:
    cls = {"write_expected": True, "task_class": "standard"}
    rows, hits = [], 0
    for case in SHAPE_CASES:
        note = skill_scope.scope_note(root, case["req"], cls)
        named = [name for name in case["must_name"] if name in note]
        ok = len(named) == len(case["must_name"])
        hits += ok
        rows.append({"req": case["req"], "shape": case["shape"], "named": named, "ok": ok, "note_chars": len(note)})
    kept = 0
    for case in SHAPE_DENY:
        shape = skill_scope.work_shape(case["req"], cls)["shape"]
        ok = shape == "slice"
        kept += ok
        rows.append({"req": case["req"], "shape": shape, "must_be": "slice", "ok": ok})
    promoted = 0
    for case in SHAPE_WANT:
        shape = skill_scope.work_shape(case["req"], cls)["shape"]
        ok = shape == "feature"
        promoted += ok
        rows.append({"req": case["req"], "shape": shape, "must_be": "feature", "ok": ok})
    gap_rows, closed = [], 0
    for case in SHAPE_GAP:
        shape = skill_scope.work_shape(case["req"], cls)["shape"]
        closed += shape == "feature"
        gap_rows.append({"req": case["req"], "lang": case["lang"], "shape": shape})
    return {
        "shape_naming": hits / len(SHAPE_CASES),
        "shape_precision": kept / len(SHAPE_DENY),
        "shape_recall": promoted / len(SHAPE_WANT),
        "shape_gap": closed / len(SHAPE_GAP),
        "shape_rows": rows,
        "shape_gap_rows": gap_rows,
    }


def measure_load(root: str) -> dict:
    """턴당 상시 부하 — 그 역할에 열린 model 호출 스킬의 이름+설명 글자 수."""
    per_role, new_cost = {}, {}
    for role in ROLES:
        rows = skill_registry.available_skills(root, role)
        per_role[role] = sum(len(row["name"]) + len(row["description"]) for row in rows)
        new_cost[role] = sum(len(row["name"]) + len(row["description"]) for row in rows if row["name"] in NEW_SKILLS)
    return {"catalog_chars": per_role, "new_skill_chars": new_cost}


def measure_latency(root: str, iters: int = 12) -> dict:
    samples = []
    for index in range(iters):
        case = CASES[index % len(CASES)]
        start = time.perf_counter()
        _resolved(root, case["req"])
        samples.append((time.perf_counter() - start) * 1000)
    warm = samples[2:] or samples  # 앞 둘은 매니페스트 읽기가 섞인 콜드
    return {"latency_ms_p50": statistics.median(warm), "latency_ms_max": max(warm), "iters": len(warm)}


def run(root: str) -> dict:
    result = {
        **measure_reach(root),
        **measure_semantic(root),
        **measure_shape(root),
        **measure_load(root),
        **measure_latency(root),
    }
    result["violations"] = [
        f"{key} {result[key]:.3f} < {floor}" if key != "latency_ms_p50" else f"{key} {result[key]:.1f}ms > {floor}ms"
        for key, floor in FLOORS.items()
        if (result[key] > floor if key == "latency_ms_p50" else result[key] < floor)
    ]
    return result


def _print(result: dict) -> None:
    total = (
        result["cases"] + len(SEMANTIC_CASES) + len(SHAPE_CASES) + len(SHAPE_DENY) + len(SHAPE_WANT) + len(SHAPE_GAP)
    )
    print(
        f"\n  스킬 도달 실측 — 사례 {total}건 (트리거 {result['cases']} · 의미 {len(SEMANTIC_CASES)} · 형상 {len(SHAPE_CASES) + len(SHAPE_DENY) + len(SHAPE_WANT) + len(SHAPE_GAP)})\n"
    )
    print(f"  reach      {result['reach']:.0%}   (ko {result['reach_ko']:.0%} · en {result['reach_en']:.0%})")
    print(f"  precision  {result['precision']:.0%}   비트리거에서 새 스킬이 뜨지 않는 비율")
    print(f"  semantic   {result['semantic_reach']:.0%}   트리거 낱말 없는 요청 (하한 아님 — 결정론 층의 천장)")
    print(f"  shape      {result['shape_naming']:.0%}   형상 노트가 사용자 호출 스킬 이름을 대는 비율")
    print(f"  shape-prec {result['shape_precision']:.0%}   한 조각짜리 요청이 feature 로 안 올라가는 비율")
    print(f"  shape-rec  {result['shape_recall']:.0%}   신설 표면 요청이 feature 로 올라가는 비율")
    print(f"  shape-gap  {result['shape_gap']:.0%}   이 층이 못 잡는 신설 요청 (하한 아님 — 남은 구멍의 크기)")
    print(f"  latency    {result['latency_ms_p50']:.1f}ms p50 · {result['latency_ms_max']:.1f}ms max\n")
    print("  턴당 상시 부하 (이름+설명 글자):")
    for role, chars in result["catalog_chars"].items():
        added = result["new_skill_chars"][role]
        print(f"    {role:<8} {chars:>6}   이번에 느는 것 +{added}")
    print("\n  이 층이 못 잡는 신설 요청 — 구멍의 실물:")
    for row in result["shape_gap_rows"]:
        print(f"    [{row['shape']}] {row['req']}")
    print("\n  트리거 낱말 없는 요청 — 결정론 층이 놓치면 모델이 이 설명을 읽고 고른다:")
    for row in result["semantic_rows"]:
        mark = "닿음" if row["ok"] else "결정론 밖"
        print(f"    [{mark}] {row['req']}")
        print(f"        {row['want']}: {row['catalog_description'][:96]}")
    missed = [row for row in result["rows"] if not row["ok"]]
    if missed:
        print("\n  놓친 사례:")
        for row in missed:
            want = row.get("want") or f"deny={row.get('deny')}"
            print(f"    [{row['lang']}] {row['req']}\n        기대 {want} · 실제 {row['got']}")
    print()
    if result["violations"]:
        print("  하한 위반: " + "; ".join(result["violations"]) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the measurement as JSON")
    parser.add_argument("--check", action="store_true", help="exit 2 when a floor is violated")
    args = parser.parse_args()
    result = run(str(REPO))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print(result)
    return 2 if (args.check and result["violations"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
