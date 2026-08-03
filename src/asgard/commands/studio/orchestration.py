"""오케스트레이션 패널의 재료 — 창이 그릴 것을 JSON 으로 만든다. 화면 문장은 여기서 안 만든다.

두 갈래를 한 왕복에 담는다: 정책(현재 값·출처·고를 수 있는 목록) · 엔진 준비 상태. 둘 다
아직 없을 수 있는 엔진(`asgard.engines`·`orchestration.policy`)이라 못 읽으면 None 으로
적고 `missing` 에 이름을 남긴다 — 조용히 빼면 "고를 것이 없다"와 "못 읽었다"가 같은 화면이
된다. 튜터 패널(`studio.tutor`)과 같은 계약이다.

엔진 준비 상태는 두 속도로 읽는다. 화면 최초 렌더는 `engines.cached()` — 마지막으로 잰 것을
그대로 들어 절대 네트워크를 안 탄다. 강제 재점검(`force`)은 사용자가 '다시 확인'을 누를 때만
돈다 — 창을 열 때마다 probe 를 돌리면 설정 화면이 엔진 수만큼 느려진다.

이 모듈이 스스로 내리는 판정은 없다: 정책의 유효성은 `policy.set_policy` 가, 닿는지의 판정은
`engines.probe` 가 진다. 여기는 그 판정을 좌표·수·이름으로 꺼내 담을 뿐이다.
"""

from __future__ import annotations

from .. import loopback

_json_body = loopback.json_body

# 정책의 사람 뜻 — 화면이 목록 옆에 그대로 붙인다. 표면이 다시 쓰면 같은 정책이
# 창마다 다르게 설명된다(튜터의 KIND_LABEL 과 같은 규율). policy 모듈이 아직 없어도
# 목록은 공용 계약(ORCH_SPEC)의 고정 값이라 여기서 이름과 뜻을 함께 든다.
#
# 쌍둥이는 `commands/orchestrate.py` 의 POLICY_HELP 다. 문장이 같아야 한다 — 한동안 갈려서
# 같은 다섯 값이 창과 CLI 에서 다른 약속으로 읽혔다.
POLICY_LABEL = {
    "auto": "아스가르드가 형상과 배치를 스스로 정해요 — 지금 닿는 엔진만 후보로 써요",
    "solo": "엔진 하나로만 돌려요 — 역할을 나눠 맡기지 않아요",
    "graph": "갈래(그래프) 형상을 먼저 써요 — 배정 단위가 하나뿐이면 다른 형상으로 돌려요",
    "squad": "편대 형상을 먼저 써요 — 못 만들면 다른 형상으로 돌리고 이유를 남겨요",
    "off": "오케스트레이션을 쓰지 않아요 — 항상 곧장 실행해요",
}


def panel_state(root: str, force: bool = False) -> dict:
    """패널 한 판의 재료. `force` 는 엔진 재점검(네트워크를 탄다) — 사용자가 누를 때만 참이다."""
    policy = _policy_state(root)
    engines = _engine_state(root, force=force)
    return {
        "policy": policy,
        "engines": engines,
        # None 은 "못 읽었다"다 — 이름까지 적어야 화면이 그 칸을 "없음"이 아니라 "미장착"으로 그린다.
        "missing": [name for name, value in (("policy", policy), ("engines", engines)) if value is None],
        "labels": dict(POLICY_LABEL),
    }


def _policy_state(root: str) -> dict | None:
    """정책 칸 — 엔진(`orchestration.policy`)이 아직 없거나 죽으면 None.

    넓게 삼키는 이유는 튜터의 부채 계기와 같다: 이 칸은 관문이 아니라 계기다. 칸 하나가
    죽었다고 설정 화면이 통째로 비면 사용자는 칸이 아니라 창을 의심한다. 못 읽은 사실은
    None 으로 남아 `missing` 에 적히므로 실패가 화면에서 사라지지는 않는다.
    """
    try:
        from ...orchestration import policy

        current, source = policy.current(root)
        return {
            "current": current,
            "source": source,
            "default": policy.DEFAULT,
            "choices": list(policy.POLICIES),
        }
    except Exception:
        return None


def _engine_state(root: str, force: bool = False) -> list[dict] | None:
    """엔진 준비 상태 — 판정기(`asgard.engines`)가 아직 없거나 죽으면 None.

    기본은 `cached()` 다: 마지막으로 잰 것만 들어 네트워크를 안 탄다. probe 는 `force` 일 때만
    돈다 — probe 자체는 예외를 안 올리는 계약이지만(못 잰 엔진은 reachable=False + 이유),
    모듈이 없는 것은 probe 의 실패가 아니라 이 칸의 미장착이라 여기서 가른다.
    """
    try:
        from ... import engines

        rows = engines.probe(root, force=True) if force else engines.cached(root)
        return [
            {
                "name": row.name,
                "display": row.display,
                "configured": bool(row.configured),
                "reachable": bool(row.reachable),
                "detail": row.detail,
                "models": list(row.models),
                "checked": float(row.checked),
            }
            for row in rows
        ]
    except Exception:
        return None


def save_policy(payload: dict, root: str) -> tuple[int, str, bytes]:
    """정책 하나를 설정에 적는다. 적힌 뒤의 패널 재료까지 한 왕복에 돌려준다 — 창이 GET 을
    한 번 더 돌면 그 사이에 낀 남의 변경이 이 저장의 결과처럼 보인다."""
    value = str(payload.get("policy") or "").strip()
    scope = str(payload.get("scope") or "project")
    if not value:
        return _json_body(400, {"error": "정책 이름이 필요해요"})
    if scope not in ("global", "project"):
        return _json_body(400, {"error": "scope는 global 또는 project여야 해요"})
    try:
        from ...orchestration import policy

        # 속성까지 여기서 짚는다 — 모듈이 죽은 채 붙어 있으면(임포트는 되나 함수가 없으면)
        # 그것도 "저장할 자리가 없다"이지 서버 오류가 아니다.
        set_policy = policy.set_policy
    except Exception:
        return _json_body(503, {"error": "정책 엔진이 아직 없어요 — 저장할 자리가 없어요"})
    try:
        saved = set_policy(root, value, scope=scope)
    except ValueError as exc:
        return _json_body(400, {"error": str(exc)})
    return _json_body(200, {"saved": saved, "state": panel_state(root)})


def recheck_engines(payload: dict, root: str) -> tuple[int, str, bytes]:
    """엔진 전부를 강제로 다시 잰다 — '다시 확인' 버튼의 뒷면이라 여기만 네트워크를 탄다."""
    state = panel_state(root, force=True)
    if state["engines"] is None:
        return _json_body(503, {"error": "엔진 판정기가 아직 없어요 — 붙으면 여기서 다시 잴 수 있어요"})
    return _json_body(200, {"state": state})
