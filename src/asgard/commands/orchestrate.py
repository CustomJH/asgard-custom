"""asgard orchestrate — 오케스트레이션을 **어떻게 돌릴지** 고르는 자리, 그리고 그 전제인
엔진 준비 상태를 보는 자리.

이 명령이 생긴 이유는 하나다. 아스가르드는 이미 오케스트레이션을 갖고 있었지만(Run·Task·
Dispatch), 그것을 어떤 모양으로 돌릴지는 분류 신호가 혼자 정했고 역할별 모델은 사람이
`trinity.<role>` 을 손으로 적어야만 갈렸다. 즉 "엔진이 여럿 준비돼 있으면 알아서 나눠 쓴다" 가
없었다 — 준비돼 있어도 아무도 안 썼다.

기본값은 `auto` 다. 아스가르드가 형상도 배치도 스스로 정하되 **지금 실제로 닿는 엔진만** 쓴다.
닿는지 먼저 재는 것이 이 기능의 전제다: 닿지 않는 엔진에 역할을 앉히는 것은 배치가 아니라
**지연된 실패**이고, 그 실패는 사람이 일을 시작한 뒤에야 드러나서 가장 비싸다.

화면이 정책과 엔진을 **같은 자리에** 놓는 이유도 같다. 둘을 다른 화면에 두면 "auto 인데 왜
안 나뉘지"의 답이 다른 화면에 있게 된다 — 그러면 사람은 정책을 의심하고, 정작 원인인 엔진
하나가 안 닿는 사실은 끝까지 안 본다.

세 어휘를 섞지 않는다. `asgard mode` 는 **어디서** 도는가(native·claude·codex·cursor),
`strategy` 의 형상은 이 요청이 **어떤 모양**인가(direct·single·graph·squad), 그리고 여기서
고르는 정책은 **얼마나 오케스트레이션할 것인가**다. 이름이 겹치면 세 설정이 한 설정으로 읽힌다.
"""

from __future__ import annotations

import json
import os

from .. import ui
from .health import _project_root

# 정책의 뜻 — 화면에 그대로 나간다. 엔진(`orchestration.policy`)이 값을 갖고, 사람 말은 여기
# 표면이 갖는다. 엔진에 두면 재료와 표현이 한 자리에 섞이고, 그러면 `--json` 소비자가 한국어
# 설명까지 받게 된다.
#
# 문장은 `commands/studio/orchestration.py` 의 POLICY_LABEL 과 같아야 한다 — 표가 둘인 것은
# 위 이유 때문이지 뜻이 둘이어서가 아니다. 갈려 있던 동안 CLI 는 squad 를 "전문 영역이 갈리면
# 여럿이 나눠 든다"고만 적어 되돌림(형상을 못 만들면 다른 형상으로 내려간다)을 감췄고, 창은
# 그 되돌림을 적고 있었다. 한쪽만 고치면 같은 값이 화면마다 다른 약속이 된다.
POLICY_HELP = {
    "auto": "아스가르드가 형상과 배치를 스스로 정해요 — 지금 닿는 엔진만 후보로 써요 (기본값)",
    "solo": "엔진 하나로만 돌려요 — 역할을 나눠 맡기지 않아요",
    "graph": "갈래(그래프) 형상을 먼저 써요 — 배정 단위가 하나뿐이면 다른 형상으로 돌려요",
    "squad": "편대 형상을 먼저 써요 — 못 만들면 다른 형상으로 돌리고 이유를 남겨요",
    "off": "오케스트레이션을 쓰지 않아요 — 항상 곧장 실행해요",
}
_MARK = {True: "●", False: "○"}


def _engines_mod():
    """엔진 계량기를 늦게 부른다. 없으면 None — 표면이 엔진보다 먼저 배송될 수 있다."""
    try:
        from .. import engines

        return engines
    except Exception:
        return None


def _policy_mod():
    try:
        from ..orchestration import policy

        return policy
    except Exception:
        return None


def _current(root: str) -> tuple[str, str]:
    policy = _policy_mod()
    if policy is None:
        return ("auto", "built-in default")
    try:
        return policy.current(root)
    except Exception:
        return ("auto", "built-in default")


def _engine_rows(root: str, probe: bool) -> tuple[list, str]:
    """(엔진 목록, 못 잰 이유). `probe` 가 아니면 **네트워크를 안 탄다** — 캐시만 읽는다.

    기본을 캐시로 두는 이유: 이 명령은 정책을 고치러 들어오는 자리이고, 그때마다 엔진 전부에
    네트워크를 태우면 설정 한 줄 바꾸는 데 몇 초가 든다. 다시 재는 것은 사람이 시킬 때만 한다.
    """
    engines = _engines_mod()
    if engines is None:
        return ([], "엔진 상태를 재는 기능이 아직 없어요")
    try:
        return (list(engines.probe(root, force=True) if probe else engines.cached(root)), "")
    except Exception as exc:
        return ([], f"{type(exc).__name__}: {exc}")


