"""사용자 오케스트레이션 정책을 형상과 닿는 엔진 배치로 옮긴다."""

from __future__ import annotations

from dataclasses import dataclass

from . import strategy

POLICIES = ("auto", "solo", "graph", "squad", "off")
DEFAULT = "auto"


@dataclass(frozen=True)
class Placement:
    role: str
    engine: str
    model: str
    why: str


@dataclass(frozen=True)
class Decision:
    policy: str
    shape: str
    why: str
    placements: tuple[Placement, ...]
    degraded: str


def _policy(value: object) -> str:
    selected = str(value or "").strip().lower()
    if selected not in POLICIES:
        raise ValueError(f"policy는 {'/'.join(POLICIES)} 중 하나예요")
    return selected


def current(root: str) -> tuple[str, str]:
    """(정책, 출처). 프로젝트가 글로벌을 덮고, 잘못된 수동 설정은 기본값으로 내려간다."""
    from ..settings import load_global, load_project

    for source, config in (("project", load_project(root)), ("global", load_global())):
        section = config.get("orchestration")
        value = section.get("policy") if isinstance(section, dict) else None
        selected = str(value or "").strip().lower()
        if selected in POLICIES:
            return selected, source
    return DEFAULT, "built-in default"


def set_policy(root: str, value: str, scope: str = "project") -> str:
    """검증한 정책을 글로벌 또는 프로젝트 설정에 적고 그 파일 경로를 돌려준다."""
    selected = _policy(value)
    if scope not in {"global", "project"}:
        raise ValueError("scope는 global/project 중 하나예요")
    if scope == "global":
        from ..settings import save_global

        return save_global("orchestration", {"policy": selected})
    from ..providers import save_config_section

    return save_config_section(root, "orchestration", {"policy": selected})


def _shape(selected: str, signals: dict) -> tuple[str, str, str]:
    choice = strategy.choose(**signals)
    shape, why = choice["shape"], choice["why"]
    if selected == "off":
        return "direct", "off 정책이라 오케스트레이션을 사용하지 않아요", ""
    if selected == "solo":
        return ("direct", why, "") if shape == "direct" else ("single", "solo 정책이라 한 Worker 흐름으로 실행해요", "")
    if selected == "auto":
        return shape, why, choice["disagreement"]

    if shape == "direct":
        return shape, why, f"쓰기가 없어 {selected} 형상을 사용하지 않아요"
    unit_count = int(signals.get("unit_count", 0))
    planned = bool(signals.get("planned", False))
    specialists = list(signals.get("specialists") or [])
    if selected == "graph":
        if planned and unit_count < 2:
            return shape, why, f"계획이 낸 배정 단위가 {unit_count}개라 graph 형상을 만들 수 없어요"
        return "graph", "graph 정책에 따라 그래프 실행을 우선해요", ""

    if unit_count >= 2:
        return shape, why, f"계획이 낸 배정 단위가 {unit_count}개라 squad 대신 graph로 실행해요"
    if len(specialists) < 2:
        return shape, why, "매칭된 전문 영역이 2개 미만이라 squad 형상을 만들 수 없어요"
    return "squad", "squad 정책에 따라 전문가 편대 실행을 우선해요", ""


def _ready(engines: list) -> list:
    ready, seen = [], set()
    for engine in engines:
        if engine.reachable and engine.name not in seen:
            ready.append(engine)
            seen.add(engine.name)
    return ready


def _place(role: str, engine, why: str) -> Placement:
    return Placement(role, engine.name, str(engine.models[0]) if engine.models else "", why)


def _placements(engines: list, solo: bool) -> tuple[tuple[Placement, ...], str]:
    ready = _ready(engines)
    if not ready:
        return (), "지금 닿는 엔진이 없어 역할을 배치하지 못했어요"
    worker = ready[0]
    if solo or len(ready) == 1:
        reason = "solo 정책이 기본 엔진 하나를 써요" if solo else "지금 닿는 엔진이 하나뿐이에요"
        return tuple(
            _place(role, worker, f"{reason} — {role} 역할을 맡겨요") for role in ("thinker", "worker", "verifier")
        ), ""

    verifier = ready[1]
    thinker = ready[2] if len(ready) >= 3 else worker
    thinker_why = (
        "worker·verifier와 다른 엔진에 독립 계획을 맡겨요"
        if len(ready) >= 3
        else "검증 독립성을 우선하고 기본 엔진에 계획을 맡겨요"
    )
    return (
        _place("thinker", thinker, thinker_why),
        _place("worker", worker, "첫 번째 닿는 엔진에 실행을 맡겨요"),
        _place("verifier", verifier, "worker와 다른 엔진에 독립 검증을 맡겨요"),
    ), ""


def decide(root: str, *, engines: list, policy: str = "", **signals) -> Decision:
    """정책과 닿는 엔진, strategy 분류 신호를 감사 가능한 실행 결정으로 만든다."""
    selected = _policy(policy) if policy else current(root)[0]
    shape, why, degraded = _shape(selected, signals)
    placements, placement_degraded = ((), "") if shape == "direct" else _placements(engines, selected == "solo")
    return Decision(
        selected,
        shape,
        why,
        placements,
        " · ".join(reason for reason in (degraded, placement_degraded) if reason),
    )
