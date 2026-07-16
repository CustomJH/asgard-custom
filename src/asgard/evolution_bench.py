"""evolution_bench — learned 스킬 A/B 검증 하니스 (자가발전 C4, CUS-251 후속).

승인된 스킬이 실제로 도움이 되는지 개입(intervention)으로 실측한다: 같은 벤치 명령을
스킬 OFF(baseline) / ON(variant) 로 반복 실행해 METRIC 을 수집하고, MAD(중앙절대편차)
노이즈 플로어 대비 몇 배 개선인지로 keep/discard 를 판정한다.

설계 근거 (CUS-251 리서치):
- MAD confidence — run < 3 또는 MAD = 0 이면 confidence 없음
  (우연을 채택하지 않는다). 개선은 "노이즈의 몇 배"로만 말한다.
- 개입 검증 — SkillGen(arXiv 2605.10999): 스킬 채택은 성능에 양의 효과가 실측될 때만.
- 짧은 루프 — 판정은 1회 A/B 로 끝난다. 자율 반복 최적화 루프는 두지 않는다
  (리워드 해킹은 반복 길이에 비례 — ICLR 2026 RSI 실측).
- 계보 보존 — 모든 판정을 bench.jsonl 에 append (DGM 아카이브 원칙). 판정은 기록이고,
  archive 실행은 여전히 사용자 몫 (자동 처분 없음).

벤치 명령 계약: 명령은 stdout 에 `METRIC <name>=<float>` 한 줄을 출력한다 (마지막 매치 채택).
baseline 런에는 ASGARD_LEARNED_DISABLE=<skill> 이 주입된다 — resolve_learned 가 이를 존중한다.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import time
from typing import Callable

_CONF_THRESHOLD = 2.0  # 노이즈 플로어의 2배 이상 차이만 유의미로 판정
_METRIC_PAT = "METRIC {name}="


def mad(xs: list[float]) -> float:
    """중앙절대편차 — 노이즈 플로어. 표준편차보다 아웃라이어(1회 튄 런)에 강건하다."""
    if not xs:
        return 0.0
    med = statistics.median(xs)
    return statistics.median(abs(x - med) for x in xs)


def confidence(baseline: list[float], variant: list[float]) -> float | None:
    """|중앙값 차| / MAD(baseline) — run < 3 또는 MAD = 0 이면 None (판정 불가, 우연 배제 불능)."""
    if len(baseline) < 3 or len(variant) < 3:
        return None
    floor = mad(baseline)
    if floor == 0:
        return None
    return abs(statistics.median(variant) - statistics.median(baseline)) / floor


def _parse_metric(stdout: str, name: str) -> float | None:
    hits = re.findall(rf"^METRIC\s+{re.escape(name)}=([-+0-9.eE]+)\s*$", stdout, re.MULTILINE)
    try:
        return float(hits[-1]) if hits else None
    except ValueError:
        return None


def _shell_runner(root: str, cmd: str, metric: str, timeout: int) -> Callable[[str], float | None]:
    def run(disable: str) -> float | None:
        env = {**os.environ, "ASGARD_LEARNED_DISABLE": disable}
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=root, env=env, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            return None
        return _parse_metric(proc.stdout, metric)

    return run


def run_ab(
    root: str,
    skill: str,
    cmd: str,
    metric: str,
    runs: int = 5,
    direction: str = "min",
    timeout: int = 600,
    runner: Callable[[str], float | None] | None = None,
) -> dict:
    """스킬 OFF/ON A/B — 판정 레코드 반환 + bench.jsonl append.

    runner(disable) 는 1회 실행해 metric 값을 반환 (테스트 주입점 — 기본은 shell 실행).
    verdict: keep(스킬이 유의미하게 낫다) / discard(유의미하게 나쁘다) / inconclusive."""
    run = runner or _shell_runner(root, cmd, metric, timeout)
    baseline = [v for v in (run(skill) for _ in range(runs)) if v is not None]
    variant = [v for v in (run("") for _ in range(runs)) if v is not None]
    conf = confidence(baseline, variant)
    verdict = "inconclusive"
    if conf is not None and conf >= _CONF_THRESHOLD:
        better = (
            statistics.median(variant) < statistics.median(baseline)
            if direction == "min"
            else statistics.median(variant) > statistics.median(baseline)
        )
        verdict = "keep" if better else "discard"
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "skill": skill,
        "cmd": cmd,
        "metric": metric,
        "direction": direction,
        "runs": runs,
        "baseline": baseline,
        "variant": variant,
        "baseline_median": statistics.median(baseline) if baseline else None,
        "variant_median": statistics.median(variant) if variant else None,
        "mad": mad(baseline) if baseline else None,
        "confidence": conf,
        "verdict": verdict,
    }
    d = os.path.join(root, ".asgard", "evolution")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "bench.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