def _payload(root: str, policy_name: str, source: str, rows: list, why: str) -> str:
    return json.dumps(
        {
            "root": os.path.realpath(root),
            "policy": policy_name,
            "source": source,
            "policies": [{"name": k, "help": v} for k, v in POLICY_HELP.items()],
            "engines": [
                {
                    "name": getattr(e, "name", ""),
                    "display": getattr(e, "display", ""),
                    "configured": bool(getattr(e, "configured", False)),
                    "reachable": bool(getattr(e, "reachable", False)),
                    "detail": getattr(e, "detail", ""),
                    "models": list(getattr(e, "models", ()) or ()),
                    "checked": getattr(e, "checked", 0.0),
                }
                for e in rows
            ],
            "unmeasured": why,
        },
        ensure_ascii=False,
        indent=2,
    )


def _emit_policy(policy_name: str, source: str) -> None:
    ui.phase(f"지금 정책 — {policy_name} ({source})")
    ui.step(ui.dim(f"    {POLICY_HELP.get(policy_name, '')}"))


def _emit_engines(rows: list, why: str, probed: bool) -> None:
    """연결된 것과 안 된 것을 **같은 화면에** 놓는다. 안 된 것을 숨기면 "auto 인데 왜 안 나뉘지"
    의 답이 화면 밖으로 나가고, 그러면 사람은 정책을 의심하게 된다."""
    if why:
        ui.phase("엔진 준비 상태")
        ui.warn(why)
        return
    if not rows:
        ui.phase("엔진 준비 상태")
        ui.ok("아직 잰 적이 없어요 — `asgard orchestrate --probe`로 확인해 보세요")
        return
    ready = [e for e in rows if getattr(e, "reachable", False)]
    ui.phase(f"엔진 준비 상태 — 연결됨 {len(ready)}/{len(rows)}" + ("" if probed else " (마지막으로 잰 값)"))
    for engine in rows:
        live = bool(getattr(engine, "reachable", False))
        line = f"{_MARK[live]} {getattr(engine, 'display', '') or getattr(engine, 'name', '')}"
        (ui.step if live else ui.warn)(line)
        detail = getattr(engine, "detail", "")
        if detail:
            ui.step(ui.dim(f"    {detail}"))
    _emit_auto_note(len(ready))


def _emit_auto_note(ready: int) -> None:
    """auto 가 이 숫자로 무엇을 할 것인지 미리 말해 준다 — 설정 화면에서 결과를 예고하지 않으면
    사람은 일을 시켜 본 뒤에야 자기 설정이 무엇을 뜻했는지 안다."""
    if ready == 0:
        ui.step(ui.dim("    닿는 엔진이 없어요 — auto라도 나눌 수가 없어요. 먼저 엔진을 연결해 주세요"))
    elif ready == 1:
        ui.step(ui.dim("    닿는 엔진이 하나라 auto는 세 역할을 전부 거기에 앉혀요"))
    elif ready == 2:
        ui.step(ui.dim("    auto는 검증을 작업과 다른 엔진에 앉혀요 — 같은 모델은 자기가 놓친 걸 또 놓쳐요"))
    else:
        ui.step(ui.dim("    auto는 계획·작업·검증을 서로 다른 엔진에 갈라 앉혀요"))


def run_orchestrate(
    *,
    set_policy: str = "",
    scope: str = "project",
    probe: bool = False,
    json_out: bool = False,
    quiet: bool = False,
) -> int:
    """종료 코드는 언제나 0 — 설정을 보여 주는 자리는 관문이 아니다(`mode` 와 같은 등급)."""
    root = _project_root(os.getcwd())
    ui.set_quiet(json_out or quiet)
    if set_policy:
        return _run_set(root, set_policy, scope, json_out)
    policy_name, source = _current(root)
    rows, why = _engine_rows(root, probe)
    if json_out:
        print(_payload(root, policy_name, source, rows, why))
        return 0
    ui.head("orchestrate · 오케스트레이션을 어떻게 돌릴까요")
    _emit_policy(policy_name, source)
    _emit_engines(rows, why, probe)
    ui.phase("고를 수 있는 것")
    for name, help_text in POLICY_HELP.items():
        mark = "▸" if name == policy_name else " "
        ui.step(f"{mark} {name} — {help_text}")
    ui.step(ui.dim("    바꾸기: `asgard orchestrate --set auto` · 모든 프로젝트에: `--set auto --global`"))
    if not probe:
        ui.step(ui.dim("    엔진을 지금 다시 확인: `asgard orchestrate --probe`"))
    ui.done()
    return 0


def _run_set(root: str, value: str, scope: str, json_out: bool) -> int:
    policy = _policy_mod()
    ui.head("orchestrate · 정책 바꾸기")
    if policy is None:
        ui.warn("아직 정책 엔진이 없어요")
        ui.done()
        return 0
    try:
        path = policy.set_policy(root, value, scope)
    except ValueError as exc:
        # 잘못된 값에 종료 코드를 주지 않는 이유: 이 명령은 판정기가 아니라 설정 표면이다.
        # 대신 고를 수 있는 것을 그 자리에서 다시 보여 준다 — 사람이 다시 찾아보지 않게.
        ui.warn(str(exc))
        ui.step(ui.dim(f"    고를 수 있는 값: {' · '.join(POLICY_HELP)}"))
        ui.done()
        return 0
    if json_out:
        print(json.dumps({"policy": value, "scope": scope, "saved": path}, ensure_ascii=False))
        return 0
    ui.ok(f"정책을 바꿨어요 — {value}: {POLICY_HELP.get(value, '')}")
    ui.step(ui.dim(f"    적은 자리: {os.path.relpath(path, root) if path.startswith(root) else path}"))
    ui.done()
    return 0
