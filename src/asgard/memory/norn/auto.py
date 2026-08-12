"""트리거와 자율 등급 — 언제 손질할지, 무엇까지 스스로 할지.

`_memory_settings`를 읽는 자리가 여기 모여 있다 (문턱·간격·`norn_auto`·`norn_insight_auto`).
호출면이 보는 손잡이도 여기다: `wake` 하나가 판정·등급 분기·latch·스폰을 전부 쥔다.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib

from ..policy import _memory_settings, memory_dir
from ..store import _today, ensure_home
from .apply import apply_norn
from .insight import INSIGHT_AUTO_FLOOR
from .plan import plan_norn
from .state import _load_state, _log_lines, _save_state

OPS_THRESHOLD = 25  # log.md 신규 연산 누적 문턱 — config [memory].norn_ops_threshold
MIN_INTERVAL_DAYS = 3  # 노른 간 최소 간격 — config [memory].norn_min_interval_days


def _settings_int(key: str, default: int) -> int:
    try:
        v = _memory_settings().get(key)
        return max(1, int(v)) if v is not None else default
    except Exception:
        return default


def norn_due(d: str | None = None) -> tuple[bool, str]:
    """트리거 판정 — (due, 사유). 연산 누적 문턱 + 최소 간격 — 활동이 쌓였을 때만 손질한다."""
    d = d or memory_dir()
    state = _load_state(d)
    threshold = _settings_int("norn_ops_threshold", OPS_THRESHOLD)
    interval = _settings_int("norn_min_interval_days", MIN_INTERVAL_DAYS)
    delta = _log_lines(d) - int(state.get("log_lines", 0))
    if delta < threshold:
        return False, f"연산 누적 {delta}/{threshold}건 — 아직 이르다"
    last = str(state.get("last_norn", ""))
    if last:
        try:
            days = (_dt.date.today() - _dt.date.fromisoformat(last[:10])).days
            if days < interval:
                return False, f"최근 노른 {days}일 전 — 최소 간격 {interval}일"
        except ValueError:
            pass
    return True, f"연산 누적 {delta}건 (문턱 {threshold})"


# ── 자율 계층 (오딘 결정 26-07-24: "추가는 자율, 파괴는 동의") ─────────────────────
#
# 스스로 기록하며 성장하되, 되돌릴 수 없는 것은 손대지 않는다:
# 완전 가역·순수 추가인 op는 자율로 기록하고, 위키의 형태를 바꾸는
# op(병합·보관)는 제안으로 남긴다. 스킬 승인 게이트(CUS-251)는 이 계층과 무관하게 불변 —
# 여기서 자율화되는 것은 advisory 지식(개인 위키)뿐이고, 그마저 스캔·플로어·캡을 통과한
# 것만이다. 게이트는 여전히 어떤 메모리도 완료 증거로 신뢰하지 않는다.
#
#   off  — 자율 없음: 전부 제안 (넛지만)
#   safe — contradiction(보고 전용)만 자동, 기본값
#   full — merge·archive까지 자동 (백업+복원 가능하지만 형태 변경 — 명시 선택)
#
# 통찰(insight)은 어느 모드에도 기본으로 들어가지 않는다. 26-07-28 판정:
#
# 통찰을 자동에서 뺀 것은 게이트가 약해서가 아니라 **게이트가 답할 수 없는 물음이라서**다.
# 검증기가 결정론으로 답할 수 있는 것은 "이 문장이 출처에서 왔는가"(근거 대조)와 "출처의 주장을
# 뒤집었는가"(극성)까지다. "출처에서 왔고, 뒤집지도 않았는데, 그래도 틀린 추론"은 결정론이
# 잡을 수 있는 모양이 아니다 — 귀납의 비약은 형상이 없다.
#
# 가역성은 이 자리에서 자격이 되지 못한다. remove로 지울 수 있다는 사실은, 허구가 정본
# 자리에 앉아 회수에 섞여 나가고 다른 통찰의 출처가 되던 시간을 되돌려 주지 않는다.
# 그래서 기본은 "접수하되 사람이 연다"이고, 자동은 그 비용을 아는 사람이 켜는 것이다:
#
#   [memory] norn_insight_auto = true   — 켜도 근거 점수가 INSIGHT_AUTO_FLOOR 이상 + 극성 충돌
#                                          없음만 자동이고, mode=off 에서는 여전히 안 켜진다.

AUTO_MODES = ("off", "safe", "full")
_AUTO_OPS = {
    "off": frozenset(),
    "safe": frozenset({"contradiction"}),
    "full": frozenset({"merge", "archive", "contradiction"}),
}


def auto_mode() -> str:
    """노른 자율 모드 — config [memory].norn_auto ∈ off|safe|full (기본 safe)."""
    try:
        v = str(_memory_settings().get("norn_auto", "safe")).strip().lower()
        return v if v in AUTO_MODES else "safe"
    except Exception:
        return "safe"


def insight_auto() -> bool:
    """통찰 자동 승격 옵트인 — config [memory].norn_insight_auto (기본 false).

    기본이 false 인 이유는 위 주석에 있다. 이 스위치는 "검증기를 믿는다"가 아니라
    "검증기가 못 잡는 오류를 내가 감당한다"는 선언이다."""
    try:
        value = _memory_settings().get("norn_insight_auto", False)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    except Exception:
        return False


def partition_ops(ops: list[dict], mode: str, *, allow_insight: bool | None = None) -> tuple[list[dict], list[dict]]:
    """검증 통과 op를 (자동 적용분, 제안 잔류분)으로 가른다 — 모드가 자격을 정하되,
    통찰은 모드만으로 자격을 얻지 못한다: 옵트인 + 근거가 짙어야 자동이다.

    allow_insight를 명시하면 설정을 덮는다 (테스트·호출측 정책용)."""
    allowed = _AUTO_OPS.get(mode, frozenset())
    opted_in = insight_auto() if allow_insight is None else allow_insight

    def _eligible(op: dict) -> bool:
        if op["op"] == "insight":
            # 옵트인 + 모드가 자율을 허용 + 극성 무충돌 + 근거가 짙음. 넷 다여야 자동이다.
            if not opted_in or not allowed or op.get("polarity_conflict"):
                return False
            # 근거 점수 없는 통찰 = 검증기를 안 거친 통찰. 모르면 자동으로 넣지 않는다.
            with contextlib.suppress(TypeError, ValueError):
                return float(op.get("grounding") or 0.0) >= INSIGHT_AUTO_FLOOR
            return False
        return op["op"] in allowed

    auto = [op for op in ops if _eligible(op)]
    proposed = [op for op in ops if not _eligible(op)]
    return auto, proposed


def run_auto(root: str, d: str | None = None) -> dict:
    """자율 노른 1회 — due 판정 → 계획 → 모드 자격분만 적용, 잔류분은 제안으로 보고.

    비-due 여도 강제하지 않는다 (호출측이 due를 확인하고 부르는 것이 정상 경로지만,
    수동 `norn --auto`는 즉시 실행을 원하므로 due를 다시 막지 않는다)."""
    d = ensure_home(d)
    mode = auto_mode()
    plan = plan_norn(root, d)
    auto_ops, proposed = partition_ops(plan["ops"], mode)
    if auto_ops or proposed or plan["dropped"]:
        # 제안·기각뿐이어도 리포트는 남긴다 — 백그라운드 런의 결과가 침묵 속에 사라지지 않는다
        result = apply_norn(d, {"ops": auto_ops, "dropped": plan["dropped"], "proposed": proposed})
    else:
        result = {"applied": [], "failed": [], "backup": "", "report": ""}
        state = _load_state(d)  # 무수확 런도 상태는 전진 — 같은 누적으로 재발화하지 않는다
        state.update({"last_norn": _today(), "log_lines": _log_lines(d)})
        _save_state(d, state)
    return {
        "mode": mode,
        "applied": result["applied"],
        "failed": result["failed"],
        "proposed": proposed,
        "report": result["report"],
    }


# ── wake (호출면 단일 출처 — 훅·네이티브 루프가 같은 판정을 쓴다) ─────────────────


def wake(root: str, d: str | None = None) -> str | None:
    """턴·퀘스트가 끝난 자리에서 부르는 손질 신호 — 사람에게 보일 한 줄 또는 None(침묵).

    **왜 함수인가.**이 판정은 호출면마다 다시 쓰면 안 된다. 개인 메모리는 소유자의 기억이라
    어느 호스트에서 일하든 같은 속도로 손질돼야 하는데(policy.CLIENT_MODES 주석), 등급 분기와
    latch를 표면마다 따로 구현하면 호스트에 따라 위키가 다르게 자란다. 훅(`memory norn
    --wake`)과 네이티브 루프가 여기 하나를 본다.

    **비싼 일은 여기서 안 한다.** due 판정은 log.md 행 수와 state 파일만 읽는다 — LLM도
    임베더도 안 뜬다. 실제 손질(plan_norn의 LLM 왕복)은 분리 스폰한 자식이 맡는다:
    호출자의 턴은 그 사이 그냥 끝난다.

    동의 경계는 `norn_auto` 등급이 쥐고 있지 이 함수가 쥐고 있지 않다 — off는 넛지만,
    기본 safe는 보고 전용(contradiction)까지, full 이라야 병합·보관이 자동이다."""
    d = ensure_home(d)
    due, reason = norn_due(d)
    if not due:
        return None
    mode = auto_mode()
    if mode == "off":
        return nudge_line(d)
    state = _load_state(d)
    digest = str(_log_lines(d))
    if state.get("auto_spawn_digest") == digest:
        return None  # 같은 누적 상태로 이미 스폰 — 중복 백그라운드 방지
    state["auto_spawn_digest"] = digest
    _save_state(d, state)
    if not spawn_pass(root, "memory", "norn", "--auto"):
        return None  # 스폰 못 했으면 말도 안 한다 — 시작하지 않은 일을 시작했다고 하지 않는다
    return f"위그드라실 노른 자동 통합 시작 — {reason} (모드 {mode}: 추가는 자율, 병합·보관은 제안)"


def spawn_pass(root: str, *args: str) -> bool:
    """자율 패스 하나를 분리 스폰 — 호출자의 수명과 끊는다 (훅 타임아웃·턴 종료 무관).

    노른만의 손잡이가 아니다. 자율 패스는 넷이고(노른·패턴·2차 진화·프로젝트 학습) 넷 다 같은 자리에서
    같은 이유로 떨어져야 한다 — 표면마다 Popen을 다시 쓰면 아래 두 계약 중 하나가 조용히
    빠진 사본이 생긴다.

    **에이전트를 env로 명시해서 넘긴다.** `profiles.scoped()`는 contextvar라 자식에게 안 따라간다
    — 안 넘기면 이 자식은 끈끈한 활성 에이전트로 떨어져, 에이전트 A로 돌던 세션의 기억을 B의
    위키에 쓴다. 턴마다 도는 자식이라 조용히 쌓이고, 기억은 되돌리기가 가장 어렵다
    (hermes 이슈 18594가 같은 사고였다).

    **시간 상한 표식은 떼고 넘긴다** (`memory_semantic.detached_env`). 훅이 켠
    `ASGARD_MEMORY_NO_DOWNLOAD` 는 부모의 시계를 뜻하는데 이 자식은 그 밖에서 돌고, 물려받으면
    위키를 쓰면서 벡터를 안 만들어 vec_coverage 가 조용히 썩는다."""
    import shutil as _shutil
    import subprocess
    import sys

    from ...memory_semantic import detached_env
    from ...profiles import subprocess_env

    exe = _shutil.which("asgard") or sys.argv[0]
    try:
        subprocess.Popen(
            [exe, *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=root or None,
            env=detached_env(subprocess_env()),
        )
    except Exception:
        return False
    return True


# ── 넛지 (latch — 제안 피로 방지) ──────────────────────────────────────────────


def nudge_line(d: str | None = None) -> str | None:
    """노른이 due 이고 같은 누적 상태로 아직 말하지 않았을 때만 한 줄. 그 외 None."""
    d = d or memory_dir()
    due, reason = norn_due(d)
    if not due:
        return None
    state = _load_state(d)
    digest = hashlib.sha1(f"{_log_lines(d)}".encode()).hexdigest()[:12]
    if state.get("nudge_digest") == digest:
        return None
    state["nudge_digest"] = digest
    _save_state(d, state)
    return f"위그드라실 노른 제안 — {reason}. asgard memory norn으로 통합 검토 (--apply 전엔 무변경)"
