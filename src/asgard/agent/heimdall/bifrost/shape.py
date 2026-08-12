"""오케스트레이션 형상 판정 — 신호 + 사용자가 고른 정책, 그리고 장부 없이도 도는 갈래.

`_by_policy` 를 갈아 끼우려면 이 모듈에 꽂아라. 장부(`ledger`)는 자기 이름으로 들고 있지
않고 `shape._by_policy` 로 부르므로, 여기 한 자리가 두 호출자를 다 덮는다."""

from __future__ import annotations

from ....orchestration import choose_shape


def _shape_why(decision: dict) -> str:
    """Run 에 적을 형상 사유 — 엇갈림과 내려앉음을 **따로** 붙인다.

    둘은 다른 축이다. `이견` 은 신호와 계획이 다른 답을 냈다는 뜻이고, `내려앉음` 은 사용자가
    고른 정책을 지금 형편으로 못 이뤘다는 뜻이다. 한 칸에 합치면 "닿는 엔진이 없다" 가 형상
    판정의 근거로 읽히고, 그러면 Run 의 이 한 줄이 왜 이 모양으로 돌았는지를 잘못 증언한다.
    """
    why = str(decision.get("why") or "")
    disagreement = str(decision.get("disagreement") or "")
    degraded = str(decision.get("degraded") or "")
    if disagreement:
        why = f"{why} · 이견: {disagreement}"
    return f"{why} · 내려앉음: {degraded}" if degraded else why


def _by_policy(root: str, signals: dict) -> dict | None:
    """사용자가 고른 오케스트레이션 정책까지 얹은 판정. 못 하면 None — 호출부가 신호만으로 간다.

    이 함수가 없으면 `asgard orchestrate` 로 고른 값은 **아무것도 안 한다**: 설정은 저장되는데
    실행 경로가 안 읽으니 화면만 바뀌고 도는 모양은 그대로다. 설정이 아무 일도 안 하는 것은
    설정이 없는 것보다 나쁘다 — 사람은 자기가 뭔가 바꿨다고 믿는다.

    엔진 목록은 **캐시만** 읽는다(`engines.cached`). 여기는 매 퀘스트가 지나는 뜨거운 길이라
    네트워크를 타면 그 값이 형상 판정에 얹혀서 모든 요청이 느려진다. 캐시가 비어 있으면 배치가
    비는 것이지 형상이 틀리는 것이 아니다 — 다시 재는 것은 사람이 `--probe` 로 시킬 때만 한다.

    통째로 fail-open 인 이유는 이 계층의 등급이다: 배차 장부는 Trinity 를 막지 않는다(이 파일의
    계약). 정책을 못 읽어서 퀘스트가 안 도는 것은 그 계약을 깨는 일이다.
    """
    try:
        from ....engines import cached
        from ....orchestration.policy import current, decide
    except Exception:
        return None
    try:
        selected, _ = current(root)
        try:
            live = cached(root)
        except Exception:
            live = []  # 엔진을 못 읽어도 형상은 고를 수 있다 — 배치만 비운다
        found = decide(root, engines=live, policy=selected, **signals)
        # `disagreement` 는 **신호와 계획이 엇갈렸다**는 뜻이고 그 칸의 주인은 여전히
        # `strategy` 다. 정책의 `degraded` 를 여기 밀어 넣으면 "닿는 엔진이 없다" 같은 배치
        # 사실이 형상 판정의 근거로 읽힌다 — 축이 둘인데 칸이 하나면 둘 다 못 읽는다.
        # 순수 함수라 한 번 더 불러도 값이 같고 모델 호출도 없다.
        signal_only = choose_shape(**signals)
    except Exception:
        return None
    return {
        "shape": found.shape,
        "why": found.why,
        "parallel": found.shape in ("graph", "squad"),
        "disagreement": signal_only["disagreement"] if found.shape == signal_only["shape"] else "",
        "degraded": found.degraded,
        "policy": found.policy,
        "placements": found.placements,
    }


class _NullLedgerShapeMixin:
    """비활성 장부도 형상은 고른다 — 판정이 순수 함수라 장부 없이도 답이 같다."""

    shape = ""
    placements: tuple = ()  # `choose_shape` 전에 읽는 자리가 있어도 안 터지게 — 빈 배치가 기본이다

    def choose_shape(
        self,
        cls: dict,
        *,
        unit_count: int = 0,
        specialists: list[str] | None = None,
        planned: bool = False,
    ) -> dict:
        signals = {
            "write_expected": bool(cls.get("write_expected", True)),
            "task_class": str(cls.get("task_class") or "deep"),
            "parallel_requested": bool(cls.get("parallel_requested")),
            "unit_count": unit_count,
            "specialists": list(specialists or []),
            "planned": planned,
        }
        # 장부가 안 선 경로(재개·테스트 대역)도 같은 정책을 지난다. 여기만 빼 두면 같은 저장소가
        # 어느 길로 들어왔느냐에 따라 다른 모양으로 돌고, 그건 설정이 반만 듣는다는 뜻이다.
        decision = _by_policy(getattr(self, "root", "") or ".", signals) or choose_shape(**signals)
        self.shape = decision["shape"]
        self.placements = tuple(decision.get("placements") or ())
        return decision
