"""asgard budget — 이 세션이 얼마나 썼는지의 사람 표면.

왜 게이트만으론 부족한가: 상한은 벽이고, 벽은 부딪혀야 알게 된다. 부딪히고 나서야 아는 예산은
예산이 아니라 사고다. 이 화면의 계약은 **벽에 닿기 전에 보이게 하는 것** 하나다.

세 가지를 한 화면에 싣는다: ① 가중 비용 단위(판정에 실제로 쓰이는 값)와 남은 여유, ② 네 성분의
원시 값 — 가중치는 가정이고 가정이 바뀌어도 관측은 남아야 한다, ③ 레인별 귀속(메인 vs 역할별).
③ 이 없으면 "많이 썼다"는 알아도 "어디서 썼다"를 몰라 다음 세션이 똑같이 쓴다.
"""

from __future__ import annotations

import glob
import json
import os

from .. import ui
from ..hooks import budget_guard as bg


def _project_key(root: str) -> str:
    """Claude Code의 프로젝트 트랜스크립트 디렉터리 이름 — 경로 구분자를 `-`로 치환한 형태."""
    return os.path.abspath(root).replace(os.sep, "-").replace("_", "-")


def latest_transcript(root: str) -> str:
    """이 프로젝트의 가장 최근 트랜스크립트. 없으면 빈 문자열 — 추측해서 남의 세션을 읽지 않는다."""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    base = os.path.join(home, ".claude", "projects", _project_key(root))
    files = [p for p in glob.glob(os.path.join(base, "*.jsonl")) if os.path.isfile(p)]
    if not files:
        return ""
    return max(files, key=os.path.getmtime)


def _payload(ledger: bg.Ledger, limits: dict, spent: float) -> str:
    weights = limits.get("weights") if isinstance(limits.get("weights"), dict) else None
    total = ledger.total()
    return json.dumps(
        {
            "enforce": limits.get("enforce"),
            "cost_units": round(spent),
            "session_cost_units": limits.get("session_cost_units"),
            "warn_cost_units": limits.get("warn_cost_units"),
            "raw": {
                "input": total.input,
                "output": total.output,
                "cache_write": total.cache_write,
                "cache_read": total.cache_read,
            },
            "main_cost_units": round(ledger.main.cost_units(weights)),
            "agents": {
                role: {
                    "calls": ledger.agent_calls.get(role, 0),
                    "cost_units": round(usage.cost_units(weights)),
                }
                for role, usage in sorted(ledger.agents.items())
            },
            "agent_calls_without_usage": {
                role: n for role, n in sorted(ledger.agent_calls.items()) if role not in ledger.agents
            },
            "models": dict(sorted(ledger.models.items())),
            "read_error": ledger.read_error,
        },
        ensure_ascii=False,
        indent=2,
    )


def run_budget(*, transcript: str = "", json_out: bool = False, quiet: bool = False) -> int:
    """종료 코드 = 상한 도달이면 1, 경고면 0. 화면은 막지 않는다 — 막는 것은 훅의 일이다."""
    root = os.getcwd()
    ui.set_quiet(json_out or quiet)
    path = transcript or latest_transcript(root)
    limits = bg.load_limits(root)
    ledger = bg.read_ledger(path)
    weights = limits.get("weights") if isinstance(limits.get("weights"), dict) else None
    spent = ledger.cost_units(weights)
    result = bg.verdict(ledger, limits)

    if json_out:
        print(_payload(ledger, limits, spent))
        return 1 if result.action == "block" else 0

    ui.head("budget · 이 세션이 쓴 것")
    if not path:
        ui.warn("이 프로젝트의 트랜스크립트를 못 찾았다 — 계측할 세션이 없다")
        ui.done()
        return 0
    ui.step(ui.dim(f"트랜스크립트 {os.path.basename(path)}"))
    if ledger.read_error:
        ui.warn(f"부분 관측 — {ledger.read_error}")

    ceiling = float(limits.get("session_cost_units") or bg.DEFAULTS["session_cost_units"])
    warn_at = float(limits.get("warn_cost_units") or bg.DEFAULTS["warn_cost_units"])
    pct = (spent / ceiling * 100) if ceiling else 0.0
    line = f"가중 비용 단위 {spent:,.0f} / {ceiling:,.0f} ({pct:.0f}%)"
    (ui.warn if spent >= warn_at else ui.ok)(line)
    ui.step(ui.dim(f"    경고 문턱 {warn_at:,.0f} · 집행 {limits.get('enforce')}"))

    total = ledger.total()
    ui.phase("원시 성분 (가중치는 가정, 관측은 사실)")
    for label, value, weight in (
        ("입력", total.input, bg.WEIGHTS["input"]),
        ("출력", total.output, bg.WEIGHTS["output"]),
        ("캐시 쓰기", total.cache_write, bg.WEIGHTS["cache_write"]),
        ("캐시 읽기", total.cache_read, bg.WEIGHTS["cache_read"]),
    ):
        ui.step(f"{label:<10} {value:>14,d}  ×{weight}")

    if ledger.agent_calls:
        ui.phase("레인별 귀속")
        ui.step(f"{'main':<24} {ledger.main.cost_units(weights):>14,.0f}")
        for role, calls in sorted(ledger.agent_calls.items(), key=lambda kv: -kv[1]):
            usage = ledger.agents.get(role)
            spent_role = usage.cost_units(weights) if usage else 0.0
            note = "" if usage else "  (usage 미제공)"
            ui.step(f"{role:<24} {spent_role:>14,.0f}  ×{calls}회{note}")

    if result.action == "block":
        ui.warn(result.message)
    ui.done()
    return 1 if result.action == "block" else 0
